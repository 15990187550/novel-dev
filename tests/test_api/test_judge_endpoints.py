import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router, get_session
from novel_dev.db.models import JudgePromptVersion

app = FastAPI()
app.include_router(router)


def _override_session(async_session):
    async def override():
        yield async_session

    return override


@pytest.mark.asyncio
async def test_list_judge_prompt_versions(async_session):
    pv = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="a", is_active=True)
    async_session.add(pv)
    await async_session.flush()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/judge-prompt-versions")
        assert resp.status_code == 200
        data = resp.json()
        assert any(d["version"] == "v1" for d in data)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_judge_prompt_version(async_session):
    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/judge-prompt-versions", json={
                "version": "judge-v1",
                "agent_name": "judge_agent",
                "prompt_text": "你是一位...",
            })
        assert resp.status_code == 201
        data = resp.json()
        assert data["version"] == "judge-v1"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_activate_judge_prompt_version(async_session):
    pv = JudgePromptVersion(version="v2", agent_name="judge_agent", prompt_text="a", is_active=False)
    async_session.add(pv)
    await async_session.flush()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"/api/judge-prompt-versions/{pv.id}/activate")
        assert resp.status_code == 200
        await async_session.refresh(pv)
        assert pv.is_active is True
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_judge_call_stats(async_session):
    from novel_dev.db.models import JudgeCallLog
    from datetime import datetime, timedelta
    for i in range(3):
        log = JudgeCallLog(
            decision_id=f"d{i}", experiment_id="exp_1",
            prompt_version_id="p", model="claude-sonnet-4-6",
            input_tokens=1000, output_tokens=100, latency_ms=2000, cost_usd=0.01,
            called_at=datetime.utcnow() - timedelta(hours=i),
        )
        async_session.add(log)
    await async_session.flush()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/judge-call-stats?experiment_id=exp_1&window_days=14")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_calls"] == 3
        assert abs(data["total_cost_usd"] - 0.03) < 1e-6
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_post_judge_sweeper_tick(async_session):
    from novel_dev.db.models import JudgeABTest
    ab = JudgeABTest(
        baseline_version="v1",
        challenger_version="v2",
        agent_name="judge_agent",
        status="running",
    )
    async_session.add(ab)
    await async_session.flush()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/judge-sweeper/tick")
        assert resp.status_code == 200
        data = resp.json()
        assert "decisions" in data
        assert isinstance(data["decisions"], list)
    finally:
        app.dependency_overrides.clear()
