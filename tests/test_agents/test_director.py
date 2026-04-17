import pytest

from novel_dev.agents.director import NovelDirector, Phase, VALID_TRANSITIONS


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


def test_brainstorming_phase_exists():
    assert Phase.BRAINSTORMING.value == "brainstorming"


def test_valid_transitions_include_brainstorming():
    assert Phase.VOLUME_PLANNING in VALID_TRANSITIONS
    assert Phase.BRAINSTORMING in VALID_TRANSITIONS[Phase.VOLUME_PLANNING]
    assert Phase.VOLUME_PLANNING in VALID_TRANSITIONS[Phase.BRAINSTORMING]


def test_can_transition_brainstorming():
    from novel_dev.agents.director import NovelDirector
    director = NovelDirector(session=None)
    assert director.can_transition(Phase.BRAINSTORMING, Phase.VOLUME_PLANNING) is True
    assert director.can_transition(Phase.VOLUME_PLANNING, Phase.BRAINSTORMING) is True
    assert director.can_transition(Phase.BRAINSTORMING, Phase.DRAFTING) is False
