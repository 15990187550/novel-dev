# Real LLM Acceptance Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the real LLM generation acceptance runner validate explicit stage contracts, report actionable failures, and separate default contract validation from strict export validation.

**Architecture:** Add a focused `generation_contracts.py` module for pure contract parsing and evidence building, then update `generation_runner.py` to call those helpers after successful API stages. Keep `real-contract` as the default scope and add `real-e2e-export` for stricter archive-plus-export validation.

**Tech Stack:** Python 3.11, pytest, httpx, SQLAlchemy async, existing `novel_dev.testing` report and generation runner.

---

## File Structure

- Create: `src/novel_dev/testing/generation_contracts.py`
  - Owns pure helpers for extracting a chapter plan, summarizing checkpoint keys, detecting generated chapter text, summarizing quality state, and deciding whether export is required.
- Create: `tests/test_testing/test_generation_contracts.py`
  - Unit tests for the pure helpers without API, database, or LLM calls.
- Modify: `src/novel_dev/testing/generation_runner.py`
  - Adds `AcceptanceScope`, scope validation, contract artifacts, stage-specific contract failures, chapter text inspection, quality gate reporting, and conditional export behavior.
- Modify: `src/novel_dev/testing/cli.py`
  - Adds `--acceptance-scope`.
- Modify: `scripts/verify_generation_real.sh`
  - Adds `ACCEPTANCE_SCOPE` environment forwarding.
- Modify: `tests/test_testing/test_generation_runner.py`
  - Tests runner integration for scope parsing, volume contract failure, quality gate reporting, and export behavior.

## Scope Notes

This plan does not change production APIs, LLM prompts, fiction quality scoring, or historical report cleanup.

The implementation should keep current CLI stage names working. Contract failures are expressed through issue `stage` values such as `volume_plan_contract`, `quality_gate`, and `export_contract`.

---

### Task 1: Add Acceptance Scope Option

**Files:**
- Modify: `src/novel_dev/testing/generation_runner.py`
- Modify: `src/novel_dev/testing/cli.py`
- Modify: `scripts/verify_generation_real.sh`
- Test: `tests/test_testing/test_generation_runner.py`

- [ ] **Step 1: Write failing scope validation tests**

Add this test block to `tests/test_testing/test_generation_runner.py`:

```python
import pytest

from novel_dev.testing.generation_runner import (
    GenerationRunOptions,
    validate_acceptance_scope,
)


def test_acceptance_scope_defaults_to_real_contract():
    assert GenerationRunOptions().acceptance_scope == "real-contract"


def test_validate_acceptance_scope_accepts_known_scopes():
    assert validate_acceptance_scope("real-contract") == "real-contract"
    assert validate_acceptance_scope("real-e2e-export") == "real-e2e-export"


def test_validate_acceptance_scope_rejects_unknown_scope():
    with pytest.raises(ValueError, match="Unknown acceptance scope"):
        validate_acceptance_scope("full")
```

- [ ] **Step 2: Run the new scope tests and verify they fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_generation_runner.py::test_acceptance_scope_defaults_to_real_contract tests/test_testing/test_generation_runner.py::test_validate_acceptance_scope_accepts_known_scopes tests/test_testing/test_generation_runner.py::test_validate_acceptance_scope_rejects_unknown_scope -q
```

Expected: FAIL because `validate_acceptance_scope` and `GenerationRunOptions.acceptance_scope` do not exist.

- [ ] **Step 3: Implement scope validation**

In `src/novel_dev/testing/generation_runner.py`, update imports and option definitions:

```python
from typing import Any, Awaitable, Callable, Literal


AcceptanceScope = Literal["real-contract", "real-e2e-export"]
```

Add this function near `validate_stage`:

```python
def validate_acceptance_scope(scope: str | None) -> AcceptanceScope:
    if scope in {None, ""}:
        return "real-contract"
    if scope in {"real-contract", "real-e2e-export"}:
        return scope
    raise ValueError(
        "Unknown acceptance scope: "
        f"{scope}. Valid scopes: real-contract, real-e2e-export"
    )
```

Update `GenerationRunOptions`:

```python
@dataclass(frozen=True, slots=True)
class GenerationRunOptions:
    dataset: str = "minimal_builtin"
    llm_mode: LLMMode = "real_then_fake_on_external_block"
    acceptance_scope: AcceptanceScope = "real-contract"
    stage: str | None = None
    run_id: str | None = None
    report_root: str = "reports/test-runs"
    api_base_url: str = "http://127.0.0.1:8000"
