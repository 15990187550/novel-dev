from datetime import datetime, timedelta, timezone

import pytest

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.generation_job_repo import GenerationJobRepository
from novel_dev.services.recovery_cleanup_service import RecoveryCleanupOptions, RecoveryCleanupService


@pytest.mark.asyncio
async def test_cleanup_marks_stale_running_job_failed(async_session):
    repo = GenerationJobRepository(async_session)
    job = await repo.create("novel-stale-running", "chapter_auto_run", {})
    await repo.mark_running(job.id)
    old = datetime.utcnow() - timedelta(hours=3)
    job.heartbeat_at = old
    job.updated_at = old
    job_id = job.id
    await async_session.commit()

    result = await RecoveryCleanupService(async_session).run_cleanup()

    refreshed = await repo.get_by_id(job_id)
    assert refreshed.status == "failed"
    assert refreshed.result_payload["recovered"] is True
    assert result.cleaned_jobs == [job_id]


@pytest.mark.asyncio
async def test_cleanup_does_not_mark_fresh_running_job(async_session):
    repo = GenerationJobRepository(async_session)
    job = await repo.create("novel-fresh-running", "chapter_auto_run", {})
    await repo.mark_running(job.id)
    await async_session.commit()

    result = await RecoveryCleanupService(async_session).run_cleanup()

    refreshed = await repo.get_by_id(job.id)
    assert refreshed.status == "running"
    assert result.cleaned_jobs == []


@pytest.mark.asyncio
async def test_cleanup_releases_lock_without_active_job(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel-stale-lock",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={
            "existing": "value",
            "auto_run_lock": {"active": True, "token": "old-token"},
        },
    )
    await async_session.commit()

    result = await RecoveryCleanupService(async_session).run_cleanup()

    state = await director.resume("novel-stale-lock")
    assert state.checkpoint_data["existing"] == "value"
    assert "auto_run_lock" not in state.checkpoint_data
    assert state.checkpoint_data["auto_run_last_result"]["stopped_reason"] == "recovered"
    assert result.released_locks == ["novel-stale-lock"]


@pytest.mark.asyncio
async def test_cleanup_keeps_lock_with_fresh_active_job(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel-fresh-lock",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={
            "existing": "value",
            "auto_run_lock": {"active": True, "token": "fresh-token"},
        },
    )
    repo = GenerationJobRepository(async_session)
    job = await repo.create("novel-fresh-lock", "chapter_auto_run", {})
    await repo.mark_running(job.id)
    await async_session.commit()

    result = await RecoveryCleanupService(async_session).run_cleanup()

    state = await director.resume("novel-fresh-lock")
    assert state.checkpoint_data["auto_run_lock"]["token"] == "fresh-token"
    assert result.released_locks == []
    assert result.skipped == [{"novel_id": "novel-fresh-lock", "reason": "fresh_active_job"}]


@pytest.mark.asyncio
async def test_cleanup_clears_expired_flow_stop(async_session):
    director = NovelDirector(session=async_session)
    requested_at = (datetime.utcnow() - timedelta(hours=25)).isoformat() + "Z"
    await director.save_checkpoint(
        "novel-expired-flow-stop",
        phase=Phase.DRAFTING,
        checkpoint_data={
            "existing": "value",
            "flow_control": {
                "cancel_requested": True,
                "requested_at": requested_at,
                "reason": "user_requested",
            },
        },
    )
    await async_session.commit()

    result = await RecoveryCleanupService(async_session).run_cleanup()

    state = await director.resume("novel-expired-flow-stop")
    assert state.checkpoint_data == {"existing": "value"}
    assert result.cleared_flow_stops == ["novel-expired-flow-stop"]


@pytest.mark.asyncio
async def test_cleanup_clears_expired_flow_stop_with_offset_timestamp(async_session):
    director = NovelDirector(session=async_session)
    requested_at = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    await director.save_checkpoint(
        "novel-expired-offset-flow-stop",
        phase=Phase.DRAFTING,
        checkpoint_data={
            "existing": "value",
            "flow_control": {
                "cancel_requested": True,
                "requested_at": requested_at,
                "reason": "user_requested",
            },
        },
    )
    await async_session.commit()

    result = await RecoveryCleanupService(async_session).run_cleanup()

    state = await director.resume("novel-expired-offset-flow-stop")
    assert state.checkpoint_data == {"existing": "value"}
    assert result.cleared_flow_stops == ["novel-expired-offset-flow-stop"]


