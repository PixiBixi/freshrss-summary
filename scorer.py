"""Article scoring by topic relevance."""

import re
from dataclasses import dataclass, field

from freshrss_client import Article


@dataclass
class TopicConfig:
    name: str
    keywords: list[str]
    weight: float = 1.0
    pattern: re.Pattern | None = field(default=None, init=False, repr=False)

    def __post_init__(self):
        if self.keywords:
            # Single compiled regex with capturing group — one findall() per topic per text
            pat = r"\b(" + "|".join(re.escape(kw) for kw in self.keywords) + r")\b"
            self.pattern = re.compile(pat)


@dataclass
class ScoredArticle:
    article: Article
    score: float
    matched_topics: dict[str, float]  # topic_name -> contribution score
    matched_keywords: list[str]
    _stripped_content: str = field(default="", repr=False)

    @property
    def top_topic(self) -> str | None:
        if not self.matched_topics:
            return None
        return max(self.matched_topics, key=lambda t: self.matched_topics[t])

    def to_dict(self) -> dict:
        stripped = self._stripped_content
        return {
            "id": self.article.id,
            "title": self.article.title,
            "url": self.article.url,
            "feed_title": self.article.feed_title,
            "published": self.article.published,
            "score": round(self.score, 2),
            "matched_topics": {k: round(v, 2) for k, v in self.matched_topics.items()},
            "matched_keywords": self.matched_keywords[:10],
            "top_topic": self.top_topic,
            "summary": stripped[:400],
            "_content": stripped,  # full text, stored in DB for rescore — not sent to frontend
        }


def build_topics(topics: dict) -> list[TopicConfig]:
    result = []
    for name, cfg in topics.items():
        result.append(
            TopicConfig(
                name=name,
                keywords=[kw.lower() for kw in cfg.get("keywords", [])],
                weight=float(cfg.get("weight", 1.0)),
            )
        )
    return result


def score_article(
    article: Article,
    topics: list[TopicConfig],
    title_weight: int = 3,
) -> ScoredArticle:
    title_lower = article.title.lower()
    stripped_content = _strip_html(article.content)
    content_lower = stripped_content.lower()

    matched_topics: dict[str, float] = {}
    all_keywords: set[str] = set()

    for topic in topics:
        if topic.pattern is None:
            continue
        title_matches = topic.pattern.findall(title_lower)
        content_matches = topic.pattern.findall(content_lower)
        hits = len(title_matches) * title_weight + len(content_matches)
        if hits > 0:
            matched_topics[topic.name] = hits * topic.weight
            all_keywords.update(title_matches)
            all_keywords.update(content_matches)

    total_score = sum(matched_topics.values())

    return ScoredArticle(
        article=article,
        score=total_score,
        matched_topics=matched_topics,
        matched_keywords=sorted(all_keywords),
        _stripped_content=stripped_content,
    )


def score_articles(
    articles: list[Article],
    topics: list[TopicConfig],
    title_weight: int = 3,
    min_score: float = 1.0,
) -> list[ScoredArticle]:
    scored = []
    for article in articles:
        result = score_article(article, topics, title_weight)
        if result.score >= min_score:
            scored.append(result)

    scored.sort(key=lambda a: a.score, reverse=True)
    return scored


def analyze_favorites(
    starred: list[Article],
    topics: list[TopicConfig],
    title_weight: int = 3,
) -> dict:
    """
    Analyze starred articles to suggest weight adjustments.

    Strategy: if a topic appears in X% of starred articles, boost its weight
    by 0.5 * X (e.g. 60% hit rate → weight * 1.30). We never penalize topics
    with zero hits — absence of stars doesn't mean disinterest.

    Returns:
        total_starred  : number of starred articles analyzed
        top_keywords   : list of (keyword, count) sorted by frequency
        suggestions    : dict topic_name → {current, suggested, starred_count, starred_rate}
    """
    if not starred:
        return {"total_starred": 0, "top_keywords": [], "suggestions": {}}

    total = len(starred)
    topic_hits: dict[str, int] = {}
    keyword_freq: dict[str, int] = {}

    for article in starred:
        scored = score_article(article, topics, title_weight)
        for topic_name in scored.matched_topics:
            topic_hits[topic_name] = topic_hits.get(topic_name, 0) + 1
        for kw in scored.matched_keywords:
            keyword_freq[kw] = keyword_freq.get(kw, 0) + 1

    suggestions = {}
    for topic in topics:
        hit_count = topic_hits.get(topic.name, 0)
        hit_rate = hit_count / total
        suggested = round(topic.weight * (1 + 0.5 * hit_rate), 2) if hit_rate > 0 else topic.weight
        suggestions[topic.name] = {
            "current": topic.weight,
            "suggested": suggested,
            "starred_count": hit_count,
            "starred_rate": round(hit_rate * 100, 1),
        }

    return {
        "total_starred": total,
        "top_keywords": sorted(keyword_freq.items(), key=lambda x: -x[1]),
        "suggestions": suggestions,
    }


def _strip_html(text: str) -> str:
    """Remove HTML tags from text."""
    if not text:
        return ""
    return re.sub(r"<[^>]+>", " ", text)
