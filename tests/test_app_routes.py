"""Route handler tests using httpx AsyncClient + ASGITransport."""

import json
import time

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from app import app, cache
from db import metadata, set_engine_for_testing

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

_ARTICLE = {
    "id": "tag:a",
    "title": "K8s guide",
    "url": "https://example.com/k8s",
    "feed_title": "CNCF",
    "published": int(time.time()) - 3600,  # 1 hour ago — within any days window
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
        """Health endpoint is public — no session needed."""
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
            patch(
                "app._fetch_and_score_iter",
                return_value=iter([([article], 1)]),
            ),
            patch(
                "app.load_config",
                return_value={
                    "freshrss": {"url": "http://x", "username": "u", "api_password": "p"}
                },
            ),
            patch("app._get_or_seed_scoring_config", new_callable=AsyncMock, return_value={}),
            patch("app.get_feed_weights", new_callable=AsyncMock, return_value={}),
            patch("app._persist_and_populate", new_callable=AsyncMock),
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
            patch(
                "app._fetch_and_score_iter",
                side_effect=RuntimeError("fetch failed"),
            ),
            patch(
                "app.load_config",
                return_value={
                    "freshrss": {"url": "http://x", "username": "u", "api_password": "p"}
                },
            ),
            patch("app._get_or_seed_scoring_config", new_callable=AsyncMock, return_value={}),
            patch("app.get_feed_weights", new_callable=AsyncMock, return_value={}),
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
