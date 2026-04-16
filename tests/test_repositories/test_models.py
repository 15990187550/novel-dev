import pytest

from novel_dev.db.models import Entity, EntityVersion, Chapter, NovelState, PendingExtraction


def test_entity_table_name():
    assert Entity.__tablename__ == "entities"


def test_version_table_name():
    assert EntityVersion.__tablename__ == "entity_versions"


def test_chapter_table_name():
    assert Chapter.__tablename__ == "chapters"


def test_novel_state_table_name():
    assert NovelState.__tablename__ == "novel_state"


@pytest.mark.asyncio
async def test_pending_extraction_model(async_session):
    pe = PendingExtraction(
        id="pe_1",
        novel_id="n1",
        extraction_type="setting",
        status="pending",
        raw_result={"worldview": "test"},
        proposed_entities=[{"type": "character", "name": "Lin Feng"}],
    )
    async_session.add(pe)
    await async_session.flush()
    result = await async_session.get(PendingExtraction, "pe_1")
    assert result.novel_id == "n1"
    assert result.status == "pending"
