from unittest.mock import AsyncMock

import pytest

from novel_dev.agents.context_agent import ContextAgent
from novel_dev.schemas.context import ChapterPlan, BeatPlan
from novel_dev.schemas.similar_document import SimilarDocument
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository


@pytest.mark.asyncio
async def test_similar_chapters_populated_via_embedding_service(async_session):
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=2,
        title="测试章节",
        target_word_count=3000,
        beats=[BeatPlan(summary="开场", target_mood="tense", key_entities=["林风"])],
    )
    await director.save_checkpoint(
        "n_test_ctx",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={"current_chapter_plan": chapter_plan.model_dump()},
        volume_id="vol_1",
        chapter_id="ch_2",
    )

    mock_embedding = AsyncMock()
    mock_embedding.search_similar_chapters.return_value = [
        SimilarDocument(
            doc_id="ch_1",
            doc_type="chapter",
            title="第一章",
            content_preview="第一章内容预览",
            similarity_score=0.88,
        )
    ]

    agent = ContextAgent(async_session, embedding_service=mock_embedding)
    context = await agent.assemble("n_test_ctx", "ch_2")

    assert len(context.similar_chapters) == 1
    assert context.similar_chapters[0].doc_id == "ch_1"
    assert context.similar_chapters[0].title == "第一章"
    mock_embedding.search_similar_chapters.assert_awaited_once_with(
        novel_id="n_test_ctx", query_text="测试章节\n开场", limit=2
    )


@pytest.mark.asyncio
async def test_similar_chapters_empty_when_no_embedding_service(async_session):
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=1,
        title="首章",
        target_word_count=3000,
        beats=[BeatPlan(summary="开场", target_mood="tense")],
    )
    await director.save_checkpoint(
        "n_test_no_emb",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={"current_chapter_plan": chapter_plan.model_dump()},
        volume_id="vol_1",
        chapter_id="ch_1",
    )

    agent = ContextAgent(async_session, embedding_service=None)
    context = await agent.assemble("n_test_no_emb", "ch_1")

    assert context.similar_chapters == []


@pytest.mark.asyncio
async def test_assemble_persists_beat_boundary_cards_in_checkpoint(async_session, monkeypatch):
    plan = ChapterPlan(
        chapter_number=1,
        title="边界测试",
        target_word_count=1600,
        beats=[
            BeatPlan(
                summary="陆照潜入药库寻找救命丹药",
                target_mood="紧张",
                key_entities=["陆照", "救命丹药"],
                foreshadowings_to_embed=["玉佩发热"],
            ),
            BeatPlan(summary="执事推门而入，陆照被迫藏起丹药", target_mood="压迫"),
        ],
    )
    await NovelStateRepository(async_session).save_checkpoint(
        "n_boundary_ctx",
        Phase.CONTEXT_PREPARATION.value,
        {"current_chapter_plan": plan.model_dump()},
        "vol_boundary",
        "ch_boundary",
    )
    await ChapterRepository(async_session).create(
        "ch_boundary",
        "vol_boundary",
        1,
        title="边界测试",
        novel_id="n_boundary_ctx",
    )

    async def fake_location_context(self, chapter_plan, novel_id):
        from novel_dev.schemas.context import LocationContext

        return LocationContext(current="药库", narrative="药香压着潮湿木架。")

    monkeypatch.setattr(ContextAgent, "_load_location_context", fake_location_context)

    context = await ContextAgent(async_session, embedding_service=None).assemble("n_boundary_ctx", "ch_boundary")
    state = await NovelStateRepository(async_session).get_state("n_boundary_ctx")
    cards = state.checkpoint_data["chapter_context"]["chapter_plan"]["beat_boundary_cards"]

    assert state.current_phase == Phase.DRAFTING.value
    assert len(context.chapter_plan.beat_boundary_cards) == 2
    assert len(cards) == 2
    assert cards[0]["beat_index"] == 0
    assert "陆照潜入药库寻找救命丹药" in cards[0]["must_cover"]
    assert "陆照" in cards[0]["allowed_materials"]
    assert "玉佩发热" in cards[0]["allowed_materials"]


@pytest.mark.asyncio
async def test_assemble_for_chapter_mutates_provided_checkpoint_with_boundary_cards(async_session, monkeypatch):
    plan = ChapterPlan(
        chapter_number=1,
        title="直接调用边界测试",
        target_word_count=1600,
        beats=[
            BeatPlan(
                summary="陆照潜入药库寻找救命丹药",
                target_mood="紧张",
                key_entities=["陆照"],
                foreshadowings_to_embed=["玉佩发热"],
            )
        ],
    )
    checkpoint = {"story_contract": {"protagonist_goal": "救妹妹"}}

    async def fake_location_context(self, chapter_plan, novel_id):
        from novel_dev.schemas.context import LocationContext

        return LocationContext(current="药库", narrative="药香压着潮湿木架。")

    monkeypatch.setattr(ContextAgent, "_load_location_context", fake_location_context)

    context = await ContextAgent(async_session, embedding_service=None).assemble_for_chapter(
        "n_boundary_direct",
        "ch_boundary_direct",
        plan,
        volume_id="vol_boundary_direct",
        checkpoint=checkpoint,
    )

    cards = checkpoint["chapter_context"]["chapter_plan"]["beat_boundary_cards"]
    assert context.chapter_plan.beat_boundary_cards[0].beat_index == 0
    assert cards[0]["beat_index"] == 0
    assert "陆照潜入药库寻找救命丹药" in cards[0]["must_cover"]
    assert "玉佩发热" in cards[0]["allowed_materials"]
