"""CLI commands against a real (file) SQLite DB: persistence stays consistent with the app."""

import argparse
import asyncio
import json
import time
from unittest.mock import patch

import pytest

import config as config_module
from db import (
    get_engine,
    get_seen_ids,
    init_db,
    load_articles,
    record_seen_ids,
    set_articles_read,
    set_engine_for_testing,
)
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
