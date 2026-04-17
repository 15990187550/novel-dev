import pytest

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.outline import SynopsisData
from novel_dev.repositories.document_repo import DocumentRepository


@pytest.mark.asyncio
async def test_valid_transitions_completed_to_volume_planning(async_session):
    director = NovelDirector(session=async_session)
    assert director.can_transition(Phase.COMPLETED, Phase.VOLUME_PLANNING) is True


@pytest.mark.asyncio
async def test_advance_volume_planning_to_context_preparation(async_session, mock_llm_factory):
    director = NovelDirector(session=async_session)
    synopsis = SynopsisData(
        title="T",
        logline="L",
        core_conflict="C",
        estimated_volumes=1,
        estimated_total_chapters=1,
        estimated_total_words=3000,
    )
    await DocumentRepository(async_session).create(
        "d1", "n_dir_vol", "worldview", "WV", "大陆"
    )
    await director.save_checkpoint(
        "n_dir_vol",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={"synopsis_data": synopsis.model_dump()},
        volume_id=None,
        chapter_id=None,
    )

    state = await director.advance("n_dir_vol")
    assert state.current_phase == Phase.CONTEXT_PREPARATION.value
    assert "current_volume_plan" in state.checkpoint_data


@pytest.mark.asyncio
async def test_advance_drafting_missing_draft(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_unsup",
        phase=Phase.DRAFTING,
        checkpoint_data={},
        volume_id="v1",
        chapter_id="c1",
    )
    with pytest.raises(ValueError, match="Chapter draft not generated"):
        await director.advance("n_unsup")
