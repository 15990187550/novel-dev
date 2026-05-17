import json
from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.fast_review_agent import (
    FastReviewAgent,
    _build_genre_quality_issues,
    _find_language_style_issues,
)
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.llm.models import LLMResponse
from novel_dev.schemas.review import DimensionIssue, DimensionScore, ScoreResult
from novel_dev.services.quality_gate_service import QUALITY_UNCHECKED, QualityGateResult


def test_build_genre_quality_issues_converts_type_drift_items():
    issues = _build_genre_quality_issues(
        "董事会刚结束，他突然回宗门突破境界。",
        {
            "blocking_rules": {"type_drift": True},
            "forbidden_drift_patterns": ["宗门", "境界突破"],
        },
    )

    assert [issue.code for issue in issues] == ["type_drift"]
    assert issues[0].category == "style"
    assert issues[0].severity == "block"
    assert issues[0].source == "fast_review"
    assert any("宗门" in item for item in issues[0].evidence)


def test_find_language_style_issues_allows_authorized_modern_terms():
    issues = _find_language_style_issues(
        "他用 KPI 和 APP 复盘项目。",
        context={"genre_quality_config": {"modern_terms_policy": "allow", "authorized_latin_terms": ["KPI", "APP"]}},
    )

    assert not any("现代" in issue or "英文/外文" in issue for issue in issues)

    unauthorized_issues = _find_language_style_issues(
        "他突然说出 UNKNOWNTERM。",
        context={"genre_quality_config": {"modern_terms_policy": "allow", "authorized_latin_terms": ["KPI", "APP"]}},
    )

    assert any("英文/外文" in issue for issue in unauthorized_issues)


@pytest.mark.asyncio
async def test_fast_review_pass(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_pass",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={"chapter_context": {"chapter_plan": {"target_word_count": 4}}},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")
    await ChapterRepository(async_session).update_text("c1", raw_draft="甲乙丙。", polished_text="甲乙丙。")

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
        checkpoint_data={
            "chapter_context": {"chapter_plan": {"target_word_count": 1000}},
            "quality_gate": {"status": "block"},
            "quality_issues": [{"code": "stale"}],
            "quality_issue_summary": {"total": 1},
            "repair_tasks": [{"task_id": "stale"}],
            "continuity_audit": {"status": "block"},
            "final_polish_issues": {"source": "previous_final_review"},
        },
        volume_id="v1",
        chapter_id="c1",
    )
    repo = ChapterRepository(async_session)
    await repo.create("c1", "v1", 1, "Test")
    await repo.update_text(
        "c1",
        raw_draft="a very long raw draft with many characters",
        polished_text="short",
    )
    await repo.update_quality_gate(
        "c1",
        quality_status="block",
        quality_reasons={"status": "block", "blocking_items": [{"code": "stale"}]},
        world_state_ingested=True,
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
    for key in ("quality_gate", "quality_issues", "quality_issue_summary", "repair_tasks", "continuity_audit"):
        assert key not in state.checkpoint_data
    assert state.checkpoint_data["final_polish_issues"] == {"source": "previous_final_review"}
    chapter = await repo.get_by_id("c1")
    assert chapter.quality_status == QUALITY_UNCHECKED
    assert chapter.quality_reasons == {}
    assert chapter.world_state_ingested is False


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
async def test_fast_review_longform_acceptance_scope_relaxes_word_count(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_longform_scope",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={
            "acceptance_scope": "real-longform-volume1",
            "chapter_context": {"chapter_plan": {"target_word_count": 3000}},
        },
        volume_id="v1",
        chapter_id="c_longform_scope",
    )
    await ChapterRepository(async_session).create("c_longform_scope", "v1", 1, "Longform")
    await ChapterRepository(async_session).update_text(
        "c_longform_scope",
        raw_draft="陆照提着药篓走进巷口，风从墙缝里钻出来，吹得衣角微动。",
        polished_text="陆照提着药篓走进巷口，风从墙缝里钻出来，吹得衣角微动。",
    )

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(
        text=json.dumps({"consistency_fixed": True, "beat_cohesion_ok": True, "notes": []})
    )

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = FastReviewAgent(async_session)
        report = await agent.review("novel_fr_longform_scope", "c_longform_scope")

    assert report.word_count_ok is True

    state = await director.resume("novel_fr_longform_scope")
    assert state.current_phase == Phase.LIBRARIAN.value


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
async def test_fast_review_fails_plan_language_in_polished_text(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_fail_plan_language",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={"chapter_context": {"chapter_plan": {"target_word_count": 40}}},
        volume_id="v1",
        chapter_id="c_plan_language",
    )
    await ChapterRepository(async_session).create("c_plan_language", "v1", 1, "Test")
    await ChapterRepository(async_session).update_text(
        "c_plan_language",
        raw_draft="陆照站在石阶上，压住肩背伤势。",
        polished_text="阻力不需要另起一条线，它就压在当前这件事上。陆照站在石阶上。",
    )

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(
        text=json.dumps({"consistency_fixed": True, "beat_cohesion_ok": True, "notes": []})
    )

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = FastReviewAgent(async_session)
        report = await agent.review("novel_fr_fail_plan_language", "c_plan_language")

    assert report.language_style_ok is False
    assert any("规划/元叙述" in note for note in report.notes)

    state = await director.resume("novel_fr_fail_plan_language")
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
    assert "读者体验" in prompt
    assert "相信人物" in prompt
    assert "愿意继续读" in prompt
    assert "正向改写目标" in prompt
    assert "比喻过密" in prompt
    assert "类型概念" in prompt
    assert "最多 3 条" in prompt
    assert "不超过 60 个汉字" in prompt
    assert "简短指出" in prompt
    assert "notes" in prompt


