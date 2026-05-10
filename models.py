"""Domain model for articles."""

from dataclasses import dataclass, field


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
