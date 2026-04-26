# Telegram Digest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send the top 20% of today's articles to a Telegram chat every evening at 21h (Europe/Paris), and on-demand via `/digest` bot command.

**Architecture:** New `telegram_digest.py` module with three pure/async functions (build_digest, send_message, send_digest). `app.py` is extended with telegram env-var config, an APScheduler cron job added to the existing lifespan scheduler, and a `POST /telegram/webhook` endpoint that verifies a secret header and dispatches the same send_digest function.

**Tech Stack:** `httpx` (already in requirements), `apscheduler` (already in requirements), Telegram Bot API (HTTP, no SDK).

---

## File Map

| File | Change |
|---|---|
| `telegram_digest.py` | **Create** — build_digest, _split_message, send_message, send_digest, _register_webhook |
| `tests/test_telegram_digest.py` | **Create** — unit tests for all functions |
| `app.py` | **Modify** — load_config (telegram env vars), lifespan (scheduler job + webhook registration + app.state), new endpoint |
| `config.example.yaml` | **Modify** — add telegram section |

---

## Task 1: `build_digest` and `_split_message` — pure functions, TDD

**Files:**
- Create: `telegram_digest.py`
- Create: `tests/test_telegram_digest.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_telegram_digest.py
"""Unit tests for telegram_digest.py."""
import math
import time

import pytest

from telegram_digest import _split_message, build_digest


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


class TestSplitMessage:
    def test_short_message_unchanged(self):
        chunks = _split_message("hello\nworld", 4096)
        assert chunks == ["hello\nworld"]

    def test_long_message_splits_at_newline(self):
        # 50 lines of 100 chars each = 5050 chars total
        long_text = "\n".join(["x" * 100] * 50)
        chunks = _split_message(long_text, 4096)
        assert len(chunks) == 2
        for chunk in chunks:
            assert len(chunk) <= 4096

    def test_single_line_longer_than_limit_stays_in_one_chunk(self):
        single = "x" * 5000
        chunks = _split_message(single, 4096)
        assert len(chunks) == 1  # Can't split a single line


class TestBuildDigest:
    def test_empty_articles_returns_no_articles_message(self):
        result = build_digest([])
        assert "Aucun article" in result

    def test_old_articles_excluded(self):
        old = _make_article(title="Old Article", published_offset=-90_000)  # >24h
        result = build_digest([old])
        assert "Aucun article" in result

    def test_top_20_percent_selected(self):
        # 10 articles, top 20% = ceil(2) = 2
        articles = [_make_article(title=f"Article {i}", score=float(100 - i)) for i in range(10)]
        result = build_digest(articles)
        assert "Article 0" in result
        assert "Article 1" in result
        assert "Article 2" not in result

    def test_minimum_one_article(self):
        # Only 1 article, 20% rounds up to 1
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
        result = build_digest([article])
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_header_contains_emoji_and_date(self):
        articles = [_make_article()]
        result = build_digest(articles)
        assert "📡" in result
        assert "FreshRSS Digest" in result

    def test_footer_shows_count(self):
        articles = [_make_article(title=f"Art {i}", score=float(10 - i)) for i in range(5)]
        result = build_digest(articles)
        # ceil(5 * 0.2) = 1 article
        assert "1 article" in result
```

- [ ] **Step 2: Run tests — verify they all fail**

```bash
cd /Users/jeremy/Documents/perso/git/freshrss-summary
uv run pytest tests/test_telegram_digest.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'telegram_digest'`

- [ ] **Step 3: Implement `telegram_digest.py` with `build_digest` and `_split_message`**

