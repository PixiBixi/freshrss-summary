"""FreshRSS Summary — FastAPI backend."""

import asyncio
import datetime
import json
import logging
import logging.config
import os
import secrets
import time
import zoneinfo
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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

from auth import (
    get_secret_key,
    hash_password,
    init_admin_user,
    login_rate_limit,
    require_auth,
    verify_password,
)
from config import load_config
from db import (
    DEFAULT_DB_URL,
    add_pending_sync,
    add_snooze,
    clear_pending_sync,
    delete_snooze,
    get_all_feed_titles,
    get_bookmarked_ids,
    get_due_snoozes,
    get_engine,
    get_feed_weights,
    get_meta,
    get_pending_sync,
    get_user_hash,
    init_db,
    load_articles,
    load_for_rescore,
    load_read_articles,
    save_articles,
    set_articles_read,
    set_feed_weights,
    set_scoring_config,
    set_user_password,
    toggle_bookmark,
)
from freshrss_client import FreshRSSClient
from models import ArticleDict
from pipeline import fetch_and_score_iter, rescore_articles
from scorer import build_topics
from telegram_digest import (
    TelegramConfig,
    check_trending,
    register_webhook,
    send_digest,
    send_snooze_reminders,
)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------


@dataclass
class _Metrics:
    articles: Gauge
    last_refresh: Gauge
    refreshes: Counter
    refresh_dur: Histogram
    topic_articles: Gauge


_metrics: _Metrics | None = None


def _get_metrics() -> _Metrics:
    """Return the shared Prometheus metrics singleton, creating it lazily on first call."""
    global _metrics
    if _metrics is not None:
        return _metrics

    def _get_or_register_metric(name, factory):  # type: ignore[no-untyped-def]
        try:
            return factory()
        except ValueError:
            from prometheus_client import REGISTRY

            return REGISTRY._names_to_collectors[name]  # type: ignore[attr-defined]

    _metrics = _Metrics(
        articles=_get_or_register_metric(
            "freshrss_articles_total",
            lambda: Gauge("freshrss_articles_total", "Articles currently in cache"),
        ),
        last_refresh=_get_or_register_metric(
            "freshrss_last_refresh_timestamp_seconds",
            lambda: Gauge(
                "freshrss_last_refresh_timestamp_seconds",
                "Unix timestamp of last successful refresh",
            ),
        ),
        refreshes=_get_or_register_metric(
            "freshrss_refreshes_total",
            lambda: Counter("freshrss_refreshes_total", "Successful refreshes since startup"),
        ),
        refresh_dur=_get_or_register_metric(
            "freshrss_refresh_duration_seconds",
            lambda: Histogram(
                "freshrss_refresh_duration_seconds",
                "Refresh duration in seconds",
                buckets=[2, 5, 15, 30, 60, 120, 300],
            ),
        ),
        topic_articles=_get_or_register_metric(
            "freshrss_articles_by_topic",
            lambda: Gauge("freshrss_articles_by_topic", "Articles per topic in cache", ["topic"]),
        ),
    )
    return _metrics


def _update_prom_cache() -> None:
    """Sync Prometheus gauges from current cache state."""
    m = _get_metrics()
    m.articles.set(len(cache.articles))
    if cache.last_refresh:
        m.last_refresh.set(cache.last_refresh)
    topic_counts: dict[str, int] = {}
    for a in cache.articles:
        for t in a.get("matched_topics", {}):
            topic_counts[t] = topic_counts.get(t, 0) + 1
    for topic, count in topic_counts.items():
        m.topic_articles.labels(topic=topic).set(count)


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
        self.articles: list[ArticleDict] = []
        self.all_topics: list[str] = []
        self.total_fetched: int = 0
        self.last_refresh: float | None = None
        self.is_loading: bool = False
        self.initialized: bool = False  # True after first populate() completes post-lifespan
        self.load_progress: str = ""
        self.error: str | None = None
        self.refresh_task: asyncio.Task | None = None
        self.trending_alerted: set[tuple[str, int]] = set()

    def populate(
        self, articles: list[dict[str, Any]], last_refresh: float | None, total_fetched: int
    ) -> None:
        self.articles = articles
        self.last_refresh = last_refresh
        self.total_fetched = total_fetched
        self.all_topics = sorted({t for a in articles for t in a["matched_topics"]})
        self.initialized = True


cache = Cache()


# ---------------------------------------------------------------------------
# App lifespan: init DB and warm cache from persisted data
# ---------------------------------------------------------------------------


