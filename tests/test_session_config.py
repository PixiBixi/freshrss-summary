import config


def test_https_only_default_false(monkeypatch):
    monkeypatch.delenv("SESSION_HTTPS_ONLY", raising=False)
    monkeypatch.setattr(config, "load_raw_config", lambda: {})
    assert config.session_https_only() is False


def test_https_only_env_override(monkeypatch):
    monkeypatch.setenv("SESSION_HTTPS_ONLY", "true")
    assert config.session_https_only() is True


def test_https_only_from_yaml(monkeypatch):
    monkeypatch.delenv("SESSION_HTTPS_ONLY", raising=False)
    monkeypatch.setattr(config, "load_raw_config", lambda: {"server": {"https_only": True}})
    assert config.session_https_only() is True
