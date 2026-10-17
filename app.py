"""FreshRSS Summary - FastAPI backend."""

import asyncio
import datetime
import json
import logging
import logging.config
import os
import secrets
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import itsdangerous
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
from pydantic import BaseModel
from sqlalchemy import text as sa_text
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from auth import (
    hash_password,
    init_admin_user,
    login_rate_limit,
    require_auth,
    resolve_secret_key,
    verify_password,
)
from config import ConfigDict, load_config, session_https_only
from db import (
    DEFAULT_DB_URL,
    add_pending_sync,
    add_snooze,
    delete_snooze,
    get_all_feed_titles,
    get_due_snoozes,
    get_engine,
    get_feed_weights,
    get_or_seed_scoring_config,
    get_scoring_config,
    get_user_hash,
    init_db,
    load_articles,
    load_for_rescore,
    load_read_articles,
    set_articles_read,
    set_feed_weights,
    set_scoring_config,
    set_user_password,
    toggle_bookmark,
)
from freshrss_client import FreshRSSClient, close_shared_client, get_shared_client
from logging_config import LOGGING_CONFIG
from metrics import CONTENT_TYPE_LATEST, _update_prom_cache, generate_latest
from refresh_service import Cache, refresh_job, rescore_job
from scheduler import run_daily_at, run_every
from scorer import DEFAULT_TOPICS
from telegram_digest import (
    TelegramConfig,
    check_trending,
    register_webhook,
    send_digest,
    send_snooze_reminders,
)

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory cache (process-local: the app must run as a single replica)
# ---------------------------------------------------------------------------

cache = Cache()


# ---------------------------------------------------------------------------
# App lifespan: init DB and warm cache from persisted data
# ---------------------------------------------------------------------------


async def _setup_telegram_tasks(
    bg_tasks: list[asyncio.Task], tg_cfg: TelegramConfig, cfg: ConfigDict
) -> None:
    """Spawn asyncio background tasks for all Telegram-related periodic jobs."""
    hour = int(cfg.get("telegram", {}).get("digest_hour", 21))
    bg_tasks.append(
        asyncio.create_task(run_daily_at(_dispatch_daily_digest, hour, "Europe/Paris", tg_cfg))
    )
    logger.info("Telegram digest scheduled at %02dh00 Europe/Paris", hour)
    bg_tasks.append(asyncio.create_task(run_every(_check_trending, 3600, tg_cfg)))
    logger.info("Trending topic checker scheduled: every 1h")
    bg_tasks.append(asyncio.create_task(run_every(_check_snoozes, 900, tg_cfg)))
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
    if _session_middleware is not None:
        _session_middleware.bind_secret_key(await resolve_secret_key())
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
    _update_prom_cache(cache.articles, cache.last_refresh)

    bg_tasks: list[asyncio.Task] = []
    interval = int(cfg.get("scheduler", {}).get("interval_minutes", 0))
    if interval > 0:
        bg_tasks.append(asyncio.create_task(run_every(_auto_refresh, interval * 60)))
        logger.info("Auto-refresh scheduler started: every %d min", interval)

    tg_cfg = TelegramConfig.from_dict(dict(cfg.get("telegram", {})))
    if tg_cfg.is_configured():
        await _setup_telegram_tasks(bg_tasks, tg_cfg, cfg)

    app.state.tg_cfg = tg_cfg

    yield

    for task in bg_tasks:
        task.cancel()
    await asyncio.gather(*bg_tasks, return_exceptions=True)
    close_shared_client()


_session_middleware: "_SessionMiddleware | None" = None


class _SessionMiddleware(SessionMiddleware):
    """
    Session middleware whose signing key is bound during startup.

    Starlette builds the middleware stack *before* running the lifespan body, so
    the key cannot be read here: it may live in the database, which `init_db()`
    has not opened yet. The placeholder below is replaced by `bind_secret_key()`
    at the end of the lifespan, before any request is served.
    """

    def __init__(self, app: Any) -> None:
        super().__init__(
            app,
            secret_key=secrets.token_hex(32),
            same_site="lax",
            https_only=session_https_only(),
        )
        global _session_middleware
        _session_middleware = self

    def bind_secret_key(self, key: str) -> None:
        self.signer = itsdangerous.TimestampSigner(key)


