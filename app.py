"""FreshRSS Summary — FastAPI backend."""

import asyncio
import datetime
import hashlib
import json
import logging
import logging.config
import os
import secrets
import time
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel
from sqlalchemy import text as sa_text
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from config import CONFIG_PATH, DEFAULT_TOPICS, load_config
from db import (
    DEFAULT_DB_URL,
    add_pending_sync,
    add_snooze,
    clear_pending_sync,
    delete_snooze,
    get_bookmarked_ids,
    get_due_snoozes,
    get_engine,
    get_meta,
    get_pending_sync,
    get_scoring_config,
    get_user_hash,
    has_users,
    init_db,
    load_articles,
    load_for_rescore,
    load_read_articles,
    save_articles,
    set_articles_read,
    set_scoring_config,
    set_user_password,
    toggle_bookmark,
    upsert_user,
)
from freshrss_client import FreshRSSClient, article_from_row
from scorer import build_topics, score_articles
from telegram_digest import check_trending, register_webhook, send_digest, send_snooze_reminders

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

_prom_articles = Gauge("freshrss_articles_total", "Articles currently in cache")
_prom_last_refresh = Gauge(
    "freshrss_last_refresh_timestamp_seconds", "Unix timestamp of last successful refresh"
)
_prom_refreshes = Counter("freshrss_refreshes_total", "Successful refreshes since startup")
_prom_refresh_dur = Histogram(
    "freshrss_refresh_duration_seconds",
    "Refresh duration in seconds",
    buckets=[2, 5, 15, 30, 60, 120, 300],
)
_prom_topic_articles = Gauge("freshrss_articles_by_topic", "Articles per topic in cache", ["topic"])


def _update_prom_cache() -> None:
    """Sync Prometheus gauges from current cache state."""
    _prom_articles.set(len(cache.articles))
    if cache.last_refresh:
        _prom_last_refresh.set(cache.last_refresh)
    topic_counts: dict[str, int] = {}
    for a in cache.articles:
        for t in a.get("matched_topics", {}):
            topic_counts[t] = topic_counts.get(t, 0) + 1
    for topic, count in topic_counts.items():
        _prom_topic_articles.labels(topic=topic).set(count)


LOG_FMT = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
LOG_DATE = "%Y-%m-%d %H:%M:%S"

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": LOG_FMT, "datefmt": LOG_DATE},
    },
    "handlers": {
        "default": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": "ext://sys.stdout",
        },
    },
    "root": {"level": "INFO", "handlers": ["default"]},
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.access": {"handlers": ["default"], "level": "INFO", "propagate": False},
    },
}

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------


class Cache:
    def __init__(self):
        self.articles: list[dict] = []
        self.all_topics: list[str] = []
        self.total_fetched: int = 0
        self.last_refresh: float | None = None
        self.is_loading: bool = False
        self.load_progress: str = ""
        self.error: str | None = None
        self.refresh_task: asyncio.Task | None = None
        self.trending_alerted: set[tuple[str, int]] = set()

    def populate(
        self, articles: list[dict], last_refresh: float | None, total_fetched: int
    ) -> None:
        self.articles = articles
        self.last_refresh = last_refresh
        self.total_fetched = total_fetched
        self.all_topics = sorted({t for a in articles for t in a["matched_topics"]})


cache = Cache()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Password hashing (stdlib scrypt — no extra deps)
# ---------------------------------------------------------------------------


