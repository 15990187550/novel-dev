import json
from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.fast_review_agent import FastReviewAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.llm.models import LLMResponse
from novel_dev.schemas.review import DimensionScore, ScoreResult


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
    await ChapterRepository(async_session).update_text("c1", raw_draft="甲乙丙", polished_text="甲乙丙")

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


@pytest.mark.asyncio
async def test_fast_review_fails_unapproved_english_terms(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_fail_english",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={"chapter_context": {"chapter_plan": {"target_word_count": 25}}},
        volume_id="v1",
        chapter_id="c_english",
    )
    await ChapterRepository(async_session).create("c_english", "v1", 1, "Test")
    await ChapterRepository(async_session).update_text(
        "c_english",
        raw_draft="他摸到床头竹筒，脑子里冒出前世闹钟的念头。",
        polished_text="他摸到床头竹筒，脑子里冒出一句 snooze。",
    )

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(
        text=json.dumps({"consistency_fixed": True, "beat_cohesion_ok": True, "notes": []})
    )

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = FastReviewAgent(async_session)
        report = await agent.review("novel_fr_fail_english", "c_english")

    assert report.language_style_ok is False
    assert any("snooze" in note for note in report.notes)

    state = await director.resume("novel_fr_fail_english")
    assert state.current_phase == Phase.EDITING.value


@pytest.mark.asyncio
async def test_fast_review_llm_prompt_asks_for_ai_flavor_residue_notes(async_session):
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(
        text=json.dumps({"consistency_fixed": True, "beat_cohesion_ok": True, "notes": []})
    )

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = FastReviewAgent(async_session)
        await agent._llm_check_consistency_and_cohesion(
            "光像潮水，意识深处又像万花筒。",
            "光像潮水，意识深处又像万花筒。",
            {"chapter_plan": {"target_word_count": 20}},
            "novel_fr_ai_prompt",
        )

    prompt = mock_client.acomplete.call_args.args[0][0].content
    assert "AI 味残留" in prompt
    assert "比喻过密" in prompt
    assert "抽象玄幻词" in prompt
    assert "最多 3 条" in prompt
    assert "不超过 60 个汉字" in prompt
    assert "不要展开长段分析" in prompt
    assert "notes" in prompt


@pytest.mark.asyncio
async def test_fast_review_parse_failure_falls_back_to_editing(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_parse_fallback",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={"chapter_context": {"chapter_plan": {"target_word_count": 3}}},
        volume_id="v1",
        chapter_id="c_parse_fallback",
    )
    await ChapterRepository(async_session).create("c_parse_fallback", "v1", 1, "Test")
    await ChapterRepository(async_session).update_text(
        "c_parse_fallback",
        raw_draft="甲乙丙",
        polished_text="甲乙丙",
    )

    with patch(
        "novel_dev.agents.fast_review_agent.call_and_parse_model",
        new_callable=AsyncMock,
        side_effect=RuntimeError("truncated json"),
    ):
        agent = FastReviewAgent(async_session)
        report = await agent.review("novel_fr_parse_fallback", "c_parse_fallback")

    assert report.consistency_fixed is False
    assert report.beat_cohesion_ok is False
    assert "快速评审模型输出解析失败，需退回精修复核" in report.notes

    chapter = await ChapterRepository(async_session).get_by_id("c_parse_fallback")
    assert chapter.fast_review_score == 50
    assert chapter.fast_review_feedback["consistency_fixed"] is False

    state = await director.resume("novel_fr_parse_fallback")
    assert state.current_phase == Phase.EDITING.value


