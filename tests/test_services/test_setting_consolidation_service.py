from datetime import datetime

import pytest

from novel_dev.db.models import Entity, EntityRelationship, GenerationJob
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.pending_extraction_repo import PendingExtractionRepository
from novel_dev.repositories.setting_workbench_repo import SettingWorkbenchRepository
from novel_dev.services.setting_consolidation_service import SettingConsolidationService


pytestmark = pytest.mark.asyncio


class FakeConsolidationAgent:
    def __init__(self):
        self.snapshot = None

    async def consolidate(self, snapshot):
        self.snapshot = snapshot
        assert [doc["id"] for doc in snapshot["documents"]] == ["doc-current"]
        assert [entity["id"] for entity in snapshot["entities"]] == ["entity-active"]
        assert [relationship["source_id"] for relationship in snapshot["relationships"]] == ["entity-active"]
        assert [pending["id"] for pending in snapshot["selected_pending"]] == ["pending-selected"]
        assert "pending-unselected" not in str(snapshot)
        assert "未选择资料" not in str(snapshot)
        return {
            "summary": "生成 1 张整合设定，归档 1 条旧设定，发现 1 个冲突",
            "changes": [
                {
                    "target_type": "setting_card",
                    "operation": "create",
                    "after_snapshot": {
                        "doc_type": "setting",
                        "title": "修炼体系总览",
                        "content": "炼气、筑基、金丹。",
                    },
                },
                {
                    "target_type": "setting_card",
                    "operation": "archive",
                    "target_id": "doc-current",
                    "before_snapshot": {"title": "旧修炼体系"},
                },
                {
                    "target_type": "conflict",
                    "operation": "resolve",
                    "after_snapshot": {"title": "境界层数冲突", "options": ["九层", "十二层"]},
                    "conflict_hints": [{"reason": "炼气层数冲突"}],
                },
            ],
        }


class FailingIfCalledAgent:
    def __init__(self):
        self.called = False

    async def consolidate(self, snapshot):
        self.called = True
        raise AssertionError("agent should not be called")


class FailingConsolidationAgent:
    async def consolidate(self, snapshot):
        raise RuntimeError("model failed")


async def test_consolidation_snapshots_effective_docs_and_selected_pending(async_session):
    doc_repo = DocumentRepository(async_session)
    await doc_repo.create("doc-current", "novel-c", "setting", "旧修炼体系", "炼气九层", version=1)
    await doc_repo.create("doc-old-version", "novel-c", "setting", "旧修炼体系", "炼气八层", version=0)
    async_session.add(
        Entity(
            id="entity-active",
            novel_id="novel-c",
            type="character",
            name="陆照",
        )
    )
    async_session.add(
        Entity(
            id="entity-archived",
            novel_id="novel-c",
            type="character",
            name="旧陆照",
            archived_at=datetime.utcnow(),
        )
    )
    async_session.add(
        EntityRelationship(
            source_id="entity-active",
            target_id="entity-active",
            relation_type="自我",
            novel_id="novel-c",
        )
    )
    pending_repo = PendingExtractionRepository(async_session)
    await pending_repo.create(
        "pending-selected",
        "novel-c",
        "setting",
        {"worldview": "选中的待审核资料"},
        source_filename="selected.md",
    )
    await pending_repo.create(
        "pending-unselected",
        "novel-c",
        "setting",
        {"worldview": "未选择资料"},
        source_filename="unselected.md",
    )
    async_session.add(
        GenerationJob(
            id="job-setting-1",
            novel_id="novel-c",
            job_type="setting_consolidation",
        )
    )
    await async_session.commit()

    agent = FakeConsolidationAgent()
    service = SettingConsolidationService(async_session, agent=agent)
    batch = await service.run_consolidation(
        novel_id="novel-c",
        selected_pending_ids=["pending-selected"],
        job_id="job-setting-1",
    )
    await async_session.commit()

    review_repo = SettingWorkbenchRepository(async_session)
    changes = await review_repo.list_review_changes(batch.id)

    assert agent.snapshot is not None
    assert batch.source_type == "consolidation"
    assert batch.job_id == "job-setting-1"
    assert batch.status == "pending"
    assert batch.input_snapshot["documents"][0]["id"] == "doc-current"
    assert batch.input_snapshot["selected_pending"][0]["id"] == "pending-selected"
    assert "pending-unselected" not in str(batch.input_snapshot)
    assert [change.operation for change in changes] == ["create", "archive", "resolve"]
    assert [change.target_type for change in changes] == ["setting_card", "setting_card", "conflict"]
    assert changes[2].conflict_hints == [{"reason": "炼气层数冲突"}]


