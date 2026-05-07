from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from novel_dev.llm.exceptions import LLMRateLimitError, LLMTimeoutError
from novel_dev.testing.report import Issue, IssueType


LLMMode = Literal["fake", "real", "real_then_fake_on_external_block"]


@dataclass(frozen=True, slots=True)
class GenerationRunOptions:
    dataset: str = "minimal_builtin"
    llm_mode: LLMMode = "real_then_fake_on_external_block"
    stage: str | None = None
    run_id: str | None = None
    report_root: str = "reports/test-runs"
    api_base_url: str = "http://127.0.0.1:8000"


def _timeout_is_external(message: str) -> bool:
    markers = ("provider", "upstream", "rate", "quota", "network")
    normalized = message.lower()
    return any(marker in normalized for marker in markers)


def _exception_is_parse_failure(message: str) -> bool:
    markers = ("parse", "json", "validation")
    normalized = message.lower()
    return any(marker in normalized for marker in markers)


def classify_exception(stage: str, exc: Exception, real_llm: bool) -> Issue:
    issue_type: IssueType
    is_external_blocker = False

    if isinstance(exc, LLMRateLimitError):
        issue_type = "EXTERNAL_BLOCKED"
        is_external_blocker = True
    elif isinstance(exc, LLMTimeoutError):
        if _timeout_is_external(str(exc)):
            issue_type = "EXTERNAL_BLOCKED"
            is_external_blocker = True
        else:
            issue_type = "TIMEOUT_INTERNAL"
    elif _exception_is_parse_failure(str(exc)):
        issue_type = "LLM_PARSE_ERROR"
    else:
        issue_type = "SYSTEM_BUG"

    return Issue(
        id=f"{issue_type}-{stage}",
        type=issue_type,
        severity="high",
        stage=stage,
        is_external_blocker=is_external_blocker,
        real_llm=real_llm,
        fake_rerun_status=None,
        message=str(exc),
        evidence=[],
        reproduce=f"scripts/verify_generation_real.sh --stage {stage}",
    )


def should_fake_rerun_affect_final_status(issue_type: IssueType) -> bool:
    return issue_type == "EXTERNAL_BLOCKED"
