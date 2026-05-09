"""Shared test fixtures."""

import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from db import metadata, set_engine_for_testing

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db():
    """Fresh in-memory SQLite database for each test function."""
    engine = create_async_engine(TEST_DB_URL, echo=False)
    set_engine_for_testing(engine)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()
    set_engine_for_testing(None)
