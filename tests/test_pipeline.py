"""Direct unit tests for the pipeline module.

Tests fetch_and_score_iter and rescore_articles without relying on mocks
of higher-level wrappers in app.py or cli.py.
"""

from unittest.mock import MagicMock, patch

from models import Article, ArticleDict
from pipeline import fetch_and_score_iter, rescore_articles
from scorer import TopicConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TOPICS = [
    TopicConfig(name="Kubernetes", keywords=["kubernetes", "k8s"], weight=2.0),
    TopicConfig(name="SRE", keywords=["sre", "incident"], weight=1.5),
]

_MINIMAL_CFG: dict = {
    "freshrss": {
        "url": "http://localhost",
        "username": "user",
        "api_password": "pass",
    },
}


def _make_raw_article(**overrides) -> ArticleDict:
    base: ArticleDict = {
        "id": "1",
        "title": "Kubernetes deployment",
        "url": "http://example.com",
        "feed_title": "Tech Blog",
        "published": 1700000000,
        "score": 3.0,
        "matched_topics": {"Kubernetes": 3.0},
        "matched_keywords": ["kubernetes"],
        "top_topic": "Kubernetes",
        "feed_weight": 1.0,
        "summary": "",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# fetch_and_score_iter
# ---------------------------------------------------------------------------


class TestFetchAndScoreIter:
    def test_yields_batches_from_client(self):
        """Generator yields (scored_articles, cumulative_count) for each batch."""
        article = Article(
            id="1",
            title="kubernetes deployment",
            url="http://example.com",
            content="kubernetes k8s cluster",
            summary="",
            feed_title="Tech",
            published=1700000000,
        )
        mock_client = MagicMock()
        mock_client.fetch_unread.return_value = [[article]]
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("pipeline.FreshRSSClient", return_value=mock_client):
            results = list(fetch_and_score_iter(_MINIMAL_CFG, _TOPICS))

        assert len(results) == 1
        batch, total = results[0]
        assert total == 1
        assert isinstance(batch, list)

    def test_empty_feed_yields_nothing(self):
        """When client returns no batches, generator is empty."""
        mock_client = MagicMock()
        mock_client.fetch_unread.return_value = []
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("pipeline.FreshRSSClient", return_value=mock_client):
            results = list(fetch_and_score_iter(_MINIMAL_CFG, _TOPICS))

        assert results == []

    def test_cumulative_count_accumulates_across_batches(self):
        """Total fetched count accumulates correctly across multiple batches."""
        article = Article(
            id="1",
            title="kubernetes",
            url="http://a.com",
            content="k8s",
            summary="",
            feed_title="Blog",
            published=1700000000,
        )
        mock_client = MagicMock()
        mock_client.fetch_unread.return_value = [[article, article], [article]]
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("pipeline.FreshRSSClient", return_value=mock_client):
            results = list(fetch_and_score_iter(_MINIMAL_CFG, _TOPICS))

        assert len(results) == 2
        assert results[0][1] == 2  # first batch: 2 articles
        assert results[1][1] == 3  # second batch: cumulative 3


# ---------------------------------------------------------------------------
# rescore_articles
# ---------------------------------------------------------------------------


class TestRescoreArticles:
    _RAW_ROWS = [
        {
            "id": "1",
            "title": "kubernetes deployment guide",
            "url": "http://a.com",
            "content": "kubernetes k8s cluster pod",
            "feed_title": "Tech",
            "published": 1700000000,
        },
        {
            "id": "2",
            "title": "weather forecast",
            "url": "http://b.com",
            "content": "sunny skies tomorrow",
            "feed_title": "News",
            "published": 1700000001,
        },
        {
            "id": "3",
            "title": "SRE incident postmortem",
            "url": "http://c.com",
            "content": "sre on-call incident pagerduty",
            "feed_title": "Ops",
            "published": 1700000002,
        },
    ]

    def test_filters_articles_below_min_score(self):
        """Articles scoring below min_score are excluded from results."""
        result = rescore_articles(
            self._RAW_ROWS,
            _TOPICS,
            min_score=5.0,  # high threshold to filter most articles
        )
        # Only articles with keyword matches score highly enough
        for art in result:
            assert art["score"] >= 5.0

    def test_returns_all_matching_articles_above_min_score(self):
        """Articles above min_score are all included."""
        result = rescore_articles(
            self._RAW_ROWS,
            _TOPICS,
            min_score=0.0,  # accept all
        )
        assert len(result) == 3

    def test_results_sorted_by_score_descending(self):
        """Results are sorted by score descending."""
        result = rescore_articles(
            self._RAW_ROWS,
            _TOPICS,
            min_score=0.0,
        )
        scores = [a["score"] for a in result]
        assert scores == sorted(scores, reverse=True)

    def test_score_reflects_topic_matches(self):
        """Articles with topic keyword matches have higher scores than unmatched."""
        result = rescore_articles(
            self._RAW_ROWS,
            _TOPICS,
            min_score=0.0,
        )
        scores_by_id = {a["id"]: a["score"] for a in result}
        # weather article (id=2) has no keyword matches → lowest score
        assert scores_by_id["2"] < scores_by_id["1"]
        assert scores_by_id["2"] < scores_by_id["3"]

    def test_empty_raw_returns_empty_list(self):
        """Empty input returns empty output."""
        result = rescore_articles([], _TOPICS)
        assert result == []
