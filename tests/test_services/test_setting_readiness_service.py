import pytest

from novel_dev.repositories.setting_workbench_repo import SettingWorkbenchRepository
from novel_dev.services.setting_readiness_service import SettingReadinessService


@pytest.mark.asyncio
async def test_setting_readiness_allows_partially_approved_batch_when_changes_are_settled(async_session):
    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="n_readiness_settled",
        source_type="ai_session",
        status="partially_approved",
        summary="已处理的设定审核",
        input_snapshot={},
    )
    await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        status="approved",
        after_snapshot={"title": "设定", "content": "内容"},
    )
    await repo.add_review_change(
        batch_id=batch.id,
        target_type="conflict",
        operation="resolve",
        status="rejected",
        after_snapshot={"title": "冲突", "content": "无需采用"},
    )
    await async_session.commit()

    readiness = await SettingReadinessService(async_session).evaluate_for_outline_generation(
        "n_readiness_settled"
    )

    assert readiness.ready is True
    assert readiness.blockers == []


@pytest.mark.asyncio
async def test_setting_readiness_blocks_partially_approved_batch_with_pending_conflict(async_session):
    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="n_readiness_pending_conflict",
        source_type="ai_session",
        status="partially_approved",
        summary="仍有冲突的设定审核",
        input_snapshot={},
    )
    await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        status="approved",
        after_snapshot={"title": "设定", "content": "内容"},
    )
    await repo.add_review_change(
        batch_id=batch.id,
        target_type="conflict",
        operation="resolve",
        status="pending",
        after_snapshot={"title": "冲突", "content": "待处理"},
    )
    await async_session.commit()

    readiness = await SettingReadinessService(async_session).evaluate_for_outline_generation(
        "n_readiness_pending_conflict"
    )

    assert readiness.ready is False
    assert any("change_status=pending" in blocker for blocker in readiness.blockers)


@pytest.mark.asyncio
async def test_setting_readiness_blocks_failed_review_batch(async_session):
    repo = SettingWorkbenchRepository(async_session)
    await repo.create_review_batch(
        novel_id="n_readiness_failed_batch",
        source_type="ai_session",
        status="failed",
        summary="失败的设定审核",
        input_snapshot={},
    )
    await async_session.commit()

    readiness = await SettingReadinessService(async_session).evaluate_for_outline_generation(
        "n_readiness_failed_batch"
    )

    assert readiness.ready is False
    assert any("status=failed" in blocker for blocker in readiness.blockers)


@pytest.mark.asyncio
async def test_setting_readiness_uses_latest_consolidation_batch(async_session):
    repo = SettingWorkbenchRepository(async_session)
    older = await repo.create_review_batch(
        novel_id="n_readiness_latest_consolidation",
        source_type="consolidation",
        status="failed",
        summary="旧合并批次失败",
        input_snapshot={},
    )
    await repo.add_review_change(
        batch_id=older.id,
        target_type="synopsis",
        operation="upsert",
        status="failed",
        after_snapshot={"title": "旧失败"},
    )
    latest = await repo.create_review_batch(
        novel_id="n_readiness_latest_consolidation",
        source_type="consolidation",
        status="partially_approved",
        summary="最新合并批次已处理",
        input_snapshot={},
    )
    await repo.add_review_change(
        batch_id=latest.id,
        target_type="setting",
        operation="upsert",
        status="approved",
        after_snapshot={"title": "已采纳", "content": "内容"},
    )
    await repo.add_review_change(
        batch_id=latest.id,
        target_type="conflict",
        operation="resolve",
        status="rejected",
        after_snapshot={"title": "冲突", "content": "不采用"},
    )
    await async_session.commit()

    readiness = await SettingReadinessService(async_session).evaluate_for_outline_generation(
        "n_readiness_latest_consolidation"
    )

    assert readiness.ready is True
    assert readiness.blockers == []


@pytest.mark.asyncio
async def test_setting_readiness_still_blocks_latest_consolidation_failure(async_session):
    repo = SettingWorkbenchRepository(async_session)
    settled = await repo.create_review_batch(
        novel_id="n_readiness_latest_consolidation_failed",
        source_type="consolidation",
        status="approved",
        summary="旧合并批次成功",
        input_snapshot={},
    )
    await repo.add_review_change(
        batch_id=settled.id,
        target_type="setting",
        operation="upsert",
        status="approved",
        after_snapshot={"title": "旧成功"},
    )
    latest = await repo.create_review_batch(
        novel_id="n_readiness_latest_consolidation_failed",
        source_type="consolidation",
        status="failed",
        summary="最新合并批次失败",
        input_snapshot={},
    )
    await repo.add_review_change(
        batch_id=latest.id,
        target_type="relationship",
        operation="upsert",
        status="failed",
        after_snapshot={},
    )
    await async_session.commit()

    readiness = await SettingReadinessService(async_session).evaluate_for_outline_generation(
        "n_readiness_latest_consolidation_failed"
    )

    assert readiness.ready is False
    assert readiness.blockers == [
        f"setting_review_batch:{latest.id}:status=failed:source_type=consolidation"
    ]
