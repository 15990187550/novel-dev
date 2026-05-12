import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml
from pydantic import ValidationError
from sqlalchemy import select

from novel_dev.db.models import Entity, EntityRelationship, NovelDocument, SettingReviewBatch, SettingReviewChange
from novel_dev.llm.exceptions import LLMTimeoutError
from novel_dev.llm.orchestrator import OrchestratedTaskConfig
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.setting_workbench_repo import SettingWorkbenchRepository
from novel_dev.services.entity_service import EntityService
from novel_dev.services.setting_workbench_service import SettingWorkbenchService

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _disable_setting_workbench_orchestration_by_default(monkeypatch):
    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.llm_factory.resolve_orchestration_config",
        lambda agent_name, task: None,
    )


async def test_apply_review_batch_creates_ai_sourced_setting_card_and_entity(async_session):
    repo = SettingWorkbenchRepository(async_session)
    session = await repo.create_session(
        novel_id="novel-sw-service",
        title="修炼体系补全",
        target_categories=["体系设定"],
    )
    batch = await repo.create_review_batch(
        novel_id="novel-sw-service",
        source_type="ai_session",
        source_session_id=session.id,
        summary="新增设定卡和实体",
    )
    setting_change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        after_snapshot={"doc_type": "setting", "title": "修炼体系", "content": "凡、灵、玄三境。"},
        source_session_id=session.id,
    )
    entity_change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="entity",
        operation="create",
        after_snapshot={
            "type": "character",
            "name": "陆照",
            "state": {"identity": "主角"},
        },
        source_session_id=session.id,
    )

    result = await SettingWorkbenchService(async_session).apply_review_decisions(
        "novel-sw-service",
        batch.id,
        [
            {"change_id": setting_change.id, "decision": "approve"},
            {"change_id": entity_change.id, "decision": "approve"},
        ],
    )

    assert result["status"] == "approved"
    assert result["applied"] == 2

    documents = await DocumentRepository(async_session).get_by_type_and_title(
        "novel-sw-service",
        "setting",
        "修炼体系",
    )
    assert len(documents) == 1
    document = documents[0]
    assert document.content == "凡、灵、玄三境。"
    assert document.source_type == "ai"
    assert document.source_session_id == session.id
    assert document.source_review_batch_id == batch.id
    assert document.source_review_change_id == setting_change.id

    entity_result = await async_session.execute(
        select(Entity).where(
            Entity.novel_id == "novel-sw-service",
            Entity.type == "character",
            Entity.name == "陆照",
        )
    )
    entity = entity_result.scalar_one()
    assert entity.source_type == "ai"
    assert entity.source_session_id == session.id
    assert entity.source_review_batch_id == batch.id
    assert entity.source_review_change_id == entity_change.id


async def test_apply_review_batch_supports_partial_approval(async_session):
    repo = SettingWorkbenchRepository(async_session)
    session = await repo.create_session(
        novel_id="novel-sw-partial",
        title="人物补全",
        target_categories=["人物"],
    )
    batch = await repo.create_review_batch(
        novel_id="novel-sw-partial",
        source_type="ai_session",
        source_session_id=session.id,
        summary="新增两个人物",
    )
    approved_change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="entity",
        operation="create",
        after_snapshot={"type": "character", "name": "陆照", "state": {"identity": "主角"}},
        source_session_id=session.id,
    )
    rejected_change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="entity",
        operation="create",
        after_snapshot={"type": "character", "name": "误识人物", "state": {"identity": "噪声"}},
        source_session_id=session.id,
    )

    result = await SettingWorkbenchService(async_session).apply_review_decisions(
        "novel-sw-partial",
        batch.id,
        [
            {"change_id": approved_change.id, "decision": "approve"},
            {"change_id": rejected_change.id, "decision": "reject"},
        ],
    )

    assert result == {"status": "partially_approved", "applied": 1, "rejected": 1, "failed": 0}

    entities = (
        await async_session.execute(
            select(Entity).where(Entity.novel_id == "novel-sw-partial").order_by(Entity.name.asc())
        )
    ).scalars().all()
    assert [entity.name for entity in entities] == ["陆照"]
    assert (await repo.get_review_change(approved_change.id)).status == "approved"
    assert (await repo.get_review_change(rejected_change.id)).status == "rejected"
    assert (await repo.get_review_batch(batch.id)).status == "partially_approved"


async def test_apply_review_batch_updates_existing_card_with_before_after(async_session):
    repo = SettingWorkbenchRepository(async_session)
    doc_repo = DocumentRepository(async_session)
    existing = await doc_repo.create(
        doc_id="doc_power_v1",
        novel_id="novel-sw-update",
        doc_type="setting",
        title="修炼境界",
        content="三境。",
        version=1,
    )
    session = await repo.create_session(
        novel_id="novel-sw-update",
        title="修炼境界修订",
        target_categories=["体系设定"],
    )
    batch = await repo.create_review_batch(
        novel_id="novel-sw-update",
        source_type="ai_session",
        source_session_id=session.id,
        summary="修订境界设定",
    )
    change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="update",
        target_id=existing.id,
        before_snapshot={"title": "修炼境界", "content": "三境。"},
        after_snapshot={"title": "修炼境界", "content": "九境。前案。"},
        source_session_id=session.id,
    )

    result = await SettingWorkbenchService(async_session).apply_review_decisions(
        "novel-sw-update",
        batch.id,
        [
            {
                "change_id": change.id,
                "decision": "edit_approve",
                "edited_after_snapshot": {"title": "修炼境界", "content": "九境。"},
            }
        ],
    )

    assert result["status"] == "approved"
    documents = await doc_repo.get_by_type_and_title("novel-sw-update", "setting", "修炼境界")
    assert [document.version for document in documents] == [2, 1]
    assert documents[0].content == "九境。"
    assert documents[0].source_review_change_id == change.id


async def test_apply_review_batch_deactivates_relationship(async_session):
    async_session.add_all(
        [
            Entity(id="ent_source", type="character", name="陆照", novel_id="novel-sw-rel"),
            Entity(id="ent_target", type="faction", name="青云门", novel_id="novel-sw-rel"),
        ]
    )
    await async_session.flush()
    relationship = EntityRelationship(
        source_id="ent_source",
        target_id="ent_target",
        relation_type="member",
        novel_id="novel-sw-rel",
        is_active=True,
    )
    async_session.add(relationship)
    await async_session.flush()

    repo = SettingWorkbenchRepository(async_session)
    session = await repo.create_session(
        novel_id="novel-sw-rel",
        title="关系清理",
        target_categories=["关系"],
    )
    batch = await repo.create_review_batch(
        novel_id="novel-sw-rel",
        source_type="ai_session",
        source_session_id=session.id,
        summary="删除错误关系",
    )
    change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="relationship",
        operation="delete",
        target_id=str(relationship.id),
        source_session_id=session.id,
    )

    result = await SettingWorkbenchService(async_session).apply_review_decisions(
        "novel-sw-rel",
        batch.id,
        [{"change_id": change.id, "decision": "approve"}],
    )

    assert result["status"] == "approved"
    stored = await async_session.get(EntityRelationship, relationship.id)
    assert stored.is_active is False
    assert stored.source_type == "ai"
    assert stored.source_session_id == session.id
    assert stored.source_review_batch_id == batch.id
    assert stored.source_review_change_id == change.id


@pytest.mark.parametrize("target_mode", ["missing", "wrong_novel"])
async def test_apply_review_batch_relationship_delete_fails_for_missing_or_wrong_target(
    async_session,
    target_mode,
):
    relationship = None
    if target_mode == "wrong_novel":
        async_session.add_all(
            [
                Entity(id="rel_wrong_source", type="character", name="甲", novel_id="novel-other"),
                Entity(id="rel_wrong_target", type="character", name="乙", novel_id="novel-other"),
            ]
        )
        await async_session.flush()
        relationship = EntityRelationship(
            source_id="rel_wrong_source",
            target_id="rel_wrong_target",
            relation_type="ally",
            novel_id="novel-other",
            is_active=True,
        )
        async_session.add(relationship)
        await async_session.flush()

    repo = SettingWorkbenchRepository(async_session)
    session = await repo.create_session(
        novel_id="novel-sw-rel-fail",
        title="关系删除失败",
        target_categories=["关系"],
    )
    batch = await repo.create_review_batch(
        novel_id="novel-sw-rel-fail",
        source_type="ai_session",
        source_session_id=session.id,
        summary="删除不存在或跨小说关系",
    )
    target_id = str(relationship.id) if relationship is not None else "999999"
    change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="relationship",
        operation="delete",
        target_id=target_id,
        source_session_id=session.id,
    )

    result = await SettingWorkbenchService(async_session).apply_review_decisions(
        "novel-sw-rel-fail",
        batch.id,
        [{"change_id": change.id, "decision": "approve"}],
    )

    assert result == {"status": "failed", "applied": 0, "rejected": 0, "failed": 1}
    assert (await repo.get_review_change(change.id)).status == "failed"
    if relationship is not None:
        stored = await async_session.get(EntityRelationship, relationship.id)
        assert stored.is_active is True
        assert stored.source_type is None


async def test_apply_review_batch_setting_card_create_forces_version_one(async_session):
    repo = SettingWorkbenchRepository(async_session)
    session = await repo.create_session(
        novel_id="novel-sw-version",
        title="设定版本",
        target_categories=["体系设定"],
    )
    batch = await repo.create_review_batch(
        novel_id="novel-sw-version",
        source_type="ai_session",
        source_session_id=session.id,
        summary="新增带版本号的设定卡",
    )
    change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        after_snapshot={"title": "境界", "content": "九境。", "version": 9},
        source_session_id=session.id,
    )

    result = await SettingWorkbenchService(async_session).apply_review_decisions(
        "novel-sw-version",
        batch.id,
        [{"change_id": change.id, "decision": "approve"}],
    )

    assert result["status"] == "approved"
    documents = await DocumentRepository(async_session).get_by_type_and_title(
        "novel-sw-version",
        "setting",
        "境界",
    )
    assert documents[0].version == 1


async def test_apply_review_batch_marks_change_failed_after_flush_error(async_session):
    async_session.add(
        NovelDocument(
            id="doc_duplicate",
            novel_id="novel-sw-failure",
            doc_type="setting",
            title="既有设定",
            content="旧内容",
            version=1,
        )
    )
    await async_session.flush()

    repo = SettingWorkbenchRepository(async_session)
    session = await repo.create_session(
        novel_id="novel-sw-failure",
        title="冲突设定",
        target_categories=["体系设定"],
    )
    batch = await repo.create_review_batch(
        novel_id="novel-sw-failure",
        source_type="ai_session",
        source_session_id=session.id,
        summary="新增会触发 flush 失败的设定卡",
    )
    change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        after_snapshot={"id": "doc_duplicate", "title": "重复设定", "content": "新内容"},
        source_session_id=session.id,
    )

    result = await SettingWorkbenchService(async_session).apply_review_decisions(
        "novel-sw-failure",
        batch.id,
        [{"change_id": change.id, "decision": "approve"}],
    )

    stored_change = await repo.get_review_change(change.id)
    stored_batch = await repo.get_review_batch(batch.id)
    assert result == {"status": "failed", "applied": 0, "rejected": 0, "failed": 1}
    assert stored_change.status == "failed"
    assert stored_change.error_message
    assert stored_batch.status == "failed"


