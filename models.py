"""Domain model for articles."""

from dataclasses import dataclass, field
from typing import Any, TypedDict, cast


@dataclass
class Article:
    id: str
    title: str
    url: str
    content: str
    summary: str
    feed_title: str
    published: int  # Unix timestamp
    categories: list[str] = field(default_factory=list)


class ArticleDict(TypedDict, total=False):
    id: str
    title: str
    url: str
    feed_title: str
    published: int
    score: float
    matched_topics: dict[str, float]
    matched_keywords: list[str]
    top_topic: "str | None"
    feed_weight: float
    summary: str
    _content: str
    bookmarked: bool
    _read: bool


class SnoozeReminderDict(TypedDict):
    """Shape of snooze reminder records returned by db.get_due_snoozes()."""

    article_id: str
    chat_id: str
    snooze_until: int
    title: str
    url: str


class DbArticleRow(TypedDict):
    """Shape of rows returned by db.load_for_rescore()."""

    id: str
    title: str
    url: str
    content: str
    feed_title: str
    published: int


def strip_content(article: ArticleDict) -> ArticleDict:
    """
    Return a copy without `_content`, the full article text.

    `_content` is only needed on the way to the DB (see db._article_to_row): it
    averages ~10 kB per article, so keeping it in the cache both bloats memory and
    leaks the whole text through the public /api/articles.

    Note `_read` is deliberately preserved despite its underscore: the frontend
    reads it (static/js/render.js:157) to flag already-read entries.
    """
    return cast(ArticleDict, {k: v for k, v in article.items() if k != "_content"})


def article_from_row(row: dict[str, Any]) -> Article:
    """Reconstruct an Article from a DB row dict (for rescore operations)."""
    return Article(
        id=row["id"],
        title=row["title"],
        url=row["url"],
        content=row["content"],
        summary="",
        feed_title=row["feed_title"],
        published=row["published"],
    )
