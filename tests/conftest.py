"""Shared test fixtures."""

import sys

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

import db as db_module
from db import metadata, set_engine_for_testing

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(autouse=True)
def _isolated_default_db(tmp_path, monkeypatch):
    """Point the default DB at tmp_path: no test may ever write data/articles.db."""
    path = tmp_path / "default.db"
    url = f"sqlite+aiosqlite:///{path}"
    monkeypatch.setattr(db_module, "DEFAULT_DB_PATH", path)
    monkeypatch.setattr(db_module, "DEFAULT_DB_URL", url)
    monkeypatch.setattr(db_module.init_db, "__defaults__", (url,))
    if "app" in sys.modules:  # app binds the name at import time
        monkeypatch.setattr(sys.modules["app"], "DEFAULT_DB_URL", url)
    return url


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
