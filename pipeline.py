"""Shared fetch-score-rescore pipeline logic for app.py and cli.py.

Both the web app and CLI perform the same core operations:
  1. Fetch unread articles from FreshRSS in batches and score each batch.
  2. Re-score previously saved articles from DB with updated topic weights.

This module extracts those pure operations, keeping them free of HTTP/cache
side effects. Callers (app.py, cli.py) own progress reporting and persistence.
"""

from __future__ import annotations

from collections.abc import Iterator

from freshrss_client import FreshRSSClient
from models import article_from_row
from scorer import TopicConfig, score_article, score_articles


def fetch_and_score_iter(
    cfg: dict,
    topics: list[TopicConfig],
    feed_weights: dict[str, float] | None = None,
) -> Iterator[tuple[list[dict], int]]:
    """
    Generator: fetch unread articles in batches, score each batch.

    Yields (scored_batch, cumulative_total_fetched) for each batch so callers
    can report progress incrementally. Runs synchronously — use asyncio.to_thread
    when calling from an async context.

    Args:
        cfg: full config dict (must contain freshrss and fetch sub-keys).
        topics: pre-built TopicConfig list from build_topics().
        feed_weights: optional per-feed score multipliers.
    """
    fr_cfg = cfg["freshrss"]
    fetch_cfg = cfg.get("fetch", {})
    scoring_cfg = cfg.get("scoring", {})
    batch_size = int(fetch_cfg.get("batch_size", 1000))
    max_batches = int(fetch_cfg.get("max_batches", 10))
    title_weight = int(scoring_cfg.get("title_weight", 3))
    min_score = float(scoring_cfg.get("min_score", 1.0))
    total_fetched = 0

    with FreshRSSClient(fr_cfg["url"], fr_cfg["username"], fr_cfg["api_password"]) as client:
        for batch in client.fetch_unread(batch_size=batch_size, max_batches=max_batches):
            total_fetched += len(batch)
            scored = [
                sa.to_dict()
                for sa in score_articles(
                    batch,
                    topics,
                    title_weight=title_weight,
                    min_score=min_score,
                    feed_weights=feed_weights,
                )
            ]
            yield scored, total_fetched


def rescore_articles(
    raw: list[dict],
    topics: list[TopicConfig],
    title_weight: int = 3,
    min_score: float = 1.0,
    feed_weights: dict[str, float] | None = None,
) -> list[dict]:
    """
    Re-score DB rows with updated topic weights.

    Args:
        raw: article rows from load_for_rescore() — each row is a dict with
             id, title, url, content, feed_title, published keys.
        topics: pre-built TopicConfig list from build_topics().
        title_weight: multiplier applied to title keyword matches.
        min_score: articles scoring below this are excluded from the result.
        feed_weights: optional per-feed score multipliers.

    Returns:
        Sorted list of article dicts (score desc) for articles ≥ min_score.
    """
    result = []
    for r in raw:
        art = article_from_row(r)
        scored = score_article(art, topics, title_weight, feed_weights=feed_weights)
        if scored.score >= min_score:
            result.append(scored.to_dict())
    result.sort(key=lambda a: a["score"], reverse=True)
    return result
