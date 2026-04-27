from datetime import datetime, timedelta, timezone

import pytest

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.db.models import NovelState
from novel_dev.repositories.generation_job_repo import GenerationJobRepository
from novel_dev.services.flow_control_service import clear_cancel_request, is_cancel_requested, request_cancel
from novel_dev.services.recovery_cleanup_service import (
    RECOVERED_LOCK_RESULT,
    RecoveryCleanupOptions,
    RecoveryCleanupService,
)


def _cleaned_job_detail(
    job_id: str,
    novel_id: str,
    previous_status: str,
    job_type: str = "chapter_auto_run",
) -> dict[str, str]:
    return {
        "job_id": job_id,
        "novel_id": novel_id,
        "job_type": job_type,
        "previous_status": previous_status,
        "reason": f"Recovered stale {previous_status} job after process interruption",
    }


def _released_lock_detail(
    novel_id: str,
    chapter_id: str | None = None,
    volume_id: str | None = None,
) -> dict[str, str | None]:
    return {
        "novel_id": novel_id,
        "chapter_id": chapter_id,
        "volume_id": volume_id,
        "reason": "Recovered stale auto_run_lock after process interruption",
    }


def _cleared_flow_stop_detail(novel_id: str) -> dict[str, str]:
    return {
        "novel_id": novel_id,
        "reason": "Cleared expired flow stop marker",
    }


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
    assert refreshed.error_message == "Recovered stale running job after process interruption"
    assert refreshed.result_payload["recovered"] is True
    assert result.cleaned_jobs == [
        _cleaned_job_detail(job_id, "novel-stale-running", "running")
    ]


@pytest.mark.asyncio
async def test_cleanup_marks_stale_queued_job_failed(async_session):
    repo = GenerationJobRepository(async_session)
    job = await repo.create("novel-stale-queued", "chapter_auto_run", {})
    old = datetime.utcnow() - timedelta(hours=1)
    job.updated_at = old
    job_id = job.id
    await async_session.commit()

    result = await RecoveryCleanupService(async_session).run_cleanup()

    refreshed = await repo.get_by_id(job_id)
    assert refreshed.status == "failed"
    assert refreshed.error_message == "Recovered stale queued job after process interruption"
    assert refreshed.result_payload["recovered"] is True
    assert result.cleaned_jobs == [
        _cleaned_job_detail(job_id, "novel-stale-queued", "queued")
    ]


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
    assert state.checkpoint_data["auto_run_last_result"] == RECOVERED_LOCK_RESULT
    assert result.released_locks == [_released_lock_detail("novel-stale-lock")]


@pytest.mark.asyncio
async def test_cleanup_releases_lock_after_recovering_stale_active_job(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel-stale-job-lock",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={
            "existing": "value",
            "auto_run_lock": {"active": True, "token": "stale-job-token"},
        },
    )
    repo = GenerationJobRepository(async_session)
    job = await repo.create("novel-stale-job-lock", "chapter_auto_run", {})
    await repo.mark_running(job.id)
    old = datetime.utcnow() - timedelta(hours=3)
    job.heartbeat_at = old
    job.updated_at = old
    job_id = job.id
    await async_session.commit()

    result = await RecoveryCleanupService(async_session).run_cleanup()

    refreshed = await repo.get_by_id(job_id)
    state = await director.resume("novel-stale-job-lock")
    assert refreshed.status == "failed"
    assert refreshed.error_message == "Recovered stale running job after process interruption"
    assert "auto_run_lock" not in state.checkpoint_data
    assert result.cleaned_jobs == [
        _cleaned_job_detail(job_id, "novel-stale-job-lock", "running")
    ]
    assert result.released_locks == [_released_lock_detail("novel-stale-job-lock")]


@pytest.mark.asyncio
async def test_cleanup_preserves_previous_auto_run_result_when_releasing_lock(async_session):
    director = NovelDirector(session=async_session)
    previous_result = {"stopped_reason": "max_chapters_reached"}
    await director.save_checkpoint(
        "novel-stale-lock-with-result",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={
            "auto_run_lock": {"active": True, "token": "old-token"},
            "auto_run_last_result": previous_result,
        },
    )
    await async_session.commit()

    await RecoveryCleanupService(async_session).run_cleanup()

    state = await director.resume("novel-stale-lock-with-result")
    assert "auto_run_lock" not in state.checkpoint_data
    assert state.checkpoint_data["auto_run_last_result"] == previous_result


