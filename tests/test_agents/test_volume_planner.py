from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.volume_planner import VolumePlannerAgent, VolumePlanBlueprint
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.outline import SynopsisData, VolumeScoreResult, VolumePlan, VolumeBeat
from novel_dev.schemas.context import BeatPlan
import uuid
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.llm.models import LLMResponse


@pytest.mark.asyncio
async def test_plan_volume_success(async_session):
    director = NovelDirector(session=async_session)
    synopsis = SynopsisData(
        title="Test",
        logline="Logline",
        core_conflict="Conflict",
        estimated_volumes=1,
        estimated_total_chapters=3,
        estimated_total_words=9000,
    )
    await director.save_checkpoint(
        "n_plan",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={"synopsis_data": synopsis.model_dump()},
        volume_id=None,
        chapter_id=None,
    )

    blueprint = VolumePlanBlueprint(
        volume_id="vol_1",
        volume_number=1,
        title="第一卷",
        summary="卷总述",
        total_chapters=3,
        estimated_total_words=9000,
        chapters=[
            {
                "chapter_number": 1,
                "title": "第一章",
                "summary": "第一章剧情",
            },
            {
                "chapter_number": 2,
                "title": "第二章",
                "summary": "第二章剧情",
            },
            {
                "chapter_number": 3,
                "title": "第三章",
                "summary": "第三章剧情",
            },
        ],
    )
    chapter_batch = [
        VolumeBeat(
            chapter_id=str(uuid.uuid4()),
            chapter_number=1,
            title="第一章",
            summary="第一章剧情",
            target_word_count=3000,
            target_mood="tense",
            beats=[BeatPlan(summary="B1", target_mood="tense")],
        ),
        VolumeBeat(
            chapter_id=str(uuid.uuid4()),
            chapter_number=2,
            title="第二章",
            summary="第二章剧情",
            target_word_count=3000,
            target_mood="tense",
            beats=[BeatPlan(summary="B2", target_mood="tense")],
        ),
        VolumeBeat(
            chapter_id=str(uuid.uuid4()),
            chapter_number=3,
            title="第三章",
            summary="第三章剧情",
            target_word_count=3000,
            target_mood="tense",
            beats=[BeatPlan(summary="B3", target_mood="tense")],
        ),
    ]

    score_result = VolumeScoreResult(
        overall=88,
        outline_fidelity=88,
        character_plot_alignment=88,
        hook_distribution=88,
        foreshadowing_management=88,
        chapter_hooks=88,
        page_turning=88,
        summary_feedback="good",
    )
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=blueprint.model_dump_json()),
        LLMResponse(text=f"[{','.join(chapter.model_dump_json() for chapter in chapter_batch)}]"),
        LLMResponse(text=score_result.model_dump_json()),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_helpers_factory:
        mock_helpers_factory.get.return_value = mock_client
        agent = VolumePlannerAgent(async_session)
        plan = await agent.plan("n_plan", volume_number=1)

    assert plan.volume_id == "vol_1"
    assert len(plan.chapters) == 3

    state = await director.resume("n_plan")
    assert state.current_phase == Phase.CONTEXT_PREPARATION.value
    assert "current_volume_plan" in state.checkpoint_data
    assert "current_chapter_plan" in state.checkpoint_data

    docs = await DocumentRepository(async_session).get_by_type("n_plan", "volume_plan")
    assert len(docs) == 1
    assert docs[0].doc_type == "volume_plan"


@pytest.mark.asyncio
async def test_plan_volume_large_outline_skips_full_revise(async_session):
    director = NovelDirector(session=async_session)
    synopsis = SynopsisData(
        title="大长篇",
        logline="长篇升级之路",
        core_conflict="主角与幕后黑手对抗",
        estimated_volumes=26,
        estimated_total_chapters=1300,
        estimated_total_words=3900000,
    )
    await director.save_checkpoint(
        "n_large_skip",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={"synopsis_data": synopsis.model_dump()},
        volume_id=None,
        chapter_id=None,
    )

    chapters = [
        VolumeBeat(
            chapter_id=f"ch_{index}",
            chapter_number=index,
            title=f"第{index}章",
            summary=f"第{index}章剧情",
            target_word_count=3000,
            target_mood="tense",
            beats=[BeatPlan(summary=f"B{index}", target_mood="tense")],
        )
        for index in range(1, 21)
    ]
    large_plan = VolumePlan(
        volume_id="vol_1",
        volume_number=1,
        title="第一卷",
        summary="卷总述",
        total_chapters=20,
        estimated_total_words=60000,
        chapters=chapters,
    )
    agent = VolumePlannerAgent(async_session)
    agent._generate_volume_plan = AsyncMock(return_value=large_plan)
    agent._generate_score = AsyncMock(return_value=VolumeScoreResult(
        overall=60,
        outline_fidelity=80,
        character_plot_alignment=60,
        hook_distribution=60,
        foreshadowing_management=80,
        chapter_hooks=70,
        page_turning=65,
        summary_feedback="需要继续细化",
    ))
    agent._revise_volume_plan = AsyncMock(side_effect=AssertionError("large plan should not trigger full revise"))

    plan = await agent.plan("n_large_skip", volume_number=1)

    assert plan.total_chapters == 20
    agent._revise_volume_plan.assert_not_called()