async def test_snapshot_uses_latest_non_archived_document_when_latest_is_archived(async_session):
    doc_repo = DocumentRepository(async_session)
    active = await doc_repo.create(
        "doc-active-previous",
        "novel-docs",
        "setting",
        "修炼体系",
        "炼气九层",
        version=1,
    )
    archived_latest = await doc_repo.create(
        "doc-archived-latest",
        "novel-docs",
        "setting",
        "修炼体系",
        "炼气十二层",
        version=2,
    )
    archived_latest.archived_at = datetime.utcnow()
    await async_session.commit()

    service = SettingConsolidationService(async_session, agent=FakeConsolidationAgent())
    snapshot = await service.build_input_snapshot("novel-docs", [])

    assert [doc["id"] for doc in snapshot["documents"]] == [active.id]
    assert snapshot["documents"][0]["content"] == "炼气九层"


@pytest.mark.parametrize("selected_pending_ids", [["missing-pending"], ["pending-approved"]])
async def test_invalid_selected_pending_raises_before_agent_or_review_batch(async_session, selected_pending_ids):
    pending_repo = PendingExtractionRepository(async_session)
    await pending_repo.create(
        "pending-approved",
        "novel-invalid",
        "setting",
        {"worldview": "已处理资料"},
        status="approved",
    )
    await async_session.commit()

    agent = FailingIfCalledAgent()
    service = SettingConsolidationService(async_session, agent=agent)

    with pytest.raises(ValueError):
        await service.run_consolidation(
            novel_id="novel-invalid",
            selected_pending_ids=selected_pending_ids,
        )

    review_repo = SettingWorkbenchRepository(async_session)
    assert agent.called is False
    assert await review_repo.list_review_batches("novel-invalid") == []


async def test_agent_failure_creates_no_review_batch_or_changes(async_session):
    pending_repo = PendingExtractionRepository(async_session)
    await pending_repo.create(
        "pending-selected",
        "novel-failure",
        "setting",
        {"worldview": "选中的待审核资料"},
    )
    await async_session.commit()

    service = SettingConsolidationService(async_session, agent=FailingConsolidationAgent())

    with pytest.raises(RuntimeError, match="model failed"):
        await service.run_consolidation(
            novel_id="novel-failure",
            selected_pending_ids=["pending-selected"],
        )

    review_repo = SettingWorkbenchRepository(async_session)
    batches = await review_repo.list_review_batches("novel-failure")
    assert batches == []