@pytest.mark.asyncio
async def test_cleanup_skips_failed_lock_cleanup_and_continues_releasing_other_locks(async_session, monkeypatch):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel-lock-save-fails",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={"auto_run_lock": {"active": True, "token": "fail-token"}},
    )
    await director.save_checkpoint(
        "novel-lock-save-succeeds",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={"auto_run_lock": {"active": True, "token": "success-token"}},
    )
    await async_session.commit()
    original_save = RecoveryCleanupService._save_state_checkpoint

    async def fail_one_save(self, state, checkpoint):
        if state.novel_id == "novel-lock-save-fails":
            raise RuntimeError("checkpoint write failed")
        await original_save(self, state, checkpoint)

    monkeypatch.setattr(RecoveryCleanupService, "_save_state_checkpoint", fail_one_save)

    result = await RecoveryCleanupService(async_session).run_cleanup()

    failed_state = await director.resume("novel-lock-save-fails")
    succeeded_state = await director.resume("novel-lock-save-succeeds")
    assert failed_state.checkpoint_data["auto_run_lock"]["token"] == "fail-token"
    assert "auto_run_lock" not in succeeded_state.checkpoint_data
    assert succeeded_state.checkpoint_data["auto_run_last_result"] == RECOVERED_LOCK_RESULT
    assert result.released_locks == [_released_lock_detail("novel-lock-save-succeeds")]
    assert result.skipped == [
        {
            "novel_id": "novel-lock-save-fails",
            "reason": "cleanup_error",
            "error": "checkpoint write failed",
        }
    ]


@pytest.mark.asyncio
async def test_cleanup_continues_after_checkpoint_flush_failure(async_session, monkeypatch):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel-lock-flush-fails",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={"auto_run_lock": {"active": True, "token": "flush-fail-token"}},
    )
    await director.save_checkpoint(
        "novel-lock-after-flush-failure",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={"auto_run_lock": {"active": True, "token": "after-failure-token"}},
    )
    await async_session.commit()
    original_save = RecoveryCleanupService._save_state_checkpoint

    async def fail_one_save_with_flush(self, state, checkpoint):
        if state.novel_id == "novel-lock-flush-fails":
            self.session.expunge(state)
            self.session.add(
                NovelState(
                    novel_id=state.novel_id,
                    current_phase=state.current_phase,
                    current_volume_id=state.current_volume_id,
                    current_chapter_id=state.current_chapter_id,
                    checkpoint_data=checkpoint,
                )
            )
            await self.session.flush()
        await original_save(self, state, checkpoint)

    monkeypatch.setattr(RecoveryCleanupService, "_save_state_checkpoint", fail_one_save_with_flush)

    result = await RecoveryCleanupService(async_session).run_cleanup()

    failed_state = await director.resume("novel-lock-flush-fails")
    succeeded_state = await director.resume("novel-lock-after-flush-failure")
    assert failed_state.checkpoint_data["auto_run_lock"]["token"] == "flush-fail-token"
    assert "auto_run_lock" not in succeeded_state.checkpoint_data
    assert result.released_locks == [_released_lock_detail("novel-lock-after-flush-failure")]
    assert len(result.skipped) == 1
    assert result.skipped[0]["novel_id"] == "novel-lock-flush-fails"
    assert result.skipped[0]["reason"] == "cleanup_error"
    assert "novel_state" in result.skipped[0]["error"]


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
    assert result.cleared_flow_stops == [
        _cleared_flow_stop_detail("novel-expired-flow-stop")
    ]


