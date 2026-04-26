"""SQLAlchemy async persistence for scored articles.

Supported backends (set DATABASE_URL env var or database.url in config.yaml):
  SQLite (default) : sqlite+aiosqlite:///./data/articles.db
  MySQL            : mysql+aiomysql://user:pass@host/dbname
  PostgreSQL       : postgresql+asyncpg://user:pass@host/dbname
"""

import json
import logging
import time
from pathlib import Path

from sqlalchemy import (
    Column,
    Float,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    delete,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).parent / "data" / "articles.db"
DEFAULT_DB_URL = f"sqlite+aiosqlite:///{DEFAULT_DB_PATH}"

metadata = MetaData()

articles_table = Table(
    "articles",
    metadata,
    Column("id", Text, primary_key=True),
    Column("title", Text, nullable=False),
    Column("url", Text),
    Column("feed_title", Text),
    Column("published", Integer),
    Column("score", Float),
    Column("matched_topics", Text),
    Column("matched_keywords", Text),
    Column("top_topic", Text),
    Column("summary", Text),
    Column("content", Text),
    Column("fetched_at", Integer, nullable=False),
    Column("read_at", Integer),  # NULL = unread; set = soft-deleted (marked as read)
    Index("idx_score", "score"),
)

meta_table = Table(
    "meta",
    metadata,
    Column("key", Text, primary_key=True),
    Column("value", Text),
)

bookmarks_table = Table(
    "bookmarks",
    metadata,
    Column("id", Text, primary_key=True),
    Column("bookmarked_at", Integer, nullable=False),
)

pending_sync_table = Table(
    "pending_read_sync",
    metadata,
    Column("id", Text, primary_key=True),
    Column("queued_at", Integer, nullable=False),
)

users_table = Table(
    "users",
    metadata,
    Column("username", Text, primary_key=True),
    Column("password_hash", Text, nullable=False),
    Column("created_at", Integer, nullable=False),
)

_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Database not initialised. Call init_db() first.")
    return _engine


async def init_db(url: str = DEFAULT_DB_URL) -> None:
    """Create engine, tables, and run any pending migrations."""
    global _engine

    # Ensure data/ dir exists for SQLite
    if url.startswith("sqlite"):
        DEFAULT_DB_PATH.parent.mkdir(exist_ok=True)

    _engine = create_async_engine(url, echo=False)

    async with _engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

        # Migration: content column (pre-existing SQLite DBs)
        try:
            await conn.execute(text("ALTER TABLE articles ADD COLUMN content TEXT DEFAULT ''"))
            logger.info("DB migrated: added content column")
        except Exception:
            pass  # column already exists

        # Migration: read_at column
        try:
            await conn.execute(text("ALTER TABLE articles ADD COLUMN read_at INTEGER"))
            logger.info("DB migrated: added read_at column")
        except Exception:
            pass  # column already exists

    safe_url = url.split("@")[-1] if "@" in url else url
    logger.info("DB ready: %s", safe_url)


# ---------------------------------------------------------------------------
# Articles
# ---------------------------------------------------------------------------


async def save_articles(articles: list[dict], total_fetched: int) -> None:
    """Replace unread articles with a fresh scored set; purge read articles older than 7 days."""
    now = int(time.time())
    cutoff_read = now - 7 * 86400
    async with get_engine().begin() as conn:
        # Replace only unread articles (read_at IS NULL)
        await conn.execute(delete(articles_table).where(articles_table.c.read_at.is_(None)))
        # Purge read articles older than 7 days
        await conn.execute(
            delete(articles_table).where(
                articles_table.c.read_at.is_not(None),
                articles_table.c.read_at < cutoff_read,
            )
        )
        if articles:
            await conn.execute(
                insert(articles_table),
                [
                    {
                        "id": a["id"],
                        "title": a["title"],
                        "url": a["url"],
                        "feed_title": a["feed_title"],
                        "published": a["published"],
                        "score": a["score"],
                        "matched_topics": json.dumps(a["matched_topics"]),
                        "matched_keywords": json.dumps(a["matched_keywords"]),
                        "top_topic": a.get("top_topic"),
                        "summary": a["summary"],
                        "content": a.get("_content", a["summary"]),
                        "fetched_at": now,
                    }
                    for a in articles
                ],
            )
        await _set_meta(conn, "last_refresh", str(now))
        await _set_meta(conn, "total_fetched", str(total_fetched))
    logger.info("Saved %d articles to DB", len(articles))