async def test_snapshot_ordering_is_deterministic(async_session):
    doc_repo = DocumentRepository(async_session)
    await doc_repo.create("doc-setting-b", "novel-order", "setting", "B设定", "B", version=1)
    await doc_repo.create("doc-concept-a", "novel-order", "concept", "A概念", "A", version=1)
    await doc_repo.create("doc-setting-a", "novel-order", "setting", "A设定", "A", version=1)
    async_session.add_all(
        [
            Entity(id="entity-z", novel_id="novel-order", type="place", name="紫府"),
            Entity(id="entity-a", novel_id="novel-order", type="character", name="阿照"),
            Entity(id="entity-b", novel_id="novel-order", type="character", name="白术"),
        ]
    )
    await async_session.flush()
    async_session.add_all(
        [
            EntityRelationship(
                source_id="entity-b",
                target_id="entity-z",
                relation_type="驻守",
                novel_id="novel-order",
            ),
            EntityRelationship(
                source_id="entity-a",
                target_id="entity-z",
                relation_type="到达",
                novel_id="novel-order",
            ),
            EntityRelationship(
                source_id="entity-a",
                target_id="entity-b",
                relation_type="同伴",
                novel_id="novel-order",
            ),
        ]
    )
    await async_session.commit()

    service = SettingConsolidationService(async_session, agent=FakeConsolidationAgent())
    snapshot = await service.build_input_snapshot("novel-order", [])

    assert [doc["id"] for doc in snapshot["documents"]] == [
        "doc-concept-a",
        "doc-setting-a",
        "doc-setting-b",
    ]
    assert [entity["id"] for entity in snapshot["entities"]] == [
        "entity-b",
        "entity-a",
        "entity-z",
    ]
    assert [
        (relationship["source_id"], relationship["target_id"], relationship["relation_type"])
        for relationship in snapshot["relationships"]
    ] == [
        ("entity-a", "entity-b", "同伴"),
        ("entity-a", "entity-z", "到达"),
        ("entity-b", "entity-z", "驻守"),
    ]


async def test_approve_all_blocks_unresolved_conflict_and_leaves_statuses_unchanged(async_session):
    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="novel-approve-conflict",
        source_type="consolidation",
        summary="待审核",
        input_snapshot={},
    )
    create_change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        after_snapshot={"title": "修炼体系总览"},
    )
    conflict_change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="conflict",
        operation="resolve",
        after_snapshot={"title": "境界冲突"},
        conflict_hints=[{"reason": "层数冲突"}],
    )
    await async_session.commit()

    service = SettingConsolidationService(async_session, agent=FailingIfCalledAgent())

    with pytest.raises(ValueError, match="存在未解决冲突"):
        await service.approve_review_batch(batch.id, approve_all=True)

    unchanged_batch = await repo.get_review_batch(batch.id)
    unchanged_changes = await repo.list_review_changes(batch.id)
    assert unchanged_batch.status == "pending"
    assert {change.id: change.status for change in unchanged_changes} == {
        create_change.id: "pending",
        conflict_change.id: "pending",
    }


async def test_resolve_conflict_creates_pending_setting_change(async_session):
    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="novel-resolve-conflict",
        source_type="consolidation",
        summary="待解决冲突",
        input_snapshot={},
    )
    conflict_change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="conflict",
        operation="resolve",
        after_snapshot={"title": "境界冲突"},
        conflict_hints=[{"reason": "层数冲突"}],
        source_session_id="session-1",
    )
    await async_session.commit()

    service = SettingConsolidationService(async_session, agent=FailingIfCalledAgent())
    updated_batch = await service.resolve_conflict_change(
        batch.id,
        change_id=conflict_change.id,
        resolved_after_snapshot={
            "title": "修炼体系总览",
            "content": "炼气、筑基、金丹三境统一为九层。",
        },
    )

    changes = await repo.list_review_changes(batch.id)
    conflict = next(change for change in changes if change.id == conflict_change.id)
    generated = next(change for change in changes if change.id != conflict_change.id)
    assert updated_batch.status == "ready_for_review"
    assert conflict.status == "resolved"
    assert generated.target_type == "setting_card"
    assert generated.operation == "create"
    assert generated.status == "pending"
    assert generated.after_snapshot["doc_type"] == "setting"
    assert generated.after_snapshot["title"] == "修炼体系总览"
    assert generated.conflict_hints == [{"reason": "层数冲突"}]
    assert generated.source_session_id == "session-1"


