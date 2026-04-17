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


@pytest.mark.asyncio
async def test_create_entity_with_novel_id(async_session):
    repo = EntityRepository(async_session)
    entity = await repo.create("char_002", "character", "Zhang San", novel_id="novel_a")
    assert entity.id == "char_002"
    assert entity.novel_id == "novel_a"


@pytest.mark.asyncio
async def test_list_entities_by_novel(async_session):
    repo = EntityRepository(async_session)
    await repo.create("e1", "character", "A", novel_id="n1")
    await repo.create("e2", "character", "B", novel_id="n1")
    await repo.create("e3", "character", "C", novel_id="n2")
    results = await repo.list_by_novel("n1")
    assert len(results) == 2
    assert {r.name for r in results} == {"A", "B"}
