"""Unit tests for telegram_digest.py."""

from __future__ import annotations

import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from telegram_digest import (
    _register_webhook,
    _split_message,
    build_digest,
    send_digest,
    send_message,
)


def _make_article(title="Test", score=10.0, published_offset=-100, feed="Feed A"):
    """Helper: article dict as stored in cache.articles."""
    return {
        "id": "art-1",
        "title": title,
        "url": f"https://example.com/{title.replace(' ', '-')}",
        "score": score,
        "feed_title": feed,
        "published": time.time() + published_offset,
        "matched_topics": {},
        "bookmarked": False,
        "_read": False,
    }


def _make_fake_client(calls: list):
    """Returns a context-manager-compatible fake httpx.AsyncClient."""
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()

    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    async def fake_post(url, json=None, **kw):
        calls.append({"url": url, "json": json})
        return fake_response

    fake_client.post = fake_post
    return fake_client


# ── _split_message ────────────────────────────────────────────────────────────


class TestSplitMessage:
    def test_short_message_unchanged(self):
        chunks = _split_message("hello\nworld", 4096)
        assert chunks == ["hello\nworld"]

    def test_long_message_splits_at_newline(self):
        long_text = "\n".join(["x" * 100] * 50)  # ~5050 chars
        chunks = _split_message(long_text, 4096)
        assert len(chunks) == 2
        for chunk in chunks:
            assert len(chunk) <= 4096

    def test_single_line_longer_than_limit_stays_in_one_chunk(self):
        single = "x" * 5000
        chunks = _split_message(single, 4096)
        assert len(chunks) == 1


# ── build_digest ──────────────────────────────────────────────────────────────


class TestBuildDigest:
    def test_empty_articles_returns_no_articles_message(self):
        result = build_digest([])
        assert "Aucun article" in result

    def test_old_articles_excluded(self):
        old = _make_article(title="Old Article", published_offset=-90_000)
        result = build_digest([old])
        assert "Aucun article" in result

    def test_top_20_percent_selected(self):
        articles = [_make_article(title=f"Article {i}", score=float(100 - i)) for i in range(10)]
        result = build_digest(articles)
        assert "Article 0" in result
        assert "Article 1" in result
        assert "Article 2" not in result

    def test_minimum_one_article(self):
        articles = [_make_article(title="Solo Article", score=5.0)]
        result = build_digest(articles)
        assert "Solo Article" in result

    def test_result_contains_score_and_feed(self):
        articles = [_make_article(title="K8s News", score=142.0, feed="The Register")]
        result = build_digest(articles)
        assert "142" in result
        assert "The Register" in result

    def test_result_contains_url_link(self):
        article = _make_article(title="My Article")
        result = build_digest([article])
        assert "https://example.com/" in result

    def test_html_special_chars_escaped(self):
        article = _make_article(title="<script>alert('xss')</script>")
        article["url"] = "https://example.com/safe-url"  # URLs don't have angle brackets
        result = build_digest([article])
        assert "&lt;script&gt;" in result
        # The raw tag should not appear outside of the href attribute value
        assert "<script>" not in result.split('href="')[0]

    def test_header_contains_emoji_and_date(self):
        articles = [_make_article()]
        result = build_digest(articles)
        assert "📡" in result
        assert "FreshRSS Digest" in result

    def test_footer_shows_count(self):
        articles = [_make_article(title=f"Art {i}", score=float(10 - i)) for i in range(5)]
        result = build_digest(articles)
        assert "1 article" in result  # ceil(5 * 0.2) = 1


# ── send_message ──────────────────────────────────────────────────────────────


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_send_message_posts_to_telegram(self):
        calls: list = []
        with patch("telegram_digest.httpx.AsyncClient", return_value=_make_fake_client(calls)):
            await send_message("MY_TOKEN", "CHAT_123", "hello world")
        assert len(calls) == 1
        assert "MY_TOKEN" in calls[0]["url"]
        assert calls[0]["json"]["chat_id"] == "CHAT_123"
        assert calls[0]["json"]["text"] == "hello world"
        assert calls[0]["json"]["parse_mode"] == "HTML"
        assert calls[0]["json"]["disable_web_page_preview"] is True

    @pytest.mark.asyncio
    async def test_send_message_splits_long_text(self):
        calls: list = []
        long_text = "\n".join(["x" * 100] * 50)  # ~5050 chars
        with patch("telegram_digest.httpx.AsyncClient", return_value=_make_fake_client(calls)):
            await send_message("TOKEN", "123", long_text)
        assert len(calls) == 2


# ── send_digest ───────────────────────────────────────────────────────────────


class TestSendDigest:
    @pytest.mark.asyncio
    async def test_send_digest_calls_send_message(self):
        class FakeCache:
            articles = [_make_article(title="K8s News", score=50.0)]

        sent: list = []

        async def fake_send(token, chat_id, text):
            sent.append({"token": token, "chat_id": chat_id, "text": text})

        with patch("telegram_digest.send_message", side_effect=fake_send):
            await send_digest({"bot_token": "TOK", "chat_id": "42"}, FakeCache())

        assert len(sent) == 1
        assert sent[0]["token"] == "TOK"
        assert sent[0]["chat_id"] == "42"
        assert "K8s News" in sent[0]["text"]

    @pytest.mark.asyncio
    async def test_send_digest_skips_if_no_token(self):
        class FakeCache:
            articles = []

        sent: list = []

        async def fake_send(*a, **kw):
            sent.append(True)

        with patch("telegram_digest.send_message", side_effect=fake_send):
            await send_digest({"bot_token": "", "chat_id": "42"}, FakeCache())

        assert sent == []

    @pytest.mark.asyncio
    async def test_send_digest_logs_on_error(self, caplog):
        class FakeCache:
            articles = [_make_article()]

        async def failing_send(*a, **kw):
            raise httpx.ConnectError("timeout")

        with patch("telegram_digest.send_message", side_effect=failing_send):
            with caplog.at_level(logging.ERROR, logger="telegram_digest"):
                await send_digest({"bot_token": "TOK", "chat_id": "42"}, FakeCache())

        assert any("failed" in r.message.lower() for r in caplog.records)


# ── _register_webhook ─────────────────────────────────────────────────────────


class TestRegisterWebhook:
    @pytest.mark.asyncio
    async def test_register_webhook_calls_set_webhook(self):
        calls: list = []
        with patch("telegram_digest.httpx.AsyncClient", return_value=_make_fake_client(calls)):
            await _register_webhook(
                {"bot_token": "TOK", "webhook_secret": "mysecret"},
                "https://myapp.example.com",
            )
        assert len(calls) == 1
        assert "setWebhook" in calls[0]["url"]
        assert calls[0]["json"]["url"] == "https://myapp.example.com/telegram/webhook"
        assert calls[0]["json"]["secret_token"] == "mysecret"

    @pytest.mark.asyncio
    async def test_register_webhook_skips_if_no_token(self):
        with patch("telegram_digest.httpx.AsyncClient") as mock_client:
            await _register_webhook({"bot_token": ""}, "https://example.com")
        mock_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_register_webhook_logs_on_error(self, caplog):
        async def failing_post(*a, **kw):
            raise httpx.ConnectError("refused")

        fake_client = AsyncMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)
        fake_client.post = failing_post

        with patch("telegram_digest.httpx.AsyncClient", return_value=fake_client):
            with caplog.at_level(logging.ERROR, logger="telegram_digest"):
                await _register_webhook({"bot_token": "TOK"}, "https://example.com")

        assert any("failed" in r.message.lower() for r in caplog.records)
