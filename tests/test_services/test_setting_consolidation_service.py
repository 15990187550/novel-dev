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
