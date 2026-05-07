# Codex Web And Generation Testing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Codex-executable testing system for stable local gates, real LLM generation acceptance, Web E2E, structured visual checks, and actionable issue reports.

**Architecture:** Add a small `novel_dev.testing` support package for report writing, failure classification, quality validation, fixture loading, and generation orchestration. Keep deterministic pytest/Vitest in the normal gate, put real LLM acceptance behind a dedicated script, and use Playwright for browser and visual checks with a shared report directory.

**Tech Stack:** Python 3.11, pytest, FastAPI/httpx, SQLAlchemy async, existing `novel_dev` services/agents, Bash, Vue 3, Vite, Vitest, Playwright.

---

## File Structure

Create these backend testing support files:

- `src/novel_dev/testing/__init__.py`: package exports.
- `src/novel_dev/testing/report.py`: report schema, issue ids, artifact paths, `summary.json`, and `summary.md` writing.
- `src/novel_dev/testing/quality.py`: deterministic generated material validators and rubric result models.
- `src/novel_dev/testing/fixtures.py`: load built-in YAML/JSON fixture data and optional external source directories.
- `src/novel_dev/testing/generation_runner.py`: async real/Fake generation flow orchestration with failure classification.
- `src/novel_dev/testing/cli.py`: command line entrypoint used by shell scripts.

Create these backend tests and fixtures:

- `tests/test_testing/test_report.py`: report schema and Markdown output tests.
- `tests/test_testing/test_quality.py`: deterministic settings, outline, chapter, and consistency validator tests.
- `tests/test_testing/test_generation_runner.py`: failure classification and fallback policy tests.
- `tests/generation/fixtures/minimal_novel.yaml`: built-in small novel input used by stable and real generation checks.
- `tests/generation/test_minimal_generation_flow.py`: deterministic Fake/Mock generation gate for `verify_local.sh`.

Modify these scripts:

- `scripts/verify_local.sh`: add deterministic Fake/Mock generation flow after Python compile check and before Web tests.
- `scripts/verify_generation_real.sh`: new shell entrypoint for real LLM acceptance.
- `scripts/verify_web_e2e.sh`: new shell entrypoint for Playwright checks.

Create these Web E2E files:

- `src/novel_dev/web/playwright.config.js`: Playwright config, reporters, trace/screenshot/video settings.
- `src/novel_dev/web/e2e/helpers/reporting.js`: append Web issues to the shared report path.
- `src/novel_dev/web/e2e/helpers/visualChecks.js`: structured visual checks.
- `src/novel_dev/web/e2e/flows/navigation.spec.js`: app boot, route, and page smoke flow.
- `src/novel_dev/web/e2e/flows/generation.spec.js`: key UI flow against seeded or generated state.
- `src/novel_dev/web/e2e/visual/layout.spec.js`: desktop/mobile layout checks.

Modify these Web files:

- `src/novel_dev/web/package.json`: add Playwright scripts and dev dependency.
- `src/novel_dev/web/package-lock.json`: update via `npm install`.

---

### Task 1: Report Schema And Writer

**Files:**
- Create: `src/novel_dev/testing/__init__.py`
- Create: `src/novel_dev/testing/report.py`
- Test: `tests/test_testing/test_report.py`

- [ ] **Step 1: Write the failing report tests**

Create `tests/test_testing/test_report.py`:

```python
import json

from novel_dev.testing.report import Issue, ReportWriter, TestRunReport


def test_report_writer_creates_json_and_markdown(tmp_path):
    report = TestRunReport(
        run_id="2026-05-07T153000-generation-real",
        entrypoint="scripts/verify_generation_real.sh",
        status="failed",
        duration_seconds=12.5,
        dataset="minimal_builtin",
        llm_mode="real_then_fake_on_external_block",
        environment={"python": "3.11"},
    )
    report.add_issue(
        Issue(
            id="GEN-QUALITY-001",
            type="GENERATION_QUALITY",
            severity="high",
            stage="chapter_draft",
            is_external_blocker=False,
            real_llm=True,
            fake_rerun_status="passed",
            message="Chapter draft missed a required beat.",
            evidence=["artifacts/generation/stage-07-chapter.md"],
            reproduce="scripts/verify_generation_real.sh --stage chapter_draft",
        )
    )

    writer = ReportWriter(tmp_path)
    paths = writer.write(report)

    summary_json = json.loads(paths.summary_json.read_text(encoding="utf-8"))
    assert summary_json["status"] == "failed"
    assert summary_json["issues"][0]["id"] == "GEN-QUALITY-001"
    assert summary_json["issues"][0]["reproduce"].endswith("--stage chapter_draft")

    summary_md = paths.summary_md.read_text(encoding="utf-8")
    assert "# Test Run 2026-05-07T153000-generation-real" in summary_md
    assert "GEN-QUALITY-001" in summary_md
    assert "Chapter draft missed a required beat." in summary_md


def test_report_status_becomes_failed_when_blocking_issue_is_added():
    report = TestRunReport(
        run_id="run",
        entrypoint="entry",
        status="passed",
        duration_seconds=1,
        dataset="minimal_builtin",
        llm_mode="fake",
    )
    report.add_issue(
        Issue(
            id="SYSTEM-001",
            type="SYSTEM_BUG",
            severity="high",
            stage="preflight",
            is_external_blocker=False,
            real_llm=False,
            fake_rerun_status=None,
            message="API health check failed.",
            evidence=[],
            reproduce="scripts/verify_generation_real.sh --stage preflight",
        )
    )

    assert report.status == "failed"
```