async def test_approve_archive_hides_old_document_with_consolidation_metadata(async_session):
    doc_repo = DocumentRepository(async_session)
    doc = await doc_repo.create("doc-archive", "novel-archive", "setting", "旧势力设定", "旧内容", version=1)
    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="novel-archive",
        source_type="consolidation",
        summary="归档旧设定",
        input_snapshot={},
    )
    archive_change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="archive",
        target_id=doc.id,
        before_snapshot={"title": doc.title},
    )
    await async_session.commit()

    service = SettingConsolidationService(async_session, agent=FailingIfCalledAgent())
    updated_batch = await service.approve_review_batch(batch.id, change_ids=[archive_change.id])
    archived = await doc_repo.get_by_id(doc.id)
    updated_change = await repo.get_review_change(archive_change.id)

    assert updated_batch.status == "approved"
    assert updated_change.status == "approved"
    assert archived.archived_at is not None
    assert archived.archive_reason == "setting_consolidation"
    assert archived.archived_by_consolidation_batch_id == batch.id
    assert archived.archived_by_consolidation_change_id == archive_change.id


async def test_approve_setting_card_create_writes_consolidation_source_metadata(async_session):
    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="novel-create-setting",
        source_type="consolidation",
        summary="创建设定卡",
        input_snapshot={},
    )
    create_change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        after_snapshot={"title": "修炼体系总览", "content": "炼气、筑基、金丹。"},
    )
    await async_session.commit()

    service = SettingConsolidationService(async_session, agent=FailingIfCalledAgent())
    await service.approve_review_batch(batch.id, change_ids=[create_change.id])

    created = await DocumentRepository(async_session).get_by_id(f"setting_{create_change.id}")
    updated_change = await repo.get_review_change(create_change.id)
    assert created is not None
    assert created.novel_id == "novel-create-setting"
    assert created.doc_type == "setting"
    assert created.title == "修炼体系总览"
    assert created.content == "炼气、筑基、金丹。"
    assert created.source_type == "consolidation"
    assert created.source_review_batch_id == batch.id
    assert created.source_review_change_id == create_change.id
    assert updated_change.status == "approved"


async def test_approve_review_batch_missing_batch_raises(async_session):
    service = SettingConsolidationService(async_session, agent=FailingIfCalledAgent())

    with pytest.raises(ValueError, match="审核记录不存在"):
        await service.approve_review_batch("missing-batch", approve_all=True)


async def test_approve_unsupported_change_marks_failed_and_batch_failed(async_session):
    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="novel-unsupported",
        source_type="consolidation",
        summary="不支持变更",
        input_snapshot={},
    )
    change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="rewrite",
        target_id="doc-missing",
    )
    await async_session.commit()

    service = SettingConsolidationService(async_session, agent=FailingIfCalledAgent())
    updated_batch = await service.approve_review_batch(batch.id, change_ids=[change.id])
    updated_change = await repo.get_review_change(change.id)

    assert updated_batch.status == "failed"
    assert updated_change.status == "failed"
    assert "暂不支持的设定审核变更" in updated_change.error_message


@pytest.mark.parametrize(
    ("target_type", "target_id"),
    [
        ("setting_card", "doc-foreign"),
        ("entity", "entity-foreign"),
        ("relationship", None),
    ],
)
async def test_archive_rejects_cross_novel_targets_and_leaves_foreign_target_unarchived(
    async_session,
    target_type,
    target_id,
):
    doc_repo = DocumentRepository(async_session)
    foreign_doc = await doc_repo.create(
        "doc-foreign",
        "novel-foreign",
        "setting",
        "外部设定",
        "不属于当前小说",
    )
    foreign_entity = Entity(
        id="entity-foreign",
        novel_id="novel-foreign",
        type="character",
        name="外部人物",
    )
    async_session.add(foreign_entity)
    await async_session.flush()
    foreign_relationship = EntityRelationship(
        source_id="entity-foreign",
        target_id="entity-foreign",
        relation_type="自指",
        novel_id="novel-foreign",
    )
    async_session.add(foreign_relationship)
    await async_session.flush()
    if target_type == "relationship":
        target_id = str(foreign_relationship.id)

    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="novel-owner",
        source_type="consolidation",
        summary="跨小说归档",
        input_snapshot={},
    )
    change = await repo.add_review_change(
        batch_id=batch.id,
        target_type=target_type,
        operation="archive",
        target_id=target_id,
    )
    await async_session.commit()

    service = SettingConsolidationService(async_session, agent=FailingIfCalledAgent())
    updated_batch = await service.approve_review_batch(batch.id, change_ids=[change.id])
    updated_change = await repo.get_review_change(change.id)

    assert updated_batch.status == "failed"
    assert updated_change.status == "failed"
    assert "归档目标不存在" in updated_change.error_message
    assert (await doc_repo.get_by_id(foreign_doc.id)).archived_at is None
    assert (await service.entity_repo.get_by_id(foreign_entity.id)).archived_at is None
    assert (await service.relationship_repo.get_by_id(foreign_relationship.id)).archived_at is None