async def test_apply_review_batch_entity_delete_fails_for_wrong_novel_target(async_session):
    entity_service = EntityService(async_session)
    other_entity = await entity_service.create_entity(
        "ent_wrong_novel_delete",
        "character",
        "误删对象",
        novel_id="novel-other-entity",
        initial_state={"identity": "其他小说人物"},
    )
    repo = SettingWorkbenchRepository(async_session)
    session = await repo.create_session(
        novel_id="novel-sw-entity-delete",
        title="实体删除失败",
        target_categories=["人物"],
    )
    batch = await repo.create_review_batch(
        novel_id="novel-sw-entity-delete",
        source_type="ai_session",
        source_session_id=session.id,
        summary="跨小说实体删除",
    )
    change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="entity",
        operation="delete",
        target_id=other_entity.id,
        source_session_id=session.id,
    )

    result = await SettingWorkbenchService(async_session).apply_review_decisions(
        "novel-sw-entity-delete",
        batch.id,
        [{"change_id": change.id, "decision": "approve"}],
    )

    latest_state = await entity_service.get_latest_state(other_entity.id)
    stored_entity = await async_session.get(Entity, other_entity.id)
    assert result == {"status": "failed", "applied": 0, "rejected": 0, "failed": 1}
    assert (await repo.get_review_change(change.id)).status == "failed"
    assert latest_state.get("_archived") is not True
    assert stored_entity.source_type is None


async def test_apply_review_batch_entity_update_renames_target_entity(async_session):
    entity_service = EntityService(async_session)
    entity = await entity_service.create_entity(
        "ent_update_target",
        "character",
        "旧名",
        novel_id="novel-sw-entity-update",
        initial_state={"identity": "旧身份"},
    )
    repo = SettingWorkbenchRepository(async_session)
    session = await repo.create_session(
        novel_id="novel-sw-entity-update",
        title="实体更新",
        target_categories=["人物"],
    )
    batch = await repo.create_review_batch(
        novel_id="novel-sw-entity-update",
        source_type="ai_session",
        source_session_id=session.id,
        summary="重命名实体",
    )
    change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="entity",
        operation="update",
        target_id=entity.id,
        after_snapshot={"type": "character", "name": "新名", "state": {"identity": "新身份"}},
        source_session_id=session.id,
    )

    result = await SettingWorkbenchService(async_session).apply_review_decisions(
        "novel-sw-entity-update",
        batch.id,
        [{"change_id": change.id, "decision": "approve"}],
    )

    stored_entity = await async_session.get(Entity, entity.id)
    latest_state = await entity_service.get_latest_state(entity.id)
    entity_count = (
        await async_session.execute(select(Entity).where(Entity.novel_id == "novel-sw-entity-update"))
    ).scalars().all()
    assert result["status"] == "approved"
    assert stored_entity.name == "新名"
    assert latest_state["name"] == "新名"
    assert latest_state["identity"] == "新身份"
    assert stored_entity.source_type == "ai"
    assert stored_entity.source_session_id == session.id
    assert stored_entity.source_review_batch_id == batch.id
    assert stored_entity.source_review_change_id == change.id
    assert len(entity_count) == 1


async def test_apply_review_batch_relationship_update_mutates_target_relationship(async_session):
    async_session.add_all(
        [
            Entity(id="rel_update_source", type="character", name="师父", novel_id="novel-sw-rel-update"),
            Entity(id="rel_update_target", type="character", name="徒弟", novel_id="novel-sw-rel-update"),
        ]
    )
    await async_session.flush()
    relationship = EntityRelationship(
        source_id="rel_update_source",
        target_id="rel_update_target",
        relation_type="ally",
        meta={"note": "old"},
        novel_id="novel-sw-rel-update",
        is_active=True,
    )
    async_session.add(relationship)
    await async_session.flush()

    repo = SettingWorkbenchRepository(async_session)
    session = await repo.create_session(
        novel_id="novel-sw-rel-update",
        title="关系更新",
        target_categories=["关系"],
    )
    batch = await repo.create_review_batch(
        novel_id="novel-sw-rel-update",
        source_type="ai_session",
        source_session_id=session.id,
        summary="修改关系类型",
    )
    change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="relationship",
        operation="update",
        target_id=str(relationship.id),
        after_snapshot={"relation_type": "mentor", "meta": {"note": "updated"}},
        source_session_id=session.id,
    )

    result = await SettingWorkbenchService(async_session).apply_review_decisions(
        "novel-sw-rel-update",
        batch.id,
        [{"change_id": change.id, "decision": "approve"}],
    )

    relationships = (
        await async_session.execute(
            select(EntityRelationship).where(EntityRelationship.novel_id == "novel-sw-rel-update")
        )
    ).scalars().all()
    stored = await async_session.get(EntityRelationship, relationship.id)
    assert result["status"] == "approved"
    assert len(relationships) == 1
    assert stored.relation_type == "mentor"
    assert stored.meta == {"note": "updated", "source": "setting_workbench"}
    assert stored.source_type == "ai"
    assert stored.source_session_id == session.id
    assert stored.source_review_batch_id == batch.id
    assert stored.source_review_change_id == change.id


async def test_apply_review_batch_setting_card_update_ignores_snapshot_id(async_session):
    repo = SettingWorkbenchRepository(async_session)
    doc_repo = DocumentRepository(async_session)
    existing = await doc_repo.create(
        doc_id="doc_snapshot_id_v1",
        novel_id="novel-sw-doc-update-id",
        doc_type="setting",
        title="境界",
        content="三境。",
        version=1,
    )
    session = await repo.create_session(
        novel_id="novel-sw-doc-update-id",
        title="设定更新忽略快照 id",
        target_categories=["体系设定"],
    )
    batch = await repo.create_review_batch(
        novel_id="novel-sw-doc-update-id",
        source_type="ai_session",
        source_session_id=session.id,
        summary="更新设定",
    )
    change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="update",
        target_id=existing.id,
        after_snapshot={"id": existing.id, "title": "境界", "content": "九境。"},
        source_session_id=session.id,
    )

    result = await SettingWorkbenchService(async_session).apply_review_decisions(
        "novel-sw-doc-update-id",
        batch.id,
        [{"change_id": change.id, "decision": "approve"}],
    )

    documents = await doc_repo.get_by_type_and_title("novel-sw-doc-update-id", "setting", "境界")
    assert result["status"] == "approved"
    assert [document.version for document in documents] == [2, 1]
    assert documents[0].id != existing.id
    assert documents[0].source_type == "ai"
    assert documents[0].source_session_id == session.id
    assert documents[0].source_review_batch_id == batch.id
    assert documents[0].source_review_change_id == change.id


async def test_apply_review_batch_entity_update_without_target_id_fails(async_session):
    repo = SettingWorkbenchRepository(async_session)
    session = await repo.create_session(
        novel_id="novel-sw-entity-update-missing-target",
        title="实体更新缺目标",
        target_categories=["人物"],
    )
    batch = await repo.create_review_batch(
        novel_id="novel-sw-entity-update-missing-target",
        source_type="ai_session",
        source_session_id=session.id,
        summary="缺少目标实体的更新",
    )
    change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="entity",
        operation="update",
        after_snapshot={"type": "character", "name": "不应创建", "state": {"identity": "噪声"}},
        source_session_id=session.id,
    )

    result = await SettingWorkbenchService(async_session).apply_review_decisions(
        "novel-sw-entity-update-missing-target",
        batch.id,
        [{"change_id": change.id, "decision": "approve"}],
    )

    entities = (
        await async_session.execute(
            select(Entity).where(Entity.novel_id == "novel-sw-entity-update-missing-target")
        )
    ).scalars().all()
    assert result == {"status": "failed", "applied": 0, "rejected": 0, "failed": 1}
    assert (await repo.get_review_change(change.id)).status == "failed"
    assert entities == []


async def test_apply_review_batch_relationship_update_without_target_id_fails(async_session):
    async_session.add_all(
        [
            Entity(
                id="rel_missing_update_source",
                type="character",
                name="甲",
                novel_id="novel-sw-rel-update-missing-target",
            ),
            Entity(
                id="rel_missing_update_target",
                type="character",
                name="乙",
                novel_id="novel-sw-rel-update-missing-target",
            ),
        ]
    )
    await async_session.flush()
    repo = SettingWorkbenchRepository(async_session)
    session = await repo.create_session(
        novel_id="novel-sw-rel-update-missing-target",
        title="关系更新缺目标",
        target_categories=["关系"],
    )
    batch = await repo.create_review_batch(
        novel_id="novel-sw-rel-update-missing-target",
        source_type="ai_session",
        source_session_id=session.id,
        summary="缺少目标关系的更新",
    )
    change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="relationship",
        operation="update",
        after_snapshot={
            "source_id": "rel_missing_update_source",
            "target_id": "rel_missing_update_target",
            "relation_type": "ally",
        },
        source_session_id=session.id,
    )

    result = await SettingWorkbenchService(async_session).apply_review_decisions(
        "novel-sw-rel-update-missing-target",
        batch.id,
        [{"change_id": change.id, "decision": "approve"}],
    )

    relationships = (
        await async_session.execute(
            select(EntityRelationship).where(
                EntityRelationship.novel_id == "novel-sw-rel-update-missing-target"
            )
        )
    ).scalars().all()
    assert result == {"status": "failed", "applied": 0, "rejected": 0, "failed": 1}
    assert (await repo.get_review_change(change.id)).status == "failed"
    assert relationships == []


