"""Unit tests for scorer.py — pure functions, no I/O."""

import pytest

from freshrss_client import Article
from scorer import (
    TopicConfig,
    _strip_html,
    analyze_favorites,
    build_topics,
    score_article,
    score_articles,
)


def make_article(**kwargs) -> Article:
    defaults = dict(
        id="art-1",
        title="Test Article",
        url="https://example.com",
        content="",
        summary="",
        feed_title="Test Feed",
        published=1_000_000,
    )
    defaults.update(kwargs)
    return Article(**defaults)


def make_topic(name: str, keywords: list[str], weight: float = 1.0) -> TopicConfig:
    return TopicConfig(name=name, keywords=keywords, weight=weight)


# ── _strip_html ─────────────────────────────────────────────────────────────


class TestStripHtml:
    def test_removes_tags(self):
        assert _strip_html("<p>Hello <b>world</b></p>") == " Hello  world  "

    def test_empty_string(self):
        assert _strip_html("") == ""

    def test_no_tags(self):
        assert _strip_html("plain text") == "plain text"

    def test_self_closing_tags(self):
        result = _strip_html("line1<br/>line2")
        assert "line1" in result
        assert "line2" in result
        assert "<" not in result


# ── TopicConfig ──────────────────────────────────────────────────────────────


class TestTopicConfig:
    def test_pattern_compiled(self):
        t = make_topic("k8s", ["kubernetes", "kubectl"])
        assert t.pattern is not None
        assert t.pattern.findall("kubernetes is cool") == ["kubernetes"]

    def test_no_keywords_no_pattern(self):
        t = make_topic("empty", [])
        assert t.pattern is None

    def test_word_boundary(self):
        t = make_topic("k8s", ["go"])
        # "go" inside "google" should not match (word boundary)
        assert t.pattern.findall("google cloud") == []
        assert t.pattern.findall("go programming") == ["go"]


# ── build_topics ─────────────────────────────────────────────────────────────


class TestBuildTopics:
    def test_builds_from_config(self):
        cfg = {
            "topics": {
                "Kubernetes": {"keywords": ["kubernetes", "kubectl"], "weight": 2.0},
                "Terraform": {"keywords": ["terraform"], "weight": 1.5},
            }
        }
        topics = build_topics(cfg)
        assert len(topics) == 2
        assert {t.name for t in topics} == {"Kubernetes", "Terraform"}

    def test_keywords_lowercased(self):
        cfg = {"topics": {"SRE": {"keywords": ["Prometheus", "Grafana"]}}}
        topics = build_topics(cfg)
        assert topics[0].keywords == ["prometheus", "grafana"]

    def test_weight_default(self):
        cfg = {"topics": {"X": {"keywords": ["x"]}}}
        topics = build_topics(cfg)
        assert topics[0].weight == 1.0

    def test_empty_config(self):
        assert build_topics({}) == []
        assert build_topics({"topics": {}}) == []


# ── score_article ─────────────────────────────────────────────────────────────


class TestScoreArticle:
    def test_no_match(self):
        article = make_article(title="Nothing relevant", content="some random text")
        topic = make_topic("k8s", ["kubernetes"])
        result = score_article(article, [topic])
        assert result.score == 0
        assert result.matched_topics == {}
        assert result.matched_keywords == []

    def test_title_match_weighted(self):
        article = make_article(title="kubernetes tutorial", content="")
        topic = make_topic("k8s", ["kubernetes"], weight=1.0)
        result = score_article(article, [topic], title_weight=3)
        # 1 title match × 3 = 3 hits × weight 1.0 = 3.0
        assert result.score == 3.0
        assert "k8s" in result.matched_topics
        assert "kubernetes" in result.matched_keywords

    def test_content_match(self):
        article = make_article(title="intro", content="<p>kubernetes is great</p>")
        topic = make_topic("k8s", ["kubernetes"], weight=2.0)
        result = score_article(article, [topic], title_weight=3)
        # 0 title + 1 content = 1 hit × weight 2.0 = 2.0
        assert result.score == 2.0

    def test_html_stripped_before_matching(self):
        article = make_article(title="test", content="<div>kubernetes</div>")
        topic = make_topic("k8s", ["kubernetes"])
        result = score_article(article, [topic])
        assert result.score > 0

    def test_multiple_keywords_same_topic(self):
        article = make_article(title="kubernetes kubectl demo", content="")
        topic = make_topic("k8s", ["kubernetes", "kubectl"], weight=1.0)
        result = score_article(article, [topic], title_weight=3)
        # 2 title matches × 3 = 6 hits
        assert result.score == 6.0
        assert set(result.matched_keywords) == {"kubernetes", "kubectl"}

    def test_multiple_topics(self):
        article = make_article(title="kubernetes terraform", content="argocd")
        topics = [
            make_topic("k8s", ["kubernetes"], weight=1.0),
            make_topic("tf", ["terraform"], weight=2.0),
            make_topic("cd", ["argocd"], weight=1.5),
        ]
        result = score_article(article, topics, title_weight=3)
        assert "k8s" in result.matched_topics
        assert "tf" in result.matched_topics
        assert "cd" in result.matched_topics
        assert result.score > 0

    def test_top_topic_is_highest_scorer(self):
        # "kubernetes" twice in title → k8s wins
        article = make_article(title="kubernetes kubernetes", content="terraform")
        topics = [
            make_topic("k8s", ["kubernetes"], weight=1.0),
            make_topic("tf", ["terraform"], weight=1.0),
        ]
        result = score_article(article, topics, title_weight=3)
        assert result.top_topic == "k8s"

    def test_top_topic_none_when_no_match(self):
        article = make_article(title="nothing")
        result = score_article(article, [make_topic("k8s", ["kubernetes"])])
        assert result.top_topic is None

    def test_no_topics(self):
        article = make_article(title="kubernetes")
        result = score_article(article, [])
        assert result.score == 0


