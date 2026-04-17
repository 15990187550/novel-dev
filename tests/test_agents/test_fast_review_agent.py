import json
from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.fast_review_agent import FastReviewAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.llm.models import LLMResponse


@pytest.mark.asyncio
async def test_fast_review_pass(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_pass",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={"chapter_context": {"chapter_plan": {"target_word_count": 3}}},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")
    await ChapterRepository(async_session).update_text("c1", raw_draft="abc", polished_text="abc")

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(
        text=json.dumps({"consistency_fixed": True, "beat_cohesion_ok": True, "notes": []})
    )

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = FastReviewAgent(async_session)
        report = await agent.review("novel_fr_pass", "c1")

    assert report.word_count_ok is True
    assert report.ai_flavor_reduced is True
    assert report.beat_cohesion_ok is True
    assert report.consistency_fixed is True
    assert report.notes == []

    state = await director.resume("novel_fr_pass")
    assert state.current_phase == Phase.LIBRARIAN.value


@pytest.mark.asyncio
async def test_fast_review_fail_ai_flavor(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_fail_flavor",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={"chapter_context": {"chapter_plan": {"target_word_count": 1000}}},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")
    await ChapterRepository(async_session).update_text(
        "c1",
        raw_draft="a very long raw draft with many characters",
        polished_text="short",
    )

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(
        text=json.dumps({"consistency_fixed": True, "beat_cohesion_ok": True, "notes": []})
    )

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = FastReviewAgent(async_session)
        report = await agent.review("novel_fr_fail_flavor", "c1")

    assert report.ai_flavor_reduced is False

    state = await director.resume("novel_fr_fail_flavor")
    assert state.current_phase == Phase.EDITING.value


@pytest.mark.asyncio
async def test_fast_review_fail_word_count(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_fail",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={"chapter_context": {"chapter_plan": {"target_word_count": 10}}},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")
    await ChapterRepository(async_session).update_text("c1", raw_draft="abc", polished_text="this is way too long")

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(
        text=json.dumps({"consistency_fixed": True, "beat_cohesion_ok": True, "notes": []})
    )

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = FastReviewAgent(async_session)
        report = await agent.review("novel_fr_fail", "c1")

    assert report.word_count_ok is False
    assert "字数偏离目标超过10%" in report.notes

    state = await director.resume("novel_fr_fail")
    assert state.current_phase == Phase.EDITING.value