async def test_reply_to_session_stores_clarification_question(async_session, monkeypatch):
    service = SettingWorkbenchService(async_session)
    session = await service.create_generation_session(
        novel_id="novel-ai",
        title="修炼体系补全",
        initial_idea="主角废脉开局",
        target_categories=["功法"],
    )

    async def fake_call_and_parse_model(
        agent_name,
        task,
        prompt,
        model_cls,
        *,
        config_agent_name=None,
        novel_id="",
        max_retries=3,
    ):
        from novel_dev.agents.setting_workbench_agent import SettingClarificationDecision

        assert agent_name == "SettingWorkbenchService"
        assert task == "setting_workbench_clarify"
        assert "想要玄幻升级流" in prompt
        assert model_cls is SettingClarificationDecision
        assert config_agent_name == "setting_workbench_service"
        assert novel_id == "novel-ai"
        assert max_retries == 2
        return SettingClarificationDecision(
            status="needs_clarification",
            assistant_message="请补充世界层级。",
            questions=["世界最高战力到什么层次？"],
            target_categories=["功法"],
            conversation_summary="用户想写废脉开局。",
        )

    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.call_and_parse_model",
        fake_call_and_parse_model,
    )

    result = await service.reply_to_session(
        novel_id="novel-ai",
        session_id=session.id,
        content="想要玄幻升级流",
    )

    assert result["session"].status == "clarifying"
    assert result["assistant_message"] == "请补充世界层级。"
    assert result["questions"] == ["世界最高战力到什么层次？"]
    messages = await service.repo.list_messages(session.id)
    assert [(message.role, message.content) for message in messages] == [
        ("user", "主角废脉开局"),
        ("user", "想要玄幻升级流"),
        ("assistant", "请补充世界层级。"),
    ]


async def test_reply_to_session_ready_decision_moves_session_to_ready_to_generate(async_session, monkeypatch):
    service = SettingWorkbenchService(async_session)
    session = await service.create_generation_session(
        novel_id="novel-ai-ready",
        title="体系补全",
        initial_idea="九境体系",
        target_categories=["体系"],
    )

    async def fake_call_and_parse_model(
        agent_name,
        task,
        prompt,
        model_cls,
        *,
        config_agent_name=None,
        novel_id="",
        max_retries=3,
    ):
        from novel_dev.agents.setting_workbench_agent import SettingClarificationDecision

        assert agent_name == "SettingWorkbenchService"
        assert task == "setting_workbench_clarify"
        assert model_cls is SettingClarificationDecision
        assert config_agent_name == "setting_workbench_service"
        assert novel_id == "novel-ai-ready"
        assert max_retries == 2
        return SettingClarificationDecision(
            status="ready",
            assistant_message="信息足够，可以生成。",
            questions=[],
            target_categories=["体系"],
            conversation_summary="用户给出了九境体系。",
        )

    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.call_and_parse_model",
        fake_call_and_parse_model,
    )

    result = await service.reply_to_session(
        novel_id="novel-ai-ready",
        session_id=session.id,
        content="补充宗门等级",
    )

    assert result["session"].status == "ready_to_generate"
    assert result["session"].clarification_round == 1


async def test_reply_to_session_includes_existing_setting_context(async_session, monkeypatch):
    service = SettingWorkbenchService(async_session)
    await DocumentRepository(async_session).create(
        "doc_clarify_world",
        "novel-ai-clarify-context",
        "worldview",
        "世界观",
        "北境由雪庭统治。",
    )
    entity_service = EntityService(async_session)
    entity_service._refresh_entity_artifacts = AsyncMock()
    await entity_service.create_entity(
        "ent_clarify_snow",
        "faction",
        "雪庭",
        novel_id="novel-ai-clarify-context",
        initial_state={"description": "北境势力"},
    )
    session = await service.create_generation_session(
        novel_id="novel-ai-clarify-context",
        title="补充北境人物",
        initial_idea="想补一个北境人物",
        target_categories=["人物"],
    )

    async def fake_call_and_parse_model(
        agent_name,
        task,
        prompt,
        model_cls,
        *,
        config_agent_name=None,
        novel_id="",
        max_retries=3,
    ):
        from novel_dev.agents.setting_workbench_agent import SettingClarificationDecision

        assert task == "setting_workbench_clarify"
        assert "当前已生效设定上下文" in prompt
        assert "北境由雪庭统治" in prompt
        assert "ent_clarify_snow" in prompt
        return SettingClarificationDecision(
            status="needs_clarification",
            assistant_message="这个人物与雪庭是什么关系？",
            questions=["这个人物与雪庭是什么关系？"],
            target_categories=["人物"],
            conversation_summary="北境人物待补充。",
        )

    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.call_and_parse_model",
        fake_call_and_parse_model,
    )

    result = await service.reply_to_session(
        novel_id="novel-ai-clarify-context",
        session_id=session.id,
        content="他来自北境",
    )

    assert result["questions"] == ["这个人物与雪庭是什么关系？"]


async def test_reply_to_session_fifth_clarification_round_becomes_ready_even_if_more_questions(
    async_session,
    monkeypatch,
):
    service = SettingWorkbenchService(async_session)
    session = await service.create_generation_session(
        novel_id="novel-ai-round-limit",
        title="多轮澄清",
        initial_idea="先问问题",
        target_categories=["势力"],
    )
    await service.repo.update_session_state(session.id, status="clarifying", clarification_round=4)

    async def fake_call_and_parse_model(
        agent_name,
        task,
        prompt,
        model_cls,
        *,
        config_agent_name=None,
        novel_id="",
        max_retries=3,
    ):
        from novel_dev.agents.setting_workbench_agent import SettingClarificationDecision

        assert agent_name == "SettingWorkbenchService"
        assert task == "setting_workbench_clarify"
        assert model_cls is SettingClarificationDecision
        assert config_agent_name == "setting_workbench_service"
        assert novel_id == "novel-ai-round-limit"
        assert max_retries == 2
        return SettingClarificationDecision(
            status="needs_clarification",
            assistant_message="还想追问，但轮次已满。",
            questions=["还需要什么势力？"],
            target_categories=["势力"],
            conversation_summary="已有 5 轮澄清。",
        )

    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.call_and_parse_model",
        fake_call_and_parse_model,
    )

    result = await service.reply_to_session(
        novel_id="novel-ai-round-limit",
        session_id=session.id,
        content="第五轮补充",
    )

    assert result["session"].status == "ready_to_generate"
    assert result["session"].clarification_round == 5


async def test_generate_review_batch_creates_changes_from_agent(async_session, monkeypatch):
    service = SettingWorkbenchService(async_session)
    session = await service.create_generation_session(
        novel_id="novel-ai-gen",
        title="势力格局",
        initial_idea="宗门对立",
        target_categories=["势力"],
    )
    await service.repo.update_session_state(session.id, status="ready_to_generate")

    async def fake_call_and_parse_model(
        agent_name,
        task,
        prompt,
        model_cls,
        *,
        config_agent_name=None,
        novel_id="",
        max_retries=3,
    ):
        from novel_dev.agents.setting_workbench_agent import SettingBatchDraft

        assert agent_name == "SettingWorkbenchService"
        assert task == "setting_workbench_generate_batch"
        assert "宗门对立" in prompt
        assert model_cls is SettingBatchDraft
        assert config_agent_name == "setting_workbench_service"
        assert novel_id == "novel-ai-gen"
        assert max_retries == 2
        return SettingBatchDraft.model_validate(
            {
                "summary": "新增 1 张设定卡片，1 个实体",
                "changes": [
                    {
                        "target_type": "setting_card",
                        "operation": "create",
                        "after_snapshot": {
                            "doc_type": "setting",
                            "title": "势力格局",
                            "content": "青云门与魔宗对立。",
                        },
                    },
                    {
                        "target_type": "entity",
                        "operation": "create",
                        "after_snapshot": {
                            "type": "faction",
                            "name": "青云门",
                            "state": {"description": "正道宗门"},
                        },
                    },
                ],
            }
        )

    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.call_and_parse_model",
        fake_call_and_parse_model,
    )

    batch = await service.generate_review_batch(novel_id="novel-ai-gen", session_id=session.id)
    changes = await service.repo.list_review_changes(batch.id)

    assert batch.summary == "新增 1 张设定卡片，1 个实体"
    assert [change.target_type for change in changes] == ["setting_card", "entity"]
    assert [change.status for change in changes] == ["pending", "pending"]
    assert (await service.repo.get_session(session.id)).status == "generated"


async def test_generate_review_batch_rejects_missing_output_for_individual_suggested_batch(
    async_session,
    monkeypatch,
):
    service = SettingWorkbenchService(async_session)
    for domain in ("阳神", "完美世界", "吞噬星空"):
        await service.doc_repo.create(
            f"doc_required_{domain}",
            "novel-ai-required-sections",
            "domain_setting",
            f"{domain} / 修炼体系",
            f"{domain} 修炼境界资料。",
        )
    session = await service.create_generation_session(
        novel_id="novel-ai-required-sections",
        title="外部宇宙规划",
        initial_idea="规划外部宇宙联动。",
        target_categories=["世界观"],
    )
    await service.repo.add_message(
        session_id=session.id,
        role="assistant",
        content=(
            "已确认所有关键参数。\n\n"
            "**建议生成批次：**\n"
            "- 批次1：18卷整体结构规划（含真实界+外部宇宙穿插叙事）\n"
            "- 批次2：外部宇宙统一对标体系（含阳神、完美世界、吞噬星空等境界映射）\n"
            "- 批次3：跨作品联动剧情框架与关键节点设计\n"
        ),
    )
    await service.repo.update_session_state(session.id, status="ready_to_generate")

    async def fake_call_and_parse_model(
        agent_name,
        task,
        prompt,
        model_cls,
        *,
        config_agent_name=None,
        novel_id="",
        max_retries=3,
    ):
        from novel_dev.agents.setting_workbench_agent import SettingBatchDraft

        assert agent_name == "SettingWorkbenchService"
        assert task == "setting_workbench_generate_batch"
        assert "必须完整生成以下建议批次" in prompt
        assert "批次1：18卷整体结构规划" in prompt
        assert "批次2：外部宇宙统一对标体系" not in prompt
        assert "批次3：跨作品联动剧情框架与关键节点设计" not in prompt
        assert model_cls is SettingBatchDraft
        assert config_agent_name == "setting_workbench_service"
        assert novel_id == "novel-ai-required-sections"
        assert max_retries == 2
        return SettingBatchDraft.model_validate(
            {
                "summary": "无关设定",
                "changes": [
                    {
                        "target_type": "setting_card",
                        "operation": "create",
                        "after_snapshot": {
                            "doc_type": "setting",
                            "title": "无关设定",
                            "content": "没有覆盖当前建议批次。",
                        },
                    }
                ],
            }
        )

    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.call_and_parse_model",
        fake_call_and_parse_model,
    )

    with pytest.raises(ValueError, match="Missing required suggested batches.*批次1"):
        await service.generate_review_batch(novel_id="novel-ai-required-sections", session_id=session.id)

    assert (await service.repo.get_session(session.id)).status == "ready_to_generate"
    batches = (
        await async_session.execute(
            select(SettingReviewBatch).where(SettingReviewBatch.novel_id == "novel-ai-required-sections")
        )
    ).scalars().all()
    changes = (await async_session.execute(select(SettingReviewChange))).scalars().all()
    assert batches == []
    assert changes == []


