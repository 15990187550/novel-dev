from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.writer_agent import WriterAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.context import ChapterContext, ChapterPlan, BeatPlan, LocationContext
from novel_dev.schemas.similar_document import SimilarDocument
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.llm.models import LLMResponse


@pytest.mark.asyncio
async def test_similar_chapters_block_appears_in_prompt(async_session):
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=1,
        title="Test",
        target_word_count=2000,
        beats=[BeatPlan(summary="开场", target_mood="压抑")],
    )
    similar = [
        SimilarDocument(
            doc_id="ch_prev_1",
            doc_type="chapter",
            title="第一章",
            content_preview="这是之前的章节内容预览。",
            similarity_score=0.92,
        )
    ]
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[],
        similar_chapters=similar,
    )
    await director.save_checkpoint(
        "novel_test_sim",
        phase=Phase.DRAFTING,
        checkpoint_data={"chapter_context": context.model_dump()},
        volume_id="vol_1",
        chapter_id="ch_sim",
    )
    await ChapterRepository(async_session).create("ch_sim", "vol_1", 1, "Test")

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(
        text="这是一个很长的节拍正文内容，字数足够多，情节跌宕起伏，引人入胜，令人难以忘怀。"
    )

    captured_prompts = []

    def capture_prompt(agent, task=None):
        mock = AsyncMock()

        async def acomplete(messages):
            captured_prompts.append(messages[0].content)
            return LLMResponse(
                text="这是一个很长的节拍正文内容，字数足够多，情节跌宕起伏，引人入胜，令人难以忘怀。"
            )

        mock.acomplete.side_effect = acomplete
        return mock

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.side_effect = capture_prompt
        agent = WriterAgent(async_session)
        await agent.write("novel_test_sim", context, "ch_sim")

    assert len(captured_prompts) >= 1
    prompt = captured_prompts[0]
    assert "参考章节（保持风格一致性）" in prompt
    assert "[chapter] 第一章" in prompt
    assert "这是之前的章节内容预览。" in prompt


@pytest.mark.asyncio
async def test_empty_similar_chapters_omits_block(async_session):
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
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[],
        similar_chapters=[],
    )
    await director.save_checkpoint(
        "novel_test_empty",
        phase=Phase.DRAFTING,
        checkpoint_data={"chapter_context": context.model_dump()},
        volume_id="vol_1",
        chapter_id="ch_empty",
    )
    await ChapterRepository(async_session).create("ch_empty", "vol_1", 1, "Test")

    captured_prompts = []

    def capture_prompt(agent, task=None):
        mock = AsyncMock()

        async def acomplete(messages):
            captured_prompts.append(messages[0].content)
            return LLMResponse(
                text="这是一个很长的节拍正文内容，字数足够多，情节跌宕起伏，引人入胜，令人难以忘怀。"
            )

        mock.acomplete.side_effect = acomplete
        return mock

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.side_effect = capture_prompt
        agent = WriterAgent(async_session)
        await agent.write("novel_test_empty", context, "ch_empty")

    assert len(captured_prompts) >= 1
    prompt = captured_prompts[0]
    assert "参考章节（保持风格一致性）" not in prompt