```

In `run_generation_acceptance`, add scope validation and artifact recording:

```python
target_stage = validate_stage(options.stage)
acceptance_scope = validate_acceptance_scope(options.acceptance_scope)
```

Set the artifact value:

```python
report.artifacts["contract_scope"] = acceptance_scope
report.artifacts["acceptance_scope"] = acceptance_scope
```

- [ ] **Step 4: Add CLI and script forwarding**

In `src/novel_dev/testing/cli.py`, add the argument:

```python
generation.add_argument(
    "--acceptance-scope",
    choices=("real-contract", "real-e2e-export"),
    default="real-contract",
)
```

Pass it into `GenerationRunOptions`:

```python
options = GenerationRunOptions(
    dataset=args.dataset,
    llm_mode=args.llm_mode,
    acceptance_scope=args.acceptance_scope,
    stage=args.stage,
    run_id=args.run_id,
    report_root=args.report_root,
    api_base_url=args.api_base_url,
)
```

In `scripts/verify_generation_real.sh`, add:

```bash
ACCEPTANCE_SCOPE="${ACCEPTANCE_SCOPE:-real-contract}"
```

Add the CLI argument in the `args` array:

```bash
--acceptance-scope "${ACCEPTANCE_SCOPE}"
```

- [ ] **Step 5: Run scope tests and commit**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_generation_runner.py::test_acceptance_scope_defaults_to_real_contract tests/test_testing/test_generation_runner.py::test_validate_acceptance_scope_accepts_known_scopes tests/test_testing/test_generation_runner.py::test_validate_acceptance_scope_rejects_unknown_scope -q
```

Expected: PASS.

Commit:

```bash
git add src/novel_dev/testing/generation_runner.py src/novel_dev/testing/cli.py scripts/verify_generation_real.sh tests/test_testing/test_generation_runner.py
git commit -m "test: add real llm acceptance scope option"
```

---

### Task 2: Add Pure Contract Helpers

**Files:**
- Create: `src/novel_dev/testing/generation_contracts.py`
- Test: `tests/test_testing/test_generation_contracts.py`

- [ ] **Step 1: Write failing helper tests**

Create `tests/test_testing/test_generation_contracts.py`:

```python
from types import SimpleNamespace

from novel_dev.testing.generation_contracts import (
    build_volume_plan_contract_evidence,
    detect_chapter_text,
    extract_chapter_plan,
    summarize_quality_gate,
)


def test_extract_chapter_plan_from_current_chapter_plan():
    response = {"volume_id": "vol-1"}
    checkpoint = {
        "current_chapter_plan": {
            "chapter_id": "ch-1",
            "chapter_number": 2,
            "title": "First Plan",
            "summary": "A usable summary",
            "beats": [{"summary": "beat"}],
        }
    }

    result = extract_chapter_plan(response, checkpoint)

    assert result is not None
    assert result.source == "current_chapter_plan"
    assert result.plan["chapter_id"] == "ch-1"


def test_extract_chapter_plan_from_current_volume_plan_chapters():
    response = {"volume_id": "vol-1"}
    checkpoint = {
        "current_volume_plan": {
            "chapters": [
                {
                    "chapter_id": "ch-2",
                    "chapter_number": 1,
                    "title": "Volume Chapter",
                    "summary": "A usable summary",
                }
            ]
        }
    }

    result = extract_chapter_plan(response, checkpoint)

    assert result is not None
    assert result.source == "current_volume_plan.chapters[0]"
    assert result.plan["chapter_id"] == "ch-2"


def test_extract_chapter_plan_from_response_chapter():
    response = {
        "chapter": {
            "chapter_id": "ch-3",
            "chapter_number": 1,
            "title": "Response Chapter",
            "summary": "A usable summary",
        }
    }
    checkpoint = {}

    result = extract_chapter_plan(response, checkpoint)

    assert result is not None
    assert result.source == "response.chapter"
    assert result.plan["chapter_id"] == "ch-3"


def test_extract_chapter_plan_rejects_plan_without_text_material():
    response = {}
    checkpoint = {"current_chapter_plan": {"chapter_id": "ch-4", "chapter_number": 1}}

    assert extract_chapter_plan(response, checkpoint) is None


def test_build_volume_plan_contract_evidence_lists_keys_and_counts():
    response = {"volume_id": "vol-1"}
    checkpoint = {
        "synopsis_data": {},
        "current_volume_plan": {"volume_id": "vol-1", "chapters": []},
    }

    evidence = build_volume_plan_contract_evidence(response, checkpoint)

    assert "response_keys=volume_id" in evidence
    assert "checkpoint_keys=current_volume_plan,synopsis_data" in evidence
    assert "current_chapter_plan_present=false" in evidence
    assert "current_volume_plan_keys=chapters,volume_id" in evidence
    assert "current_volume_plan_chapter_count=0" in evidence


def test_detect_chapter_text_prefers_polished_text():
    chapter = SimpleNamespace(raw_draft="raw text", polished_text="polished text")

    status = detect_chapter_text(chapter)

    assert status.field == "polished_text"
    assert status.length == len("polished text")
    assert status.has_text is True


def test_detect_chapter_text_handles_missing_chapter():
    status = detect_chapter_text(None)

    assert status.field == "none"
    assert status.length == 0
    assert status.has_text is False


def test_summarize_quality_gate_returns_status_and_reasons():
    chapter = SimpleNamespace(
        quality_status="block",
        quality_reasons={"word_count_drift": "too short"},
    )

    summary = summarize_quality_gate(chapter)

    assert summary.status == "block"
    assert "word_count_drift" in summary.reasons
```

