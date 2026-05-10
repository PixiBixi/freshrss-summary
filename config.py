"""Shared configuration loading and built-in defaults for FreshRSS Summary."""

import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_raw_config() -> dict[str, Any]:
    """Load config.yaml as-is, without env-var overrides or validation. Used during early startup."""
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open() as f:
        return yaml.safe_load(f) or {}


def load_config() -> dict[str, Any]:
    """
    Load config from config.yaml (if present), then apply env var overrides.

    Supported env vars (all optional, take priority over config.yaml):
      FRESHRSS_URL           → freshrss.url
      FRESHRSS_USERNAME      → freshrss.username
      FRESHRSS_API_PASSWORD  → freshrss.api_password
      SERVER_HOST            → server.host
      SERVER_PORT            → server.port
      REFRESH_INTERVAL_MINUTES → scheduler.interval_minutes
      DATABASE_URL           → database.url
      TELEGRAM_BOT_TOKEN     → telegram.bot_token
      TELEGRAM_CHAT_ID       → telegram.chat_id
      TELEGRAM_WEBHOOK_SECRET → telegram.webhook_secret
      PUBLIC_URL             → server.public_url

    Raises:
        RuntimeError: if FRESHRSS_URL, FRESHRSS_USERNAME, or FRESHRSS_API_PASSWORD
            are missing from both config.yaml and environment variables.
    """
    cfg: dict = {}
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open() as f:
            cfg = yaml.safe_load(f) or {}
    else:
        logger.warning("config.yaml not found — relying entirely on environment variables")

    fr = cfg.setdefault("freshrss", {})
    if v := os.environ.get("FRESHRSS_URL"):
        fr["url"] = v
    if v := os.environ.get("FRESHRSS_USERNAME"):
        fr["username"] = v
    if v := os.environ.get("FRESHRSS_API_PASSWORD"):
        fr["api_password"] = v

    srv = cfg.setdefault("server", {})
    if v := os.environ.get("SERVER_HOST"):
        srv["host"] = v
    if v := os.environ.get("SERVER_PORT"):
        srv["port"] = int(v)
    if v := os.environ.get("PUBLIC_URL"):
        srv["public_url"] = v

    sched = cfg.setdefault("scheduler", {})
    if v := os.environ.get("REFRESH_INTERVAL_MINUTES"):
        sched["interval_minutes"] = int(v)

    db = cfg.setdefault("database", {})
    if v := os.environ.get("DATABASE_URL"):
        db["url"] = v

    tg = cfg.setdefault("telegram", {})
    if v := os.environ.get("TELEGRAM_BOT_TOKEN"):
        tg["bot_token"] = v
    if v := os.environ.get("TELEGRAM_CHAT_ID"):
        tg["chat_id"] = v
    if v := os.environ.get("TELEGRAM_WEBHOOK_SECRET"):
        tg["webhook_secret"] = v

    # Validate required FreshRSS fields
    missing = [k for k in ("url", "username", "api_password") if not fr.get(k)]
    if missing:
        raise RuntimeError(
            f"Missing FreshRSS config: {', '.join(missing)}. "
            "Set them in config.yaml or via FRESHRSS_URL / FRESHRSS_USERNAME / FRESHRSS_API_PASSWORD."
        )

    return cfg


def get_secret_key_from_config() -> str | None:
    """Return the auth.secret_key value from config.yaml, or None if absent."""
    return load_raw_config().get("auth", {}).get("secret_key") or None