@pytest.mark.asyncio
async def test_fast_review_parse_failure_falls_back_to_editing(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_parse_fallback",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={"chapter_context": {"chapter_plan": {"target_word_count": 4}}},
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
async def test_fast_review_standalone_clears_stale_terminal_metadata_before_edit_limit(async_session):
    repo = ChapterRepository(async_session)
    await repo.create("c_standalone_retry", "v1", 1, "Standalone Retry")
    await repo.update_text(
        "c_standalone_retry",
        raw_draft="a very long raw draft with many characters",
        polished_text="short",
    )
    await repo.update_quality_gate(
        "c_standalone_retry",
        quality_status="block",
        quality_reasons={"status": "block", "blocking_items": [{"code": "stale"}]},
        world_state_ingested=True,
    )
    checkpoint = {
        "edit_attempt_count": 0,
        "chapter_context": {"chapter_plan": {"target_word_count": 1000}},
        "quality_gate": {"status": "block"},
        "quality_issues": [{"code": "stale"}],
        "quality_issue_summary": {"total": 1},
        "repair_tasks": [{"task_id": "stale"}],
        "continuity_audit": {"status": "block"},
        "final_polish_issues": {"source": "previous_final_review"},
    }

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
        report = await agent.review_standalone("novel_fr_standalone_retry", "c_standalone_retry", checkpoint)

    assert report.ai_flavor_reduced is False
    for key in ("quality_gate", "quality_issues", "quality_issue_summary", "repair_tasks", "continuity_audit"):
        assert key not in checkpoint
    assert checkpoint["final_polish_issues"] == {"source": "previous_final_review"}
    chapter = await repo.get_by_id("c_standalone_retry")
    assert chapter.quality_status == QUALITY_UNCHECKED
    assert chapter.quality_reasons == {}
    assert chapter.world_state_ingested is False


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


def test_store_quality_issues_keeps_empty_repair_tasks_for_manual_block():
    checkpoint = {"repair_tasks": [{"task_id": "stale"}]}
    gate = QualityGateResult(
        status="block",
        blocking_items=[
            {
                "code": "review_note",
                "message": "严重矛盾：需要人工判断结构是否要重排",
            }
        ],
        summary="人工阻断",
    )

    FastReviewAgent._store_quality_issues_and_repairs(checkpoint, gate, "c_manual_block")

    assert checkpoint["repair_tasks"] == []
    assert checkpoint["quality_issue_summary"]["total"] == 1
    assert checkpoint["quality_issue_summary"]["by_code"]["review_note"] == 1
    assert checkpoint["quality_issues"][0]["repairability"] == "manual"


def test_store_quality_issues_clears_stale_repair_tasks_for_non_block_gate():
    checkpoint = {
        "repair_tasks": [{"task_id": "stale"}],
        "quality_issues": [{"code": "stale"}],
        "quality_issue_summary": {"total": 99},
    }
    gate = QualityGateResult(
        status="warn",
        warning_items=[
            {
                "code": "ai_flavor",
                "message": "AI 腔或模板化表达未充分降低",
            }
        ],
        summary="可放行告警",
    )

    FastReviewAgent._store_quality_issues_and_repairs(checkpoint, gate, "c_warn")

    assert "repair_tasks" not in checkpoint
    assert checkpoint["quality_issue_summary"]["total"] == 1
    assert checkpoint["quality_issue_summary"]["by_code"]["ai_flavor"] == 1
    assert checkpoint["quality_issues"][0]["code"] == "ai_flavor"


def test_store_quality_issues_ignores_resolved_structure_guard_for_warn_gate():
    guard = {
        "beat_index": 1,
        "issues": ["提前写入后续 beat 的核心事件"],
        "suggested_rewrite_focus": "聚焦当前 beat",
    }
    checkpoint = {
        "chapter_structure_guard": dict(guard),
        "editor_guard_resolved": [dict(guard)],
        "repair_tasks": [{"task_id": "stale"}],
    }
    gate = QualityGateResult(
        status="warn",
        warning_items=[
            {
                "code": "ai_flavor",
                "message": "AI 腔或模板化表达未充分降低",
            }
        ],
        summary="可放行告警",
    )

    FastReviewAgent._store_quality_issues_and_repairs(checkpoint, gate, "c_warn_resolved_guard")

    assert "repair_tasks" not in checkpoint
    issue_codes = {issue["code"] for issue in checkpoint["quality_issues"]}
    assert issue_codes == {"ai_flavor"}
    assert "plan_boundary_violation" not in checkpoint["quality_issue_summary"]["by_code"]


def test_store_quality_issues_manual_block_ignores_resolved_structure_guard():
    guard = {
        "beat_index": 1,
        "issues": ["提前写入后续 beat 的核心事件"],
        "suggested_rewrite_focus": "聚焦当前 beat",
    }
    checkpoint = {
        "chapter_structure_guard": dict(guard),
        "editor_guard_resolved": [dict(guard)],
        "repair_tasks": [{"task_id": "stale"}],
    }
    gate = QualityGateResult(
        status="block",
        blocking_items=[
            {
                "code": "review_note",
                "message": "严重矛盾：需要人工判断结构是否要重排",
            }
        ],
        summary="人工阻断",
    )

    FastReviewAgent._store_quality_issues_and_repairs(checkpoint, gate, "c_manual_block_resolved_guard")

    assert checkpoint["repair_tasks"] == []
    issue_codes = {issue["code"] for issue in checkpoint["quality_issues"]}
    assert issue_codes == {"review_note"}
    assert checkpoint["quality_issue_summary"]["by_code"]["review_note"] == 1


def test_unresolved_structure_guard_promotes_gate_and_creates_repair_task():
    checkpoint = {
        "chapter_structure_guard": {
            "beat_index": 1,
            "issues": ["提前写入后续 beat 的核心事件"],
            "suggested_rewrite_focus": "聚焦当前 beat",
        },
        "editor_guard_resolved": [],
    }
    gate = QualityGateResult(status="pass", summary="通过")

    gate = FastReviewAgent._apply_structure_guard_to_gate(checkpoint, gate)
    FastReviewAgent._store_quality_issues_and_repairs(checkpoint, gate, "c_unresolved_guard")

    assert gate.status == "block"
    assert gate.blocking_items[0]["code"] == "plan_boundary_violation"
    assert checkpoint["quality_issue_summary"]["by_code"]["plan_boundary_violation"] == 1
    assert checkpoint["quality_issues"][0]["code"] == "plan_boundary_violation"
    assert checkpoint["quality_issues"][0]["beat_index"] == 1
    assert checkpoint["repair_tasks"][0]["issue_codes"] == ["plan_boundary_violation"]


@pytest.mark.asyncio
async def test_fast_review_stores_standard_issues_and_repair_tasks_for_block(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_standard_issues_block",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={
            "edit_attempt_count": 2,
            "chapter_structure_guard": {
                "beat_index": 1,
                "issues": ["提前写入后续 beat 的核心事件", "新增计划外事实"],
                "suggested_rewrite_focus": "聚焦当前 beat 的既定行动",
            },
            "chapter_context": {"chapter_plan": {"target_word_count": 12}},
        },
        volume_id="v1",
        chapter_id="c_standard_issues_block",
    )
    await ChapterRepository(async_session).create("c_standard_issues_block", "v1", 1, "Block")
    await ChapterRepository(async_session).update_text(
        "c_standard_issues_block",
        raw_draft="甲乙丙丁戊己庚辛壬癸子丑",
        polished_text="甲乙丙丁戊己庚辛壬癸子丑",
    )

    with patch(
        "novel_dev.agents.fast_review_agent.call_and_parse_model",
        new_callable=AsyncMock,
        return_value=type("LLMCheck", (), {
            "consistency_fixed": False,
            "beat_cohesion_ok": False,
            "notes": ["主角状态异常", "节拍之间缺少承接"],
        })(),
    ):
        agent = FastReviewAgent(async_session)
        await agent.review("novel_fr_standard_issues_block", "c_standard_issues_block")

    state = await director.resume("novel_fr_standard_issues_block")
    assert state.current_phase == Phase.FAST_REVIEWING.value
    checkpoint = state.checkpoint_data
    issue_codes = {issue["code"] for issue in checkpoint["quality_issues"]}
    assert {"consistency", "beat_cohesion", "plan_boundary_violation"} <= issue_codes
    assert checkpoint["quality_issue_summary"]["total"] == len(checkpoint["quality_issues"])
    assert checkpoint["quality_issue_summary"]["by_severity"]["block"] >= 3
    assert checkpoint["quality_issue_summary"]["by_code"]["plan_boundary_violation"] == 1
    assert checkpoint["repair_tasks"]
    repair_codes = {code for task in checkpoint["repair_tasks"] for code in task["issue_codes"]}
    assert {"consistency", "beat_cohesion", "plan_boundary_violation"} <= repair_codes


