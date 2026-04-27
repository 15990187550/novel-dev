import asyncio
import inspect
from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.writer_agent import WriterAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.context import ChapterContext, ChapterPlan, BeatPlan, EntityState, LocationContext
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.llm.models import LLMResponse


def test_write_does_not_fire_and_forget_chapter_indexing():
    source = inspect.getsource(WriterAgent.write)
    assert "create_task(self.embedding_service.index_chapter" not in source


@pytest.mark.asyncio
async def test_write_draft_success(async_session):
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=1,
        title="Test",
        target_word_count=2000,
        beats=[
            BeatPlan(summary="开场", target_mood="压抑"),
            BeatPlan(summary="冲突", target_mood="紧张"),
        ],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[{"id": "fs_1", "content": "玉佩发光", "role_in_chapter": "embed"}],
    )
    await director.save_checkpoint(
        "novel_test",
        phase=Phase.DRAFTING,
        checkpoint_data={"chapter_context": context.model_dump()},
        volume_id="vol_1",
        chapter_id="ch_1",
    )
    await ChapterRepository(async_session).create("ch_1", "vol_1", 1, "Test")

    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text="开场节拍生成的正文内容，字数足够多，情节跌宕起伏，引人入胜，令人难以忘怀。这是第一段非常详细的描写，包含了丰富的场景和人物心理活动，忽然玉佩发光。"),
        LLMResponse(text="冲突节拍生成的正文内容，字数足够多，矛盾尖锐，冲突激烈，让读者欲罢不能。这是第二段非常详细的描写，包含了紧张的对话和激烈的动作场面。"),
    ]

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = WriterAgent(async_session)
        metadata = await agent.write("novel_test", context, "ch_1")

    assert metadata.total_words > 0
    assert len(metadata.beat_coverage) == 2
    assert "fs_1" in metadata.embedded_foreshadowings

    ch = await ChapterRepository(async_session).get_by_id("ch_1")
    assert ch.status == "drafted"
    assert ch.raw_draft is not None

    state = await director.resume("novel_test")
    assert state.current_phase == Phase.REVIEWING.value


@pytest.mark.asyncio
async def test_write_awaits_chapter_indexing(async_session):
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=1,
        title="Test",
        target_word_count=800,
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
    )
    await director.save_checkpoint(
        "novel_index_wait",
        phase=Phase.DRAFTING,
        checkpoint_data={"chapter_context": context.model_dump()},
        volume_id="vol_1",
        chapter_id="ch_index_wait",
    )
    await ChapterRepository(async_session).create("ch_index_wait", "vol_1", 1, "Test")

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="这是一个足够长的节拍正文内容，人物行动明确，场景推进稳定，读起来完整自然。")
    started = asyncio.Event()
    release = asyncio.Event()
    embedding_service = AsyncMock()

    async def index_chapter(chapter_id):
        assert chapter_id == "ch_index_wait"
        started.set()
        await release.wait()

    embedding_service.index_chapter.side_effect = index_chapter

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        mock_factory._resolve_config.return_value = None
        agent = WriterAgent(async_session, embedding_service=embedding_service)
        write_task = asyncio.create_task(agent.write("novel_index_wait", context, "ch_index_wait"))
        await started.wait()
        for _ in range(20):
            await asyncio.sleep(0)
        assert write_task.done() is False
        release.set()
        await write_task

    embedding_service.index_chapter.assert_awaited_once_with("ch_index_wait")


@pytest.mark.asyncio
async def test_write_missing_context(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_no_ctx",
        phase=Phase.DRAFTING,
        checkpoint_data={},
        volume_id="vol_1",
        chapter_id="ch_1",
    )
    context = ChapterContext(
        chapter_plan=ChapterPlan(chapter_number=1, title="T", target_word_count=100, beats=[]),
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[],
    )
    agent = WriterAgent(async_session)
    with pytest.raises(ValueError, match="chapter_context missing"):
        await agent.write("novel_no_ctx", context, "ch_1")


@pytest.mark.asyncio
async def test_write_wrong_phase(async_session):
    director = NovelDirector(session=async_session)
    plan = ChapterPlan(chapter_number=1, title="T", target_word_count=100, beats=[])
    context = ChapterContext(
        chapter_plan=plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[],
    )
    await director.save_checkpoint(
        "novel_wrong",
        phase=Phase.REVIEWING,
        checkpoint_data={"chapter_context": context.model_dump()},
        volume_id="vol_1",
        chapter_id="ch_1",
    )
    agent = WriterAgent(async_session)
    with pytest.raises(ValueError, match="Cannot write draft"):
        await agent.write("novel_wrong", context, "ch_1")
