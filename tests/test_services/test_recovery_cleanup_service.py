from datetime import datetime, timedelta

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
