from collections import deque

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from novel_dev.api.routes import get_session, router
from novel_dev.db.models import AgentLog, NovelState
from novel_dev.services.log_service import LogService


app = FastAPI()
app.include_router(router)


@pytest.fixture(autouse=True)
def clear_log_service_state():
    LogService._buffers.clear()
    LogService._listeners.clear()
    LogService._pending_tasks.clear()


@pytest.mark.asyncio
async def test_delete_logs_clears_persisted_and_buffered_logs(async_session):
    async def override():
        yield async_session

    async_session.add_all([
        NovelState(novel_id="novel-log-clear", current_phase="brainstorming", checkpoint_data={}),
        AgentLog(novel_id="novel-log-clear", agent="TestAgent", message="要清空", level="info"),
        AgentLog(novel_id="novel-keep", agent="TestAgent", message="保留", level="info"),
    ])
    await async_session.commit()
    LogService._buffers["novel-log-clear"] = deque([{"agent": "TestAgent", "message": "buffered"}])

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete("/api/novels/novel-log-clear/logs")
            assert resp.status_code == 200
            assert resp.json()["deleted_count"] == 1

        cleared = await async_session.execute(
            select(AgentLog).where(AgentLog.novel_id == "novel-log-clear")
        )
        kept = await async_session.execute(
            select(AgentLog).where(AgentLog.novel_id == "novel-keep")
        )
        assert cleared.scalars().first() is None
        assert kept.scalars().first() is not None
        assert list(LogService._buffers.get("novel-log-clear", [])) == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_logs_requires_existing_novel(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete("/api/novels/missing/logs")
            assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()
