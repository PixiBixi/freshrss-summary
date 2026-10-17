import collections
import time

import auth


def test_login_attempts_bounded(monkeypatch):
    monkeypatch.setattr(auth, "_login_attempts", {})
    monkeypatch.setattr(auth, "_LOGIN_MAX_TRACKED", 50)
    for i in range(500):
        assert auth.login_rate_limit(f"10.0.{i // 256}.{i % 256}")
    assert len(auth._login_attempts) <= 50


def test_expired_entries_evicted(monkeypatch):
    old = collections.deque([time.time() - auth._LOGIN_WINDOW - 5])
    monkeypatch.setattr(auth, "_login_attempts", {"1.1.1.1": old, "2.2.2.2": collections.deque()})
    monkeypatch.setattr(auth, "_LOGIN_MAX_TRACKED", 2)
    assert auth.login_rate_limit("3.3.3.3")
    assert set(auth._login_attempts) == {"3.3.3.3"}


def test_rate_limit_still_blocks(monkeypatch):
    monkeypatch.setattr(auth, "_login_attempts", {})
    results = [auth.login_rate_limit("9.9.9.9") for _ in range(auth._LOGIN_MAX + 1)]
    assert results[-1] is False
