"""CLI commands against a real (file) SQLite DB: persistence stays consistent with the app."""

import argparse
import asyncio
import concurrent.futures
import json
import time
from unittest.mock import MagicMock, patch

import pytest

import config as config_module
from db import (
    get_engine,
    get_feed_weights,
    get_meta,
    get_scoring_config,
    get_seen_ids,
    init_db,
    load_articles,
    record_seen_ids,
    save_articles,
    set_articles_read,
    set_engine_for_testing,
    set_feed_weights,
    set_scoring_config,
)
from models import Article
from pipeline import IncrementalBatch

_TOPICS = {"Kubernetes": {"weight": 1.0, "keywords": ["kubernetes"]}}


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "config.yaml")
    yield {
        "freshrss": {"url": "http://x", "username": "u", "api_password": "p"},
        "database": {"url": f"sqlite+aiosqlite:///{tmp_path / 'cli.db'}"},
        "scoring": {"min_score": 1.0, "title_weight": 3},
        "topics": _TOPICS,
    }
    set_engine_for_testing(None)


def _db(cfg, fn, *args):
    """Run one DB call on its own loop, as each CLI command does."""

    async def _go():
        await init_db(cfg["database"]["url"])
        try:
            return await fn(*args)
        finally:
            await get_engine().dispose()

    return asyncio.run(_go())


def _article(aid: str, score: float = 5.0) -> dict:
    return {
        "id": aid,
        "title": f"kubernetes {aid}",
        "url": f"https://example.com/{aid}",
        "feed_title": "Feed",
        "published": int(time.time()),
        "score": score,
        "matched_topics": {"Kubernetes": score},
        "matched_keywords": ["kubernetes"],
        "top_topic": "Kubernetes",
        "summary": "kubernetes",
        "_content": "kubernetes cluster",
    }


def _unread_ids(cfg) -> list[str]:
    return sorted(a["id"] for a in _db(cfg, load_articles)[0])


# -- fetch -------------------------------------------------------------------


def test_fetch_records_seen_ids_so_articles_get_reconciled(cfg):
    from cli import cmd_fetch

    args = argparse.Namespace(dry_run=False)
    first = [IncrementalBatch([_article("a")], set(), 2, ["a", "low"])]
    with patch("refresh_service.fetch_and_score_incremental_iter", return_value=iter(first)):
        assert cmd_fetch(args, cfg) == 0

    assert _db(cfg, get_seen_ids) == {"a", "low"}
    assert _unread_ids(cfg) == ["a"]

    # Read upstream since: the next fetch must mark it read, not keep it forever.
    second = [IncrementalBatch([], {"a", "low"}, 0, [])]
    with patch("refresh_service.fetch_and_score_incremental_iter", return_value=iter(second)):
        assert cmd_fetch(args, cfg) == 0

    assert _unread_ids(cfg) == []
    assert _db(cfg, get_seen_ids) == set()


def test_fetch_dry_run_writes_nothing(cfg):
    from cli import cmd_fetch

    batches = [IncrementalBatch([_article("a")], set(), 1, ["a"])]
    with patch("refresh_service.fetch_and_score_incremental_iter", return_value=iter(batches)):
        assert cmd_fetch(argparse.Namespace(dry_run=True), cfg) == 0

    assert _db(cfg, get_seen_ids) == set()
    assert _unread_ids(cfg) == []


# -- import ------------------------------------------------------------------


def test_import_records_seen_ids_and_keeps_read_rows_read(cfg, tmp_path):
    from cli import cmd_import

    data = tmp_path / "articles.json"
    data.write_text(
        json.dumps(
            [
                {"id": "i1", "title": "kubernetes one", "content": "kubernetes"},
                {"id": "i2", "title": "kubernetes two", "content": "kubernetes"},
            ]
        )
    )
    args = argparse.Namespace(starred=False, file=str(data), dry_run=False, limit=None)
    _db(cfg, record_seen_ids, ["other"])  # non-empty: init_db's one-off backfill stays out

    assert cmd_import(args, cfg) == 0
    assert _db(cfg, get_seen_ids) >= {"i1", "i2"}

    _db(cfg, set_articles_read, ["i2"])
    assert cmd_import(args, cfg) == 0

    assert _unread_ids(cfg) == ["i1"], "a read article must not come back unread"


# -- rescore -----------------------------------------------------------------


def test_rescore_uses_db_feed_weights_and_keeps_total_fetched(cfg):
    from cli import cmd_rescore

    _db(cfg, set_scoring_config, _TOPICS)
    _db(cfg, save_articles, [_article("a")], 42)
    _db(cfg, set_feed_weights, {"Feed": 2.0})

    with patch(
        "refresh_service.concurrent.futures.ProcessPoolExecutor",
        concurrent.futures.ThreadPoolExecutor,
    ):
        assert cmd_rescore(argparse.Namespace(dry_run=False), cfg) == 0

    articles, _, total_fetched = _db(cfg, load_articles)
    assert total_fetched == 42, "the stored FreshRSS unread count must survive a rescore"
    # title (x3) + body match on "kubernetes" at weight 1.0, doubled by the feed weight
    assert articles[0]["score"] == pytest.approx(2 * (3 + 1))


# -- tune --------------------------------------------------------------------


def _starred_client():
    starred = [
        Article(
            id=f"s{i}",
            title="kubernetes upgrade",
            url="https://example.com",
            content="kubernetes",
            summary="",
            feed_title="Feed",
            published=0,
        )
        for i in range(3)
    ]
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.fetch_starred.return_value = starred
    return client


def test_tune_apply_writes_active_db_scoring_config(cfg):
    from cli import cmd_tune

    _db(cfg, set_scoring_config, _TOPICS)

    with patch("cli.make_client", return_value=_starred_client()):
        assert cmd_tune(argparse.Namespace(apply=True, limit=None), cfg) == 0

    stored = _db(cfg, get_scoring_config)
    assert stored["Kubernetes"]["weight"] == pytest.approx(1.5)
    assert stored["Kubernetes"]["keywords"] == ["kubernetes"]
    assert not config_module.CONFIG_PATH.exists(), "config.yaml is not the active config"


def test_tune_reads_feed_weights_from_db(cfg):
    import scorer
    from cli import cmd_tune

    _db(cfg, set_scoring_config, _TOPICS)
    _db(cfg, set_feed_weights, {"Feed": 3.0})
    seen: list = []
    real = scorer.analyze_favorites

    def _spy(*a, **kw):
        seen.append(kw.get("feed_weights"))
        return real(*a, **kw)

    with (
        patch("cli.make_client", return_value=_starred_client()),
        patch("scorer.analyze_favorites", _spy),
    ):
        assert cmd_tune(argparse.Namespace(apply=False, limit=None), cfg) == 0

    assert seen == [{"Feed": 3.0}]
    assert _db(cfg, get_feed_weights) == {"Feed": 3.0}
    assert _db(cfg, get_meta, "total_fetched", "unset") == "unset"


# -- isolation ---------------------------------------------------------------


def test_cli_default_db_resolves_inside_tmp_path(tmp_path):
    from cli import _init_db

    async def _resolved() -> str:
        await _init_db({"database": {}})
        try:
            return str(get_engine().url.database)
        finally:
            await get_engine().dispose()

    try:
        resolved = asyncio.run(_resolved())
    finally:
        set_engine_for_testing(None)
    assert resolved.startswith(str(tmp_path)), resolved
