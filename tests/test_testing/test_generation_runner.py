import json
import httpx
import pytest
from contextlib import asynccontextmanager

from novel_dev.llm.exceptions import LLMRateLimitError, LLMTimeoutError
from novel_dev.repositories.setting_workbench_repo import SettingWorkbenchRepository
from novel_dev.testing import generation_runner
from novel_dev.testing.generation_runner import (
    GenerationRunOptions,
    classify_exception,
    run_generation_acceptance,
    run_stage_with_classification,
    should_fake_rerun_affect_final_status,
    validate_acceptance_scope,
)
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.testing.report import TestRunReport


def test_rate_limit_is_external_blocker():
    issue = classify_exception("chapter_draft", LLMRateLimitError("quota exhausted"), True)

    assert issue.type == "EXTERNAL_BLOCKED"
    assert issue.severity == "high"
    assert issue.stage == "chapter_draft"
    assert issue.is_external_blocker is True
    assert issue.real_llm is True
    assert issue.fake_rerun_status is None
    assert issue.message == "quota exhausted"
    assert issue.evidence == []
    assert issue.reproduce == "scripts/verify_generation_real.sh"


def test_internal_timeout_message_is_system_timeout():
    issue = classify_exception("preflight", LLMTimeoutError("local watchdog elapsed"), False)

    assert issue.type == "TIMEOUT_INTERNAL"
    assert issue.is_external_blocker is False
    assert issue.real_llm is False


def test_acceptance_target_word_count_has_runner_only_floor():
    fixture = generation_runner.load_generation_fixture("minimal_builtin")

    assert fixture.minimum_chapter_chars == 120
    assert generation_runner._acceptance_target_word_count(fixture) == 1000


def test_longform_source_loader_reads_supported_files_and_ignores_hidden(tmp_path):
    source_dir = tmp_path / "novel"
    source_dir.mkdir()
    (source_dir / "世界观.md").write_text("世界观设定", encoding="utf-8")
    (source_dir / "力量体系.md").write_text("力量体系设定", encoding="utf-8")
    (source_dir / "原文.txt").write_text("正文参考", encoding="utf-8")
    (source_dir / ".DS_Store").write_text("ignored", encoding="utf-8")
    (source_dir / "notes.pdf").write_text("ignored", encoding="utf-8")

    materials = generation_runner.load_source_materials(source_dir)

    assert [item.filename for item in materials] == ["世界观.md", "力量体系.md", "原文.txt"]
    assert [item.content for item in materials] == ["世界观设定", "力量体系设定", "正文参考"]
    assert all(item.char_count > 0 for item in materials)
    assert all(item.byte_count > 0 for item in materials)


def test_longform_options_default_volume1_distribution():
    options = GenerationRunOptions(
        acceptance_scope="real-longform-volume1",
        target_volumes=18,
        target_chapters=1200,
        target_word_count=2_000_000,
    )

    assert options.resolved_target_volume_chapters() == 67
    assert options.resolved_chapter_target_word_count() == 1667
    assert options.resolved_target_volume_word_count() == 111_689


def test_create_novel_payload_includes_genre_for_scope():
    assert generation_runner._build_create_novel_payload(
        "长篇",
        "real-longform-volume1",
    ) == {
        "title": "长篇",
        "primary_category_slug": "xuanhuan",
        "secondary_category_slug": "zhutian",
    }
    assert generation_runner._build_create_novel_payload("普通", "real-contract") == {
        "title": "普通",
        "primary_category_slug": "general",
        "secondary_category_slug": "uncategorized",
    }


def test_create_novel_payload_includes_default_genre_for_longform_runner():
    from novel_dev.testing.generation_runner import _build_create_novel_payload

    payload = _build_create_novel_payload("正式小说", acceptance_scope="real-longform-volume1")

    assert payload["title"] == "正式小说"
    assert payload["primary_category_slug"] == "xuanhuan"
    assert payload["secondary_category_slug"] == "zhutian"


def test_report_summary_includes_genre_resolution():
    from novel_dev.testing.generation_runner import _summarize_genre_report

    summary = _summarize_genre_report(
        {
            "genre": {"primary_name": "玄幻", "secondary_name": "诸天文"},
            "checkpoint_data": {
                "genre_template": {
                    "matched_templates": ["builtin:global:global:*:*:v1"],
                    "warnings": [],
                }
            },
        }
    )

    assert summary["genre"] == "玄幻 / 诸天文"
    assert summary["template_layers"] == 1
    assert summary["template_evidence_available"] is True


def test_report_summary_marks_missing_template_evidence():
    from novel_dev.testing.generation_runner import _summarize_genre_report

    summary = _summarize_genre_report(
        {"genre": {"primary_name": "都市", "secondary_name": "职场商战"}}
    )

    assert summary["genre"] == "都市 / 职场商战"
    assert summary["template_layers"] == 0
    assert summary["template_evidence_available"] is False


def test_report_summary_tolerates_malformed_payload():
    from novel_dev.testing.generation_runner import _summarize_genre_report

    summary = _summarize_genre_report({"genre": "bad", "checkpoint_data": "bad"})

    assert summary["genre"] == "通用 / 未分类"
    assert summary["template_layers"] == 0
    assert summary["template_warnings"] == []
    assert summary["template_evidence_available"] is False


@pytest.mark.asyncio
async def test_prepare_longform_synopsis_contract_sets_volume1_range(async_session):
    await NovelStateRepository(async_session).save_checkpoint(
        "novel-longform-contract",
        "volume_planning",
        {
            "synopsis_data": {
                "title": "长篇",
                "logline": "主角追索超脱。",
                "core_conflict": "主角 vs 末劫",
                "estimated_volumes": 6,
                "estimated_total_chapters": 450,
                "estimated_total_words": 1_350_000,
                "volume_outlines": [
                    {
                        "volume_number": 1,
                        "title": "第一卷",
                        "summary": "开局卷。",
                        "target_chapter_range": "1-30",
                    }
                ],
            }
        },
    )
    await async_session.commit()

    @asynccontextmanager
    async def fake_session_maker():
        yield async_session

    options = GenerationRunOptions(
        acceptance_scope="real-longform-volume1",
        source_dir="/tmp/novel",
        target_volumes=18,
        target_chapters=1200,
        target_word_count=2_000_000,
        target_volume_number=1,
        target_volume_chapters=67,
    )

    old_session_maker = generation_runner.async_session_maker
    generation_runner.async_session_maker = fake_session_maker
    try:
        await generation_runner._prepare_longform_synopsis_contract("novel-longform-contract", options)
    finally:
        generation_runner.async_session_maker = old_session_maker

    state = await NovelStateRepository(async_session).get_state("novel-longform-contract")
    synopsis = state.checkpoint_data["synopsis_data"]
    assert synopsis["estimated_volumes"] == 18
    assert synopsis["estimated_total_chapters"] == 1200
    assert synopsis["estimated_total_words"] == 2_000_000
    assert synopsis["volume_outlines"][0]["target_chapter_range"] == "1-67"
    assert state.checkpoint_data["acceptance_scope"] == "real-longform-volume1"


@pytest.mark.asyncio
async def test_prepare_longform_volume_plan_contract_sets_chapter_targets(async_session):
    await NovelStateRepository(async_session).save_checkpoint(
        "novel-longform-volume",
        "context_preparation",
        {
            "current_volume_plan": {
                "volume_id": "vol_1",
                "volume_number": 1,
                "title": "第一卷",
                "total_chapters": 2,
                "estimated_total_words": 6000,
                "chapters": [
                    {
                        "chapter_id": "vol_1_ch_1",
                        "chapter_number": 1,
                        "title": "一",
                        "summary": "一",
                        "target_word_count": 3000,
                        "beats": [{"summary": "a"}, {"summary": "b"}],
                    },
                    {
                        "chapter_id": "vol_1_ch_2",
                        "chapter_number": 2,
                        "title": "二",
                        "summary": "二",
                        "target_word_count": 3000,
                        "beats": [{"summary": "c"}],
                    },
                ],
            },
            "current_chapter_plan": {
                "chapter_id": "vol_1_ch_1",
                "chapter_number": 1,
                "title": "一",
                "summary": "一",
                "target_word_count": 3000,
                "beats": [{"summary": "a"}, {"summary": "b"}],
            },
        },
        current_volume_id="vol_1",
        current_chapter_id="vol_1_ch_1",
    )
    await async_session.commit()

    @asynccontextmanager
    async def fake_session_maker():
        yield async_session

    options = GenerationRunOptions(
        acceptance_scope="real-longform-volume1",
        source_dir="/tmp/novel",
        target_volumes=1,
        target_chapters=2,
        target_word_count=4000,
        target_volume_number=1,
        target_volume_chapters=2,
    )

    old_session_maker = generation_runner.async_session_maker
    generation_runner.async_session_maker = fake_session_maker
    try:
        await generation_runner._prepare_longform_volume_plan_contract("novel-longform-volume", options)
    finally:
        generation_runner.async_session_maker = old_session_maker

    state = await NovelStateRepository(async_session).get_state("novel-longform-volume")
    plan = state.checkpoint_data["current_volume_plan"]
    assert plan["estimated_total_words"] == 4000
    assert [chapter["target_word_count"] for chapter in plan["chapters"]] == [2000, 2000]
    assert [beat["target_word_count"] for beat in plan["chapters"][0]["beats"]] == [1000, 1000]
    assert state.checkpoint_data["current_chapter_plan"]["target_word_count"] == 2000


@pytest.mark.asyncio
async def test_prepare_longform_volume_plan_contract_expands_short_volume_plan(
    async_session,
):
    await NovelStateRepository(async_session).save_checkpoint(
        "novel-longform-expand",
        "context_preparation",
        {
            "current_volume_plan": {
                "volume_id": "vol_1",
                "volume_number": 1,
                "title": "第一卷",
                "total_chapters": 2,
                "chapters": [
                    {
                        "chapter_id": "vol_1_ch_1",
                        "chapter_number": 1,
                        "title": "起点",
                        "summary": "陆照获得线索。",
                        "beats": [{"summary": "a"}],
                    },
                    {
                        "chapter_id": "vol_1_ch_2",
                        "chapter_number": 2,
                        "title": "交锋",
                        "summary": "陆照与暗子交锋。",
                        "beats": [{"summary": "b"}],
                    },
                ],
            },
            "current_chapter_plan": {
                "chapter_id": "vol_1_ch_1",
                "chapter_number": 1,
                "title": "起点",
                "summary": "陆照获得线索。",
                "beats": [{"summary": "a"}],
            },
        },
        current_volume_id="vol_1",
        current_chapter_id="vol_1_ch_1",
    )
    await async_session.commit()

    @asynccontextmanager
    async def fake_session_maker():
        yield async_session

    old_session_maker = generation_runner.async_session_maker
    generation_runner.async_session_maker = fake_session_maker
    try:
        await generation_runner._prepare_longform_volume_plan_contract(
            "novel-longform-expand",
            GenerationRunOptions(
                acceptance_scope="real-longform-volume1",
                source_dir="/tmp/novel",
                target_volumes=1,
                target_chapters=5,
                target_word_count=5000,
                target_volume_number=1,
                target_volume_chapters=5,
            ),
        )
    finally:
        generation_runner.async_session_maker = old_session_maker

    state = await NovelStateRepository(async_session).get_state("novel-longform-expand")
    chapters = state.checkpoint_data["current_volume_plan"]["chapters"]
    assert len(chapters) == 5
    assert state.checkpoint_data["current_volume_plan"]["total_chapters"] == 5
    assert [chapter["chapter_id"] for chapter in chapters] == [
        "vol_1_ch_1",
        "vol_1_ch_2",
        "vol_1_ch_3",
        "vol_1_ch_4",
        "vol_1_ch_5",
    ]
    assert all(chapter["target_word_count"] == 1000 for chapter in chapters)
    assert any("只完成当前小目标" in chapter["summary"] for chapter in chapters)


