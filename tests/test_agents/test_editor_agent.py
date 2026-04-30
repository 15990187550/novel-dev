from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.editor_agent import EditorAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.llm.models import LLMResponse
from novel_dev.services.log_service import LogService


@pytest.fixture(autouse=True)
def clear_log_buffers():
    LogService._buffers.clear()
    LogService._listeners.clear()


@pytest.mark.asyncio
async def test_polish_low_score_beats(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_edit",
        phase=Phase.EDITING,
        checkpoint_data={
            "beat_scores": [
                {"beat_index": 0, "scores": {"humanity": 60}},
                {"beat_index": 1, "scores": {"humanity": 80}},
            ]
        },
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")
    await ChapterRepository(async_session).update_text("c1", raw_draft="Beat one\n\nBeat two")

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="润色后的 Beat one")

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = EditorAgent(async_session)
        await agent.polish("novel_edit", "c1")

    ch = await ChapterRepository(async_session).get_by_id("c1")
    assert "润色后的 Beat one" in ch.polished_text
    assert "Beat two" in ch.polished_text
    assert ch.status == "edited"

    state = await director.resume("novel_edit")
    assert state.current_phase == Phase.FAST_REVIEWING.value


@pytest.mark.asyncio
async def test_polish_emits_direct_llm_rewrite_step_logs(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_edit_logs",
        phase=Phase.EDITING,
        checkpoint_data={
            "beat_scores": [
                {"beat_index": 0, "scores": {"humanity": 60}},
            ]
        },
        volume_id="v1",
        chapter_id="c_logs",
    )
    await ChapterRepository(async_session).create("c_logs", "v1", 1, "Test")
    await ChapterRepository(async_session).update_text("c_logs", raw_draft="Beat one")

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="润色后的 Beat one")

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = EditorAgent(async_session)
        await agent.polish("novel_edit_logs", "c_logs")

    entries = list(LogService._buffers["novel_edit_logs"])
    assert any(
        entry.get("event") == "agent.step"
        and entry.get("status") == "started"
        and entry.get("node") == "polish_beat"
        for entry in entries
    )
    assert any(
        entry.get("event") == "agent.step"
        and entry.get("status") == "succeeded"
        and entry.get("task") == "polish_beat"
        for entry in entries
    )


@pytest.mark.asyncio
async def test_polish_preserves_high_readability(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_edit_high_readability",
        phase=Phase.EDITING,
        checkpoint_data={
            "beat_scores": [
                {"beat_index": 0, "scores": {"readability": 80}},
            ]
        },
        volume_id="v1",
        chapter_id="c2",
    )
    await ChapterRepository(async_session).create("c2", "v1", 2, "Test")
    await ChapterRepository(async_session).update_text("c2", raw_draft="A readable beat")

    agent = EditorAgent(async_session)
    await agent.polish("novel_edit_high_readability", "c2")

    ch = await ChapterRepository(async_session).get_by_id("c2")
    assert ch.polished_text == "A readable beat"
    assert ch.status == "edited"


@pytest.mark.asyncio
async def test_rewrite_beat_prompt_requires_cleaning_english_terms(async_session):
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="他摸到竹筒，翻身坐起。")

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = EditorAgent(async_session)
        await agent._rewrite_beat(
            "他摸到竹筒，脑子里冒出一句 snooze。",
            {},
            [],
            [],
            {"style_profile": {}},
        )

    prompt = mock_client.acomplete.call_args.args[0][0].content
    assert "禁止输出英文" in prompt
    assert "snooze" in prompt


@pytest.mark.asyncio
async def test_rewrite_beat_prompt_targets_low_ai_flavor_patterns(async_session):
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="陆照扶着石壁坐稳，先去看掌心。")

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = EditorAgent(async_session)
        await agent._rewrite_beat(
            "光像潮水，意识深处又像万花筒，仿佛有什么存在从古经里醒来。",
            {"humanity": 60, "readability": 62},
            [
                {
                    "dim": "humanity",
                    "problem": "比喻连续堆叠，抽象玄幻词过密",
                    "suggestion": "压缩异象，只保留一个具体画面和一个身体后果",
                }
            ],
            [],
            {"style_profile": {}},
        )

    prompt = mock_client.acomplete.call_args.args[0][0].content
    assert "比喻过密" in prompt
    assert "抽象玄幻词" in prompt
    assert "奇观堆叠" in prompt
    assert "模板化入体" in prompt
    assert "保留最关键的 1-2 个画面" in prompt
