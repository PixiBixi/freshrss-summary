"""Route handler tests using httpx AsyncClient + ASGITransport."""

import asyncio
import json
import time

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from app import app, cache
from db import metadata, set_engine_for_testing
from pipeline import IncrementalBatch
from tests.conftest import TEST_DB_URL

_ARTICLE = {
    "id": "tag:a",
    "title": "K8s guide",
    "url": "https://example.com/k8s",
    "feed_title": "CNCF",
    "published": int(time.time()) - 3600,  # 1 hour ago - within any days window
    "score": 12.0,
    "matched_topics": {"Kubernetes": 12.0},
    "matched_keywords": ["kubernetes"],
    "top_topic": "Kubernetes",
    "summary": "A guide to Kubernetes.",
    "bookmarked": False,
}


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    set_engine_for_testing(engine)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()
    set_engine_for_testing(None)


@pytest_asyncio.fixture
async def client(db_engine):
    cache.initialized = True  # simulate post-lifespan state
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    cache.initialized = False


@pytest_asyncio.fixture
async def authed_client(db_engine):
    """Client with an authenticated session via login."""
    import os

    from auth import hash_password
    from db import upsert_user

    await upsert_user("admin", hash_password("testpass"))
    os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests")

    cache.initialized = True  # simulate post-lifespan state
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/login", data={"username": "admin", "password": "testpass"})
        assert resp.status_code in (200, 303)
        yield ac
    cache.initialized = False


# ── /api/articles ──────────────────────────────────────────────────────────────


class TestGetArticles:
    async def test_returns_empty_when_cache_empty(self, client):
        cache.articles = []
        resp = await client.get("/api/articles")
        assert resp.status_code == 200
        data = resp.json()
        assert data["articles"] == []
        assert data["total"] == 0

    async def test_returns_articles_from_cache(self, client):
        cache.articles = [dict(_ARTICLE)]
        resp = await client.get("/api/articles")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["articles"]) == 1
        assert data["articles"][0]["id"] == "tag:a"

    async def test_days_filter_excludes_old_articles(self, client):
        import time

        old = dict(_ARTICLE, id="old", published=int(time.time()) - 30 * 86400)
        recent = dict(_ARTICLE, id="recent", published=int(time.time()) - 1 * 86400)
        cache.articles = [old, recent]

        resp = await client.get("/api/articles?days=7")
        assert resp.status_code == 200
        ids = [a["id"] for a in resp.json()["articles"]]
        assert "recent" in ids
        assert "old" not in ids

    async def test_days_0_returns_all(self, client):
        import time

        old = dict(_ARTICLE, id="old", published=int(time.time()) - 30 * 86400)
        cache.articles = [old]
        resp = await client.get("/api/articles?days=0")
        assert resp.status_code == 200
        assert len(resp.json()["articles"]) == 1

    async def test_min_score_filter(self, client):
        low = dict(_ARTICLE, id="low", score=2.0)
        high = dict(_ARTICLE, id="high", score=50.0)
        cache.articles = [low, high]
        resp = await client.get("/api/articles?min_score=10")
        ids = [a["id"] for a in resp.json()["articles"]]
        assert "high" in ids
        assert "low" not in ids

    async def test_topic_filter(self, client):
        k8s = dict(_ARTICLE, id="k8s", matched_topics={"Kubernetes": 5.0})
        sre = dict(_ARTICLE, id="sre", matched_topics={"SRE": 3.0})
        cache.articles = [k8s, sre]
        resp = await client.get("/api/articles?topic=Kubernetes")
        ids = [a["id"] for a in resp.json()["articles"]]
        assert "k8s" in ids
        assert "sre" not in ids


