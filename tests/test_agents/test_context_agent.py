import pytest

from novel_dev.agents.context_agent import ContextAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.version_repo import EntityVersionRepository
from novel_dev.repositories.timeline_repo import TimelineRepository
from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.schemas.context import ChapterPlan, BeatPlan


@pytest.mark.asyncio
async def test_assemble_context_success(async_session):
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=1,
        title="Test Chapter",
        target_word_count=3000,
        beats=[BeatPlan(summary="Beat 1", target_mood="tense", key_entities=["林风"])],
    )
    await director.save_checkpoint(
        "novel_test",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={"current_chapter_plan": chapter_plan.model_dump()},
        volume_id="vol_1",
        chapter_id="ch_1",
    )

    await EntityRepository(async_session).create("ent_1", "character", "林风")
    await EntityVersionRepository(async_session).create("ent_1", 1, {"realm": "炼气"}, chapter_id="ch_1")
    await TimelineRepository(async_session).create(1, "event 1")
    await ForeshadowingRepository(async_session).create("fs_1", "玉佩发光", 相关人物_ids=["ent_1"])
    await DocumentRepository(async_session).create("doc_1", "novel_test", "style_profile", "Style", '{"guide": "fast"}')
    await DocumentRepository(async_session).create("doc_2", "novel_test", "worldview", "Worldview", "天玄大陆")
    await ChapterRepository(async_session).create("ch_1", "vol_1", 1, "Test Chapter")

    agent = ContextAgent(async_session)
    context = await agent.assemble("novel_test", "ch_1")

    assert context.chapter_plan.title == "Test Chapter"
    assert len(context.active_entities) == 1
    assert context.active_entities[0].name == "林风"
    assert len(context.pending_foreshadowings) == 1
    assert context.worldview_summary == "天玄大陆"

    state = await director.resume("novel_test")
    assert state.current_phase == Phase.DRAFTING.value


@pytest.mark.asyncio
async def test_assemble_missing_plan(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_no_plan",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={},
        volume_id="vol_1",
        chapter_id="ch_1",
    )
    agent = ContextAgent(async_session)
    with pytest.raises(ValueError, match="current_chapter_plan missing"):
        await agent.assemble("novel_no_plan", "ch_1")


@pytest.mark.asyncio
async def test_assemble_wrong_phase(async_session):
    director = NovelDirector(session=async_session)
    plan = ChapterPlan(chapter_number=1, title="T", target_word_count=100, beats=[])
    await director.save_checkpoint(
        "novel_wrong_phase",
        phase=Phase.DRAFTING,
        checkpoint_data={"current_chapter_plan": plan.model_dump()},
        volume_id="vol_1",
        chapter_id="ch_1",
    )
    agent = ContextAgent(async_session)
    with pytest.raises(ValueError, match="Cannot prepare context"):
        await agent.assemble("novel_wrong_phase", "ch_1")
