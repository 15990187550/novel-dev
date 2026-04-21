import pytest

from novel_dev.repositories.entity_group_repo import EntityGroupRepository
from novel_dev.repositories.entity_repo import EntityRepository


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
async def test_create_entity_initializes_classification_fields(async_session):
    repo = EntityRepository(async_session)
    entity = await repo.create("char_100", "character", "陆照", novel_id="novel_x")

    assert entity.system_category is None
    assert entity.system_group_id is None
    assert entity.manual_category is None
    assert entity.manual_group_id is None
    assert entity.classification_reason is None
    assert entity.classification_confidence is None
    assert entity.search_document is None
    assert entity.search_vector_embedding is None
    assert entity.system_needs_review is False


@pytest.mark.asyncio
async def test_list_entities_by_novel(async_session):
    repo = EntityRepository(async_session)
    await repo.create("e1", "character", "A", novel_id="n1")
    await repo.create("e2", "character", "B", novel_id="n1")
    await repo.create("e3", "character", "C", novel_id="n2")
    results = await repo.list_by_novel("n1")
    assert len(results) == 2
    assert {r.name for r in results} == {"A", "B"}


@pytest.mark.asyncio
async def test_entity_repo_rejects_manual_group_outside_manual_category(async_session):
    group_repo = EntityGroupRepository(async_session)
    entity_repo = EntityRepository(async_session)

    group = await group_repo.upsert(
        novel_id="novel_x",
        category="人物",
        group_name="人物",
        group_slug="people",
    )
    entity = await entity_repo.create("char_200", "character", "陆照", novel_id="novel_x")

    with pytest.raises(ValueError, match="manual_group must belong to manual_category"):
        await entity_repo.update_classification(
            entity.id,
            manual_category="势力",
            manual_group_id=group.id,
        )


@pytest.mark.asyncio
async def test_update_classification_clears_manual_group_when_category_changes(async_session):
    group_repo = EntityGroupRepository(async_session)
    entity_repo = EntityRepository(async_session)

    people_group = await group_repo.upsert(
        novel_id="novel_x",
        category="人物",
        group_name="人物",
        group_slug="people",
    )
    entity = await entity_repo.create("char_201", "character", "陆照", novel_id="novel_x")

    await entity_repo.update_classification(
        entity.id,
        manual_category="人物",
        manual_group_id=people_group.id,
    )

    updated = await entity_repo.update_classification(
        entity.id,
        manual_category="势力",
    )
    assert updated.manual_category == "势力"
    assert updated.manual_group_id is None

    await entity_repo.update_classification(
        entity.id,
        manual_category="人物",
        manual_group_id=people_group.id,
    )
    cleared = await entity_repo.update_classification(
        entity.id,
        manual_category=None,
    )
    assert cleared.manual_category is None
    assert cleared.manual_group_id is None


@pytest.mark.asyncio
async def test_update_classification_clears_system_group_when_category_changes(async_session):
    group_repo = EntityGroupRepository(async_session)
    entity_repo = EntityRepository(async_session)

    people_group = await group_repo.upsert(
        novel_id="novel_x",
        category="人物",
        group_name="人物",
        group_slug="people",
    )
    faction_group = await group_repo.upsert(
        novel_id="novel_x",
        category="势力",
        group_name="势力",
        group_slug="factions",
    )
    entity = await entity_repo.create("char_202", "character", "陆照", novel_id="novel_x")

    await entity_repo.update_classification(
        entity.id,
        system_category="人物",
        system_group_id=people_group.id,
    )

    updated = await entity_repo.update_classification(
        entity.id,
        system_category="势力",
    )
    assert updated.system_category == "势力"
    assert updated.system_group_id is None

    with pytest.raises(ValueError, match="system_group must belong to system_category"):
        await entity_repo.update_classification(
            entity.id,
            system_category="人物",
            system_group_id=faction_group.id,
        )
