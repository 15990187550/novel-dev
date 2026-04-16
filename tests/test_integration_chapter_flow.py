import pytest

from novel_dev.services.entity_service import EntityService
from novel_dev.services.chapter_service import ChapterService
from novel_dev.agents.director import NovelDirector, Phase


@pytest.mark.asyncio
async def test_full_chapter_flow(async_session):
    # Setup
    entity_svc = EntityService(async_session)
    chapter_svc = ChapterService(async_session, "/tmp/test_integration_output")
    director = NovelDirector(session=async_session)

    # 1. Create a character
    await entity_svc.create_entity("hero", "character", "Lin Feng", chapter_id="ch_1")

    # 2. Director saves checkpoint for drafting
    await director.save_checkpoint(
        "novel_demo",
        phase=Phase.DRAFTING,
        checkpoint_data={"volume_plan": "Hero ascends", "chapter_plan": "Breakthrough"},
        volume_id="vol_1",
        chapter_id="ch_1",
    )

    # 3. Create and complete chapter
    await chapter_svc.create("ch_1", "vol_1", 1, "Breakthrough")
    await chapter_svc.complete_chapter("novel_demo", "ch_1", "vol_1", "draft body", "polished body")

    # 4. Update entity state as if LibrarianAgent found a change
    await entity_svc.update_state("hero", {"name": "Lin Feng", "realm": "foundation_building"}, chapter_id="ch_1")

    # 5. Mark chapter flow complete
    await director.save_checkpoint(
        "novel_demo",
        phase=Phase.COMPLETED,
        checkpoint_data={},
        volume_id="vol_1",
        chapter_id="ch_1",
    )

    # Verify
    state = await director.resume("novel_demo")
    assert state.current_phase == Phase.COMPLETED.value

    hero_state = await entity_svc.get_latest_state("hero")
    assert hero_state["realm"] == "foundation_building"

    ch = await chapter_svc.get("ch_1")
    assert ch.status == "completed"
    assert ch.polished_text == "polished body"