@pytest.mark.asyncio
async def test_cleanup_dry_run_does_not_mutate(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel-dry-run",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={
            "existing": "value",
            "auto_run_lock": {"active": True, "token": "dry-token"},
            "flow_control": {
                "cancel_requested": True,
                "requested_at": (datetime.utcnow() - timedelta(hours=25)).isoformat() + "Z",
            },
        },
    )
    repo = GenerationJobRepository(async_session)
    job = await repo.create("novel-dry-run", "chapter_auto_run", {})
    await repo.mark_running(job.id)
    old = datetime.utcnow() - timedelta(hours=3)
    job.heartbeat_at = old
    job.updated_at = old
    job_id = job.id
    await async_session.commit()

    result = await RecoveryCleanupService(async_session).run_cleanup(
        RecoveryCleanupOptions(dry_run=True)
    )

    refreshed = await repo.get_by_id(job_id)
    state = await director.resume("novel-dry-run")
    assert refreshed.status == "running"
    assert state.checkpoint_data["auto_run_lock"]["token"] == "dry-token"
    assert state.checkpoint_data["flow_control"]["cancel_requested"] is True
    assert result.cleaned_jobs == [job_id]


@pytest.mark.asyncio
async def test_cleanup_dry_run_keeps_uncommitted_caller_work(async_session):
    repo = GenerationJobRepository(async_session)
    job = await repo.create("novel-uncommitted-work", "manual_job", {})
    job_id = job.id

    await RecoveryCleanupService(async_session).run_cleanup(
        RecoveryCleanupOptions(dry_run=True)
    )
    await async_session.flush()
    await async_session.commit()

    refreshed = await repo.get_by_id(job_id)
    assert refreshed is not None
    assert refreshed.status == "queued"


@pytest.mark.asyncio
async def test_cleanup_emits_logs_only_after_commit(async_session, monkeypatch):
    repo = GenerationJobRepository(async_session)
    job = await repo.create("novel-log-order", "chapter_auto_run", {})
    await repo.mark_running(job.id)
    old = datetime.utcnow() - timedelta(hours=3)
    job.heartbeat_at = old
    job.updated_at = old
    await async_session.commit()

    commit_completed = False
    original_commit = async_session.commit
    log_calls = []

    async def tracked_commit():
        nonlocal commit_completed
        await original_commit()
        commit_completed = True

    def collect_log(*args, **kwargs):
        assert commit_completed is True
        log_calls.append((args, kwargs))

    monkeypatch.setattr(async_session, "commit", tracked_commit)
    monkeypatch.setattr(
        "novel_dev.services.recovery_cleanup_service.log_service.add_log",
        collect_log,
    )

    await RecoveryCleanupService(async_session).run_cleanup()

    assert len(log_calls) == 1
    assert log_calls[0][0][1] == "RecoveryCleanup"
    assert log_calls[0][1]["event"] == "recovery.cleanup"


@pytest.mark.asyncio
async def test_cleanup_dry_run_does_not_emit_mutation_logs(async_session, monkeypatch):
    repo = GenerationJobRepository(async_session)
    job = await repo.create("novel-dry-run-log", "chapter_auto_run", {})
    await repo.mark_running(job.id)
    old = datetime.utcnow() - timedelta(hours=3)
    job.heartbeat_at = old
    job.updated_at = old
    await async_session.commit()
    log_calls = []

    monkeypatch.setattr(
        "novel_dev.services.recovery_cleanup_service.log_service.add_log",
        lambda *args, **kwargs: log_calls.append((args, kwargs)),
    )

    await RecoveryCleanupService(async_session).run_cleanup(
        RecoveryCleanupOptions(dry_run=True)
    )

    assert log_calls == []
