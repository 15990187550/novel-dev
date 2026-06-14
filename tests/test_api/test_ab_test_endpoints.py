import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router, get_session

app = FastAPI()
app.include_router(router)


def _override_session(async_session):
    async def override():
        yield async_session

    return override


@pytest.mark.asyncio
async def test_start_ab_test(async_session):
    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/prompts/critic/versions",
                json={"version": "v1.0", "content": "a", "is_active": True},
            )
            await client.post(
                "/api/prompts/critic/versions",
                json={"version": "v2.0", "content": "b"},
            )

            resp = await client.post(
                "/api/ab-tests",
                json={
                    "agent_name": "critic",
                    "baseline_version": "v1.0",
                    "challenger_version": "v2.0",
                    "max_samples": 5,
                    "min_samples": 2,
                },
            )
        assert resp.status_code == 201
        assert resp.json()["status"] == "running"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_ab_tests(async_session):
    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/ab-tests")
        assert resp.status_code == 200
        assert "tests" in resp.json()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_ab_test_results(async_session):
    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/prompts/critic/versions",
                json={"version": "v1.0", "content": "a", "is_active": True},
            )
            await client.post(
                "/api/prompts/critic/versions",
                json={"version": "v2.0", "content": "b"},
            )
            start = await client.post(
                "/api/ab-tests",
                json={
                    "agent_name": "critic",
                    "baseline_version": "v1.0",
                    "challenger_version": "v2.0",
                },
            )
            test_id = start.json()["id"]
            resp = await client.get(f"/api/ab-tests/{test_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_stop_ab_test(async_session):
    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/prompts/critic/versions",
                json={"version": "v1.0", "content": "a", "is_active": True},
            )
            await client.post(
                "/api/prompts/critic/versions",
                json={"version": "v2.0", "content": "b"},
            )
            start = await client.post(
                "/api/ab-tests",
                json={
                    "agent_name": "critic",
                    "baseline_version": "v1.0",
                    "challenger_version": "v2.0",
                },
            )
            test_id = start.json()["id"]
            resp = await client.post(f"/api/ab-tests/{test_id}/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "aborted"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_declare_winner(async_session):
    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/prompts/critic/versions",
                json={"version": "v1.0", "content": "a", "is_active": True},
            )
            await client.post(
                "/api/prompts/critic/versions",
                json={"version": "v2.0", "content": "b"},
            )
            start = await client.post(
                "/api/ab-tests",
                json={
                    "agent_name": "critic",
                    "baseline_version": "v1.0",
                    "challenger_version": "v2.0",
                },
            )
            test_id = start.json()["id"]
            resp = await client.post(
                f"/api/ab-tests/{test_id}/declare-winner",
                json={"winner": "challenger"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
    finally:
        app.dependency_overrides.clear()