@pytest.mark.asyncio
async def test_fast_review_returns_to_editing_for_recoverable_quality_gate_block(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_recoverable_block",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={
            "acceptance_scope": "real-longform-volume1",
            "edit_attempt_count": 2,
            "chapter_context": {
                "chapter_plan": {"target_word_count": 12},
                "writing_cards": [
                    {"beat_index": 0, "required_payoffs": ["主角做出当场选择"], "ending_hook": "危险信号逼近"}
                ],
            },
        },
        volume_id="v1",
        chapter_id="c_recoverable_block",
    )
    repo = ChapterRepository(async_session)
    await repo.create("c_recoverable_block", "v1", 1, "Recoverable Block")
    await repo.update_text(
        "c_recoverable_block",
        raw_draft="甲乙丙丁。",
        polished_text="甲乙丙丁。甲乙丙丁。",
    )

    final_score = ScoreResult(
        overall=78,
        dimensions=[DimensionScore(name="readability", score=78, comment="基本顺畅")],
        summary_feedback="存在可修复的转场问题",
    )

    with patch(
        "novel_dev.agents.fast_review_agent.call_and_parse_model",
        new_callable=AsyncMock,
        return_value=type("LLMCheck", (), {
            "consistency_fixed": True,
            "beat_cohesion_ok": False,
            "notes": ["节拍之间缺少承接"],
        })(),
    ), patch(
        "novel_dev.agents.critic_agent.CriticAgent._generate_score",
        new_callable=AsyncMock,
        return_value=final_score,
    ):
        agent = FastReviewAgent(async_session)
        await agent.review("novel_fr_recoverable_block", "c_recoverable_block")

    chapter = await repo.get_by_id("c_recoverable_block")
    assert chapter.quality_status == "block"

    state = await director.resume("novel_fr_recoverable_block")
    assert state.current_phase == Phase.EDITING.value
    assert state.checkpoint_data["quality_gate_repair_attempt_count"] == 1
    assert state.checkpoint_data["final_polish_issues"]["quality_gate_blocking_items"][0]["code"] == "beat_cohesion"