async def _run_every(
    coro_fn: Callable[..., Coroutine], interval_seconds: float, *args: Any
) -> None:
    """Run coro_fn(*args) at fixed intervals, swallowing non-cancellation exceptions."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await coro_fn(*args)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduled task %s failed", coro_fn.__name__)


async def _run_daily_at(
    coro_fn: Callable[..., Coroutine], hour: int, tz_name: str, *args: Any
) -> None:
    """Run coro_fn(*args) once per day at the given hour in tz_name timezone."""
    tz = zoneinfo.ZoneInfo(tz_name)
    while True:
        now = datetime.datetime.now(tz)
        next_run = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += datetime.timedelta(days=1)
        await asyncio.sleep((next_run - now).total_seconds())
        try:
            await coro_fn(*args)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Daily task %s failed", coro_fn.__name__)


async def _setup_telegram_tasks(
    bg_tasks: list[asyncio.Task], tg_cfg: TelegramConfig, cfg: dict[str, Any]
) -> None:
    """Spawn asyncio background tasks for all Telegram-related periodic jobs."""
    hour = int(cfg.get("telegram", {}).get("digest_hour", 21))
    bg_tasks.append(
        asyncio.create_task(_run_daily_at(_dispatch_daily_digest, hour, "Europe/Paris", tg_cfg))
    )
    logger.info("Telegram digest scheduled at %02dh00 Europe/Paris", hour)
    bg_tasks.append(asyncio.create_task(_run_every(_check_trending, 3600, tg_cfg)))
    logger.info("Trending topic checker scheduled: every 1h")
    bg_tasks.append(asyncio.create_task(_run_every(_check_snoozes, 900, tg_cfg)))
    logger.info("Snooze checker scheduled: every 15min")
    public_url = cfg.get("server", {}).get("public_url", "")
    if public_url:
        await register_webhook(tg_cfg, public_url)
    else:
        logger.info(
            "Telegram: set server.public_url (or PUBLIC_URL env var) to auto-register webhook"
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
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

    bg_tasks: list[asyncio.Task] = []
    interval = int(cfg.get("scheduler", {}).get("interval_minutes", 0))
    if interval > 0:
        bg_tasks.append(asyncio.create_task(_run_every(_auto_refresh, interval * 60)))
        logger.info("Auto-refresh scheduler started: every %d min", interval)

    tg_cfg = TelegramConfig.from_dict(cfg.get("telegram", {}))
    if tg_cfg.is_configured():
        await _setup_telegram_tasks(bg_tasks, tg_cfg, cfg)

    app.state.tg_cfg = tg_cfg

    yield

    for task in bg_tasks:
        task.cancel()
    await asyncio.gather(*bg_tasks, return_exceptions=True)


class _LazySessionMiddleware(SessionMiddleware):
    """Read the session secret lazily when the middleware stack is first built, not at import time."""

    def __init__(self, app: Any) -> None:
        super().__init__(app, secret_key=get_secret_key())


app = FastAPI(title="FreshRSS Summary", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(_LazySessionMiddleware)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "authenticated": bool(request.session.get("authenticated")),
            "username": request.session.get("username", ""),
        },
    )


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> Response:
    if request.session.get("authenticated"):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(request, "login.html")


@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
) -> Response:
    ip = request.client.host if request.client else "unknown"
    if not login_rate_limit(ip):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Trop de tentatives. Réessayez dans une minute."},
            status_code=429,
        )

    stored_hash = await get_user_hash(username)
    if stored_hash and verify_password(password, stored_hash):
        request.session.clear()
        request.session["authenticated"] = True
        request.session["username"] = username
        next_url = request.query_params.get("next", "/")
        return RedirectResponse(url=next_url, status_code=303)

    return templates.TemplateResponse(
        request, "login.html", {"error": "Identifiants invalides"}, status_code=401
    )


@app.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/api/status")
async def get_status() -> dict[str, Any]:
    return {
        "is_loading": cache.is_loading,
        "initialized": cache.initialized,
        "load_progress": cache.load_progress,
        "error": cache.error,
        "total_fetched": cache.total_fetched,
        "article_count": len(cache.articles),
        "last_refresh": cache.last_refresh,
        "all_topics": cache.all_topics,
    }


@app.get("/api/articles")
async def get_articles(
    request: Request,
    topic: str | None = None,
    min_score: float | None = None,
    sort: str = "score",
    limit: int = 1000,
    offset: int = 0,
    days: int = 7,
    show_read: bool = False,
) -> dict[str, Any]:
    if not cache.initialized:
        raise HTTPException(status_code=503, detail="Cache initializing — try again shortly")
    if show_read and not request.session.get("authenticated"):
        show_read = False
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


async def _get_or_seed_scoring_config() -> dict[str, Any]:
    from db import get_or_seed_scoring_config
    from scorer import DEFAULT_TOPICS

    return await get_or_seed_scoring_config(load_config(), DEFAULT_TOPICS)


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
        logger.exception(
            "FreshRSS unreachable — queuing %d article(s) for deferred sync", len(req.article_ids)
        )
        await add_pending_sync(req.article_ids)
        return {"status": "queued", "marked": str(len(req.article_ids))}

    return {"status": "ok", "marked": str(len(req.article_ids))}


def _blocking_fetch_and_score(
    cfg: dict[str, Any],
    topics_cfg: dict[str, Any],
    feed_weights: dict[str, float] | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Blocking fetch + score — runs in a thread pool via asyncio.to_thread."""
    all_articles: list[dict[str, Any]] = []
    total_fetched = 0

    topics = build_topics(topics_cfg)
    for scored_batch, total_fetched in fetch_and_score_iter(cfg, topics, feed_weights):
        if on_progress:
            on_progress(f"Récupération : {total_fetched} articles...")
        all_articles.extend(scored_batch)

    if total_fetched == 0:
        logger.warning("No articles fetched from FreshRSS — DB not modified")
        return [], 0

    return all_articles, total_fetched