@pytest.mark.asyncio
async def test_generate_volume_plan_batches_large_projects(async_session):
    agent = VolumePlannerAgent(async_session)
    synopsis = SynopsisData(
        title="道经照诸天",
        logline="陆照在诸天万界争夺超脱路径。",
        core_conflict="陆照 vs 末劫幕后布局者",
        estimated_volumes=26,
        estimated_total_chapters=1300,
        estimated_total_words=3900000,
    )

    blueprint = VolumePlanBlueprint(
        volume_id="vol_1",
        volume_number=1,
        title="第一卷",
        summary="卷总述",
        total_chapters=10,
        estimated_total_words=30000,
        chapters=[
            {"chapter_number": index, "title": f"第{index}章", "summary": f"第{index}章摘要"}
            for index in range(1, 11)
        ],
    )
    first_batch = [
        VolumeBeat(
            chapter_id=f"ch_{index}",
            chapter_number=index,
            title=f"第{index}章",
            summary=f"第{index}章剧情",
            target_word_count=3000,
            target_mood="tense",
            beats=[BeatPlan(summary=f"B{index}", target_mood="tense")],
        )
        for index in range(1, 9)
    ]
    second_batch = [
        VolumeBeat(
            chapter_id=f"ch_{index}",
            chapter_number=index,
            title=f"第{index}章",
            summary=f"第{index}章剧情",
            target_word_count=3000,
            target_mood="tense",
            beats=[BeatPlan(summary=f"B{index}", target_mood="tense")],
        )
        for index in range(9, 11)
    ]

    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=blueprint.model_dump_json()),
        LLMResponse(text=f"[{','.join(chapter.model_dump_json() for chapter in first_batch)}]"),
        LLMResponse(text=f"[{','.join(chapter.model_dump_json() for chapter in second_batch)}]"),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        plan = await agent._generate_volume_plan(synopsis, 1, novel_id="n_large_batches")

    assert len(plan.chapters) == 10
    assert mock_client.acomplete.await_count == 3


@pytest.mark.asyncio
async def test_generate_volume_plan_prompt_limits_output_scale_for_large_projects(async_session):
    agent = VolumePlannerAgent(async_session)
    synopsis = SynopsisData(
        title="道经照诸天",
        logline="陆照在诸天万界争夺超脱路径。",
        core_conflict="陆照 vs 末劫幕后布局者",
        estimated_volumes=26,
        estimated_total_chapters=1300,
        estimated_total_words=3900000,
    )

    blueprint = VolumePlanBlueprint(
        volume_id="vol_1",
        volume_number=1,
        title="第一卷",
        summary="卷总述",
        total_chapters=20,
        estimated_total_words=60000,
        chapters=[
            {"chapter_number": index, "title": f"第{index}章", "summary": f"第{index}章摘要"}
            for index in range(1, 9)
        ],
    )
    expanded_batch = [
        VolumeBeat(
            chapter_id="ch_1",
            chapter_number=1,
            title="第一章",
            summary="第一章剧情",
            target_word_count=3000,
            target_mood="tense",
            beats=[BeatPlan(summary="B1", target_mood="tense")],
        ),
    ]
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=blueprint.model_dump_json()),
        LLMResponse(text=f"[{','.join(chapter.model_dump_json() for chapter in expanded_batch)}]"),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        await agent._generate_volume_plan(synopsis, 1, novel_id="n_large")

    first_prompt = mock_client.acomplete.await_args_list[0].args[0][0].content
    second_prompt = mock_client.acomplete.await_args_list[1].args[0][0].content
    assert "total_chapters 必须控制在 20-36 章之间" in first_prompt
    assert "不要试图一次覆盖整部小说的全部章节" in first_prompt
    assert "只返回合法 JSON 数组" in second_prompt
    assert "chapter_id 使用 ch_<chapter_number>" in second_prompt


@pytest.mark.asyncio
async def test_plan_volume_missing_synopsis(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_no_syn",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )
    agent = VolumePlannerAgent(async_session)
    with pytest.raises(ValueError, match="synopsis_data missing"):
        await agent.plan("n_no_syn")


@pytest.mark.asyncio
async def test_plan_volume_max_attempts(async_session):
    director = NovelDirector(session=async_session)
    synopsis = SynopsisData(
        title="Test",
        logline="Logline",
        core_conflict="Conflict",
        estimated_volumes=1,
        estimated_total_chapters=1,
        estimated_total_words=3000,
    )
    await director.save_checkpoint(
        "n_max",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={"synopsis_data": synopsis.model_dump(), "volume_plan_attempt_count": 2},
        volume_id=None,
        chapter_id=None,
    )

    agent = VolumePlannerAgent(async_session)

    async def _mock_generate_score(plan, novel_id=""):
        return VolumeScoreResult(
            overall=50,
            outline_fidelity=50,
            character_plot_alignment=50,
            hook_distribution=50,
            foreshadowing_management=50,
            chapter_hooks=50,
            page_turning=50,
            summary_feedback="too weak",
        )

    async def _mock_revise_volume_plan(plan, feedback, plan_context="", novel_id=""):
        return plan

    agent._generate_score = _mock_generate_score
    agent._revise_volume_plan = _mock_revise_volume_plan

    with pytest.raises(RuntimeError, match="Max volume plan attempts exceeded"):
        await agent.plan("n_max")

    state = await director.resume("n_max")
    assert state.current_phase == Phase.VOLUME_PLANNING.value
    assert state.checkpoint_data["volume_plan_attempt_count"] == 3


@pytest.mark.asyncio
async def test_extract_chapter_plan_merges_foreshadowings(async_session):
    from novel_dev.schemas.context import BeatPlan
    from novel_dev.schemas.outline import VolumeBeat

    agent = VolumePlannerAgent(async_session)
    vb = VolumeBeat(
        chapter_id="ch_1",
        chapter_number=1,
        title="T",
        summary="S",
        target_word_count=100,
        target_mood="tense",
        foreshadowings_to_embed=["fs_1"],
        beats=[BeatPlan(summary="B1", target_mood="dark")],
    )
    cp = agent._extract_chapter_plan(vb)
    assert cp["beats"][0]["foreshadowings_to_embed"] == ["fs_1"]

