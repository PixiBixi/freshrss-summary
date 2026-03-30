"""Shared test fixtures."""

import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

import db as db_module
from db import metadata

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db():
    """Fresh in-memory SQLite database for each test function."""
    engine = create_async_engine(TEST_DB_URL, echo=False)
    db_module._engine = engine
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()
    db_module._engine = None
