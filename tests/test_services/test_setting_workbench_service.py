import pytest
from sqlalchemy import select

from novel_dev.db.models import Entity, EntityRelationship, NovelDocument
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