- [ ] **Step 2: Run the report tests to verify they fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_report.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'novel_dev.testing'`.

- [ ] **Step 3: Add the report implementation**

Create `src/novel_dev/testing/__init__.py`:

```python
"""Testing helpers for Codex-driven validation flows."""
```

Create `src/novel_dev/testing/report.py`:

```python
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
```

- [ ] **Step 4: Run the report tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_report.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/testing/__init__.py src/novel_dev/testing/report.py tests/test_testing/test_report.py
git commit -m "test: add codex test report writer"
```

---

### Task 2: Deterministic Quality Validators

**Files:**
- Create: `src/novel_dev/testing/quality.py`
- Test: `tests/test_testing/test_quality.py`

- [ ] **Step 1: Write failing quality validator tests**

Create `tests/test_testing/test_quality.py`:

```python
from novel_dev.testing.quality import (
    QualityFinding,
    validate_chapter,
    validate_cross_stage_consistency,
    validate_outline,
    validate_settings,
)


def test_validate_settings_accepts_complete_material():
    settings = {
        "worldview": "天玄大陆，宗门与王朝并立。",
        "characters": [{"name": "林照", "goal": "查明家族覆灭真相"}],
        "factions": [{"name": "青云宗", "role": "正道宗门"}],
        "locations": [{"name": "青云山", "role": "修行起点"}],
        "rules": ["修为分为炼气、筑基、金丹"],
        "core_conflicts": ["林照与灭门真凶的冲突"],
    }

    findings = validate_settings(settings)

    assert findings == []


def test_validate_settings_reports_missing_required_sections():
    findings = validate_settings({"worldview": "天玄大陆"})

    assert QualityFinding(
        code="SETTINGS_MISSING_CHARACTERS",
        severity="high",
        message="Settings must include at least one character.",
    ) in findings
    assert any(item.code == "SETTINGS_MISSING_CORE_CONFLICTS" for item in findings)


def test_validate_outline_requires_executable_chapters():
    outline = {
        "main_line": "林照查明真相",
        "conflicts": ["宗门试炼"],
        "character_motivations": ["为家族复仇"],
        "chapters": [{"title": "第一章", "beats": ["觉醒血脉"]}],
    }

    assert validate_outline(outline) == []

    findings = validate_outline({"main_line": "林照查明真相", "chapters": []})
    assert any(item.code == "OUTLINE_MISSING_CHAPTERS" for item in findings)


def test_validate_chapter_requires_beat_coverage_and_length():
    chapter = "第一章\n林照在青云山觉醒血脉。随后他拒绝退缩，决定参加宗门试炼。"
    findings = validate_chapter(
        chapter,
        required_beats=["觉醒血脉", "参加宗门试炼"],
        minimum_chars=20,
    )

    assert findings == []

    bad = validate_chapter("第一章\n林照醒来。", ["觉醒血脉", "参加宗门试炼"], 20)
    assert any(item.code == "CHAPTER_TOO_SHORT" for item in bad)
    assert any(item.code == "CHAPTER_MISSING_BEAT" for item in bad)


def test_validate_cross_stage_consistency_flags_undefined_terms():
    findings = validate_cross_stage_consistency(
        allowed_terms={"林照", "青云宗", "青云山"},
        generated_text="林照在青云山遇到玄火盟长老。",
        watched_terms={"玄火盟", "血海殿"},
    )

    assert findings == [
        QualityFinding(
            code="CROSS_STAGE_UNDEFINED_TERM",
            severity="high",
            message="Generated text references undefined term: 玄火盟",
        )
    ]
```

- [ ] **Step 2: Run the quality tests to verify they fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_quality.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `novel_dev.testing.quality`.

- [ ] **Step 3: Add the quality validator implementation**

Create `src/novel_dev/testing/quality.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


Severity = Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True, slots=True)
class QualityFinding:
    code: str
    severity: Severity
    message: str


def _has_items(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set)):
        return len(value) > 0
    return value is not None


def validate_settings(settings: dict[str, Any]) -> list[QualityFinding]:
    checks = [
        ("worldview", "SETTINGS_MISSING_WORLDVIEW", "Settings must include worldview."),
        ("characters", "SETTINGS_MISSING_CHARACTERS", "Settings must include at least one character."),
        ("factions", "SETTINGS_MISSING_FACTIONS", "Settings must include at least one faction or force."),
        ("locations", "SETTINGS_MISSING_LOCATIONS", "Settings must include at least one location."),
        ("rules", "SETTINGS_MISSING_RULES", "Settings must include at least one rule or power-system constraint."),
        ("core_conflicts", "SETTINGS_MISSING_CORE_CONFLICTS", "Settings must include at least one core conflict."),
    ]
    findings: list[QualityFinding] = []
    for key, code, message in checks:
        if not _has_items(settings.get(key)):
            findings.append(QualityFinding(code=code, severity="high", message=message))
    return findings


def validate_outline(outline: dict[str, Any]) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    required = [
        ("main_line", "OUTLINE_MISSING_MAIN_LINE", "Outline must include a main line."),
        ("conflicts", "OUTLINE_MISSING_CONFLICTS", "Outline must include conflicts."),
        ("character_motivations", "OUTLINE_MISSING_MOTIVATIONS", "Outline must include character motivations."),
        ("chapters", "OUTLINE_MISSING_CHAPTERS", "Outline must include executable chapters."),
    ]
    for key, code, message in required:
        if not _has_items(outline.get(key)):
            findings.append(QualityFinding(code=code, severity="high", message=message))

    for index, chapter in enumerate(outline.get("chapters") or [], start=1):
        beats = chapter.get("beats") if isinstance(chapter, dict) else None
        if not _has_items(beats):
            findings.append(
                QualityFinding(
                    code="OUTLINE_CHAPTER_MISSING_BEATS",
                    severity="high",
                    message=f"Chapter {index} must include at least one beat.",
                )
            )
    return findings


def validate_chapter(
    text: str,
    required_beats: list[str],
    minimum_chars: int,
) -> list[QualityFinding]:
    compact = "".join(text.split())
    findings: list[QualityFinding] = []
    if len(compact) < minimum_chars:
        findings.append(
            QualityFinding(
                code="CHAPTER_TOO_SHORT",
                severity="high",
                message=f"Chapter has {len(compact)} non-space characters, below minimum {minimum_chars}.",
            )
        )
    for beat in required_beats:
        if beat and beat not in text:
            findings.append(
                QualityFinding(
                    code="CHAPTER_MISSING_BEAT",
                    severity="high",
                    message=f"Chapter does not cover required beat: {beat}",
                )
            )
    return findings


def validate_cross_stage_consistency(
    allowed_terms: set[str],
    generated_text: str,
    watched_terms: set[str],
) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    for term in sorted(watched_terms):
        if term in generated_text and term not in allowed_terms:
            findings.append(
                QualityFinding(
                    code="CROSS_STAGE_UNDEFINED_TERM",
                    severity="high",
                    message=f"Generated text references undefined term: {term}",
                )
            )
    return findings
```

