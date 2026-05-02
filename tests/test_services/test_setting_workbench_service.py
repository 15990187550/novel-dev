from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from sqlalchemy import select

from novel_dev.db.models import Entity, EntityRelationship, NovelDocument, SettingReviewBatch, SettingReviewChange
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.setting_workbench_repo import SettingWorkbenchRepository
from novel_dev.services.entity_service import EntityService
from novel_dev.services.setting_workbench_service import SettingWorkbenchService

pytestmark = pytest.mark.asyncio


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


async def test_generate_review_batch_rejects_relationship_to_same_batch_entity_without_id(
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
                        "source_id": "陆照",
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

    with pytest.raises(ValueError, match="same-batch entity create.*after_snapshot.id"):
        await service.generate_review_batch(
            novel_id="novel-ai-rel-missing-entity-id",
            session_id=session.id,
        )

    assert (await service.repo.get_session(session.id)).status == "ready_to_generate"
    batches = (
        await async_session.execute(
            select(SettingReviewBatch).where(SettingReviewBatch.novel_id == "novel-ai-rel-missing-entity-id")
        )
    ).scalars().all()
    changes = (await async_session.execute(select(SettingReviewChange))).scalars().all()
    assert batches == []
    assert changes == []


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
