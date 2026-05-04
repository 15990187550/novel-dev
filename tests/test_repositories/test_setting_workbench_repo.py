from datetime import datetime

import pytest

from novel_dev.db.models import GenerationJob, SettingReviewBatch
from novel_dev.repositories.setting_workbench_repo import SettingWorkbenchRepository


pytestmark = pytest.mark.asyncio


async def test_setting_workbench_repo_creates_session_with_initial_message(async_session):
    repo = SettingWorkbenchRepository(async_session)

    session = await repo.create_session(
        novel_id="novel-setting",
        title="修炼体系补全",
        target_categories=["功法", "体系设定"],
    )
    message = await repo.add_message(
        session_id=session.id,
        role="user",
        content="主角从废脉开始修炼",
        metadata={"kind": "initial_idea"},
    )
    await async_session.commit()

    sessions = await repo.list_sessions("novel-setting")
    messages = await repo.list_messages(session.id)

    assert sessions[0].id == session.id
    assert sessions[0].title == "修炼体系补全"
    assert sessions[0].status == "clarifying"
    assert sessions[0].target_categories == ["功法", "体系设定"]
    assert messages[0].id == message.id
    assert messages[0].content == "主角从废脉开始修炼"


async def test_setting_workbench_repo_creates_consolidation_batch_and_changes(async_session):
    repo = SettingWorkbenchRepository(async_session)
    async_session.add(
        GenerationJob(
            id="job_consolidate_1",
            novel_id="novel-setting",
            job_type="setting_consolidation",
        )
    )
    await async_session.flush()

    batch = await repo.create_review_batch(
        novel_id="novel-setting",
        source_type="consolidation",
        summary="整合 2 条设定，发现 1 个冲突",
        input_snapshot={"documents": [{"id": "doc-1", "title": "旧修炼体系"}]},
        job_id="job_consolidate_1",
    )
    await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        after_snapshot={
            "doc_type": "setting",
            "title": "修炼体系总览",
            "content": "炼气、筑基、金丹三境。",
        },
    )
    await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="archive",
        target_id="doc-1",
        before_snapshot={"title": "旧修炼体系"},
        conflict_hints=[],
    )
    await repo.add_review_change(
        batch_id=batch.id,
        target_type="conflict",
        operation="resolve",
        after_snapshot={
            "title": "境界冲突",
            "options": [
                {"key": "a", "content": "炼气九层"},
                {"key": "b", "content": "炼气十二层"},
            ],
        },
        conflict_hints=[{"reason": "同一境界层数不一致"}],
    )
    await async_session.commit()

    batches = await repo.list_review_batches("novel-setting")
    changes = await repo.list_review_changes(batch.id)

    assert batches[0].source_type == "consolidation"
    assert batches[0].status == "pending"
    assert batches[0].input_snapshot["documents"][0]["id"] == "doc-1"
    assert [change.operation for change in changes] == ["create", "archive", "resolve"]
    assert changes[2].target_type == "conflict"
    assert changes[2].status == "pending"


async def test_list_review_batches_uses_deterministic_id_tiebreaker(async_session):
    repo = SettingWorkbenchRepository(async_session)
    same_time = datetime(2026, 5, 4, 12, 0, 0)
    for batch_id in ("batch-a", "batch-c", "batch-b"):
        async_session.add(
            SettingReviewBatch(
                id=batch_id,
                novel_id="novel-order",
                source_type="consolidation",
                status="pending",
                summary=batch_id,
                input_snapshot={},
                created_at=same_time,
                updated_at=same_time,
            )
        )
    async_session.add(
        SettingReviewBatch(
            id="batch-other",
            novel_id="other-novel",
            source_type="consolidation",
            status="pending",
            summary="other",
            input_snapshot={},
            created_at=same_time,
            updated_at=same_time,
        )
    )
    await async_session.flush()

    batches = await repo.list_review_batches("novel-order")

    assert [batch.id for batch in batches] == ["batch-c", "batch-b", "batch-a"]


async def test_get_review_batch_by_job_returns_latest_deterministic_duplicate(async_session):
    repo = SettingWorkbenchRepository(async_session)
    async_session.add(
        GenerationJob(
            id="job_duplicate_batches",
            novel_id="novel-setting",
            job_type="setting_consolidation",
        )
    )
    same_time = datetime(2026, 5, 4, 13, 0, 0)
    for batch_id in ("job-batch-a", "job-batch-c", "job-batch-b"):
        async_session.add(
            SettingReviewBatch(
                id=batch_id,
                novel_id="novel-setting",
                source_type="consolidation",
                job_id="job_duplicate_batches",
                status="pending",
                summary=batch_id,
                input_snapshot={},
                created_at=same_time,
                updated_at=same_time,
            )
        )
    await async_session.flush()

    batch = await repo.get_review_batch_by_job("job_duplicate_batches")

    assert batch is not None
    assert batch.id == "job-batch-c"
    assert await repo.get_review_batch_by_job("missing-job") is None


async def test_mark_change_status_updates_fields_and_preserves_or_changes_error(async_session):
    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="novel-setting",
        source_type="consolidation",
    )
    change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        after_snapshot={"title": "old"},
    )
    change.error_message = "existing error"
    change.updated_at = datetime(2026, 1, 1, 0, 0, 0)
    await async_session.flush()
    old_updated_at = change.updated_at

    updated = await repo.mark_change_status(
        change.id,
        "approved",
        after_snapshot={"title": "new"},
    )

    assert updated is not None
    assert updated.status == "approved"
    assert updated.after_snapshot == {"title": "new"}
    assert updated.error_message == "existing error"
    assert updated.updated_at > old_updated_at

    change.updated_at = datetime(2026, 1, 1, 0, 0, 0)
    await async_session.flush()
    updated = await repo.mark_change_status(change.id, "failed", error_message="new error")

    assert updated is not None
    assert updated.status == "failed"
    assert updated.after_snapshot == {"title": "new"}
    assert updated.error_message == "new error"
    assert updated.updated_at > datetime(2026, 1, 1, 0, 0, 0)

    updated = await repo.mark_change_status(change.id, "pending", error_message=None)

    assert updated is not None
    assert updated.error_message is None
    assert await repo.mark_change_status("missing-change", "approved") is None


async def test_update_batch_status_updates_fields_and_preserves_or_changes_error(async_session):
    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="novel-setting",
        source_type="consolidation",
        summary="old summary",
    )
    batch.error_message = "existing batch error"
    batch.updated_at = datetime(2026, 1, 1, 0, 0, 0)
    await async_session.flush()
    old_updated_at = batch.updated_at

    updated = await repo.update_batch_status(batch.id, "ready", summary="new summary")

    assert updated is not None
    assert updated.status == "ready"
    assert updated.summary == "new summary"
    assert updated.error_message == "existing batch error"
    assert updated.updated_at > old_updated_at

    batch.updated_at = datetime(2026, 1, 1, 0, 0, 0)
    await async_session.flush()
    updated = await repo.update_batch_status(batch.id, "failed", error_message="new batch error")

    assert updated is not None
    assert updated.status == "failed"
    assert updated.summary == "new summary"
    assert updated.error_message == "new batch error"
    assert updated.updated_at > datetime(2026, 1, 1, 0, 0, 0)

    updated = await repo.update_batch_status(batch.id, "pending", error_message=None)

    assert updated is not None
    assert updated.error_message is None
    assert await repo.update_batch_status("missing-batch", "approved") is None