class TestShowReadFilters:
    async def test_read_articles_go_through_the_same_filters(self, authed_client, db_engine):
        from db import save_articles, set_articles_read

        off_topic = dict(_ARTICLE, id="read-sre", matched_topics={"SRE": 3.0}, score=3.0)
        low = dict(_ARTICLE, id="read-low", score=1.0)
        old = dict(_ARTICLE, id="read-old", published=int(time.time()) - 30 * 86400)
        kept = dict(_ARTICLE, id="read-kept")
        await save_articles([off_topic, low, old, kept], total_fetched=4)
        await set_articles_read(["read-sre", "read-low", "read-old", "read-kept"])
        cache.articles = [dict(_ARTICLE)]

        resp = await authed_client.get(
            "/api/articles?show_read=true&topic=Kubernetes&min_score=5&days=7"
        )

        data = resp.json()
        assert sorted(a["id"] for a in data["articles"]) == ["read-kept", "tag:a"]
        assert data["total"] == 2


# ── /api/mark-read ─────────────────────────────────────────────────────────────


class TestMarkRead:
    async def test_requires_auth(self, client, db_engine):
        resp = await client.post(
            "/api/mark-read",
            json={"article_ids": ["tag:a"]},
        )
        assert resp.status_code == 401

    async def test_marks_article_authenticated(self, authed_client, db_engine):
        from db import save_articles

        await save_articles([dict(_ARTICLE)], total_fetched=1)
        cache.articles = [dict(_ARTICLE)]

        resp = await authed_client.post(
            "/api/mark-read",
            json={"article_ids": ["tag:a"]},
        )
        assert resp.status_code == 200
        assert cache.articles == []

    async def test_empty_ids_returns_400(self, authed_client, db_engine):
        resp = await authed_client.post("/api/mark-read", json={"article_ids": []})
        assert resp.status_code == 400


# ── /health ────────────────────────────────────────────────────────────────────


class TestHealth:
    async def test_health_ok_with_db(self, client, db_engine):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["db"] == "ok"

    async def test_health_no_auth_required(self, client, db_engine):
        """Health endpoint is public - no session needed."""
        resp = await client.get("/health")
        assert resp.status_code == 200

    async def test_health_returns_article_count(self, client, db_engine):
        cache.articles = [dict(_ARTICLE)]
        resp = await client.get("/health")
        assert resp.json()["articles"] == 1
        cache.articles = []


class TestLogin:
    async def test_get_login_page(self, client, db_engine):
        resp = await client.get("/login")
        assert resp.status_code == 200
        assert b"login" in resp.content.lower()

    async def test_login_success_redirects(self, db_engine):
        import os

        from auth import hash_password
        from db import upsert_user

        await upsert_user("admin", hash_password("testpass"))
        os.environ.setdefault("SECRET_KEY", "test-secret-key")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/login", data={"username": "admin", "password": "testpass"})
        assert resp.status_code in (200, 303)

    async def test_login_wrong_password(self, db_engine):
        import os

        from auth import hash_password
        from db import upsert_user

        await upsert_user("admin", hash_password("testpass"))
        os.environ.setdefault("SECRET_KEY", "test-secret-key")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/login", data={"username": "admin", "password": "wrong"})
        assert resp.status_code == 401


class TestLogout:
    async def test_logout_redirects_to_login(self, client, db_engine):
        resp = await client.post("/logout")
        assert resp.status_code in (200, 303)


class TestApiStatus:
    async def test_status_public(self, client, db_engine):
        resp = await client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "article_count" in data
        assert "is_loading" in data

    async def test_status_includes_cache_size(self, client, db_engine):
        cache.articles = [dict(_ARTICLE)]
        resp = await client.get("/api/status")
        assert resp.json()["article_count"] == 1
        cache.articles = []


class TestMarkReadAuthGuard:
    async def test_mark_read_requires_auth(self, client, db_engine):
        resp = await client.post("/api/mark-read", json={"article_ids": ["tag:a"]})
        assert resp.status_code in (401, 403)

    async def test_mark_read_authed(self, authed_client, db_engine):
        resp = await authed_client.post("/api/mark-read", json={"article_ids": ["tag:nonexistent"]})
        assert resp.status_code == 200