async def load_articles() -> tuple[list[dict], float | None, int]:
    """Load scored articles from DB for cache warm-up. Excludes raw content."""
    async with get_engine().connect() as conn:
        rows = (
            (
                await conn.execute(
                    select(
                        articles_table,
                        bookmarks_table.c.id.is_not(None).label("bookmarked"),
                    )
                    .select_from(
                        articles_table.outerjoin(
                            bookmarks_table,
                            articles_table.c.id == bookmarks_table.c.id,
                        )
                    )
                    .where(articles_table.c.read_at.is_(None))
                    .order_by(articles_table.c.score.desc())
                )
            )
            .mappings()
            .all()
        )

        meta = {
            r["key"]: r["value"] for r in (await conn.execute(select(meta_table))).mappings().all()
        }

    articles = [
        {
            "id": r["id"],
            "title": r["title"],
            "url": r["url"],
            "feed_title": r["feed_title"],
            "published": r["published"],
            "score": r["score"],
            "matched_topics": json.loads(r["matched_topics"] or "{}"),
            "matched_keywords": json.loads(r["matched_keywords"] or "[]"),
            "top_topic": r["top_topic"],
            "summary": r["summary"] or "",
            "bookmarked": bool(r["bookmarked"]),
        }
        for r in rows
    ]

    last_refresh = float(meta["last_refresh"]) if "last_refresh" in meta else None
    total_fetched = int(meta.get("total_fetched", 0))
    return articles, last_refresh, total_fetched


async def load_for_rescore() -> list[dict]:
    """Load articles with full content for re-scoring."""
    async with get_engine().connect() as conn:
        rows = (
            (
                await conn.execute(
                    select(
                        articles_table.c.id,
                        articles_table.c.title,
                        articles_table.c.url,
                        articles_table.c.feed_title,
                        articles_table.c.published,
                        articles_table.c.content,
                    )
                )
            )
            .mappings()
            .all()
        )
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "url": r["url"],
            "feed_title": r["feed_title"],
            "published": r["published"],
            "content": r["content"] or "",
        }
        for r in rows
    ]


async def get_scoring_config() -> dict | None:
    """Return scoring topics config from DB, or None if not yet persisted."""
    async with get_engine().connect() as conn:
        row = (
            await conn.execute(
                select(meta_table.c.value).where(meta_table.c.key == "scoring_config")
            )
        ).first()
    return json.loads(row[0]) if row else None


async def set_scoring_config(topics: dict) -> None:
    """Persist scoring topics config to DB."""
    async with get_engine().begin() as conn:
        await _set_meta(conn, "scoring_config", json.dumps(topics, ensure_ascii=False))


async def get_meta(key: str, default: str = "0") -> str:
    async with get_engine().connect() as conn:
        row = (
            await conn.execute(select(meta_table.c.value).where(meta_table.c.key == key))
        ).first()
    return row[0] if row else default


async def set_articles_read(ids: list[str]) -> None:
    """Soft-delete articles by setting read_at. Also removes associated bookmarks."""
    if not ids:
        return
    now = int(time.time())
    # SQLite caps IN-clause variables at 999 — chunk to stay safe on all backends.
    chunk_size = 500
    async with get_engine().begin() as conn:
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i : i + chunk_size]
            await conn.execute(
                update(articles_table).where(articles_table.c.id.in_(chunk)).values(read_at=now)
            )
            await conn.execute(delete(bookmarks_table).where(bookmarks_table.c.id.in_(chunk)))
    logger.info("Marked %d articles as read in DB", len(ids))


async def load_read_articles(days: int = 7) -> list[dict]:
    """Load articles marked as read (for 'show read' toggle)."""
    cutoff = int(time.time()) - days * 86400 if days > 0 else 0
    async with get_engine().connect() as conn:
        q = select(articles_table).where(articles_table.c.read_at.is_not(None))
        if cutoff > 0:
            q = q.where(articles_table.c.read_at >= cutoff)
        rows = (await conn.execute(q)).mappings().all()
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "url": r["url"],
            "feed_title": r["feed_title"],
            "published": r["published"],
            "score": r["score"],
            "matched_topics": json.loads(r["matched_topics"] or "{}"),
            "matched_keywords": json.loads(r["matched_keywords"] or "[]"),
            "top_topic": r["top_topic"],
            "summary": r["summary"] or "",
            "bookmarked": False,
            "_read": True,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Bookmarks