async def test_generate_review_batch_repairs_missing_output_for_individual_suggested_batch(
    async_session,
    monkeypatch,
):
    service = SettingWorkbenchService(async_session)
    for domain in ("阳神", "完美世界", "吞噬星空"):
        await service.doc_repo.create(
            f"doc_repair_{domain}",
            "novel-ai-required-repair",
            "domain_setting",
            f"{domain} / 修炼体系",
            f"{domain} 修炼境界资料。",
        )
    session = await service.create_generation_session(
        novel_id="novel-ai-required-repair",
        title="外部宇宙规划",
        initial_idea="规划外部宇宙联动。",
        target_categories=["世界观"],
    )
    await service.repo.add_message(
        session_id=session.id,
        role="assistant",
        content=(
            "已确认所有关键参数。\n\n"
            "**建议生成批次：**\n"
            "- 批次1：18卷整体结构规划（含真实界+外部宇宙穿插叙事）\n"
            "- 批次2：外部宇宙统一对标体系（含阳神、完美世界、吞噬星空等境界映射）\n"
            "- 批次3：跨作品联动剧情框架与关键节点设计\n"
        ),
    )
    await service.repo.update_session_state(session.id, status="ready_to_generate")

    prompts: list[str] = []

    async def fake_call_and_parse_model(
        agent_name,
        task,
        prompt,
        model_cls,
        *,
        config_agent_name=None,
        novel_id="",
        max_retries=3,
    ):
        from novel_dev.agents.setting_workbench_agent import SettingBatchDraft

        prompts.append(prompt)
        if "批次2：外部宇宙统一对标体系" in prompt and "上一次输出缺少以下建议批次" not in prompt:
            return SettingBatchDraft.model_validate(
                {
                    "summary": "无关设定",
                    "changes": [
                        {
                            "target_type": "setting_card",
                            "operation": "create",
                            "after_snapshot": {
                                "doc_type": "setting",
                                "title": "无关设定",
                                "content": "没有覆盖第二批。",
                            },
                        }
                    ],
                }
            )

        if "上一次输出缺少以下建议批次" in prompt:
            assert "批次2：外部宇宙统一对标体系" in prompt
            assert "批次1：18卷整体结构规划" not in prompt
            assert "批次3：跨作品联动剧情框架与关键节点设计" not in prompt
            title = "外部宇宙统一对标体系"
            summary = "补全外部宇宙统一对标体系"
        elif "批次1：18卷整体结构规划" in prompt:
            title = "18卷整体结构规划"
            summary = title
        elif "批次3：跨作品联动剧情框架与关键节点设计" in prompt:
            title = "跨作品联动剧情框架与关键节点设计"
            summary = title
        else:
            raise AssertionError("prompt should target one suggested batch")

        return SettingBatchDraft.model_validate(
            {
                "summary": summary,
                "changes": [
                    {
                        "target_type": "setting_card",
                        "operation": "create",
                        "after_snapshot": {
                            "doc_type": "setting",
                            "title": title,
                            "content": f"{title}完整内容。",
                        },
                    }
                ],
            }
        )

    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.call_and_parse_model",
        fake_call_and_parse_model,
    )

    batch = await service.generate_review_batch(novel_id="novel-ai-required-repair", session_id=session.id)

    assert batch.summary == "18卷整体结构规划；补全外部宇宙统一对标体系；跨作品联动剧情框架与关键节点设计"
    assert len(prompts) == 4
    changes = await service.repo.list_review_changes(batch.id)
    assert [change.after_snapshot["title"] for change in changes] == [
        "18卷整体结构规划",
        "外部宇宙统一对标体系",
        "跨作品联动剧情框架与关键节点设计",
    ]


async def test_generate_review_batch_generates_suggested_batches_individually(async_session, monkeypatch):
    service = SettingWorkbenchService(async_session)
    for domain in ("阳神", "完美世界", "吞噬星空"):
        await service.doc_repo.create(
            f"doc_split_{domain}",
            "novel-ai-required-split",
            "domain_setting",
            f"{domain} / 修炼体系",
            f"{domain} 修炼境界资料。",
        )
    session = await service.create_generation_session(
        novel_id="novel-ai-required-split",
        title="外部宇宙规划",
        initial_idea="规划外部宇宙联动。",
        target_categories=["世界观"],
    )
    await service.repo.add_message(
        session_id=session.id,
        role="assistant",
        content=(
            "**建议生成批次：**\n"
            "- 批次1：18卷整体结构规划（含真实界+外部宇宙穿插叙事）\n"
            "- 批次2：外部宇宙统一对标体系（含阳神、完美世界、吞噬星空等境界映射）\n"
            "- 批次3：跨作品联动剧情框架与关键节点设计\n"
        ),
    )
    await service.repo.update_session_state(session.id, status="ready_to_generate")

    prompts: list[str] = []

    async def fake_call_and_parse_model(
        agent_name,
        task,
        prompt,
        model_cls,
        *,
        config_agent_name=None,
        novel_id="",
        max_retries=3,
    ):
        from novel_dev.agents.setting_workbench_agent import SettingBatchDraft

        prompts.append(prompt)
        section_titles = [
            "18卷整体结构规划",
            "外部宇宙统一对标体系",
            "跨作品联动剧情框架与关键节点设计",
        ]
        title = section_titles[len(prompts) - 1]
        assert title in prompt
        for other_title in section_titles:
            if other_title != title:
                assert f"：{other_title}" not in prompt
        return SettingBatchDraft.model_validate(
            {
                "summary": title,
                "changes": [
                    {
                        "target_type": "setting_card",
                        "operation": "create",
                        "after_snapshot": {
                            "doc_type": "setting",
                            "title": title,
                            "content": f"{title}内容。",
                        },
                    }
                ],
            }
        )

    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.call_and_parse_model",
        fake_call_and_parse_model,
    )

    batch = await service.generate_review_batch(novel_id="novel-ai-required-split", session_id=session.id)

    assert len(prompts) == 3
    assert batch.summary == "18卷整体结构规划；外部宇宙统一对标体系；跨作品联动剧情框架与关键节点设计"
    changes = await service.repo.list_review_changes(batch.id)
    assert [change.after_snapshot["title"] for change in changes] == [
        "18卷整体结构规划",
        "外部宇宙统一对标体系",
        "跨作品联动剧情框架与关键节点设计",
    ]


async def test_generate_review_batch_fills_source_docs_before_section_validation(async_session, monkeypatch):
    service = SettingWorkbenchService(async_session)
    for domain in ("阳神", "完美世界", "吞噬星空"):
        await service.doc_repo.create(
            f"doc_section_source_{domain}",
            "novel-ai-section-source-fill",
            "domain_setting",
            f"{domain} / 修炼体系",
            f"{domain} 修炼境界资料。",
        )
    session = await service.create_generation_session(
        novel_id="novel-ai-section-source-fill",
        title="外部宇宙规划",
        initial_idea="规划外部宇宙联动。",
        target_categories=["世界观"],
    )
    await service.repo.add_message(
        session_id=session.id,
        role="assistant",
        content=(
            "**建议生成批次：**\n"
            "- 批次1：18卷整体结构规划（含真实界+外部宇宙穿插叙事）\n"
            "- 批次2：外部宇宙统一对标体系（含阳神、完美世界、吞噬星空等境界映射）\n"
            "- 批次3：跨作品联动剧情框架与关键节点设计\n"
        ),
    )
    await service.repo.update_session_state(session.id, status="ready_to_generate")

    async def fake_call_and_parse_model(
        agent_name,
        task,
        prompt,
        model_cls,
        *,
        config_agent_name=None,
        novel_id="",
        max_retries=3,
    ):
        from novel_dev.agents.setting_workbench_agent import SettingBatchDraft

        if "批次1：18卷整体结构规划" in prompt:
            title = "18卷整体结构规划"
            content = "阳神、完美世界、吞噬星空作为外部宇宙参与跨作品联动，并纳入境界对标。"
        elif "批次2：外部宇宙统一对标体系" in prompt:
            title = "外部宇宙统一对标体系"
            content = "阳神、完美世界、吞噬星空的境界映射作为待审核对标体系。"
        else:
            title = "跨作品联动剧情框架与关键节点设计"
            content = "阳神、完美世界、吞噬星空在后期形成跨作品联动节点。"
        return SettingBatchDraft.model_validate(
            {
                "summary": title,
                "changes": [
                    {
                        "target_type": "setting_card",
                        "operation": "create",
                        "after_snapshot": {
                            "doc_type": "plot",
                            "title": title,
                            "content": content,
                        },
                    }
                ],
            }
        )

    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.call_and_parse_model",
        fake_call_and_parse_model,
    )

    batch = await service.generate_review_batch(
        novel_id="novel-ai-section-source-fill",
        session_id=session.id,
    )

    changes = await service.repo.list_review_changes(batch.id)
    assert len(changes) == 3
    for change in changes:
        assert set(change.after_snapshot["source_doc_ids"]) == {
            "doc_section_source_阳神",
            "doc_section_source_完美世界",
            "doc_section_source_吞噬星空",
        }


async def test_generate_review_batch_blocks_external_mapping_without_source_coverage(async_session, monkeypatch):
    service = SettingWorkbenchService(async_session)
    session = await service.create_generation_session(
        novel_id="novel-ai-source-gate",
        title="外部宇宙对标",
        initial_idea="请生成仙逆、遮天、灭运图录对标一世之尊的境界映射。",
        target_categories=["世界观"],
    )
    await service.repo.add_message(
        session_id=session.id,
        role="assistant",
        content=(
            "**建议生成批次：**\n"
            "- 批次1：外部宇宙统一对标体系（含仙逆、遮天、灭运图录境界映射）\n"
        ),
    )
    await service.repo.update_session_state(session.id, status="ready_to_generate")

    async def should_not_call_model(*args, **kwargs):
        raise AssertionError("LLM should not be called when required source coverage is missing")

    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.call_and_parse_model",
        should_not_call_model,
    )

    with pytest.raises(ValueError, match="Source coverage insufficient.*仙逆.*遮天.*灭运图录"):
        await service.generate_review_batch(novel_id="novel-ai-source-gate", session_id=session.id)

    assert (await service.repo.get_session(session.id)).status == "ready_to_generate"
    batches = (
        await async_session.execute(
            select(SettingReviewBatch).where(SettingReviewBatch.novel_id == "novel-ai-source-gate")
        )
    ).scalars().all()
    assert batches == []


