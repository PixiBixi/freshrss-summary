"""FreshRSS Summary — FastAPI backend."""

import asyncio
import concurrent.futures
import datetime
import json
import logging
import logging.config
import math
import os
import secrets
import time
from collections.abc import AsyncGenerator, Coroutine
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
from config import ConfigDict, load_config
from db import (
    DEFAULT_DB_URL,
    add_pending_sync,
    add_snooze,
    clear_pending_sync,
    delete_snooze,
    forget_seen_ids,
    get_all_feed_titles,
    get_bookmarked_ids,
    get_due_snoozes,
    get_engine,
    get_feed_weights,
    get_meta,
    get_or_seed_scoring_config,
    get_pending_sync,
    get_scoring_config,
    get_seen_ids,
    get_user_hash,
    init_db,
    load_articles,
    load_for_rescore,
    load_read_articles,
    record_seen_ids,
    save_articles,
    set_articles_read,
    set_feed_weights,
    set_scoring_config,
    set_user_password,
    sync_articles,
    toggle_bookmark,
)
from freshrss_client import FreshRSSClient, close_shared_client, get_shared_client
from logging_config import LOGGING_CONFIG
from metrics import CONTENT_TYPE_LATEST, _get_metrics, _update_prom_cache, generate_latest
from models import ArticleDict, strip_content
from pipeline import fetch_and_score_incremental_iter, rescore_chunk
from scheduler import run_daily_at, run_every
from scorer import DEFAULT_TOPICS, build_topics
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

    def try_begin_loading(self) -> bool:
        """
        Claim the refresh slot, or return False if one is already running.

        Test and set happen with no `await` in between, which makes them atomic on
        the single-threaded event loop. Checking `is_loading` in a handler and
        letting the worker set it later left a window several awaits wide: a
        double-click, or the scheduler firing during a manual refresh, started two
        concurrent fetches writing the same rows.

        Every caller must pair this with end_loading() in a finally.
        """
        if self.is_loading:
            return False
        self.is_loading = True
        self.error = None
        self.load_progress = "Démarrage..."
        return True

    def end_loading(self) -> None:
        """Release the refresh slot."""
        self.is_loading = False

    def populate(
        self, articles: list[ArticleDict], last_refresh: float | None, total_fetched: int
    ) -> None:
        # Single choke point for the cache: `_content` holds the full article text
        # (~10 kB each) and is only needed on the way to the DB. Keeping it here
        # would both bloat memory and leak it through the public /api/articles.
        self.articles = [strip_content(a) for a in articles]
        self.last_refresh = last_refresh
        self.total_fetched = total_fetched
        self.all_topics = sorted({t for a in self.articles for t in a["matched_topics"]})
        self.initialized = True


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
        super().__init__(app, secret_key=secrets.token_hex(32))
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
    asyncio.create_task() can be garbage-collected mid-flight — silently killing
    the work and swallowing any exception it raised.
    """
    task = asyncio.create_task(coro)
    _inflight_tasks.add(task)
    task.add_done_callback(_inflight_tasks.discard)
    return task


def _safe_next_url(raw: str) -> str:
    """
    Return `raw` if it is a local path, else "/".

    `?next=//evil.tld` and `?next=https://evil.tld` would otherwise turn the
    post-login redirect into an open redirect towards an attacker-controlled site.
    """
    if raw.startswith("/") and not raw.startswith(("//", "/\\")):
        return raw
    return "/"


def _make_freshrss_client(cfg: ConfigDict) -> FreshRSSClient:
    """Build a FreshRSSClient from the freshrss section of the config."""
    fr = cfg["freshrss"]  # type: ignore[typeddict-item]
    return FreshRSSClient(fr["url"], fr["username"], fr["api_password"])


def _shared_freshrss_client(cfg: ConfigDict) -> FreshRSSClient:
    """Process-wide client for short mark-read calls — must not be closed by callers."""
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
    page = articles[offset:] if limit <= 0 else articles[offset : offset + limit]

    return {"total": total, "articles": page}


class MarkReadRequest(BaseModel):
    article_ids: list[str]


@app.post("/api/mark-read", dependencies=[Depends(require_auth)])
async def mark_read(req: MarkReadRequest) -> dict[str, Any]:
    if not req.article_ids:
        raise HTTPException(status_code=400, detail="No article IDs provided")

    # Local state updated immediately — never blocked by upstream availability
    ids_set = set(req.article_ids)
    cache.articles = [a for a in cache.articles if a["id"] not in ids_set]
    await set_articles_read(req.article_ids)

    # load_config() raises RuntimeError on missing credentials. That is a
    # misconfiguration, not an unreachable upstream: reported as plain "queued" it
    # was indistinguishable from a network blip, so pending_sync grew forever while
    # nobody noticed FreshRSS was never contacted. Surfaced as its own status and
    # logged at error level — but still a 200, because marking read locally must
    # never fail on an upstream concern.
    try:
        cfg = load_config()
    except RuntimeError:
        logger.error(
            "FreshRSS is not configured — %d article(s) marked read locally only",
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
            "FreshRSS unreachable — queuing %d article(s) for deferred sync", len(req.article_ids)
        )
        await add_pending_sync(req.article_ids)
        return {"status": "queued", "marked": len(req.article_ids)}

    return {"status": "ok", "marked": len(req.article_ids)}


async def _auto_refresh() -> None:
    """Scheduled job: runs _do_fetch_and_score unless a refresh is already in progress."""
    if not cache.try_begin_loading():
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
    """Save articles to DB, reconcile bookmarks, populate cache, update Prometheus.
    Used by the rescore path (full replace semantics).
    """
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
    _update_prom_cache(cache.articles, cache.last_refresh)


async def _record_refresh_ids(processed: list[str], removed: set[str]) -> None:
    """Record processed IDs and forget the ones FreshRSS no longer lists as unread."""
    await record_seen_ids(processed)
    await forget_seen_ids(removed)


async def _incremental_persist_and_populate(
    new_articles: list[dict[str, Any]],
    removed_ids: set[str],
    total_fetched: int,
    elapsed: float | None = None,
) -> None:
    """Incremental sync to DB, reload full cache from DB, update Prometheus."""
    await sync_articles(new_articles, removed_ids, total_fetched)
    articles, last_refresh, _ = await load_articles()
    cache.populate(articles, last_refresh or time.time(), total_fetched)
    if elapsed is not None:
        m = _get_metrics()
        m.refreshes.inc()
        m.refresh_dur.observe(elapsed)
    _update_prom_cache(cache.articles, cache.last_refresh)


async def _do_fetch_and_score() -> None:
    """Background task: incremental fetch → score → sync DB → populate cache.

    The refresh slot is claimed by the caller via cache.try_begin_loading(); this
    only owns releasing it.
    """
    _t0 = time.perf_counter()

    try:
        cfg = load_config()
        topics_cfg = await get_or_seed_scoring_config(cfg, DEFAULT_TOPICS)
        feed_weights = await get_feed_weights()

        # Drain outbox: replay mark-as-read calls that failed when FreshRSS was offline
        pending = await get_pending_sync()
        if pending:
            try:

                def _sync_pending() -> None:
                    _shared_freshrss_client(cfg).mark_as_read(pending)

                await asyncio.to_thread(_sync_pending)
                await clear_pending_sync(pending)
                logger.info("Flushed %d pending read sync(s) to FreshRSS", len(pending))
            except Exception:
                logger.exception("Pending sync flush failed, will retry on next refresh")

        seen_ids = await get_seen_ids()

        def _blocking_incremental() -> tuple[list[dict[str, Any]], set[str], int, list[str]]:
            all_new: list[dict[str, Any]] = []
            removed: set[str] = set()
            total = 0
            processed: list[str] = []
            topics = build_topics(topics_cfg)
            for b in fetch_and_score_incremental_iter(cfg, topics, seen_ids, feed_weights):
                cache.load_progress = f"Récupération : {len(all_new) + len(b.scored)} nouveaux..."
                all_new.extend(b.scored)
                removed = b.removed_ids
                total = b.total_fetched
                processed.extend(b.processed_ids)
            return all_new, removed, total, processed

        new_articles, removed_ids, total_fetched, processed_ids = await asyncio.to_thread(
            _blocking_incremental
        )
        # Recorded whatever their score: articles below min_score are never stored
        # in `articles`, so this is the only thing keeping them out of the next diff.
        await _record_refresh_ids(processed_ids, removed_ids)

        if not new_articles and not removed_ids:
            cache.load_progress = "Aucun changement"
            logger.info("Incremental refresh: no changes (0 new, 0 removed)")
        else:
            cache.load_progress = "Sauvegarde..."
            await _incremental_persist_and_populate(
                new_articles, removed_ids, total_fetched, elapsed=time.perf_counter() - _t0
            )
            cache.load_progress = "Terminé"
            logger.info(
                "Incremental refresh: %d total unread, +%d new, -%d removed, %d relevant",
                total_fetched,
                len(new_articles),
                len(removed_ids),
                len(cache.articles),
            )
    except Exception as e:
        cache.error = f"{type(e).__name__}: {e}"
        cache.load_progress = "Erreur"
        logger.exception("Refresh failed")
    finally:
        cache.end_loading()


@app.post("/api/refresh", dependencies=[Depends(require_auth)])
async def refresh() -> dict[str, Any]:
    """Start async refresh. Returns immediately; poll /api/status for progress."""
    if not cache.try_begin_loading():
        return {"status": "already_loading", "progress": cache.load_progress}

    cache.refresh_task = _spawn(_do_fetch_and_score())
    return {"status": "started"}


@app.get("/api/refresh/stream", dependencies=[Depends(require_auth)])
async def refresh_stream() -> StreamingResponse:
    """SSE: fetch → score per batch → stream each scored article as it arrives."""
    if not cache.try_begin_loading():

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

    def _sse_refresh_worker(
        topics_cfg: dict[str, Any],
        feed_weights: dict[str, float],
        seen_ids: set[str],
        cfg: ConfigDict,
    ) -> None:
        # Runs in a thread pool — survives SSE client disconnections.
        # The slot was already claimed by the handler; this owns releasing it.
        all_new_articles: list[dict[str, Any]] = []
        removed_ids: set[str] = set()
        total_fetched = 0
        _t0 = time.perf_counter()

        try:
            topics = build_topics(topics_cfg)
            first_batch = True
            processed_ids: list[str] = []
            for b in fetch_and_score_incremental_iter(cfg, topics, seen_ids, feed_weights):
                scored_batch = b.scored
                removed_ids = b.removed_ids
                total_fetched = b.total_fetched
                processed_ids.extend(b.processed_ids)

                # Emit removed IDs before the first article batch so the UI can drop them
                if first_batch:
                    first_batch = False
                    if removed_ids:
                        _put({"type": "removed", "ids": list(removed_ids)})

                if scored_batch:
                    msg = f"Récupération : {len(all_new_articles) + len(scored_batch)} nouveaux..."
                    _put({"type": "progress", "message": msg, "_load_progress": msg})
                    for d in scored_batch:
                        all_new_articles.append(d)
                        # `d` still carries `_content` for the DB write below; the
                        # client gets a stripped copy. The filter applied to the
                        # event itself only covers its top-level keys.
                        _put({"type": "article", "article": strip_content(d)})

            # Handle case where generator yielded nothing (e.g. network error before first yield)
            if first_batch and removed_ids:
                _put({"type": "removed", "ids": list(removed_ids)})

            # Before the early return below: a batch where every article scored under
            # min_score yields nothing to store, yet those IDs must still be recorded
            # or the next refresh re-downloads them.
            if processed_ids or removed_ids:
                asyncio.run_coroutine_threadsafe(
                    _record_refresh_ids(processed_ids, removed_ids), loop
                ).result()

            if not all_new_articles and not removed_ids:
                logger.info("Stream refresh: no changes")
            else:
                _put({"type": "state", "_load_progress": "Sauvegarde..."})
                elapsed = time.perf_counter() - _t0
                asyncio.run_coroutine_threadsafe(
                    _incremental_persist_and_populate(
                        all_new_articles, removed_ids, total_fetched, elapsed=elapsed
                    ),
                    loop,
                ).result()
                logger.info(
                    "Stream refresh done: %d total unread, +%d new, -%d removed, %d relevant",
                    total_fetched,
                    len(all_new_articles),
                    len(removed_ids),
                    len(cache.articles),
                )

            _put(
                {
                    "type": "done",
                    "total_fetched": total_fetched,
                    "count": len(cache.articles),
                    "new_count": len(all_new_articles),
                    "incremental": True,
                    "_load_progress": "Terminé",
                    "_is_loading": False,
                }
            )
        except Exception as e:
            logger.exception("refresh-stream worker failed")
            _put(
                {
                    "type": "error",
                    "message": str(e),
                    "_cache_error": f"{type(e).__name__}: {e}",
                    "_load_progress": "Erreur",
                    "_is_loading": False,
                }
            )
        finally:
            cache.end_loading()

    async def _event_gen():
        try:
            cfg = load_config()
            topics_cfg = await get_or_seed_scoring_config(cfg, DEFAULT_TOPICS)
            feed_weights = await get_feed_weights()
            seen_ids = await get_seen_ids()
        except Exception as e:
            logger.exception("refresh-stream init failed")
            cache.error = f"{type(e).__name__}: {e}"
            cache.load_progress = "Erreur"
            # The worker never starts, so nothing downstream would release the slot.
            cache.end_loading()
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        _spawn(asyncio.to_thread(_sse_refresh_worker, topics_cfg, feed_weights, seen_ids, cfg))
        try:
            while True:
                event = await q.get()
                # Apply cache state mutations sent by the worker through the queue
                if "_load_progress" in event:
                    cache.load_progress = event["_load_progress"]
                if "_cache_error" in event:
                    cache.error = event["_cache_error"]
                if "_is_loading" in event:
                    cache.is_loading = event["_is_loading"]
                if event["type"] == "state":
                    continue  # pure state update — not forwarded to SSE client
                # Strip private fields before forwarding to the SSE client
                public_event = {k: v for k, v in event.items() if not k.startswith("_")}
                yield f"data: {json.dumps(public_event)}\n\n"
                if event["type"] in ("done", "error"):
                    break
        except asyncio.CancelledError:
            raise

    return StreamingResponse(
        _event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _available_cpus() -> int:
    """
    CPU budget usable by this process, honouring container limits.

    os.cpu_count() reports the host's CPUs: under `docker --cpus=2` on a 16-core
    box it returns 16 and we would oversubscribe by 8x. cgroup v2 publishes the
    real quota in cpu.max ("<quota> <period>", or "max" when uncapped).
    """
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if quota != "max":
            return max(1, round(int(quota) / int(period)))
    except (OSError, ValueError):
        pass
    # process_cpu_count() honours CPU affinity; it is 3.13+, hence the getattr.
    counter = getattr(os, "process_cpu_count", None) or os.cpu_count
    return counter() or 2


_RESCORE_CPUS = _available_cpus()
# Leave one CPU to the event loop so the UI stays responsive during a rescore.
_RESCORE_WORKERS = max(1, _RESCORE_CPUS - 1)
_RESCORE_MIN_CHUNK = 500  # below this, spawning processes costs more than it saves


async def _rescore_compute(
    raw: list[dict[str, Any]],
    cfg: ConfigDict,
    topics_cfg: dict[str, Any],
    feed_weights: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """
    Re-score articles across worker processes.

    Scoring is regex-bound and CPython's `re` never releases the GIL, so running
    this through asyncio.to_thread still stalled the event loop for the whole job
    (~4 ms per article, measured). Processes move the work off the loop entirely
    and split it across cores. Falls back to a thread when spawning is impossible
    (restricted container, no /dev/shm) — degraded, but still correct.
    """
    scoring_cfg = cfg.get("scoring", {})
    title_weight = int(scoring_cfg.get("title_weight", 3))
    min_score = float(scoring_cfg.get("min_score", 1.0))

    # One worker still means one *process*: even without parallelism that keeps the
    # regex work off the event loop, which a thread cannot do.
    workers = max(1, min(_RESCORE_WORKERS, math.ceil(len(raw) / _RESCORE_MIN_CHUNK)))
    size = math.ceil(len(raw) / workers)
    chunks = [raw[i : i + size] for i in range(0, len(raw), size)]
    loop = asyncio.get_running_loop()
    _t0 = time.perf_counter()
    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
            results = await asyncio.gather(
                *(
                    loop.run_in_executor(
                        pool, rescore_chunk, c, topics_cfg, title_weight, min_score, feed_weights
                    )
                    for c in chunks
                )
            )
    except OSError:
        logger.warning("Process pool unavailable — falling back to a single thread")
        return await asyncio.to_thread(
            rescore_chunk, raw, topics_cfg, title_weight, min_score, feed_weights
        )
    elapsed = time.perf_counter() - _t0
    logger.info(
        "Rescored %d articles in %.1fs using %d worker process(es) (%d CPUs visible, %.0f articles/s)",
        len(raw),
        elapsed,
        workers,
        _RESCORE_CPUS,
        len(raw) / elapsed if elapsed else 0,
    )

    merged = [a for chunk in results for a in chunk]
    merged.sort(key=lambda a: a["score"], reverse=True)
    return merged


async def _do_rescore_from_db() -> None:
    """Background task: rescore from DB → persist → populate cache.

    The refresh slot is claimed by the caller via cache.try_begin_loading(); this
    only owns releasing it.
    """
    cache.load_progress = "Démarrage du re-scoring..."

    try:
        raw = await load_for_rescore()
        cfg = load_config()
        topics_cfg = await get_or_seed_scoring_config(load_config(), DEFAULT_TOPICS)
        feed_weights = await get_feed_weights()
        article_dicts = await _rescore_compute(raw, cfg, topics_cfg, feed_weights)
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
        cache.end_loading()


@app.post("/api/rescore", dependencies=[Depends(require_auth)])
async def rescore() -> dict[str, Any]:
    """Re-score cached articles with current config. No FreshRSS fetch."""
    if not cache.try_begin_loading():
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
        host=str(srv.get("host", "0.0.0.0")),  # nosec B104 — default binds all interfaces; callers override via SERVER_HOST
        port=int(srv.get("port", 8123)),
        reload=reload,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_config=LOGGING_CONFIG,
    )