def hash_password(plain: str) -> str:
    """Hash a plaintext password with scrypt. Returns 'salt_hex:hash_hex'."""
    salt = os.urandom(16)
    key = hashlib.scrypt(plain.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ":" + key.hex()


def verify_password(plain: str, stored: str) -> bool:
    """Verify a plaintext password against a stored 'salt_hex:hash_hex' string."""
    try:
        salt_hex, key_hex = stored.split(":", 1)
        key = hashlib.scrypt(plain.encode(), salt=bytes.fromhex(salt_hex), n=16384, r=8, p=1)
        return key.hex() == key_hex
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Admin user initialisation
# ---------------------------------------------------------------------------


async def init_admin_user() -> None:
    """
    Ensure at least one user exists in DB.

    - If ADMIN_PASSWORD env var is set: upsert admin with that password (useful
      for Docker secrets / initial deploy / password reset).
    - Else if DB has no users: generate a random password, store it, log it.
    """
    admin_username = os.environ.get("ADMIN_USERNAME", "admin")
    admin_password = os.environ.get("ADMIN_PASSWORD")

    if admin_password:
        await upsert_user(admin_username, hash_password(admin_password))
        logger.info("Admin user '%s' password applied from ADMIN_PASSWORD env var", admin_username)
    elif not await has_users():
        admin_password = secrets.token_urlsafe(16)
        await upsert_user(admin_username, hash_password(admin_password))
        sep = "=" * 56
        logger.warning(sep)
        logger.warning("  FIRST RUN — admin account created")
        logger.warning("  Username : %s", admin_username)
        logger.warning("  Password : %s", admin_password)
        logger.warning("  Set ADMIN_PASSWORD env var to override on restart")
        logger.warning(sep)


def _get_secret_key() -> str:
    """Return secret key for session signing. Precedence: env > config > random (warns)."""
    if v := os.environ.get("SECRET_KEY"):
        return v
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open() as f:
            cfg = yaml.safe_load(f) or {}
        if sk := cfg.get("auth", {}).get("secret_key"):
            return sk
    # No key configured: derive a stable key from the config path so sessions
    # survive restarts, but document that this is not cryptographically ideal.
    logger.warning(
        "No SECRET_KEY configured — session key derived from config path. "
        "Set auth.secret_key in config.yaml or SECRET_KEY env var for production."
    )
    return hashlib.sha256(str(CONFIG_PATH.resolve()).encode()).hexdigest()


def require_auth(request: Request) -> None:
    """FastAPI dependency: raises 401 if the request has no valid session."""
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=401, detail="Authentication required")


# ---------------------------------------------------------------------------
# App lifespan: init DB and warm cache from persisted data
# ---------------------------------------------------------------------------