async def _auto_refresh() -> None:
    """Scheduled job: runs _do_fetch_and_score unless a refresh is already in progress."""
    if cache.is_loading:
        logger.info("Scheduled refresh skipped — already in progress")
        return
    logger.info("Scheduled refresh starting")
    await _do_fetch_and_score()


async def _persist_and_populate(
    article_dicts: list[dict[str, Any]],
    total_fetched: int,
    elapsed: float | None = None,
    refresh_time: float | None = None,
) -> None:
    """Save articles to DB, reconcile bookmarks, populate cache, update Prometheus."""
    await save_articles(article_dicts, total_fetched)
    bookmarked = await get_bookmarked_ids()
    for a in article_dicts:
        a["bookmarked"] = a["id"] in bookmarked
    cache.populate(
        article_dicts, refresh_time if refresh_time is not None else time.time(), total_fetched
    )
    if elapsed is not None:
        m = _get_metrics()
        m.refreshes.inc()
        m.refresh_dur.observe(elapsed)
    _update_prom_cache()


async def _do_fetch_and_score() -> None:
    """Background task: fetch → score → persist → populate cache."""
    cache.is_loading = True
    cache.error = None
    cache.load_progress = "Démarrage..."
    _t0 = time.perf_counter()

    try:
        cfg = load_config()
        topics_cfg = await _get_or_seed_scoring_config()
        feed_weights = await get_feed_weights()

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
                logger.exception("Pending sync flush failed, will retry on next refresh")

        article_dicts, total_fetched = await asyncio.to_thread(
            _blocking_fetch_and_score,
            cfg,
            topics_cfg,
            feed_weights,
            lambda msg: setattr(cache, "load_progress", msg),
        )
        if total_fetched == 0:
            cache.load_progress = "Aucun article non lu récupéré — DB inchangée"
            logger.info("Refresh complete: 0 articles fetched, cache unchanged")
        else:
            cache.load_progress = "Sauvegarde..."
            await _persist_and_populate(
                article_dicts, total_fetched, elapsed=time.perf_counter() - _t0
            )
            cache.load_progress = "Terminé"
            logger.info(
                "Refresh complete: %d fetched, %d relevant", total_fetched, len(article_dicts)
            )
    except Exception as e:
        cache.error = f"{type(e).__name__}: {e}"
        cache.load_progress = "Erreur"
        logger.exception("Refresh failed")
    finally:
        cache.is_loading = False