@pytest.mark.asyncio
async def test_cleanup_clears_in_memory_cancel_flag_with_expired_flow_stop(async_session):
    novel_id = "novel-expired-flow-memory"
    clear_cancel_request(novel_id)
    director = NovelDirector(session=async_session)
    requested_at = (datetime.utcnow() - timedelta(hours=25)).isoformat() + "Z"
    await director.save_checkpoint(
        novel_id,
        phase=Phase.DRAFTING,
        checkpoint_data={
            "flow_control": {
                "cancel_requested": True,
                "requested_at": requested_at,
                "reason": "user_requested",
            },
        },
    )
    request_cancel(novel_id)
    assert is_cancel_requested(novel_id) is True
    await async_session.commit()

    await RecoveryCleanupService(async_session).run_cleanup()

    assert is_cancel_requested(novel_id) is False


@pytest.mark.asyncio
async def test_cleanup_keeps_recent_flow_stop(async_session):
    director = NovelDirector(session=async_session)
    requested_at = (datetime.utcnow() - timedelta(hours=1)).isoformat() + "Z"
    await director.save_checkpoint(
        "novel-recent-flow-stop",
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

    state = await director.resume("novel-recent-flow-stop")
    assert state.checkpoint_data["flow_control"]["requested_at"] == requested_at
    assert result.cleared_flow_stops == []


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
    assert result.cleared_flow_stops == [
        _cleared_flow_stop_detail("novel-expired-offset-flow-stop")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("flow_control", [
    {"cancel_requested": True, "reason": "missing_timestamp"},
    {"cancel_requested": True, "requested_at": "not-a-date", "reason": "invalid_timestamp"},
])
async def test_cleanup_clears_unvalidated_flow_stop_without_active_job(async_session, flow_control):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        f"novel-{flow_control['reason']}",
        phase=Phase.DRAFTING,
        checkpoint_data={"existing": "value", "flow_control": flow_control},
    )
    await async_session.commit()

    result = await RecoveryCleanupService(async_session).run_cleanup()

    state = await director.resume(f"novel-{flow_control['reason']}")
    assert state.checkpoint_data == {"existing": "value"}
    assert result.cleared_flow_stops == [
        _cleared_flow_stop_detail(f"novel-{flow_control['reason']}")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("flow_control", [
    {"cancel_requested": True, "reason": "missing_timestamp_active"},
    {"cancel_requested": True, "requested_at": "not-a-date", "reason": "invalid_timestamp_active"},
])
async def test_cleanup_keeps_unvalidated_flow_stop_with_active_job(async_session, flow_control):
    novel_id = f"novel-{flow_control['reason']}"
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        novel_id,
        phase=Phase.DRAFTING,
        checkpoint_data={"existing": "value", "flow_control": flow_control},
    )
    repo = GenerationJobRepository(async_session)
    await repo.create(novel_id, "chapter_auto_run", {})
    await async_session.commit()

    result = await RecoveryCleanupService(async_session).run_cleanup()

    state = await director.resume(novel_id)
    assert state.checkpoint_data["flow_control"] == flow_control
    assert result.cleared_flow_stops == []
    assert result.skipped == [{"novel_id": novel_id, "reason": "active_job_with_unvalidated_flow_stop"}]


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
    assert result.cleaned_jobs == [
        _cleaned_job_detail(job_id, "novel-dry-run", "running")
    ]
    assert result.released_locks == [_released_lock_detail("novel-dry-run")]
    assert result.cleared_flow_stops == [_cleared_flow_stop_detail("novel-dry-run")]


@pytest.mark.asyncio
async def test_cleanup_dry_run_plans_flow_stop_clear_after_stale_active_job_recovery(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel-dry-run-stale-flow",
        phase=Phase.DRAFTING,
        checkpoint_data={
            "flow_control": {
                "cancel_requested": True,
                "requested_at": "not-a-date",
                "reason": "invalid_timestamp",
            },
        },
    )
    repo = GenerationJobRepository(async_session)
    job = await repo.create("novel-dry-run-stale-flow", "chapter_auto_run", {})
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
    state = await director.resume("novel-dry-run-stale-flow")
    assert refreshed.status == "running"
    assert state.checkpoint_data["flow_control"]["cancel_requested"] is True
    assert result.cleaned_jobs == [
        _cleaned_job_detail(job_id, "novel-dry-run-stale-flow", "running")
    ]
    assert result.cleared_flow_stops == [
        _cleared_flow_stop_detail("novel-dry-run-stale-flow")
    ]
    assert result.skipped == []


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
