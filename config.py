"""Shared configuration loading and built-in defaults for FreshRSS Summary."""

import logging
import os
from pathlib import Path
from typing import Any, TypedDict, cast

import yaml

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config.yaml"


class FreshRSSConfig(TypedDict):
    url: str
    username: str
    api_password: str


class _ServerConfig(TypedDict, total=False):
    host: str
    port: int
    public_url: str
    https_only: bool


class _SchedulerConfig(TypedDict, total=False):
    interval_minutes: int
    digest_hour: int
    timezone: str


class _DatabaseConfig(TypedDict, total=False):
    url: str


class _TelegramSection(TypedDict, total=False):
    bot_token: str
    chat_id: str
    webhook_secret: str


class _AuthConfig(TypedDict, total=False):
    secret_key: str
    admin_password: str


class _ScoringSection(TypedDict, total=False):
    feed_weights: dict[str, float]


class ConfigDict(TypedDict, total=False):
    """Typed shape of the application config (config.yaml + env var overrides)."""

    freshrss: FreshRSSConfig
    server: _ServerConfig
    scheduler: _SchedulerConfig
    database: _DatabaseConfig
    telegram: _TelegramSection
    auth: _AuthConfig
    scoring: _ScoringSection


def _read_yaml() -> dict[str, Any]:
    """
    Parse config.yaml, mapping sections left empty to {}.

    A section holding only comments (`database:` in config.example.yaml) parses as
    null, and every caller does `cfg.get(section, {}).get(...)` on it.
    """
    with CONFIG_PATH.open() as f:
        raw = yaml.safe_load(f) or {}
    return {k: ({} if v is None else v) for k, v in raw.items()}


def load_raw_config() -> ConfigDict:
    """Load config.yaml as-is, without env-var overrides or validation. Used during early startup."""
    if not CONFIG_PATH.exists():
        return cast(ConfigDict, {})
    return cast(ConfigDict, _read_yaml())


def session_https_only() -> bool:
    """Whether the session cookie gets the Secure flag (env override, no credentials needed)."""
    if v := os.environ.get("SESSION_HTTPS_ONLY"):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(load_raw_config().get("server", {}).get("https_only", False))


def load_config() -> ConfigDict:
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
      SESSION_HTTPS_ONLY     → server.https_only

    Raises:
        RuntimeError: if FRESHRSS_URL, FRESHRSS_USERNAME, or FRESHRSS_API_PASSWORD
            are missing from both config.yaml and environment variables.
    """
    cfg: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        cfg = _read_yaml()
    else:
        logger.warning("config.yaml not found - relying entirely on environment variables")

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
    if v := os.environ.get("SESSION_HTTPS_ONLY"):
        srv["https_only"] = v.strip().lower() in ("1", "true", "yes", "on")

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

    return cast(ConfigDict, cfg)


def get_secret_key_from_config() -> str | None:
    """Return the auth.secret_key value from config.yaml, or None if absent."""
    return load_raw_config().get("auth", {}).get("secret_key") or None
