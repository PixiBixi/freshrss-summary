"""Refresh orchestrator: event stream, persistence and error reporting."""

import time
from unittest.mock import MagicMock, patch

import pytest

import refresh_service
from db import add_pending_sync, get_meta, get_pending_sync, get_seen_ids, load_articles
from pipeline import IncrementalBatch
from refresh_service import Cache, refresh_job, run_refresh

_CFG = {"freshrss": {"url": "http://x", "username": "u", "api_password": "p"}}


def _article(aid: str, score: float = 5.0) -> dict:
    return {
        "id": aid,
        "title": f"title {aid}",
        "url": f"https://example.com/{aid}",
        "feed_title": "Feed",
        "published": int(time.time()),
        "score": score,
        "matched_topics": {"Kubernetes": score},
        "matched_keywords": ["kubernetes"],
        "top_topic": "Kubernetes",
        "summary": "s",
        "_content": "full text",
    }


def _upstream(batches):
    return patch("refresh_service.fetch_and_score_incremental_iter", return_value=iter(batches))


async def test_events_are_ordered_and_state_is_persisted(db):
    events: list[dict] = []
    cache = Cache()
    batches = [
        IncrementalBatch([_article("a")], {"gone"}, 3, ["a", "low"]),
        IncrementalBatch([_article("b")], {"gone"}, 3, ["b"]),
    ]
    with _upstream(batches):
        out = await run_refresh(events.append, cache=cache, cfg=_CFG)

    types = [e["type"] for e in events]
    assert types == ["removed", "progress", "article", "progress", "article", "state", "done"]
    assert all("_content" not in e["article"] for e in events if e["type"] == "article")
    assert events[-1]["count"] == 2
    assert events[-1]["new_count"] == 2
    assert events[-1]["_load_progress"] == "Terminé"
    assert out.batches == [(2, 1), (1, 1)]
    assert await get_seen_ids() == {"a", "b", "low"}
    assert [a["id"] for a in cache.articles] == ["a", "b"]
    assert cache.total_fetched == 3


async def test_noop_refresh_reports_no_change(db):
    events: list[dict] = []
    with _upstream([IncrementalBatch([], set(), 0, [])]):
        await run_refresh(events.append, cache=Cache(), cfg=_CFG)

    assert [e["type"] for e in events] == ["state", "done"]
    assert events[-1]["_load_progress"] == "Aucun changement"


async def test_dry_run_writes_nothing(db):
    await add_pending_sync(["queued"])
    shared = MagicMock()
    with (
        _upstream([IncrementalBatch([_article("a")], set(), 1, ["a"])]),
        patch("refresh_service.get_shared_client", return_value=shared),
    ):
        out = await run_refresh(lambda e: None, cfg=_CFG, persist=False)

    assert [a["id"] for a in out.new_articles] == ["a"]
    assert await get_seen_ids() == set()
    assert (await load_articles())[0] == []
    assert await get_meta("last_refresh", "") == ""
    shared.mark_as_read.assert_not_called()
    assert await get_pending_sync() == ["queued"]


async def test_pending_read_syncs_are_flushed(db):
    await add_pending_sync(["queued"])
    shared = MagicMock()
    with (
        _upstream([IncrementalBatch([], set(), 0, [])]),
        patch("refresh_service.get_shared_client", return_value=shared),
    ):
        await run_refresh(lambda e: None, cfg=_CFG)

    shared.mark_as_read.assert_called_once_with(["queued"])
    assert await get_pending_sync() == []


async def test_persist_without_cache_still_writes_db(db):
    with _upstream([IncrementalBatch([_article("a")], set(), 7, ["a"])]):
        await run_refresh(lambda e: None, cfg=_CFG)

    articles, last_refresh, total = await load_articles()
    assert [a["id"] for a in articles] == ["a"]
    assert last_refresh is not None
    assert total == 7


async def test_refresh_job_reports_failure_as_error_event(db):
    cache = Cache()
    forwarded: list[dict] = []
    with (
        patch("refresh_service.load_config", return_value=_CFG),
        patch(
            "refresh_service.fetch_and_score_incremental_iter",
            side_effect=RuntimeError("boom"),
        ),
    ):
        await refresh_job(cache, forwarded.append)

    assert forwarded[-1]["type"] == "error"
    assert forwarded[-1]["message"] == "boom"
    assert cache.error == "RuntimeError: boom"
    assert cache.load_progress == "Erreur"


async def test_run_refresh_raises_for_direct_callers(db):
    with (
        patch(
            "refresh_service.fetch_and_score_incremental_iter",
            side_effect=RuntimeError("boom"),
        ),
        pytest.raises(RuntimeError, match="boom"),
    ):
        await run_refresh(lambda e: None, cfg=_CFG)


async def test_upstream_generator_is_closed_on_failure(db):
    closed = False

    def _gen(*a, **kw):
        nonlocal closed
        try:
            yield IncrementalBatch([_article("a")], set(), 1, ["a"])
            yield IncrementalBatch([_article("b")], set(), 1, ["b"])
        finally:
            closed = True

    def _emit(event):
        if event["type"] == "article":
            raise RuntimeError("consumer failed")

    with (
        patch.object(refresh_service, "fetch_and_score_incremental_iter", _gen),
        pytest.raises(RuntimeError),
    ):
        await run_refresh(_emit, cfg=_CFG)

    assert closed, "the FreshRSS client context must be released"