async def test_source_coverage_accepts_canonical_world_docs_outside_domain_types(async_session):
    service = SettingWorkbenchService(async_session)
    await service.doc_repo.create(
        "doc_yishi_realm",
        "novel-ai-yishi-source",
        "setting",
        "修炼体系",
        "一世之尊体系，从低到高：开窍→外景→法身→传说→造化→彼岸。",
    )
    await service.doc_repo.create(
        "doc_zhetian_realm_source",
        "novel-ai-yishi-source",
        "domain_setting",
        "遮天 / 修炼体系",
        "遮天修炼境界：四极、化龙、仙台、圣人、大帝、红尘仙。",
    )

    coverage = await service._build_source_coverage(
        novel_id="novel-ai-yishi-source",
        title="外部宇宙对标",
        target_categories=["世界观"],
        messages=[
            {
                "role": "user",
                "content": "生成遮天对标一世之尊的境界映射。",
            }
        ],
        required_sections=[],
    )

    assert coverage["required"] is True
    assert coverage["missing_domains"] == []
    matched = {item["name"]: item["matched_doc_ids"] for item in coverage["domains"]}
    assert matched["一世之尊"] == ["doc_yishi_realm"]
    assert matched["遮天"] == ["doc_zhetian_realm_source"]


async def test_source_coverage_does_not_match_other_domain_docs_by_incidental_content(async_session):
    service = SettingWorkbenchService(async_session)
    await service.doc_repo.create(
        "doc_perfect_realm_mentions_zhetian",
        "novel-ai-domain-noise",
        "domain_setting",
        "完美世界 / 修炼体系",
        "完美世界修炼体系，补充说明：与遮天世界存在后续关联。",
    )
    await service.doc_repo.create(
        "doc_zhetian_realm_clean",
        "novel-ai-domain-noise",
        "domain_setting",
        "遮天 / 修炼体系",
        "遮天修炼境界：四极、化龙、仙台、红尘仙。",
    )

    coverage = await service._build_source_coverage(
        novel_id="novel-ai-domain-noise",
        title="外部宇宙对标",
        target_categories=["世界观"],
        messages=[{"role": "user", "content": "生成遮天对标一世之尊的境界映射。"}],
        required_sections=[],
    )

    matched = {item["name"]: item["matched_doc_ids"] for item in coverage["domains"]}
    assert matched["遮天"] == ["doc_zhetian_realm_clean"]


async def test_generation_document_full_tool_is_bound_to_current_novel(async_session):
    service = SettingWorkbenchService(async_session)
    await service.doc_repo.create(
        "doc_bound_realm",
        "novel-ai-bound-doc-tool",
        "domain_setting",
        "完美世界 / 修炼体系",
        "搬血、洞天、化灵、铭纹、列阵。",
    )

    tools = service._build_generation_tools(
        novel_id="novel-ai-bound-doc-tool",
        current_setting_context={},
        orchestration_config=OrchestratedTaskConfig(
            tool_allowlist=["get_novel_document_full"],
            max_tool_result_chars=4000,
        ),
    )

    result = await tools[0].handler({
        "novel_id": "wrong-novel-id",
        "doc_id": "doc_bound_realm",
    })

    assert result["id"] == "doc_bound_realm"
    assert result["content"] == "搬血、洞天、化灵、铭纹、列阵。"


async def test_validate_batch_draft_rejects_non_monotonic_external_realm_mapping(async_session):
    from novel_dev.agents.setting_workbench_agent import SettingBatchDraft

    draft = SettingBatchDraft.model_validate(
        {
            "summary": "错误境界对标",
            "changes": [
                {
                    "target_type": "setting_card",
                    "operation": "create",
                    "after_snapshot": {
                        "doc_type": "setting",
                        "title": "遮天世界境界对标",
                        "source_doc_ids": ["doc_zhetian_realm"],
                        "content": (
                            "| 遮天境界 | 对标一世之尊 |\n"
                            "|----------|-------------|\n"
                            "| 大帝/古皇 | 传说~造化 |\n"
                            "| 红尘仙 | 初入传说 |\n"
                        ),
                    },
                }
            ],
        }
    )

    with pytest.raises(ValueError, match="Realm mapping order regression.*红尘仙"):
        SettingWorkbenchService(async_session)._validate_batch_draft(draft)


async def test_validate_batch_draft_allows_multi_world_realm_mapping_table(async_session):
    from novel_dev.agents.setting_workbench_agent import SettingBatchDraft

    draft = SettingBatchDraft.model_validate(
        {
            "summary": "多作品境界对标",
            "changes": [
                {
                    "target_type": "setting_card",
                    "operation": "create",
                    "after_snapshot": {
                        "doc_type": "power_system",
                        "title": "外部宇宙统一对标体系",
                        "source_doc_ids": ["doc_yangshen_realm", "doc_perfect_realm"],
                        "content": (
                            "| 原体系境界 | 对标一世之尊 |\n"
                            "|----------|-------------|\n"
                            "| 造物主/阳神 | 传说~造化 |\n"
                            "| 彼岸（阳神世界） | 彼岸 |\n"
                            "| 搬血/洞天/化灵/铭纹/列阵 | 开窍~外景初期 |\n"
                            "| 尊者/神火/真一/圣祭/天神 | 外景~法身 |\n"
                        ),
                    },
                }
            ],
        }
    )

    SettingWorkbenchService(async_session)._validate_batch_draft(draft)


async def test_validate_batch_draft_still_rejects_same_world_realm_mapping_regression(async_session):
    from novel_dev.agents.setting_workbench_agent import SettingBatchDraft

    draft = SettingBatchDraft.model_validate(
        {
            "summary": "同作品境界倒退",
            "changes": [
                {
                    "target_type": "setting_card",
                    "operation": "create",
                    "after_snapshot": {
                        "doc_type": "power_system",
                        "title": "完美世界境界对标",
                        "source_doc_ids": ["doc_perfect_realm"],
                        "content": (
                            "| 完美世界境界 | 对标一世之尊 |\n"
                            "|----------|-------------|\n"
                            "| 尊者/神火/真一 | 法身 |\n"
                            "| 圣祭/天神 | 外景 |\n"
                        ),
                    },
                }
            ],
        }
    )

    with pytest.raises(ValueError, match="Realm mapping order regression.*圣祭/天神"):
        SettingWorkbenchService(async_session)._validate_batch_draft(draft)


async def test_validate_batch_draft_rejects_cross_world_protagonist_contamination(async_session):
    from novel_dev.agents.setting_workbench_agent import SettingBatchDraft

    draft = SettingBatchDraft.model_validate(
        {
            "summary": "错误联动",
            "changes": [
                {
                    "target_type": "setting_card",
                    "operation": "create",
                    "after_snapshot": {
                        "doc_type": "setting",
                        "title": "跨作品联动剧情框架",
                        "source_doc_ids": ["doc_mieyun_plot"],
                        "content": "灭运图录：与纪宁共同探索永恒奥秘，参与混沌宇宙战争。",
                    },
                }
            ],
        }
    )

    with pytest.raises(ValueError, match="Canonical world/protagonist mismatch.*灭运图录.*纪宁"):
        SettingWorkbenchService(async_session)._validate_batch_draft(draft)


async def test_validate_batch_draft_allows_cross_work_protagonist_co_presence(async_session):
    from novel_dev.agents.setting_workbench_agent import SettingBatchDraft

    draft = SettingBatchDraft.model_validate(
        {
            "summary": "跨作品联动",
            "changes": [
                {
                    "target_type": "setting_card",
                    "operation": "create",
                    "after_snapshot": {
                        "doc_type": "plot",
                        "title": "跨作品联动剧情框架",
                        "source_doc_ids": ["doc_cross_work_plot"],
                        "content": "一世之尊体系作为真实界主线，后期与石昊等外部宇宙强者形成跨作品联动节点。",
                    },
                }
            ],
        }
    )

    SettingWorkbenchService(async_session)._validate_batch_draft(draft)


async def test_validate_batch_draft_allows_yishi_system_with_external_protagonist_list(async_session):
    from novel_dev.agents.setting_workbench_agent import SettingBatchDraft

    draft = SettingBatchDraft.model_validate(
        {
            "summary": "跨作品联动原则",
            "changes": [
                {
                    "target_type": "setting_card",
                    "operation": "create",
                    "after_snapshot": {
                        "doc_type": "plot",
                        "title": "跨作品联动设计原则",
                        "source_doc_ids": ["doc_cross_work_plot"],
                        "content": (
                            "【跨作品联动设计原则】\n"
                            "1. 一世之尊体系碾压优势：主角保有体系优势，"
                            "但尊重石昊、罗峰、叶凡等土著主角的原著成长轨迹。\n"
                            "2. 终局阶段，各世界至强者以投影形式参与共同威胁。"
                        ),
                    },
                }
            ],
        }
    )

    SettingWorkbenchService(async_session)._validate_batch_draft(draft)


async def test_validate_draft_source_evidence_requires_docs_to_cover_mentioned_domains(async_session):
    from novel_dev.agents.setting_workbench_agent import SettingBatchDraft

    service = SettingWorkbenchService(async_session)
    await service.doc_repo.create(
        "doc_yangshen_realm",
        "novel-ai-evidence",
        "domain_setting",
        "阳神 / 修炼体系",
        "阳神世界修炼体系资料。",
    )
    draft = SettingBatchDraft.model_validate(
        {
            "summary": "错误来源",
            "changes": [
                {
                    "target_type": "setting_card",
                    "operation": "create",
                    "after_snapshot": {
                        "doc_type": "setting",
                        "title": "仙逆世界境界对标",
                        "source_doc_ids": ["doc_yangshen_realm"],
                        "content": (
                            "| 仙逆境界 | 对标一世之尊 |\n"
                            "|----------|-------------|\n"
                            "| 踏天 | 传说 |\n"
                        ),
                    },
                }
            ],
        }
    )

    with pytest.raises(ValueError, match="Source evidence mismatch.*仙逆"):
        await service._validate_draft_source_evidence("novel-ai-evidence", draft)


async def test_fill_missing_source_doc_ids_from_coverage_for_external_setting(async_session):
    from novel_dev.agents.setting_workbench_agent import SettingBatchDraft

    service = SettingWorkbenchService(async_session)
    draft = SettingBatchDraft.model_validate(
        {
            "summary": "外部宇宙设定",
            "changes": [
                {
                    "target_type": "setting_card",
                    "operation": "create",
                    "after_snapshot": {
                        "doc_type": "plot",
                        "title": "跨作品联动剧情框架",
                        "content": "阳神与遮天作为外部宇宙参与跨作品联动，并纳入境界对标。",
                    },
                }
            ],
        }
    )

    service._fill_missing_source_doc_ids_from_coverage(
        draft,
        {
            "required": True,
            "domains": [
                {"name": "阳神", "matched_doc_ids": ["doc_yangshen_realm", "doc_yangshen_world"]},
                {"name": "遮天", "matched_doc_ids": ["doc_zhetian_realm"]},
                {"name": "仙逆", "matched_doc_ids": ["doc_xianni_realm"]},
            ],
        },
    )

    assert set(draft.changes[0].after_snapshot["source_doc_ids"]) == {
        "doc_yangshen_realm",
        "doc_yangshen_world",
        "doc_zhetian_realm",
    }


