"""Prometheus metrics subsystem for FreshRSS Summary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

if TYPE_CHECKING:
    pass

__all__ = [
    "CONTENT_TYPE_LATEST",
    "generate_latest",
    "_Metrics",
    "_get_metrics",
    "_update_prom_cache",
]


@dataclass
class _Metrics:
    articles: Gauge
    last_refresh: Gauge
    refreshes: Counter
    refresh_dur: Histogram
    topic_articles: Gauge


_metrics: _Metrics | None = None


def _get_metrics() -> _Metrics:
    """Return the shared Prometheus metrics singleton, creating it lazily on first call."""
    global _metrics
    if _metrics is not None:
        return _metrics

    def _get_or_register_metric(name, factory):  # type: ignore[no-untyped-def]
        try:
            return factory()
        except ValueError:
            from prometheus_client import REGISTRY

            return REGISTRY._names_to_collectors[name]  # type: ignore[attr-defined]

    _metrics = _Metrics(
        articles=_get_or_register_metric(
            "freshrss_articles_total",
            lambda: Gauge("freshrss_articles_total", "Articles currently in cache"),
        ),
        last_refresh=_get_or_register_metric(
            "freshrss_last_refresh_timestamp_seconds",
            lambda: Gauge(
                "freshrss_last_refresh_timestamp_seconds",
                "Unix timestamp of last successful refresh",
            ),
        ),
        refreshes=_get_or_register_metric(
            "freshrss_refreshes_total",
            lambda: Counter("freshrss_refreshes_total", "Successful refreshes since startup"),
        ),
        refresh_dur=_get_or_register_metric(
            "freshrss_refresh_duration_seconds",
            lambda: Histogram(
                "freshrss_refresh_duration_seconds",
                "Refresh duration in seconds",
                buckets=[2, 5, 15, 30, 60, 120, 300],
            ),
        ),
        topic_articles=_get_or_register_metric(
            "freshrss_articles_by_topic",
            lambda: Gauge("freshrss_articles_by_topic", "Articles per topic in cache", ["topic"]),
        ),
    )
    return _metrics


def _update_prom_cache(articles: list[dict[str, Any]], last_refresh: float | None) -> None:
    """Sync Prometheus gauges from current cache state."""
    m = _get_metrics()
    m.articles.set(len(articles))
    if last_refresh:
        m.last_refresh.set(last_refresh)
    topic_counts: dict[str, int] = {}
    for a in articles:
        for t in a.get("matched_topics", {}):
            topic_counts[t] = topic_counts.get(t, 0) + 1
    for topic, count in topic_counts.items():
        m.topic_articles.labels(topic=topic).set(count)
