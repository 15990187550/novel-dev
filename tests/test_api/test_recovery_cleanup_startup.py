import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from novel_dev import api
from novel_dev.api import app as api_app
from novel_dev.api import run_startup_recovery_cleanup


@pytest.mark.asyncio
async def test_startup_recovery_cleanup_swallows_errors(monkeypatch):
    class FailingService:
        def __init__(self, session):
            self.session = session

        async def run_cleanup(self):
            raise RuntimeError("cleanup exploded")

    class DummySession:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    logs = []
    monkeypatch.setattr("novel_dev.api.async_session_maker", lambda: DummySession())
    monkeypatch.setattr("novel_dev.api.RecoveryCleanupService", FailingService)
    monkeypatch.setattr(
        "novel_dev.api.log_service.add_log",
        lambda *args, **kwargs: logs.append((args, kwargs)),
    )

    await run_startup_recovery_cleanup()

    assert logs
    assert logs[0][0][0] == "system"
    assert logs[0][0][1] == "RecoveryCleanup"
    assert "启动恢复清理失败" in logs[0][0][2]
    assert logs[0][1]["level"] == "error"
    assert logs[0][1]["status"] == "startup_failed"


@pytest.mark.asyncio
async def test_lifespan_schedules_recovery_cleanup_without_blocking_routes(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_cleanup():
        started.set()
        await release.wait()

    monkeypatch.setattr(api, "run_startup_recovery_cleanup", slow_cleanup)

    async def exercise_lifespan():
        async with api_app.router.lifespan_context(api_app):
            await asyncio.wait_for(started.wait(), timeout=0.1)

            transport = ASGITransport(app=api_app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/healthz")

            assert response.status_code == 200
            assert response.json() == {"ok": True}
            assert not release.is_set()
            release.set()

    await asyncio.wait_for(exercise_lifespan(), timeout=1)