async def test_fill_missing_source_doc_ids_uses_all_coverage_for_generic_cross_work_card(async_session):
    from novel_dev.agents.setting_workbench_agent import SettingBatchDraft

    service = SettingWorkbenchService(async_session)
    draft = SettingBatchDraft.model_validate(
        {
            "summary": "外部宇宙设定",
            "changes": [
                {
                    "target_type": "setting_card",
                    "operation": "create",
                    "after_snapshot": {
                        "doc_type": "plot",
                        "title": "18卷整体结构规划",
                        "content": "真实界与外部宇宙双轨推进，后期进入跨作品联动和境界对标阶段。",
                    },
                }
            ],
        }
    )

    service._fill_missing_source_doc_ids_from_coverage(
        draft,
        {
            "required": True,
            "domains": [
                {"name": "阳神", "matched_doc_ids": ["doc_yangshen_realm"]},
                {"name": "遮天", "matched_doc_ids": ["doc_zhetian_realm"]},
            ],
        },
    )

    assert set(draft.changes[0].after_snapshot["source_doc_ids"]) == {
        "doc_yangshen_realm",
        "doc_zhetian_realm",
    }


async def test_fill_missing_source_doc_ids_falls_back_when_domain_key_does_not_match(async_session):
    from novel_dev.agents.setting_workbench_agent import SettingBatchDraft

    service = SettingWorkbenchService(async_session)
    draft = SettingBatchDraft.model_validate(
        {
            "summary": "外部宇宙设定",
            "changes": [
                {
                    "target_type": "setting_card",
                    "operation": "create",
                    "after_snapshot": {
                        "doc_type": "power_system",
                        "title": "外部宇宙统一对标体系",
                        "content": "吞噬星空境界映射需要纳入跨作品联动的境界对标。",
                    },
                }
            ],
        }
    )

    service._fill_missing_source_doc_ids_from_coverage(
        draft,
        {
            "required": True,
            "domains": [
                {"name": "吞噬星空 / 修炼体系", "matched_doc_ids": ["doc_tunshi_realm"]},
            ],
        },
    )

    assert draft.changes[0].after_snapshot["source_doc_ids"] == ["doc_tunshi_realm"]


async def test_generate_review_batch_emits_progress_logs(async_session, monkeypatch):
    service = SettingWorkbenchService(async_session)
    session = await service.create_generation_session(
        novel_id="novel-ai-log-success",
        title="日志设定",
        initial_idea="生成日志可见的审核批次",
        target_categories=["体系"],
    )
    await service.repo.add_message(
        session_id=session.id,
        role="assistant",
        content=(
            "**建议生成批次：**\n"
            "- 批次1：修炼体系总览\n"
            "- 批次2：势力格局总览\n"
        ),
    )
    await service.repo.update_session_state(session.id, status="ready_to_generate")
    emitted_logs = []

    def capture_log(novel_id, agent, message, level="info", **kwargs):
        emitted_logs.append({
            "novel_id": novel_id,
            "agent": agent,
            "message": message,
            "level": level,
            **kwargs,
        })

    monkeypatch.setattr("novel_dev.services.setting_workbench_service.log_service.add_log", capture_log)

    async def fake_call_and_parse_model(
        agent_name,
        task,
        prompt,
        model_cls,
        *,
        config_agent_name=None,
        novel_id="",
        max_retries=3,
    ):
        from novel_dev.agents.setting_workbench_agent import SettingBatchDraft

        assert "必须完整生成以下建议批次" in prompt
        if "修炼体系总览" in prompt:
            title = "修炼体系总览"
            content = "修炼体系。"
            assert "势力格局总览" not in prompt
        elif "势力格局总览" in prompt:
            title = "势力格局总览"
            content = "势力格局。"
            assert "修炼体系总览" not in prompt
        else:
            raise AssertionError("prompt should target one suggested batch")
        return SettingBatchDraft.model_validate(
            {
                "summary": title,
                "changes": [
                    {
                        "target_type": "setting_card",
                        "operation": "create",
                        "after_snapshot": {
                            "doc_type": "setting",
                            "title": title,
                            "content": content,
                        },
                    }
                ],
            }
        )

    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.call_and_parse_model",
        fake_call_and_parse_model,
    )

    batch = await service.generate_review_batch(novel_id="novel-ai-log-success", session_id=session.id)

    events = [item.get("node") for item in emitted_logs]
    assert events == [
        "setting_generate_prepare",
        "setting_generate_llm",
        "setting_generate_section",
        "setting_generate_section",
        "setting_generate_section",
        "setting_generate_section",
        "setting_generate_llm",
        "setting_generate_validate",
        "setting_generate_persist",
    ]
    assert emitted_logs[0]["metadata"]["message_count"] == 2
    assert emitted_logs[0]["metadata"]["required_section_count"] == 2
    assert emitted_logs[0]["metadata"]["prompt_chars"] > 0
    assert emitted_logs[3]["duration_ms"] >= 0
    assert emitted_logs[2]["metadata"]["section"]["title"] == "修炼体系总览"
    assert emitted_logs[4]["metadata"]["section"]["title"] == "势力格局总览"
    assert emitted_logs[-1]["metadata"]["batch_id"] == batch.id
    assert emitted_logs[-1]["metadata"]["change_count"] == 2


async def test_generate_review_batch_uses_orchestrated_context_tools_when_configured(async_session, monkeypatch):
    service = SettingWorkbenchService(async_session)
    await service.doc_repo.create(
        "doc_orch_setting",
        "novel-ai-orch",
        "setting",
        "秘境细节",
        "深层设定细节不应该进入首轮提示，但工具可以读取。",
    )
    await service.entity_service.create_entity(
        "ent_orch_guardian",
        "character",
        "守境人",
        novel_id="novel-ai-orch",
        initial_state={
            "境界": "深层实体状态不应该进入首轮提示",
            "职责": "看守秘境",
            "_merged_duplicate_entities": [{"entity_id": "ent_old_guardian"}],
        },
        use_llm_for_classification=False,
    )
    session = await service.create_generation_session(
        novel_id="novel-ai-orch",
        title="秘境补全",
        initial_idea="补一个秘境设定。",
        target_categories=["地域"],
    )
    await service.repo.update_session_state(session.id, status="ready_to_generate")

    orchestration_config = OrchestratedTaskConfig(
        tool_allowlist=["get_setting_workbench_context", "query_entity", "get_novel_documents"],
        max_tool_calls=3,
        max_tool_result_chars=1600,
    )
    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.llm_factory.resolve_orchestration_config",
        lambda agent_name, task: orchestration_config,
    )

    async def should_not_call_plain_model(*args, **kwargs):
        raise AssertionError("plain call_and_parse_model should not be used when orchestration is configured")

    async def fake_orchestrated_call_and_parse_model(
        agent_name,
        task,
        prompt,
        model_cls,
        *,
        tools,
        task_config,
        config_agent_name=None,
        novel_id="",
        max_retries=3,
    ):
        from novel_dev.agents.setting_workbench_agent import SettingBatchDraft

        assert agent_name == "SettingWorkbenchService"
        assert task == "setting_workbench_generate_batch"
        assert model_cls is SettingBatchDraft
        assert config_agent_name == "setting_workbench_service"
        assert novel_id == "novel-ai-orch"
        assert max_retries == 2
        assert task_config is orchestration_config
        assert "补一个秘境设定" in prompt
        assert "深层设定细节不应该进入首轮提示" not in prompt
        assert "query_entity" in prompt
        tool_names = [tool.name for tool in tools]
        assert "get_setting_workbench_context" in tool_names
        assert "query_entity" in tool_names
        assert "get_novel_documents" in tool_names
        context_tool = next(tool for tool in tools if tool.name == "get_setting_workbench_context")
        context = await context_tool.handler({"novel_id": "novel-ai-orch"})
        assert context["documents"][0]["content_preview"] == "深层设定细节不应该进入首轮提示，但工具可以读取。"
        assert context["entities"][0]["state"]["境界"] == "深层实体状态不应该进入首轮提示"
        assert "_merged_duplicate_entities" not in context["entities"][0]["state"]
        return SettingBatchDraft.model_validate(
            {
                "summary": "新增秘境设定",
                "changes": [
                    {
                        "target_type": "setting_card",
                        "operation": "create",
                        "after_snapshot": {
                            "doc_type": "setting",
                            "title": "秘境",
                            "content": "云渊秘境每十年开启。",
                        },
                    }
                ],
            }
        )

    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.call_and_parse_model",
        should_not_call_plain_model,
    )
    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.orchestrated_call_and_parse_model",
        fake_orchestrated_call_and_parse_model,
    )

    batch = await service.generate_review_batch(novel_id="novel-ai-orch", session_id=session.id)

    assert batch.summary == "新增秘境设定"

    documents = await DocumentRepository(async_session).get_by_type_and_title(
        "novel-ai-gen",
        "setting",
        "势力格局",
    )
    entities = (
        await async_session.execute(select(Entity).where(Entity.novel_id == "novel-ai-gen"))
    ).scalars().all()
    assert documents == []
    assert entities == []


async def test_generate_review_batch_includes_existing_setting_context(async_session, monkeypatch):
    service = SettingWorkbenchService(async_session)
    await DocumentRepository(async_session).create(
        "doc_ctx_world",
        "novel-ai-context",
        "worldview",
        "世界观",
        "中央大陆被九宗共同治理。",
    )
    await DocumentRepository(async_session).create(
        "doc_ctx_setting",
        "novel-ai-context",
        "setting",
        "修炼体系",
        "炼气、筑基、金丹三境。",
    )
    entity_service = EntityService(async_session)
    entity_service._refresh_entity_artifacts = AsyncMock()
    await entity_service.create_entity(
        "ent_ctx_luzhao",
        "character",
        "陆照",
        novel_id="novel-ai-context",
        initial_state={
            "identity": "主角",
            "goal": "寻找道经",
            "_merged_duplicate_entities": [
                {"entity_id": "ent_old_luzhao", "state": {"identity": "旧重复实体"}}
            ],
        },
    )
    await entity_service.create_entity(
        "ent_ctx_daojing",
        "item",
        "道经",
        novel_id="novel-ai-context",
        initial_state={"description": "陆照所得功法"},
    )
    await service.relationship_repo.create(
        "ent_ctx_luzhao",
        "ent_ctx_daojing",
        "修炼功法",
        novel_id="novel-ai-context",
    )
    session = await service.create_generation_session(
        novel_id="novel-ai-context",
        title="补充宗门设定",
        initial_idea="生成一个与陆照有关的宗门。",
        target_categories=["势力"],
    )
    await service.repo.update_session_state(session.id, status="ready_to_generate")

    async def fake_call_and_parse_model(
        agent_name,
        task,
        prompt,
        model_cls,
        *,
        config_agent_name=None,
        novel_id="",
        max_retries=3,
    ):
        from novel_dev.agents.setting_workbench_agent import SettingBatchDraft

        assert task == "setting_workbench_generate_batch"
        assert model_cls is SettingBatchDraft
        assert "当前已生效设定上下文" in prompt
        assert "中央大陆被九宗共同治理" in prompt
        assert "炼气、筑基、金丹三境" in prompt
        assert "ent_ctx_luzhao" in prompt
        assert "陆照" in prompt
        assert "_merged_duplicate_entities" not in prompt
        assert "ent_old_luzhao" not in prompt
        assert "ent_ctx_daojing" in prompt
        assert "修炼功法" in prompt
        return SettingBatchDraft.model_validate(
            {
                "summary": "新增宗门实体",
                "changes": [
                    {
                        "target_type": "entity",
                        "operation": "create",
                        "after_snapshot": {
                            "type": "faction",
                            "name": "玄天宗",
                            "state": {"description": "守护中央大陆的宗门"},
                        },
                    },
                ],
            }
        )

    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.call_and_parse_model",
        fake_call_and_parse_model,
    )

    batch = await service.generate_review_batch(novel_id="novel-ai-context", session_id=session.id)

    assert batch.summary == "新增宗门实体"