@pytest.mark.asyncio
async def test_prepare_resume_state_can_reset_only_current_failed_chapter(
    async_session,
    monkeypatch,
):
    chapter_plan = {
        "chapter_id": "vol_1_ch_1",
        "chapter_number": 1,
        "title": "第一章",
        "summary": "章节概要",
        "beats": [{"summary": "进入主线"}],
    }
    await NovelStateRepository(async_session).save_checkpoint(
        "novel-resume",
        "fast_reviewing",
        {
            "current_chapter_plan": chapter_plan,
            "chapter_context": {"chapter_plan": chapter_plan, "notes": ["stale"]},
            "quality_gate": {"status": "block"},
            "flow_control": {"cancel_requested": True},
        },
        current_volume_id="vol-1",
        current_chapter_id="vol_1_ch_1",
    )
    chapter = await ChapterRepository(async_session).ensure_from_plan(
        "novel-resume",
        "vol-1",
        chapter_plan,
    )
    chapter.status = "edited"
    chapter.raw_draft = "raw"
    chapter.polished_text = "polished"
    chapter.quality_status = "block"
    chapter.quality_reasons = {"issues": ["old gate"]}
    await async_session.commit()

    @asynccontextmanager
    async def fake_session_maker():
        yield async_session

    monkeypatch.setattr(generation_runner, "async_session_maker", fake_session_maker)

    artifacts = await generation_runner._prepare_resume_state(
        "novel-resume",
        GenerationRunOptions(
            resume_novel_id="novel-resume",
            resume_from_stage="auto_run_chapters",
            resume_reset_current_chapter=True,
        ),
        resume_from_stage="auto_run_chapters",
    )

    state = await NovelStateRepository(async_session).get_state("novel-resume")
    reset_chapter = await ChapterRepository(async_session).get_by_id("vol_1_ch_1")
    assert artifacts["resume_reset_chapter_id"] == "vol_1_ch_1"
    assert artifacts["resume_cleared_flow_stop"] == "true"
    assert state.current_phase == "context_preparation"
    assert state.current_chapter_id == "vol_1_ch_1"
    assert "chapter_context" not in state.checkpoint_data
    assert "quality_gate" not in state.checkpoint_data
    assert "flow_control" not in state.checkpoint_data
    assert reset_chapter.status == "pending"
    assert reset_chapter.raw_draft is None
    assert reset_chapter.polished_text is None
    assert reset_chapter.quality_status == "unchecked"


@pytest.mark.asyncio
async def test_fake_longform_run_validates_source_dir_and_records_target_artifacts(tmp_path):
    source_dir = tmp_path / "novel"
    source_dir.mkdir()
    (source_dir / "世界观.md").write_text("世界观设定", encoding="utf-8")

    report = await run_generation_acceptance(
        GenerationRunOptions(
            llm_mode="fake",
            acceptance_scope="real-longform-volume1",
            source_dir=str(source_dir),
            target_volumes=18,
            target_chapters=1200,
            target_word_count=2_000_000,
        )
    )

    assert report.status == "passed"
    assert report.artifacts["target_volume_chapters"] == "67"
    assert report.artifacts["chapter_target_word_count"] == "1667"
    assert report.artifacts["source_material_count"] == "1"


def test_httpx_timeout_exception_is_internal_timeout_with_message():
    issue = classify_exception("generate_setting_review_batch", httpx.ReadTimeout(""), True)

    assert issue.type == "TIMEOUT_INTERNAL"
    assert issue.is_external_blocker is False
    assert issue.message == "ReadTimeout"


def test_provider_timeout_message_is_external_blocker():
    issue = classify_exception(
        "worldbuilding",
        LLMTimeoutError("provider request timed out in upstream queue"),
        True,
    )

    assert issue.type == "EXTERNAL_BLOCKED"
    assert issue.is_external_blocker is True


def test_internal_task_queue_timeout_is_system_timeout():
    issue = classify_exception(
        "orchestration",
        LLMTimeoutError("internal task queue timed out after 600s"),
        True,
    )

    assert issue.type == "TIMEOUT_INTERNAL"
    assert issue.is_external_blocker is False