# ── score_articles ────────────────────────────────────────────────────────────


class TestScoreArticles:
    def test_min_score_filter(self):
        articles = [
            make_article(id="match", title="kubernetes"),
            make_article(id="no-match", title="nothing"),
        ]
        topic = make_topic("k8s", ["kubernetes"], weight=1.0)
        result = score_articles(articles, [topic], title_weight=3, min_score=1.0)
        assert len(result) == 1
        assert result[0].article.id == "match"

    def test_sorted_by_score_desc(self):
        articles = [
            make_article(id="low", title="kubernetes"),
            make_article(id="high", title="kubernetes kubernetes"),
        ]
        topic = make_topic("k8s", ["kubernetes"])
        result = score_articles(articles, [topic], title_weight=3, min_score=0)
        assert result[0].article.id == "high"

    def test_empty_articles(self):
        assert score_articles([], [make_topic("k8s", ["kubernetes"])]) == []

    def test_no_topics_all_score_zero(self):
        articles = [make_article(title="kubernetes")]
        result = score_articles(articles, [], min_score=0)
        assert len(result) == 1
        assert result[0].score == 0


# ── ScoredArticle.to_dict ─────────────────────────────────────────────────────


class TestToDict:
    def test_structure(self):
        article = make_article(
            id="x",
            title="k8s article",
            url="http://x.com",
            content="kubernetes is cool",
            feed_title="Feed",
        )
        topic = make_topic("k8s", ["kubernetes"])
        d = score_article(article, [topic]).to_dict()

        for key in (
            "id",
            "title",
            "url",
            "feed_title",
            "published",
            "score",
            "matched_topics",
            "matched_keywords",
            "top_topic",
            "summary",
            "_content",
        ):
            assert key in d, f"Missing key: {key}"

    def test_keywords_capped_at_10(self):
        many_kw = [f"kw{i}" for i in range(15)]
        topic = make_topic("t", many_kw)
        content = " ".join(many_kw)
        article = make_article(content=content)
        d = score_article(article, [topic]).to_dict()
        assert len(d["matched_keywords"]) <= 10

    def test_summary_capped_at_400(self):
        long_content = "kubernetes " * 100
        article = make_article(content=long_content)
        topic = make_topic("k8s", ["kubernetes"])
        d = score_article(article, [topic]).to_dict()
        assert len(d["summary"]) <= 400

    def test_score_rounded(self):
        article = make_article(title="kubernetes", content="kubernetes")
        topic = make_topic("k8s", ["kubernetes"], weight=1.333)
        d = score_article(article, [topic], title_weight=3).to_dict()
        # score should be rounded to 2 decimal places
        assert d["score"] == round(d["score"], 2)


# ── analyze_favorites ─────────────────────────────────────────────────────────


class TestAnalyzeFavorites:
    def test_empty_returns_defaults(self):
        result = analyze_favorites([], [])
        assert result == {"total_starred": 0, "top_keywords": [], "suggestions": {}}

    def test_hit_rate_calculation(self):
        articles = [
            make_article(id="1", title="kubernetes deploy"),
            make_article(id="2", title="kubernetes tutorial"),
            make_article(id="3", title="terraform plan"),
        ]
        topics = [
            make_topic("k8s", ["kubernetes"], weight=1.0),
            make_topic("tf", ["terraform"], weight=1.0),
        ]
        result = analyze_favorites(articles, topics, title_weight=3)

        assert result["total_starred"] == 3
        k8s = result["suggestions"]["k8s"]
        tf = result["suggestions"]["tf"]
        assert k8s["starred_count"] == 2
        assert tf["starred_count"] == 1
        assert k8s["starred_rate"] == pytest.approx(66.7, abs=0.1)

    def test_suggested_weight_increases_with_hits(self):
        articles = [make_article(title="kubernetes") for _ in range(10)]
        topics = [make_topic("k8s", ["kubernetes"], weight=2.0)]
        result = analyze_favorites(articles, topics)
        assert result["suggestions"]["k8s"]["suggested"] > 2.0

    def test_no_hits_weight_unchanged(self):
        articles = [make_article(title="random news")]
        topics = [make_topic("k8s", ["kubernetes"], weight=3.0)]
        result = analyze_favorites(articles, topics)
        assert result["suggestions"]["k8s"]["suggested"] == 3.0

    def test_top_keywords_sorted_by_frequency(self):
        articles = [
            make_article(title="kubernetes kubernetes kubernetes"),
            make_article(title="terraform"),
        ]
        topics = [
            make_topic("k8s", ["kubernetes"]),
            make_topic("tf", ["terraform"]),
        ]
        result = analyze_favorites(articles, topics, title_weight=3)
        keywords = [kw for kw, _ in result["top_keywords"]]
        assert keywords[0] == "kubernetes"
