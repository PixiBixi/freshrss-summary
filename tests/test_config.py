"""Config loading: tolerance to sections left empty in config.yaml."""

import shutil
from pathlib import Path

import pytest

import config as config_module
from config import load_config, load_raw_config, session_https_only

_EXAMPLE = Path(__file__).parent.parent / "config.example.yaml"


@pytest.fixture
def config_path(monkeypatch, tmp_path):
    path = tmp_path / "config.yaml"
    monkeypatch.setattr(config_module, "CONFIG_PATH", path)
    for var in ("DATABASE_URL", "SESSION_HTTPS_ONLY", "TELEGRAM_BOT_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    return path


def test_example_config_loads(config_path):
    shutil.copy(_EXAMPLE, config_path)

    cfg = load_config()

    # `database:` holds only comments in the example, which YAML reads as null.
    assert cfg["database"] == {}
    assert cfg.get("database", {}).get("url") is None


def test_null_sections_become_empty_dicts(config_path, monkeypatch):
    config_path.write_text(
        "freshrss:\n  url: http://x\n  username: u\n  api_password: p\n"
        "database:\nserver:\nscheduler:\ntelegram:\nscoring:\nfetch:\nauth:\ntopics:\n"
    )
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///x.db")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")

    cfg = load_config()

    assert cfg["database"] == {"url": "sqlite+aiosqlite:///x.db"}
    assert cfg["telegram"] == {"bot_token": "tok"}
    for section in ("server", "scheduler", "scoring", "fetch", "auth", "topics"):
        assert cfg[section] == {}, section  # type: ignore[literal-required]


def test_null_freshrss_section_reports_missing_fields(config_path):
    config_path.write_text("freshrss:\n")

    with pytest.raises(RuntimeError, match="Missing FreshRSS config"):
        load_config()


def test_raw_config_tolerates_null_sections(config_path):
    config_path.write_text("server:\nauth:\n")

    assert load_raw_config() == {"server": {}, "auth": {}}
    assert session_https_only() is False
    assert config_module.get_secret_key_from_config() is None
