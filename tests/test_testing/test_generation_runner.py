from novel_dev.llm.exceptions import LLMRateLimitError, LLMTimeoutError
from novel_dev.testing.generation_runner import (
    GenerationRunOptions,
    classify_exception,
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
