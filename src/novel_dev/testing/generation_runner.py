from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

import httpx
from novel_dev.llm.exceptions import LLMRateLimitError, LLMTimeoutError
from novel_dev.testing.fixtures import GenerationFixture, load_generation_fixture
from novel_dev.testing.quality import validate_outline, validate_settings
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
    report.artifacts["acceptance_scope"] = "settings_brainstorm_volume_export"
    if options.llm_mode == "fake":
        try:
            _run_fake_generation_diagnostic(fixture)
        except Exception as exc:
            report.add_issue(
                classify_exception("fake_generation_diagnostic", exc, real_llm=False)
            )
        report.duration_seconds = time.monotonic() - started
        return report

    if options.llm_mode != "fake":
        try:
            artifacts, issues = await _run_api_smoke_flow(options, fixture)
        except Exception as exc:
            report.add_issue(classify_exception("api_smoke_flow", exc, real_llm=False))
        else:
            report.artifacts.update(artifacts)
            for issue in issues:
                report.add_issue(issue)

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
) -> tuple[dict[str, str], list[Issue]]:
    artifacts: dict[str, str] = {
        "acceptance_scope": "settings_brainstorm_volume_export",
    }
    issues: list[Issue] = []

    async def fake_step() -> None:
        _run_fake_generation_diagnostic(fixture)

    async def run_stage(stage: str, real_step: Step) -> bool:
        if options.llm_mode == "real_then_fake_on_external_block":
            issue, _fake_status = await run_stage_with_classification(
                stage,
                real_step,
                fake_step,
            )
        else:
            try:
                await real_step()
            except Exception as exc:
                issue = classify_exception(stage, exc, real_llm=True)
            else:
                issue = None

        if issue is not None:
            issues.append(issue)
            return False
        return True

    async with httpx.AsyncClient(base_url=options.api_base_url, timeout=60) as client:
        async def preflight_health() -> None:
            response = await client.get("/healthz")
            response.raise_for_status()

        if not await run_stage("preflight_health", preflight_health):
            return artifacts, issues

        async def create_novel() -> None:
            data = await _request_json(
                client.post("/api/novels", json={"title": fixture.title})
            )
            artifacts["novel_id"] = _require_string(data, "novel_id", "create_novel")

        if not await run_stage("create_novel", create_novel):
            return artifacts, issues

        novel_id = artifacts["novel_id"]

        async def create_setting_session() -> None:
            data = await _request_json(
                client.post(
                    f"/api/novels/{novel_id}/settings/sessions",
                    json={
                        "title": "Codex real generation settings acceptance",
                        "initial_idea": fixture.initial_setting_idea,
                        "target_categories": [],
                    },
                )
            )
            artifacts["setting_session_id"] = _require_string(
                data,
                "id",
                "create_setting_session",
            )

        if not await run_stage("create_setting_session", create_setting_session):
            return artifacts, issues

        setting_session_id = artifacts["setting_session_id"]

        async def generate_setting_review_batch() -> None:
            data = await _request_json(
                client.post(
                    f"/api/novels/{novel_id}/settings/sessions/{setting_session_id}/generate",
                    json={},
                )
            )
            review_batch_id = _first_string(data, "id", "review_batch_id", "batch_id")
            if review_batch_id is not None:
                artifacts["review_batch_id"] = review_batch_id

        if not await run_stage(
            "generate_setting_review_batch",
            generate_setting_review_batch,
        ):
            return artifacts, issues

        async def upload_seed_setting() -> None:
            data = await _request_json(
                client.post(
                    f"/api/novels/{novel_id}/documents/upload",
                    json={
                        "filename": "codex_seed_setting.md",
                        "content": fixture.initial_setting_idea,
                    },
                )
            )
            pending_id = _first_string(data, "pending_id", "id")
            if pending_id is not None:
                artifacts["pending_id"] = pending_id

        if not await run_stage("upload_seed_setting", upload_seed_setting):
            return artifacts, issues

        async def approve_seed_setting() -> None:
            pending_id = artifacts.get("pending_id")
            if pending_id is None:
                raise RuntimeError("upload_seed_setting did not return pending_id")
            await _request_json(
                client.post(
                    f"/api/novels/{novel_id}/documents/pending/approve",
                    json={"pending_id": pending_id, "field_resolutions": []},
                )
            )

        if not await run_stage("approve_seed_setting", approve_seed_setting):
            return artifacts, issues

        async def brainstorm() -> None:
            await _request_json(client.post(f"/api/novels/{novel_id}/brainstorm"))

        if not await run_stage("brainstorm", brainstorm):
            return artifacts, issues

        async def volume_plan() -> None:
            data = await _request_json(
                client.post(
                    f"/api/novels/{novel_id}/volume_plan",
                    json={"volume_number": 1},
                )
            )
            volume_id = _first_string(data, "volume_id", "id")
            if volume_id is not None:
                artifacts["volume_id"] = volume_id

        if not await run_stage("volume_plan", volume_plan):
            return artifacts, issues

        async def export() -> None:
            data = await _request_json(
                client.post(f"/api/novels/{novel_id}/export", params={"format": "md"})
            )
            exported_path = _first_string(data, "exported_path", "path")
            if exported_path is not None:
                artifacts["exported_path"] = exported_path

        await run_stage("export", export)
        return artifacts, issues