```python
# telegram_digest.py
"""Telegram digest sender for FreshRSS Summary."""

from __future__ import annotations

import logging
import math
import time

import httpx

logger = logging.getLogger(__name__)

# ── French date helpers ────────────────────────────────────────────────────
_WEEKDAYS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
_MONTHS_FR = [
    "", "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]

_TELEGRAM_MAX_LEN = 4096


def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _split_message(text: str, max_len: int = _TELEGRAM_MAX_LEN) -> list[str]:
    """Split a message into chunks of at most max_len chars, breaking at newlines."""
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    lines = text.split("\n")
    current: list[str] = []
    current_len = 0
    for line in lines:
        # +1 for the newline that will join them
        needed = len(line) + (1 if current else 0)
        if current and current_len + needed > max_len:
            chunks.append("\n".join(current))
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += needed
    if current:
        chunks.append("\n".join(current))
    return chunks


def build_digest(articles: list[dict]) -> str:
    """
    Build an HTML-formatted Telegram digest from cache articles.

    Filters to last 24h, keeps top 20% by score (minimum 1).
    Returns a ready-to-send HTML string.
    """
    cutoff = time.time() - 86400
    today = [a for a in articles if (a.get("published") or 0) >= cutoff]

    if not today:
        return "📡 Aucun article pertinent dans les dernières 24h."

    today.sort(key=lambda a: a["score"], reverse=True)
    n = max(1, math.ceil(len(today) * 0.2))
    top = today[:n]

    dt = time.localtime()
    weekday = _WEEKDAYS_FR[dt.tm_wday]
    date_str = f"{weekday} {dt.tm_mday} {_MONTHS_FR[dt.tm_mon]}"

    lines: list[str] = [f"📡 <b>FreshRSS Digest</b> — {date_str}", ""]
    for a in top:
        title = _html_escape(a["title"])
        feed = _html_escape(a["feed_title"])
        score = int(a["score"])
        url = a["url"]
        lines.append(f'<a href="{url}">{title}</a> · <b>{score}</b> · {feed}')

    article_word = "article" if len(top) == 1 else "articles"
    lines.extend(["", f"{len(top)} {article_word} · top 20% du jour"])
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run pytest tests/test_telegram_digest.py::TestSplitMessage tests/test_telegram_digest.py::TestBuildDigest -v
```

Expected: all green

- [ ] **Step 5: Commit**

```bash
git add telegram_digest.py tests/test_telegram_digest.py
git commit -m "feat(telegram): add build_digest and _split_message with tests"
```

---

## Task 2: `send_message` — async HTTP, TDD with monkeypatch

**Files:**
- Modify: `telegram_digest.py` (add `send_message`)
- Modify: `tests/test_telegram_digest.py` (add `TestSendMessage`)

- [ ] **Step 1: Write the failing tests**

Add this class to `tests/test_telegram_digest.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


class TestSendMessage:
    """Tests for send_message — mocks httpx.AsyncClient."""

    def _make_fake_client(self, calls: list):
        """Returns a context-manager-compatible fake httpx client."""
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()

        fake_client = AsyncMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)
        fake_client.post = AsyncMock(side_effect=lambda url, json=None, **kw: (
            calls.append({"url": url, "json": json}) or fake_response
        ))
        return fake_client

    @pytest.mark.asyncio
    async def test_send_message_posts_to_telegram(self):
        from telegram_digest import send_message
        calls = []
        with patch("telegram_digest.httpx.AsyncClient", return_value=self._make_fake_client(calls)):
            await send_message("MY_TOKEN", "CHAT_123", "hello world")
        assert len(calls) == 1
        assert "MY_TOKEN" in calls[0]["url"]
        assert calls[0]["json"]["chat_id"] == "CHAT_123"
        assert calls[0]["json"]["text"] == "hello world"
        assert calls[0]["json"]["parse_mode"] == "HTML"
        assert calls[0]["json"]["disable_web_page_preview"] is True

    @pytest.mark.asyncio
    async def test_send_message_splits_long_text(self):
        from telegram_digest import send_message
        calls = []
        long_text = "\n".join(["x" * 100] * 50)  # ~5050 chars
        with patch("telegram_digest.httpx.AsyncClient", return_value=self._make_fake_client(calls)):
            await send_message("TOKEN", "123", long_text)
        assert len(calls) == 2  # split into 2 chunks
```

- [ ] **Step 2: Run the new tests — verify they fail**

```bash
uv run pytest tests/test_telegram_digest.py::TestSendMessage -v
```

Expected: `ImportError` or `AttributeError` — `send_message` not defined yet

- [ ] **Step 3: Add `send_message` to `telegram_digest.py`**

Add after `build_digest`:

```python
async def send_message(bot_token: str, chat_id: str, text: str) -> None:
    """Send one or more Telegram messages (splits at 4096 chars)."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    chunks = _split_message(text)
    async with httpx.AsyncClient(timeout=10) as client:
        for chunk in chunks:
            r = await client.post(url, json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })
            r.raise_for_status()
```

- [ ] **Step 4: Run all telegram tests — verify they pass**

