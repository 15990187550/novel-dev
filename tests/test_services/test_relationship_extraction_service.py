from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from novel_dev.db.models import EntityRelationship
from novel_dev.repositories.entity_repo import EntityRepository
import novel_dev.services.relationship_extraction_service as relationship_module
from novel_dev.services.relationship_extraction_service import (
    ExtractedRelationship,
    RelationshipExtractionResult,
    RelationshipExtractionService,
)


@pytest.mark.asyncio
async def test_extract_and_persist_setting_relationships_resolves_entities_by_name(async_session):
    entity_repo = EntityRepository(async_session)
    await entity_repo.create("shihao", "character", "石昊", novel_id="n_rel_extract")
    await entity_repo.create("yunxi", "character", "云曦", novel_id="n_rel_extract")
    extractor = AsyncMock(
        return_value=RelationshipExtractionResult(
            relationships=[
                ExtractedRelationship(
                    source_entity_name="石昊",
                    target_entity_name="云曦",
                    relation_type="妻子",
                    evidence="云曦是石昊的妻子。",
                    confidence=0.92,
                )
            ]
        )
    )
    service = RelationshipExtractionService(async_session, extractor=extractor)

    result = await service.extract_and_persist_from_setting(
        novel_id="n_rel_extract",
        source_text="石昊与云曦结为夫妻。",
        source_ref="setting.md",
    )

    rows = (
        await async_session.execute(
            select(EntityRelationship).where(EntityRelationship.novel_id == "n_rel_extract")
        )
    ).scalars().all()
    assert result["created"] == 1
    assert result["skipped"] == []
    assert len(rows) == 1
    assert rows[0].source_id == "shihao"
    assert rows[0].target_id == "yunxi"
    assert rows[0].relation_type == "妻子"
    assert rows[0].meta["evidence"] == "云曦是石昊的妻子。"
    assert rows[0].meta["confidence"] == 0.92
    assert rows[0].meta["source_ref"] == "setting.md"


@pytest.mark.asyncio
async def test_extract_and_persist_setting_relationships_skips_unresolved_entities(async_session):
    entity_repo = EntityRepository(async_session)
    await entity_repo.create("shihao", "character", "石昊", novel_id="n_rel_skip")
    await entity_repo.create("huolinger", "character", "火灵儿", novel_id="n_rel_skip")
    extractor = AsyncMock(
        return_value=RelationshipExtractionResult(
            relationships=[
                ExtractedRelationship(
                    source_entity_name="石昊",
                    target_entity_name="云曦",
                    relation_type="妻子",
                    evidence="云曦是石昊的妻子。",
                    confidence=0.92,
                )
            ]
        )
    )
    service = RelationshipExtractionService(async_session, extractor=extractor)

    result = await service.extract_and_persist_from_setting(
        novel_id="n_rel_skip",
        source_text="石昊与云曦结为夫妻。",
        source_ref="setting.md",
    )

    rows = (
        await async_session.execute(
            select(EntityRelationship).where(EntityRelationship.novel_id == "n_rel_skip")
        )
    ).scalars().all()
    assert result["created"] == 0
    assert rows == []
    assert result["skipped"] == [
        {
            "source_entity_name": "石昊",
            "target_entity_name": "云曦",
            "relation_type": "妻子",
            "reason": "entity_not_found_or_ambiguous",
        }
    ]


@pytest.mark.asyncio
async def test_extract_and_persist_global_setting_ignores_local_domain_name_collisions(async_session):
    entity_repo = EntityRepository(async_session)
    hero = await entity_repo.create("luzhao", "character", "陆照", novel_id="n_rel_global")
    local = await entity_repo.create("dao-local", "item", "道经", novel_id="n_rel_global")
    domain = await entity_repo.create("dao-domain", "item", "道经", novel_id="n_rel_global")
    hero.search_document = "名称：陆照\n一级分类：人物"
    local.search_document = "名称：道经\n一级分类：功法"
    domain.search_document = "名称：道经\n一级分类：功法\n_knowledge_domain_id：domain_yangshen\n_knowledge_domain_name：阳神"
    extractor = AsyncMock(
        return_value=RelationshipExtractionResult(
            relationships=[
                ExtractedRelationship(
                    source_entity_name="陆照",
                    target_entity_name="道经",
                    relation_type="所修功法",
                    evidence="陆照修行道经。",
                    confidence=0.9,
                )
            ]
        )
    )
    service = RelationshipExtractionService(async_session, extractor=extractor)

    result = await service.extract_and_persist_from_setting(
        novel_id="n_rel_global",
        source_text="陆照修行道经。",
        source_ref="setting.md",
    )

    rows = (
        await async_session.execute(
            select(EntityRelationship).where(EntityRelationship.novel_id == "n_rel_global")
        )
    ).scalars().all()
    assert result["created"] == 1
    assert rows[0].source_id == "luzhao"
    assert rows[0].target_id == "dao-local"


@pytest.mark.asyncio
async def test_relationship_extraction_inherits_setting_extractor_task_config(async_session, monkeypatch):
    captured = {}

    async def fake_call_and_parse_model(*args, **kwargs):
        captured.update(kwargs)
        return RelationshipExtractionResult(relationships=[])

    monkeypatch.setattr(relationship_module, "call_and_parse_model", fake_call_and_parse_model)
    service = RelationshipExtractionService(async_session)

    await service._extract(
        "n_config",
        "石昊与云曦结为夫妻。",
        "setting.md",
        [
            {"id": "shihao", "name": "石昊", "type": "character", "scope": "global"},
            {"id": "yunxi", "name": "云曦", "type": "character", "scope": "global"},
        ],
    )

    assert captured["config_agent_name"] == "SettingExtractorAgent"
    assert captured["config_task"] == "extract_setting"