@pytest.mark.asyncio
async def test_fast_review_returns_to_editing_for_longform_repairable_structure_block(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_longform_structure_repair",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={
            "acceptance_scope": "real-longform-volume1",
            "edit_attempt_count": 2,
            "chapter_structure_guard": {
                "beat_index": 2,
                "issues": ["新增计划外事实", "删除关键决心表达"],
                "suggested_rewrite_focus": "删除计划外事实，恢复原决心表达，只做承接润色",
            },
            "chapter_context": {"chapter_plan": {"target_word_count": 12}},
        },
        volume_id="v1",
        chapter_id="c_longform_structure_repair",
    )
    repo = ChapterRepository(async_session)
    await repo.create("c_longform_structure_repair", "v1", 1, "Longform Repair")
    await repo.update_text(
        "c_longform_structure_repair",
        raw_draft="甲乙丙丁戊己庚辛壬癸子丑",
        polished_text="甲乙丙丁戊己庚辛壬癸子丑甲乙丙丁",
    )

    final_score = ScoreResult(
        overall=68,
        dimensions=[DimensionScore(name="readability", score=68, comment="转场和承接偏弱")],
        summary_feedback="需要修节拍承接和计划边界",
    )

    with patch(
        "novel_dev.agents.fast_review_agent.call_and_parse_model",
        new_callable=AsyncMock,
        return_value=type("LLMCheck", (), {
            "consistency_fixed": False,
            "beat_cohesion_ok": False,
            "notes": ["节拍之间缺少承接", "存在拼接感"],
        })(),
    ), patch(
        "novel_dev.agents.critic_agent.CriticAgent._generate_score",
        new_callable=AsyncMock,
        return_value=final_score,
    ):
        agent = FastReviewAgent(async_session)
        await agent.review("novel_fr_longform_structure_repair", "c_longform_structure_repair")

    chapter = await repo.get_by_id("c_longform_structure_repair")
    assert chapter.quality_status == "block"

    state = await director.resume("novel_fr_longform_structure_repair")
    assert state.current_phase == Phase.EDITING.value
    assert state.checkpoint_data["quality_gate_repair_attempt_count"] == 1
    repair_codes = {
        item["code"]
        for item in state.checkpoint_data["final_polish_issues"]["quality_gate_blocking_items"]
        if isinstance(item, dict) and item.get("code")
    }
    assert {"consistency", "beat_cohesion", "plan_boundary_violation"} <= repair_codes


