"""Integration tests: fetch→score→DB save→load roundtrip."""

import pytest

from db import load_articles, upsert_articles


@pytest.mark.anyio
async def test_upsert_and_load_roundtrip(db):
    """Verify save→load roundtrip preserves article fields."""
    articles = [
        {
            "id": "test-article-1",
            "title": "Test Article 1",
            "url": "https://example.com/1",
            "feed_title": "Test Feed",
            "published": 1700000000,
            "score": 42.5,
            "matched_topics": {"SRE": 25.0, "Kubernetes": 17.5},
            "matched_keywords": ["kubernetes", "sre"],
            "top_topic": "SRE",
            "summary": None,
        },
        {
            "id": "test-article-2",
            "title": "Test Article 2",
            "url": "https://example.com/2",
            "feed_title": "Test Feed",
            "published": 1700001000,
            "score": 15.0,
            "matched_topics": {"GKE": 15.0},
            "matched_keywords": ["gke"],
            "top_topic": "GKE",
            "summary": "A summary",
        },
    ]

    await upsert_articles(articles)
    loaded, last_refresh, total_fetched = await load_articles()

    assert len(loaded) == 2
    loaded_by_id = {a["id"]: a for a in loaded}

    assert loaded_by_id["test-article-1"]["score"] == pytest.approx(42.5)
    assert loaded_by_id["test-article-1"]["top_topic"] == "SRE"
    assert loaded_by_id["test-article-2"]["score"] == pytest.approx(15.0)
    assert loaded_by_id["test-article-2"]["top_topic"] == "GKE"
    # last_refresh is None since upsert_articles does not update the meta table
    assert last_refresh is None
