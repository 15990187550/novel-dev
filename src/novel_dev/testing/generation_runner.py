from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable, Literal

import httpx
from novel_dev.llm.exceptions import LLMRateLimitError, LLMTimeoutError
from novel_dev.testing.fixtures import GenerationFixture, load_generation_fixture
from novel_dev.testing.report import Issue, IssueType, ReportWriter, TestRunReport


LLMMode = Literal["fake", "real", "real_then_fake_on_external_block"]
Step = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class GenerationRunOptions:
    dataset: str = "minimal_builtin"
    llm_mode: LLMMode = "real_then_fake_on_external_block"
    stage: str | None = None
    run_id: str | None = None
    report_root: str = "reports/test-runs"
    api_base_url: str = "http://127.0.0.1:8000"


def make_run_id(prefix: str) -> str:
    stamp = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    return f"{stamp}-{prefix}"


def validate_run_id(run_id: str | None) -> str | None:
    if run_id is None:
        return None
    if Path(run_id).is_absolute() or "/" in run_id or "\\" in run_id or ".." in run_id:
        raise ValueError("Unsafe run_id: use a simple name without paths.")
    return run_id


async def run_generation_acceptance(options: GenerationRunOptions) -> TestRunReport:
    started = time.monotonic()
    fixture = load_generation_fixture(options.dataset)
    run_id = validate_run_id(options.run_id) or make_run_id("generation-real")

    report = TestRunReport(
        run_id=run_id,
        entrypoint="scripts/verify_generation_real.sh",
        status="passed",
        duration_seconds=time.monotonic() - started,
        dataset=fixture.dataset,
        llm_mode=options.llm_mode,
        environment={"api_base_url": options.api_base_url},
    )
    report.artifacts["fixture_title"] = fixture.title
    if options.llm_mode != "fake":
        try:
            artifacts = await _run_api_smoke_flow(options, fixture)
        except Exception as exc:
            report.add_issue(classify_exception("api_smoke_flow", exc, real_llm=False))
        else:
            report.artifacts.update(artifacts)

    report.duration_seconds = time.monotonic() - started
    return report


async def run_generation_acceptance_and_write(
    options: GenerationRunOptions,
) -> TestRunReport:
    report = await run_generation_acceptance(options)
    ReportWriter(Path(options.report_root) / report.run_id).write(report)
    return report


async def run_stage_with_classification(
    stage: str,
    real_step: Step,
    fake_step: Step,
) -> tuple[Issue | None, str | None]:
    try:
        await real_step()
    except Exception as exc:
        issue = classify_exception(stage, exc, real_llm=True)
        if not issue.is_external_blocker:
            return issue, None

        try:
            await fake_step()
        except Exception:
            issue.fake_rerun_status = "failed"
            return issue, "failed"

        issue.fake_rerun_status = "passed"
        return issue, "passed"

    return None, None


async def _run_api_smoke_flow(
    options: GenerationRunOptions,
    fixture: GenerationFixture,
) -> dict[str, str]:
    async with httpx.AsyncClient(base_url=options.api_base_url, timeout=60) as client:
        health = await client.get("/healthz")
        health.raise_for_status()

        create = await client.post("/api/novels", json={"title": fixture.title})
        create.raise_for_status()
        novel_id = str(create.json()["novel_id"])

        session = await client.post(
            f"/api/novels/{novel_id}/settings/sessions",
            json={
                "title": "Codex 真实生成设定验收",
                "initial_idea": fixture.initial_setting_idea,
                "target_categories": [],
            },
        )
        session.raise_for_status()
        setting_session_id = str(session.json()["id"])

        detail = await client.get(
            f"/api/novels/{novel_id}/settings/sessions/{setting_session_id}"
        )
        detail.raise_for_status()

        return {
            "novel_id": novel_id,
            "setting_session_id": setting_session_id,
        }


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

    if isinstance(exc, httpx.HTTPStatusError):
        issue_type = "SYSTEM_BUG"
    elif isinstance(exc, LLMRateLimitError):
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
