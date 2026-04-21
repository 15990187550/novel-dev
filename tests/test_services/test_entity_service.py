import pytest
from unittest.mock import AsyncMock

from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.services.entity_service import EntityService


@pytest.mark.asyncio
async def test_create_entity_and_update_state(async_session):
    svc = EntityService(async_session)
    entity = await svc.create_entity("char_003", "character", "Wang Wu", chapter_id="ch_001")
    assert entity.current_version == 1

    updated = await svc.update_state("char_003", {"realm": "golden_core"}, chapter_id="ch_002")
    assert updated.version == 2
    assert updated.state["realm"] == "golden_core"

    latest = await svc.get_latest_state("char_003")
    assert latest["realm"] == "golden_core"


@pytest.mark.asyncio
async def test_update_state_refreshes_search_index_and_classification(async_session):
    embedding_service = AsyncMock()
    embedding_service.index_entity = AsyncMock()
    embedding_service.index_entity_search = AsyncMock()
    entity_repo = EntityRepository(async_session)

    svc = EntityService(async_session, embedding_service)
    await svc.create_entity(
        "ent_001",
        "faction",
        "青云宗",
        novel_id="n1",
        initial_state={"description": "一个宗门势力"},
    )
    await svc.update_state(
        "ent_001",
        {"name": "青云宗", "description": "一个宗门势力", "notes": "新线索"},
        chapter_id="ch_002",
    )

    updated = await entity_repo.get_by_id("ent_001")
    assert updated.system_category == "势力"
    assert updated.system_needs_review is False
    assert embedding_service.index_entity.await_count >= 2
    assert embedding_service.index_entity_search.await_count >= 2
