import pytest

from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
from novel_dev.repositories.relationship_repo import RelationshipRepository


@pytest.mark.asyncio
async def test_foreshadowing_lifecycle(async_session):
    repo = ForeshadowingRepository(async_session)
    fs = await repo.create(
        fs_id="fs_001",
        content="A jade pendant",
        埋下_chapter_id="ch_001",
        回收条件={"必要条件": ["筑基期"], "预计回收卷": "vol_2"},
    )
    assert fs.回收状态 == "pending"
    await repo.mark_recovered("fs_001", "ch_010", "evt_010")
    recovered = await repo.get_by_id("fs_001")
    assert recovered.回收状态 == "recovered"


@pytest.mark.asyncio
async def test_relationship_crud(async_session):
    from novel_dev.repositories.entity_repo import EntityRepository
    e_repo = EntityRepository(async_session)
    await e_repo.create("m_1", "character", "Master")
    await e_repo.create("d_1", "character", "Disciple")

    r_repo = RelationshipRepository(async_session)
    rel = await r_repo.create("m_1", "d_1", "master_of", chapter_id="ch_001")
    assert rel.relation_type == "master_of"