- [ ] **Step 4: Run the quality tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_quality.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/testing/quality.py tests/test_testing/test_quality.py
git commit -m "test: add generation quality validators"
```

---

### Task 3: Built-In Minimal Novel Fixture Loader

**Files:**
- Create: `src/novel_dev/testing/fixtures.py`
- Create: `tests/generation/fixtures/minimal_novel.yaml`
- Test: `tests/test_testing/test_fixtures.py`

- [ ] **Step 1: Write failing fixture tests**

Create `tests/test_testing/test_fixtures.py`:

```python
from pathlib import Path

from novel_dev.testing.fixtures import GenerationFixture, load_generation_fixture


def test_load_builtin_minimal_fixture():
    fixture = load_generation_fixture("minimal_builtin")

    assert isinstance(fixture, GenerationFixture)
    assert fixture.dataset == "minimal_builtin"
    assert fixture.title == "Codex 最小生成验收"
    assert "初始设定目标" in fixture.initial_setting_idea
    assert fixture.minimum_chapter_chars > 0


def test_load_external_fixture_directory(tmp_path):
    source = tmp_path / "novel"
    source.mkdir()
    (source / "fixture.yaml").write_text(
        "\n".join(
            [
                "dataset: external_dir",
                "title: 外部验收小说",
                "initial_setting_idea: 外部设定输入",
                "minimum_chapter_chars: 50",
                "watched_terms:",
                "  - 玄火盟",
            ]
        ),
        encoding="utf-8",
    )

    fixture = load_generation_fixture(str(source))

    assert fixture.dataset == "external_dir"
    assert fixture.title == "外部验收小说"
    assert fixture.watched_terms == ["玄火盟"]
```

- [ ] **Step 2: Run fixture tests to verify they fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_fixtures.py -q
```

Expected: FAIL because `novel_dev.testing.fixtures` does not exist.

- [ ] **Step 3: Add minimal fixture data**

Create `tests/generation/fixtures/minimal_novel.yaml`:

```yaml
dataset: minimal_builtin
title: Codex 最小生成验收
initial_setting_idea: |
  初始设定目标：生成一部东方玄幻短篇测试小说。
  世界需要包含宗门、修炼规则、主角、对立势力、核心冲突和第一章可执行目标。
  主角林照出身青云宗外门，目标是查明家族覆灭真相。
minimum_chapter_chars: 120
watched_terms:
  - 青云宗
  - 林照
  - 玄火盟
  - 血海殿
```

- [ ] **Step 4: Add fixture loader implementation**

Create `src/novel_dev/testing/fixtures.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
BUILTIN_FIXTURE = REPO_ROOT / "tests" / "generation" / "fixtures" / "minimal_novel.yaml"


@dataclass(frozen=True, slots=True)
class GenerationFixture:
    dataset: str
    title: str
    initial_setting_idea: str
    minimum_chapter_chars: int
    watched_terms: list[str] = field(default_factory=list)


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Fixture must be a mapping: {path}")
    return data


def _from_data(data: dict[str, Any]) -> GenerationFixture:
    return GenerationFixture(
        dataset=str(data["dataset"]),
        title=str(data["title"]),
        initial_setting_idea=str(data["initial_setting_idea"]),
        minimum_chapter_chars=int(data.get("minimum_chapter_chars", 120)),
        watched_terms=[str(item) for item in data.get("watched_terms", [])],
    )


def load_generation_fixture(dataset: str) -> GenerationFixture:
    if dataset == "minimal_builtin":
        return _from_data(_read_yaml(BUILTIN_FIXTURE))

    source = Path(dataset)
    if source.is_dir():
        fixture_path = source / "fixture.yaml"
        if not fixture_path.exists():
            raise FileNotFoundError(f"External fixture directory lacks fixture.yaml: {source}")
        return _from_data(_read_yaml(fixture_path))

    raise ValueError(f"Unsupported generation dataset: {dataset}")
```

- [ ] **Step 5: Run fixture tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_fixtures.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/testing/fixtures.py tests/test_testing/test_fixtures.py tests/generation/fixtures/minimal_novel.yaml
git commit -m "test: add generation fixture loader"
```

---

### Task 4: Failure Classification And Runner Skeleton

**Files:**
- Create: `src/novel_dev/testing/generation_runner.py`
- Test: `tests/test_testing/test_generation_runner.py`

- [ ] **Step 1: Write failing runner classification tests**

Create `tests/test_testing/test_generation_runner.py`:

```python
from novel_dev.llm.exceptions import LLMRateLimitError, LLMTimeoutError
from novel_dev.testing.generation_runner import (
    GenerationRunOptions,
    classify_exception,
    should_fake_rerun_affect_final_status,
)


