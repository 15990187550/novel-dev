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
async def test_get_logs_returns_persisted_history(async_session):
    async def override():
        yield async_session

    async_session.add_all([
        NovelState(novel_id="novel-log-history", current_phase="brainstorming", checkpoint_data={}),
        AgentLog(novel_id="novel-log-history", agent="OldAgent", message="较早日志", level="info"),
        AgentLog(
            novel_id="novel-log-history",
            agent="NewAgent",
            message="最近日志",
            level="warning",
            event="agent.step",
            status="failed",
            node="review",
            task="score",
            meta={"reason": "test"},
            duration_ms=123,
        ),
        AgentLog(novel_id="novel-other", agent="OtherAgent", message="不应返回", level="info"),
    ])
    await async_session.commit()

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/novel-log-history/logs")
            assert resp.status_code == 200
            body = resp.json()
            assert body["novel_id"] == "novel-log-history"
            assert [entry["message"] for entry in body["logs"]] == ["较早日志", "最近日志"]
            assert body["logs"][1]["event"] == "agent.step"
            assert body["logs"][1]["metadata"] == {"reason": "test"}
            assert body["logs"][1]["duration_ms"] == 123
    finally:
        app.dependency_overrides.clear()


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
            body = resp.json()
            assert body["deleted_count"] == 1
            assert body["audit_log"]["event"] == "logs.clear"
            assert body["audit_log"]["metadata"]["deleted_count"] == 1

        cleared = await async_session.execute(
            select(AgentLog).where(AgentLog.novel_id == "novel-log-clear").order_by(AgentLog.timestamp)
        )
        kept = await async_session.execute(
            select(AgentLog).where(AgentLog.novel_id == "novel-keep")
        )
        remaining = list(cleared.scalars())
        assert len(remaining) == 1
        assert remaining[0].event == "logs.clear"
        assert remaining[0].meta == {"deleted_count": 1}
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
