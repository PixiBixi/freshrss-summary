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


# ── CLI command handlers ───────────────────────────────────────────────────────

_MINIMAL_CFG = {
    "freshrss": {"url": "http://x", "username": "u", "api_password": "p"},
    "database": {},
    "scoring": {"title_weight": 3, "min_score": 1.0},
    "topics": {},
}

_DB_STATS = {
    "articles": 5,
    "total_fetched": 10,
    "last_refresh": 1_700_000_000.0,
    "bookmarks": 2,
    "topics": ["Kubernetes", "SRE"],
}


class TestCmdStats:
    def test_returns_0_on_success(self, capsys):
        import argparse
        from unittest.mock import patch

        from cli import cmd_stats

        with patch("cli.asyncio.run", return_value=_DB_STATS):
            args = argparse.Namespace()
            rc = cmd_stats(args, _MINIMAL_CFG)
        assert rc == 0
        out = capsys.readouterr().out
        assert "5" in out

    def test_db_error_returns_1(self, monkeypatch, capsys):
        from unittest.mock import patch

        with patch("cli.asyncio.run", side_effect=RuntimeError("DB unreachable")):
            import argparse

            from cli import cmd_stats

            args = argparse.Namespace()
            rc = cmd_stats(args, _MINIMAL_CFG)
        assert rc == 1
        out = capsys.readouterr().out
        assert "DB" in out


class TestCmdRescore:
    def test_dry_run_no_save(self, monkeypatch, capsys):
        from unittest.mock import patch

        raw = [
            {
                "id": "1",
                "title": "K8s",
                "url": "http://x",
                "feed_title": "F",
                "published": 1700000000,
                "content": "kubernetes cluster",
            }
        ]

        import argparse

        args = argparse.Namespace(dry_run=True)

        call_count = {"n": 0}

        def fake_run(coro):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return raw  # _load_for_rescore
            return None  # should not be called again in dry_run

        from cli import cmd_rescore

        with patch("cli.asyncio.run", side_effect=fake_run):
            rc = cmd_rescore(args, _MINIMAL_CFG)

        assert rc == 0
        out = capsys.readouterr().out
        assert "dry-run" in out.lower() or "dry_run" in out.lower() or "--dry-run" in out

    def test_empty_db_returns_0(self, monkeypatch, capsys):
        import argparse
        from unittest.mock import patch

        args = argparse.Namespace(dry_run=False)

        from cli import cmd_rescore

        with patch("cli.asyncio.run", return_value=[]):
            rc = cmd_rescore(args, _MINIMAL_CFG)

        assert rc == 0
        out = capsys.readouterr().out
        assert "No articles" in out

    def test_db_load_error_returns_1(self, monkeypatch, capsys):
        import argparse
        from unittest.mock import patch

        args = argparse.Namespace(dry_run=False)

        from cli import cmd_rescore

        with patch("cli.asyncio.run", side_effect=RuntimeError("load failed")):
            rc = cmd_rescore(args, _MINIMAL_CFG)

        assert rc == 1


class TestCmdCheck:
    def test_success_returns_0(self, monkeypatch, capsys):
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.ping.return_value = 1
        mock_client.fetch_starred.return_value = []

        import argparse

        args = argparse.Namespace()

        from cli import cmd_check

        with patch("cli.make_client", return_value=mock_client):
            with patch("cli.asyncio.run", return_value=_DB_STATS):
                rc = cmd_check(args, _MINIMAL_CFG)

        assert rc == 0
        out = capsys.readouterr().out
        assert "Auth OK" in out

    def test_freshrss_error_returns_1(self, monkeypatch, capsys):
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(side_effect=RuntimeError("connection refused"))
        mock_client.__exit__ = MagicMock(return_value=False)

        import argparse

        args = argparse.Namespace()

        from cli import cmd_check

        with patch("cli.make_client", return_value=mock_client):
            rc = cmd_check(args, _MINIMAL_CFG)

        assert rc == 1


_ARTICLE_DICT = {
    "id": "a1",
    "title": "K8s tip",
    "url": "http://x.com",
    "score": 5.0,
    "feed_title": "Feed",
    "published": 0,
    "matched_topics": {"Kubernetes": 5.0},
    "matched_keywords": ["kubernetes"],
    "top_topic": "Kubernetes",
    "summary": "",
    "bookmarked": False,
    "feed_weight": 1.0,
}


class TestCmdFetch:
    def test_dry_run_returns_0(self, capsys):
        import argparse
        from unittest.mock import patch

        args = argparse.Namespace(dry_run=True)
        from cli import cmd_fetch

        with patch("pipeline.fetch_and_score_iter", return_value=iter([([_ARTICLE_DICT], 1)])):
            rc = cmd_fetch(args, _MINIMAL_CFG)

        assert rc == 0

    def test_no_articles_returns_0(self, capsys):
        import argparse
        from unittest.mock import patch

        args = argparse.Namespace(dry_run=False)
        from cli import cmd_fetch

        with patch("pipeline.fetch_and_score_iter", return_value=iter([])):
            rc = cmd_fetch(args, _MINIMAL_CFG)

        assert rc == 0

    def test_fetch_error_returns_1(self, capsys):
        import argparse
        from unittest.mock import patch

        def _raise(*a, **kw):
            raise RuntimeError("connection refused")
            yield  # make it a generator

        args = argparse.Namespace(dry_run=False)
        from cli import cmd_fetch

        with patch("pipeline.fetch_and_score_iter", side_effect=RuntimeError("connection refused")):
            rc = cmd_fetch(args, _MINIMAL_CFG)

        assert rc == 1

    def test_save_to_db_called_when_not_dry_run(self, capsys):
        import argparse
        from unittest.mock import patch

        args = argparse.Namespace(dry_run=False)
        from cli import cmd_fetch

        with patch("pipeline.fetch_and_score_iter", return_value=iter([([_ARTICLE_DICT], 1)])):
            with patch("cli.asyncio.run", return_value=None) as mock_run:
                rc = cmd_fetch(args, _MINIMAL_CFG)

        assert rc == 0
        mock_run.assert_called_once()


