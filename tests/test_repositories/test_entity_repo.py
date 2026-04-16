import pytest

from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.db.models import Entity


@pytest.mark.asyncio
async def test_create_entity(async_session):
    repo = EntityRepository(async_session)
    entity = await repo.create("char_001", "character", "Lin Feng")
    assert entity.id == "char_001"
    assert entity.name == "Lin Feng"