```bash
uv run pytest tests/test_telegram_digest.py -v
```

Expected: all green

- [ ] **Step 5: Commit**

```bash
git add telegram_digest.py tests/test_telegram_digest.py
git commit -m "feat(telegram): add send_message with chunking"
```

---

## Task 3: `send_digest` and `_register_webhook`

**Files:**
- Modify: `telegram_digest.py` (add `send_digest`, `_register_webhook`)
- Modify: `tests/test_telegram_digest.py` (add `TestSendDigest`, `TestRegisterWebhook`)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_telegram_digest.py`:

```python
class TestSendDigest:
    @pytest.mark.asyncio
    async def test_send_digest_calls_send_message(self):
        from telegram_digest import send_digest

        class FakeCache:
            articles = [
                {
                    "id": "1", "title": "K8s News", "url": "https://example.com",
                    "score": 50.0, "feed_title": "CNCF", "matched_topics": {},
                    "published": time.time() - 100, "bookmarked": False, "_read": False,
                }
            ]

        sent = []
        async def fake_send(token, chat_id, text):
            sent.append({"token": token, "chat_id": chat_id, "text": text})

        with patch("telegram_digest.send_message", side_effect=fake_send):
            await send_digest(
                {"bot_token": "TOK", "chat_id": "42"},
                FakeCache(),
            )

        assert len(sent) == 1
        assert sent[0]["token"] == "TOK"
        assert sent[0]["chat_id"] == "42"
        assert "K8s News" in sent[0]["text"]

    @pytest.mark.asyncio
    async def test_send_digest_skips_if_no_token(self):
        from telegram_digest import send_digest

        class FakeCache:
            articles = []

        sent = []
        async def fake_send(*a, **kw):
            sent.append(True)

        with patch("telegram_digest.send_message", side_effect=fake_send):
            await send_digest({"bot_token": "", "chat_id": "42"}, FakeCache())

        assert sent == []  # nothing sent

    @pytest.mark.asyncio
    async def test_send_digest_logs_on_error(self, caplog):
        from telegram_digest import send_digest
        import logging

        class FakeCache:
            articles = [_make_article()]

        async def failing_send(*a, **kw):
            raise httpx.ConnectError("timeout")

        with patch("telegram_digest.send_message", side_effect=failing_send):
            with caplog.at_level(logging.ERROR, logger="telegram_digest"):
                # Should not raise
                await send_digest({"bot_token": "TOK", "chat_id": "42"}, FakeCache())

        assert any("failed" in r.message.lower() for r in caplog.records)


class TestRegisterWebhook:
    @pytest.mark.asyncio
    async def test_register_webhook_calls_set_webhook(self):
        from telegram_digest import _register_webhook

        calls = []
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_client = AsyncMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)
        fake_client.post = AsyncMock(side_effect=lambda url, json=None, **kw: (
            calls.append({"url": url, "json": json}) or fake_response
        ))

        with patch("telegram_digest.httpx.AsyncClient", return_value=fake_client):
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
        from telegram_digest import _register_webhook

        calls = []
        with patch("telegram_digest.httpx.AsyncClient") as mock_client:
            await _register_webhook({"bot_token": ""}, "https://example.com")

        mock_client.assert_not_called()
```

- [ ] **Step 2: Run new tests — verify they fail**

```bash
uv run pytest tests/test_telegram_digest.py::TestSendDigest tests/test_telegram_digest.py::TestRegisterWebhook -v
```

Expected: `ImportError` — `send_digest`/`_register_webhook` not defined yet

- [ ] **Step 3: Add `send_digest` and `_register_webhook` to `telegram_digest.py`**

Add after `send_message`:

```python
async def send_digest(tg_cfg: dict, cache) -> None:
    """Build and send the digest. Called by scheduler and webhook handler."""
    bot_token = tg_cfg.get("bot_token", "")
    chat_id = tg_cfg.get("chat_id", "")
    if not bot_token or not chat_id:
        logger.warning("Telegram digest: bot_token or chat_id missing, skipping")
        return
    text = build_digest(cache.articles)
    try:
        await send_message(bot_token, chat_id, text)
        logger.info("Telegram digest sent (%d chars)", len(text))
    except Exception as exc:
        logger.error("Telegram digest send failed: %s", exc)


