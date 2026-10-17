"""Refresh and rescore orchestration shared by the web app and the CLI.

One code path runs fetch -> score -> persist -> cache -> metrics, whoever starts
it: POST /api/refresh, the SSE stream, the scheduler or `cli.py fetch`. Progress
is reported as events (plain dicts) through an `emit` callback; the SSE route
forwards them to the browser, everything else only applies them to the cache.

Event types: `removed`, `progress`, `article`, `state`, `done`, `error`. Keys
starting with `_` are private: they update the cache and are never sent to a
client.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import math
import os
import time
from collections.abc import Callable
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import ConfigDict, load_config
from db import (
    clear_pending_sync,
    get_bookmarked_ids,
    get_feed_weights,
    get_meta,
    get_or_seed_scoring_config,
    get_pending_sync,
    get_seen_ids,
    load_articles,
    load_for_rescore,
    save_articles,
    sync_articles,
)
from freshrss_client import get_shared_client
from metrics import _get_metrics, _update_prom_cache
from models import ArticleDict, DbArticleRow, strip_content
from pipeline import fetch_and_score_incremental_iter, rescore_chunk
from scorer import DEFAULT_TOPICS, build_topics

logger = logging.getLogger(__name__)

Event = dict[str, Any]
Emit = Callable[[Event], None]


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

        Only app._start_in_slot() calls this: it ties the release to the job's
        task, so no early return or exception between claim and release can leak
        the slot.
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

    def apply(self, event: Event) -> None:
        """Apply the private state fields of a refresh event."""
        if "_load_progress" in event:
            self.load_progress = event["_load_progress"]
        if "_cache_error" in event:
            self.error = event["_cache_error"]


def error_event(e: BaseException) -> Event:
    return {
        "type": "error",
        "message": str(e),
        "_cache_error": f"{type(e).__name__}: {e}",
        "_load_progress": "Erreur",
    }


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------


@dataclass
class RefreshOutcome:
    new_articles: list[dict[str, Any]] = field(default_factory=list)
    removed_ids: set[str] = field(default_factory=set)
    total_fetched: int = 0
    processed_ids: list[str] = field(default_factory=list)
    # (articles processed, articles relevant) per fetched chunk
    batches: list[tuple[int, int]] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.new_articles or self.removed_ids)


async def _flush_pending_sync(cfg: ConfigDict) -> None:
    """Replay mark-as-read calls that failed while FreshRSS was offline."""
    pending = await get_pending_sync()
    if not pending:
        return
    fr = cfg["freshrss"]  # type: ignore[typeddict-item]
    try:
        client = get_shared_client(fr["url"], fr["username"], fr["api_password"])
        await asyncio.to_thread(client.mark_as_read, pending)
        await clear_pending_sync(pending)
        logger.info("Flushed %d pending read sync(s) to FreshRSS", len(pending))
    except Exception:
        logger.exception("Pending sync flush failed, will retry on next refresh")


async def persist_refresh(outcome: RefreshOutcome, elapsed: float, cache: Cache | None) -> None:
    """Incremental sync to DB, then refresh the cache and Prometheus when given one.

    Runs on every successful refresh, changes or not: a no-op refresh is still a
    refresh, and skipping it froze last_refresh and the refresh metrics.
    """
    # Processed IDs are recorded whatever their score: articles below min_score are
    # never stored in `articles`, so seen_ids is all that keeps them out of the
    # next diff. Same transaction as the articles, or a failed write loses them.
    refreshed_at = await sync_articles(
        outcome.new_articles, outcome.removed_ids, outcome.total_fetched, outcome.processed_ids
    )
    if cache is None:
        return
    if outcome.changed:
        articles, _, _ = await load_articles()
    else:
        articles = cache.articles  # nothing changed: skip reloading the table
    cache.populate(articles, float(refreshed_at), outcome.total_fetched)
    m = _get_metrics()
    m.refreshes.inc()
    m.refresh_dur.observe(elapsed)
    _update_prom_cache(cache.articles, cache.last_refresh)


async def run_refresh(
    emit: Emit,
    *,
    cache: Cache | None = None,
    cfg: ConfigDict | None = None,
    persist: bool = True,
) -> RefreshOutcome:
    """
    Incremental fetch -> score -> persist -> cache, reporting progress via `emit`.

    `emit` is called on the event loop. Raises on failure; `refresh_job` is the
    variant that reports the failure as an `error` event instead. With
    `persist=False` (CLI dry run) nothing is written, pending syncs included.
    """
    t0 = time.perf_counter()
    if cfg is None:
        cfg = load_config()
    topics_cfg = await get_or_seed_scoring_config(cfg, DEFAULT_TOPICS)
    feed_weights = await get_feed_weights()
    if persist:
        await _flush_pending_sync(cfg)
    seen_ids = await get_seen_ids()
    topics = await asyncio.to_thread(build_topics, topics_cfg)

    out = RefreshOutcome()
    batches = fetch_and_score_incremental_iter(cfg, topics, seen_ids, feed_weights)
    try:
        # One chunk per thread hop: fetching and scoring stay off the event loop,
        # while every event is emitted from it.
        while (b := await asyncio.to_thread(next, batches, None)) is not None:
            # Removed IDs go before the first article so the UI can drop them.
            if b.removed_ids and not out.batches:
                emit({"type": "removed", "ids": list(b.removed_ids)})
            out.removed_ids = b.removed_ids
            out.total_fetched = b.total_fetched
            out.processed_ids.extend(b.processed_ids)
            out.batches.append((len(b.processed_ids), len(b.scored)))
            if b.scored:
                msg = f"Récupération : {len(out.new_articles) + len(b.scored)} nouveaux..."
                emit({"type": "progress", "message": msg, "_load_progress": msg})
                for d in b.scored:
                    out.new_articles.append(d)
                    # `d` keeps `_content` for the DB write; clients get a copy without it.
                    emit({"type": "article", "article": strip_content(d)})
    finally:
        close = getattr(batches, "close", None)
        if close is not None:
            close()

    if persist:
        emit({"type": "state", "_load_progress": "Sauvegarde..."})
        await persist_refresh(out, time.perf_counter() - t0, cache)

    if out.changed:
        logger.info(
            "Refresh: %d total unread, +%d new, -%d removed, %d relevant",
            out.total_fetched,
            len(out.new_articles),
            len(out.removed_ids),
            len(cache.articles) if cache is not None else len(out.new_articles),
        )
    else:
        logger.info("Refresh: no changes (0 new, 0 removed)")
    emit(
        {
            "type": "done",
            "total_fetched": out.total_fetched,
            "count": len(cache.articles) if cache is not None else len(out.new_articles),
            "new_count": len(out.new_articles),
            "incremental": True,
            "_load_progress": "Terminé" if out.changed else "Aucun changement",
        }
    )
    return out


async def refresh_job(cache: Cache, forward: Emit | None = None) -> None:
    """
    App refresh: events update `cache`, then go to `forward` (the SSE queue).

    Never raises: a failure becomes an `error` event, so the SSE client and
    /api/status both see it.
    """

    def emit(event: Event) -> None:
        # Applied here, not by the SSE generator: the cache must keep tracking
        # the job after the client disconnects.
        cache.apply(event)
        if forward is not None:
            forward(event)

    try:
        await run_refresh(emit, cache=cache)
    except Exception as e:
        logger.exception("Refresh failed")
        emit(error_event(e))


# ---------------------------------------------------------------------------
# Rescore
# ---------------------------------------------------------------------------


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


async def rescore_compute(
    raw: list[DbArticleRow],
    cfg: ConfigDict,
    topics_cfg: dict[str, Any],
    feed_weights: dict[str, float] | None = None,
) -> list[ArticleDict]:
    """
    Re-score articles across worker processes.

    Scoring is regex-bound and CPython's `re` never releases the GIL, so running
    this through asyncio.to_thread still stalled the event loop for the whole job
    (~4 ms per article, measured). Processes move the work off the loop entirely
    and split it across cores. Falls back to a thread when spawning is impossible
    (restricted container, no /dev/shm) - degraded, but still correct.
    """
    scoring_cfg = cfg.get("scoring", {})
    title_weight = int(scoring_cfg.get("title_weight", 3))
    min_score = float(scoring_cfg.get("min_score", 1.0))
    if not raw:
        return []  # every article was read meanwhile; chunking below needs one

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
    # BrokenProcessPool (a worker killed, e.g. OOM) is a RuntimeError, not an OSError.
    except (OSError, BrokenProcessPool):
        logger.warning("Process pool unavailable - falling back to a single thread")
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
    m = _get_metrics()
    m.rescores.inc()
    m.rescore_dur.observe(elapsed)
    m.rescore_articles.observe(len(raw))
    m.rescore_workers.set(workers)

    merged = [a for chunk in results for a in chunk]
    merged.sort(key=lambda a: a["score"], reverse=True)
    return merged


async def compute_rescore(
    cfg: ConfigDict,
) -> tuple[list[DbArticleRow], list[ArticleDict], int]:
    """Rescore unread DB articles with the active topics and feed weights.

    Returns (raw rows, rescored articles, stored total_fetched). The stored count
    is FreshRSS's unread total: the number of rows rescored is not a substitute.
    """
    raw = await load_for_rescore()
    topics_cfg = await get_or_seed_scoring_config(cfg, DEFAULT_TOPICS)
    feed_weights = await get_feed_weights()
    rescored = await rescore_compute(raw, cfg, topics_cfg, feed_weights)
    total_fetched = int(await get_meta("total_fetched", "0"))
    return raw, rescored, total_fetched


async def persist_rescore(
    cache: Cache | None,
    article_dicts: list[ArticleDict],
    total_fetched: int,
    refresh_time: float | None = None,
) -> None:
    """Save a rescored set (full replace), then refresh the cache when given one."""
    read_meanwhile = await save_articles(article_dicts, total_fetched)
    if cache is None:
        return
    if read_meanwhile:
        article_dicts = [a for a in article_dicts if a["id"] not in read_meanwhile]
    bookmarked = await get_bookmarked_ids()
    for a in article_dicts:
        a["bookmarked"] = a["id"] in bookmarked
    cache.populate(
        article_dicts, refresh_time if refresh_time is not None else time.time(), total_fetched
    )
    _update_prom_cache(cache.articles, cache.last_refresh)


async def rescore_job(cache: Cache) -> None:
    """App rescore: DB -> score -> persist -> cache. Never raises."""
    cache.load_progress = "Démarrage du re-scoring..."
    try:
        _, rescored, total_fetched = await compute_rescore(load_config())
        cache.load_progress = "Sauvegarde..."
        await persist_rescore(cache, rescored, total_fetched, refresh_time=cache.last_refresh)
        cache.load_progress = "Terminé"
        logger.info("Rescore complete: %d relevant articles", len(rescored))
    except Exception as e:
        cache.apply(error_event(e))
        logger.exception("Rescore failed")