def test_rate_limit_is_external_blocker():
    issue = classify_exception(
        stage="settings_generate",
        exc=LLMRateLimitError("quota exceeded"),
        real_llm=True,
    )

    assert issue.type == "EXTERNAL_BLOCKED"
    assert issue.is_external_blocker is True


def test_internal_timeout_message_is_system_timeout():
    issue = classify_exception(
        stage="chapter_draft",
        exc=LLMTimeoutError("generation job polling timed out after 600s"),
        real_llm=True,
    )

    assert issue.type == "TIMEOUT_INTERNAL"
    assert issue.is_external_blocker is False


def test_provider_timeout_message_is_external_blocker():
    issue = classify_exception(
        stage="chapter_draft",
        exc=LLMTimeoutError("provider queue timeout from upstream"),
        real_llm=True,
    )

    assert issue.type == "EXTERNAL_BLOCKED"
    assert issue.is_external_blocker is True


def test_fake_rerun_does_not_clear_system_failure():
    assert should_fake_rerun_affect_final_status("SYSTEM_BUG") is False
    assert should_fake_rerun_affect_final_status("GENERATION_QUALITY") is False
    assert should_fake_rerun_affect_final_status("EXTERNAL_BLOCKED") is True


def test_options_default_to_real_then_fake_on_external_block():
    options = GenerationRunOptions()

    assert options.dataset == "minimal_builtin"
    assert options.llm_mode == "real_then_fake_on_external_block"
```

- [ ] **Step 2: Run runner tests to verify they fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_generation_runner.py -q
```

Expected: FAIL because `novel_dev.testing.generation_runner` does not exist.

- [ ] **Step 3: Add runner skeleton and classifier**

Create `src/novel_dev/testing/generation_runner.py`:

```python
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
    lowered = message.lower()
    external_markers = ["provider", "upstream", "rate", "quota", "queue", "network"]
    return any(marker in lowered for marker in external_markers)


def classify_exception(stage: str, exc: Exception, real_llm: bool) -> Issue:
    issue_type: IssueType
    external = False
    if isinstance(exc, LLMRateLimitError):
        issue_type = "EXTERNAL_BLOCKED"
        external = True
    elif isinstance(exc, LLMTimeoutError) and _timeout_is_external(str(exc)):
        issue_type = "EXTERNAL_BLOCKED"
        external = True
    elif isinstance(exc, LLMTimeoutError):
        issue_type = "TIMEOUT_INTERNAL"
    elif isinstance(exc, (ValueError, KeyError)):
        issue_type = "LLM_PARSE_ERROR"
    else:
        issue_type = "SYSTEM_BUG"

    issue_prefix = "EXT" if external else issue_type.split("_", maxsplit=1)[0]
    return Issue(
        id=f"{issue_prefix}-001",
        type=issue_type,
        severity="high",
        stage=stage,
        is_external_blocker=external,
        real_llm=real_llm,
        fake_rerun_status=None,
        message=str(exc),
        evidence=[],
        reproduce=f"scripts/verify_generation_real.sh --stage {stage}",
    )


def should_fake_rerun_affect_final_status(issue_type: IssueType) -> bool:
    return issue_type == "EXTERNAL_BLOCKED"
```

- [ ] **Step 4: Run runner tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_generation_runner.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/testing/generation_runner.py tests/test_testing/test_generation_runner.py
git commit -m "test: add generation failure classification"
```

---

### Task 5: Deterministic Fake/Mock Generation Gate

**Files:**
- Create: `tests/generation/test_minimal_generation_flow.py`
- Modify: `scripts/verify_local.sh`

- [ ] **Step 1: Add a failing deterministic generation test**

Create `tests/generation/test_minimal_generation_flow.py`:

```python
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from novel_dev.api.routes import get_session, router