async def _setup_telegram_scheduler(scheduler: AsyncIOScheduler, tg_cfg: dict, cfg: dict) -> None:
    """Register all Telegram-related scheduler jobs and webhook."""
    hour = int(tg_cfg.get("digest_hour", 21))
    scheduler.add_job(
        _run_daily_digest,
        CronTrigger(hour=hour, minute=0, timezone="Europe/Paris"),
        args=[tg_cfg],
        id="daily_digest",
        max_instances=1,
        coalesce=True,
    )
    logger.info("Telegram digest scheduled at %02dh00 Europe/Paris", hour)
    scheduler.add_job(
        _check_trending,
        "interval",
        hours=1,
        args=[tg_cfg],
        id="trending_check",
        max_instances=1,
        coalesce=True,
    )
    logger.info("Trending topic checker scheduled: every 1h")
    scheduler.add_job(
        _check_snoozes,
        "interval",
        minutes=15,
        args=[tg_cfg],
        id="snooze_check",
        max_instances=1,
        coalesce=True,
    )
    logger.info("Snooze checker scheduled: every 15min")
    public_url = cfg.get("server", {}).get("public_url", "")
    if public_url:
        await register_webhook(tg_cfg, public_url)
    else:
        logger.info(
            "Telegram: set server.public_url (or PUBLIC_URL env var) to auto-register webhook"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config()
    db_url = cfg.get("database", {}).get("url", DEFAULT_DB_URL)
    await init_db(db_url)
    await init_admin_user()
    articles, last_refresh, total_fetched = await load_articles()
    if articles:
        cache.populate(articles, last_refresh, total_fetched)
        logger.info(
            "Cache warmed from DB: %d articles (last refresh: %s)",
            len(articles),
            time.strftime("%Y-%m-%d %H:%M", time.localtime(last_refresh))
            if last_refresh
            else "never",
        )
    _update_prom_cache()

    scheduler: AsyncIOScheduler | None = None
    interval = int(cfg.get("scheduler", {}).get("interval_minutes", 0))
    if interval > 0:
        scheduler = AsyncIOScheduler(timezone="UTC")
        scheduler.add_job(
            _auto_refresh,
            "interval",
            minutes=interval,
            id="auto_refresh",
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
        logger.info("Auto-refresh scheduler started: every %d min", interval)

    tg_cfg = cfg.get("telegram", {})
    if tg_cfg.get("bot_token") and tg_cfg.get("chat_id"):
        if scheduler is None:
            scheduler = AsyncIOScheduler(timezone="UTC")
            scheduler.start()
        await _setup_telegram_scheduler(scheduler, tg_cfg, cfg)

    app.state.tg_cfg = tg_cfg

    yield

    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(title="FreshRSS Summary", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(SessionMiddleware, secret_key=_get_secret_key())
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("authenticated"):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(request, "login.html")


@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    stored_hash = await get_user_hash(username)
    if stored_hash and verify_password(password, stored_hash):
        request.session["authenticated"] = True
        request.session["username"] = username
        next_url = request.query_params.get("next", "/")
        return RedirectResponse(url=next_url, status_code=303)

    return templates.TemplateResponse(
        request, "login.html", {"error": "Identifiants invalides"}, status_code=401
    )


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/api/me")
async def me(request: Request) -> dict[str, Any]:
    auth = request.session.get("authenticated", False)
    return {
        "authenticated": bool(auth),
        "username": request.session.get("username") if auth else None,
    }


@app.get("/api/status", dependencies=[Depends(require_auth)])
async def get_status() -> dict[str, Any]:
    return {
        "is_loading": cache.is_loading,
        "load_progress": cache.load_progress,
        "error": cache.error,
        "total_fetched": cache.total_fetched,
        "article_count": len(cache.articles),
        "last_refresh": cache.last_refresh,
        "all_topics": cache.all_topics,
    }


@app.get("/api/articles", dependencies=[Depends(require_auth)])
async def get_articles(
    topic: str | None = None,
    min_score: float | None = None,
    sort: str = "score",
    limit: int = 1000,
    offset: int = 0,
    days: int = 7,
    show_read: bool = False,
) -> dict[str, Any]:
    articles = cache.articles

    if days > 0:
        cutoff = int(time.time()) - days * 86400
        articles = [a for a in articles if (a["published"] or 0) >= cutoff]

    if topic:
        articles = [a for a in articles if topic in a.get("matched_topics", {})]

    if min_score is not None:
        articles = [a for a in articles if a["score"] >= min_score]

    if show_read:
        read_articles = await load_read_articles(days=days)
        articles = articles + read_articles

    if sort == "score":
        articles = sorted(articles, key=lambda a: a["score"], reverse=True)
    elif sort == "date":
        articles = sorted(articles, key=lambda a: a["published"], reverse=True)
    elif sort == "feed":
        articles = sorted(articles, key=lambda a: a["feed_title"])

    total = len(articles)
    page = articles[offset : offset + limit]

    return {"total": total, "articles": page}


class MarkReadRequest(BaseModel):
    article_ids: list[str]


async def _get_or_init_scoring_config() -> dict:
    stored = await get_scoring_config()
    if stored is not None:
        return stored
    cfg = load_config()
    topics = cfg.get("topics") or DEFAULT_TOPICS
    await set_scoring_config(topics)
    return topics


@app.post("/api/mark-read", dependencies=[Depends(require_auth)])
async def mark_read(req: MarkReadRequest) -> dict[str, str]:
    if not req.article_ids:
        raise HTTPException(status_code=400, detail="No article IDs provided")

    # Local state updated immediately — never blocked by upstream availability
    ids_set = set(req.article_ids)
    cache.articles = [a for a in cache.articles if a["id"] not in ids_set]
    await set_articles_read(req.article_ids)

    # Best-effort upstream sync; queue for retry if FreshRSS is unreachable
    try:

        def _sync_mark_read() -> None:
            fr = load_config()["freshrss"]
            with FreshRSSClient(fr["url"], fr["username"], fr["api_password"]) as c:
                c.mark_as_read(req.article_ids)

        await asyncio.to_thread(_sync_mark_read)
    except Exception:
        logger.warning(
            "FreshRSS unreachable — queuing %d article(s) for deferred sync", len(req.article_ids)
        )
        await add_pending_sync(req.article_ids)
        return {"status": "queued", "marked": str(len(req.article_ids))}

    return {"status": "ok", "marked": str(len(req.article_ids))}


def _fetch_and_score_iter(cfg: dict, topics_cfg: dict) -> Iterator[tuple[list[dict], int]]:
    """
    Generator: fetch unread articles in batches, score each, yield (scored_batch, cumulative_count).
    Runs in a thread pool (blocking I/O). Callers decide whether to stream or accumulate.
    """
    fr_cfg = cfg["freshrss"]
    fetch_cfg = cfg.get("fetch", {})
    scoring_cfg = cfg.get("scoring", {})
    batch_size = int(fetch_cfg.get("batch_size", 1000))
    max_batches = int(fetch_cfg.get("max_batches", 10))
    title_weight = int(scoring_cfg.get("title_weight", 3))
    min_score = float(scoring_cfg.get("min_score", 1.0))
    topics = build_topics(topics_cfg)
    total_fetched = 0

    with FreshRSSClient(fr_cfg["url"], fr_cfg["username"], fr_cfg["api_password"]) as client:
        for batch in client.fetch_unread(batch_size=batch_size, max_batches=max_batches):
            total_fetched += len(batch)
            scored = [
                sa.to_dict()
                for sa in score_articles(
                    batch, topics, title_weight=title_weight, min_score=min_score
                )
            ]
            yield scored, total_fetched


def _blocking_fetch_and_score(cfg: dict, topics_cfg: dict) -> tuple[list[dict], int]:
    """Blocking fetch + score — runs in a thread pool via asyncio.to_thread."""
    all_articles: list[dict] = []
    total_fetched = 0

    for scored_batch, total_fetched in _fetch_and_score_iter(cfg, topics_cfg):
        cache.load_progress = f"Récupération : {total_fetched} articles..."
        all_articles.extend(scored_batch)

    if total_fetched == 0:
        logger.warning("No articles fetched from FreshRSS — DB not modified")
        return [], 0

    return all_articles, total_fetched


async def _auto_refresh() -> None:
    """Scheduled job: runs _run_refresh unless a refresh is already in progress."""
    if cache.is_loading:
        logger.info("Scheduled refresh skipped — already in progress")
        return
    logger.info("Scheduled refresh starting")
    await _run_refresh()


async def _run_refresh() -> None:
    """Background task: fetch → score → persist → populate cache."""
    cache.is_loading = True
    cache.error = None
    cache.load_progress = "Démarrage..."
    _t0 = time.perf_counter()

    try:
        cfg = load_config()
        topics_cfg = await _get_or_init_scoring_config()

        # Drain outbox: replay mark-as-read calls that failed when FreshRSS was offline
        pending = await get_pending_sync()
        if pending:
            try:

                def _sync_pending() -> None:
                    fr = load_config()["freshrss"]
                    with FreshRSSClient(fr["url"], fr["username"], fr["api_password"]) as c:
                        c.mark_as_read(pending)

                await asyncio.to_thread(_sync_pending)
                await clear_pending_sync(pending)
                logger.info("Flushed %d pending read sync(s) to FreshRSS", len(pending))
            except Exception:
                logger.warning("Pending sync flush failed, will retry on next refresh")

        article_dicts, total_fetched = await asyncio.to_thread(
            _blocking_fetch_and_score, cfg, topics_cfg
        )
        if total_fetched == 0:
            cache.load_progress = "Aucun article non lu récupéré — DB inchangée"
            logger.info("Refresh complete: 0 articles fetched, cache unchanged")
        else:
            cache.load_progress = "Sauvegarde..."
            await save_articles(article_dicts, total_fetched)
            cache.populate(article_dicts, time.time(), total_fetched)
            cache.load_progress = "Terminé"
            _prom_refreshes.inc()
            _prom_refresh_dur.observe(time.perf_counter() - _t0)
            _update_prom_cache()
            logger.info(
                "Refresh complete: %d fetched, %d relevant", total_fetched, len(article_dicts)
            )
    except Exception as e:
        cache.error = str(e)
        cache.load_progress = "Erreur"
        logger.exception("Refresh failed")
    finally:
        cache.is_loading = False


@app.post("/api/refresh", dependencies=[Depends(require_auth)])
async def refresh() -> dict[str, Any]:
    """Start async refresh. Returns immediately; poll /api/status for progress."""
    if cache.is_loading:
        return {"status": "already_loading", "progress": cache.load_progress}

    cache.refresh_task = asyncio.create_task(_run_refresh())
    return {"status": "started"}


@app.get("/api/refresh/stream", dependencies=[Depends(require_auth)])
async def refresh_stream() -> StreamingResponse:
    """SSE: fetch → score per batch → stream each scored article as it arrives."""
    if cache.is_loading:

        async def _busy():
            yield f"data: {json.dumps({'type': 'busy'})}\n\n"

        return StreamingResponse(
            _busy(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    def _put(event: dict) -> None:
        loop.call_soon_threadsafe(q.put_nowait, event)

    def _worker(topics_cfg: dict) -> None:
        cfg = load_config()
        all_articles: list[dict] = []
        total_fetched = 0

        try:
            for scored_batch, total_fetched in _fetch_and_score_iter(cfg, topics_cfg):
                _put({"type": "progress", "message": f"Récupération : {total_fetched} articles..."})
                for d in scored_batch:
                    all_articles.append(d)
                    _put({"type": "article", "article": d})

            if total_fetched == 0:
                logger.warning("Stream refresh: 0 articles fetched — DB not modified")

            _put({"type": "done", "total_fetched": total_fetched, "count": len(all_articles)})
        except Exception as e:
            logger.exception("refresh-stream worker failed")
            _put({"type": "error", "message": str(e)})

    async def _event_gen():
        cache.is_loading = True
        cache.error = None
        cache.load_progress = "Démarrage..."
        all_articles: list[dict] = []
        total_fetched = 0
        _t0 = time.perf_counter()

        topics_cfg = await _get_or_init_scoring_config()
        asyncio.create_task(asyncio.to_thread(_worker, topics_cfg))
        try:
            while True:
                event = await q.get()
                if event["type"] == "article":
                    all_articles.append(event["article"])
                elif event["type"] == "progress":
                    cache.load_progress = event["message"]
                elif event["type"] == "done":
                    total_fetched = event["total_fetched"]
                    if total_fetched > 0:
                        cache.load_progress = "Sauvegarde..."
                        await save_articles(all_articles, total_fetched)
                        bookmarked = await get_bookmarked_ids()
                        for a in all_articles:
                            a["bookmarked"] = a["id"] in bookmarked
                        cache.populate(all_articles, time.time(), total_fetched)
                        _prom_refreshes.inc()
                        _prom_refresh_dur.observe(time.perf_counter() - _t0)
                        _update_prom_cache()
                    cache.load_progress = "Terminé"
                    logger.info(
                        "Stream refresh done: %d fetched, %d relevant",
                        total_fetched,
                        len(all_articles),
                    )
                elif event["type"] == "error":
                    cache.error = event["message"]
                    cache.load_progress = "Erreur"

                yield f"data: {json.dumps(event)}\n\n"

                if event["type"] in ("done", "error"):
                    break
        except asyncio.CancelledError:
            pass
        finally:
            cache.is_loading = False

    return StreamingResponse(
        _event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _blocking_rescore_compute(raw: list[dict], cfg: dict, topics_cfg: dict) -> list[dict]:
    """CPU re-scoring of cached articles. Updates cache.load_progress for progress reporting. Runs in a thread pool via asyncio.to_thread."""
    scoring_cfg = cfg.get("scoring", {})
    title_weight = int(scoring_cfg.get("title_weight", 3))
    min_score = float(scoring_cfg.get("min_score", 1.0))
    topics = build_topics(topics_cfg)

    cache.load_progress = f"Re-scoring {len(raw)} articles..."
    articles = [article_from_row(r) for r in raw]
    return [
        a.to_dict()
        for a in score_articles(articles, topics, title_weight=title_weight, min_score=min_score)
    ]


async def _run_rescore() -> None:
    """Background task: rescore from DB → persist → populate cache."""
    cache.is_loading = True
    cache.error = None
    cache.load_progress = "Démarrage du re-scoring..."

    try:
        raw = await load_for_rescore()
        cfg = load_config()
        topics_cfg = await _get_or_init_scoring_config()
        article_dicts = await asyncio.to_thread(_blocking_rescore_compute, raw, cfg, topics_cfg)
        total_fetched = int(await get_meta("total_fetched", "0"))
        cache.load_progress = "Sauvegarde..."
        await save_articles(article_dicts, total_fetched)
        bookmarked = await get_bookmarked_ids()
        for a in article_dicts:
            a["bookmarked"] = a["id"] in bookmarked
        cache.populate(article_dicts, cache.last_refresh, total_fetched)
        _update_prom_cache()
        cache.load_progress = "Terminé"
        logger.info("Rescore complete: %d relevant articles", len(article_dicts))
    except Exception as e:
        cache.error = str(e)
        cache.load_progress = "Erreur"
        logger.exception("Rescore failed")
    finally:
        cache.is_loading = False


@app.post("/api/rescore", dependencies=[Depends(require_auth)])
async def rescore() -> dict[str, Any]:
    """Re-score cached articles with current config. No FreshRSS fetch."""
    if cache.is_loading:
        return {"status": "already_loading", "progress": cache.load_progress}

    if not cache.articles and not await load_for_rescore():
        raise HTTPException(
            status_code=400, detail="Aucun article en DB. Lance d'abord un Rafraîchir."
        )

    cache.refresh_task = asyncio.create_task(_run_rescore())
    return {"status": "started"}


class BookmarkRequest(BaseModel):
    article_id: str


@app.post("/api/bookmark", dependencies=[Depends(require_auth)])
async def bookmark(req: BookmarkRequest) -> dict[str, Any]:
    """Toggle bookmark for an article. Returns new bookmark state."""
    if not any(a["id"] == req.article_id for a in cache.articles):
        raise HTTPException(status_code=404, detail="Article not found")

    is_bookmarked = await toggle_bookmark(req.article_id)

    for a in cache.articles:
        if a["id"] == req.article_id:
            a["bookmarked"] = is_bookmarked
            break

    return {"bookmarked": is_bookmarked}


# ---------------------------------------------------------------------------
# Snooze
# ---------------------------------------------------------------------------


class SnoozeRequest(BaseModel):
    article_id: str
    snooze_until: int | None = None  # Unix timestamp; default = tomorrow 08:00 local


@app.post("/api/snooze", dependencies=[Depends(require_auth)])
async def snooze_article(req: SnoozeRequest, request: Request) -> dict[str, Any]:
    """Schedule a Telegram reminder for an article."""
    article = next((a for a in cache.articles if a["id"] == req.article_id), None)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    tg_cfg: dict = getattr(request.app.state, "tg_cfg", {})
    if not tg_cfg.get("bot_token") or not tg_cfg.get("chat_id"):
        raise HTTPException(status_code=400, detail="Telegram not configured")

    if req.snooze_until is not None:
        snooze_until = req.snooze_until
    else:
        tomorrow = datetime.date.today() + datetime.timedelta(days=1)
        snooze_until = int(datetime.datetime.combine(tomorrow, datetime.time(8, 0)).timestamp())

    await add_snooze(
        req.article_id,
        tg_cfg["chat_id"],
        snooze_until,
        article["title"],
        article["url"],
    )
    return {"status": "ok", "snooze_until": snooze_until}


# ---------------------------------------------------------------------------
# Scoring config
# ---------------------------------------------------------------------------


@app.get("/api/config/scoring", dependencies=[Depends(require_auth)])
async def get_scoring() -> dict[str, Any]:
    """Return the active scoring topics config (from DB, or seeded from config.yaml)."""
    return {"topics": await _get_or_init_scoring_config()}


class ScoringConfigRequest(BaseModel):
    topics: dict[str, Any]


@app.put("/api/config/scoring", dependencies=[Depends(require_auth)])
async def update_scoring(req: ScoringConfigRequest) -> dict[str, str]:
    """Persist a new scoring config to DB. Takes effect on next refresh or rescore."""
    await set_scoring_config(req.topics)
    logger.info("Scoring config updated: %d topics", len(req.topics))
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Password change
# ---------------------------------------------------------------------------


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@app.post("/api/change-password", dependencies=[Depends(require_auth)])
async def change_password(req: ChangePasswordRequest, request: Request) -> dict[str, str]:
    """Change the password of the currently authenticated user."""
    username = request.session.get("username", os.environ.get("ADMIN_USERNAME", "admin"))
    stored_hash = await get_user_hash(username)
    if not stored_hash or not verify_password(req.current_password, stored_hash):
        raise HTTPException(status_code=400, detail="current_password_wrong")
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="password_too_short")
    await set_user_password(username, hash_password(req.new_password))
    logger.info("Password changed for user '%s'", username)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Health & metrics
# ---------------------------------------------------------------------------


async def _run_daily_digest(tg_cfg: dict) -> None:
    """Scheduler job: build and send digest from current cache articles."""
    await send_digest(tg_cfg, cache.articles)


async def _check_trending(tg_cfg: dict) -> None:
    """Scheduler job: alert if a topic is surging in the last 2h."""
    cache.trending_alerted = await check_trending(tg_cfg, cache.articles, cache.trending_alerted)


async def _check_snoozes(tg_cfg: dict) -> None:
    """Scheduler job: deliver due snooze reminders and remove them from DB."""
    due = await get_due_snoozes()
    if not due:
        return
    sent = await send_snooze_reminders(tg_cfg, due)
    for article_id in sent:
        await delete_snooze(article_id)


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> dict:
    """Receive Telegram updates. Verifies secret header, handles /digest command."""
    tg_cfg: dict = getattr(request.app.state, "tg_cfg", {})
    webhook_secret = tg_cfg.get("webhook_secret", "")
    if not webhook_secret:
        raise HTTPException(status_code=404)

    header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not secrets.compare_digest(header_secret, webhook_secret):
        raise HTTPException(status_code=403, detail="Invalid secret")

    body = await request.json()
    text: str = body.get("message", {}).get("text", "")
    if text.startswith("/digest"):
        asyncio.create_task(send_digest(tg_cfg, cache.articles))

    return {}


@app.get("/health")
async def health() -> JSONResponse:
    """Liveness/readiness probe. No auth required."""
    db_status = "ok"
    try:
        async with get_engine().connect() as conn:
            await conn.execute(sa_text("SELECT 1"))
    except Exception as exc:
        db_status = f"error: {exc}"

    status = "ok" if db_status == "ok" else "degraded"
    payload = {
        "status": status,
        "db": db_status,
        "articles": len(cache.articles),
        "last_refresh": (
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(cache.last_refresh))
            if cache.last_refresh
            else None
        ),
        "is_loading": cache.is_loading,
    }
    return JSONResponse(content=payload, status_code=200 if status == "ok" else 503)


@app.get("/metrics", dependencies=[Depends(require_auth)])
async def metrics() -> Response:
    """Prometheus metrics scrape endpoint. Requires authentication."""
    _update_prom_cache()
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    cfg = load_config()
    srv = cfg.get("server", {})

    reload = bool(srv.get("reload", False))
    uvicorn.run(
        # String form required for --reload (uvicorn needs to reimport the module).
        # Object form used otherwise to avoid double-import of module-level code
        # (e.g. Prometheus metric registration).
        "app:app" if reload else app,
        host=str(srv.get("host", "0.0.0.0")),
        port=int(srv.get("port", 8123)),
        reload=reload,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_config=LOGGING_CONFIG,
    )