@pytest.mark.asyncio
async def test_poll_generation_job_failed_includes_checkpoint_guard_evidence(monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(generation_runner.asyncio, "sleep", no_sleep)

    class FakeClient:
        async def get(self, path):
            request = httpx.Request("GET", f"http://test{path}")
            if path == "/api/novels/novel-test/generation_jobs/job-test":
                return httpx.Response(
                    200,
                    request=request,
                    json={
                        "job_id": "job-test",
                        "status": "failed",
                        "error_message": "Writer beat structure guard failed",
                        "result_payload": {
                            "stopped_reason": "failed",
                            "failed_phase": "drafting",
                            "failed_chapter_id": "ch-1",
                        },
                    },
                )
            if path == "/api/novels/novel-test/state":
                return httpx.Response(
                    200,
                    request=request,
                    json={
                        "checkpoint_data": {
                            "chapter_structure_guard": {
                                "mode": "writer_retry",
                                "beat_index": 2,
                                "passed": False,
                                "issues": ["提前写到后续节拍"],
                            },
                            "writer_guard_failures": [
                                {"mode": "writer", "beat_index": 2, "passed": False},
                                {"mode": "writer_retry", "beat_index": 2, "passed": False},
                            ],
                        }
                    },
                )
            raise AssertionError(f"Unexpected path: {path}")

    with pytest.raises(generation_runner.ContractValidationError) as exc_info:
        await generation_runner._poll_generation_job(
            FakeClient(),
            "novel-test",
            "job-test",
            failure_stage="auto_run_chapters",
        )

    error = exc_info.value
    assert error.stage == "auto_run_chapters"
    assert str(error) == "Writer beat structure guard failed"
    assert "result_payload.failed_phase=drafting" in error.evidence
    assert "writer_guard_failures_count=2" in error.evidence
    assert any(item.startswith("chapter_structure_guard=") for item in error.evidence)


def test_provider_queue_timeout_remains_external_blocker():
    issue = classify_exception(
        "worldbuilding",
        LLMTimeoutError("provider queue timeout from upstream"),
        True,
    )

    assert issue.type == "EXTERNAL_BLOCKED"
    assert issue.is_external_blocker is True


def test_runtime_parse_failure_is_llm_parse_error():
    issue = classify_exception(
        "chapter_draft",
        RuntimeError("LLM parse failed after 3 attempts"),
        True,
    )

    assert issue.type == "LLM_PARSE_ERROR"
    assert issue.is_external_blocker is False


def test_value_error_without_parse_marker_is_system_bug():
    issue = classify_exception("state_load", ValueError("Novel state not found"), False)

    assert issue.type == "SYSTEM_BUG"
    assert issue.is_external_blocker is False


def test_value_error_with_json_parse_marker_is_llm_parse_error():
    issue = classify_exception("chapter_draft", ValueError("JSON parse failed"), True)

    assert issue.type == "LLM_PARSE_ERROR"
    assert issue.is_external_blocker is False


def test_http_status_error_is_system_bug_even_with_json_message():
    request = httpx.Request("POST", "http://testserver/api/novels")
    response = httpx.Response(
        500,
        request=request,
        text="JSON validation failed inside API",
    )
    issue = classify_exception(
        "api_smoke_flow",
        httpx.HTTPStatusError(
            "JSON validation failed inside API",
            request=request,
            response=response,
        ),
        False,
    )

    assert issue.type == "SYSTEM_BUG"
    assert issue.is_external_blocker is False


def test_http_429_status_error_is_external_blocker():
    request = httpx.Request("POST", "http://testserver/api/novels")
    response = httpx.Response(429, request=request, text="rate limited")

    issue = classify_exception(
        "generate_setting_review_batch",
        httpx.HTTPStatusError(
            "rate limited",
            request=request,
            response=response,
        ),
        True,
    )

    assert issue.type == "EXTERNAL_BLOCKED"
    assert issue.is_external_blocker is True


def test_http_502_authentication_error_is_external_blocker():
    request = httpx.Request("POST", "http://testserver/api/novels/n/settings/sessions/s/reply")
    response = httpx.Response(
        502,
        request=request,
        text="AI 模型配置或认证失败：Error code: 401 - invalid API key",
    )

    issue = classify_exception(
        "advance_setting_session",
        httpx.HTTPStatusError(
            "bad gateway",
            request=request,
            response=response,
        ),
        True,
    )

    assert issue.type == "EXTERNAL_BLOCKED"
    assert issue.is_external_blocker is True


def test_http_504_without_external_marker_is_internal_timeout():
    request = httpx.Request("POST", "http://testserver/api/novels")
    response = httpx.Response(504, request=request, text="local worker timed out")

    issue = classify_exception(
        "volume_plan",
        httpx.HTTPStatusError(
            "local worker timed out",
            request=request,
            response=response,
        ),
        True,
    )

    assert issue.type == "TIMEOUT_INTERNAL"
    assert issue.is_external_blocker is False


def test_http_504_in_setting_generation_stage_remains_internal_timeout():
    request = httpx.Request(
        "POST",
        "http://testserver/api/novels/n/settings/sessions/s/generate",
    )
    response = httpx.Response(
        504,
        request=request,
        text="AI 生成设定审核记录超时，请稍后重试",
    )

    issue = classify_exception(
        "generate_setting_review_batch",
        httpx.HTTPStatusError(
            "gateway timeout",
            request=request,
            response=response,
        ),
        True,
    )

    assert issue.type == "TIMEOUT_INTERNAL"
    assert issue.is_external_blocker is False


def test_http_504_raise_for_status_generate_url_does_not_match_rate_marker():
    request = httpx.Request(
        "POST",
        "http://testserver/api/novels/n/settings/sessions/s/generate",
    )
    response = httpx.Response(
        504,
        request=request,
        text="AI 生成设定审核记录超时，请稍后重试",
    )

    with pytest.raises(httpx.HTTPStatusError) as raised:
        response.raise_for_status()

    issue = classify_exception(
        "generate_setting_review_batch",
        raised.value,
        True,
    )

    assert "generate" in str(raised.value)
    assert issue.type == "TIMEOUT_INTERNAL"
    assert issue.is_external_blocker is False


def test_fake_rerun_does_not_clear_system_failure():
    assert should_fake_rerun_affect_final_status("SYSTEM_BUG") is False
    assert should_fake_rerun_affect_final_status("TIMEOUT_INTERNAL") is False
    assert should_fake_rerun_affect_final_status("LLM_PARSE_ERROR") is False
    assert should_fake_rerun_affect_final_status("EXTERNAL_BLOCKED") is True


def test_options_default_to_real_then_fake_on_external_block():
    options = GenerationRunOptions()

    assert options.dataset == "minimal_builtin"
    assert options.llm_mode == "real_then_fake_on_external_block"
    assert options.acceptance_scope == "real-contract"
    assert options.stage is None
    assert options.run_id is None
    assert options.report_root == "reports/test-runs"
    assert options.api_base_url == "http://127.0.0.1:8000"
    assert options.resume_novel_id is None
    assert options.resume_from_stage is None
    assert options.resume_reset_current_chapter is False


def test_acceptance_scope_defaults_to_real_contract():
    assert GenerationRunOptions().acceptance_scope == "real-contract"


def test_validate_acceptance_scope_accepts_known_scopes():
    assert validate_acceptance_scope("real-contract") == "real-contract"
    assert validate_acceptance_scope("real-e2e-export") == "real-e2e-export"


def test_validate_acceptance_scope_rejects_unknown_scope():
    with pytest.raises(ValueError, match="Unknown acceptance scope"):
        validate_acceptance_scope("full")


def test_validate_resume_options_requires_novel_id_and_stage():
    with pytest.raises(ValueError, match="requires --resume-from-stage"):
        generation_runner.validate_resume_options(
            GenerationRunOptions(resume_novel_id="novel-1")
        )

    with pytest.raises(ValueError, match="requires --resume-novel-id"):
        generation_runner.validate_resume_options(
            GenerationRunOptions(resume_from_stage="auto_run_chapters")
        )


def test_validate_resume_options_rejects_stop_stage_before_resume_stage():
    with pytest.raises(ValueError, match="cannot be before"):
        generation_runner.validate_resume_options(
            GenerationRunOptions(
                stage="volume_plan",
                resume_novel_id="novel-1",
                resume_from_stage="auto_run_chapters",
            )
        )


def test_export_required_for_real_contract_only_when_archived():
    assert generation_runner._should_require_export("real-contract", archived_count=0) is False
    assert generation_runner._should_require_export("real-contract", archived_count=1) is True


def test_export_required_for_real_e2e_export_even_without_archive():
    assert generation_runner._should_require_export("real-e2e-export", archived_count=0) is True


def test_classify_exception_reproduce_command_preserves_acceptance_scope():
    issue = generation_runner.classify_exception(
        "volume_plan",
        RuntimeError("boom"),
        real_llm=True,
        acceptance_scope="real-e2e-export",
    )

    assert (
        issue.reproduce
        == "scripts/verify_generation_real.sh --acceptance-scope real-e2e-export --stage volume_plan"
    )


@pytest.mark.asyncio
async def test_run_stage_with_classification_runs_fake_diagnostic_for_external_blocker():
    calls = []

    async def real_step():
        calls.append("real")
        raise LLMRateLimitError("quota exhausted")

    async def fake_step():
        calls.append("fake")

    issue, fake_status = await run_stage_with_classification(
        "chapter_draft",
        real_step,
        fake_step,
    )

    assert calls == ["real", "fake"]
    assert issue is not None
    assert issue.type == "EXTERNAL_BLOCKED"
    assert issue.fake_rerun_status == "passed"
    assert fake_status == "passed"


@pytest.mark.asyncio
async def test_run_stage_with_classification_marks_http_external_fake_rerun_status():
    request = httpx.Request("POST", "http://testserver/api/novels/x/brainstorm")
    response = httpx.Response(429, request=request, text="rate limited")

    async def real_step():
        raise httpx.HTTPStatusError(
            "rate limited",
            request=request,
            response=response,
        )

    async def fake_step():
        return None

    issue, fake_status = await run_stage_with_classification(
        "brainstorm",
        real_step,
        fake_step,
    )

    assert issue is not None
    assert issue.type == "EXTERNAL_BLOCKED"
    assert issue.fake_rerun_status == "passed"
    assert fake_status == "passed"


@pytest.mark.asyncio
async def test_run_stage_with_classification_returns_none_on_real_success():
    calls = []

    async def real_step():
        calls.append("real")

    async def fake_step():
        calls.append("fake")

    issue, fake_status = await run_stage_with_classification(
        "chapter_draft",
        real_step,
        fake_step,
    )

    assert calls == ["real"]
    assert issue is None
    assert fake_status is None


@pytest.mark.asyncio
async def test_run_stage_with_classification_does_not_fake_rerun_non_external_issue():
    calls = []

    async def real_step():
        calls.append("real")
        raise RuntimeError("local invariant failed")

    async def fake_step():
        calls.append("fake")

    issue, fake_status = await run_stage_with_classification(
        "orchestration",
        real_step,
        fake_step,
    )

    assert calls == ["real"]
    assert issue is not None
    assert issue.type == "SYSTEM_BUG"
    assert issue.fake_rerun_status is None
    assert fake_status is None


@pytest.mark.asyncio
async def test_run_stage_with_classification_runs_fake_diagnostic_for_timeout_issue():
    request = httpx.Request("POST", "http://testserver/api/novels/n/documents/upload")
    response = httpx.Response(
        504,
        request=request,
        text="设定提取超时，请稍后重试或切换模型",
    )
    calls = []

    async def real_step():
        calls.append("real")
        raise httpx.HTTPStatusError(
            "gateway timeout",
            request=request,
            response=response,
        )

    async def fake_step():
        calls.append("fake")

    issue, fake_status = await run_stage_with_classification(
        "upload_seed_setting",
        real_step,
        fake_step,
    )

    assert calls == ["real", "fake"]
    assert issue is not None
    assert issue.type == "TIMEOUT_INTERNAL"
    assert issue.fake_rerun_status == "passed"
    assert fake_status == "passed"


@pytest.mark.asyncio
async def test_generation_acceptance_classifies_api_smoke_flow_failure(monkeypatch):
    async def fail_api_smoke_flow(options, fixture):
        raise RuntimeError("local API unavailable")

    monkeypatch.setattr(generation_runner, "_run_api_smoke_flow", fail_api_smoke_flow)

    report = await run_generation_acceptance(
        GenerationRunOptions(llm_mode="real", run_id="api-failure-test")
    )

    assert report.status == "failed"
    assert len(report.issues) == 1
    assert report.issues[0].stage == "api_smoke_flow"
    assert report.issues[0].type == "SYSTEM_BUG"
    assert report.issues[0].real_llm is False


@pytest.mark.asyncio
async def test_generation_acceptance_skips_export_contract_after_external_blocker(monkeypatch, tmp_path):
    source_dir = tmp_path / "novel"
    source_dir.mkdir()
    (source_dir / "世界观.md").write_text("世界观", encoding="utf-8")

    async def external_blocked_flow(_options, _fixture):
        issue = generation_runner.classify_exception(
            "advance_setting_session",
            LLMRateLimitError("quota exhausted"),
            real_llm=True,
            acceptance_scope="real-longform-volume1",
        )
        return {"acceptance_scope": "real-longform-volume1"}, [issue]

    monkeypatch.setattr(generation_runner, "_run_api_smoke_flow", external_blocked_flow)

    report = await run_generation_acceptance(
        GenerationRunOptions(
            llm_mode="real",
            acceptance_scope="real-longform-volume1",
            source_dir=str(source_dir),
            run_id="external-block-test",
        )
    )

    assert report.status == "external_blocked"
    assert [issue.stage for issue in report.issues] == ["advance_setting_session"]
    assert report.issues[0].reproduce == (
        "scripts/verify_generation_real.sh --acceptance-scope real-longform-volume1 "
        "--stage advance_setting_session"
    )


@pytest.mark.asyncio
async def test_generation_acceptance_threads_non_default_scope_into_artifacts_and_reproduce(
    monkeypatch,
):
    async def fail_api_smoke_flow(options, fixture):
        raise RuntimeError("local API unavailable")

    monkeypatch.setattr(generation_runner, "_run_api_smoke_flow", fail_api_smoke_flow)

    report = await run_generation_acceptance(
        GenerationRunOptions(
            llm_mode="real",
            acceptance_scope="real-e2e-export",
            run_id="api-failure-e2e-export-test",
        )
    )

    assert report.artifacts["contract_scope"] == "real-e2e-export"
    assert report.artifacts["acceptance_scope"] == "real-e2e-export"
    assert (
        report.issues[0].reproduce
        == "scripts/verify_generation_real.sh --acceptance-scope real-e2e-export"
    )


@pytest.mark.asyncio
async def test_fake_generation_diagnostic_failure_has_valid_reproduce_command(monkeypatch):
    def fail_fake_generation_diagnostic(fixture):
        raise RuntimeError("Fake diagnostic failed")

    monkeypatch.setattr(
        generation_runner,
        "_run_fake_generation_diagnostic",
        fail_fake_generation_diagnostic,
    )

    report = await run_generation_acceptance(
        GenerationRunOptions(llm_mode="fake", run_id="fake-failure-test")
    )

    assert report.status == "failed"
    assert len(report.issues) == 1
    assert report.issues[0].stage == "fake_generation_diagnostic"
    assert (
        report.issues[0].reproduce
        == "scripts/verify_generation_real.sh --llm-mode fake"
    )


@pytest.mark.asyncio
async def test_api_smoke_flow_replies_before_setting_generation(monkeypatch):
    calls = []
    client_kwargs = {}
    reply_payloads = []

    class FakeAsyncClient:
        def __init__(self, *, base_url, timeout, trust_env):
            self.base_url = str(base_url)
            self.timeout = timeout
            client_kwargs["base_url"] = self.base_url
            client_kwargs["timeout"] = timeout
            client_kwargs["trust_env"] = trust_env

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def get(self, path):
            calls.append(("GET", path, None))
            return self._response("GET", path, {"ok": True})

        async def post(self, path, json=None, params=None):
            calls.append(("POST", path, json or params))
            if path == "/api/novels":
                return self._response(
                    "POST",
                    path,
                    {
                        "novel_id": "novel-test",
                        "genre": {
                            "primary_name": "玄幻",
                            "secondary_name": "诸天文",
                        },
                        "checkpoint_data": {
                            "genre_template": {
                                "matched_templates": ["builtin:global:global:*:*:v1"],
                                "warnings": ["template warning"],
                            },
                        },
                    },
                )
            if path == "/api/novels/novel-test/settings/sessions":
                return self._response("POST", path, {"id": "session-test"})
            if path.endswith("/reply"):
                reply_payloads.append(json)
                if len(reply_payloads) == 1:
                    return self._response(
                        "POST",
                        path,
                        {
                            "session": {
                                "id": "session-test",
                                "status": "clarifying",
                                "clarification_round": 1,
                            },
                            "assistant_message": "请补充第一卷目标。",
                            "questions": ["第一卷目标是什么？"],
                        },
                    )
                return self._response(
                    "POST",
                    path,
                    {
                        "session": {
                            "id": "session-test",
                            "status": "ready_to_generate",
                            "clarification_round": 2,
                        },
                        "assistant_message": "可以生成",
                        "questions": [],
                    },
                )
            if path.endswith("/generate"):
                return self._response("POST", path, {"id": "batch-test"})
            raise AssertionError(f"Unexpected request: {path}")

        def _response(self, method, path, data):
            request = httpx.Request(method, f"http://testserver{path}")
            return httpx.Response(200, request=request, json=data)

    monkeypatch.setattr(generation_runner.httpx, "AsyncClient", FakeAsyncClient)
    fixture = generation_runner.load_generation_fixture("minimal_builtin")

    artifacts, issues = await generation_runner._run_api_smoke_flow(
        GenerationRunOptions(
            llm_mode="real",
            stage="generate_setting_review_batch",
        ),
        fixture,
    )

    paths = [path for _method, path, _payload in calls]
    assert issues == []
    assert paths == [
        "/healthz",
        "/api/novels",
        "/api/novels/novel-test/settings/sessions",
        "/api/novels/novel-test/settings/sessions/session-test/reply",
        "/api/novels/novel-test/settings/sessions/session-test/reply",
        "/api/novels/novel-test/settings/sessions/session-test/generate",
    ]
    assert artifacts["setting_session_id"] == "session-test"
    assert artifacts["setting_session_status"] == "ready_to_generate"
    assert artifacts["setting_clarification_round"] == "2"
    assert artifacts["review_batch_id"] == "batch-test"
    assert json.loads(artifacts["genre_template_summary"]) == {
        "genre": "玄幻 / 诸天文",
        "template_layers": 1,
        "template_warnings": ["template warning"],
        "template_evidence_available": True,
    }
    assert client_kwargs == {
        "base_url": "http://127.0.0.1:8000",
        "timeout": generation_runner.API_SMOKE_TIMEOUT_SECONDS,
        "trust_env": False,
    }
    assert len(reply_payloads) == 2
    assert "第一卷目标是什么？" in reply_payloads[1]["content"]


@pytest.mark.asyncio
async def test_api_smoke_flow_runs_auto_chapter_before_export(monkeypatch):
    calls = []
    job_polls = 0
    prepare_synopsis_calls = []
    prepare_calls = []

    class FakeChapter:
        polished_text = "polished generated chapter"
        raw_draft = None
        quality_status = "pass"
        quality_reasons = None

    class FakeAsyncClient:
        def __init__(self, *, base_url, timeout, trust_env):
            self.base_url = str(base_url)
            self.timeout = timeout
            self.trust_env = trust_env

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def get(self, path):
            nonlocal job_polls
            calls.append(("GET", path, None))
            if path == "/healthz":
                return self._response("GET", path, {"ok": True})
            if path == "/api/novels/novel-test/generation_jobs/job-test":
                job_polls += 1
                status = "running" if job_polls == 1 else "succeeded"
                payload = None if status == "running" else {
                    "completed_chapters": ["ch-1"],
                    "stopped_reason": "max_chapters_reached",
                }
                return self._response(
                    "GET",
                    path,
                    {
                        "job_id": "job-test",
                        "status": status,
                        "result_payload": payload,
                        "error_message": None,
                    },
                )
            if path == "/api/novels/novel-test/archive_stats":
                return self._response(
                    "GET",
                    path,
                    {"archived_chapter_count": 1, "total_word_count": 1200},
                )
            raise AssertionError(f"Unexpected GET request: {path}")

        async def post(self, path, json=None, params=None):
            calls.append(("POST", path, json or params))
            if path == "/api/novels":
                return self._response("POST", path, {"novel_id": "novel-test"})
            if path == "/api/novels/novel-test/settings/sessions":
                return self._response("POST", path, {"id": "session-test"})
            if path.endswith("/reply"):
                return self._response(
                    "POST",
                    path,
                    {
                        "session": {
                            "id": "session-test",
                            "status": "ready_to_generate",
                            "clarification_round": 1,
                        },
                        "assistant_message": "可以生成",
                        "questions": [],
                    },
                )
            if path.endswith("/generate"):
                return self._response("POST", path, {"id": "batch-test"})
            if path == "/api/novels/novel-test/documents/upload":
                return self._response("POST", path, {"pending_id": "pending-test"})
            if path == "/api/novels/novel-test/documents/pending/approve":
                return self._response("POST", path, {})
            if path == "/api/novels/novel-test/brainstorm":
                return self._response("POST", path, {})
            if path == "/api/novels/novel-test/volume_plan":
                return self._response("POST", path, {"volume_id": "vol-test"})
            if path == "/api/novels/novel-test/chapters/auto-run":
                return self._response("POST", path, {"job_id": "job-test", "status": "queued"})
            if path == "/api/novels/novel-test/export":
                return self._response("POST", path, {"exported_path": "./novel_output/novel-test/novel.md"})
            raise AssertionError(f"Unexpected POST request: {path}")

        def _response(self, method, path, data):
            request = httpx.Request(method, f"http://testserver{path}")
            return httpx.Response(200, request=request, json=data)

    async def immediate_sleep(_seconds):
        return None

    async def fake_prepare_minimal_synopsis(novel_id, fixture):
        prepare_synopsis_calls.append((novel_id, fixture.minimum_chapter_chars))
        return generation_runner.BrainstormContractResult(
            original_estimated_volumes=15,
            original_estimated_total_chapters=300,
            shrunk_estimated_total_chapters=1,
        )

    async def fake_prepare_minimal_chapter_plan(
        novel_id,
        fixture,
        *,
        volume_plan_response,
        acceptance_scope="real-contract",
    ):
        prepare_calls.append(
            (
                novel_id,
                fixture.minimum_chapter_chars,
                volume_plan_response,
                acceptance_scope,
            )
        )
        return generation_runner.MinimalChapterPlanResult(
            chapter_id="acceptance-novel-test-ch1",
            volume_id="acceptance-novel-test-vol1",
            source="current_volume_plan.chapters[0]",
            target_word_count=fixture.minimum_chapter_chars,
        )

    async def fake_get_chapter_contract_state(novel_id, chapter_id):
        return FakeChapter()

    monkeypatch.setattr(generation_runner.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(generation_runner.asyncio, "sleep", immediate_sleep)
    monkeypatch.setattr(
        generation_runner,
        "_prepare_minimal_synopsis",
        fake_prepare_minimal_synopsis,
    )
    monkeypatch.setattr(
        generation_runner,
        "_prepare_minimal_chapter_plan",
        fake_prepare_minimal_chapter_plan,
    )
    monkeypatch.setattr(
        generation_runner,
        "_get_chapter_contract_state",
        fake_get_chapter_contract_state,
    )
    fixture = generation_runner.load_generation_fixture("minimal_builtin")

    artifacts, issues = await generation_runner._run_api_smoke_flow(
        GenerationRunOptions(llm_mode="real"),
        fixture,
    )

    paths = [path for _method, path, _payload in calls]
    assert issues == []
    assert "/api/novels/novel-test/chapters/auto-run" in paths
    assert "/api/novels/novel-test/generation_jobs/job-test" in paths
    assert "/api/novels/novel-test/archive_stats" in paths
    assert prepare_synopsis_calls == [("novel-test", fixture.minimum_chapter_chars)]
    assert prepare_calls == [
        (
            "novel-test",
            fixture.minimum_chapter_chars,
            {"volume_id": "vol-test"},
            "real-contract",
        )
    ]
    assert artifacts["brainstorm_original_estimated_volumes"] == "15"
    assert artifacts["brainstorm_original_estimated_total_chapters"] == "300"
    assert artifacts["brainstorm_shrunk_estimated_total_chapters"] == "1"
    assert artifacts["chapter_id"] == "acceptance-novel-test-ch1"
    assert artifacts["chapter_plan_source"] == "current_volume_plan.chapters[0]"
    assert artifacts["chapter_target_word_count"] == str(fixture.minimum_chapter_chars)
    assert artifacts["volume_id"] == "vol-test"
    assert artifacts["chapter_auto_run_job_id"] == "job-test"
    assert artifacts["chapter_text_status"] == "polished_text"
    assert artifacts["chapter_text_length"] == str(len("polished generated chapter"))
    assert artifacts["quality_status"] == "pass"
    assert artifacts["archived_chapter_count"] == "1"
    assert artifacts["exported_path"] == "./novel_output/novel-test/novel.md"


@pytest.mark.asyncio
async def test_longform_volume1_flow_imports_sources_consolidates_and_generates_volume(
    monkeypatch,
    tmp_path,
):
    source_dir = tmp_path / "novel"
    source_dir.mkdir()
    (source_dir / "世界观.md").write_text("世界观设定", encoding="utf-8")
    (source_dir / "原文.txt").write_text("正文参考", encoding="utf-8")
    (source_dir / ".DS_Store").write_text("ignored", encoding="utf-8")
    calls = []

    class FakeChapter:
        raw_draft = "raw generated chapter"
        polished_text = "正文" * 900
        quality_status = "pass"
        quality_reasons = {}
        final_review_score = 82

    class FakeAsyncClient:
        def __init__(self, *, base_url, timeout, trust_env):
            self.base_url = str(base_url)
            self.timeout = timeout
            self.trust_env = trust_env

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def get(self, path):
            calls.append(("GET", path, None))
            if path == "/healthz":
                return self._response("GET", path, {"ok": True})
            if path == "/api/novels/novel-test/generation_jobs/job-consolidation":
                return self._response(
                    "GET",
                    path,
                    {
                        "job_id": "job-consolidation",
                        "status": "succeeded",
                        "result_payload": {"batch_id": "batch-consolidation"},
                    },
                )
            if path == "/api/novels/novel-test/generation_jobs/job-volume":
                return self._response(
                    "GET",
                    path,
                    {
                        "job_id": "job-volume",
                        "status": "succeeded",
                        "result_payload": {
                            "completed_chapters": [f"ch_{index}" for index in range(1, 68)],
                            "stopped_reason": "volume_completed",
                        },
                    },
                )
            if path == "/api/novels/novel-test/archive_stats":
                return self._response(
                    "GET",
                    path,
                    {"archived_chapter_count": 67, "total_word_count": 111689},
                )
            if path == "/api/novels/novel-test/settings/review_batches/batch-test":
                return self._response(
                    "GET",
                    path,
                    {
                        "batch": {"id": "batch-test", "status": "pending"},
                        "changes": [
                            {"id": "change-1", "target_type": "setting_card", "status": "pending"},
                            {"id": "change-conflict", "target_type": "conflict", "status": "pending"},
                        ],
                    },
                )
            if path == "/api/novels/novel-test/settings/review_batches/batch-consolidation":
                return self._response(
                    "GET",
                    path,
                    {
                        "batch": {"id": "batch-consolidation", "status": "pending"},
                        "changes": [
                            {"id": "change-2", "target_type": "setting_card", "status": "pending"},
                        ],
                    },
                )
            raise AssertionError(f"Unexpected GET request: {path}")

        async def post(self, path, json=None, params=None):
            payload = json if json is not None else params
            calls.append(("POST", path, payload))
            if path == "/api/novels":
                return self._response("POST", path, {"novel_id": "novel-test"})
            if path == "/api/novels/novel-test/settings/sessions":
                return self._response("POST", path, {"id": "session-test"})
            if path.endswith("/reply"):
                return self._response(
                    "POST",
                    path,
                    {
                        "session": {"id": "session-test", "status": "ready_to_generate"},
                        "questions": [],
                    },
                )
            if path.endswith("/generate"):
                return self._response("POST", path, {"id": "batch-test"})
            if path == "/api/novels/novel-test/settings/review_batches/batch-test/approve":
                assert payload == {"change_ids": ["change-1"], "approve_all": False}
                return self._response(
                    "POST",
                    path,
                    {"batch": {"id": "batch-test", "status": "partially_approved"}, "changes": []},
                )
            if path == "/api/novels/novel-test/documents/upload":
                return self._response("POST", path, {"id": f"pending-{payload['filename']}"})
            if path == "/api/novels/novel-test/documents/pending/approve":
                return self._response("POST", path, {})
            if path == "/api/novels/novel-test/settings/consolidations":
                return self._response("POST", path, {"job_id": "job-consolidation", "status": "queued"})
            if path == "/api/novels/novel-test/settings/review_batches/batch-consolidation/approve":
                assert payload == {"change_ids": ["change-2"], "approve_all": False}
                return self._response(
                    "POST",
                    path,
                    {"batch": {"id": "batch-consolidation", "status": "approved"}, "changes": []},
                )
            if path == "/api/novels/novel-test/brainstorm":
                return self._response("POST", path, {})
            if path == "/api/novels/novel-test/volume_plan":
                return self._response("POST", path, {"volume_id": "vol-test"})
            if path == "/api/novels/novel-test/chapters/auto-run":
                assert payload == {"max_chapters": 67, "stop_at_volume_end": True}
                return self._response("POST", path, {"job_id": "job-volume", "status": "queued"})
            if path == "/api/novels/novel-test/export":
                return self._response("POST", path, {"exported_path": "./novel_output/novel-test/novel.md"})
            raise AssertionError(f"Unexpected POST request: {path}")

        def _response(self, method, path, data):
            request = httpx.Request(method, f"http://testserver{path}")
            return httpx.Response(200, request=request, json=data)

    async def immediate_sleep(_seconds):
        return None

    async def fail_prepare_minimal_synopsis(*args, **kwargs):
        raise AssertionError("longform flow must not shrink synopsis")

    async def fail_prepare_minimal_chapter_plan(*args, **kwargs):
        raise AssertionError("longform flow must not shrink chapter plan")

    async def noop_prepare_longform_contract(*args, **kwargs):
        return None

    async def fake_get_chapter_contract_state(_novel_id, _chapter_id):
        return FakeChapter()

    monkeypatch.setattr(generation_runner.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(generation_runner.asyncio, "sleep", immediate_sleep)
    monkeypatch.setattr(generation_runner, "_prepare_minimal_synopsis", fail_prepare_minimal_synopsis)
    monkeypatch.setattr(generation_runner, "_prepare_minimal_chapter_plan", fail_prepare_minimal_chapter_plan)
    monkeypatch.setattr(generation_runner, "_prepare_longform_synopsis_contract", noop_prepare_longform_contract)
    monkeypatch.setattr(generation_runner, "_prepare_longform_volume_plan_contract", noop_prepare_longform_contract)
    monkeypatch.setattr(generation_runner, "_get_chapter_contract_state", fake_get_chapter_contract_state)
    fixture = generation_runner.load_generation_fixture("minimal_builtin")

    artifacts, issues = await generation_runner._run_api_smoke_flow(
        GenerationRunOptions(
            llm_mode="real",
            acceptance_scope="real-longform-volume1",
            source_dir=str(source_dir),
            target_volumes=18,
            target_chapters=1200,
            target_word_count=2_000_000,
        ),
        fixture,
    )

    assert issues == []
    upload_payloads = [
        payload for method, path, payload in calls
        if method == "POST" and path == "/api/novels/novel-test/documents/upload"
    ]
    assert [payload["filename"] for payload in upload_payloads] == ["世界观.md", "原文.txt"]
    assert ("POST", "/api/novels/novel-test/settings/consolidations", {"selected_pending_ids": []}) in calls
    assert artifacts["acceptance_scope"] == "real-longform-volume1"
    assert artifacts["generated_setting_approvable_change_count"] == "1"
    assert artifacts["generated_setting_conflict_change_count"] == "1"
    assert artifacts["generated_setting_batch_status"] == "partially_approved"
    assert artifacts["consolidated_setting_approvable_change_count"] == "1"
    assert artifacts["consolidated_setting_batch_status"] == "approved"
    assert artifacts["source_material_count"] == "2"
    assert artifacts["target_volume_chapters"] == "67"
    assert artifacts["chapter_auto_run_job_id"] == "job-volume"
    assert artifacts["completed_chapter_count"] == "67"
    assert artifacts["archived_chapter_count"] == "67"
    assert artifacts["total_word_count"] == "111689"


@pytest.mark.asyncio
async def test_resume_from_auto_run_skips_transient_setting_session_state(
    monkeypatch,
    tmp_path,
):
    source_dir = tmp_path / "novel"
    source_dir.mkdir()
    (source_dir / "世界观.md").write_text("世界观设定", encoding="utf-8")
    calls = []

    class FakeChapter:
        raw_draft = "raw"
        polished_text = "正文" * 900
        quality_status = "pass"
        quality_reasons = {}
        final_review_score = 82

    class FakeAsyncClient:
        def __init__(self, *, base_url, timeout, trust_env):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def get(self, path):
            calls.append(("GET", path))
            if path == "/healthz":
                return self._response("GET", path, {"ok": True})
            if path == "/api/novels/novel-resume/generation_jobs/job-resume":
                return self._response(
                    "GET",
                    path,
                    {
                        "job_id": "job-resume",
                        "status": "succeeded",
                        "result_payload": {
                            "completed_chapters": ["vol_1_ch_1"],
                            "stopped_reason": "max_chapters_reached",
                        },
                    },
                )
            if path == "/api/novels/novel-resume/archive_stats":
                return self._response(
                    "GET",
                    path,
                    {"archived_chapter_count": 67, "total_word_count": 111689},
                )
            raise AssertionError(f"Unexpected GET request: {path}")

        async def post(self, path, json=None, params=None):
            calls.append(("POST", path))
            if path == "/api/novels/novel-resume/chapters/auto-run":
                return self._response("POST", path, {"job_id": "job-resume"})
            raise AssertionError(f"Unexpected POST request: {path}")

        def _response(self, method, path, data):
            request = httpx.Request(method, f"http://testserver{path}")
            return httpx.Response(200, request=request, json=data)

    async def fake_prepare_resume_state(*args, **kwargs):
        return {"chapter_id": "vol_1_ch_1", "volume_id": "vol_1"}

    async def noop_prepare_longform_contract(*args, **kwargs):
        return None

    async def fake_get_chapter_contract_state(_novel_id, _chapter_id):
        return FakeChapter()

    async def immediate_sleep(_seconds):
        return None

    monkeypatch.setattr(generation_runner.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(generation_runner.asyncio, "sleep", immediate_sleep)
    monkeypatch.setattr(generation_runner, "_prepare_resume_state", fake_prepare_resume_state)
    monkeypatch.setattr(generation_runner, "_prepare_longform_synopsis_contract", noop_prepare_longform_contract)
    monkeypatch.setattr(generation_runner, "_prepare_longform_volume_plan_contract", noop_prepare_longform_contract)
    monkeypatch.setattr(generation_runner, "_get_chapter_contract_state", fake_get_chapter_contract_state)
    fixture = generation_runner.load_generation_fixture("minimal_builtin")

    artifacts, issues = await generation_runner._run_api_smoke_flow(
        GenerationRunOptions(
            llm_mode="real",
            acceptance_scope="real-longform-volume1",
            source_dir=str(source_dir),
            target_volumes=18,
            target_chapters=1200,
            target_word_count=2_000_000,
            resume_novel_id="novel-resume",
            resume_from_stage="auto_run_chapters",
            stage="auto_run_chapters",
        ),
        fixture,
    )

    assert issues == []
    assert artifacts["create_setting_session_status"] == "skipped_for_resume"
    assert artifacts["chapter_auto_run_job_id"] == "job-resume"
    assert artifacts["archived_chapter_count"] == "67"
    assert ("POST", "/api/novels/novel-resume/settings/sessions") not in calls


@pytest.mark.asyncio
async def test_api_smoke_flow_reports_quality_gate_when_text_exists_without_archive(
    monkeypatch,
):
    calls = []
    job_polls = 0

    class FakeChapter:
        raw_draft = "raw generated chapter"
        polished_text = "polished generated chapter"
        quality_status = "block"
        quality_reasons = {"word_count_drift": "too short"}

    class FakeAsyncClient:
        def __init__(self, *, base_url, timeout, trust_env):
            self.base_url = str(base_url)
            self.timeout = timeout
            self.trust_env = trust_env

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def get(self, path):
            nonlocal job_polls
            calls.append(("GET", path, None))
            if path == "/healthz":
                return self._response("GET", path, {"ok": True})
            if path == "/api/novels/novel-test/generation_jobs/job-test":
                job_polls += 1
                status = "running" if job_polls == 1 else "succeeded"
                return self._response(
                    "GET",
                    path,
                    {
                        "job_id": "job-test",
                        "status": status,
                        "result_payload": {
                            "completed_chapters": [],
                            "stopped_reason": "quality_blocked",
                        }
                        if status == "succeeded"
                        else None,
                    },
                )
            if path == "/api/novels/novel-test/archive_stats":
                return self._response("GET", path, {"archived_chapter_count": 0})
            raise AssertionError(f"Unexpected GET request: {path}")

        async def post(self, path, json=None, params=None):
            calls.append(("POST", path, json or params))
            if path == "/api/novels":
                return self._response("POST", path, {"novel_id": "novel-test"})
            if path == "/api/novels/novel-test/settings/sessions":
                return self._response("POST", path, {"id": "session-test"})
            if path.endswith("/reply"):
                return self._response(
                    "POST",
                    path,
                    {
                        "session": {
                            "status": "ready_to_generate",
                            "clarification_round": 1,
                        }
                    },
                )
            if path.endswith("/generate"):
                return self._response("POST", path, {"id": "batch-test"})
            if path == "/api/novels/novel-test/documents/upload":
                return self._response("POST", path, {"pending_id": "pending-test"})
            if path == "/api/novels/novel-test/documents/pending/approve":
                return self._response("POST", path, {})
            if path == "/api/novels/novel-test/brainstorm":
                return self._response("POST", path, {})
            if path == "/api/novels/novel-test/volume_plan":
                return self._response("POST", path, {"volume_id": "vol-test"})
            if path == "/api/novels/novel-test/chapters/auto-run":
                return self._response("POST", path, {"job_id": "job-test"})
            if path == "/api/novels/novel-test/export":
                raise AssertionError(
                    "default real-contract should not export after quality block"
                )
            raise AssertionError(f"Unexpected POST request: {path}")

        def _response(self, method, path, data):
            request = httpx.Request(method, f"http://testserver{path}")
            return httpx.Response(200, request=request, json=data)

    async def immediate_sleep(_seconds):
        return None

    async def fake_prepare_minimal_synopsis(novel_id, fixture):
        return generation_runner.BrainstormContractResult(
            original_estimated_volumes=15,
            original_estimated_total_chapters=300,
            shrunk_estimated_total_chapters=1,
        )

    async def fake_prepare_minimal_chapter_plan(
        novel_id,
        fixture,
        *,
        volume_plan_response,
        acceptance_scope="real-contract",
    ):
        return generation_runner.MinimalChapterPlanResult(
            chapter_id="acceptance-novel-test-ch1",
            volume_id="acceptance-novel-test-vol1",
            source="current_volume_plan.chapters[0]",
            target_word_count=fixture.minimum_chapter_chars,
        )

    async def fake_get_chapter_contract_state(novel_id, chapter_id):
        return FakeChapter()

    monkeypatch.setattr(generation_runner.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(generation_runner.asyncio, "sleep", immediate_sleep)
    monkeypatch.setattr(
        generation_runner,
        "_prepare_minimal_synopsis",
        fake_prepare_minimal_synopsis,
    )
    monkeypatch.setattr(
        generation_runner,
        "_prepare_minimal_chapter_plan",
        fake_prepare_minimal_chapter_plan,
    )
    monkeypatch.setattr(
        generation_runner,
        "_get_chapter_contract_state",
        fake_get_chapter_contract_state,
    )

    fixture = generation_runner.load_generation_fixture("minimal_builtin")
    artifacts, issues = await generation_runner._run_api_smoke_flow(
        GenerationRunOptions(llm_mode="real", acceptance_scope="real-contract"),
        fixture,
    )

    assert artifacts["chapter_text_status"] == "polished_text"
    assert artifacts["chapter_text_length"] == str(len("polished generated chapter"))
    assert artifacts["quality_status"] == "block"
    assert artifacts["quality_reasons"] == "word_count_drift"
    assert len(issues) == 1
    assert issues[0].stage == "quality_gate"
    assert issues[0].type == "GENERATION_QUALITY"
    assert issues[0].evidence == [
        "chapter_id=acceptance-novel-test-ch1",
        "job_id=job-test",
        "chapter_job_stopped_reason=quality_blocked",
        "archived_chapter_count=0",
        "quality_status=block",
        "quality_reasons=word_count_drift",
    ]
    assert (
        issues[0].reproduce
        == "scripts/verify_generation_real.sh --stage auto_run_chapters"
    )


@pytest.mark.asyncio
async def test_api_smoke_flow_real_e2e_export_reports_export_contract_without_archive(
    monkeypatch,
):
    calls = []
    job_polls = 0

    class FakeChapter:
        raw_draft = "raw generated chapter"
        polished_text = "polished generated chapter"
        quality_status = "block"
        quality_reasons = {"word_count_drift": "too short"}

    class FakeAsyncClient:
        def __init__(self, *, base_url, timeout, trust_env):
            self.base_url = str(base_url)
            self.timeout = timeout
            self.trust_env = trust_env

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def get(self, path):
            nonlocal job_polls
            calls.append(("GET", path, None))
            if path == "/healthz":
                return self._response("GET", path, {"ok": True})
            if path == "/api/novels/novel-test/generation_jobs/job-test":
                job_polls += 1
                status = "running" if job_polls == 1 else "succeeded"
                return self._response(
                    "GET",
                    path,
                    {
                        "job_id": "job-test",
                        "status": status,
                        "result_payload": {
                            "completed_chapters": [],
                            "stopped_reason": "quality_blocked",
                        }
                        if status == "succeeded"
                        else None,
                    },
                )
            if path == "/api/novels/novel-test/archive_stats":
                return self._response("GET", path, {"archived_chapter_count": 0})
            raise AssertionError(f"Unexpected GET request: {path}")

        async def post(self, path, json=None, params=None):
            calls.append(("POST", path, json or params))
            if path == "/api/novels":
                return self._response("POST", path, {"novel_id": "novel-test"})
            if path == "/api/novels/novel-test/settings/sessions":
                return self._response("POST", path, {"id": "session-test"})
            if path.endswith("/reply"):
                return self._response(
                    "POST",
                    path,
                    {
                        "session": {
                            "status": "ready_to_generate",
                            "clarification_round": 1,
                        }
                    },
                )
            if path.endswith("/generate"):
                return self._response("POST", path, {"id": "batch-test"})
            if path == "/api/novels/novel-test/documents/upload":
                return self._response("POST", path, {"pending_id": "pending-test"})
            if path == "/api/novels/novel-test/documents/pending/approve":
                return self._response("POST", path, {})
            if path == "/api/novels/novel-test/brainstorm":
                return self._response("POST", path, {})
            if path == "/api/novels/novel-test/volume_plan":
                return self._response("POST", path, {"volume_id": "vol-test"})
            if path == "/api/novels/novel-test/chapters/auto-run":
                return self._response("POST", path, {"job_id": "job-test"})
            if path == "/api/novels/novel-test/export":
                return self._response(
                    "POST",
                    path,
                    {"exported_path": "./novel_output/novel-test/novel.md"},
                )
            raise AssertionError(f"Unexpected POST request: {path}")

        def _response(self, method, path, data):
            request = httpx.Request(method, f"http://testserver{path}")
            return httpx.Response(200, request=request, json=data)

    async def immediate_sleep(_seconds):
        return None

    async def fake_prepare_minimal_synopsis(novel_id, fixture):
        return generation_runner.BrainstormContractResult(
            original_estimated_volumes=15,
            original_estimated_total_chapters=300,
            shrunk_estimated_total_chapters=1,
        )

    async def fake_prepare_minimal_chapter_plan(
        novel_id, fixture, *, volume_plan_response, acceptance_scope="real-contract"
    ):
        return generation_runner.MinimalChapterPlanResult(
            chapter_id="acceptance-novel-test-ch1",
            volume_id="acceptance-novel-test-vol1",
            source="current_volume_plan.chapters[0]",
            target_word_count=fixture.minimum_chapter_chars,
        )

    async def fake_get_chapter_contract_state(novel_id, chapter_id):
        return FakeChapter()

    monkeypatch.setattr(generation_runner.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(generation_runner.asyncio, "sleep", immediate_sleep)
    monkeypatch.setattr(
        generation_runner,
        "_prepare_minimal_synopsis",
        fake_prepare_minimal_synopsis,
    )
    monkeypatch.setattr(
        generation_runner,
        "_prepare_minimal_chapter_plan",
        fake_prepare_minimal_chapter_plan,
    )
    monkeypatch.setattr(
        generation_runner,
        "_get_chapter_contract_state",
        fake_get_chapter_contract_state,
    )

    fixture = generation_runner.load_generation_fixture("minimal_builtin")
    artifacts, issues = await generation_runner._run_api_smoke_flow(
        GenerationRunOptions(llm_mode="real", acceptance_scope="real-e2e-export"),
        fixture,
    )

    assert "exported_path" not in artifacts
    assert len(issues) == 2
    assert issues[0].stage == "quality_gate"
    assert issues[0].type == "GENERATION_QUALITY"
    assert issues[1].stage == "export_contract"
    assert (
        issues[0].reproduce
        == "scripts/verify_generation_real.sh --acceptance-scope real-e2e-export --stage auto_run_chapters"
    )
    assert issues[1].evidence == [
        "chapter_id=acceptance-novel-test-ch1",
        "job_id=job-test",
        "chapter_job_stopped_reason=quality_blocked",
        "archived_chapter_count=0",
        "quality_status=block",
        "quality_reasons=word_count_drift",
    ]
    assert (
        issues[1].reproduce
        == "scripts/verify_generation_real.sh --acceptance-scope real-e2e-export --stage export"
    )
    assert "/api/novels/novel-test/export" not in [
        path for _method, path, _payload in calls
    ]


@pytest.mark.asyncio
async def test_api_smoke_flow_real_e2e_export_runs_export_when_archive_exists(
    monkeypatch,
):
    calls = []
    job_polls = 0

    class FakeChapter:
        raw_draft = "raw generated chapter"
        polished_text = "polished generated chapter"
        quality_status = "pass"
        quality_reasons = None

    class FakeAsyncClient:
        def __init__(self, *, base_url, timeout, trust_env):
            self.base_url = str(base_url)
            self.timeout = timeout
            self.trust_env = trust_env

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def get(self, path):
            nonlocal job_polls
            calls.append(("GET", path, None))
            if path == "/healthz":
                return self._response("GET", path, {"ok": True})
            if path == "/api/novels/novel-test/generation_jobs/job-test":
                job_polls += 1
                status = "running" if job_polls == 1 else "succeeded"
                payload = None if status == "running" else {
                    "completed_chapters": ["ch-1"],
                    "stopped_reason": "max_chapters_reached",
                }
                return self._response(
                    "GET",
                    path,
                    {
                        "job_id": "job-test",
                        "status": status,
                        "result_payload": payload,
                        "error_message": None,
                    },
                )
            if path == "/api/novels/novel-test/archive_stats":
                return self._response(
                    "GET",
                    path,
                    {"archived_chapter_count": 1, "total_word_count": 1200},
                )
            raise AssertionError(f"Unexpected GET request: {path}")

        async def post(self, path, json=None, params=None):
            calls.append(("POST", path, json or params))
            if path == "/api/novels":
                return self._response("POST", path, {"novel_id": "novel-test"})
            if path == "/api/novels/novel-test/settings/sessions":
                return self._response("POST", path, {"id": "session-test"})
            if path.endswith("/reply"):
                return self._response(
                    "POST",
                    path,
                    {
                        "session": {
                            "status": "ready_to_generate",
                            "clarification_round": 1,
                        }
                    },
                )
            if path.endswith("/generate"):
                return self._response("POST", path, {"id": "batch-test"})
            if path == "/api/novels/novel-test/documents/upload":
                return self._response("POST", path, {"pending_id": "pending-test"})
            if path == "/api/novels/novel-test/documents/pending/approve":
                return self._response("POST", path, {})
            if path == "/api/novels/novel-test/brainstorm":
                return self._response("POST", path, {})
            if path == "/api/novels/novel-test/volume_plan":
                return self._response("POST", path, {"volume_id": "vol-test"})
            if path == "/api/novels/novel-test/chapters/auto-run":
                return self._response("POST", path, {"job_id": "job-test"})
            if path == "/api/novels/novel-test/export":
                return self._response(
                    "POST",
                    path,
                    {"exported_path": "./novel_output/novel-test/novel.md"},
                )
            raise AssertionError(f"Unexpected POST request: {path}")

        def _response(self, method, path, data):
            request = httpx.Request(method, f"http://testserver{path}")
            return httpx.Response(200, request=request, json=data)

    async def immediate_sleep(_seconds):
        return None

    async def fake_prepare_minimal_synopsis(novel_id, fixture):
        return generation_runner.BrainstormContractResult(
            original_estimated_volumes=15,
            original_estimated_total_chapters=300,
            shrunk_estimated_total_chapters=1,
        )

    async def fake_prepare_minimal_chapter_plan(
        novel_id, fixture, *, volume_plan_response, acceptance_scope="real-contract"
    ):
        return generation_runner.MinimalChapterPlanResult(
            chapter_id="acceptance-novel-test-ch1",
            volume_id="acceptance-novel-test-vol1",
            source="current_volume_plan.chapters[0]",
            target_word_count=fixture.minimum_chapter_chars,
        )

    async def fake_get_chapter_contract_state(novel_id, chapter_id):
        return FakeChapter()

    monkeypatch.setattr(generation_runner.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(generation_runner.asyncio, "sleep", immediate_sleep)
    monkeypatch.setattr(
        generation_runner,
        "_prepare_minimal_synopsis",
        fake_prepare_minimal_synopsis,
    )
    monkeypatch.setattr(
        generation_runner,
        "_prepare_minimal_chapter_plan",
        fake_prepare_minimal_chapter_plan,
    )
    monkeypatch.setattr(
        generation_runner,
        "_get_chapter_contract_state",
        fake_get_chapter_contract_state,
    )

    fixture = generation_runner.load_generation_fixture("minimal_builtin")
    artifacts, issues = await generation_runner._run_api_smoke_flow(
        GenerationRunOptions(llm_mode="real", acceptance_scope="real-e2e-export"),
        fixture,
    )

    assert issues == []
    assert artifacts["exported_path"] == "./novel_output/novel-test/novel.md"
    assert "/api/novels/novel-test/export" in [
        path for _method, path, _payload in calls
    ]


@pytest.mark.asyncio
async def test_generation_acceptance_reports_empty_export_as_export_contract(
    monkeypatch,
    tmp_path,
):
    export_path = tmp_path / "novel.md"
    export_path.write_text("", encoding="utf-8")

    async def ok_api_smoke_flow(options, fixture):
        return {
            "contract_scope": "real-e2e-export",
            "archived_chapter_count": "1",
            "exported_path": str(export_path),
        }, []

    monkeypatch.setattr(generation_runner, "_run_api_smoke_flow", ok_api_smoke_flow)

    report = await run_generation_acceptance(
        GenerationRunOptions(
            llm_mode="real",
            acceptance_scope="real-e2e-export",
            run_id="empty-export-test",
        )
    )

    assert report.status == "failed"
    assert len(report.issues) == 1
    assert report.issues[0].stage == "export_contract"
    assert report.issues[0].type == "SYSTEM_BUG"
    assert "empty" in report.issues[0].message.lower()


@pytest.mark.asyncio
async def test_generation_acceptance_reports_missing_export_path_as_export_contract(
    monkeypatch,
):
    async def ok_api_smoke_flow(options, fixture):
        return {
            "contract_scope": "real-e2e-export",
            "archived_chapter_count": "1",
        }, []

    monkeypatch.setattr(generation_runner, "_run_api_smoke_flow", ok_api_smoke_flow)

    report = await run_generation_acceptance(
        GenerationRunOptions(
            llm_mode="real",
            acceptance_scope="real-e2e-export",
            run_id="missing-export-path-test",
        )
    )

    assert report.status == "failed"
    assert len(report.issues) == 1
    assert report.issues[0].stage == "export_contract"
    assert report.issues[0].type == "SYSTEM_BUG"
    assert "missing" in report.issues[0].message.lower()


@pytest.mark.asyncio
async def test_build_generation_quality_snapshot_collects_checkpoint_chapters_and_setting_batch(
    async_session,
    monkeypatch,
):
    await NovelStateRepository(async_session).save_checkpoint(
        "novel-snapshot",
        "reviewing",
        {
            "synopsis_data": {"review_status": {"synopsis_quality_report": {"passed": True}}},
            "current_volume_plan": {
                "review_status": {"writability_status": {"passed": True, "failed_chapter_numbers": []}}
            },
        },
        current_volume_id="vol-1",
        current_chapter_id="ch-1",
    )
    chapter_repo = ChapterRepository(async_session)
    await chapter_repo.create(
        "ch-1",
        "vol-1",
        1,
        title="第一章",
        novel_id="novel-snapshot",
    )
    await chapter_repo.update_text("ch-1", raw_draft="draft text", polished_text="polished text")
    await chapter_repo.update_quality_gate(
        "ch-1",
        quality_status="pass",
        quality_reasons={"blocking_items": []},
        final_review_score=88,
    )
    await SettingWorkbenchRepository(async_session).create_review_batch(
        novel_id="novel-snapshot",
        source_type="ai_generation",
        input_snapshot={
            "setting_quality_report": {
                "passed": False,
                "missing_sections": ["power_system"],
            }
        },
    )
    await async_session.commit()

    @asynccontextmanager
    async def fake_session_maker():
        yield async_session

    monkeypatch.setattr(generation_runner, "async_session_maker", fake_session_maker)

    snapshot = await generation_runner._build_generation_quality_snapshot(
        TestRunReport(
            run_id="snapshot-run",
            entrypoint="scripts/verify_generation_real.sh",
            status="passed",
            duration_seconds=1.0,
            dataset="minimal_builtin",
            llm_mode="real",
            artifacts={"novel_id": "novel-snapshot"},
        )
    )

    assert snapshot is not None
    assert snapshot["novel_id"] == "novel-snapshot"
    assert snapshot["dataset"] == "minimal_builtin"
    assert snapshot["checkpoint"]["current_volume_id"] == "vol-1"
    assert snapshot["chapters"][0]["chapter_id"] == "ch-1"
    assert snapshot["chapters"][0]["quality_status"] == "pass"
    assert snapshot["setting_review_batch"]["input_snapshot"]["setting_quality_report"]["passed"] is False


@pytest.mark.asyncio
async def test_run_generation_acceptance_and_write_emits_snapshot_and_quality_summary(
    monkeypatch,
    tmp_path,
):
    async def fake_run_generation_acceptance(_options):
        return TestRunReport(
            run_id="quality-chain",
            entrypoint="scripts/verify_generation_real.sh",
            status="passed",
            duration_seconds=1.0,
            dataset="minimal_builtin",
            llm_mode="real",
            artifacts={"novel_id": "novel-chain"},
        )

    async def fake_build_generation_quality_snapshot(_report):
        return {
            "novel_id": "novel-chain",
            "dataset": "minimal_builtin",
            "llm_mode": "real",
            "checkpoint": {
                "setting_quality_report": {
                    "passed": False,
                    "missing_sections": ["power_system"],
                }
            },
            "chapters": [],
        }

    monkeypatch.setattr(generation_runner, "run_generation_acceptance", fake_run_generation_acceptance)
    monkeypatch.setattr(
        generation_runner,
        "_build_generation_quality_snapshot",
        fake_build_generation_quality_snapshot,
    )

    report = await generation_runner.run_generation_acceptance_and_write(
        GenerationRunOptions(
            run_id="quality-chain",
            report_root=str(tmp_path / "reports"),
        )
    )

    assert report.status == "failed"
    assert [issue.id for issue in report.issues] == ["SETTING-QUALITY-001"]
    root = tmp_path / "reports" / "quality-chain"
    snapshot_path = root / "artifacts" / "generation_snapshot.json"
    quality_summary_path = root / "quality-summary" / "summary.json"
    assert snapshot_path.exists()
    assert quality_summary_path.exists()
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    assert summary["artifacts"]["generation_snapshot_json"] == str(snapshot_path)
    assert summary["artifacts"]["quality_summary_json"] == str(quality_summary_path)
    assert summary["artifacts"]["quality_summary_status"] == "failed"


@pytest.mark.asyncio
async def test_run_generation_acceptance_and_write_skips_quality_summary_after_external_blocker(
    monkeypatch,
    tmp_path,
):
    async def fake_run_generation_acceptance(_options):
        report = TestRunReport(
            run_id="external-quality-skip",
            entrypoint="scripts/verify_generation_real.sh",
            status="passed",
            duration_seconds=1.0,
            dataset="minimal_builtin",
            llm_mode="real",
            artifacts={"novel_id": "novel-external"},
        )
        report.add_issue(
            generation_runner.classify_exception(
                "advance_setting_session",
                LLMRateLimitError("quota exhausted"),
                real_llm=True,
            )
        )
        return report

    async def fail_build_generation_quality_snapshot(_report):
        raise AssertionError("quality summary should be skipped after external blockers")

    monkeypatch.setattr(generation_runner, "run_generation_acceptance", fake_run_generation_acceptance)
    monkeypatch.setattr(
        generation_runner,
        "_build_generation_quality_snapshot",
        fail_build_generation_quality_snapshot,
    )

    report = await generation_runner.run_generation_acceptance_and_write(
        GenerationRunOptions(
            run_id="external-quality-skip",
            report_root=str(tmp_path / "reports"),
        )
    )

    assert report.status == "external_blocked"
    assert report.artifacts["quality_summary_status"] == "skipped_external_blocker"
    root = tmp_path / "reports" / "external-quality-skip"
    assert (root / "summary.json").exists()
    assert not (root / "quality-summary" / "summary.json").exists()


@pytest.mark.asyncio
async def test_prepare_minimal_synopsis_returns_original_scale_artifacts(
    async_session,
    monkeypatch,
):
    await NovelStateRepository(async_session).save_checkpoint(
        "novel-test",
        "volume_planning",
        {
            "synopsis_data": {
                "title": "Long Story",
                "logline": "A long logline",
                "estimated_volumes": 15,
                "estimated_total_chapters": 300,
                "estimated_total_words": 900000,
                "volume_outlines": [
                    {
                        "volume_number": 1,
                        "title": "Volume One",
                        "summary": "Summary",
                        "target_chapter_range": "20-24",
                    }
                ],
            }
        },
    )
    await async_session.commit()

    @asynccontextmanager
    async def fake_session_maker():
        yield async_session

    monkeypatch.setattr(generation_runner, "async_session_maker", fake_session_maker)
    fixture = generation_runner.load_generation_fixture("minimal_builtin")

    result = await generation_runner._prepare_minimal_synopsis("novel-test", fixture)

    assert result.original_estimated_volumes == 15
    assert result.original_estimated_total_chapters == 300
    assert result.shrunk_estimated_total_chapters == 1


@pytest.mark.asyncio
async def test_prepare_minimal_chapter_plan_rekeys_ids_and_resets_chapter(
    async_session,
    monkeypatch,
):
    await ChapterRepository(async_session).create(
        "vol_1_ch_1",
        "vol-1",
        1,
        "Old Chapter",
        novel_id="other-novel",
    )
    await ChapterRepository(async_session).update_text(
        "vol_1_ch_1",
        raw_draft="old raw",
        polished_text="old polished",
    )
    await ChapterRepository(async_session).update_status("vol_1_ch_1", "edited")
    await NovelStateRepository(async_session).save_checkpoint(
        "novel-test",
        "context_preparation",
        {
            "current_volume_plan": {
                "volume_id": "vol-1",
                "total_chapters": 2,
                "estimated_total_words": 6000,
                "chapters": [
                    {
                        "chapter_id": "vol_1_ch_1",
                        "chapter_number": 1,
                        "title": "New Chapter",
                        "summary": "Summary",
                        "target_word_count": 3000,
                        "beats": [
                            {"summary": "beat", "target_word_count": 2500},
                            {"summary": "beat 2", "target_word_count": 3000},
                        ],
                    },
                    {
                        "chapter_id": "vol_1_ch_2",
                        "chapter_number": 2,
                        "title": "Other",
                        "summary": "Other",
                        "target_word_count": 3000,
                        "beats": [{"summary": "beat"}],
                    },
                ],
            },
            "current_chapter_plan": {
                "chapter_id": "vol_1_ch_1",
                "chapter_number": 1,
                "title": "New Chapter",
                "summary": "Summary",
                "target_word_count": 3000,
                "beats": [
                    {"summary": "beat", "target_word_count": 2500},
                    {"summary": "beat 2", "target_word_count": 3000},
                ],
            },
        },
        current_volume_id="vol-1",
        current_chapter_id="vol_1_ch_1",
    )
    await async_session.commit()

    @asynccontextmanager
    async def fake_session_maker():
        yield async_session

    monkeypatch.setattr(generation_runner, "async_session_maker", fake_session_maker)
    fixture = generation_runner.load_generation_fixture("minimal_builtin")

    target = await generation_runner._prepare_minimal_chapter_plan(
        "novel-test",
        fixture,
        volume_plan_response={"volume_id": "vol-1"},
    )

    assert (
        target.target_word_count
        == generation_runner._acceptance_target_word_count(fixture)
    )
    assert target.chapter_id == "acceptance-novel-test-ch1"
    assert target.source == "current_chapter_plan"

    state = await NovelStateRepository(async_session).get_state("novel-test")
    assert state.current_phase == "context_preparation"
    assert state.current_volume_id == "acceptance-novel-test-vol1"
    assert state.current_chapter_id == "acceptance-novel-test-ch1"
    assert (
        state.checkpoint_data["current_chapter_plan"]["target_word_count"]
        == generation_runner._acceptance_target_word_count(fixture)
    )
    assert (
        state.checkpoint_data["current_chapter_plan"]["chapter_id"]
        == "acceptance-novel-test-ch1"
    )
    assert state.checkpoint_data["acceptance_scope"] == "real-contract"
    beat_targets = [
        beat.get("target_word_count")
        for beat in state.checkpoint_data["current_chapter_plan"]["beats"]
    ]
    assert beat_targets == [500, 500]

    isolated = await ChapterRepository(async_session).get_by_id("acceptance-novel-test-ch1")
    assert isolated is not None
    assert isolated.novel_id == "novel-test"
    assert isolated.volume_id == "acceptance-novel-test-vol1"
    assert isolated.status == "pending"
    assert isolated.raw_draft is None
    assert isolated.polished_text is None


@pytest.mark.asyncio
async def test_prepare_minimal_chapter_plan_uses_volume_plan_chapter_when_current_chapter_missing(
    async_session,
    monkeypatch,
):
    await NovelStateRepository(async_session).save_checkpoint(
        "novel-test",
        "volume_planning",
        {
            "current_volume_plan": {
                "volume_id": "vol-1",
                "total_chapters": 1,
                "chapters": [
                    {
                        "chapter_id": "vol_1_ch_1",
                        "chapter_number": 1,
                        "title": "From Volume Plan",
                        "summary": "A usable generated chapter summary",
                        "beats": [
                            {"summary": "beat", "target_word_count": 2500},
                            {"summary": "beat 2", "target_word_count": 3000},
                        ],
                    }
                ],
            }
        },
        current_volume_id="vol-1",
        current_chapter_id=None,
    )
    await async_session.commit()

    @asynccontextmanager
    async def fake_session_maker():
        yield async_session

    monkeypatch.setattr(generation_runner, "async_session_maker", fake_session_maker)
    fixture = generation_runner.load_generation_fixture("minimal_builtin")

    result = await generation_runner._prepare_minimal_chapter_plan(
        "novel-test",
        fixture,
        volume_plan_response={"volume_id": "vol-1"},
    )

    assert (
        result.target_word_count
        == generation_runner._acceptance_target_word_count(fixture)
    )
    assert result.chapter_id == "acceptance-novel-test-ch1"
    assert result.source == "current_volume_plan.chapters[0]"
    state = await NovelStateRepository(async_session).get_state("novel-test")
    assert state.current_phase == "context_preparation"
    assert state.current_volume_id == "acceptance-novel-test-vol1"
    assert state.current_chapter_id == "acceptance-novel-test-ch1"
    assert state.checkpoint_data["acceptance_scope"] == "real-contract"
    beat_targets = [
        beat.get("target_word_count")
        for beat in state.checkpoint_data["current_chapter_plan"]["beats"]
    ]
    assert beat_targets == [500, 500]


@pytest.mark.asyncio
async def test_prepare_minimal_chapter_plan_reports_contract_evidence_when_missing(
    async_session,
    monkeypatch,
):
    await NovelStateRepository(async_session).save_checkpoint(
        "novel-test",
        "volume_planning",
        {"current_volume_plan": {"volume_id": "vol-1", "chapters": []}},
    )
    await async_session.commit()

    @asynccontextmanager
    async def fake_session_maker():
        yield async_session

    monkeypatch.setattr(generation_runner, "async_session_maker", fake_session_maker)
    fixture = generation_runner.load_generation_fixture("minimal_builtin")

    with pytest.raises(generation_runner.ContractValidationError) as error:
        await generation_runner._prepare_minimal_chapter_plan(
            "novel-test",
            fixture,
            volume_plan_response={"volume_id": "vol-1"},
        )

    assert error.value.stage == "volume_plan_contract"
    assert "current_volume_plan_chapter_count=0" in error.value.evidence


@pytest.mark.asyncio
async def test_prepare_minimal_chapter_plan_fails_when_volume_plan_review_failed(
    async_session,
    monkeypatch,
):
    await NovelStateRepository(async_session).save_checkpoint(
        "novel-test",
        "volume_planning",
        {
            "current_volume_plan": {
                "volume_id": "vol-1",
                "chapters": [
                    {
                        "chapter_id": "vol_1_ch_1",
                        "chapter_number": 1,
                        "title": "第一章",
                        "summary": "章节概要",
                        "beats": [{"summary": "节拍"}],
                    }
                ],
                "review_status": {
                    "status": "revise_failed",
                    "reason": "已达最大自动修订次数，请人工处理。",
                    "attempt": 3,
                },
            }
        },
    )
    await async_session.commit()

    @asynccontextmanager
    async def fake_session_maker():
        yield async_session

    monkeypatch.setattr(generation_runner, "async_session_maker", fake_session_maker)
    fixture = generation_runner.load_generation_fixture("minimal_builtin")

    with pytest.raises(generation_runner.ContractValidationError) as error:
        await generation_runner._prepare_minimal_chapter_plan(
            "novel-test",
            fixture,
            volume_plan_response={"volume_id": "vol-1"},
        )

    assert error.value.stage == "volume_plan_contract"
    assert "review_status_status=revise_failed" in error.value.evidence
    assert "review_status_reason=已达最大自动修订次数，请人工处理。" in error.value.evidence


def test_classify_exception_preserves_contract_validation_stage_and_evidence():
    issue = generation_runner.classify_exception(
        "volume_plan",
        generation_runner.ContractValidationError(
            "volume_plan_contract",
            "volume_plan did not produce a usable chapter plan",
            ["current_volume_plan_chapter_count=0"],
        ),
        real_llm=True,
    )

    assert issue.type == "SYSTEM_BUG"
    assert issue.stage == "volume_plan_contract"
    assert issue.evidence == ["current_volume_plan_chapter_count=0"]
    assert (
        issue.reproduce
        == "scripts/verify_generation_real.sh --stage volume_plan"
    )


@pytest.mark.asyncio
async def test_prepare_minimal_synopsis_reports_contract_failure_for_non_mapping_synopsis(
    async_session,
    monkeypatch,
):
    await NovelStateRepository(async_session).save_checkpoint(
        "novel-test",
        "volume_planning",
        {"synopsis_data": ["not", "a", "mapping"]},
    )
    await async_session.commit()

    @asynccontextmanager
    async def fake_session_maker():
        yield async_session

    monkeypatch.setattr(generation_runner, "async_session_maker", fake_session_maker)
    fixture = generation_runner.load_generation_fixture("minimal_builtin")

    with pytest.raises(generation_runner.ContractValidationError) as error:
        await generation_runner._prepare_minimal_synopsis("novel-test", fixture)

    assert error.value.stage == "brainstorm_contract"
    assert "checkpoint_keys=synopsis_data" in error.value.evidence
    assert "synopsis_type=list" in error.value.evidence


@pytest.mark.asyncio
async def test_prepare_minimal_synopsis_reports_contract_failure_for_malformed_volume_outlines(
    async_session,
    monkeypatch,
):
    await NovelStateRepository(async_session).save_checkpoint(
        "novel-test",
        "volume_planning",
        {
            "synopsis_data": {
                "title": "Long Story",
                "logline": "A long logline",
                "estimated_volumes": 15,
                "estimated_total_chapters": 300,
                "volume_outlines": "not-a-list",
            }
        },
    )
    await async_session.commit()

    @asynccontextmanager
    async def fake_session_maker():
        yield async_session

    monkeypatch.setattr(generation_runner, "async_session_maker", fake_session_maker)
    fixture = generation_runner.load_generation_fixture("minimal_builtin")

    with pytest.raises(generation_runner.ContractValidationError) as error:
        await generation_runner._prepare_minimal_synopsis("novel-test", fixture)

    assert error.value.stage == "brainstorm_contract"
    assert "synopsis_keys=estimated_total_chapters,estimated_volumes,logline,title,volume_outlines" in error.value.evidence
    assert "volume_outlines_type=str" in error.value.evidence


@pytest.mark.asyncio
async def test_prepare_minimal_synopsis_reports_contract_failure_for_non_mapping_outline_item(
    async_session,
    monkeypatch,
):
    await NovelStateRepository(async_session).save_checkpoint(
        "novel-test",
        "volume_planning",
        {
            "synopsis_data": {
                "title": "Long Story",
                "logline": "A long logline",
                "estimated_volumes": 15,
                "estimated_total_chapters": 300,
                "volume_outlines": ["not-a-mapping"],
            }
        },
    )
    await async_session.commit()

    @asynccontextmanager
    async def fake_session_maker():
        yield async_session

    monkeypatch.setattr(generation_runner, "async_session_maker", fake_session_maker)
    fixture = generation_runner.load_generation_fixture("minimal_builtin")

    with pytest.raises(generation_runner.ContractValidationError) as error:
        await generation_runner._prepare_minimal_synopsis("novel-test", fixture)

    assert error.value.stage == "brainstorm_contract"
    assert "volume_outlines_type=list" in error.value.evidence
    assert "first_volume_outline_type=str" in error.value.evidence


@pytest.mark.asyncio
async def test_prepare_minimal_synopsis_shrinks_scope(
    async_session,
    monkeypatch,
):
    await NovelStateRepository(async_session).save_checkpoint(
        "novel-test",
        "volume_planning",
        {
            "synopsis_data": {
                "title": "Long Story",
                "logline": "A long logline",
                "core_conflict": "conflict",
                "estimated_volumes": 15,
                "estimated_total_chapters": 300,
                "estimated_total_words": 900000,
                "volume_outlines": [
                    {
                        "volume_number": 1,
                        "title": "Volume One",
                        "summary": "Summary",
                        "target_chapter_range": "20-24",
                    },
                    {
                        "volume_number": 2,
                        "title": "Volume Two",
                        "summary": "Summary 2",
                        "target_chapter_range": "20-24",
                    },
                ],
            }
        },
    )
    await async_session.commit()

    @asynccontextmanager
    async def fake_session_maker():
        yield async_session

    monkeypatch.setattr(generation_runner, "async_session_maker", fake_session_maker)
    fixture = generation_runner.load_generation_fixture("minimal_builtin")

    await generation_runner._prepare_minimal_synopsis("novel-test", fixture)

    state = await NovelStateRepository(async_session).get_state("novel-test")
    synopsis = state.checkpoint_data["synopsis_data"]
    assert synopsis["estimated_volumes"] == 1
    assert synopsis["estimated_total_chapters"] == 1
    assert (
        synopsis["estimated_total_words"]
        == generation_runner._acceptance_target_word_count(fixture)
    )
    assert len(synopsis["volume_outlines"]) == 1
    assert synopsis["volume_outlines"][0]["target_chapter_range"] == "1-1"


@pytest.mark.asyncio
async def test_prepare_minimal_chapter_plan_syncs_volume_plan_when_response_chapter_is_source(
    async_session,
    monkeypatch,
):
    await NovelStateRepository(async_session).save_checkpoint(
        "novel-test",
        "volume_planning",
        {
            "current_volume_plan": {
                "volume_id": "vol-1",
                "total_chapters": 1,
                "chapters": [
                    {
                        "chapter_id": "stale-chapter",
                        "chapter_number": 1,
                        "title": "",
                        "summary": "",
                    }
                ],
            }
        },
        current_volume_id="vol-1",
        current_chapter_id=None,
    )
    await async_session.commit()

    @asynccontextmanager
    async def fake_session_maker():
        yield async_session

    monkeypatch.setattr(generation_runner, "async_session_maker", fake_session_maker)
    fixture = generation_runner.load_generation_fixture("minimal_builtin")

    result = await generation_runner._prepare_minimal_chapter_plan(
        "novel-test",
        fixture,
        volume_plan_response={
            "volume_id": "vol-1",
            "chapter": {
                "chapter_id": "response-chapter",
                "chapter_number": 7,
                "title": "Response Title",
                "summary": "Response summary",
                "beats": [{"summary": "beat"}],
            },
        },
    )

    assert result.source == "response.chapter"

    state = await NovelStateRepository(async_session).get_state("novel-test")
    current_chapter_plan = state.checkpoint_data["current_chapter_plan"]
    volume_chapter = state.checkpoint_data["current_volume_plan"]["chapters"][0]
    assert current_chapter_plan["title"] == "Response Title"
    assert volume_chapter["title"] == "Response Title"
    assert current_chapter_plan["summary"] == "Response summary"
    assert volume_chapter["summary"] == "Response summary"
    assert current_chapter_plan["chapter_id"] == "acceptance-novel-test-ch1"
    assert volume_chapter["chapter_id"] == "acceptance-novel-test-ch1"
