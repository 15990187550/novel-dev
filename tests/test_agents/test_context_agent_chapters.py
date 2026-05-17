from unittest.mock import AsyncMock

import pytest

from novel_dev.agents.context_agent import ContextAgent
from novel_dev.schemas.context import ChapterPlan, BeatPlan, EntityState, LocationContext
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
        beats=[BeatPlan(
            summary="林风为查清学院密令进入学院，却被门卫盘问；他必须在隐藏身份和交出信物之间选择，失败会暴露目标，结尾听见追兵逼近。",
            target_mood="tense",
            key_entities=["林风"],
        )],
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
        novel_id="n_test_ctx",
        query_text="测试章节\n林风为查清学院密令进入学院，却被门卫盘问；他必须在隐藏身份和交出信物之间选择，失败会暴露目标，结尾听见追兵逼近。",
        limit=2,
    )


@pytest.mark.asyncio
async def test_similar_chapters_empty_when_no_embedding_service(async_session):
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=1,
        title="首章",
        target_word_count=3000,
        beats=[BeatPlan(
            summary="主角为查清学院密令进入学院，却被门卫盘问；他必须在隐藏身份和交出信物之间选择，失败会暴露目标，结尾听见追兵逼近。",
            target_mood="tense",
        )],
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
                summary="陆照为救妹妹潜入药库寻找救命丹药，却听见执事逼近；他必须在继续搜药和立刻撤离之间选择，失败会暴露玉佩，结尾玉佩发热。",
                target_mood="紧张",
                key_entities=["陆照", "救命丹药"],
                foreshadowings_to_embed=["玉佩发热"],
            ),
            BeatPlan(summary="执事推门而入，陆照被迫藏起丹药；他必须在交出丹药和引开执事之间选择，失败会失去救命药，结尾听见追兵逼近。", target_mood="压迫"),
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
    assert "陆照为救妹妹潜入药库寻找救命丹药" in cards[0]["must_cover"][0]
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
                summary="陆照为救妹妹潜入药库寻找救命丹药，却听见执事逼近；他必须在继续搜药和立刻撤离之间选择，失败会暴露玉佩，结尾玉佩发热。",
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
    assert checkpoint["chapter_context"]["chapter_plan"]["quality_preflight_report"]["status"] in {"block", "warn", "pass"}
    assert context.writing_cards[0].readability_contract
    assert cards[0]["beat_index"] == 0
    assert "陆照为救妹妹潜入药库寻找救命丹药" in cards[0]["must_cover"][0]
    assert "玉佩发热" in cards[0]["allowed_materials"]


@pytest.mark.asyncio
async def test_assemble_blocks_when_quality_preflight_blocks(async_session, monkeypatch):
    plan = ChapterPlan(
        chapter_number=1,
        title="阻断测试",
        target_word_count=1200,
        beats=[BeatPlan(summary="陆照醒来了解世界。", target_mood="平静", key_entities=["陆照"])],
    )
    checkpoint = {"current_chapter_plan": plan.model_dump()}

    async def fake_location_context(self, chapter_plan, novel_id):
        from novel_dev.schemas.context import LocationContext

        return LocationContext(current="山门", narrative="山门晨雾未散。")

    monkeypatch.setattr(ContextAgent, "_load_location_context", fake_location_context)

    with pytest.raises(ValueError, match="quality preflight blocked"):
        await ContextAgent(async_session, embedding_service=None).assemble_for_chapter(
            "n_boundary_block",
            "ch_boundary_block",
            plan,
            volume_id="vol_boundary_block",
            checkpoint=checkpoint,
        )

    assert checkpoint["chapter_quality_preflight"]["status"] == "block"


@pytest.mark.asyncio
async def test_assemble_blocks_weak_plan_before_semantic_retrieval(async_session):
    plan = ChapterPlan(
        chapter_number=1,
        title="早阻断测试",
        target_word_count=1200,
        beats=[BeatPlan(summary="陆照醒来了解世界。", target_mood="平静", key_entities=["陆照"])],
    )
    checkpoint = {"current_chapter_plan": plan.model_dump()}
    mock_embedding = AsyncMock()

    with pytest.raises(ValueError, match="quality preflight blocked"):
        await ContextAgent(async_session, embedding_service=mock_embedding).assemble_for_chapter(
            "n_boundary_block_early",
            "ch_boundary_block_early",
            plan,
            volume_id="vol_boundary_block_early",
            checkpoint=checkpoint,
        )

    assert checkpoint["chapter_quality_preflight"]["status"] == "block"
    mock_embedding.search_similar_entities.assert_not_awaited()
    mock_embedding.search_similar.assert_not_awaited()
    mock_embedding.search_similar_chapters.assert_not_awaited()


@pytest.mark.asyncio
async def test_assemble_persists_quality_preflight_block_for_resume(async_session):
    plan = ChapterPlan(
        chapter_number=1,
        title="可恢复阻断",
        target_word_count=1200,
        beats=[BeatPlan(summary="陆照醒来了解世界。", target_mood="平静", key_entities=["陆照"])],
    )
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_preflight_resume",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={"current_chapter_plan": plan.model_dump()},
        volume_id="vol_preflight_resume",
        chapter_id="ch_preflight_resume",
    )
    await async_session.commit()

    with pytest.raises(ValueError, match="quality preflight blocked"):
        await ContextAgent(async_session, embedding_service=None).assemble(
            "n_preflight_resume",
            "ch_preflight_resume",
        )

    state = await director.resume("n_preflight_resume")
    assert state.current_phase == Phase.CONTEXT_PREPARATION.value
    assert state.current_chapter_id == "ch_preflight_resume"
    assert state.checkpoint_data["context_failure_stage"] == "quality_preflight"
    assert state.checkpoint_data["chapter_quality_preflight"]["status"] == "block"


def test_context_guardrails_keep_location_and_entity_state_before_preflight_overflow(async_session):
    plan = ChapterPlan(
        chapter_number=1,
        title="截断测试",
        target_word_count=1200,
        beats=[
            BeatPlan(
                summary="陆照为查玉佩线索潜入药库，却被执事盘问；他必须在追问和隐忍之间选择，失败会暴露行踪，结尾听见追兵逼近。",
                target_mood="紧张",
                key_entities=["陆照"],
            )
        ],
        quality_preflight_report={
            "canonical_constraints": [f"约束{i}: 内容" for i in range(12)],
            "continuity_requirements": [f"连续{i}: 内容" for i in range(12)],
        },
    )

    guardrails = ContextAgent(async_session)._build_guardrails(
        plan,
        [
            EntityState(
                entity_id="ent_luzhao",
                name="陆照",
                type="character",
                current_state="重伤但仍握有玉佩",
            )
        ],
        LocationContext(current="药库"),
        {"current_time_tick": 7},
    )

    assert any("当前主要场景" in item for item in guardrails)
    assert any("当前时间 tick" in item for item in guardrails)
    assert any("陆照 的当前状态必须延续" in item for item in guardrails)