@pytest.mark.asyncio
async def test_fast_review_blocks_severe_failure_at_edit_limit(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_block",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={
            "edit_attempt_count": 2,
            "chapter_context": {"chapter_plan": {"target_word_count": 12}},
        },
        volume_id="v1",
        chapter_id="c_block",
    )
    await ChapterRepository(async_session).create("c_block", "v1", 1, "Block")
    await ChapterRepository(async_session).update_text(
        "c_block",
        raw_draft="甲乙丙丁戊己庚辛壬癸子丑",
        polished_text="甲乙丙丁戊己庚辛壬癸子丑",
    )

    with patch(
        "novel_dev.agents.fast_review_agent.call_and_parse_model",
        new_callable=AsyncMock,
        return_value=type("LLMCheck", (), {
            "consistency_fixed": False,
            "beat_cohesion_ok": False,
            "notes": ["主角状态与上一章冲突", "节拍之间缺少承接"],
        })(),
    ):
        agent = FastReviewAgent(async_session)
        report = await agent.review("novel_fr_block", "c_block")

    assert report.consistency_fixed is False
    chapter = await ChapterRepository(async_session).get_by_id("c_block")
    assert chapter.quality_status == "block"
    assert chapter.world_state_ingested is False
    assert chapter.quality_reasons["blocking_items"]

    state = await director.resume("novel_fr_block")
    assert state.current_phase == Phase.FAST_REVIEWING.value
    assert state.checkpoint_data["quality_gate"]["status"] == "block"


@pytest.mark.asyncio
async def test_fast_review_records_final_review_score_from_polished_text(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_final_score",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={"chapter_context": {"chapter_plan": {"target_word_count": 3}}},
        volume_id="v1",
        chapter_id="c_final_score",
    )
    repo = ChapterRepository(async_session)
    await repo.create("c_final_score", "v1", 1, "Final Score")
    await repo.update_text("c_final_score", raw_draft="甲乙丙", polished_text="甲乙丙")
    await repo.update_scores("c_final_score", 61, {"readability": 61}, {"summary": "草稿偏弱"})

    final_score = ScoreResult(
        overall=82,
        dimensions=[DimensionScore(name="readability", score=82, comment="成稿顺畅")],
        summary_feedback="成稿明显改善",
    )

    with patch(
        "novel_dev.agents.fast_review_agent.call_and_parse_model",
        new_callable=AsyncMock,
        return_value=type("LLMCheck", (), {
            "consistency_fixed": True,
            "beat_cohesion_ok": True,
            "notes": [],
        })(),
    ), patch(
        "novel_dev.agents.critic_agent.CriticAgent._generate_score",
        new_callable=AsyncMock,
        return_value=final_score,
    ) as final_review:
        agent = FastReviewAgent(async_session)
        await agent.review("novel_fr_final_score", "c_final_score")

    final_review.assert_awaited_once()
    chapter = await repo.get_by_id("c_final_score")
    assert chapter.draft_review_score == 61
    assert chapter.final_review_score == 82
    assert chapter.final_review_feedback["summary_feedback"] == "成稿明显改善"


@pytest.mark.asyncio
async def test_fast_review_warns_word_count_only_at_edit_limit(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_warn",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={
            "edit_attempt_count": 2,
            "chapter_context": {"chapter_plan": {"target_word_count": 5}},
        },
        volume_id="v1",
        chapter_id="c_warn",
    )
    await ChapterRepository(async_session).create("c_warn", "v1", 1, "Warn")
    await ChapterRepository(async_session).update_text(
        "c_warn",
        raw_draft="甲乙丙丁戊",
        polished_text="甲乙丙丁戊己庚",
    )

    with patch(
        "novel_dev.agents.fast_review_agent.call_and_parse_model",
        new_callable=AsyncMock,
        return_value=type("LLMCheck", (), {
            "consistency_fixed": True,
            "beat_cohesion_ok": True,
            "notes": [],
        })(),
    ):
        agent = FastReviewAgent(async_session)
        report = await agent.review("novel_fr_warn", "c_warn")

    assert report.word_count_ok is False
    chapter = await ChapterRepository(async_session).get_by_id("c_warn")
    assert chapter.quality_status == "warn"
    assert chapter.quality_reasons["warning_items"]

    state = await director.resume("novel_fr_warn")
    assert state.current_phase == Phase.LIBRARIAN.value
    assert state.checkpoint_data["quality_gate"]["status"] == "warn"