class TestCmdImport:
    def test_missing_file_and_no_starred_returns_1(self, capsys):
        import argparse

        from cli import cmd_import

        args = argparse.Namespace(starred=False, file=None, dry_run=False, limit=None)
        rc = cmd_import(args, _MINIMAL_CFG)
        assert rc == 1

    def test_file_not_found_returns_1(self, capsys, tmp_path):
        import argparse

        from cli import cmd_import

        args = argparse.Namespace(
            starred=False, file=str(tmp_path / "missing.json"), dry_run=False, limit=None
        )
        rc = cmd_import(args, _MINIMAL_CFG)
        assert rc == 1

    def test_invalid_json_returns_1(self, capsys, tmp_path):
        import argparse

        from cli import cmd_import

        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json}")
        args = argparse.Namespace(starred=False, file=str(bad), dry_run=False, limit=None)
        rc = cmd_import(args, _MINIMAL_CFG)
        assert rc == 1

    def test_json_not_list_returns_1(self, capsys, tmp_path):
        import argparse

        from cli import cmd_import

        f = tmp_path / "obj.json"
        f.write_text('{"key": "val"}')
        args = argparse.Namespace(starred=False, file=str(f), dry_run=False, limit=None)
        rc = cmd_import(args, _MINIMAL_CFG)
        assert rc == 1

    def test_starred_dry_run_returns_0(self, capsys):
        import argparse
        from unittest.mock import MagicMock, patch

        from models import Article

        mock_article = Article(
            id="s1",
            title="Starred",
            url="http://x.com",
            content="c",
            summary="",
            feed_title="Feed",
            published=0,
        )
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.fetch_starred.return_value = [mock_article]

        args = argparse.Namespace(starred=True, file=None, dry_run=True, limit=None)
        from cli import cmd_import

        with patch("cli.make_client", return_value=mock_client):
            rc = cmd_import(args, _MINIMAL_CFG)

        assert rc == 0


class TestCmdTune:
    def test_no_topics_returns_1(self, capsys):
        import argparse

        from cli import cmd_tune

        cfg_no_topics = {**_MINIMAL_CFG, "topics": {}}
        args = argparse.Namespace(apply=False, limit=None)
        rc = cmd_tune(args, cfg_no_topics)
        assert rc == 1

    def test_no_starred_returns_0(self, capsys):
        import argparse
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.fetch_starred.return_value = []

        cfg_with_topics = {**_MINIMAL_CFG, "topics": {"SRE": {"weight": 1.5, "keywords": ["sre"]}}}
        args = argparse.Namespace(apply=False, limit=None)
        from cli import cmd_tune

        with patch("cli.make_client", return_value=mock_client):
            rc = cmd_tune(args, cfg_with_topics)

        assert rc == 0

    def test_fetch_error_returns_1(self, capsys):
        import argparse
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(side_effect=RuntimeError("oops"))
        mock_client.__exit__ = MagicMock(return_value=False)

        cfg_with_topics = {**_MINIMAL_CFG, "topics": {"SRE": {"weight": 1.5, "keywords": ["sre"]}}}
        args = argparse.Namespace(apply=False, limit=None)
        from cli import cmd_tune

        with patch("cli.make_client", return_value=mock_client):
            rc = cmd_tune(args, cfg_with_topics)

        assert rc == 1


class TestCmdDigest:
    def test_prints_digest_returns_0(self, capsys):
        import argparse
        from unittest.mock import patch

        args = argparse.Namespace(send=False)
        from cli import cmd_digest

        with patch("cli.asyncio.run", return_value=[]):
            rc = cmd_digest(args, _MINIMAL_CFG)

        assert rc == 0

    def test_db_error_returns_1(self, capsys):
        import argparse
        from unittest.mock import patch

        args = argparse.Namespace(send=False)
        from cli import cmd_digest

        with patch("cli.asyncio.run", side_effect=RuntimeError("db down")):
            rc = cmd_digest(args, _MINIMAL_CFG)

        assert rc == 1

    def test_send_missing_token_returns_1(self, capsys):
        import argparse
        from unittest.mock import patch

        args = argparse.Namespace(send=True)
        from cli import cmd_digest

        with patch("cli.asyncio.run", return_value=[]):
            rc = cmd_digest(args, _MINIMAL_CFG)  # _MINIMAL_CFG has no telegram key

        assert rc == 1

    def test_send_success_returns_0(self, capsys):
        import argparse
        from unittest.mock import patch

        args = argparse.Namespace(send=True)
        cfg_with_tg = {
            **_MINIMAL_CFG,
            "telegram": {"bot_token": "TOK", "chat_id": "123"},
        }
        from cli import cmd_digest

        with patch("cli.asyncio.run", return_value=[]):
            rc = cmd_digest(args, cfg_with_tg)

        assert rc == 0
