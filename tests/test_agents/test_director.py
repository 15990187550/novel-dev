import pytest

from novel_dev.agents.director import NovelDirector, Phase


def test_phase_transition():
    director = NovelDirector()
    assert director.can_transition(Phase.CONTEXT_PREPARATION, Phase.DRAFTING)
    assert not director.can_transition(Phase.DRAFTING, Phase.CONTEXT_PREPARATION)


@pytest.mark.asyncio
async def test_save_and_resume(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_1",
        phase=Phase.DRAFTING,
        checkpoint_data={"chapter_plan": "plan"},
        volume_id="vol_1",
        chapter_id="ch_1",
    )
    state = await director.resume("novel_1")
    assert state.current_phase == Phase.DRAFTING.value
