import os

# Force tests to use a shared SQLite file DB so the global engine
# (used by MCP server and non-overridden API routes) can connect
# to the same database across connections.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_novel_dev.db"

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import Base
from novel_dev.db.engine import engine, async_session_maker


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(autouse=True)
async def cleanup_tables():
    yield
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


@pytest_asyncio.fixture
async def async_session():
    async with async_session_maker() as session:
        yield session
        await session.rollback()