async def test_generate_review_batch_excludes_noisy_relationship_metadata_from_prompt(
    async_session,
    monkeypatch,
):
    service = SettingWorkbenchService(async_session)
    entity_service = EntityService(async_session)
    entity_service._refresh_entity_artifacts = AsyncMock()
    await entity_service.create_entity(
        "ent_ctx_meta_luzhao",
        "character",
        "陆照",
        novel_id="novel-ai-rel-meta",
        initial_state={"identity": "主角"},
    )
    await entity_service.create_entity(
        "ent_ctx_meta_daojing",
        "item",
        "道经",
        novel_id="novel-ai-rel-meta",
        initial_state={"description": "功法"},
    )
    await service.relationship_repo.create(
        "ent_ctx_meta_luzhao",
        "ent_ctx_meta_daojing",
        "修炼功法",
        novel_id="novel-ai-rel-meta",
        meta={
            "source": "relationship_backfill",
            "evidence": "NOISY_RELATIONSHIP_METADATA_SHOULD_NOT_LEAK",
            "source_entity_names": ["很长的回填实体列表"] * 20,
        },
    )
    session = await service.create_generation_session(
        novel_id="novel-ai-rel-meta",
        title="补充设定",
        initial_idea="补充设定",
        target_categories=["关系"],
    )
    await service.repo.update_session_state(session.id, status="ready_to_generate")

    async def fake_call_and_parse_model(
        agent_name,
        task,
        prompt,
        model_cls,
        *,
        config_agent_name=None,
        novel_id="",
        max_retries=3,
    ):
        from novel_dev.agents.setting_workbench_agent import SettingBatchDraft

        assert "修炼功法" in prompt
        assert "ent_ctx_meta_luzhao" in prompt
        assert "ent_ctx_meta_daojing" in prompt
        assert "NOISY_RELATIONSHIP_METADATA_SHOULD_NOT_LEAK" not in prompt
        assert "source_entity_names" not in prompt
        return SettingBatchDraft.model_validate(
            {
                "summary": "新增设定卡片",
                "changes": [
                    {
                        "target_type": "setting_card",
                        "operation": "create",
                        "after_snapshot": {
                            "doc_type": "setting",
                            "title": "关系补充",
                            "content": "陆照修炼道经。",
                        },
                    }
                ],
            }
        )

    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.call_and_parse_model",
        fake_call_and_parse_model,
    )

    await service.generate_review_batch(novel_id="novel-ai-rel-meta", session_id=session.id)


@pytest.mark.parametrize("status", ["clarifying", "generating", "failed", "archived"])
async def test_generate_review_batch_rejects_non_ready_or_generated_status(async_session, status):
    service = SettingWorkbenchService(async_session)
    session = await service.create_generation_session(
        novel_id=f"novel-ai-gen-{status}",
        title="状态校验",
        initial_idea="不能生成",
        target_categories=["势力"],
    )
    await service.repo.update_session_state(session.id, status=status)

    with pytest.raises(ValueError, match="not ready to generate"):
        await service.generate_review_batch(novel_id=f"novel-ai-gen-{status}", session_id=session.id)


async def test_generate_review_batch_rejects_empty_changes_and_restores_ready_state(
    async_session,
    monkeypatch,
):
    service = SettingWorkbenchService(async_session)
    session = await service.create_generation_session(
        novel_id="novel-ai-empty-draft",
        title="空变更",
        initial_idea="重新生成空审核批次",
        target_categories=["势力"],
    )
    await service.repo.update_session_state(session.id, status="generated")

    async def fake_call_and_parse_model(
        agent_name,
        task,
        prompt,
        model_cls,
        *,
        config_agent_name=None,
        novel_id="",
        max_retries=3,
    ):
        from novel_dev.agents.setting_workbench_agent import SettingBatchDraft

        assert agent_name == "SettingWorkbenchService"
        assert task == "setting_workbench_generate_batch"
        assert model_cls is SettingBatchDraft
        assert config_agent_name == "setting_workbench_service"
        assert novel_id == "novel-ai-empty-draft"
        assert max_retries == 2
        return SettingBatchDraft.model_construct(summary="重新生成空批次", changes=[])

    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.call_and_parse_model",
        fake_call_and_parse_model,
    )

    with pytest.raises(ValueError, match="at least one change"):
        await service.generate_review_batch(novel_id="novel-ai-empty-draft", session_id=session.id)

    assert (await service.repo.get_session(session.id)).status == "ready_to_generate"
    batches = (
        await async_session.execute(
            select(SettingReviewBatch).where(SettingReviewBatch.novel_id == "novel-ai-empty-draft")
        )
    ).scalars().all()
    changes = (await async_session.execute(select(SettingReviewChange))).scalars().all()
    messages = await service.repo.list_messages(session.id)
    assert batches == []
    assert changes == []
    assert messages[-1].role == "assistant"
    assert messages[-1].meta["status"] == "error"


async def test_generate_review_batch_restores_ready_state_when_llm_fails(async_session, monkeypatch):
    service = SettingWorkbenchService(async_session)
    session = await service.create_generation_session(
        novel_id="novel-ai-llm-fail",
        title="LLM 失败",
        initial_idea="生成会失败",
        target_categories=["势力"],
    )
    await service.repo.update_session_state(session.id, status="ready_to_generate")

    async def fake_call_and_parse_model(
        agent_name,
        task,
        prompt,
        model_cls,
        *,
        config_agent_name=None,
        novel_id="",
        max_retries=3,
    ):
        from novel_dev.agents.setting_workbench_agent import SettingBatchDraft

        assert agent_name == "SettingWorkbenchService"
        assert task == "setting_workbench_generate_batch"
        assert model_cls is SettingBatchDraft
        assert config_agent_name == "setting_workbench_service"
        assert novel_id == "novel-ai-llm-fail"
        assert max_retries == 2
        raise RuntimeError("LLM down")

    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.call_and_parse_model",
        fake_call_and_parse_model,
    )

    with pytest.raises(RuntimeError, match="LLM down"):
        await service.generate_review_batch(novel_id="novel-ai-llm-fail", session_id=session.id)

    assert (await service.repo.get_session(session.id)).status == "ready_to_generate"
    batches = (
        await async_session.execute(
            select(SettingReviewBatch).where(SettingReviewBatch.novel_id == "novel-ai-llm-fail")
        )
    ).scalars().all()
    changes = (await async_session.execute(select(SettingReviewChange))).scalars().all()
    messages = await service.repo.list_messages(session.id)
    assert batches == []
    assert changes == []
    assert messages[-1].role == "assistant"
    assert messages[-1].meta["status"] == "error"


async def test_generate_review_batch_times_out_before_frontend_request_budget(
    async_session,
    monkeypatch,
):
    service = SettingWorkbenchService(async_session)
    session = await service.create_generation_session(
        novel_id="novel-ai-wall-timeout",
        title="超时生成",
        initial_idea="生成一个会拖很久的审核批次",
        target_categories=["势力"],
    )
    await service.repo.update_session_state(session.id, status="ready_to_generate")
    emitted_logs = []

    def capture_log(novel_id, agent, message, level="info", **kwargs):
        emitted_logs.append({
            "novel_id": novel_id,
            "agent": agent,
            "message": message,
            "level": level,
            **kwargs,
        })

    monkeypatch.setattr("novel_dev.services.setting_workbench_service.log_service.add_log", capture_log)
    monkeypatch.setattr(
        SettingWorkbenchService,
        "GENERATE_BATCH_WALL_TIMEOUT_SECONDS",
        0.01,
        raising=False,
    )

    async def slow_call_and_parse_model(*args, **kwargs):
        await asyncio.sleep(0.05)
        from novel_dev.agents.setting_workbench_agent import SettingBatchDraft

        return SettingBatchDraft.model_validate(
            {
                "summary": "迟到的批次",
                "changes": [
                    {
                        "target_type": "entity",
                        "operation": "create",
                        "after_snapshot": {"type": "faction", "name": "迟到宗", "state": {}},
                    }
                ],
            }
        )

    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.call_and_parse_model",
        slow_call_and_parse_model,
    )

    with pytest.raises(LLMTimeoutError, match="Setting workbench generation timed out"):
        await service.generate_review_batch(novel_id="novel-ai-wall-timeout", session_id=session.id)

    assert (await service.repo.get_session(session.id)).status == "ready_to_generate"
    batches = (
        await async_session.execute(
            select(SettingReviewBatch).where(SettingReviewBatch.novel_id == "novel-ai-wall-timeout")
        )
    ).scalars().all()
    messages = await service.repo.list_messages(session.id)
    assert batches == []
    assert messages[-1].role == "assistant"
    assert messages[-1].meta["status"] == "error"
    assert messages[-1].meta["stage"] == "setting_workbench_generate_batch"
    failed_logs = [item for item in emitted_logs if item.get("status") == "failed"]
    assert failed_logs
    assert failed_logs[-1]["level"] == "error"
    assert failed_logs[-1]["node"] == "setting_generate"
    assert failed_logs[-1]["metadata"]["error_type"] == "LLMTimeoutError"
    assert failed_logs[-1]["metadata"]["timeout_seconds"] == 0.01


async def test_generate_review_batch_default_timeout_allows_large_setting_batches():
    assert SettingWorkbenchService.GENERATE_BATCH_WALL_TIMEOUT_SECONDS == 300


