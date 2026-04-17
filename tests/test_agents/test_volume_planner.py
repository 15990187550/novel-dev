from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.volume_planner import VolumePlannerAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.outline import SynopsisData, VolumeScoreResult, VolumePlan, VolumeBeat
from novel_dev.schemas.context import BeatPlan
import uuid
from novel_dev.repositories.novel_state_repo import NovelStateRepository
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

    initial_plan = VolumePlan(
        volume_id="vol_1",
        volume_number=1,
        title="第一卷",
        summary="卷总述",
        total_chapters=3,
        estimated_total_words=9000,
        chapters=[
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
        ],
    )

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
        LLMResponse(text=initial_plan.model_dump_json()),
        LLMResponse(text=score_result.model_dump_json()),
    ]

    with patch("novel_dev.agents.volume_planner.llm_factory") as mock_factory, \
         patch("novel_dev.agents._llm_helpers.llm_factory") as mock_helpers_factory:
        mock_factory.get.return_value = mock_client
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

    async def _mock_generate_score(plan):
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

    async def _mock_revise_volume_plan(plan, feedback):
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
