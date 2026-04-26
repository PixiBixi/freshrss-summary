"""FreshRSS Summary — FastAPI backend."""

import asyncio
import hashlib
import json
import logging
import logging.config
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import yaml
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
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from db import (
    DEFAULT_DB_URL,
    add_pending_sync,
    clear_pending_sync,
    get_bookmarked_ids,
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
from freshrss_client import Article, FreshRSSClient
from scorer import ScoredArticle, build_topics, score_articles

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

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_config() -> dict:
    """
    Load config from config.yaml (if present), then apply env var overrides.

    Supported env vars (all optional, take priority over config.yaml):
      FRESHRSS_URL           → freshrss.url
      FRESHRSS_USERNAME      → freshrss.username
      FRESHRSS_API_PASSWORD  → freshrss.api_password
      SERVER_HOST            → server.host
      SERVER_PORT            → server.port
    """
    cfg: dict = {}
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open() as f:
            cfg = yaml.safe_load(f) or {}
    else:
        logger.warning("config.yaml not found — relying entirely on environment variables")

    fr = cfg.setdefault("freshrss", {})
    if v := os.environ.get("FRESHRSS_URL"):
        fr["url"] = v
    if v := os.environ.get("FRESHRSS_USERNAME"):
        fr["username"] = v
    if v := os.environ.get("FRESHRSS_API_PASSWORD"):
        fr["api_password"] = v

    srv = cfg.setdefault("server", {})
    if v := os.environ.get("SERVER_HOST"):
        srv["host"] = v
    if v := os.environ.get("SERVER_PORT"):
        srv["port"] = int(v)

    db = cfg.setdefault("database", {})
    if v := os.environ.get("DATABASE_URL"):
        db["url"] = v

    # Validate required FreshRSS fields
    missing = [k for k in ("url", "username", "api_password") if not fr.get(k)]
    if missing:
        raise RuntimeError(
            f"Missing FreshRSS config: {', '.join(missing)}. "
            "Set them in config.yaml or via FRESHRSS_URL / FRESHRSS_USERNAME / FRESHRSS_API_PASSWORD."
        )

    return cfg


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

    def populate(
        self, articles: list[dict], last_refresh: float | None, total_fetched: int
    ) -> None:
        self.articles = articles
        self.last_refresh = last_refresh
        self.total_fetched = total_fetched
        self.all_topics = sorted({t for a in articles for t in a["matched_topics"]})


cache = Cache()
_refresh_task: asyncio.Task | None = None


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

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")


async def init_admin_user() -> None:
    """
    Ensure at least one user exists in DB.

    - If ADMIN_PASSWORD env var is set: upsert admin with that password (useful
      for Docker secrets / initial deploy / password reset).
    - Else if DB has no users: generate a random password, store it, log it.
    """
    admin_password = os.environ.get("ADMIN_PASSWORD")

    if admin_password:
        await upsert_user(ADMIN_USERNAME, hash_password(admin_password))
        logger.info("Admin user '%s' password applied from ADMIN_PASSWORD env var", ADMIN_USERNAME)
    elif not await has_users():
        admin_password = secrets.token_urlsafe(16)
        await upsert_user(ADMIN_USERNAME, hash_password(admin_password))
        sep = "=" * 56
        logger.warning(sep)
        logger.warning("  FIRST RUN — admin account created")
        logger.warning("  Username : %s", ADMIN_USERNAME)
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
    yield


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
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("authenticated"):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


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
        "login.html",
        {"request": request, "error": "Identifiants invalides"},
        status_code=401,
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


@app.get("/api/status")
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


@app.get("/api/articles")
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


async def _load_scoring_config() -> dict:
    """Load topics config from DB; seed from config.yaml on first call."""
    stored = await get_scoring_config()
    if stored is not None:
        return stored
    cfg = load_config()
    topics = cfg.get("topics", {})
    if topics:
        await set_scoring_config(topics)
    return topics


def _blocking_mark_as_read(article_ids: list[str]) -> None:
    cfg = load_config()
    fr_cfg = cfg["freshrss"]
    with FreshRSSClient(fr_cfg["url"], fr_cfg["username"], fr_cfg["api_password"]) as client:
        client.mark_as_read(article_ids)


@app.post("/api/mark-read")
async def mark_read(req: MarkReadRequest) -> dict[str, str]:
    if not req.article_ids:
        raise HTTPException(status_code=400, detail="No article IDs provided")

    # Local state updated immediately — never blocked by upstream availability
    ids_set = set(req.article_ids)
    cache.articles = [a for a in cache.articles if a["id"] not in ids_set]
    await set_articles_read(req.article_ids)

    # Best-effort upstream sync; queue for retry if FreshRSS is unreachable
    try:
        await asyncio.to_thread(_blocking_mark_as_read, req.article_ids)
    except Exception:
        logger.warning(
            "FreshRSS unreachable — queuing %d article(s) for deferred sync", len(req.article_ids)
        )
        await add_pending_sync(req.article_ids)
        return {"status": "queued"}

    return {"status": "ok", "marked": str(len(req.article_ids))}


def _blocking_fetch_and_score(cfg: dict, topics_cfg: dict) -> tuple[list[dict], int]:
    """
    Blocking fetch + score — runs in a thread pool via asyncio.to_thread.
    Updates cache.load_progress directly (thread-safe for simple str assignment).
    """
    fr_cfg = cfg["freshrss"]
    fetch_cfg = cfg.get("fetch", {})
    scoring_cfg = cfg.get("scoring", {})

    batch_size = int(fetch_cfg.get("batch_size", 1000))
    max_batches = int(fetch_cfg.get("max_batches", 10))
    title_weight = int(scoring_cfg.get("title_weight", 3))
    min_score = float(scoring_cfg.get("min_score", 1.0))

    topics = build_topics({"topics": topics_cfg})
    all_articles = []
    total_fetched = 0

    with FreshRSSClient(fr_cfg["url"], fr_cfg["username"], fr_cfg["api_password"]) as client:
        for batch in client.fetch_unread(batch_size=batch_size, max_batches=max_batches):
            total_fetched += len(batch)
            cache.load_progress = f"Récupération : {total_fetched} articles..."
            all_articles.extend(batch)

    cache.load_progress = f"Scoring {total_fetched} articles..."
    scored: list[ScoredArticle] = score_articles(
        all_articles, topics, title_weight=title_weight, min_score=min_score
    )

    if total_fetched == 0:
        logger.warning("No articles fetched from FreshRSS — DB not modified")
        return [], 0

    return [a.to_dict() for a in scored], total_fetched


async def _do_refresh() -> None:
    """Background task: fetch → score → persist → populate cache."""
    cache.is_loading = True
    cache.error = None
    cache.load_progress = "Démarrage..."
    _t0 = time.perf_counter()

    try:
        cfg = load_config()
        topics_cfg = await _load_scoring_config()

        # Drain outbox: replay mark-as-read calls that failed when FreshRSS was offline
        pending = await get_pending_sync()
        if pending:
            try:
                await asyncio.to_thread(_blocking_mark_as_read, pending)
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
    global _refresh_task

    if cache.is_loading:
        return {"status": "already_loading", "progress": cache.load_progress}

    _refresh_task = asyncio.create_task(_do_refresh())
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
        fr_cfg = cfg["freshrss"]
        fetch_cfg = cfg.get("fetch", {})
        scoring_cfg = cfg.get("scoring", {})
        batch_size = int(fetch_cfg.get("batch_size", 1000))
        max_batches = int(fetch_cfg.get("max_batches", 10))
        title_weight = int(scoring_cfg.get("title_weight", 3))
        min_score = float(scoring_cfg.get("min_score", 1.0))
        topics = build_topics({"topics": topics_cfg})
        total_fetched = 0
        all_articles: list[dict] = []

        try:
            with FreshRSSClient(
                fr_cfg["url"], fr_cfg["username"], fr_cfg["api_password"]
            ) as client:
                for batch in client.fetch_unread(batch_size=batch_size, max_batches=max_batches):
                    total_fetched += len(batch)
                    _put(
                        {
                            "type": "progress",
                            "message": f"Récupération : {total_fetched} articles...",
                        }
                    )
                    for sa in score_articles(
                        batch, topics, title_weight=title_weight, min_score=min_score
                    ):
                        d = sa.to_dict()
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

        topics_cfg = await _load_scoring_config()
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
    """Pure CPU re-scoring — no I/O. Runs in a thread pool via asyncio.to_thread."""
    scoring_cfg = cfg.get("scoring", {})
    title_weight = int(scoring_cfg.get("title_weight", 3))
    min_score = float(scoring_cfg.get("min_score", 1.0))
    topics = build_topics({"topics": topics_cfg})

    cache.load_progress = f"Re-scoring {len(raw)} articles..."
    articles = [
        Article(
            id=r["id"],
            title=r["title"],
            url=r["url"],
            content=r["content"],
            summary="",
            feed_title=r["feed_title"],
            published=r["published"],
        )
        for r in raw
    ]
    return [
        a.to_dict()
        for a in score_articles(articles, topics, title_weight=title_weight, min_score=min_score)
    ]


async def _do_rescore() -> None:
    """Background task: rescore from DB → persist → populate cache."""
    cache.is_loading = True
    cache.error = None
    cache.load_progress = "Démarrage du re-scoring..."

    try:
        raw = await load_for_rescore()
        cfg = load_config()
        topics_cfg = await _load_scoring_config()
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
    global _refresh_task

    if cache.is_loading:
        return {"status": "already_loading", "progress": cache.load_progress}

    if not cache.articles and not await load_for_rescore():
        raise HTTPException(
            status_code=400, detail="Aucun article en DB. Lance d'abord un Rafraîchir."
        )

    _refresh_task = asyncio.create_task(_do_rescore())
    return {"status": "started"}


class BookmarkRequest(BaseModel):
    article_id: str


@app.post("/api/bookmark")
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
# Scoring config
# ---------------------------------------------------------------------------


@app.get("/api/config/scoring", dependencies=[Depends(require_auth)])
async def get_scoring() -> dict[str, Any]:
    """Return the active scoring topics config (from DB, or seeded from config.yaml)."""
    return {"topics": await _load_scoring_config()}


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
    username = request.session.get("username", ADMIN_USERNAME)
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


@app.get("/health")
async def health() -> JSONResponse:
    """Liveness/readiness probe. No auth required."""
    from sqlalchemy import text as sa_text

    from db import get_engine

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


@app.get("/metrics")
async def metrics() -> Response:
    """Prometheus metrics scrape endpoint. No auth required."""
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
        log_config=LOGGING_CONFIG,
    )