async def _register_webhook(tg_cfg: dict, public_url: str) -> None:
    """Call Telegram setWebhook on startup. Logs errors, never raises."""
    bot_token = tg_cfg.get("bot_token", "")
    if not bot_token:
        return
    webhook_url = f"{public_url.rstrip('/')}/telegram/webhook"
    payload: dict = {
        "url": webhook_url,
        "allowed_updates": ["message"],
    }
    if secret := tg_cfg.get("webhook_secret", ""):
        payload["secret_token"] = secret
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{bot_token}/setWebhook",
                json=payload,
            )
            r.raise_for_status()
        logger.info("Telegram webhook registered: %s", webhook_url)
    except Exception as exc:
        logger.error("Telegram webhook registration failed: %s", exc)
```

- [ ] **Step 4: Run all telegram tests — verify they pass**

```bash
uv run pytest tests/test_telegram_digest.py -v
```

Expected: all green

- [ ] **Step 5: Commit**

```bash
git add telegram_digest.py tests/test_telegram_digest.py
git commit -m "feat(telegram): add send_digest and _register_webhook"
```

---

## Task 4: `app.py` — telegram config in `load_config`

**Files:**
- Modify: `app.py` (lines ~120-175, `load_config` function)
- Modify: `tests/test_app.py` (add `TestTelegramConfig`)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_app.py`:

```python
class TestTelegramConfig:
    def test_telegram_env_vars_override(self, monkeypatch, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "freshrss:\n  url: http://x\n  username: u\n  api_password: p\n"
        )
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "987")
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "mysecret")
        monkeypatch.setenv("PUBLIC_URL", "https://myapp.example.com")

        import importlib
        import app as app_module
        monkeypatch.setattr(app_module, "CONFIG_PATH", config_file)
        importlib.reload(app_module)

        cfg = app_module.load_config()
        assert cfg["telegram"]["bot_token"] == "tok123"
        assert cfg["telegram"]["chat_id"] == "987"
        assert cfg["telegram"]["webhook_secret"] == "mysecret"
        assert cfg["server"]["public_url"] == "https://myapp.example.com"

    def test_telegram_missing_config_no_crash(self, monkeypatch, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "freshrss:\n  url: http://x\n  username: u\n  api_password: p\n"
        )
        import importlib
        import app as app_module
        monkeypatch.setattr(app_module, "CONFIG_PATH", config_file)
        importlib.reload(app_module)

        cfg = app_module.load_config()
        # No telegram section in yaml, no env vars — should have empty dict, no crash
        assert cfg.get("telegram", {}) == {}
```

- [ ] **Step 2: Run new tests — verify they fail**

```bash
uv run pytest tests/test_app.py::TestTelegramConfig -v
```

Expected: assertions fail — telegram keys not in cfg yet

- [ ] **Step 3: Add telegram env vars to `load_config` in `app.py`**

Find the block that ends with `db["url"] = v` (around line 160) and add after it:

```python
    tg = cfg.setdefault("telegram", {}) if any(
        os.environ.get(k) for k in (
            "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_WEBHOOK_SECRET"
        )
    ) else cfg.get("telegram", {})
    if v := os.environ.get("TELEGRAM_BOT_TOKEN"):
        cfg.setdefault("telegram", {})["bot_token"] = v
    if v := os.environ.get("TELEGRAM_CHAT_ID"):
        cfg.setdefault("telegram", {})["chat_id"] = v
    if v := os.environ.get("TELEGRAM_WEBHOOK_SECRET"):
        cfg.setdefault("telegram", {})["webhook_secret"] = v
    if v := os.environ.get("PUBLIC_URL"):
        cfg.setdefault("server", {})["public_url"] = v
```

Actually, use the same pattern as the rest of load_config (simpler):

```python
    if v := os.environ.get("TELEGRAM_BOT_TOKEN"):
        cfg.setdefault("telegram", {})["bot_token"] = v
    if v := os.environ.get("TELEGRAM_CHAT_ID"):
        cfg.setdefault("telegram", {})["chat_id"] = v
    if v := os.environ.get("TELEGRAM_WEBHOOK_SECRET"):
        cfg.setdefault("telegram", {})["webhook_secret"] = v
    if v := os.environ.get("PUBLIC_URL"):
        srv["public_url"] = v
```

