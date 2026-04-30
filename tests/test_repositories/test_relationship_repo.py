import pytest
from sqlalchemy import select

from novel_dev.db.models import Entity, EntityRelationship
from novel_dev.repositories.relationship_repo import RelationshipRepository


@pytest.mark.asyncio
async def test_upsert_collapses_duplicate_active_relationship_pairs(async_session):
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
        relation_type="ally",
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

    assert relationship.relation_type == "ally"
    assert len(active_relationships) == 1
    assert active_relationships[0].id == relationship.id