@pytest.mark.asyncio
async def test_fast_review_records_final_review_score_from_polished_text(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_final_score",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={"chapter_context": {"chapter_plan": {"target_word_count": 4}}},
        volume_id="v1",
        chapter_id="c_final_score",
    )
    repo = ChapterRepository(async_session)
    await repo.create("c_final_score", "v1", 1, "Final Score")
    await repo.update_text("c_final_score", raw_draft="甲乙丙。", polished_text="甲乙丙。")
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
async def test_fast_review_returns_to_editing_for_low_final_score_before_edit_limit(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_final_polish",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={
            "edit_attempt_count": 1,
            "chapter_context": {
                "chapter_plan": {
                    "target_word_count": 4,
                    "beats": [{"summary": "林照展开残信", "target_mood": "tense"}],
                },
                "writing_cards": [
                    {
                        "beat_index": 0,
                        "required_payoffs": ["林照读出残信上的禁字"],
                        "ending_hook": "残信上的禁字让林照意识到危险逼近",
                    }
                ],
            },
        },
        volume_id="v1",
        chapter_id="c_final_polish",
    )
    repo = ChapterRepository(async_session)
    await repo.create("c_final_polish", "v1", 1, "Final Polish")
    await repo.update_text("c_final_polish", raw_draft="甲乙丙。", polished_text="甲乙丙。")

    final_score = ScoreResult(
        overall=72,
        dimensions=[DimensionScore(name="hook_strength", score=72, comment="章末钩子偏弱")],
        summary_feedback="章末钩子偏弱，残信线索没有形成读者牵引。",
        per_dim_issues=[
            DimensionIssue(
                dim="hook_strength",
                beat_idx=0,
                problem="残信出现后没有当场后果和风险余波。",
                suggestion="用残信字迹、林照身体反应和危险余波形成停点。",
            )
        ],
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
    ):
        agent = FastReviewAgent(async_session)
        await agent.review("novel_fr_final_polish", "c_final_polish")

    chapter = await repo.get_by_id("c_final_polish")
    assert chapter.quality_status == QUALITY_UNCHECKED
    assert chapter.quality_reasons == {}
    assert chapter.world_state_ingested is False
    assert chapter.final_review_score == 72

    state = await director.resume("novel_fr_final_polish")
    assert state.current_phase == Phase.EDITING.value
    for key in ("quality_gate", "quality_issues", "quality_issue_summary", "repair_tasks", "continuity_audit"):
        assert key not in state.checkpoint_data
    final_polish = state.checkpoint_data["final_polish_issues"]
    assert final_polish["source"] == "final_review"
    assert final_polish["beat_issues"][0]["beat_index"] == 0
    assert "残信出现后没有当场后果" in final_polish["beat_issues"][0]["issues"][0]["problem"]
    assert any(item["code"] == "required_payoff" for item in final_polish["quality_gate_warnings"])


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
        raw_draft="甲乙丙丁戊。",
        polished_text="甲乙丙丁戊己庚。",
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


