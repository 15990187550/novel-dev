import pytest

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