async def test_selecting_conflict_change_blocks_without_marking_failed(async_session):
    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="novel-selected-conflict",
        source_type="consolidation",
        summary="待审核",
        input_snapshot={},
    )
    conflict_change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="conflict",
        operation="resolve",
        after_snapshot={"title": "冲突"},
    )
    await async_session.commit()

    service = SettingConsolidationService(async_session, agent=FailingIfCalledAgent())
    with pytest.raises(ValueError, match="存在未解决冲突"):
        await service.approve_review_batch(batch.id, change_ids=[conflict_change.id])

    unchanged_batch = await repo.get_review_batch(batch.id)
    unchanged_change = await repo.get_review_change(conflict_change.id)
    assert unchanged_batch.status == "pending"
    assert unchanged_change.status == "pending"
    assert unchanged_change.error_message is None


async def test_selective_approval_requires_change_ids(async_session):
    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="novel-empty-selection",
        source_type="consolidation",
        summary="待审核",
        input_snapshot={},
    )
    await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        after_snapshot={"title": "修炼体系"},
    )
    await async_session.commit()

    service = SettingConsolidationService(async_session, agent=FailingIfCalledAgent())
    with pytest.raises(ValueError, match="未选择审核变更"):
        await service.approve_review_batch(batch.id, change_ids=[])


async def test_selective_approval_rejects_missing_and_non_pending_change_ids(async_session):
    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="novel-invalid-selection",
        source_type="consolidation",
        summary="待审核",
        input_snapshot={},
    )
    approved_change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        after_snapshot={"title": "已通过"},
        status="approved",
    )
    await async_session.commit()

    service = SettingConsolidationService(async_session, agent=FailingIfCalledAgent())
    with pytest.raises(ValueError, match="审核变更不存在或不属于当前批次"):
        await service.approve_review_batch(batch.id, change_ids=["missing-change"])
    with pytest.raises(ValueError, match="审核变更不是 pending 状态"):
        await service.approve_review_batch(batch.id, change_ids=[approved_change.id])


async def test_create_failure_marks_change_failed_and_session_remains_usable(async_session):
    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="novel-create-failure",
        source_type="consolidation",
        summary="缺标题",
        input_snapshot={},
    )
    change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        after_snapshot={"content": "缺少标题"},
    )
    await async_session.commit()

    service = SettingConsolidationService(async_session, agent=FailingIfCalledAgent())
    updated_batch = await service.approve_review_batch(batch.id, change_ids=[change.id])
    updated_change = await repo.get_review_change(change.id)
    still_readable_batch = await repo.get_review_batch(batch.id)

    assert updated_batch.status == "failed"
    assert still_readable_batch.status == "failed"
    assert updated_change.status == "failed"
    assert "设定卡标题不能为空" in updated_change.error_message


async def test_repeated_create_approval_rejects_non_pending_change(async_session):
    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="novel-repeat-create",
        source_type="consolidation",
        summary="重复通过",
        input_snapshot={},
    )
    change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        after_snapshot={"title": "修炼体系"},
    )
    await async_session.commit()

    service = SettingConsolidationService(async_session, agent=FailingIfCalledAgent())
    await service.approve_review_batch(batch.id, change_ids=[change.id])
    with pytest.raises(ValueError, match="审核变更不是 pending 状态"):
        await service.approve_review_batch(batch.id, change_ids=[change.id])
