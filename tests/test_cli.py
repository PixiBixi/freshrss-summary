"""Unit tests for cli.py — config loading and helper functions."""

import pytest

import config as config_module
from config import load_config

# ── ANSI helpers ──────────────────────────────────────────────────────────────


class TestHelpers:
    def test_ok_returns_string(self):
        from cli import ok

        result = ok("all good")
        assert isinstance(result, str)
        assert "all good" in result

    def test_warn_returns_string(self):
        from cli import warn

        result = warn("watch out")
        assert isinstance(result, str)
        assert "watch out" in result

    def test_err_returns_string(self):
        from cli import err

        result = err("something failed")
        assert isinstance(result, str)
        assert "something failed" in result

    def test_info_returns_string(self):
        from cli import info

        result = info("fyi")
        assert isinstance(result, str)
        assert "fyi" in result


# ── load_config ───────────────────────────────────────────────────────────────


class TestLoadConfig:
    def test_loads_from_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FRESHRSS_URL", "https://rss.example.com")
        monkeypatch.setenv("FRESHRSS_USERNAME", "myuser")
        monkeypatch.setenv("FRESHRSS_API_PASSWORD", "mypass")

        orig = config_module.CONFIG_PATH
        config_module.CONFIG_PATH = tmp_path / "no_config.yaml"
        try:
            cfg = load_config()
        finally:
            config_module.CONFIG_PATH = orig

        assert cfg["freshrss"]["url"] == "https://rss.example.com"
        assert cfg["freshrss"]["username"] == "myuser"
        assert cfg["freshrss"]["api_password"] == "mypass"

    def test_missing_url_raises(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FRESHRSS_URL", raising=False)
        monkeypatch.setenv("FRESHRSS_USERNAME", "u")
        monkeypatch.setenv("FRESHRSS_API_PASSWORD", "p")

        orig = config_module.CONFIG_PATH
        config_module.CONFIG_PATH = tmp_path / "no_config.yaml"
        try:
            with pytest.raises(RuntimeError, match="url"):
                load_config()
        finally:
            config_module.CONFIG_PATH = orig

    def test_missing_all_required_raises(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FRESHRSS_URL", raising=False)
        monkeypatch.delenv("FRESHRSS_USERNAME", raising=False)
        monkeypatch.delenv("FRESHRSS_API_PASSWORD", raising=False)

        orig = config_module.CONFIG_PATH
        config_module.CONFIG_PATH = tmp_path / "no_config.yaml"
        try:
            with pytest.raises(RuntimeError, match="Missing FreshRSS config"):
                load_config()
        finally:
            config_module.CONFIG_PATH = orig

    def test_database_url_from_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FRESHRSS_URL", "https://rss.example.com")
        monkeypatch.setenv("FRESHRSS_USERNAME", "u")
        monkeypatch.setenv("FRESHRSS_API_PASSWORD", "p")
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///test.db")

        orig = config_module.CONFIG_PATH
        config_module.CONFIG_PATH = tmp_path / "no_config.yaml"
        try:
            cfg = load_config()
        finally:
            config_module.CONFIG_PATH = orig

        assert cfg["database"]["url"] == "sqlite+aiosqlite:///test.db"

    def test_loads_from_yaml_file(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "freshrss:\n"
            "  url: https://from-yaml.com\n"
            "  username: yamluser\n"
            "  api_password: yamlpass\n"
        )

        orig = config_module.CONFIG_PATH
        config_module.CONFIG_PATH = config_file
        try:
            cfg = load_config()
        finally:
            config_module.CONFIG_PATH = orig

        assert cfg["freshrss"]["url"] == "https://from-yaml.com"
        assert cfg["freshrss"]["username"] == "yamluser"
