import pytest
from datetime import datetime, timedelta
from sqlalchemy import select

from novel_dev.services.log_service import LogService, agent_step, logged_agent_step
from novel_dev.db.models import AgentLog


@pytest.fixture(autouse=True)
def clear_log_service_state():
    LogService._buffers.clear()
    LogService._listeners.clear()
    LogService._pending_tasks.clear()


@pytest.mark.asyncio
async def test_add_log_publishes_structured_node_fields():
    service = LogService()
    queue = service.subscribe("novel-log")

    service.add_log(
        "novel-log",
        "TestAgent",
        "节点完成",
        level="info",
        event="agent.step",
        status="succeeded",
        node="extract",
        task="extract_setting",
        metadata={"chunk": 2},
        duration_ms=12,
    )

    entry = await queue.get()

    assert entry["agent"] == "TestAgent"
    assert entry["message"] == "节点完成"
    assert entry["event"] == "agent.step"
    assert entry["status"] == "succeeded"
    assert entry["node"] == "extract"
    assert entry["task"] == "extract_setting"
    assert entry["metadata"] == {"chunk": 2}
    assert entry["duration_ms"] == 12


@pytest.mark.asyncio
async def test_agent_step_logs_started_succeeded_and_failed_entries():
    service = LogService()

    async with agent_step(
        "novel-step",
        "TestAgent",
        "测试节点",
        node="unit",
        task="test_task",
        metadata={"attempt": 1},
    ):
        pass

    with pytest.raises(ValueError, match="boom"):
        async with agent_step("novel-step", "TestAgent", "失败节点", node="broken"):
            raise ValueError("boom")

    entries = list(service._buffers["novel-step"])

    assert [entry["status"] for entry in entries] == ["started", "succeeded", "started", "failed"]
    assert entries[0]["message"] == "测试节点开始"
    assert entries[1]["message"] == "测试节点完成"
    assert entries[1]["duration_ms"] >= 0
    assert entries[1]["metadata"] == {"attempt": 1}
    assert entries[3]["level"] == "error"
    assert "boom" in entries[3]["metadata"]["error"]


@pytest.mark.asyncio
async def test_logged_agent_step_extracts_novel_id_and_wraps_async_method():
    class DemoAgent:
        @logged_agent_step("DemoAgent", "运行 Demo", node="demo", task="demo_task")
        async def run(self, novel_id: str):
            return "ok"

    result = await DemoAgent().run("novel-decorator")

    assert result == "ok"
    entries = list(LogService._buffers["novel-decorator"])
    assert [entry["status"] for entry in entries] == ["started", "succeeded"]
    assert entries[0]["agent"] == "DemoAgent"
    assert entries[0]["node"] == "demo"
    assert entries[1]["task"] == "demo_task"


@pytest.mark.asyncio
async def test_add_log_persists_entries(async_session):
    service = LogService()

    service.add_log(
        "novel-persist",
        "PersistAgent",
        "持久化日志",
        level="warning",
        event="unit.event",
        status="succeeded",
        node="unit",
        task="persist",
        metadata={"k": "v"},
        duration_ms=7,
    )
    await service.flush_pending()

    result = await async_session.execute(
        select(AgentLog).where(AgentLog.novel_id == "novel-persist")
    )
    row = result.scalar_one()
    assert row.agent == "PersistAgent"
    assert row.message == "持久化日志"
    assert row.level == "warning"
    assert row.event == "unit.event"
    assert row.status == "succeeded"
    assert row.node == "unit"
    assert row.task == "persist"
    assert row.meta == {"k": "v"}
    assert row.duration_ms == 7


@pytest.mark.asyncio
async def test_subscribe_with_history_replays_recent_persisted_logs_only(async_session):
    now = datetime.utcnow()
    async_session.add_all([
        AgentLog(
            novel_id="novel-history",
            timestamp=now - timedelta(days=8),
            agent="OldAgent",
            message="旧日志",
            level="info",
        ),
        AgentLog(
            novel_id="novel-history",
            timestamp=now - timedelta(days=1),
            agent="RecentAgent",
            message="最近日志",
            level="info",
        ),
    ])
    await async_session.commit()

    service = LogService()
    queue = await service.subscribe_with_history("novel-history")

    entry = await queue.get()
    assert entry["agent"] == "RecentAgent"
    assert entry["message"] == "最近日志"
    assert queue.empty()