class TestApiArticlesFilter:
    async def test_filter_by_topic(self, client, db_engine):
        cache.articles = [dict(_ARTICLE)]
        resp = await client.get("/api/articles?topic=Kubernetes")
        assert resp.status_code == 200
        data = resp.json()
        assert all("Kubernetes" in a["matched_topics"] for a in data["articles"])
        cache.articles = []

    async def test_filter_by_min_score(self, client, db_engine):
        cache.articles = [dict(_ARTICLE)]
        resp = await client.get("/api/articles?min_score=100")
        assert resp.status_code == 200
        assert resp.json()["articles"] == []
        cache.articles = []

    async def test_search_query(self, client, db_engine):
        cache.articles = [dict(_ARTICLE)]
        resp = await client.get("/api/articles?q=K8s")
        assert resp.status_code == 200
        cache.articles = []


# ── /api/refresh/stream ────────────────────────────────────────────────────────


class TestRefreshStream:
    async def test_busy_returns_single_busy_event(self, authed_client):
        """When is_loading=True, SSE returns a single 'busy' event then closes."""
        cache.is_loading = True
        try:
            events = []
            async with authed_client.stream("GET", "/api/refresh/stream") as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        events.append(json.loads(line[6:]))
            assert len(events) == 1
            assert events[0]["type"] == "busy"
        finally:
            cache.is_loading = False

    async def test_happy_path_streams_progress_article_done(self, authed_client):
        """Full fetch→score→stream→persist path via mocked dependencies."""
        from unittest.mock import AsyncMock, patch

        article = dict(_ARTICLE)

        with (
            patch("refresh_service.build_topics", return_value={}),
            patch(
                "refresh_service.fetch_and_score_incremental_iter",
                # yields IncrementalBatch(scored, removed_ids, total_fetched, processed_ids)
                return_value=iter([IncrementalBatch([article], set(), 1, [article["id"]])]),
            ),
            patch(
                "refresh_service.load_config",
                return_value={
                    "freshrss": {"url": "http://x", "username": "u", "api_password": "p"}
                },
            ),
            patch(
                "refresh_service.get_or_seed_scoring_config",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("refresh_service.get_feed_weights", new_callable=AsyncMock, return_value={}),
            patch("refresh_service.get_seen_ids", new_callable=AsyncMock, return_value=set()),
            patch("refresh_service.persist_refresh", new_callable=AsyncMock),
        ):
            events = []
            async with authed_client.stream("GET", "/api/refresh/stream") as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        evt = json.loads(line[6:])
                        events.append(evt)
                        if evt["type"] in ("done", "error"):
                            break

        types = [e["type"] for e in events]
        assert "progress" in types
        assert "article" in types
        assert "done" in types
        assert not cache.is_loading

    async def test_worker_exception_sends_error_event(self, authed_client):
        """When the fetch worker raises, SSE sends an 'error' event and clears is_loading."""
        from unittest.mock import AsyncMock, patch

        with (
            patch("refresh_service.build_topics", return_value={}),
            patch(
                "refresh_service.fetch_and_score_incremental_iter",
                side_effect=RuntimeError("fetch failed"),
            ),
            patch(
                "refresh_service.load_config",
                return_value={
                    "freshrss": {"url": "http://x", "username": "u", "api_password": "p"}
                },
            ),
            patch(
                "refresh_service.get_or_seed_scoring_config",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("refresh_service.get_feed_weights", new_callable=AsyncMock, return_value={}),
            patch("refresh_service.get_seen_ids", new_callable=AsyncMock, return_value=set()),
        ):
            events = []
            async with authed_client.stream("GET", "/api/refresh/stream") as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        evt = json.loads(line[6:])
                        events.append(evt)
                        if evt["type"] in ("done", "error"):
                            break

        types = [e["type"] for e in events]
        assert "error" in types
        assert not cache.is_loading


# ── /api/rescore ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def authed_client_no_ratelimit(db_engine):
    """Authenticated client with rate limiting disabled - avoids 429 in test suites."""
    import os
    from unittest.mock import patch

    from auth import hash_password
    from db import upsert_user

    await upsert_user("admin", hash_password("testpass"))
    os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests")

    cache.initialized = True
    transport = ASGITransport(app=app)
    with patch("app.login_rate_limit", return_value=True):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/login", data={"username": "admin", "password": "testpass"})
            assert resp.status_code in (200, 303)
            yield ac
    cache.initialized = False


class TestRescore:
    async def test_rescore_requires_auth(self, client, db_engine):
        resp = await client.post("/api/rescore")
        assert resp.status_code in (401, 403)

    async def test_rescore_returns_started_when_articles_in_cache(
        self, authed_client_no_ratelimit, db_engine
    ):
        from unittest.mock import AsyncMock, patch

        cache.articles = [dict(_ARTICLE)]
        try:
            with patch("app._do_rescore_from_db", new_callable=AsyncMock):
                resp = await authed_client_no_ratelimit.post("/api/rescore")
            assert resp.status_code == 200
            assert resp.json()["status"] in ("started", "already_loading")
        finally:
            cache.articles = []

    async def test_rescore_returns_busy_when_loading(self, authed_client_no_ratelimit, db_engine):
        cache.is_loading = True
        cache.load_progress = "Fetching..."
        try:
            resp = await authed_client_no_ratelimit.post("/api/rescore")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "already_loading"
        finally:
            cache.is_loading = False
            cache.load_progress = ""


# ── /api/bookmark ─────────────────────────────────────────────────────────────


class TestBookmark:
    async def test_bookmark_requires_auth(self, client, db_engine):
        resp = await client.post("/api/bookmark", json={"article_id": "tag:a"})
        assert resp.status_code in (401, 403)

    async def test_bookmark_returns_404_when_article_not_in_cache(
        self, authed_client_no_ratelimit, db_engine
    ):
        cache.articles = []
        resp = await authed_client_no_ratelimit.post(
            "/api/bookmark", json={"article_id": "tag:missing"}
        )
        assert resp.status_code == 404

    async def test_bookmark_toggles_state(self, authed_client_no_ratelimit, db_engine):
        from db import save_articles

        article = dict(_ARTICLE, bookmarked=False)
        await save_articles([article], total_fetched=1)
        cache.articles = [dict(article)]

        resp = await authed_client_no_ratelimit.post("/api/bookmark", json={"article_id": "tag:a"})
        assert resp.status_code == 200
        data = resp.json()
        assert "bookmarked" in data

        cache.articles = []


# ── /api/snooze ────────────────────────────────────────────────────────────────


class TestSnooze:
    async def test_snooze_requires_auth(self, client, db_engine):
        resp = await client.post("/api/snooze", json={"article_id": "tag:a"})
        assert resp.status_code in (401, 403)

    async def test_snooze_returns_404_when_article_not_in_cache(
        self, authed_client_no_ratelimit, db_engine
    ):
        cache.articles = []
        resp = await authed_client_no_ratelimit.post(
            "/api/snooze", json={"article_id": "tag:missing"}
        )
        assert resp.status_code == 404

    async def test_snooze_returns_400_when_telegram_not_configured(
        self, authed_client_no_ratelimit, db_engine
    ):
        cache.articles = [dict(_ARTICLE)]
        try:
            resp = await authed_client_no_ratelimit.post(
                "/api/snooze", json={"article_id": "tag:a"}
            )
            # Without Telegram config, returns 400
            assert resp.status_code == 400
        finally:
            cache.articles = []


# ── /api/config/scoring ────────────────────────────────────────────────────────


class TestScoringConfig:
    async def test_get_requires_auth(self, client, db_engine):
        resp = await client.get("/api/config/scoring")
        assert resp.status_code in (401, 403)

    async def test_put_requires_auth(self, client, db_engine):
        resp = await client.put("/api/config/scoring", json={"topics": {}, "feed_weights": {}})
        assert resp.status_code in (401, 403)

    async def test_put_and_get_roundtrip(self, authed_client_no_ratelimit, db_engine):
        topics = {"SRE": {"weight": 2.0, "keywords": ["sre", "incident"]}}
        resp = await authed_client_no_ratelimit.put(
            "/api/config/scoring", json={"topics": topics, "feed_weights": {}}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        resp = await authed_client_no_ratelimit.get("/api/config/scoring")
        assert resp.status_code == 200
        data = resp.json()
        assert "SRE" in data["topics"]

    async def test_put_rejects_out_of_range_feed_weight(
        self, authed_client_no_ratelimit, db_engine
    ):
        resp = await authed_client_no_ratelimit.put(
            "/api/config/scoring",
            json={"topics": {}, "feed_weights": {"My Feed": 99.0}},
        )
        assert resp.status_code == 422


# ── /api/change-password ──────────────────────────────────────────────────────


class TestChangePassword:
    async def test_requires_auth(self, client, db_engine):
        resp = await client.post(
            "/api/change-password",
            json={"current_password": "testpass", "new_password": "newpass123"},
        )
        assert resp.status_code in (401, 403)

    async def test_wrong_current_password_returns_400(self, authed_client_no_ratelimit, db_engine):
        resp = await authed_client_no_ratelimit.post(
            "/api/change-password",
            json={"current_password": "wrongpass", "new_password": "newpass123"},
        )
        assert resp.status_code == 400

    async def test_too_short_new_password_returns_400(self, authed_client_no_ratelimit, db_engine):
        resp = await authed_client_no_ratelimit.post(
            "/api/change-password",
            json={"current_password": "testpass", "new_password": "short"},
        )
        assert resp.status_code == 400

    async def test_success_returns_200(self, authed_client_no_ratelimit, db_engine):
        resp = await authed_client_no_ratelimit.post(
            "/api/change-password",
            json={"current_password": "testpass", "new_password": "newpassword123"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ── Smoke tests for remaining endpoints ───────────────────────────────────────


class TestSmokeEndpoints:
    async def test_api_feeds_requires_auth(self, client, db_engine):
        resp = await client.get("/api/feeds")
        assert resp.status_code in (401, 403)

    async def test_api_feeds_returns_list(self, authed_client_no_ratelimit, db_engine):
        resp = await authed_client_no_ratelimit.get("/api/feeds")
        assert resp.status_code == 200
        assert "feeds" in resp.json()

    async def test_metrics_requires_auth(self, client, db_engine):
        resp = await client.get("/metrics")
        assert resp.status_code in (401, 403)

    async def test_metrics_returns_prometheus_text(self, authed_client_no_ratelimit, db_engine):
        resp = await authed_client_no_ratelimit.get("/metrics")
        assert resp.status_code == 200


class TestRefreshConcurrency:
    """Concurrent refresh requests must not start more than one job.

    The guard used to test `cache.is_loading` in the handler while the worker set
    it several awaits later, so a double-click started two fetches writing the
    same rows.
    """

    async def test_only_one_concurrent_refresh_starts(self, authed_client):
        import asyncio
        from unittest.mock import patch

        started = 0

        async def _slow_refresh():
            nonlocal started
            started += 1
            try:
                await asyncio.sleep(0.05)
            finally:
                cache.end_loading()

        with patch("app._do_fetch_and_score", _slow_refresh):
            responses = await asyncio.gather(
                *(authed_client.post("/api/refresh") for _ in range(5))
            )

        statuses = [r.json()["status"] for r in responses]
        assert statuses.count("started") == 1, statuses
        assert statuses.count("already_loading") == 4, statuses

        await asyncio.sleep(0.15)
        assert started == 1, "exactly one refresh job ran"
        assert not cache.is_loading, "slot released once the job finished"


def _refresh_patches(batches):
    """Patch everything a refresh touches upstream; the DB stays real."""
    from contextlib import ExitStack
    from unittest.mock import AsyncMock, patch

    stack = ExitStack()
    stack.enter_context(patch("refresh_service.build_topics", return_value={}))
    stack.enter_context(
        patch("refresh_service.fetch_and_score_incremental_iter", return_value=iter(batches))
    )
    stack.enter_context(
        patch(
            "refresh_service.load_config",
            return_value={"freshrss": {"url": "http://x", "username": "u", "api_password": "p"}},
        )
    )
    stack.enter_context(
        patch("refresh_service.get_or_seed_scoring_config", new_callable=AsyncMock, return_value={})
    )
    return stack


class TestRefreshSlotRelease:
    async def test_rescore_without_articles_releases_slot(
        self, authed_client_no_ratelimit, db_engine
    ):
        cache.articles = []
        resp = await authed_client_no_ratelimit.post("/api/rescore")
        assert resp.status_code == 400
        assert not cache.is_loading, "a 400 must not leave the slot claimed"

    async def test_stream_releases_slot_when_client_leaves_before_first_byte(self, db_engine):
        import app as app_module

        cache.end_loading()
        with _refresh_patches([IncrementalBatch([], set(), 0, [])]):
            resp = await app_module.refresh_stream()
            assert cache.is_loading
            # Starlette never iterates the body when the client disconnects first.
            await resp.body_iterator.aclose()
            async with asyncio.timeout(2):
                await asyncio.gather(*app_module._inflight_tasks)

        assert not cache.is_loading


class TestRescoreCompute:
    async def test_falls_back_to_a_thread_when_a_worker_crashes(self):
        from concurrent.futures.process import BrokenProcessPool
        from unittest.mock import patch

        import refresh_service

        class _CrashedPool:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def submit(self, *a, **kw):
                raise BrokenProcessPool("worker killed")

        rescored = [dict(_ARTICLE)]
        with (
            patch("refresh_service.concurrent.futures.ProcessPoolExecutor", _CrashedPool),
            patch("refresh_service.rescore_chunk", return_value=rescored) as chunk,
        ):
            result = await refresh_service.rescore_compute([{"id": "tag:a"}], {}, {})

        assert result == rescored
        chunk.assert_called_once()

    async def test_empty_input_returns_empty(self):
        import refresh_service

        assert await refresh_service.rescore_compute([], {}, {}) == []

    async def test_article_read_during_rescore_stays_out_of_cache(self, db_engine):
        import refresh_service
        from db import save_articles, set_articles_read

        await save_articles([dict(_ARTICLE)], total_fetched=1)
        await set_articles_read([_ARTICLE["id"]])

        await refresh_service.persist_rescore(cache, [dict(_ARTICLE)], 1)

        assert cache.articles == []


class TestRefreshPersistence:
    async def test_noop_refresh_updates_last_refresh_and_metrics(self, db_engine):
        from prometheus_client import REGISTRY

        import app as app_module
        from db import get_meta, get_seen_ids

        cache.last_refresh = None
        before = REGISTRY.get_sample_value("freshrss_refreshes_total") or 0.0
        with _refresh_patches([IncrementalBatch([], set(), 5, ["below-min"])]):
            await app_module._do_fetch_and_score()

        assert cache.error is None
        assert cache.last_refresh is not None
        assert int(await get_meta("last_refresh")) == int(cache.last_refresh)
        assert cache.total_fetched == 5
        assert REGISTRY.get_sample_value("freshrss_refreshes_total") == before + 1
        assert REGISTRY.get_sample_value(
            "freshrss_last_refresh_timestamp_seconds"
        ) == pytest.approx(cache.last_refresh)
        assert await get_seen_ids() == {"below-min"}

    async def test_failed_persist_does_not_record_seen_ids(self, db_engine):
        import app as app_module
        from db import get_seen_ids

        bad = dict(_ARTICLE, title=None)  # NOT NULL column: the insert fails
        with _refresh_patches([IncrementalBatch([bad], set(), 1, [bad["id"]])]):
            await app_module._do_fetch_and_score()

        assert cache.error is not None
        assert await get_seen_ids() == set(), "the next refresh must retry the article"
        cache.error = None