- [ ] **Step 2: Run helper tests and verify they fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_generation_contracts.py -q
```

Expected: FAIL because `generation_contracts.py` does not exist.

- [ ] **Step 3: Implement helper module**

Create `src/novel_dev/testing/generation_contracts.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ChapterPlanExtraction:
    source: str
    plan: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ChapterTextStatus:
    field: str
    length: int
    has_text: bool


@dataclass(frozen=True, slots=True)
class QualityGateSummary:
    status: str
    reasons: str


def extract_chapter_plan(
    response: dict[str, Any],
    checkpoint: dict[str, Any],
) -> ChapterPlanExtraction | None:
    candidates = [
        ("current_chapter_plan", checkpoint.get("current_chapter_plan")),
        (
            "current_volume_plan.chapters[0]",
            _first_chapter_from_volume_plan(checkpoint.get("current_volume_plan")),
        ),
        ("response.chapter", response.get("chapter")),
        ("response.current_chapter_plan", response.get("current_chapter_plan")),
    ]
    for source, value in candidates:
        if isinstance(value, dict) and _is_usable_chapter_plan(value):
            return ChapterPlanExtraction(source=source, plan=dict(value))
    return None


def build_volume_plan_contract_evidence(
    response: dict[str, Any],
    checkpoint: dict[str, Any],
) -> list[str]:
    current_volume_plan = checkpoint.get("current_volume_plan")
    evidence = [
        f"response_keys={_sorted_keys(response)}",
        f"checkpoint_keys={_sorted_keys(checkpoint)}",
        "current_chapter_plan_present="
        f"{str(isinstance(checkpoint.get('current_chapter_plan'), dict)).lower()}",
    ]
    if isinstance(current_volume_plan, dict):
        chapters = current_volume_plan.get("chapters")
        count = len(chapters) if isinstance(chapters, list) else 0
        evidence.extend(
            [
                f"current_volume_plan_keys={_sorted_keys(current_volume_plan)}",
                f"current_volume_plan_chapter_count={count}",
            ]
        )
    else:
        evidence.append("current_volume_plan_present=false")
    return evidence


def detect_chapter_text(chapter: Any | None) -> ChapterTextStatus:
    if chapter is None:
        return ChapterTextStatus(field="none", length=0, has_text=False)
    polished = (getattr(chapter, "polished_text", None) or "").strip()
    if polished:
        return ChapterTextStatus(
            field="polished_text",
            length=len(polished),
            has_text=True,
        )
    raw = (getattr(chapter, "raw_draft", None) or "").strip()
    if raw:
        return ChapterTextStatus(field="raw_draft", length=len(raw), has_text=True)
    return ChapterTextStatus(field="none", length=0, has_text=False)


def summarize_quality_gate(chapter: Any | None) -> QualityGateSummary:
    if chapter is None:
        return QualityGateSummary(status="missing_chapter", reasons="")
    status = str(getattr(chapter, "quality_status", "unchecked") or "unchecked")
    reasons_value = getattr(chapter, "quality_reasons", None)
    if isinstance(reasons_value, dict):
        reasons = ",".join(sorted(str(key) for key in reasons_value))
    elif reasons_value is None:
        reasons = ""
    else:
        reasons = str(reasons_value)
    return QualityGateSummary(status=status, reasons=reasons)


