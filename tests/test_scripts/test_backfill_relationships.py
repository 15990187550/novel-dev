import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from novel_dev.db.models import EntityRelationship, NovelDocument
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.scripts.backfill_relationships import RelationshipBackfillService
from novel_dev.services.relationship_extraction_service import (
    ExtractedRelationship,
    RelationshipExtractionResult,
)


@pytest.mark.asyncio
async def test_backfill_relationships_from_documents_writes_edges(async_session):
    entity_repo = EntityRepository(async_session)
    await entity_repo.create("shihao", "character", "石昊", novel_id="n_backfill_rel")
    await entity_repo.create("yunxi", "character", "云曦", novel_id="n_backfill_rel")
    async_session.add(
        NovelDocument(
            id="doc-setting",
            novel_id="n_backfill_rel",
            doc_type="concept",
            title="人物设定",
            content="石昊与云曦结为夫妻。",
            version=1,
        )
    )
    await async_session.flush()
    extractor = AsyncMock(
        return_value=RelationshipExtractionResult(
            relationships=[
                ExtractedRelationship(
                    source_entity_name="石昊",
                    target_entity_name="云曦",
                    relation_type="妻子",
                    evidence="石昊与云曦结为夫妻。",
                    confidence=0.9,
                )
            ]
        )
    )

    service = RelationshipBackfillService(async_session, extractor=extractor)
    result = await service.backfill_documents("n_backfill_rel")

    relationships = (
        await async_session.execute(
            select(EntityRelationship).where(EntityRelationship.novel_id == "n_backfill_rel")
        )
    ).scalars().all()
    assert result["processed"] == 1
    assert result["created"] == 1
    assert result["dry_run"] is False
    assert len(relationships) == 1
    assert relationships[0].relation_type == "妻子"
    assert relationships[0].meta["source"] == "relationship_backfill"
    assert relationships[0].meta["source_doc_id"] == "doc-setting"


@pytest.mark.asyncio
async def test_backfill_relationships_dry_run_does_not_write_edges(async_session):
    entity_repo = EntityRepository(async_session)
    await entity_repo.create("shihao", "character", "石昊", novel_id="n_backfill_dry")
    await entity_repo.create("yunxi", "character", "云曦", novel_id="n_backfill_dry")
    async_session.add(
        NovelDocument(
            id="doc-setting-dry",
            novel_id="n_backfill_dry",
            doc_type="concept",
            title="人物设定",
            content="石昊与云曦结为夫妻。",
            version=1,
        )
    )
    await async_session.flush()
    extractor = AsyncMock(
        return_value=RelationshipExtractionResult(
            relationships=[
                ExtractedRelationship(
                    source_entity_name="石昊",
                    target_entity_name="云曦",
                    relation_type="妻子",
                    evidence="石昊与云曦结为夫妻。",
                    confidence=0.9,
                )
            ]
        )
    )

    service = RelationshipBackfillService(async_session, extractor=extractor, dry_run=True)
    result = await service.backfill_documents("n_backfill_dry")

    relationships = (
        await async_session.execute(
            select(EntityRelationship).where(EntityRelationship.novel_id == "n_backfill_dry")
        )
    ).scalars().all()
    assert result["processed"] == 1
    assert result["created"] == 1
    assert result["dry_run"] is True
    assert relationships == []


@pytest.mark.asyncio
async def test_backfill_relationships_filters_low_confidence_edges(async_session):
    entity_repo = EntityRepository(async_session)
    await entity_repo.create("shihao", "character", "石昊", novel_id="n_backfill_conf")
    await entity_repo.create("yunxi", "character", "云曦", novel_id="n_backfill_conf")
    async_session.add(
        NovelDocument(
            id="doc-setting-conf",
            novel_id="n_backfill_conf",
            doc_type="concept",
            title="人物设定",
            content="石昊与云曦似有旧识。",
            version=1,
        )
    )
    await async_session.flush()
    extractor = AsyncMock(
        return_value=RelationshipExtractionResult(
            relationships=[
                ExtractedRelationship(
                    source_entity_name="石昊",
                    target_entity_name="云曦",
                    relation_type="关联",
                    evidence="石昊与云曦似有旧识。",
                    confidence=0.4,
                )
            ]
        )
    )

    service = RelationshipBackfillService(async_session, extractor=extractor, min_confidence=0.65)
    result = await service.backfill_documents("n_backfill_conf")

    assert result["created"] == 0
    assert result["skipped"][0]["reason"] == "below_min_confidence"


