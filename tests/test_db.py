"""Unit tests for db.py — async SQLAlchemy, in-memory SQLite."""

import time

from db import (
    add_pending_sync,
    add_snooze,
    clear_pending_sync,
    delete_snooze,
    get_bookmarked_ids,
    get_due_snoozes,
    get_pending_sync,
    get_scoring_config,
    get_user_hash,
    has_users,
    load_articles,
    load_for_rescore,
    load_read_articles,
    save_articles,
    set_articles_read,
    set_scoring_config,
    toggle_bookmark,
    upsert_user,
)


def _article(
    id="art-1",
    title="Test Article",
    url="http://example.com",
    feed="Test Feed",
    published=None,
    score=5.0,
) -> dict:
    return {
        "id": id,
        "title": title,
        "url": url,
        "feed_title": feed,
        "published": published or int(time.time()),
        "score": score,
        "matched_topics": {"k8s": score},
        "matched_keywords": ["kubernetes"],
        "top_topic": "k8s",
        "summary": "A short summary",
        "_content": "Full article content here",
    }


# ── save / load ───────────────────────────────────────────────────────────────


class TestSaveAndLoad:
    async def test_roundtrip(self, db):
        articles = [_article(id="1"), _article(id="2", score=10.0)]
        await save_articles(articles, total_fetched=2)

        loaded, last_refresh, total = await load_articles()
        assert len(loaded) == 2
        assert total == 2
        assert last_refresh is not None

    async def test_sorted_by_score_desc(self, db):
        await save_articles(
            [_article(id="lo", score=1.0), _article(id="hi", score=20.0)], total_fetched=2
        )
        loaded, _, _ = await load_articles()
        assert loaded[0]["id"] == "hi"

    async def test_save_replaces_unread(self, db):
        await save_articles([_article(id="old")], total_fetched=1)
        await save_articles([_article(id="new")], total_fetched=1)
        loaded, _, _ = await load_articles()
        ids = {a["id"] for a in loaded}
        assert "old" not in ids
        assert "new" in ids

    async def test_empty_db(self, db):
        loaded, last_refresh, total = await load_articles()
        assert loaded == []
        assert last_refresh is None
        assert total == 0

    async def test_meta_total_fetched(self, db):
        await save_articles([_article()], total_fetched=42)
        _, _, total = await load_articles()
        assert total == 42

    async def test_save_empty_list(self, db):
        await save_articles([], total_fetched=5)
        loaded, _, total = await load_articles()
        assert loaded == []
        assert total == 5  # meta still written


# ── soft delete ───────────────────────────────────────────────────────────────


class TestSoftDelete:
    async def test_set_read_removes_from_unread(self, db):
        await save_articles([_article(id="1"), _article(id="2")], total_fetched=2)
        await set_articles_read(["1"])
        loaded, _, _ = await load_articles()
        ids = {a["id"] for a in loaded}
        assert "1" not in ids
        assert "2" in ids

    async def test_read_articles_survive_next_save(self, db):
        await save_articles([_article(id="1")], total_fetched=1)
        await set_articles_read(["1"])
        # New refresh — should not wipe soft-deleted article
        await save_articles([_article(id="2")], total_fetched=1)
        # load_articles only returns unread
        loaded, _, _ = await load_articles()
        ids = {a["id"] for a in loaded}
        assert "1" not in ids
        assert "2" in ids

    async def test_load_read_articles(self, db):
        await save_articles([_article(id="1"), _article(id="2")], total_fetched=2)
        await set_articles_read(["1"])
        read = await load_read_articles(days=7)
        ids = {a["id"] for a in read}
        assert "1" in ids
        assert "2" not in ids

    async def test_read_article_has_read_flag(self, db):
        await save_articles([_article(id="1")], total_fetched=1)
        await set_articles_read(["1"])
        read = await load_read_articles(days=7)
        assert read[0]["_read"] is True

    async def test_empty_ids_is_noop(self, db):
        await save_articles([_article(id="1")], total_fetched=1)
        await set_articles_read([])  # must not raise
        loaded, _, _ = await load_articles()
        assert len(loaded) == 1


# ── bookmarks ─────────────────────────────────────────────────────────────────


class TestBookmarks:
    async def test_toggle_adds(self, db):
        await save_articles([_article(id="1")], total_fetched=1)
        result = await toggle_bookmark("1")
        assert result is True

    async def test_toggle_removes(self, db):
        await save_articles([_article(id="1")], total_fetched=1)
        await toggle_bookmark("1")
        result = await toggle_bookmark("1")
        assert result is False

    async def test_get_bookmarked_ids(self, db):
        await save_articles([_article(id="1"), _article(id="2")], total_fetched=2)
        await toggle_bookmark("1")
        ids = await get_bookmarked_ids()
        assert "1" in ids
        assert "2" not in ids

    async def test_bookmark_removed_on_mark_read(self, db):
        await save_articles([_article(id="1")], total_fetched=1)
        await toggle_bookmark("1")
        await set_articles_read(["1"])
        ids = await get_bookmarked_ids()
        assert "1" not in ids

    async def test_load_articles_includes_bookmarked_flag(self, db):
        await save_articles([_article(id="1"), _article(id="2")], total_fetched=2)
        await toggle_bookmark("1")
        loaded, _, _ = await load_articles()
        by_id = {a["id"]: a for a in loaded}
        assert by_id["1"]["bookmarked"] is True
        assert by_id["2"]["bookmarked"] is False