Place this block right after the `db` block (before the `# Validate required FreshRSS fields` comment).

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run pytest tests/test_app.py::TestTelegramConfig -v
```

Expected: green

- [ ] **Step 5: Run full test suite — no regressions**

```bash
uv run pytest tests/ -v --tb=short
```

Expected: all green

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat(telegram): add telegram env vars to load_config"
```

---

## Task 5: `app.py` — lifespan scheduler job + `app.state`

**Files:**
- Modify: `app.py` (lifespan function, around lines 287-322)

No new tests for the lifespan wiring itself (it's integration-level and tested via the endpoint in Task 6). The scheduler job calls `send_digest` which is already tested.

- [ ] **Step 1: Add import at top of `app.py`**

Find the imports block and add:

```python
from apscheduler.triggers.cron import CronTrigger

from telegram_digest import _register_webhook, send_digest
```

Place after the existing APScheduler import (`from apscheduler.schedulers.asyncio import AsyncIOScheduler`).

- [ ] **Step 2: Extend the lifespan function**

Find the lifespan function. After the existing scheduler block (the `if interval > 0:` block that ends with `scheduler.start()`), add:

```python
    tg_cfg = cfg.get("telegram", {})
    if tg_cfg.get("bot_token") and tg_cfg.get("chat_id"):
        if scheduler is None:
            scheduler = AsyncIOScheduler(timezone="UTC")
            scheduler.start()
        hour = int(tg_cfg.get("digest_hour", 21))
        scheduler.add_job(
            send_digest,
            CronTrigger(hour=hour, minute=0, timezone="Europe/Paris"),
            args=[tg_cfg, cache],
            id="daily_digest",
            max_instances=1,
            coalesce=True,
        )
        logger.info("Telegram digest scheduled at %02dh00 Europe/Paris", hour)
        public_url = cfg.get("server", {}).get("public_url", "")
        if public_url:
            await _register_webhook(tg_cfg, public_url)
        else:
            logger.info(
                "Telegram: set server.public_url (or PUBLIC_URL env var) to auto-register webhook"
            )

    app.state.tg_cfg = tg_cfg
```

The `app.state.tg_cfg = tg_cfg` line must be **before** the `yield` — it stores config for the webhook endpoint to use.

- [ ] **Step 3: Verify the app starts without telegram config (no crash)**

```bash
uv run python -c "
import os; os.environ.setdefault('FRESHRSS_URL','http://x')
os.environ.setdefault('FRESHRSS_USERNAME','u')
os.environ.setdefault('FRESHRSS_API_PASSWORD','p')
from app import load_config; cfg = load_config()
print('telegram:', cfg.get('telegram', {}))
print('OK')
"
```

Expected: `telegram: {}` and `OK`

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat(telegram): wire scheduler job and app.state in lifespan"
```

---

## Task 6: `POST /telegram/webhook` endpoint

**Files:**
- Modify: `app.py` (add endpoint after existing routes)
- Modify: `tests/test_app.py` (add `TestTelegramWebhook`)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_app.py`:

```python
import asyncio
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


class TestTelegramWebhook:
    def _make_client(self, tg_cfg: dict):
        """TestClient with tg_cfg pre-loaded into app.state."""
        from app import app
        app.state.tg_cfg = tg_cfg
        return TestClient(app, raise_server_exceptions=False)

    def test_webhook_returns_404_if_no_secret_configured(self):
        client = self._make_client({})
        r = client.post("/telegram/webhook", json={"update_id": 1})
        assert r.status_code == 404

    def test_webhook_returns_403_on_wrong_secret(self):
        client = self._make_client({"webhook_secret": "correct"})
        r = client.post(
            "/telegram/webhook",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
        assert r.status_code == 403

    def test_webhook_returns_200_on_correct_secret(self):
        client = self._make_client({"webhook_secret": "correct", "bot_token": "T", "chat_id": "1"})
        with patch("app.send_digest", new_callable=AsyncMock):
            r = client.post(
                "/telegram/webhook",
                json={"update_id": 1, "message": {"text": "/start"}},
                headers={"X-Telegram-Bot-Api-Secret-Token": "correct"},
            )
        assert r.status_code == 200

    def test_webhook_dispatches_digest_on_slash_digest(self):
        dispatched = []
        async def fake_send_digest(cfg, cache):
            dispatched.append(True)

        client = self._make_client({"webhook_secret": "s", "bot_token": "T", "chat_id": "1"})
        with patch("app.send_digest", side_effect=fake_send_digest):
            r = client.post(
                "/telegram/webhook",
                json={"update_id": 1, "message": {"text": "/digest"}},
                headers={"X-Telegram-Bot-Api-Secret-Token": "s"},
            )
        assert r.status_code == 200
        # Give asyncio a chance to run the task
        import time; time.sleep(0.05)
        assert dispatched  # task was created
```

- [ ] **Step 2: Run new tests — verify they fail**

```bash
uv run pytest tests/test_app.py::TestTelegramWebhook -v
```

Expected: 404 on all (endpoint doesn't exist yet)

- [ ] **Step 3: Add the endpoint to `app.py`**

Add after the existing endpoints (before the Prometheus endpoint or at the end of the routes):

```python
@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> dict:
    """Receive Telegram updates. Verifies secret header, handles /digest."""
    tg_cfg: dict = getattr(request.app.state, "tg_cfg", {})
    webhook_secret = tg_cfg.get("webhook_secret", "")
    if not webhook_secret:
        raise HTTPException(status_code=404)

    header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not secrets.compare_digest(header_secret, webhook_secret):
        raise HTTPException(status_code=403, detail="Invalid secret")

    body = await request.json()
    text: str = body.get("message", {}).get("text", "")
    if text.startswith("/digest"):
        asyncio.create_task(send_digest(tg_cfg, cache))

    return {}
```

- [ ] **Step 4: Run all tests — verify they pass**

```bash
uv run pytest tests/ -v --tb=short
```

Expected: all green

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat(telegram): add POST /telegram/webhook endpoint"
```

---

## Task 7: `config.example.yaml` update

**Files:**
- Modify: `config.example.yaml`

- [ ] **Step 1: Add telegram section to `config.example.yaml`**

Add after the `scheduler:` block:

```yaml
# ── Telegram digest ──────────────────────────────────────────────────────────
# Optional. If bot_token and chat_id are set, a daily digest is sent at digest_hour.
# On-demand: send /digest to the bot (requires webhook setup).
#
# Setup:
#   1. Create a bot via @BotFather → copy the token
#   2. Send a message to the bot, then GET /bot<TOKEN>/getUpdates → find chat.id
#   3. Set server.public_url (or PUBLIC_URL env var) for auto webhook registration
#      OR register manually: GET https://api.telegram.org/bot<TOKEN>/setWebhook?url=<PUBLIC_URL>/telegram/webhook
#
# Overridable via env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_WEBHOOK_SECRET
# PUBLIC_URL → server.public_url

telegram:
  bot_token: ""          # TELEGRAM_BOT_TOKEN
  chat_id: ""            # TELEGRAM_CHAT_ID
  digest_hour: 21        # Hour in Europe/Paris timezone (0-23)
  webhook_secret: ""     # TELEGRAM_WEBHOOK_SECRET — any random string, e.g.:
                         # python3 -c "import secrets; print(secrets.token_hex(16))"
```

- [ ] **Step 2: Commit**

```bash
git add config.example.yaml
git commit -m "docs(config): add telegram digest section to config.example.yaml"
```

---

## Self-Review

**Spec coverage check:**
- ✅ Daily digest at 21h Europe/Paris — Task 5 (CronTrigger)
- ✅ On-demand `/digest` — Task 6 (webhook endpoint)
- ✅ Top 20% by score, last 24h — Task 1 (build_digest)
- ✅ Minimalist format: title + score + link — Task 1
- ✅ Message splitting at 4096 chars — Task 1 + 2
- ✅ Webhook secret verification — Task 6
- ✅ Auto-register webhook on startup — Task 5 (_register_webhook)
- ✅ Silently disabled if no config — Task 4 + 5
- ✅ Error handling: log, don't crash — Task 3 (send_digest)
- ✅ Config via yaml + env vars — Task 4
- ✅ config.example.yaml updated — Task 7

**Type consistency:**
- `send_digest(tg_cfg: dict, cache)` — consistent across Task 3, 5, 6
- `_register_webhook(tg_cfg: dict, public_url: str)` — consistent across Task 3, 5
- `build_digest(articles: list[dict])` — consistent with `cache.articles: list[dict]`
- `send_message(bot_token: str, chat_id: str, text: str)` — consistent across Task 2, 3

**No placeholders:** confirmed — all steps have concrete code.