app = FastAPI(title="FreshRSS Summary", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(_SessionMiddleware)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_inflight_tasks: set[asyncio.Task] = set()


def _spawn(coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
    """
    Schedule `coro` and keep a strong reference until it finishes.

    The event loop only holds a weak reference to running tasks, so a bare
    asyncio.create_task() can be garbage-collected mid-flight - silently killing
    the work and swallowing any exception it raised.
    """
    task = asyncio.create_task(coro)
    _inflight_tasks.add(task)
    task.add_done_callback(_inflight_tasks.discard)
    return task


def _start_in_slot(job: Callable[[], Awaitable[None]]) -> asyncio.Task | None:
    """
    Claim the refresh slot and run `job` in the background, or return None if busy.

    The claim is synchronous, hence atomic on the event loop, and the job's task is
    the slot's only owner: it releases it however the job ends, even when the HTTP
    client that started it is long gone.
    """
    if not cache.try_begin_loading():
        return None

    async def _owned() -> None:
        try:
            await job()
        finally:
            cache.end_loading()

    return _spawn(_owned())


def _safe_next_url(raw: str) -> str:
    """
    Return `raw` if it is a local path, else "/".

    `?next=//evil.tld` and `?next=https://evil.tld` would otherwise turn the
    post-login redirect into an open redirect towards an attacker-controlled site.
    """
    if raw.startswith("/") and not raw.startswith(("//", "/\\")):
        return raw
    return "/"


def _shared_freshrss_client(cfg: ConfigDict) -> FreshRSSClient:
    """Process-wide client for short mark-read calls - must not be closed by callers."""
    fr = cfg["freshrss"]  # type: ignore[typeddict-item]
    return get_shared_client(fr["url"], fr["username"], fr["api_password"])


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


@app.get("/login", response_class=Response)
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
        next_url = _safe_next_url(request.query_params.get("next", "/"))
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
        raise HTTPException(status_code=503, detail="Cache initializing - try again shortly")
    if show_read and not request.session.get("authenticated"):
        show_read = False
    articles = cache.articles
    # Read articles join before filtering: appended after, they ignored every
    # filter and inflated `total`.
    if show_read:
        articles = articles + await load_read_articles(days=days)

    if days > 0:
        cutoff = int(time.time()) - days * 86400
        articles = [a for a in articles if (a["published"] or 0) >= cutoff]

    if topic:
        articles = [a for a in articles if topic in a.get("matched_topics", {})]

    if min_score is not None:
        articles = [a for a in articles if a["score"] >= min_score]

    if sort == "score":
        articles = sorted(articles, key=lambda a: a["score"], reverse=True)
    elif sort == "date":
        articles = sorted(articles, key=lambda a: a["published"], reverse=True)
    elif sort == "feed":
        articles = sorted(articles, key=lambda a: a["feed_title"])

    total = len(articles)
    page = articles[offset:] if limit <= 0 else articles[offset : offset + limit]

    return {"total": total, "articles": page}


class MarkReadRequest(BaseModel):
    article_ids: list[str]


@app.post("/api/mark-read", dependencies=[Depends(require_auth)])
async def mark_read(req: MarkReadRequest) -> dict[str, Any]:
    if not req.article_ids:
        raise HTTPException(status_code=400, detail="No article IDs provided")

    # Local state updated immediately - never blocked by upstream availability
    ids_set = set(req.article_ids)
    cache.articles = [a for a in cache.articles if a["id"] not in ids_set]
    await set_articles_read(req.article_ids)

    # load_config() raises RuntimeError on missing credentials. That is a
    # misconfiguration, not an unreachable upstream: reported as plain "queued" it
    # was indistinguishable from a network blip, so pending_sync grew forever while
    # nobody noticed FreshRSS was never contacted. Surfaced as its own status and
    # logged at error level - but still a 200, because marking read locally must
    # never fail on an upstream concern.
    try:
        cfg = load_config()
    except RuntimeError:
        logger.error(
            "FreshRSS is not configured - %d article(s) marked read locally only",
            len(req.article_ids),
        )
        await add_pending_sync(req.article_ids)
        return {"status": "not_configured", "marked": len(req.article_ids)}

    # Best-effort upstream sync; queue for retry if FreshRSS is unreachable
    try:

        def _sync_mark_read() -> None:
            _shared_freshrss_client(cfg).mark_as_read(req.article_ids)

        await asyncio.to_thread(_sync_mark_read)
    except (httpx.HTTPError, RuntimeError):
        logger.exception(
            "FreshRSS unreachable - queuing %d article(s) for deferred sync", len(req.article_ids)
        )
        await add_pending_sync(req.article_ids)
        return {"status": "queued", "marked": len(req.article_ids)}

    return {"status": "ok", "marked": len(req.article_ids)}


async def _auto_refresh() -> None:
    """Scheduled job: runs _do_fetch_and_score unless a refresh is already in progress."""
    task = _start_in_slot(_do_fetch_and_score)
    if task is None:
        logger.info("Scheduled refresh skipped - already in progress")
        return
    logger.info("Scheduled refresh starting")
    await task


async def _do_fetch_and_score() -> None:
    """Refresh job for POST /api/refresh and the scheduler. Run through _start_in_slot()."""
    await refresh_job(cache)


async def _do_rescore_from_db() -> None:
    """Rescore job for POST /api/rescore. Run through _start_in_slot()."""
    await rescore_job(cache)


@app.post("/api/refresh", dependencies=[Depends(require_auth)])
async def refresh() -> dict[str, Any]:
    """Start async refresh. Returns immediately; poll /api/status for progress."""
    task = _start_in_slot(_do_fetch_and_score)
    if task is None:
        return {"status": "already_loading", "progress": cache.load_progress}

    cache.refresh_task = task
    return {"status": "started"}


@app.get("/api/refresh/stream", dependencies=[Depends(require_auth)])
async def refresh_stream() -> StreamingResponse:
    """SSE: fetch → score per batch → stream each scored article as it arrives."""
    q: asyncio.Queue = asyncio.Queue()
    # The job does all the work, not the SSE generator: Starlette never starts the
    # generator when the client leaves first, and the refresh must still run.
    task = _start_in_slot(lambda: refresh_job(cache, q.put_nowait))
    if task is None:

        async def _busy():
            yield f"data: {json.dumps({'type': 'busy'})}\n\n"

        return StreamingResponse(
            _busy(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def _event_gen():
        while True:
            event = await q.get()
            if event["type"] == "state":
                continue  # pure state update - not forwarded to SSE client
            if event["type"] in ("done", "error"):
                # Forwarded once the job has released the slot, so a client that
                # sees "done" can start the next refresh straight away.
                await asyncio.wait({task})
            # Strip private fields before forwarding to the SSE client
            public_event = {k: v for k, v in event.items() if not k.startswith("_")}
            yield f"data: {json.dumps(public_event)}\n\n"
            if event["type"] in ("done", "error"):
                break

    return StreamingResponse(
        _event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/rescore", dependencies=[Depends(require_auth)])
async def rescore() -> dict[str, Any]:
    """Re-score cached articles with current config. No FreshRSS fetch."""
    # Not the guard (_start_in_slot is): only keeps "busy" ahead of the 400 below.
    if cache.is_loading:
        return {"status": "already_loading", "progress": cache.load_progress}

    if not cache.articles and not await load_for_rescore():
        raise HTTPException(
            status_code=400, detail="Aucun article en DB. Lance d'abord un Rafraîchir."
        )

    task = _start_in_slot(_do_rescore_from_db)
    if task is None:
        return {"status": "already_loading", "progress": cache.load_progress}
    cache.refresh_task = task
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
    topics = await get_scoring_config()
    if topics is None:
        topics = await get_or_seed_scoring_config(load_config(), DEFAULT_TOPICS)
    return {
        "topics": topics,
        "feed_weights": await get_feed_weights(),
    }


class ScoringConfigRequest(BaseModel):
    topics: dict[str, Any]
    feed_weights: dict[str, float] = {}


@app.put("/api/config/scoring", dependencies=[Depends(require_auth)])
async def update_scoring(req: ScoringConfigRequest) -> dict[str, str]:
    """Persist a new scoring config to DB. Takes effect on next refresh or rescore.

    Raises HTTP 422 if any feed_weight value is outside [0.1, 10.0].
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
        _spawn(send_digest(tg_cfg, await _all_articles_for_digest()))

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
    _update_prom_cache(cache.articles, cache.last_refresh)
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
        host=str(srv.get("host", "0.0.0.0")),  # nosec B104 - default binds all interfaces; callers override via SERVER_HOST
        port=int(srv.get("port", 8123)),
        reload=reload,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_config=LOGGING_CONFIG,
    )
