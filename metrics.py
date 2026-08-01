"""Prometheus metrics subsystem for FreshRSS Summary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

__all__ = [
    "CONTENT_TYPE_LATEST",
    "_Metrics",
    "_get_metrics",
    "_update_prom_cache",
    "generate_latest",
]


@dataclass
class _Metrics:
    articles: Gauge
    last_refresh: Gauge
    refreshes: Counter
    refresh_dur: Histogram
    topic_articles: Gauge
    rescores: Counter
    rescore_dur: Histogram
    rescore_articles: Histogram
    rescore_workers: Gauge


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
            # Re-registration: the module was reloaded (uvicorn --reload, tests) so
            # our singleton is gone, but the collectors are still in the global
            # registry. prometheus_client exposes no public lookup by name.
            from prometheus_client import REGISTRY

            return REGISTRY._names_to_collectors[name]  # noqa: SLF001  # type: ignore[attr-defined]

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
        rescores=_get_or_register_metric(
            "freshrss_rescores_total",
            lambda: Counter("freshrss_rescores_total", "Rescore runs since startup"),
        ),
        rescore_dur=_get_or_register_metric(
            "freshrss_rescore_duration_seconds",
            lambda: Histogram(
                "freshrss_rescore_duration_seconds",
                "Scoring phase of a rescore, in seconds",
                # A rescore is minutes-scale on a small host and seconds-scale on a
                # big one; the buckets have to span both to stay readable.
                buckets=[1, 5, 10, 20, 30, 60, 120, 300],
            ),
        ),
        rescore_articles=_get_or_register_metric(
            "freshrss_rescore_articles",
            lambda: Histogram(
                "freshrss_rescore_articles",
                "Articles processed per rescore",
                buckets=[100, 500, 1000, 5000, 10000, 25000, 50000],
            ),
        ),
        rescore_workers=_get_or_register_metric(
            "freshrss_rescore_workers",
            lambda: Gauge(
                "freshrss_rescore_workers",
                "Worker processes used by the last rescore",
            ),
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
