"""Domain model for articles."""

from dataclasses import dataclass, field
from typing import TypedDict


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


def article_from_row(row: dict) -> Article:
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
