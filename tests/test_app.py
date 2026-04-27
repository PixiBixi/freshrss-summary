"""Unit tests for app.py — pure functions (hash, config, auth)."""

import pytest

import config as config_module
from app import hash_password, verify_password
from config import load_config

# ── Password hashing ──────────────────────────────────────────────────────────


class TestPasswordHashing:
    def test_hash_and_verify(self):
        h = hash_password("mysecret")
        assert verify_password("mysecret", h) is True

    def test_wrong_password_fails(self):
        h = hash_password("correct")
        assert verify_password("wrong", h) is False

    def test_different_hashes_for_same_password(self):
        # Different salts each time
        h1 = hash_password("pass")
        h2 = hash_password("pass")
        assert h1 != h2

    def test_hash_format_is_salt_colon_hash(self):
        h = hash_password("pass")
        parts = h.split(":")
        assert len(parts) == 2
        # Both parts are hex strings
        assert all(c in "0123456789abcdef" for c in parts[0])
        assert all(c in "0123456789abcdef" for c in parts[1])

    def test_invalid_stored_format_returns_false(self):
        assert verify_password("pass", "not-valid") is False
        assert verify_password("pass", "") is False
        assert verify_password("pass", ":") is False


# ── load_config ───────────────────────────────────────────────────────────────


class TestLoadConfig:
    def test_env_vars_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FRESHRSS_URL", "https://my.freshrss.com")
        monkeypatch.setenv("FRESHRSS_USERNAME", "testuser")
        monkeypatch.setenv("FRESHRSS_API_PASSWORD", "testapipass")
        monkeypatch.setenv("SERVER_HOST", "0.0.0.0")
        monkeypatch.setenv("SERVER_PORT", "9000")

        orig = config_module.CONFIG_PATH
        config_module.CONFIG_PATH = tmp_path / "nonexistent.yaml"
        try:
            cfg = load_config()
        finally:
            config_module.CONFIG_PATH = orig

        assert cfg["freshrss"]["url"] == "https://my.freshrss.com"
        assert cfg["freshrss"]["username"] == "testuser"
        assert cfg["freshrss"]["api_password"] == "testapipass"
        assert cfg["server"]["host"] == "0.0.0.0"
        assert cfg["server"]["port"] == 9000

    def test_missing_required_fields_raises(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FRESHRSS_URL", raising=False)
        monkeypatch.delenv("FRESHRSS_USERNAME", raising=False)
        monkeypatch.delenv("FRESHRSS_API_PASSWORD", raising=False)

        orig = config_module.CONFIG_PATH
        config_module.CONFIG_PATH = tmp_path / "nonexistent.yaml"
        try:
            with pytest.raises(RuntimeError, match="Missing FreshRSS config"):
                load_config()
        finally:
            config_module.CONFIG_PATH = orig

    def test_partial_config_raises_with_missing_fields(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FRESHRSS_URL", "https://rss.example.com")
        monkeypatch.delenv("FRESHRSS_USERNAME", raising=False)
        monkeypatch.delenv("FRESHRSS_API_PASSWORD", raising=False)

        orig = config_module.CONFIG_PATH
        config_module.CONFIG_PATH = tmp_path / "nonexistent.yaml"
        try:
            with pytest.raises(RuntimeError) as exc_info:
                load_config()
        finally:
            config_module.CONFIG_PATH = orig

        assert "username" in str(exc_info.value)
        assert "api_password" in str(exc_info.value)

    def test_database_url_env_var(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FRESHRSS_URL", "https://x.com")
        monkeypatch.setenv("FRESHRSS_USERNAME", "u")
        monkeypatch.setenv("FRESHRSS_API_PASSWORD", "p")
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///test.db")

        orig = config_module.CONFIG_PATH
        config_module.CONFIG_PATH = tmp_path / "nonexistent.yaml"
        try:
            cfg = load_config()
        finally:
            config_module.CONFIG_PATH = orig

        assert cfg["database"]["url"] == "sqlite+aiosqlite:///test.db"


# ── Cache ─────────────────────────────────────────────────────────────────────


class TestCache:
    def test_populate_sets_topics(self):
        from app import Cache

        c = Cache()
        articles = [
            {"matched_topics": {"k8s": 5.0, "sre": 3.0}},
            {"matched_topics": {"terraform": 2.0}},
        ]
        c.populate(articles, last_refresh=1000.0, total_fetched=10)

        assert c.articles == articles
        assert c.last_refresh == 1000.0
        assert c.total_fetched == 10
        assert sorted(c.all_topics) == ["k8s", "sre", "terraform"]

    def test_populate_deduplicates_topics(self):
        from app import Cache

        c = Cache()
        articles = [
            {"matched_topics": {"k8s": 5.0}},
            {"matched_topics": {"k8s": 2.0}},
        ]
        c.populate(articles, last_refresh=None, total_fetched=2)
        assert c.all_topics == ["k8s"]

    def test_initial_state(self):
        from app import Cache

        c = Cache()
        assert c.articles == []
        assert c.all_topics == []
        assert c.total_fetched == 0
        assert c.last_refresh is None
        assert c.is_loading is False
        assert c.error is None
