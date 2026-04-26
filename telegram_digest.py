"""Telegram digest sender for FreshRSS Summary."""

from __future__ import annotations

import logging
import math
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── French date helpers ────────────────────────────────────────────────────
_WEEKDAYS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
_MONTHS_FR = [
    "",
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
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
        score = int(a["score"])
        url = a["url"]
        lines.append(f'<code>{score:>4}↑</code> <a href="{url}">{title}</a>')

    article_word = "article" if len(top) == 1 else "articles"
    lines.extend(["", f"{len(top)} {article_word} · top 20% du jour"])
    return "\n".join(lines)


async def send_message(bot_token: str, chat_id: str, text: str) -> None:
    """Send one or more Telegram messages (splits at 4096 chars)."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    chunks = _split_message(text)
    async with httpx.AsyncClient(timeout=10) as client:
        for chunk in chunks:
            r = await client.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            r.raise_for_status()


async def send_digest(tg_cfg: dict, cache: Any) -> None:
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