# ---------------------------------------------------------------------------


async def toggle_bookmark(article_id: str) -> bool:
    """Toggle bookmark for an article. Returns True if now bookmarked."""
    async with get_engine().begin() as conn:
        existing = (
            await conn.execute(
                select(bookmarks_table.c.id).where(bookmarks_table.c.id == article_id)
            )
        ).first()
        if existing:
            await conn.execute(delete(bookmarks_table).where(bookmarks_table.c.id == article_id))
            return False
        await conn.execute(
            insert(bookmarks_table).values(id=article_id, bookmarked_at=int(time.time()))
        )
        return True


async def get_bookmarked_ids() -> set[str]:
    async with get_engine().connect() as conn:
        rows = (await conn.execute(select(bookmarks_table.c.id))).all()
    return {r[0] for r in rows}


# ---------------------------------------------------------------------------
# Users / auth
# ---------------------------------------------------------------------------


async def has_users() -> bool:
    async with get_engine().connect() as conn:
        row = (await conn.execute(select(users_table.c.username).limit(1))).first()
    return row is not None


async def get_user_hash(username: str) -> str | None:
    async with get_engine().connect() as conn:
        row = (
            await conn.execute(
                select(users_table.c.password_hash).where(users_table.c.username == username)
            )
        ).first()
    return row[0] if row else None


async def set_user_password(username: str, password_hash: str) -> None:
    """Update the password hash for an existing user."""
    async with get_engine().begin() as conn:
        await conn.execute(
            update(users_table)
            .where(users_table.c.username == username)
            .values(password_hash=password_hash)
        )


async def upsert_user(username: str, password_hash: str) -> None:
    async with get_engine().begin() as conn:
        existing = (
            await conn.execute(
                select(users_table.c.username).where(users_table.c.username == username)
            )
        ).first()
        if existing:
            await conn.execute(
                update(users_table)
                .where(users_table.c.username == username)
                .values(password_hash=password_hash)
            )
        else:
            await conn.execute(
                insert(users_table).values(
                    username=username,
                    password_hash=password_hash,
                    created_at=int(time.time()),
                )
            )


# ---------------------------------------------------------------------------
# Pending read sync (outbox — retry when FreshRSS was offline)
# ---------------------------------------------------------------------------


async def add_pending_sync(ids: list[str]) -> None:
    """Queue article IDs for deferred mark-as-read sync to FreshRSS."""
    now = int(time.time())
    async with get_engine().begin() as conn:
        for article_id in ids:
            existing = (
                await conn.execute(
                    select(pending_sync_table.c.id).where(pending_sync_table.c.id == article_id)
                )
            ).first()
            if not existing:
                await conn.execute(insert(pending_sync_table).values(id=article_id, queued_at=now))
    logger.info("Queued %d article(s) for pending FreshRSS sync", len(ids))


async def get_pending_sync() -> list[str]:
    """Return all article IDs pending sync to FreshRSS."""
    async with get_engine().connect() as conn:
        rows = (await conn.execute(select(pending_sync_table.c.id))).all()
    return [r[0] for r in rows]


async def clear_pending_sync(ids: list[str]) -> None:
    """Remove successfully synced article IDs from the outbox."""
    if not ids:
        return
    chunk_size = 500
    async with get_engine().begin() as conn:
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i : i + chunk_size]
            await conn.execute(delete(pending_sync_table).where(pending_sync_table.c.id.in_(chunk)))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _set_meta(conn, key: str, value: str) -> None:
    """Portable upsert for the meta table (works on SQLite, MySQL, PostgreSQL)."""
    existing = (await conn.execute(select(meta_table.c.key).where(meta_table.c.key == key))).first()
    if existing:
        await conn.execute(update(meta_table).where(meta_table.c.key == key).values(value=value))
    else:
        await conn.execute(insert(meta_table).values(key=key, value=value))