def _first_chapter_from_volume_plan(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    chapters = value.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        return None
    first = chapters[0]
    return first if isinstance(first, dict) else None


def _is_usable_chapter_plan(value: dict[str, Any]) -> bool:
    has_id_or_number = bool(value.get("chapter_id")) or value.get("chapter_number") is not None
    has_text_material = any(
        bool(value.get(key)) for key in ("title", "summary", "beats")
    )
    return has_id_or_number and has_text_material


def _sorted_keys(value: dict[str, Any]) -> str:
    keys = sorted(str(key) for key in value.keys())
    return ",".join(keys) if keys else "none"
```

- [ ] **Step 4: Run helper tests and commit**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_generation_contracts.py -q
```

Expected: PASS.

Commit:

```bash
git add src/novel_dev/testing/generation_contracts.py tests/test_testing/test_generation_contracts.py
git commit -m "test: add real generation contract helpers"
```

---

### Task 3: Record Brainstorm Contract And Convert Volume Plan Preparation

**Files:**
- Modify: `src/novel_dev/testing/generation_runner.py`
- Test: `tests/test_testing/test_generation_runner.py`

- [ ] **Step 1: Write failing brainstorm artifact test**

Add this test to `tests/test_testing/test_generation_runner.py`:

```python
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
```

- [ ] **Step 2: Run the brainstorm artifact test and verify it fails**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_generation_runner.py::test_prepare_minimal_synopsis_returns_original_scale_artifacts -q
```

Expected: FAIL because `_prepare_minimal_synopsis` currently returns `None`.

- [ ] **Step 3: Add brainstorm contract result**

In `src/novel_dev/testing/generation_runner.py`, add this dataclass near `MinimalChapterPlanResult`:

```python
@dataclass(frozen=True, slots=True)
class BrainstormContractResult:
    original_estimated_volumes: int | None
    original_estimated_total_chapters: int | None
    shrunk_estimated_total_chapters: int
```

Change `_prepare_minimal_synopsis` to return `BrainstormContractResult`:

```python
async def _prepare_minimal_synopsis(
    novel_id: str,
    fixture: GenerationFixture,
) -> BrainstormContractResult:
```

Before mutating `synopsis`, capture original values:

```python
original_estimated_volumes = _coerce_int(synopsis.get("estimated_volumes"))
original_estimated_total_chapters = _coerce_int(
    synopsis.get("estimated_total_chapters")
)
```

At the end of `_prepare_minimal_synopsis`, return:

```python
return BrainstormContractResult(
    original_estimated_volumes=original_estimated_volumes,
    original_estimated_total_chapters=original_estimated_total_chapters,
    shrunk_estimated_total_chapters=1,
)
```

In `_run_api_smoke_flow`, replace the current call:

```python
brainstorm_contract = await _prepare_minimal_synopsis(novel_id, fixture)
if brainstorm_contract.original_estimated_volumes is not None:
    artifacts["brainstorm_original_estimated_volumes"] = str(
        brainstorm_contract.original_estimated_volumes
    )
if brainstorm_contract.original_estimated_total_chapters is not None:
    artifacts["brainstorm_original_estimated_total_chapters"] = str(
        brainstorm_contract.original_estimated_total_chapters
    )
artifacts["brainstorm_shrunk_estimated_total_chapters"] = str(
    brainstorm_contract.shrunk_estimated_total_chapters
)
```

- [ ] **Step 4: Write failing volume contract tests**

Add these tests to `tests/test_testing/test_generation_runner.py`:

```python
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

    assert result.target_word_count == fixture.minimum_chapter_chars
    assert result.chapter_id == "acceptance-novel-test-ch1"
    assert result.source == "current_volume_plan.chapters[0]"


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
```

- [ ] **Step 5: Run volume contract tests and verify they fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_generation_runner.py::test_prepare_minimal_chapter_plan_uses_volume_plan_chapter_when_current_chapter_missing tests/test_testing/test_generation_runner.py::test_prepare_minimal_chapter_plan_reports_contract_evidence_when_missing -q
```

Expected: FAIL because `_prepare_minimal_chapter_plan` does not accept `volume_plan_response`, does not return a result object, and does not raise `ContractValidationError`.

- [ ] **Step 6: Add contract error and result types**

In `src/novel_dev/testing/generation_runner.py`, import helpers:

```python
from novel_dev.testing.generation_contracts import (
    build_volume_plan_contract_evidence,
    extract_chapter_plan,
)
```

Add these definitions near the constants:

```python
@dataclass(frozen=True, slots=True)
class MinimalChapterPlanResult:
    chapter_id: str
    volume_id: str
    source: str
    target_word_count: int


class ContractValidationError(RuntimeError):
    def __init__(self, stage: str, message: str, evidence: list[str]):
        super().__init__(message)
        self.stage = stage
        self.evidence = evidence
```

- [ ] **Step 7: Update classification to preserve contract stage and evidence**

In `classify_exception`, add this branch before `httpx.HTTPStatusError`:

```python
if isinstance(exc, ContractValidationError):
    issue_type = "SYSTEM_BUG"
    return Issue(
        id=f"{issue_type}-{exc.stage}",
        type=issue_type,
        severity="high",
        stage=exc.stage,
        is_external_blocker=False,
        real_llm=real_llm,
        fake_rerun_status=None,
        message=str(exc) or exc.__class__.__name__,
        evidence=exc.evidence,
        reproduce=_reproduce_command_for_stage(exc.stage),
    )
```

Keep the rest of the existing classification logic in an `elif` chain after this branch.

- [ ] **Step 8: Update `_prepare_minimal_chapter_plan` signature and extraction**

Change the function signature:

```python
async def _prepare_minimal_chapter_plan(
    novel_id: str,
    fixture: GenerationFixture,
    *,
    volume_plan_response: dict[str, Any],
) -> MinimalChapterPlanResult:
```

Replace the initial current chapter lookup with:

```python
checkpoint = dict(state.checkpoint_data or {})
extraction = extract_chapter_plan(volume_plan_response, checkpoint)
if extraction is None:
    raise ContractValidationError(
        "volume_plan_contract",
        "volume_plan did not produce a usable chapter plan",
        build_volume_plan_contract_evidence(volume_plan_response, checkpoint),
    )

current_chapter_plan = dict(extraction.plan)
```

At the end, return:

```python
return MinimalChapterPlanResult(
    chapter_id=isolated_chapter_id,
    volume_id=isolated_volume_id,
    source=extraction.source,
    target_word_count=target_word_count,
)
```

- [ ] **Step 9: Update runner call site**

In `_run_api_smoke_flow`, capture the volume plan response:

```python
volume_plan_response: dict[str, Any] = {}

async def volume_plan() -> None:
    nonlocal volume_plan_response
    data = await _request_json(
        client.post(
            f"/api/novels/{novel_id}/volume_plan",
            json={"volume_number": 1},
        )
    )
    volume_plan_response = data
    volume_id = _first_string(data, "volume_id", "id")
    if volume_id is not None:
        artifacts["volume_id"] = volume_id
```

Update the preparation call:

```python
chapter_plan = await _prepare_minimal_chapter_plan(
    novel_id,
    fixture,
    volume_plan_response=volume_plan_response,
)
artifacts["chapter_id"] = chapter_plan.chapter_id
artifacts["chapter_plan_source"] = chapter_plan.source
artifacts["chapter_target_word_count"] = str(chapter_plan.target_word_count)
```

- [ ] **Step 10: Run focused tests and commit**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_generation_runner.py::test_prepare_minimal_chapter_plan_uses_volume_plan_chapter_when_current_chapter_missing tests/test_testing/test_generation_runner.py::test_prepare_minimal_chapter_plan_reports_contract_evidence_when_missing -q
```

Expected: PASS.

Commit:

```bash
git add src/novel_dev/testing/generation_runner.py tests/test_testing/test_generation_runner.py
git commit -m "test: validate volume plan contract"
```

---

### Task 4: Add Chapter Text And Quality Gate Contract Integration

**Files:**
- Modify: `src/novel_dev/testing/generation_runner.py`
- Test: `tests/test_testing/test_generation_runner.py`

- [ ] **Step 1: Write failing quality gate integration test**

Add this test to `tests/test_testing/test_generation_runner.py`:

```python
@pytest.mark.asyncio
async def test_api_smoke_flow_reports_quality_gate_when_text_exists_without_archive(monkeypatch):
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
                    {"session": {"status": "ready_to_generate", "clarification_round": 1}},
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
                raise AssertionError("default real-contract should not export after quality block")
            raise AssertionError(f"Unexpected POST request: {path}")

        def _response(self, method, path, data):
            request = httpx.Request(method, f"http://testserver{path}")
            return httpx.Response(200, request=request, json=data)

    async def immediate_sleep(_seconds):
        return None

    async def fake_prepare_minimal_synopsis(novel_id, fixture):
        return None

    async def fake_prepare_minimal_chapter_plan(novel_id, fixture, *, volume_plan_response):
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
    monkeypatch.setattr(generation_runner, "_prepare_minimal_synopsis", fake_prepare_minimal_synopsis)
    monkeypatch.setattr(generation_runner, "_prepare_minimal_chapter_plan", fake_prepare_minimal_chapter_plan)
    monkeypatch.setattr(generation_runner, "_get_chapter_contract_state", fake_get_chapter_contract_state)

    fixture = generation_runner.load_generation_fixture("minimal_builtin")
    artifacts, issues = await generation_runner._run_api_smoke_flow(
        GenerationRunOptions(llm_mode="real", acceptance_scope="real-contract"),
        fixture,
    )

    assert artifacts["chapter_text_status"] == "polished_text"
    assert artifacts["chapter_text_length"] == str(len("polished generated chapter"))
    assert artifacts["quality_status"] == "block"
    assert artifacts["quality_reasons"] == "word_count_drift"
    assert artifacts["export_status"] == "not_applicable_quality_blocked"
    assert len(issues) == 1
    assert issues[0].stage == "quality_gate"
    assert issues[0].type == "SYSTEM_BUG"
```

- [ ] **Step 2: Run the quality gate test and verify it fails**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_generation_runner.py::test_api_smoke_flow_reports_quality_gate_when_text_exists_without_archive -q
```

Expected: FAIL because chapter contract inspection is not integrated and export is still unconditional.

- [ ] **Step 3: Implement chapter contract state loading**

In `src/novel_dev/testing/generation_runner.py`, import helpers:

```python
from novel_dev.testing.generation_contracts import (
    build_volume_plan_contract_evidence,
    detect_chapter_text,
    extract_chapter_plan,
    summarize_quality_gate,
)
```

Add this helper:

```python
async def _get_chapter_contract_state(novel_id: str, chapter_id: str) -> Any | None:
    async with async_session_maker() as session:
        chapter = await ChapterRepository(session).get_by_id(chapter_id)
        if chapter is None or chapter.novel_id != novel_id:
            return None
        return chapter
```

- [ ] **Step 4: Update `auto_run_chapters` contract logic**

In `_run_api_smoke_flow`, before `auto_run_chapters`, add:

```python
quality_gate_issue: Issue | None = None
export_required = False
```

Inside `auto_run_chapters`, after archive stats are fetched, replace the existing archived-count failure with:

```python
nonlocal quality_gate_issue, export_required

stopped_reason = _first_string(result_payload, "stopped_reason")
if stopped_reason is not None:
    artifacts["chapter_job_stopped_reason"] = stopped_reason

chapter_id = artifacts.get("chapter_id")
if chapter_id is None:
    raise ContractValidationError(
        "auto_run_chapters_contract",
        "auto_run_chapters missing prepared chapter_id",
        [],
    )

chapter = await _get_chapter_contract_state(novel_id, chapter_id)
text_status = detect_chapter_text(chapter)
artifacts["chapter_text_status"] = text_status.field
artifacts["chapter_text_length"] = str(text_status.length)
if not text_status.has_text:
    raise ContractValidationError(
        "auto_run_chapters_contract",
        "auto_run_chapters completed without generated chapter text",
        [f"chapter_id={chapter_id}", f"job_id={job_id}"],
    )

quality = summarize_quality_gate(chapter)
artifacts["quality_status"] = quality.status
if quality.reasons:
    artifacts["quality_reasons"] = quality.reasons

stats = await _request_json(client.get(f"/api/novels/{novel_id}/archive_stats"))
archived_count = _coerce_int(stats.get("archived_chapter_count")) or 0
artifacts["archived_chapter_count"] = str(archived_count)
export_required = archived_count >= 1

if archived_count < 1 and quality.status == "block":
    quality_gate_issue = Issue(
        id="SYSTEM_BUG-quality_gate",
        type="SYSTEM_BUG",
        severity="high",
        stage="quality_gate",
        is_external_blocker=False,
        real_llm=True,
        fake_rerun_status=None,
        message="Chapter generated text but quality gate blocked archival",
        evidence=[
            f"chapter_id={chapter_id}",
            f"quality_status={quality.status}",
            f"quality_reasons={quality.reasons or 'none'}",
        ],
        reproduce="scripts/verify_generation_real.sh --stage auto_run_chapters",
    )
```

After the `run_stage("auto_run_chapters", auto_run_chapters)` call succeeds, append the quality issue if present:

```python
if quality_gate_issue is not None:
    issues.append(quality_gate_issue)
```

- [ ] **Step 5: Run quality gate test and commit**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_generation_runner.py::test_api_smoke_flow_reports_quality_gate_when_text_exists_without_archive -q
```

Expected: PASS.

Commit:

```bash
git add src/novel_dev/testing/generation_runner.py tests/test_testing/test_generation_runner.py
git commit -m "test: report quality gate contract failures"
```

---

### Task 5: Make Export Conditional By Scope

**Files:**
- Modify: `src/novel_dev/testing/generation_runner.py`
- Test: `tests/test_testing/test_generation_runner.py`

- [ ] **Step 1: Write failing export scope tests**

Add these tests to `tests/test_testing/test_generation_runner.py`:

```python
def test_export_required_for_real_contract_only_when_archived():
    assert generation_runner._should_require_export("real-contract", archived_count=0) is False
    assert generation_runner._should_require_export("real-contract", archived_count=1) is True


def test_export_required_for_real_e2e_export_even_without_archive():
    assert generation_runner._should_require_export("real-e2e-export", archived_count=0) is True
```

- [ ] **Step 2: Run export scope tests and verify they fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_generation_runner.py::test_export_required_for_real_contract_only_when_archived tests/test_testing/test_generation_runner.py::test_export_required_for_real_e2e_export_even_without_archive -q
```

Expected: FAIL because `_should_require_export` does not exist.

- [ ] **Step 3: Implement export decision helper**

Add this helper to `src/novel_dev/testing/generation_runner.py`:

```python
def _should_require_export(scope: AcceptanceScope, *, archived_count: int) -> bool:
    if scope == "real-e2e-export":
        return True
    return archived_count >= 1
```

- [ ] **Step 4: Use export decision in `_run_api_smoke_flow`**

At the top of `_run_api_smoke_flow`, add:

```python
acceptance_scope = validate_acceptance_scope(options.acceptance_scope)
```

After `auto_run_chapters`, compute export behavior:

```python
archived_count = _coerce_int(artifacts.get("archived_chapter_count")) or 0
if not _should_require_export(acceptance_scope, archived_count=archived_count):
    artifacts["export_status"] = "not_applicable_quality_blocked"
    return artifacts, issues
```

For `real-e2e-export`, fail early if no archived chapter exists:

```python
if acceptance_scope == "real-e2e-export" and archived_count < 1:
    issues.append(
        Issue(
            id="SYSTEM_BUG-export_contract",
            type="SYSTEM_BUG",
            severity="high",
            stage="export_contract",
            is_external_blocker=False,
            real_llm=True,
            fake_rerun_status=None,
            message="real-e2e-export requires at least one archived chapter before export",
            evidence=[f"archived_chapter_count={archived_count}"],
            reproduce="scripts/verify_generation_real.sh --stage export --acceptance-scope real-e2e-export",
        )
    )
    return artifacts, issues
```

- [ ] **Step 5: Run export tests and commit**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_generation_runner.py::test_export_required_for_real_contract_only_when_archived tests/test_testing/test_generation_runner.py::test_export_required_for_real_e2e_export_even_without_archive -q
```

Expected: PASS.

Commit:

```bash
git add src/novel_dev/testing/generation_runner.py tests/test_testing/test_generation_runner.py
git commit -m "test: scope export contract requirements"
```

---

### Task 6: Rename Export Artifact Validation To Export Contract

**Files:**
- Modify: `src/novel_dev/testing/generation_runner.py`
- Test: `tests/test_testing/test_generation_runner.py`

- [ ] **Step 1: Write failing export contract classification test**

Update or add this test in `tests/test_testing/test_generation_runner.py`:

```python
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
    assert report.issues[0].stage == "export_contract"
    assert report.issues[0].type == "SYSTEM_BUG"
    assert "empty" in report.issues[0].message.lower()
```

- [ ] **Step 2: Run export contract classification test and verify it fails**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_generation_runner.py::test_generation_acceptance_reports_empty_export_as_export_contract -q
```

Expected: FAIL because empty export is currently classified with stage `export`.

- [ ] **Step 3: Update export validation to raise contract error**

Change `_validate_report_artifacts` in `src/novel_dev/testing/generation_runner.py`:

```python
def _validate_report_artifacts(artifacts: dict[str, str]) -> None:
    exported_path = artifacts.get("exported_path")
    if exported_path is None:
        return

    export_file = Path(exported_path)
    if not export_file.exists():
        raise ContractValidationError(
            "export_contract",
            f"Exported novel file missing: {exported_path}",
            [f"exported_path={exported_path}"],
        )
    if export_file.stat().st_size == 0:
        raise ContractValidationError(
            "export_contract",
            f"Exported novel file is empty: {exported_path}",
            [f"exported_path={exported_path}"],
        )
```

In `run_generation_acceptance`, keep this call:

```python
try:
    _validate_report_artifacts(report.artifacts)
except Exception as exc:
    report.add_issue(classify_exception("export_contract", exc, real_llm=False))
```

- [ ] **Step 4: Run export classification test and commit**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_generation_runner.py::test_generation_acceptance_reports_empty_export_as_export_contract -q
```

Expected: PASS.

Commit:

```bash
git add src/novel_dev/testing/generation_runner.py tests/test_testing/test_generation_runner.py
git commit -m "test: classify export artifact contract failures"
```

---

### Task 7: Full Testing Pass

**Files:**
- Verify: `src/novel_dev/testing/generation_contracts.py`
- Verify: `src/novel_dev/testing/generation_runner.py`
- Verify: `src/novel_dev/testing/cli.py`
- Verify: `scripts/verify_generation_real.sh`
- Verify: `tests/test_testing/test_generation_contracts.py`
- Verify: `tests/test_testing/test_generation_runner.py`
- Verify: `tests/test_testing/test_report.py`
- Verify: `tests/test_services/test_export_service.py`

- [ ] **Step 1: Run focused testing package**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing tests/test_services/test_export_service.py -q
```

Expected: PASS.

- [ ] **Step 2: Run CLI help smoke**

Run:

```bash
PYTHONPATH=src python3.11 -m novel_dev.testing.cli generation --help
```

Expected output includes:

```text
--acceptance-scope
```

- [ ] **Step 3: Run fake generation smoke**

Run:

```bash
scripts/verify_generation_real.sh --llm-mode fake --run-id contract-fake-smoke
```

Expected: command exits `0` and writes:

```text
reports/test-runs/contract-fake-smoke/summary.md
```

- [ ] **Step 4: Commit verification-safe changes**

Commit if there are uncommitted implementation changes:

```bash
git status --short
git add src/novel_dev/testing/generation_contracts.py src/novel_dev/testing/generation_runner.py src/novel_dev/testing/cli.py scripts/verify_generation_real.sh tests/test_testing/test_generation_contracts.py tests/test_testing/test_generation_runner.py
git commit -m "test: stabilize real llm contract acceptance"
```

---

### Task 8: Optional Real Contract Rerun

**Files:**
- Verify: `reports/test-runs/full-real-contract-recheck/summary.md`
- Verify: `reports/test-runs/full-real-contract-recheck/summary.json`

- [ ] **Step 1: Confirm local API is healthy**

Run:

```bash
curl -fsS http://127.0.0.1:8000/healthz
```

Expected:

```json
{"ok":true}
```

- [ ] **Step 2: Run default real contract check**

Run:

```bash
scripts/verify_generation_real.sh --run-id full-real-contract-recheck
```

Expected: command may pass or fail depending on real LLM output, but `summary.md` must show:

```text
contract_scope
```

If the run fails at volume planning, expected failure stage is:

```text
volume_plan_contract
```

If the run generates text but quality blocks archival, expected failure stage is:

```text
quality_gate
```

- [ ] **Step 3: Inspect real run summary**

Run:

```bash
sed -n '1,220p' reports/test-runs/full-real-contract-recheck/summary.md
```

Expected: summary includes artifacts and issue stage that matches the failed contract, if any.

- [ ] **Step 4: Do not commit generated reports by default**

Run:

```bash
git status --short reports
```

Expected: report files may appear under `reports/`; leave them uncommitted unless the user explicitly wants to preserve evidence in git.

---

## Plan Self-Review

Spec coverage:

- `real-contract` and `real-e2e-export` are implemented in Task 1 and Task 5.
- Brainstorm scope artifacts are covered by Task 3 through `BrainstormContractResult` and runner artifact recording.
- Volume plan contract extraction and evidence are covered by Task 2 and Task 3.
- Chapter text detection and quality gate reporting are covered by Task 2 and Task 4.
- Conditional export and strict export are covered by Task 5 and Task 6.
- Report artifacts and focused verification are covered by Task 7 and Task 8.

Placeholder scan:

- No step uses placeholder markers, empty "handle errors" language, or helper references without a task that defines them.

Type consistency:

- `AcceptanceScope`, `MinimalChapterPlanResult`, and `ContractValidationError` are introduced before use.
- `generation_contracts.py` helper names match all test references.
- Scope values are consistently `real-contract` and `real-e2e-export`.
