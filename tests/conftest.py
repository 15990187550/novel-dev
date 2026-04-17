import os

# Force tests to use a shared SQLite file DB so the global engine
# (used by MCP server and non-overridden API routes) can connect
# to the same database across connections.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_novel_dev.db"

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import AsyncMock

from novel_dev.db.models import Base
from novel_dev.db.engine import engine, async_session_maker


@pytest.fixture
def mock_llm_factory(monkeypatch):
    from novel_dev.llm import llm_factory
    from novel_dev.llm.models import LLMResponse
    from novel_dev.schemas.outline import SynopsisData, CharacterArc, PlotMilestone

    default_synopsis = SynopsisData(
        title="天玄纪元",
        logline="主角在修炼世界中崛起",
        core_conflict="个人复仇与天下大义",
        themes=["成长", "复仇"],
        character_arcs=[
            CharacterArc(
                name="主角",
                arc_summary="从废柴到巅峰",
                key_turning_points=["觉醒", "突破"],
            )
        ],
        milestones=[
            PlotMilestone(
                act="第一幕", summary="入门试炼", climax_event="外门大比"
            )
        ],
        estimated_volumes=3,
        estimated_total_chapters=90,
        estimated_total_words=270000,
    )

    async def mock_acomplete(messages):
        if isinstance(messages, list) and any(
            (isinstance(m, dict) and "大纲生成专家" in str(m.get("content", "")))
            or (hasattr(m, "content") and "大纲生成专家" in str(m.content))
            for m in messages
        ):
            return LLMResponse(text=default_synopsis.model_dump_json())
        return LLMResponse(text="{}")

    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = mock_acomplete
    monkeypatch.setattr(llm_factory, "get", lambda agent, task=None: mock_client)


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