# ── users ─────────────────────────────────────────────────────────────────────


class TestUsers:
    async def test_has_users_empty(self, db):
        assert await has_users() is False

    async def test_has_users_after_insert(self, db):
        await upsert_user("alice", "hash")
        assert await has_users() is True

    async def test_get_user_hash_existing(self, db):
        await upsert_user("alice", "myhash")
        result = await get_user_hash("alice")
        assert result == "myhash"

    async def test_get_user_hash_missing(self, db):
        assert await get_user_hash("nobody") is None

    async def test_upsert_updates_existing(self, db):
        await upsert_user("alice", "oldhash")
        await upsert_user("alice", "newhash")
        assert await get_user_hash("alice") == "newhash"

    async def test_multiple_users(self, db):
        await upsert_user("alice", "hash_a")
        await upsert_user("bob", "hash_b")
        assert await get_user_hash("alice") == "hash_a"
        assert await get_user_hash("bob") == "hash_b"


# ── pending sync ─────────────────────────────────────────────────────────────


class TestPendingSync:
    async def test_add_and_get(self, db):
        await add_pending_sync(["1", "2", "3"])
        ids = await get_pending_sync()
        assert set(ids) == {"1", "2", "3"}

    async def test_add_idempotent(self, db):
        await add_pending_sync(["1"])
        await add_pending_sync(["1"])  # duplicate
        ids = await get_pending_sync()
        assert ids.count("1") == 1

    async def test_clear_removes_ids(self, db):
        await add_pending_sync(["1", "2"])
        await clear_pending_sync(["1"])
        ids = await get_pending_sync()
        assert "1" not in ids
        assert "2" in ids

    async def test_clear_empty_is_noop(self, db):
        await add_pending_sync(["1"])
        await clear_pending_sync([])  # must not raise
        ids = await get_pending_sync()
        assert "1" in ids

    async def test_empty_pending_returns_empty(self, db):
        assert await get_pending_sync() == []


# ── load_for_rescore ──────────────────────────────────────────────────────────


class TestScoringConfig:
    async def test_returns_none_when_not_set(self, db):
        assert await get_scoring_config() is None

    async def test_roundtrip(self, db):
        topics = {
            "Kubernetes": {"keywords": ["kubernetes", "kubectl"], "weight": 1.5},
            "SRE": {"keywords": ["sre", "slo"], "weight": 1.0},
        }
        await set_scoring_config(topics)
        result = await get_scoring_config()
        assert result == topics

    async def test_overwrite_updates(self, db):
        await set_scoring_config({"Old": {"keywords": ["old"], "weight": 1.0}})
        await set_scoring_config({"New": {"keywords": ["new"], "weight": 2.0}})
        result = await get_scoring_config()
        assert "New" in result
        assert "Old" not in result


class TestLoadForRescore:
    async def test_returns_content(self, db):
        await save_articles([_article(id="1")], total_fetched=1)
        rows = await load_for_rescore()
        assert len(rows) == 1
        assert rows[0]["content"] == "Full article content here"
        assert rows[0]["id"] == "1"

    async def test_returns_required_fields(self, db):
        await save_articles([_article()], total_fetched=1)
        rows = await load_for_rescore()
        row = rows[0]
        for key in ("id", "title", "url", "feed_title", "published", "content"):
            assert key in row, f"Missing field: {key}"


# ── snooze ────────────────────────────────────────────────────────────────────


class TestSnooze:
    async def test_add_and_get_due(self, db):
        past = int(time.time()) - 10
        await add_snooze("art-1", "42", past, "My Article", "https://example.com")
        due = await get_due_snoozes()
        assert len(due) == 1
        assert due[0]["article_id"] == "art-1"
        assert due[0]["title"] == "My Article"

    async def test_not_due_in_future(self, db):
        future = int(time.time()) + 3600
        await add_snooze("art-1", "42", future, "My Article", "https://example.com")
        due = await get_due_snoozes()
        assert due == []

    async def test_delete_snooze(self, db):
        past = int(time.time()) - 10
        await add_snooze("art-1", "42", past, "My Article", "https://example.com")
        await delete_snooze("art-1")
        due = await get_due_snoozes()
        assert due == []

    async def test_add_snooze_overwrites(self, db):
        """Adding a snooze for the same article replaces the existing one."""
        past = int(time.time()) - 10
        future = int(time.time()) + 3600
        await add_snooze("art-1", "42", past, "Old Title", "https://old.com")
        await add_snooze("art-1", "42", future, "New Title", "https://new.com")
        due = await get_due_snoozes()
        assert due == []  # now in the future, not due