@pytest.mark.asyncio
async def test_fast_review_real_contract_skips_strict_word_count_gate(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_contract",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={
            "acceptance_scope": "real-contract",
            "chapter_context": {"chapter_plan": {"target_word_count": 1000}},
        },
        volume_id="v1",
        chapter_id="c_contract",
    )
    await ChapterRepository(async_session).create("c_contract", "v1", 1, "Contract")
    await ChapterRepository(async_session).update_text(
        "c_contract",
        raw_draft="甲" * 1000,
        polished_text=("甲" * 2199) + "。",
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
        report = await agent.review("novel_fr_contract", "c_contract")

    assert report.word_count_ok is True
    assert "字数偏离目标超过10%" not in report.notes

    chapter = await ChapterRepository(async_session).get_by_id("c_contract")
    assert chapter.quality_status == "pass"

    state = await director.resume("novel_fr_contract")
    assert state.current_phase == Phase.LIBRARIAN.value


@pytest.mark.asyncio
async def test_fast_review_blocks_librarian_when_continuity_audit_finds_hard_conflict(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_continuity_block",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={
            "chapter_context": {
                "chapter_plan": {"target_word_count": 20},
                "active_entities": [
                    {"name": "林照", "type": "character", "current_state": "已死亡，尸身留在黑水城"}
                ],
            },
        },
        volume_id="v1",
        chapter_id="c_continuity_block",
    )
    await ChapterRepository(async_session).create("c_continuity_block", "v1", 1, "Continuity Block")
    await ChapterRepository(async_session).update_text(
        "c_continuity_block",
        raw_draft="林照忽然醒来，开口说出隐藏多年的真相。",
        polished_text="林照忽然醒来，开口说出隐藏多年的真相。",
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
        await agent.review("novel_fr_continuity_block", "c_continuity_block")

    chapter = await ChapterRepository(async_session).get_by_id("c_continuity_block")
    assert chapter.quality_status == "block"
    assert chapter.world_state_ingested is False

    state = await director.resume("novel_fr_continuity_block")
    assert state.current_phase == Phase.FAST_REVIEWING.value
    assert state.checkpoint_data["continuity_audit"]["status"] == "block"
    assert state.checkpoint_data["quality_gate"]["blocking_items"][0]["code"] == "continuity_audit"
