import pytest

from novel_dev.repositories.entity_group_repo import EntityGroupRepository


@pytest.mark.asyncio
async def test_entity_group_repo_upserts_with_novel_scope(async_session):
    repo = EntityGroupRepository(async_session)

    first = await repo.upsert(
        novel_id="novel_a",
        category="人物",
        group_name="人物",
        group_slug="people",
        source="system",
        sort_order=1,
    )
    second = await repo.upsert(
        novel_id="novel_a",
        category="人物",
        group_name="角色",
        group_slug="people",
        source="manual",
        sort_order=9,
    )

    assert second.id == first.id
    assert second.group_name == "角色"
    assert second.source == "manual"
    assert second.sort_order == 9


@pytest.mark.asyncio
async def test_entity_group_repo_keeps_scopes_separate(async_session):
    repo = EntityGroupRepository(async_session)

    novel_a_people = await repo.upsert(
        novel_id="novel_a",
        category="人物",
        group_name="人物A",
        group_slug="shared",
    )
    novel_b_people = await repo.upsert(
        novel_id="novel_b",
        category="人物",
        group_name="人物B",
        group_slug="shared",
    )
    novel_a_factions = await repo.upsert(
        novel_id="novel_a",
        category="势力",
        group_name="势力A",
        group_slug="shared",
    )

    assert novel_a_people.id != novel_b_people.id
    assert novel_a_people.id != novel_a_factions.id
    assert novel_b_people.id != novel_a_factions.id
    assert novel_a_people.group_name == "人物A"
    assert novel_b_people.group_name == "人物B"
    assert novel_a_factions.group_name == "势力A"
