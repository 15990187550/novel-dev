import pytest

from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.db.models import Entity


@pytest.mark.asyncio
async def test_create_entity(async_session):
    repo = EntityRepository(async_session)
    entity = await repo.create("char_001", "character", "Lin Feng")
    assert entity.id == "char_001"
    assert entity.name == "Lin Feng"


@pytest.mark.asyncio
async def test_find_by_names(async_session):
    repo = EntityRepository(async_session)
    await repo.create("e1", "character", "林风")
    await repo.create("e2", "character", "苏雪")
    results = await repo.find_by_names(["林风", "苏雪"])
    assert len(results) == 2
    assert {r.name for r in results} == {"林风", "苏雪"}
