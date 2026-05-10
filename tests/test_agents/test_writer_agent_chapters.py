from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.writer_agent import WriterAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.context import ChapterContext, ChapterPlan, BeatPlan, LocationContext
from novel_dev.schemas.similar_document import SimilarDocument
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.llm.models import LLMResponse


@pytest.mark.asyncio
async def test_multi_message_prompt_structure(async_session):
    """Verify WriterAgent uses system + user messages (not single message dump)."""
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=1,
        title="Test",
        target_word_count=2000,
        beats=[BeatPlan(summary="开场", target_mood="压抑")],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={"style_guide": "简洁有力"},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[],
        similar_chapters=[],
    )
    await director.save_checkpoint(
        "novel_test_multi",
        phase=Phase.DRAFTING,
        checkpoint_data={"chapter_context": context.model_dump()},
        volume_id="vol_1",
        chapter_id="ch_multi",
    )
    await ChapterRepository(async_session).create("ch_multi", "vol_1", 1, "Test")

    captured_messages = []

    def capture_prompt(agent, task=None):
        mock = AsyncMock()

        async def acomplete(messages, config=None):
            captured_messages.append(messages)
            return LLMResponse(
                text="这是一个很长的节拍正文内容，字数足够多，情节跌宕起伏，引人入胜，令人难以忘怀。"
            )

        mock.acomplete.side_effect = acomplete
        return mock

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.side_effect = capture_prompt
        mock_factory._resolve_config.return_value = None
        agent = WriterAgent(async_session)
        await agent.write("novel_test_multi", context, "ch_multi")

    # generate_beat call should have system + user messages
    beat_messages = captured_messages[0]
    assert len(beat_messages) >= 2
    assert beat_messages[0].role == "system"
    assert beat_messages[1].role == "user"

    # System prompt should contain rules, not worldview dump
    system = beat_messages[0].content
    assert "写作方向" in system
    assert "读者读感" in system
    assert "简洁有力" in system

    # User prompt should contain chapter plan and beat info
    user = beat_messages[1].content
    assert "当前节拍" in user
    assert "开场" in user


@pytest.mark.asyncio
async def test_prompt_does_not_contain_full_context_dump(async_session):
    """Verify the old context.model_dump_json() pattern is gone."""
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=1,
        title="Test",
        target_word_count=2000,
        beats=[BeatPlan(summary="开场", target_mood="压抑")],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="这段世界观不应该出现在用户消息中" * 50,
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[],
        similar_chapters=[],
    )
    await director.save_checkpoint(
        "novel_test_nodump",
        phase=Phase.DRAFTING,
        checkpoint_data={"chapter_context": context.model_dump()},
        volume_id="vol_1",
        chapter_id="ch_nodump",
    )
    await ChapterRepository(async_session).create("ch_nodump", "vol_1", 1, "Test")

    captured_messages = []

    def capture_prompt(agent, task=None):
        mock = AsyncMock()

        async def acomplete(messages, config=None):
            captured_messages.append(messages)
            return LLMResponse(
                text="这是一个很长的节拍正文内容，字数足够多，情节跌宕起伏，引人入胜，令人难以忘怀。"
            )

        mock.acomplete.side_effect = acomplete
        return mock

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.side_effect = capture_prompt
        mock_factory._resolve_config.return_value = None
        agent = WriterAgent(async_session)
        await agent.write("novel_test_nodump", context, "ch_nodump")

    # User message should NOT contain the full worldview dump
    beat_messages = captured_messages[0]
    user_content = beat_messages[1].content
    assert "这段世界观不应该出现在用户消息中" not in user_content


@pytest.mark.asyncio
async def test_writer_prompt_carries_story_contract_goal(async_session):
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=1,
        title="Test",
        target_word_count=2000,
        beats=[BeatPlan(summary="林照发现祠堂里的玉佩", target_mood="压抑")],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="祠堂"),
        timeline_events=[],
        pending_foreshadowings=[],
        story_contract={
            "protagonist_goal": "追查家族覆灭真相",
            "current_stage_goal": "找到父亲玉佩里的第一条线索",
            "first_chapter_goal": "让林照确认玉佩与覆灭真相有关",
            "must_carry_forward": ["父亲玉佩"],
        },
    )
    await director.save_checkpoint(
        "novel_test_contract",
        phase=Phase.DRAFTING,
        checkpoint_data={"chapter_context": context.model_dump()},
        volume_id="vol_1",
        chapter_id="ch_contract",
    )
    await ChapterRepository(async_session).create("ch_contract", "vol_1", 1, "Test")

    captured_messages = []

    def capture_prompt(agent, task=None):
        mock = AsyncMock()

        async def acomplete(messages, config=None):
            captured_messages.append(messages)
            return LLMResponse(text="林照在祠堂里握住玉佩，寒意顺着掌心蔓延，他终于确认父亲留下的线索仍在。")

        mock.acomplete.side_effect = acomplete
        return mock

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.side_effect = capture_prompt
        mock_factory._resolve_config.return_value = None
        agent = WriterAgent(async_session)
        await agent.write("novel_test_contract", context, "ch_contract")

    user = captured_messages[0][1].content
    assert "故事契约" in user
    assert "追查家族覆灭真相" in user
    assert "当前节拍动作要服务这个长期目标" in user