app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_minimal_fake_generation_flow_reaches_export(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    suffix = uuid.uuid4().hex[:8]
    title = f"Codex 最小生成验收 {suffix}"

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            create = await client.post("/api/novels", json={"title": title})
            assert create.status_code == 201
            novel_id = create.json()["novel_id"]

            setting_session = await client.post(
                f"/api/novels/{novel_id}/settings/sessions",
                json={
                    "title": "最小设定生成",
                    "initial_idea": "生成青云宗、林照、玄火盟、修炼规则和第一章冲突。",
                    "target_categories": [],
                },
            )
            assert setting_session.status_code == 200
            session_id = setting_session.json()["id"]

            detail = await client.get(f"/api/novels/{novel_id}/settings/sessions/{session_id}")
            assert detail.status_code == 200
            assert detail.json()["messages"][0]["content"]

            upload = await client.post(
                f"/api/novels/{novel_id}/documents/upload",
                json={
                    "filename": "worldview.txt",
                    "content": (
                        "世界观：天玄大陆，宗门与王朝并立。\n"
                        "主角：林照，青云宗外门弟子。\n"
                        "势力：青云宗与玄火盟冲突。\n"
                        "规则：炼气、筑基、金丹。\n"
                        "核心冲突：林照查明家族覆灭真相。"
                    ),
                },
            )
            assert upload.status_code == 200
            pending_id = upload.json()["id"]

            approve = await client.post(
                f"/api/novels/{novel_id}/documents/pending/approve",
                json={"pending_id": pending_id},
            )
            assert approve.status_code == 200

            brainstorm = await client.post(f"/api/novels/{novel_id}/brainstorm")
            assert brainstorm.status_code == 200
            assert brainstorm.json()["title"]

            volume = await client.post(f"/api/novels/{novel_id}/volume_plan")
            assert volume.status_code == 200
            assert volume.json()["chapters"]

            export = await client.post(f"/api/novels/{novel_id}/export?format=md")
            assert export.status_code == 200
            assert "exported_path" in export.json()
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run the new test and capture the first failure**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/generation/test_minimal_generation_flow.py -q
```

Expected: The test may fail on missing setup assumptions in the flow, most likely around volume plan prerequisites. Keep the assertion that identifies the missing state.

- [ ] **Step 3: Adjust only the test setup to match current API prerequisites**

Use the pattern already present in `tests/test_integration_end_to_end.py`: when the current API requires explicit checkpoint setup before volume planning, set the checkpoint with `NovelDirector.save_checkpoint(...)` and `SynopsisData(...)` inside the test. The inserted code goes after the brainstorm assertions and before `POST /volume_plan`:

```python
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.outline import SynopsisData

director = NovelDirector(session=async_session)
state = await director.resume(novel_id)
checkpoint = dict(state.checkpoint_data or {})
checkpoint["synopsis_data"] = SynopsisData(
    title="Codex 最小生成验收",
    logline="林照在宗门冲突中查明真相",
    core_conflict="青云宗与玄火盟围绕旧案对立",
    estimated_volumes=1,
    estimated_total_chapters=1,
    estimated_total_words=3000,
).model_dump()
await director.save_checkpoint(
    novel_id,
    phase=Phase.VOLUME_PLANNING,
    checkpoint_data=checkpoint,
    volume_id=None,
    chapter_id=None,
)
await async_session.commit()
```

- [ ] **Step 4: Run the deterministic generation test**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/generation/test_minimal_generation_flow.py -q
```

Expected: PASS.

- [ ] **Step 5: Add the test to `scripts/verify_local.sh`**

Modify `scripts/verify_local.sh` after the compile check block and before the Web tests block:

```bash
echo "==> Fake generation flow"
(
  cd "${ROOT_DIR}"
  PYTHONPATH=src python3.11 -m pytest tests/generation/test_minimal_generation_flow.py -q
)
```

- [ ] **Step 6: Run stable gate**

Run:

```bash
scripts/verify_local.sh
```

Expected: PASS through Python tests, compile check, Fake generation flow, Web tests, and Web build.

- [ ] **Step 7: Commit**

```bash
git add tests/generation/test_minimal_generation_flow.py scripts/verify_local.sh
git commit -m "test: add fake generation flow to local gate"
```

---

### Task 6: CLI For Generation Acceptance Reports

**Files:**
- Create: `src/novel_dev/testing/cli.py`
- Modify: `src/novel_dev/testing/generation_runner.py`
- Test: `tests/test_testing/test_cli.py`

- [ ] **Step 1: Write failing CLI test**

Create `tests/test_testing/test_cli.py`:

```python
import json

from novel_dev.testing.cli import main


def test_generation_cli_writes_report_for_fake_mode(tmp_path):
    exit_code = main(
        [
            "generation",
            "--llm-mode",
            "fake",
            "--dataset",
            "minimal_builtin",
            "--report-root",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    reports = list(tmp_path.glob("*/summary.json"))
    assert len(reports) == 1
    data = json.loads(reports[0].read_text(encoding="utf-8"))
    assert data["entrypoint"] == "scripts/verify_generation_real.sh"
    assert data["dataset"] == "minimal_builtin"
    assert data["llm_mode"] == "fake"
```

- [ ] **Step 2: Run CLI test to verify it fails**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_cli.py -q
```

Expected: FAIL because `novel_dev.testing.cli` does not exist.

- [ ] **Step 3: Add a runner function that writes reports**

Append to `src/novel_dev/testing/generation_runner.py`:

```python
from datetime import datetime
from pathlib import Path
import time

from novel_dev.testing.fixtures import load_generation_fixture
from novel_dev.testing.report import ReportWriter, TestRunReport


def make_run_id(prefix: str) -> str:
    stamp = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    return f"{stamp}-{prefix}"


async def run_generation_acceptance(options: GenerationRunOptions) -> TestRunReport:
    started = time.monotonic()
    fixture = load_generation_fixture(options.dataset)
    run_id = options.run_id or make_run_id("generation-real")
    report = TestRunReport(
        run_id=run_id,
        entrypoint="scripts/verify_generation_real.sh",
        status="passed",
        duration_seconds=0,
        dataset=fixture.dataset,
        llm_mode=options.llm_mode,
        environment={"api_base_url": options.api_base_url},
    )
    report.artifacts["fixture_title"] = fixture.title
    report.duration_seconds = time.monotonic() - started
    return report


async def run_generation_acceptance_and_write(options: GenerationRunOptions) -> TestRunReport:
    report = await run_generation_acceptance(options)
    output = Path(options.report_root) / report.run_id
    ReportWriter(output).write(report)
    return report
```

- [ ] **Step 4: Add CLI implementation**

Create `src/novel_dev/testing/cli.py`:

```python
from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence

from novel_dev.testing.generation_runner import (
    GenerationRunOptions,
    run_generation_acceptance_and_write,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="novel-dev-testing")
    subcommands = parser.add_subparsers(dest="command", required=True)

    generation = subcommands.add_parser("generation")
    generation.add_argument("--dataset", default="minimal_builtin")
    generation.add_argument(
        "--llm-mode",
        default="real_then_fake_on_external_block",
        choices=["fake", "real", "real_then_fake_on_external_block"],
    )
    generation.add_argument("--stage")
    generation.add_argument("--run-id")
    generation.add_argument("--report-root", default="reports/test-runs")
    generation.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "generation":
        options = GenerationRunOptions(
            dataset=args.dataset,
            llm_mode=args.llm_mode,
            stage=args.stage,
            run_id=args.run_id,
            report_root=args.report_root,
            api_base_url=args.api_base_url,
        )
        report = asyncio.run(run_generation_acceptance_and_write(options))
        return 0 if report.status in {"passed", "external_blocked"} else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run CLI test**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/testing/cli.py src/novel_dev/testing/generation_runner.py tests/test_testing/test_cli.py
git commit -m "test: add generation acceptance cli"
```

---

### Task 7: Real Generation Shell Entrypoint

**Files:**
- Create: `scripts/verify_generation_real.sh`
- Test: manual shell command

- [ ] **Step 1: Create the shell entrypoint**

Create `scripts/verify_generation_real.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"
DATASET="${DATASET:-minimal_builtin}"
REPORT_ROOT="${REPORT_ROOT:-${ROOT_DIR}/reports/test-runs}"
API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8000}"
LLM_MODE="${LLM_MODE:-real_then_fake_on_external_block}"
STAGE="${STAGE:-}"
RUN_ID="${RUN_ID:-}"

