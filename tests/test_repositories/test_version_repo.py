import pytest

from novel_dev.repositories.version_repo import EntityVersionRepository
from novel_dev.repositories.entity_repo import EntityRepository


@pytest.mark.asyncio
async def test_create_version_and_get_latest(async_session):
    entity_repo = EntityRepository(async_session)
    await entity_repo.create("char_002", "character", "Zhang San")

    ver_repo = EntityVersionRepository(async_session)
    await ver_repo.create("char_002", 1, {"realm": "qi_refinement"}, chapter_id="ch_001")
    await ver_repo.create("char_002", 2, {"realm": "foundation_building"}, chapter_id="ch_002")

    latest = await ver_repo.get_latest("char_002")
    assert latest.state["realm"] == "foundation_building"
