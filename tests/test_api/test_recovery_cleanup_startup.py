import pytest

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
