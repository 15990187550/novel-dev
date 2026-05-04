import pytest
from sqlalchemy import select

from novel_dev.db.models import Entity, EntityRelationship
from novel_dev.repositories.relationship_repo import RelationshipRepository


@pytest.mark.asyncio
async def test_upsert_collapses_duplicate_active_relationships_by_type(async_session):
    async_session.add_all([
        Entity(id="source", type="character", name="Source", novel_id="n_rel"),
        Entity(id="target", type="character", name="Target", novel_id="n_rel"),
        EntityRelationship(
            source_id="source",
            target_id="target",
            relation_type="trust",
            novel_id="n_rel",
            is_active=True,
        ),
        EntityRelationship(
            source_id="source",
            target_id="target",
            relation_type="trust",
            novel_id="n_rel",
            is_active=True,
        ),
        EntityRelationship(
            source_id="source",
            target_id="target",
            relation_type="debt",
            novel_id="n_rel",
            is_active=True,
        ),
    ])
    await async_session.flush()

    repo = RelationshipRepository(async_session)
    relationship = await repo.upsert(
        source_id="source",
        target_id="target",
        relation_type="trust",
        novel_id="n_rel",
    )

    result = await async_session.execute(
        select(EntityRelationship).where(
            EntityRelationship.source_id == "source",
            EntityRelationship.target_id == "target",
            EntityRelationship.novel_id == "n_rel",
            EntityRelationship.is_active == True,
        )
    )
    active_relationships = result.scalars().all()

    assert relationship.relation_type == "trust"
    assert [rel.relation_type for rel in active_relationships] == ["trust", "debt"]
    assert active_relationships[0].id == relationship.id


@pytest.mark.asyncio
async def test_upsert_preserves_multiple_relationship_types_for_same_pair(async_session):
    async_session.add_all([
        Entity(id="source_multi", type="character", name="Source", novel_id="n_rel_multi"),
        Entity(id="target_multi", type="character", name="Target", novel_id="n_rel_multi"),
    ])
    await async_session.flush()

    repo = RelationshipRepository(async_session)
    await repo.upsert(
        source_id="source_multi",
        target_id="target_multi",
        relation_type="师兄弟",
        novel_id="n_rel_multi",
    )
    await repo.upsert(
        source_id="source_multi",
        target_id="target_multi",
        relation_type="宿敌",
        novel_id="n_rel_multi",
    )

    result = await async_session.execute(
        select(EntityRelationship).where(
            EntityRelationship.source_id == "source_multi",
            EntityRelationship.target_id == "target_multi",
            EntityRelationship.novel_id == "n_rel_multi",
            EntityRelationship.is_active == True,
        ).order_by(EntityRelationship.id)
    )
    active_relationships = result.scalars().all()

    assert [rel.relation_type for rel in active_relationships] == ["师兄弟", "宿敌"]