async def test_generate_review_batch_rejects_update_draft_without_target_id_before_creating_batch(
    async_session,
    monkeypatch,
):
    service = SettingWorkbenchService(async_session)
    session = await service.create_generation_session(
        novel_id="novel-ai-invalid-draft",
        title="无目标更新",
        initial_idea="更新青云门",
        target_categories=["势力"],
    )
    await service.repo.update_session_state(session.id, status="ready_to_generate")

    async def fake_call_and_parse_model(
        agent_name,
        task,
        prompt,
        model_cls,
        *,
        config_agent_name=None,
        novel_id="",
        max_retries=3,
    ):
        from novel_dev.agents.setting_workbench_agent import SettingBatchChangeDraft, SettingBatchDraft

        assert agent_name == "SettingWorkbenchService"
        assert task == "setting_workbench_generate_batch"
        assert model_cls is SettingBatchDraft
        assert config_agent_name == "setting_workbench_service"
        assert novel_id == "novel-ai-invalid-draft"
        assert max_retries == 2
        return SettingBatchDraft.model_construct(
            summary="缺少目标实体的更新",
            changes=[
                SettingBatchChangeDraft.model_construct(
                    target_type="entity",
                    operation="update",
                    target_id=None,
                    before_snapshot=None,
                    after_snapshot={"type": "faction", "name": "青云门", "state": {}},
                    conflict_hints=[],
                )
            ],
        )

    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.call_and_parse_model",
        fake_call_and_parse_model,
    )

    with pytest.raises(ValueError, match="target_id is required"):
        await service.generate_review_batch(novel_id="novel-ai-invalid-draft", session_id=session.id)

    assert (await service.repo.get_session(session.id)).status == "ready_to_generate"
    batches = (
        await async_session.execute(
            select(SettingReviewBatch).where(SettingReviewBatch.novel_id == "novel-ai-invalid-draft")
        )
    ).scalars().all()
    changes = (await async_session.execute(select(SettingReviewChange))).scalars().all()
    assert batches == []
    assert changes == []


async def test_generate_review_batch_rejects_relationship_ref_fields_before_creating_batch(
    async_session,
    monkeypatch,
):
    service = SettingWorkbenchService(async_session)
    session = await service.create_generation_session(
        novel_id="novel-ai-rel-ref",
        title="关系引用",
        initial_idea="陆照持有道种",
        target_categories=["关系"],
    )
    await service.repo.update_session_state(session.id, status="ready_to_generate")

    async def fake_call_and_parse_model(
        agent_name,
        task,
        prompt,
        model_cls,
        *,
        config_agent_name=None,
        novel_id="",
        max_retries=3,
    ):
        from novel_dev.agents.setting_workbench_agent import SettingBatchChangeDraft, SettingBatchDraft

        assert agent_name == "SettingWorkbenchService"
        assert task == "setting_workbench_generate_batch"
        assert model_cls is SettingBatchDraft
        assert config_agent_name == "setting_workbench_service"
        assert novel_id == "novel-ai-rel-ref"
        assert max_retries == 2
        return SettingBatchDraft.model_construct(
            summary="混用了 ref 的关系",
            changes=[
                SettingBatchChangeDraft.model_construct(
                    target_type="relationship",
                    operation="create",
                    target_id=None,
                    before_snapshot=None,
                    after_snapshot={
                        "source_id": "ent_luzhao",
                        "target_id": "ent_seed",
                        "source_ref": "陆照",
                        "relation_type": "持有",
                    },
                    conflict_hints=[],
                )
            ],
        )

    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.call_and_parse_model",
        fake_call_and_parse_model,
    )

    with pytest.raises(ValueError, match="must not use ref fields"):
        await service.generate_review_batch(novel_id="novel-ai-rel-ref", session_id=session.id)

    assert (await service.repo.get_session(session.id)).status == "ready_to_generate"
    batches = (
        await async_session.execute(
            select(SettingReviewBatch).where(SettingReviewBatch.novel_id == "novel-ai-rel-ref")
        )
    ).scalars().all()
    changes = (await async_session.execute(select(SettingReviewChange))).scalars().all()
    assert batches == []
    assert changes == []


async def test_generate_review_batch_repairs_same_batch_entity_id_for_relationship(
    async_session,
    monkeypatch,
):
    service = SettingWorkbenchService(async_session)
    session = await service.create_generation_session(
        novel_id="novel-ai-rel-missing-entity-id",
        title="同批实体关系",
        initial_idea="陆照持有道种",
        target_categories=["实体", "关系"],
    )
    await service.repo.update_session_state(session.id, status="ready_to_generate")

    async def fake_call_and_parse_model(
        agent_name,
        task,
        prompt,
        model_cls,
        *,
        config_agent_name=None,
        novel_id="",
        max_retries=3,
    ):
        from novel_dev.agents.setting_workbench_agent import SettingBatchChangeDraft, SettingBatchDraft

        assert agent_name == "SettingWorkbenchService"
        assert task == "setting_workbench_generate_batch"
        assert model_cls is SettingBatchDraft
        assert config_agent_name == "setting_workbench_service"
        assert novel_id == "novel-ai-rel-missing-entity-id"
        assert max_retries == 2
        return SettingBatchDraft.model_construct(
            summary="同批新增实体和关系但实体无 id",
            changes=[
                SettingBatchChangeDraft.model_construct(
                    target_type="entity",
                    operation="create",
                    target_id=None,
                    before_snapshot=None,
                    after_snapshot={"type": "character", "name": "陆照", "state": {}},
                    conflict_hints=[],
                ),
                SettingBatchChangeDraft.model_construct(
                    target_type="relationship",
                    operation="create",
                    target_id=None,
                    before_snapshot=None,
                    after_snapshot={
                        "source_id": "ent_luzhao",
                        "target_id": "ent_seed",
                        "relation_type": "持有",
                    },
                    conflict_hints=[],
                ),
            ],
        )

    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.call_and_parse_model",
        fake_call_and_parse_model,
    )

    batch = await service.generate_review_batch(
        novel_id="novel-ai-rel-missing-entity-id",
        session_id=session.id,
    )

    assert batch.status == "pending"
    changes = (
        await async_session.execute(
            select(SettingReviewChange).where(SettingReviewChange.batch_id == batch.id)
        )
    ).scalars().all()
    entity_change = next(change for change in changes if change.target_type == "entity")
    assert entity_change.after_snapshot["id"] == "ent_luzhao"
    assert (await service.repo.get_session(session.id)).status == "generated"


async def test_validate_batch_draft_allows_relationship_to_same_batch_entity_id(async_session):
    from novel_dev.agents.setting_workbench_agent import SettingBatchDraft

    draft = SettingBatchDraft.model_validate(
        {
            "summary": "同批新增实体和关系",
            "changes": [
                {
                    "target_type": "entity",
                    "operation": "create",
                    "after_snapshot": {
                        "id": "ent_luzhao",
                        "type": "character",
                        "name": "陆照",
                        "state": {},
                    },
                },
                {
                    "target_type": "relationship",
                    "operation": "create",
                    "after_snapshot": {
                        "source_id": "ent_luzhao",
                        "target_id": "ent_seed",
                        "relation_type": "持有",
                    },
                },
            ],
        }
    )

    SettingWorkbenchService(async_session)._validate_batch_draft(draft)


async def test_generate_review_batch_rolls_back_when_change_persistence_fails(
    async_session,
    monkeypatch,
):
    service = SettingWorkbenchService(async_session)
    session = await service.create_generation_session(
        novel_id="novel-ai-mid-persist-fail",
        title="持久化失败",
        initial_idea="生成后写入失败",
        target_categories=["势力"],
    )
    await service.repo.update_session_state(session.id, status="ready_to_generate")

    async def fake_call_and_parse_model(
        agent_name,
        task,
        prompt,
        model_cls,
        *,
        config_agent_name=None,
        novel_id="",
        max_retries=3,
    ):
        from novel_dev.agents.setting_workbench_agent import SettingBatchDraft

        assert agent_name == "SettingWorkbenchService"
        assert task == "setting_workbench_generate_batch"
        assert model_cls is SettingBatchDraft
        assert config_agent_name == "setting_workbench_service"
        assert novel_id == "novel-ai-mid-persist-fail"
        assert max_retries == 2
        return SettingBatchDraft.model_validate(
            {
                "summary": "新增设定",
                "changes": [
                    {
                        "target_type": "setting_card",
                        "operation": "create",
                        "after_snapshot": {
                            "doc_type": "setting",
                            "title": "势力格局",
                            "content": "青云门与魔宗对立。",
                        },
                    },
                ],
            }
        )

    async def fail_add_review_change(**kwargs):
        raise RuntimeError("change persistence failed")

    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.call_and_parse_model",
        fake_call_and_parse_model,
    )
    monkeypatch.setattr(service.repo, "add_review_change", fail_add_review_change)

    with pytest.raises(RuntimeError, match="change persistence failed"):
        await service.generate_review_batch(
            novel_id="novel-ai-mid-persist-fail",
            session_id=session.id,
        )

    assert (await service.repo.get_session(session.id)).status == "ready_to_generate"
    batches = (
        await async_session.execute(
            select(SettingReviewBatch).where(SettingReviewBatch.novel_id == "novel-ai-mid-persist-fail")
        )
    ).scalars().all()
    changes = (await async_session.execute(select(SettingReviewChange))).scalars().all()
    messages = await service.repo.list_messages(session.id)
    assert batches == []
    assert changes == []
    assert messages[-1].role == "assistant"
    assert messages[-1].meta["status"] == "error"
    assert "change persistence failed" in messages[-1].content


async def test_setting_batch_draft_rejects_relationship_create_without_entity_ids():
    from novel_dev.agents.setting_workbench_agent import SettingBatchDraft

    with pytest.raises(ValidationError, match="source_id, target_id, and relation_type"):
        SettingBatchDraft.model_validate(
            {
                "summary": "新增 ref-only 关系",
                "changes": [
                    {
                        "target_type": "relationship",
                        "operation": "create",
                        "after_snapshot": {
                            "source_ref": "陆照",
                            "target_ref": "道种",
                            "relation_type": "持有",
                        },
                    },
                ],
            }
        )


async def test_llm_config_sets_setting_workbench_service_generation_budget():
    config = yaml.safe_load(Path("llm_config.yaml").read_text())

    setting_workbench = config["agents"]["setting_workbench_service"]
    assert setting_workbench["temperature"] == 0.55
    assert setting_workbench["max_tokens"] == 12000
    assert setting_workbench["orchestration"]["enabled"] is True
    assert setting_workbench["orchestration"]["tool_allowlist"] == [
        "get_setting_workbench_context",
        "query_entity",
        "get_novel_state",
        "get_novel_documents",
        "search_domain_documents",
        "get_novel_document_full",
    ]
    assert setting_workbench["orchestration"]["max_tool_calls"] == 20
    assert setting_workbench["orchestration"]["max_tool_result_chars"] == 6000
    assert setting_workbench["orchestration"]["enable_subtasks"] is True
    assert setting_workbench["orchestration"]["repairer_subtask"] == "schema_repair"
