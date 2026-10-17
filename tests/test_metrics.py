"""Tests for metrics.py."""

from prometheus_client import REGISTRY

from metrics import _update_prom_cache


def _topic_value(topic: str) -> float | None:
    return REGISTRY.get_sample_value("freshrss_articles_by_topic", {"topic": topic})


def test_topic_gauge_dropped_when_topic_has_no_article_left():
    _update_prom_cache([{"matched_topics": {"Gone": 1.0, "Kept": 1.0}}], None)
    _update_prom_cache([{"matched_topics": {"Kept": 1.0}}], None)

    assert _topic_value("Gone") is None
    assert _topic_value("Kept") == 1.0