async def _request_json(response_awaitable: Awaitable[httpx.Response]) -> dict[str, Any]:
    response = await response_awaitable
    response.raise_for_status()
    if not response.content:
        return {}
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("HTTP response JSON must be an object")
    return data


def _first_string(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return str(value)
    return None


def _require_string(data: dict[str, Any], key: str, stage: str) -> str:
    value = _first_string(data, key)
    if value is None:
        raise RuntimeError(f"{stage} response missing {key}")
    return value


def _run_fake_generation_diagnostic(fixture: GenerationFixture) -> None:
    settings_findings = validate_settings(
        {
            "worldview": fixture.initial_setting_idea,
            "characters": ["林照"],
            "factions": ["青云宗"],
            "locations": ["青云宗外门"],
            "rules": ["修炼规则"],
            "core_conflicts": ["查明家族覆灭真相"],
        }
    )
    outline_findings = validate_outline(
        {
            "main_line": fixture.initial_setting_idea,
            "conflicts": ["林照追查真相时遭遇对立势力阻挠"],
            "character_motivations": ["林照要查明家族覆灭真相"],
            "chapters": [{"beats": ["觉醒目标", "进入调查"]}],
        }
    )
    findings = settings_findings + outline_findings
    if findings:
        messages = "; ".join(
            f"{finding.code}: {finding.message}" for finding in findings
        )
        raise RuntimeError(f"Fake generation diagnostic validation failed: {messages}")


def _timeout_is_external(message: str) -> bool:
    markers = ("provider", "upstream", "rate", "quota", "network")
    normalized = message.lower()
    return any(marker in normalized for marker in markers)


def _quota_or_provider_is_external(message: str) -> bool:
    markers = ("quota", "rate", "provider", "upstream")
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
        status_code = exc.response.status_code
        message = _http_status_error_message(exc)
        if status_code == 429:
            issue_type = "EXTERNAL_BLOCKED"
            is_external_blocker = True
        elif status_code in {402, 403} and _quota_or_provider_is_external(message):
            issue_type = "EXTERNAL_BLOCKED"
            is_external_blocker = True
        elif status_code == 504:
            if _timeout_is_external(message):
                issue_type = "EXTERNAL_BLOCKED"
                is_external_blocker = True
            else:
                issue_type = "TIMEOUT_INTERNAL"
        else:
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


def _http_status_error_message(exc: httpx.HTTPStatusError) -> str:
    parts = [str(exc)]
    try:
        parts.append(exc.response.text)
    except Exception:
        pass
    return "\n".join(part for part in parts if part)


def should_fake_rerun_affect_final_status(issue_type: IssueType) -> bool:
    return issue_type == "EXTERNAL_BLOCKED"