@pytest.mark.asyncio
async def test_backfill_relationships_batches_entity_sources(async_session):
    entity_repo = EntityRepository(async_session)
    await entity_repo.create("hanli", "character", "韩立", novel_id="n_backfill_batch")
    await entity_repo.create("nangong", "character", "南宫婉", novel_id="n_backfill_batch")
    await entity_repo.create("molong", "item", "墨蛟", novel_id="n_backfill_batch")
    for entity_id, name, text in (
        ("hanli", "韩立", "名称：韩立\nrelationships：南宫婉（道侣）"),
        ("nangong", "南宫婉", "名称：南宫婉\nbackground：与韩立在血色禁地合力击杀墨蛟"),
        ("molong", "墨蛟", "名称：墨蛟\ndescription：被韩立与南宫婉合力击杀"),
    ):
        entity = await entity_repo.get_by_id(entity_id)
        entity.search_document = text
    await async_session.flush()

    seen_source_refs = []
    seen_source_texts = []

    async def extractor(novel_id, source_text, source_ref, candidates):
        seen_source_refs.append(source_ref)
        seen_source_texts.append(source_text)
        return RelationshipExtractionResult(
            relationships=[
                ExtractedRelationship(
                    source_entity_name="韩立",
                    target_entity_name="南宫婉",
                    relation_type="道侣",
                    evidence="南宫婉（道侣）",
                    confidence=0.95,
                )
            ]
        )

    service = RelationshipBackfillService(async_session, extractor=extractor, batch_size=25)
    result = await service.backfill_entities("n_backfill_batch")

    assert result["processed"] == 3
    assert result["created"] == 1
    assert len(seen_source_refs) == 1
    assert seen_source_refs[0] == "entities_batch:1:3"
    assert "韩立" in seen_source_texts[0]
    assert "南宫婉" in seen_source_texts[0]
    assert "墨蛟" in seen_source_texts[0]


@pytest.mark.asyncio
async def test_backfill_relationships_batches_25_entity_sources_by_default(async_session):
    entity_repo = EntityRepository(async_session)
    for index in range(26):
        entity = await entity_repo.create(
            f"entity_{index}",
            "character",
            f"角色{index}",
            novel_id="n_backfill_default_batch",
        )
        entity.search_document = f"名称：角色{index}\nrelationships：角色0"
    await async_session.flush()

    seen_batch_sizes = []

    async def extractor(novel_id, source_text, source_ref, candidates):
        seen_batch_sizes.append(len(json.loads(source_text)))
        return RelationshipExtractionResult(relationships=[])

    service = RelationshipBackfillService(async_session, extractor=extractor)
    result = await service.backfill_entities("n_backfill_default_batch")

    assert result["processed"] == 26
    assert seen_batch_sizes == [25, 1]


@pytest.mark.asyncio
async def test_backfill_relationships_is_idempotent_per_source_ref_and_entity_pair(async_session):
    entity_repo = EntityRepository(async_session)
    await entity_repo.create("shihao", "character", "石昊", novel_id="n_backfill_idem")
    await entity_repo.create("yunxi", "character", "云曦", novel_id="n_backfill_idem")
    async_session.add(
        NovelDocument(
            id="doc-setting-idem",
            novel_id="n_backfill_idem",
            doc_type="concept",
            title="人物设定",
            content="石昊与云曦结为夫妻。",
            version=1,
        )
    )
    await async_session.flush()
    extractor = AsyncMock(
        side_effect=[
            RelationshipExtractionResult(
                relationships=[
                    ExtractedRelationship(
                        source_entity_name="石昊",
                        target_entity_name="云曦",
                        relation_type="妻子",
                        evidence="石昊与云曦结为夫妻。",
                        confidence=0.9,
                    )
                ]
            ),
            RelationshipExtractionResult(
                relationships=[
                    ExtractedRelationship(
                        source_entity_name="石昊",
                        target_entity_name="云曦",
                        relation_type="道侣",
                        evidence="石昊与云曦结为夫妻。",
                        confidence=0.9,
                    )
                ]
            ),
        ]
    )

    service = RelationshipBackfillService(async_session, extractor=extractor)
    await service.backfill_documents("n_backfill_idem")
    await service.backfill_documents("n_backfill_idem")

    relationships = (
        await async_session.execute(
            select(EntityRelationship).where(
                EntityRelationship.novel_id == "n_backfill_idem",
                EntityRelationship.is_active == True,
            )
        )
    ).scalars().all()
    assert len(relationships) == 1
    assert relationships[0].relation_type == "道侣"


@pytest.mark.asyncio
async def test_backfill_relationships_collapses_existing_same_source_duplicates(async_session):
    entity_repo = EntityRepository(async_session)
    source = await entity_repo.create("shihao", "character", "石昊", novel_id="n_backfill_dupes")
    target = await entity_repo.create("yunxi", "character", "云曦", novel_id="n_backfill_dupes")
    async_session.add_all(
        [
            EntityRelationship(
                source_id=source.id,
                target_id=target.id,
                relation_type="传功者",
                novel_id="n_backfill_dupes",
                meta={
                    "source": "relationship_backfill",
                    "source_ref": "剧情梗概:doc-1",
                    "confidence": 0.95,
                },
            ),
            EntityRelationship(
                source_id=source.id,
                target_id=target.id,
                relation_type="传功",
                novel_id="n_backfill_dupes",
                meta={
                    "source": "relationship_backfill",
                    "source_ref": "剧情梗概:doc-1",
                    "confidence": 0.95,
                },
            ),
        ]
    )
    await async_session.flush()

    service = RelationshipBackfillService(async_session)
    await service._collapse_existing_backfill_duplicates("n_backfill_dupes")

    relationships = (
        await async_session.execute(
            select(EntityRelationship).where(
                EntityRelationship.novel_id == "n_backfill_dupes",
                EntityRelationship.is_active == True,
            )
        )
    ).scalars().all()
    assert len(relationships) == 1
    assert relationships[0].relation_type == "传功"
