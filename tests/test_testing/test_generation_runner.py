import httpx
import pytest

from novel_dev.llm.exceptions import LLMRateLimitError, LLMTimeoutError
from novel_dev.testing import generation_runner
from novel_dev.testing.generation_runner import (
    GenerationRunOptions,
    classify_exception,
    run_generation_acceptance,
    run_stage_with_classification,
    should_fake_rerun_affect_final_status,
)


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
    assert issue.reproduce == "scripts/verify_generation_real.sh --stage chapter_draft"


def test_internal_timeout_message_is_system_timeout():
    issue = classify_exception("preflight", LLMTimeoutError("local watchdog elapsed"), False)

    assert issue.type == "TIMEOUT_INTERNAL"
    assert issue.is_external_blocker is False
    assert issue.real_llm is False


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


def test_fake_rerun_does_not_clear_system_failure():
    assert should_fake_rerun_affect_final_status("SYSTEM_BUG") is False
    assert should_fake_rerun_affect_final_status("TIMEOUT_INTERNAL") is False
    assert should_fake_rerun_affect_final_status("LLM_PARSE_ERROR") is False
    assert should_fake_rerun_affect_final_status("EXTERNAL_BLOCKED") is True


def test_options_default_to_real_then_fake_on_external_block():
    options = GenerationRunOptions()

    assert options.dataset == "minimal_builtin"
    assert options.llm_mode == "real_then_fake_on_external_block"
    assert options.stage is None
    assert options.run_id is None
    assert options.report_root == "reports/test-runs"
    assert options.api_base_url == "http://127.0.0.1:8000"


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
