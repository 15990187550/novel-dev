import pytest

from novel_dev.repositories.setting_workbench_repo import SettingWorkbenchRepository

pytestmark = pytest.mark.asyncio


async def test_setting_workbench_repo_creates_session_and_messages(async_session):
    repo = SettingWorkbenchRepository(async_session)

    session = await repo.create_session(
        novel_id="novel-sw",
        title="修炼体系补全",
        target_categories=["功法", "体系设定"],
    )
    first_message = await repo.add_message(
        session_id=session.id,
        role="user",
        content="主角从废脉开始修炼",
        metadata={"round": 1},
    )
    await repo.add_message(
        session_id=session.id,
        role="user",
        content="第二轮补充宗门冲突",
        metadata={"round": 2},
    )

    await async_session.commit()

    sessions = await repo.list_sessions("novel-sw")
    messages = await repo.list_messages(session.id)

    assert sessions[0].id == session.id
    assert sessions[0].status == "clarifying"
    assert sessions[0].target_categories == ["功法", "体系设定"]
    assert messages[0].id == first_message.id
    assert [message.content for message in messages] == [
        "主角从废脉开始修炼",
        "第二轮补充宗门冲突",
    ]


async def test_setting_workbench_repo_creates_review_batch_and_changes(async_session):
    repo = SettingWorkbenchRepository(async_session)
    session = await repo.create_session(
        novel_id="novel-sw",
        title="势力格局",
        target_categories=["势力"],
    )

    batch = await repo.create_review_batch(
        novel_id="novel-sw",
        source_type="ai_session",
        source_session_id=session.id,
        summary="新增 1 张设定卡片，1 个实体，1 个关系变更",
    )
    await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        after_snapshot={"title": "势力格局", "content": "宗门互相制衡。"},
        source_session_id=session.id,
    )
    await repo.add_review_change(
        batch_id=batch.id,
        target_type="entity",
        operation="create",
        after_snapshot={"type": "faction", "name": "青云门", "state": {"description": "正道宗门"}},
        source_session_id=session.id,
    )
    await async_session.commit()

    batches = await repo.list_review_batches("novel-sw")
    changes = await repo.list_review_changes(batch.id)

    assert batches[0].id == batch.id
    assert batches[0].status == "pending"
    assert [change.target_type for change in changes] == ["setting_card", "entity"]
    assert all(change.status == "pending" for change in changes)
