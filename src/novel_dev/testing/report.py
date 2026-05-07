from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal


IssueType = Literal[
    "SYSTEM_BUG",
    "GENERATION_QUALITY",
    "LLM_PARSE_ERROR",
    "TIMEOUT_INTERNAL",
    "EXTERNAL_BLOCKED",
    "TEST_INFRA",
    "VISUAL_REGRESSION",
    "FLAKY_SUSPECTED",
]

Severity = Literal["low", "medium", "high", "critical"]
RunStatus = Literal["passed", "failed", "external_blocked"]


@dataclass(slots=True)
class Issue:
    id: str
    type: IssueType
    severity: Severity
    stage: str
    is_external_blocker: bool
    real_llm: bool
    fake_rerun_status: str | None
    message: str
    evidence: list[str]
    reproduce: str

    def is_blocking(self) -> bool:
        return not self.is_external_blocker


@dataclass(slots=True)
class TestRunReport:
    __test__ = False

    run_id: str
    entrypoint: str
    status: RunStatus
    duration_seconds: float
    dataset: str
    llm_mode: str
    environment: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)

    def add_issue(self, issue: Issue) -> None:
        self.issues.append(issue)
        if issue.is_blocking():
            self.status = "failed"
        elif self.status == "passed":
            self.status = "external_blocked"


@dataclass(slots=True)
class ReportPaths:
    root: Path
    summary_json: Path
    summary_md: Path


class ReportWriter:
    def __init__(self, root: Path):
        self.root = root

    def write(self, report: TestRunReport) -> ReportPaths:
        self.root.mkdir(parents=True, exist_ok=True)
        artifacts = self.root / "artifacts"
        artifacts.mkdir(exist_ok=True)

        summary_json = self.root / "summary.json"
        summary_md = self.root / "summary.md"
        summary_json.write_text(
            json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        summary_md.write_text(self._render_markdown(report), encoding="utf-8")
        return ReportPaths(self.root, summary_json, summary_md)

    def _render_markdown(self, report: TestRunReport) -> str:
        lines = [
            f"# Test Run {report.run_id}",
            "",
            f"- Entrypoint: `{report.entrypoint}`",
            f"- Status: `{report.status}`",
            f"- Dataset: `{report.dataset}`",
            f"- LLM mode: `{report.llm_mode}`",
            f"- Duration: `{report.duration_seconds:.1f}s`",
            "",
            "## Issues",
            "",
        ]
        if not report.issues:
            lines.append("No issues recorded.")
        for issue in report.issues:
            lines.extend(
                [
                    f"### {issue.id} `{issue.type}`",
                    "",
                    f"- Severity: `{issue.severity}`",
                    f"- Stage: `{issue.stage}`",
                    f"- External blocker: `{issue.is_external_blocker}`",
                    f"- Real LLM: `{issue.real_llm}`",
                    f"- Fake rerun status: `{issue.fake_rerun_status}`",
                    f"- Message: {issue.message}",
                    f"- Evidence: {', '.join(issue.evidence) if issue.evidence else 'none'}",
                    f"- Reproduce: `{issue.reproduce}`",
                    "",
                ]
            )
        return "\n".join(lines).rstrip() + "\n"