args=(
  generation
  --dataset "${DATASET}"
  --llm-mode "${LLM_MODE}"
  --report-root "${REPORT_ROOT}"
  --api-base-url "${API_BASE_URL}"
)

if [[ -n "${STAGE}" ]]; then
  args+=(--stage "${STAGE}")
fi

if [[ -n "${RUN_ID}" ]]; then
  args+=(--run-id "${RUN_ID}")
fi

cd "${ROOT_DIR}"
PYTHONPATH=src "${PYTHON_BIN}" -m novel_dev.testing.cli "${args[@]}"
```

- [ ] **Step 2: Make the script executable**

Run:

```bash
chmod +x scripts/verify_generation_real.sh
```

Expected: command succeeds.

- [ ] **Step 3: Run fake mode smoke for the entrypoint**

Run:

```bash
LLM_MODE=fake scripts/verify_generation_real.sh
```

Expected: PASS and creates one `reports/test-runs/*/summary.json`.

- [ ] **Step 4: Commit**

```bash
git add scripts/verify_generation_real.sh
git commit -m "test: add real generation verification entrypoint"
```

---

### Task 8: Real API Generation Flow In Runner

**Files:**
- Modify: `src/novel_dev/testing/generation_runner.py`
- Test: `tests/test_testing/test_generation_runner.py`
- Test: `scripts/verify_generation_real.sh`

- [ ] **Step 1: Add a failing test for fake rerun policy on external block**

Append to `tests/test_testing/test_generation_runner.py`:

```python
import pytest

from novel_dev.testing.generation_runner import run_stage_with_classification


@pytest.mark.asyncio
async def test_stage_external_block_runs_fake_diagnostic():
    calls = []

    async def real_step():
        calls.append("real")
        raise LLMRateLimitError("quota exceeded")

    async def fake_step():
        calls.append("fake")
        return "fake-ok"

    issue, fake_status = await run_stage_with_classification(
        stage="settings_generate",
        real_step=real_step,
        fake_step=fake_step,
    )

    assert calls == ["real", "fake"]
    assert issue.type == "EXTERNAL_BLOCKED"
    assert fake_status == "passed"
```

- [ ] **Step 2: Run the targeted test and verify it fails**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_generation_runner.py::test_stage_external_block_runs_fake_diagnostic -q
```

Expected: FAIL because `run_stage_with_classification` does not exist.

- [ ] **Step 3: Add classified stage execution helper**

Append to `src/novel_dev/testing/generation_runner.py`:

```python
from collections.abc import Awaitable, Callable
from typing import Any


async def run_stage_with_classification(
    stage: str,
    real_step: Callable[[], Awaitable[Any]],
    fake_step: Callable[[], Awaitable[Any]],
) -> tuple[Issue | None, str | None]:
    try:
        await real_step()
        return None, None
    except Exception as exc:
        issue = classify_exception(stage=stage, exc=exc, real_llm=True)
        if issue.is_external_blocker:
            try:
                await fake_step()
                issue.fake_rerun_status = "passed"
                return issue, "passed"
            except Exception:
                issue.fake_rerun_status = "failed"
                return issue, "failed"
        return issue, None
```

- [ ] **Step 4: Run the stage helper test**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_generation_runner.py::test_stage_external_block_runs_fake_diagnostic -q
```

Expected: PASS.

- [ ] **Step 5: Implement real API smoke stages**

Extend `run_generation_acceptance` in `src/novel_dev/testing/generation_runner.py` to call the running API through `httpx.AsyncClient`. Keep the first implementation scoped to stages that are already exposed and fast:

```python
import httpx


async def _run_api_smoke_flow(options: GenerationRunOptions, fixture) -> dict[str, str]:
    async with httpx.AsyncClient(base_url=options.api_base_url, timeout=60) as client:
        health = await client.get("/healthz")
        health.raise_for_status()

        create = await client.post("/api/novels", json={"title": fixture.title})
        create.raise_for_status()
        novel_id = create.json()["novel_id"]

        session = await client.post(
            f"/api/novels/{novel_id}/settings/sessions",
            json={
                "title": "Codex 真实生成设定验收",
                "initial_idea": fixture.initial_setting_idea,
                "target_categories": [],
            },
        )
        session.raise_for_status()
        session_id = session.json()["id"]

        detail = await client.get(f"/api/novels/{novel_id}/settings/sessions/{session_id}")
        detail.raise_for_status()
        return {"novel_id": novel_id, "setting_session_id": session_id}
```

Then call it inside `run_generation_acceptance` when `options.llm_mode != "fake"`:

```python
if options.llm_mode != "fake":
    try:
        artifacts = await _run_api_smoke_flow(options, fixture)
        report.artifacts.update(artifacts)
    except Exception as exc:
        report.add_issue(classify_exception("api_smoke_flow", exc, real_llm=False))
```

- [ ] **Step 6: Run CLI fake test and real smoke against a local API**

First run fake mode:

```bash
LLM_MODE=fake scripts/verify_generation_real.sh
```

Expected: PASS.

Then, with the app running locally at `http://127.0.0.1:8000`, run:

```bash
scripts/verify_generation_real.sh
```

Expected: PASS for preflight and API smoke stages, or FAIL with a classified issue in `summary.json` if the API is not running.

- [ ] **Step 7: Commit**

```bash
git add src/novel_dev/testing/generation_runner.py tests/test_testing/test_generation_runner.py
git commit -m "test: add classified generation api smoke flow"
```

---

### Task 9: Playwright Setup

**Files:**
- Modify: `src/novel_dev/web/package.json`
- Modify: `src/novel_dev/web/package-lock.json`
- Create: `src/novel_dev/web/playwright.config.js`
- Create: `src/novel_dev/web/e2e/helpers/visualChecks.js`
- Create: `src/novel_dev/web/e2e/flows/navigation.spec.js`

- [ ] **Step 1: Install Playwright test dependency**

Run:

```bash
cd src/novel_dev/web
npm install -D @playwright/test
```

Expected: `package.json` and `package-lock.json` update.

- [ ] **Step 2: Add Playwright scripts**

Modify `src/novel_dev/web/package.json` scripts:

```json
{
  "scripts": {
    "dev": "vite --host",
    "build": "vite build",
    "preview": "vite preview",
    "test": "vitest run --config vitest.config.js",
    "test:watch": "vitest --config vitest.config.js",
    "test:e2e": "playwright test e2e/flows",
    "test:visual": "playwright test e2e/visual"
  }
}
```

- [ ] **Step 3: Add Playwright config**

Create `src/novel_dev/web/playwright.config.js`:

```javascript
import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
  ],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium-desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } },
    },
    {
      name: 'chromium-mobile',
      use: { ...devices['Pixel 7'] },
    },
  ],
})
```

- [ ] **Step 4: Add structured visual helper**

Create `src/novel_dev/web/e2e/helpers/visualChecks.js`:

```javascript
import { expect } from '@playwright/test'

export async function expectUsablePage(page, selector = '#app') {
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') {
      errors.push(message.text())
    }
  })

  await expect(page.locator(selector)).toBeVisible()
  await page.waitForLoadState('networkidle')

  const bodyBox = await page.locator('body').boundingBox()
  expect(bodyBox && bodyBox.width ? bodyBox.width : 0).toBeGreaterThan(0)
  expect(bodyBox && bodyBox.height ? bodyBox.height : 0).toBeGreaterThan(0)

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2)
  expect(overflow).toBe(false)
  expect(errors).toEqual([])
}
```

- [ ] **Step 5: Add navigation smoke spec**

Create `src/novel_dev/web/e2e/flows/navigation.spec.js`:

```javascript
import { expect, test } from '@playwright/test'
import { expectUsablePage } from '../helpers/visualChecks.js'

const routes = [
  ['/dashboard', /dashboard|总览|工作台/i],
  ['/documents', /documents|文档|设定/i],
  ['/volume-plan', /volume|分卷|大纲/i],
  ['/chapters', /chapter|章节/i],
  ['/entities', /entity|实体/i],
  ['/logs', /log|日志/i],
  ['/config', /config|配置/i],
]

test.describe('navigation smoke', () => {
  for (const [route, titlePattern] of routes) {
    test(`opens ${route}`, async ({ page }) => {
      await page.goto(route)
      await expectUsablePage(page)
      await expect(page.locator('body')).toContainText(titlePattern)
    })
  }
})
```

- [ ] **Step 6: Run Playwright install and navigation smoke**

Run:

```bash
cd src/novel_dev/web
npx playwright install chromium
npm run test:e2e
```

Expected: tests run against a local Vite server if one is running. If no server is running, failure should be connection refused and fixed by Task 11 wrapper.

- [ ] **Step 7: Commit**

```bash
git add src/novel_dev/web/package.json src/novel_dev/web/package-lock.json src/novel_dev/web/playwright.config.js src/novel_dev/web/e2e/helpers/visualChecks.js src/novel_dev/web/e2e/flows/navigation.spec.js
git commit -m "test: add playwright navigation smoke"
```

---

### Task 10: Web Generation Flow And Visual Specs

**Files:**
- Create: `src/novel_dev/web/e2e/flows/generation.spec.js`
- Create: `src/novel_dev/web/e2e/visual/layout.spec.js`
- Create: `src/novel_dev/web/e2e/helpers/reporting.js`

- [ ] **Step 1: Add Web reporting helper**

Create `src/novel_dev/web/e2e/helpers/reporting.js`:

```javascript
import fs from 'node:fs'
import path from 'node:path'

export function writeWebIssue(issue) {
  const reportRoot = process.env.TEST_RUN_REPORT_DIR
  if (!reportRoot) return
  const dir = path.join(reportRoot, 'artifacts', 'web-issues')
  fs.mkdirSync(dir, { recursive: true })
  const file = path.join(dir, `${issue.id}.json`)
  fs.writeFileSync(file, `${JSON.stringify(issue, null, 2)}\n`, 'utf8')
}
```

- [ ] **Step 2: Add generation UI flow spec**

Create `src/novel_dev/web/e2e/flows/generation.spec.js`:

```javascript
import { expect, test } from '@playwright/test'
import { expectUsablePage } from '../helpers/visualChecks.js'

test('creates a novel and reaches settings entry point', async ({ page, request }) => {
  const title = `Playwright 生成验收 ${Date.now()}`
  const create = await request.post('/api/novels', { data: { title } })
  expect(create.ok()).toBe(true)
  const novel = await create.json()

  await page.goto('/dashboard')
  await expectUsablePage(page)
  await expect(page.locator('body')).toContainText(title)

  await page.goto('/documents')
  await expectUsablePage(page)

  const session = await request.post(`/api/novels/${novel.novel_id}/settings/sessions`, {
    data: {
      title: 'Playwright 设定会话',
      initial_idea: '生成青云宗、林照、玄火盟和第一章冲突。',
      target_categories: [],
    },
  })
  expect(session.ok()).toBe(true)

  await page.goto('/documents?tab=ai')
  await expectUsablePage(page)
  await expect(page.locator('body')).toContainText(/Playwright 设定会话|设定/)
})
```

- [ ] **Step 3: Add layout visual spec**

Create `src/novel_dev/web/e2e/visual/layout.spec.js`:

```javascript
import { test } from '@playwright/test'
import { expectUsablePage } from '../helpers/visualChecks.js'

const pages = [
  '/dashboard',
  '/documents',
  '/volume-plan',
  '/chapters',
  '/entities',
  '/logs',
  '/config',
]

test.describe('structured layout checks', () => {
  for (const route of pages) {
    test(`layout is usable at ${route}`, async ({ page }) => {
      await page.goto(route)
      await expectUsablePage(page)
    })
  }
})
```

- [ ] **Step 4: Run E2E and visual specs**

With API and Vite running:

```bash
cd src/novel_dev/web
npm run test:e2e
npm run test:visual
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/web/e2e/helpers/reporting.js src/novel_dev/web/e2e/flows/generation.spec.js src/novel_dev/web/e2e/visual/layout.spec.js
git commit -m "test: add web generation and visual checks"
```

---

### Task 11: Web E2E Shell Entrypoint

**Files:**
- Create: `scripts/verify_web_e2e.sh`

- [ ] **Step 1: Create Web E2E wrapper**

Create `scripts/verify_web_e2e.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_DIR="${ROOT_DIR}/src/novel_dev/web"
API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8000}"
WEB_HOST="${WEB_HOST:-127.0.0.1}"
WEB_PORT="${WEB_PORT:-5173}"
REPORT_ROOT="${REPORT_ROOT:-${ROOT_DIR}/reports/test-runs}"
RUN_ID="${RUN_ID:-$(date +%Y-%m-%dT%H%M%S)-web-e2e}"
TEST_RUN_REPORT_DIR="${REPORT_ROOT}/${RUN_ID}"

mkdir -p "${TEST_RUN_REPORT_DIR}/artifacts"

if ! curl -s -o /dev/null "${API_BASE_URL}/healthz"; then
  echo "API is not reachable at ${API_BASE_URL}/healthz"
  exit 1
fi

cd "${WEB_DIR}"
npm install --prefer-offline --no-audit --fund=false

npm run dev -- --host "${WEB_HOST}" --port "${WEB_PORT}" >"${TEST_RUN_REPORT_DIR}/artifacts/vite.log" 2>&1 &
VITE_PID="$!"
trap 'kill "${VITE_PID}" >/dev/null 2>&1 || true' EXIT

for _ in {1..60}; do
  if curl -s -o /dev/null "http://${WEB_HOST}:${WEB_PORT}/"; then
    break
  fi
  sleep 1
done

export PLAYWRIGHT_BASE_URL="http://${WEB_HOST}:${WEB_PORT}"
export TEST_RUN_REPORT_DIR
npm run test:e2e
npm run test:visual
```

- [ ] **Step 2: Make wrapper executable**

Run:

```bash
chmod +x scripts/verify_web_e2e.sh
```

Expected: command succeeds.

- [ ] **Step 3: Run wrapper**

With API running:

```bash
scripts/verify_web_e2e.sh
```

Expected: PASS and writes Vite logs under `reports/test-runs/<run-id>/artifacts/vite.log`.

- [ ] **Step 4: Commit**

```bash
git add scripts/verify_web_e2e.sh
git commit -m "test: add web e2e verification entrypoint"
```

---

### Task 12: Final Integration Verification

**Files:**
- Modify only files needed to fix failures found by the commands in this task.

- [ ] **Step 1: Run focused Python testing support tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing tests/generation/test_minimal_generation_flow.py -q
```

Expected: PASS.

- [ ] **Step 2: Run stable local gate**

Run:

```bash
scripts/verify_local.sh
```

Expected: PASS.

- [ ] **Step 3: Run generation fake mode report**

Run:

```bash
LLM_MODE=fake scripts/verify_generation_real.sh
```

Expected: PASS and creates a `summary.json` with status `passed`.

- [ ] **Step 4: Run generation real mode when local services and credentials are available**

Run:

```bash
scripts/verify_generation_real.sh
```

Expected: PASS if API and LLM services are healthy. If it fails, `summary.json` must classify the issue as `EXTERNAL_BLOCKED`, `SYSTEM_BUG`, `LLM_PARSE_ERROR`, `TIMEOUT_INTERNAL`, or `GENERATION_QUALITY`.

- [ ] **Step 5: Run Web E2E**

With API running:

```bash
scripts/verify_web_e2e.sh
```

Expected: PASS.

- [ ] **Step 6: Commit final fixes**

```bash
git status --short
git add src/novel_dev/testing tests/test_testing tests/generation scripts src/novel_dev/web/package.json src/novel_dev/web/package-lock.json src/novel_dev/web/playwright.config.js src/novel_dev/web/e2e
git commit -m "test: add codex generation and web verification"
```