@app.post("/api/refresh", dependencies=[Depends(require_auth)])
async def refresh() -> dict[str, Any]:
    """Start async refresh. Returns immediately; poll /api/status for progress."""
    if cache.is_loading:
        return {"status": "already_loading", "progress": cache.load_progress}

    cache.refresh_task = asyncio.create_task(_do_fetch_and_score())
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

    def _put(event: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(q.put_nowait, event)

    def _sse_refresh_worker(topics_cfg: dict[str, Any], feed_weights: dict[str, float]) -> None:
        # _sse_refresh_worker owns is_loading lifecycle from here through finally cleanup.
        # Runs in a thread pool — survives SSE client disconnections.
        # Responsible for DB save, cache populate, and clearing is_loading.
        cache.is_loading = True
        cfg = load_config()
        all_articles: list[dict[str, Any]] = []
        total_fetched = 0
        _t0 = time.perf_counter()

        try:
            topics = build_topics(topics_cfg)
            for scored_batch, total_fetched in fetch_and_score_iter(cfg, topics, feed_weights):
                msg = f"Récupération : {total_fetched} articles..."
                cache.load_progress = msg
                _put({"type": "progress", "message": msg})
                for d in scored_batch:
                    all_articles.append(d)
                    _put({"type": "article", "article": d})

            if total_fetched == 0:
                logger.warning("Stream refresh: 0 articles fetched — DB not modified")
            else:
                cache.load_progress = "Sauvegarde..."
                elapsed = time.perf_counter() - _t0
                asyncio.run_coroutine_threadsafe(
                    _persist_and_populate(all_articles, total_fetched, elapsed=elapsed), loop
                ).result()
                logger.info(
                    "Stream refresh done: %d fetched, %d relevant",
                    total_fetched,
                    len(all_articles),
                )

            cache.load_progress = "Terminé"
            _put({"type": "done", "total_fetched": total_fetched, "count": len(all_articles)})
        except Exception as e:
            logger.exception("refresh-stream worker failed")
            cache.error = f"{type(e).__name__}: {e}"
            cache.load_progress = "Erreur"
            _put({"type": "error", "message": str(e)})
        finally:
            cache.is_loading = False

    async def _event_gen():
        cache.error = None
        cache.load_progress = "Démarrage..."

        try:
            topics_cfg = await _get_or_seed_scoring_config()
            feed_weights = await get_feed_weights()
        except Exception as e:
            logger.exception("refresh-stream init failed")
            cache.error = f"{type(e).__name__}: {e}"
            cache.load_progress = "Erreur"
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        asyncio.create_task(asyncio.to_thread(_sse_refresh_worker, topics_cfg, feed_weights))
        try:
            while True:
                event = await q.get()
                yield f"data: {json.dumps(event)}\n\n"
                if event["type"] in ("done", "error"):
                    break
        except asyncio.CancelledError:
            raise
        # cache.is_loading is managed by the worker thread

    return StreamingResponse(
        _event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _blocking_rescore_compute(
    raw: list[dict[str, Any]],
    cfg: dict[str, Any],
    topics_cfg: dict[str, Any],
    feed_weights: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """CPU re-scoring of cached articles. Runs in a thread pool via asyncio.to_thread."""
    scoring_cfg = cfg.get("scoring", {})
    title_weight = int(scoring_cfg.get("title_weight", 3))
    min_score = float(scoring_cfg.get("min_score", 1.0))
    topics = build_topics(topics_cfg)
    return rescore_articles(raw, topics, title_weight, min_score, feed_weights)


async def _do_rescore_from_db() -> None:
    """Background task: rescore from DB → persist → populate cache."""
    cache.is_loading = True
    cache.error = None
    cache.load_progress = "Démarrage du re-scoring..."

    try:
        raw = await load_for_rescore()
        cfg = load_config()
        topics_cfg = await _get_or_seed_scoring_config()
        feed_weights = await get_feed_weights()
        article_dicts = await asyncio.to_thread(
            _blocking_rescore_compute, raw, cfg, topics_cfg, feed_weights
        )
        total_fetched = int(await get_meta("total_fetched", "0"))
        cache.load_progress = "Sauvegarde..."
        await _persist_and_populate(
            article_dicts, total_fetched, elapsed=None, refresh_time=cache.last_refresh
        )
        cache.load_progress = "Terminé"
        logger.info("Rescore complete: %d relevant articles", len(article_dicts))
    except Exception as e:
        cache.error = f"{type(e).__name__}: {e}"
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

    cache.refresh_task = asyncio.create_task(_do_rescore_from_db())
    return {"status": "started"}


class BookmarkRequest(BaseModel):
    article_id: str


@app.post("/api/bookmark", dependencies=[Depends(require_auth)])
async def bookmark(req: BookmarkRequest) -> dict[str, Any]:
    """Toggle bookmark for an article. Returns new bookmark state."""
    article = next((a for a in cache.articles if a["id"] == req.article_id), None)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")

    is_bookmarked = await toggle_bookmark(req.article_id)
    article["bookmarked"] = is_bookmarked

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

    tg_cfg: TelegramConfig = getattr(request.app.state, "tg_cfg", TelegramConfig("", ""))
    if not tg_cfg.is_configured():
        raise HTTPException(status_code=400, detail="Telegram not configured")

    if req.snooze_until is not None:
        snooze_until = req.snooze_until
    else:
        tomorrow = datetime.date.today() + datetime.timedelta(days=1)
        snooze_until = int(datetime.datetime.combine(tomorrow, datetime.time(8, 0)).timestamp())

    await add_snooze(
        req.article_id,
        tg_cfg.chat_id,
        snooze_until,
        article["title"],
        article["url"],
    )
    return {"status": "ok", "snooze_until": snooze_until}


# ---------------------------------------------------------------------------
# Scoring config
# ---------------------------------------------------------------------------


@app.get("/api/feeds", dependencies=[Depends(require_auth)])
async def list_feeds() -> dict[str, Any]:
    """Return all distinct feed titles stored in the DB."""
    return {"feeds": await get_all_feed_titles()}


@app.get("/api/config/scoring", dependencies=[Depends(require_auth)])
async def get_scoring() -> dict[str, Any]:
    """Return the active scoring topics config and feed weights (from DB, or seeded from config.yaml)."""
    return {
        "topics": await _get_or_seed_scoring_config(),
        "feed_weights": await get_feed_weights(),
    }


class ScoringConfigRequest(BaseModel):
    topics: dict[str, Any]
    feed_weights: dict[str, float] = {}


@app.put("/api/config/scoring", dependencies=[Depends(require_auth)])
async def update_scoring(req: ScoringConfigRequest) -> dict[str, str]:
    """Persist a new scoring config to DB. Takes effect on next refresh or rescore.

    Raises HTTP 422 if any feed_weight value is outside [0.1, 5.0].
    """
    for feed, mult in req.feed_weights.items():
        if not (0.1 <= mult <= 10.0):
            raise HTTPException(
                status_code=422,
                detail=f"feed_weight for '{feed}' must be in [0.1, 10.0], got {mult}",
            )
    await set_scoring_config(req.topics)
    await set_feed_weights(req.feed_weights)
    logger.info(
        "Scoring config updated: %d topics, %d feed weights", len(req.topics), len(req.feed_weights)
    )
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


async def _all_articles_for_digest() -> list[dict[str, Any]]:
    """Return unread cache articles + articles read in the last 24h (deduplicated)."""
    read_today = await load_read_articles(days=1)
    unread_ids = {a["id"] for a in cache.articles}
    extra = [a for a in read_today if a["id"] not in unread_ids]
    return cache.articles + extra


async def _dispatch_daily_digest(tg_cfg: TelegramConfig) -> None:
    """Scheduler job: build and send digest from current cache + articles read today."""
    await send_digest(tg_cfg, await _all_articles_for_digest())


async def _check_trending(tg_cfg: TelegramConfig) -> None:
    """Scheduler job: alert if a topic is surging in the last 2h."""
    cache.trending_alerted = await check_trending(tg_cfg, cache.articles, cache.trending_alerted)


async def _check_snoozes(tg_cfg: TelegramConfig) -> None:
    """Scheduler job: deliver due snooze reminders and remove them from DB."""
    due = await get_due_snoozes()
    if not due:
        return
    sent = await send_snooze_reminders(tg_cfg, due)
    for article_id in sent:
        await delete_snooze(article_id)


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> dict[str, Any]:
    """Receive Telegram updates. Verifies secret header, handles /digest command.

    Returns 404 if Telegram is not configured (webhook_secret absent).
    Returns 403 on invalid secret token.
    """
    tg_cfg: TelegramConfig = getattr(request.app.state, "tg_cfg", TelegramConfig("", ""))
    if not tg_cfg.webhook_secret:
        raise HTTPException(status_code=404)

    header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not secrets.compare_digest(header_secret, tg_cfg.webhook_secret):
        raise HTTPException(status_code=403, detail="Invalid secret")

    body = await request.json()
    text: str = body.get("message", {}).get("text", "")
    if text.startswith("/digest"):
        asyncio.create_task(send_digest(tg_cfg, await _all_articles_for_digest()))

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
        host=str(srv.get("host", "0.0.0.0")),  # nosec B104 — default binds all interfaces; callers override via SERVER_HOST
        port=int(srv.get("port", 8123)),
        reload=reload,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_config=LOGGING_CONFIG,
    )
