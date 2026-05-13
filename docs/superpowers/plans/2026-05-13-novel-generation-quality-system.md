# Novel Generation Quality System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a general quality system that standardizes novel generation issues, plans constrained repairs, improves resume diagnostics, and evaluates quality across reusable samples.

**Architecture:** Add compatibility-first schemas and adapters, then route existing review/gate/guard outputs through typed issues and repair tasks. Keep the current phase pipeline intact while adding beat boundary cards, repair planning, chapter run traces, and richer test reporting.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI service code, SQLAlchemy async repositories, existing pytest suite, existing real-generation scripts.

---

## Scope Check

The design touches several modules, but they are sequentially dependent rather than independent subsystems. `QualityIssue` is the shared contract for repair planning, run traces, and test reports, so this is one integrated plan with small commits per task.

## File Structure

- Create `src/novel_dev/schemas/quality.py`: Pydantic models and enums for `QualityIssue`, `BeatBoundaryCard`, `RepairTask`, `PhaseEvent`, and `ChapterRunTrace`.
- Modify `src/novel_dev/services/quality_gate_service.py`: convert legacy gate items into `QualityIssue` objects.
- Create `src/novel_dev/services/quality_issue_service.py`: normalize issues from critic, gate, guard, and continuity audit payloads.
- Create `src/novel_dev/services/beat_boundary_service.py`: build beat boundary cards from chapter plans.
- Create `src/novel_dev/services/repair_planner_service.py`: group issues into typed repair tasks.
- Modify `src/novel_dev/agents/writer_agent.py`: include beat boundary cards in writing prompts and checkpoint metadata.
- Modify `src/novel_dev/agents/editor_agent.py`: execute typed repair tasks and retain existing fallback behavior.
- Modify `src/novel_dev/agents/fast_review_agent.py`: emit standardized issues, create repair tasks, and store issue summaries.
- Modify `src/novel_dev/services/chapter_generation_service.py`: record chapter run traces and improve resume classification.
- Modify `src/novel_dev/testing/generation_contracts.py`: add unified chapter/run/export status helpers.
- Modify `src/novel_dev/testing/quality_summary.py`: aggregate quality issues by category, code, severity, and repairability.
- Add tests under `tests/test_schemas/`, `tests/test_services/`, `tests/test_agents/`, and `tests/test_testing/`.
- Add fixture data under `tests/generation/fixtures/quality/`.

## Implementation Tasks

### Task 1: Add Shared Quality Schemas

**Files:**
- Create: `src/novel_dev/schemas/quality.py`
- Test: `tests/test_schemas/test_quality.py`

- [ ] **Step 1: Write schema tests**

Create `tests/test_schemas/test_quality.py`:

```python
from novel_dev.schemas.quality import (
    BeatBoundaryCard,
    ChapterRunTrace,
    PhaseEvent,
    QualityIssue,
    RepairTask,
)


def test_quality_issue_defaults_are_isolated():
    first = QualityIssue(
        code="ai_flavor",
        category="prose",
        severity="warn",
        scope="chapter",
        repairability="guided",
        source="quality_gate",
    )
    second = QualityIssue(
        code="beat_cohesion",
        category="structure",
        severity="block",
        scope="beat",
        repairability="guided",
        source="fast_review",
    )

    first.evidence.append("模板化表达密集")

    assert first.evidence == ["模板化表达密集"]
    assert second.evidence == []


def test_repair_task_defaults_are_isolated():
    first = RepairTask(
        task_id="repair-1",
        chapter_id="ch-1",
        issue_codes=["text_integrity"],
        task_type="integrity_repair",
        scope="paragraph",
    )
    second = RepairTask(
        task_id="repair-2",
        chapter_id="ch-1",
        issue_codes=["required_payoff"],
        task_type="hook_repair",
        scope="beat",
        beat_index=2,
    )

    first.constraints.append("只修复断句")

    assert first.constraints == ["只修复断句"]
    assert second.constraints == []


def test_chapter_run_trace_serializes_nested_events():
    issue = QualityIssue(
        code="beat_cohesion",
        category="structure",
        severity="block",
        scope="beat",
        beat_index=1,
        repairability="guided",
        evidence=["BEAT1 与 BEAT2 重复"],
        suggestion="删除重复承接段",
        source="structure_guard",
    )
    trace = ChapterRunTrace(
        novel_id="novel-a",
        chapter_id="ch-1",
        run_id="run-1",
        current_phase="fast_reviewing",
        terminal_status="blocked",
        phase_events=[
            PhaseEvent(
                phase="fast_reviewing",
                status="blocked",
                started_at="2026-05-13T00:00:00Z",
                issues=[issue],
            )
        ],
    )

    data = trace.model_dump()

    assert data["phase_events"][0]["issues"][0]["code"] == "beat_cohesion"
    assert data["terminal_status"] == "blocked"


def test_beat_boundary_card_round_trip():
    card = BeatBoundaryCard(
        beat_index=0,
        must_cover=["主角发现线索"],
        allowed_materials=["旧信", "雨夜"],
        forbidden_materials=["新敌人现身"],
        reveal_boundary="只能暗示有人跟踪，不确认身份",
        ending_policy="停在未完成动作",
    )

    assert BeatBoundaryCard.model_validate(card.model_dump()).ending_policy == "停在未完成动作"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_schemas/test_quality.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'novel_dev.schemas.quality'`.

- [ ] **Step 3: Implement schemas**

Create `src/novel_dev/schemas/quality.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


QualityCategory = Literal["structure", "prose", "character", "plot", "continuity", "style", "process"]
QualitySeverity = Literal["info", "warn", "block"]
QualityScope = Literal["chapter", "beat", "paragraph", "flow"]
Repairability = Literal["auto", "guided", "manual", "none"]
QualitySource = Literal[
    "critic",
    "fast_review",
    "quality_gate",
    "structure_guard",
    "continuity_audit",
    "testing",
]


class QualityIssue(BaseModel):
    code: str
    category: QualityCategory
    severity: QualitySeverity
    scope: QualityScope
    beat_index: int | None = None
    repairability: Repairability
    evidence: list[str] = Field(default_factory=list)
    suggestion: str = ""
    source: QualitySource


class BeatBoundaryCard(BaseModel):
    beat_index: int
    must_cover: list[str] = Field(default_factory=list)
    allowed_materials: list[str] = Field(default_factory=list)
    forbidden_materials: list[str] = Field(default_factory=list)
    reveal_boundary: str = ""
    ending_policy: str = ""


class RepairTask(BaseModel):
    task_id: str
    chapter_id: str
    issue_codes: list[str] = Field(default_factory=list)
    task_type: Literal[
        "prose_polish",
        "cohesion_repair",
        "hook_repair",
        "character_repair",
        "integrity_repair",
        "continuity_repair",
    ]
    scope: Literal["chapter", "beat", "paragraph"]
    beat_index: int | None = None
    allowed_materials: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    attempt: int = 0


class PhaseEvent(BaseModel):
    phase: str
    status: Literal["started", "succeeded", "failed", "blocked", "skipped"]
    started_at: str
    ended_at: str | None = None
    input_summary: dict = Field(default_factory=dict)
    output_summary: dict = Field(default_factory=dict)
    issues: list[QualityIssue] = Field(default_factory=list)


class ChapterRunTrace(BaseModel):
    novel_id: str
    chapter_id: str
    run_id: str
    phase_events: list[PhaseEvent] = Field(default_factory=list)
    current_phase: str
    terminal_status: Literal["succeeded", "blocked", "failed", "cancelled", "repairing"]
    terminal_reason: str | None = None
    quality_status: str = "unchecked"
    issue_summary: dict = Field(default_factory=dict)
    repair_attempts: int = 0
    archived: bool = False
    exported: bool | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_schemas/test_quality.py -q
```

Expected: PASS, `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/schemas/quality.py tests/test_schemas/test_quality.py
git commit -m "feat: add shared quality schemas"
```

### Task 2: Convert Quality Gate Items To Standard Issues

**Files:**
- Modify: `src/novel_dev/services/quality_gate_service.py`
- Test: `tests/test_services/test_quality_gate_service.py`

- [ ] **Step 1: Add failing tests for issue conversion**

Append to `tests/test_services/test_quality_gate_service.py`:

```python
def test_quality_gate_converts_blocking_and_warning_items_to_standard_issues():
    report = FastReviewReport(
        word_count_ok=True,
        consistency_fixed=True,
        ai_flavor_reduced=False,
        beat_cohesion_ok=False,
        language_style_ok=True,
        notes=["节拍之间重复拼接", "模板化表达未降低"],
    )

    gate = QualityGateService.evaluate_fast_review(
        report,
        target_word_count=1000,
        polished_word_count=1000,
        final_review_score=72,
        polished_text="林照推门进屋。窗外雨声忽然停了。",
        acceptance_scope="real-contract",
    )

    issues = QualityGateService.to_quality_issues(gate)

    assert [issue.code for issue in issues] == ["beat_cohesion", "final_review_score", "ai_flavor"]
    assert issues[0].category == "structure"
    assert issues[0].severity == "block"
    assert issues[0].repairability == "guided"
    assert issues[1].category == "prose"
    assert issues[1].severity == "warn"
    assert issues[2].code == "ai_flavor"


def test_quality_gate_converts_required_payoff_to_plot_issue():
    report = FastReviewReport(
        word_count_ok=True,
        consistency_fixed=True,
        ai_flavor_reduced=True,
        beat_cohesion_ok=True,
        language_style_ok=True,
        notes=[],
    )

    gate = QualityGateService.evaluate_fast_review(
        report,
        target_word_count=1000,
        polished_word_count=1000,
        final_review_score=82,
        polished_text="林照离开试炼林，夜色重新安静下来。",
        required_payoffs=["林照搜查遗物发现密函"],
        acceptance_scope="real-contract",
    )

    issues = QualityGateService.to_quality_issues(gate)

    assert len(issues) == 1
    assert issues[0].code == "required_payoff"
    assert issues[0].category == "plot"
    assert issues[0].repairability == "guided"
```

Also add this import at the top:

```python
from novel_dev.schemas.quality import QualityIssue
```

The `QualityIssue` import is intentionally referenced by type in editor tooling; if linting flags it as unused, remove the import.

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_services/test_quality_gate_service.py -q
```

Expected: FAIL with `AttributeError: type object 'QualityGateService' has no attribute 'to_quality_issues'`.

- [ ] **Step 3: Implement conversion methods**

Modify `src/novel_dev/services/quality_gate_service.py`.

Add import:

```python
from novel_dev.schemas.quality import QualityIssue
```

Add methods inside `QualityGateService`:

```python
    @classmethod
    def to_quality_issues(cls, gate: QualityGateResult) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        for item in gate.blocking_items:
            issues.append(cls._gate_item_to_quality_issue(item, severity=QUALITY_BLOCK))
        for item in gate.warning_items:
            issues.append(cls._gate_item_to_quality_issue(item, severity=QUALITY_WARN))
        return issues

    @classmethod
    def _gate_item_to_quality_issue(cls, item: dict[str, Any], *, severity: str) -> QualityIssue:
        code = str(item.get("code") or "quality_gate")
        category, scope, repairability = cls._quality_issue_classification(code)
        evidence = cls._quality_issue_evidence(item)
        return QualityIssue(
            code=code,
            category=category,
            severity="block" if severity == QUALITY_BLOCK else "warn",
            scope=scope,
            repairability=repairability,
            evidence=evidence,
            suggestion=cls._quality_issue_suggestion(code),
            source="quality_gate",
        )

    @staticmethod
    def _quality_issue_classification(code: str) -> tuple[str, str, str]:
        mapping = {
            "beat_cohesion": ("structure", "beat", "guided"),
            "text_integrity": ("structure", "paragraph", "auto"),
            "word_count_drift": ("prose", "chapter", "guided"),
            "ai_flavor": ("prose", "chapter", "guided"),
            "language_style": ("style", "chapter", "guided"),
            "required_payoff": ("plot", "chapter", "guided"),
            "final_review_score": ("prose", "chapter", "guided"),
            "review_note": ("structure", "chapter", "manual"),
            "consistency": ("continuity", "chapter", "guided"),
        }
        return mapping.get(code, ("process", "chapter", "manual"))

    @staticmethod
    def _quality_issue_evidence(item: dict[str, Any]) -> list[str]:
        evidence = [str(item.get("message") or "").strip()]
        detail = item.get("detail")
        if isinstance(detail, list):
            evidence.extend(str(value).strip() for value in detail[:5] if str(value).strip())
        elif isinstance(detail, dict):
            for key, value in detail.items():
                evidence.append(f"{key}={value}")
        elif detail not in (None, "", [], {}):
            evidence.append(str(detail))
        return [value for value in evidence if value]

    @staticmethod
    def _quality_issue_suggestion(code: str) -> str:
        suggestions = {
            "beat_cohesion": "修复重复段落、时序错乱和节拍转场，让动作因果连续。",
            "text_integrity": "修复截断句、孤立标点和残缺段落，保持完整句读。",
            "word_count_drift": "压缩或补足正文，使有效冲突和目标字数接近章节计划。",
            "ai_flavor": "删除模板化表达，把心理解释改成动作、对话和具体感官。",
            "language_style": "将不符合语境的外文、现代术语或口吻改成作品内表达。",
            "required_payoff": "使用本章已出现材料补足计划要求的线索兑现或章末停点。",
            "final_review_score": "按成稿复评低分项做定点修复，不新增计划外事实。",
            "consistency": "按已建立设定、实体状态和上下文修复硬冲突。",
        }
        return suggestions.get(code, "保留原始证据，交由人工或后续流程判断。")
```

- [ ] **Step 4: Remove unused test import if needed**

If pytest passes without lint checks, no action is needed. If a local lint command flags `QualityIssue` as unused in `tests/test_services/test_quality_gate_service.py`, remove this line:

```python
from novel_dev.schemas.quality import QualityIssue
```

- [ ] **Step 5: Run tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_services/test_quality_gate_service.py tests/test_schemas/test_quality.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/services/quality_gate_service.py tests/test_services/test_quality_gate_service.py
git commit -m "feat: map quality gate items to issues"
```

### Task 3: Add Quality Issue Normalization Helpers

**Files:**
- Create: `src/novel_dev/services/quality_issue_service.py`
- Test: `tests/test_services/test_quality_issue_service.py`

- [ ] **Step 1: Write tests for critic and guard conversion**

Create `tests/test_services/test_quality_issue_service.py`:

```python
from novel_dev.services.quality_issue_service import QualityIssueService


def test_from_dimension_issue_maps_readability_to_prose():
    issues = QualityIssueService.from_dimension_issues(
        [
            {
                "dim": "readability",
                "beat_idx": 0,
                "problem": "解释性旁白过多",
                "suggestion": "改成动作呈现",
            }
        ]
    )

    assert len(issues) == 1
    assert issues[0].code == "readability"
    assert issues[0].category == "prose"
    assert issues[0].scope == "beat"
    assert issues[0].beat_index == 0
    assert issues[0].source == "critic"


def test_from_structure_guard_maps_boundary_violation():
    evidence = {
        "beat_index": 1,
        "issues": ["提前写入后续 beat 的核心事件", "新增计划外事实"],
        "suggested_rewrite_focus": "聚焦当前 beat",
    }

    issues = QualityIssueService.from_structure_guard(evidence, source="structure_guard")

    assert len(issues) == 1
    assert issues[0].code == "plan_boundary_violation"
    assert issues[0].category == "structure"
    assert issues[0].severity == "block"
    assert issues[0].beat_index == 1
    assert "提前写入后续 beat 的核心事件" in issues[0].evidence


def test_summarize_counts_by_category_code_and_repairability():
    issues = QualityIssueService.from_dimension_issues(
        [
            {"dim": "readability", "problem": "AI 腔", "suggestion": "压缩"},
            {"dim": "characterization", "problem": "配角扁平", "suggestion": "增加反应差异"},
        ]
    )

    summary = QualityIssueService.summarize(issues)

    assert summary["total"] == 2
    assert summary["by_category"]["prose"] == 1
    assert summary["by_category"]["character"] == 1
    assert summary["by_repairability"]["guided"] == 2
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_services/test_quality_issue_service.py -q
```

Expected: FAIL with missing module.

- [ ] **Step 3: Implement service**

Create `src/novel_dev/services/quality_issue_service.py`:

```python
from __future__ import annotations

from collections import Counter
from typing import Any

from novel_dev.schemas.quality import QualityIssue


class QualityIssueService:
    @classmethod
    def from_dimension_issues(cls, raw_issues: list[dict[str, Any]]) -> list[QualityIssue]:
        result: list[QualityIssue] = []
        for raw in raw_issues or []:
            if not isinstance(raw, dict):
                continue
            dim = str(raw.get("dim") or "quality").strip() or "quality"
            category = cls._category_for_dim(dim)
            beat_idx = raw.get("beat_idx")
            result.append(
                QualityIssue(
                    code=dim,
                    category=category,
                    severity="warn",
                    scope="beat" if isinstance(beat_idx, int) else "chapter",
                    beat_index=beat_idx if isinstance(beat_idx, int) else None,
                    repairability="guided",
                    evidence=[value for value in [str(raw.get("problem") or "").strip()] if value],
                    suggestion=str(raw.get("suggestion") or "").strip(),
                    source="critic",
                )
            )
        return result

    @classmethod
    def from_structure_guard(cls, evidence: dict[str, Any], *, source: str = "structure_guard") -> list[QualityIssue]:
        if not isinstance(evidence, dict):
            return []
        raw_issues = evidence.get("issues") or []
        issue_lines = [str(item).strip() for item in raw_issues if str(item).strip()]
        if not issue_lines:
            return []
        beat_index = evidence.get("beat_index")
        return [
            QualityIssue(
                code="plan_boundary_violation",
                category="structure",
                severity="block",
                scope="beat",
                beat_index=beat_index if isinstance(beat_index, int) else None,
                repairability="guided",
                evidence=issue_lines[:5],
                suggestion=str(evidence.get("suggested_rewrite_focus") or "回到当前 beat 边界内重写。"),
                source=source,  # type: ignore[arg-type]
            )
        ]

    @staticmethod
    def summarize(issues: list[QualityIssue]) -> dict[str, Any]:
        return {
            "total": len(issues),
            "by_category": dict(Counter(issue.category for issue in issues)),
            "by_code": dict(Counter(issue.code for issue in issues)),
            "by_severity": dict(Counter(issue.severity for issue in issues)),
            "by_repairability": dict(Counter(issue.repairability for issue in issues)),
        }

    @staticmethod
    def _category_for_dim(dim: str) -> str:
        mapping = {
            "readability": "prose",
            "humanity": "prose",
            "characterization": "character",
            "plot_tension": "plot",
            "hook_strength": "plot",
            "consistency": "continuity",
        }
        return mapping.get(dim, "prose")
```

- [ ] **Step 4: Run tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_services/test_quality_issue_service.py tests/test_schemas/test_quality.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/services/quality_issue_service.py tests/test_services/test_quality_issue_service.py
git commit -m "feat: normalize quality issues"
```

### Task 4: Build Beat Boundary Cards

**Files:**
- Create: `src/novel_dev/services/beat_boundary_service.py`
- Test: `tests/test_services/test_beat_boundary_service.py`

- [ ] **Step 1: Write boundary card tests**

Create `tests/test_services/test_beat_boundary_service.py`:

```python
from novel_dev.services.beat_boundary_service import BeatBoundaryService


def test_build_cards_from_chapter_plan_beats():
    chapter_plan = {
        "beats": [
            {
                "summary": "主角在雨夜发现旧信",
                "goal": "确认旧信来自父亲",
                "conflict": "有人靠近门外",
                "hook": "门外脚步停住",
            },
            {
                "summary": "主角藏起旧信并试探来人",
                "goal": "不暴露旧信",
                "conflict": "来人要求搜屋",
            },
        ]
    }

    cards = BeatBoundaryService.build_cards(chapter_plan)

    assert len(cards) == 2
    assert cards[0].beat_index == 0
    assert "主角在雨夜发现旧信" in cards[0].must_cover
    assert any("后续 beat" in item for item in cards[0].forbidden_materials)
    assert "门外脚步停住" in cards[0].ending_policy


def test_build_cards_handles_string_beats():
    cards = BeatBoundaryService.build_cards({"beats": ["发现旧信", "藏起旧信"]})

    assert len(cards) == 2
    assert cards[0].must_cover == ["发现旧信"]
    assert cards[0].reveal_boundary
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_services/test_beat_boundary_service.py -q
```

Expected: FAIL with missing module.

- [ ] **Step 3: Implement service**

Create `src/novel_dev/services/beat_boundary_service.py`:

```python
from __future__ import annotations

from typing import Any

from novel_dev.schemas.quality import BeatBoundaryCard


class BeatBoundaryService:
    @classmethod
    def build_cards(cls, chapter_plan: dict[str, Any]) -> list[BeatBoundaryCard]:
        beats = chapter_plan.get("beats") if isinstance(chapter_plan, dict) else []
        if not isinstance(beats, list):
            return []
        cards: list[BeatBoundaryCard] = []
        for idx, beat in enumerate(beats):
            summary = cls._beat_text(beat, "summary") or cls._beat_text(beat, "content") or cls._coerce_text(beat)
            goal = cls._beat_text(beat, "goal")
            conflict = cls._beat_text(beat, "conflict")
            hook = cls._beat_text(beat, "hook") or cls._beat_text(beat, "ending_hook")
            must_cover = [value for value in [summary, goal, conflict] if value]
            cards.append(
                BeatBoundaryCard(
                    beat_index=idx,
                    must_cover=must_cover,
                    allowed_materials=cls._allowed_materials(chapter_plan, beat),
                    forbidden_materials=[
                        "不得提前执行后续 beat 的核心事件",
                        "不得新增章节计划外人物、物件、证据、威胁实体或背景因果",
                        "不得改变当前 beat 已定义的信息释放顺序",
                    ],
                    reveal_boundary="只释放当前 beat 已规划的信息；风险感必须来自已有目标、阻力、物件或伏笔。",
                    ending_policy=hook or "停在当前 beat 的动作余波、未完成选择或已有风险逼近感。",
                )
            )
        return cards

    @classmethod
    def _allowed_materials(cls, chapter_plan: dict[str, Any], beat: Any) -> list[str]:
        materials: list[str] = []
        for key in ("characters", "entities", "locations", "props", "foreshadowings"):
            value = chapter_plan.get(key)
            if isinstance(value, list):
                materials.extend(cls._coerce_text(item) for item in value)
        if isinstance(beat, dict):
            for key in ("characters", "entities", "locations", "props", "foreshadowings"):
                value = beat.get(key)
                if isinstance(value, list):
                    materials.extend(cls._coerce_text(item) for item in value)
        return [item for item in dict.fromkeys(materials) if item]

    @staticmethod
    def _beat_text(beat: Any, key: str) -> str:
        if isinstance(beat, dict):
            return BeatBoundaryService._coerce_text(beat.get(key))
        return ""

    @staticmethod
    def _coerce_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, dict):
            for key in ("name", "title", "summary", "content"):
                text = str(value.get(key) or "").strip()
                if text:
                    return text
            return ""
        return str(value).strip()
```

- [ ] **Step 4: Run tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_services/test_beat_boundary_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/services/beat_boundary_service.py tests/test_services/test_beat_boundary_service.py
git commit -m "feat: build beat boundary cards"
```

### Task 5: Persist Boundary Cards In Chapter Context And Writer Prompt

**Files:**
- Modify: `src/novel_dev/agents/context_agent.py`
- Modify: `src/novel_dev/agents/writer_agent.py`
- Test: `tests/test_agents/test_context_agent_chapters.py`
- Test: `tests/test_agents/test_writer_agent.py`

- [ ] **Step 1: Add context test for boundary cards**

In `tests/test_agents/test_context_agent_chapters.py`, add a test near existing chapter context assertions:

```python
async def test_context_agent_adds_beat_boundary_cards(async_session):
    novel_id = "novel-boundary-context"
    chapter_id = "ch-boundary-1"
    state_repo = NovelStateRepository(async_session)
    await state_repo.save_checkpoint(
        novel_id,
        "context_preparation",
        checkpoint_data={
            "current_chapter_plan": {
                "chapter_id": chapter_id,
                "title": "雨夜旧信",
                "beats": [{"summary": "主角发现旧信", "hook": "门外脚步停住"}],
            }
        },
        current_volume_id="vol-1",
        current_chapter_id=chapter_id,
    )

    context = await ContextAgent(async_session).assemble(novel_id, chapter_id)

    assert context.chapter_plan["beat_boundary_cards"][0]["beat_index"] == 0
    assert "主角发现旧信" in context.chapter_plan["beat_boundary_cards"][0]["must_cover"]
```

If the local `NovelStateRepository` helper has a different method name, use the setup pattern already present in the file. Keep the assertion unchanged.

- [ ] **Step 2: Add writer prompt test**

In `tests/test_agents/test_writer_agent.py`, add:

```python
def test_writer_prompt_includes_beat_boundary_cards():
    context = {
        "chapter_plan": {
            "title": "雨夜旧信",
            "beats": [{"summary": "主角发现旧信"}],
            "beat_boundary_cards": [
                {
                    "beat_index": 0,
                    "must_cover": ["主角发现旧信"],
                    "allowed_materials": ["旧信", "雨夜"],
                    "forbidden_materials": ["不得提前执行后续 beat 的核心事件"],
                    "reveal_boundary": "只释放当前 beat 信息",
                    "ending_policy": "停在门外脚步",
                }
            ],
        }
    }

    prompt = WriterAgent._build_beat_boundary_prompt(context["chapter_plan"], 0)

    assert "主角发现旧信" in prompt
    assert "不得提前执行后续 beat 的核心事件" in prompt
    assert "只释放当前 beat 信息" in prompt
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_writer_agent.py::test_writer_prompt_includes_beat_boundary_cards -q
```

Expected: FAIL with missing `_build_beat_boundary_prompt`.

- [ ] **Step 4: Implement context boundary card injection**

Modify `src/novel_dev/agents/context_agent.py` where `chapter_context` or `chapter_plan` is assembled. Add:

```python
from novel_dev.services.beat_boundary_service import BeatBoundaryService
```

Immediately after resolving `chapter_plan` and before persisting context:

```python
chapter_plan = dict(chapter_plan or {})
if "beat_boundary_cards" not in chapter_plan:
    chapter_plan["beat_boundary_cards"] = [
        card.model_dump() for card in BeatBoundaryService.build_cards(chapter_plan)
    ]
```

Then ensure the context uses this mutated `chapter_plan`.

- [ ] **Step 5: Implement writer prompt helper**

Modify `src/novel_dev/agents/writer_agent.py`:

```python
    @staticmethod
    def _build_beat_boundary_prompt(chapter_plan: dict, beat_index: int) -> str:
        cards = chapter_plan.get("beat_boundary_cards") or []
        card = next(
            (
                item
                for item in cards
                if isinstance(item, dict) and item.get("beat_index") == beat_index
            ),
            None,
        )
        if not card:
            return ""
        lines = ["### 当前节拍边界卡"]
        for label, key in (
            ("必须覆盖", "must_cover"),
            ("允许材料", "allowed_materials"),
            ("禁止材料", "forbidden_materials"),
        ):
            values = card.get(key) or []
            if values:
                lines.append(f"{label}:")
                lines.extend(f"- {value}" for value in values)
        if card.get("reveal_boundary"):
            lines.append(f"信息释放边界: {card['reveal_boundary']}")
        if card.get("ending_policy"):
            lines.append(f"停点策略: {card['ending_policy']}")
        return "\n".join(lines)
```

In the beat-writing prompt assembly, append:

```python
boundary_prompt = self._build_beat_boundary_prompt(chapter_plan, beat_index)
if boundary_prompt:
    prompt_parts.append(boundary_prompt)
```

Use the local variable names already present in `writer_agent.py`; if the method uses `idx` instead of `beat_index`, pass `idx`.

- [ ] **Step 6: Run focused tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_writer_agent.py::test_writer_prompt_includes_beat_boundary_cards tests/test_services/test_beat_boundary_service.py -q
```

Expected: PASS.

- [ ] **Step 7: Run context test**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_context_agent_chapters.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/novel_dev/agents/context_agent.py src/novel_dev/agents/writer_agent.py tests/test_agents/test_context_agent_chapters.py tests/test_agents/test_writer_agent.py
git commit -m "feat: pass beat boundary cards to writer"
```

### Task 6: Add Repair Planner

**Files:**
- Create: `src/novel_dev/services/repair_planner_service.py`
- Test: `tests/test_services/test_repair_planner_service.py`

- [ ] **Step 1: Write planner tests**

Create `tests/test_services/test_repair_planner_service.py`:

```python
from novel_dev.schemas.quality import QualityIssue
from novel_dev.services.repair_planner_service import RepairPlanner


def issue(code, category="structure", severity="block", scope="beat", beat_index=0):
    return QualityIssue(
        code=code,
        category=category,
        severity=severity,
        scope=scope,
        beat_index=beat_index,
        repairability="guided",
        evidence=[f"{code} evidence"],
        suggestion=f"{code} suggestion",
        source="quality_gate",
    )


def test_planner_maps_beat_cohesion_to_cohesion_repair():
    tasks = RepairPlanner.plan("ch-1", [issue("beat_cohesion")])

    assert len(tasks) == 1
    assert tasks[0].task_type == "cohesion_repair"
    assert tasks[0].beat_index == 0
    assert "beat_cohesion" in tasks[0].issue_codes
    assert any("重复" in item or "转场" in item for item in tasks[0].success_criteria)


def test_planner_groups_ai_flavor_as_prose_polish():
    tasks = RepairPlanner.plan(
        "ch-1",
        [issue("ai_flavor", category="prose", severity="warn", scope="chapter", beat_index=None)],
    )

    assert len(tasks) == 1
    assert tasks[0].task_type == "prose_polish"
    assert tasks[0].scope == "chapter"


def test_planner_skips_non_repairable_issue():
    non_repairable = QualityIssue(
        code="provider_timeout",
        category="process",
        severity="block",
        scope="flow",
        repairability="manual",
        evidence=["provider timeout"],
        source="testing",
    )

    assert RepairPlanner.plan("ch-1", [non_repairable]) == []
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_services/test_repair_planner_service.py -q
```

Expected: FAIL with missing module.

- [ ] **Step 3: Implement planner**

Create `src/novel_dev/services/repair_planner_service.py`:

```python
from __future__ import annotations

import uuid
from collections import defaultdict

from novel_dev.schemas.quality import QualityIssue, RepairTask


class RepairPlanner:
    @classmethod
    def plan(cls, chapter_id: str, issues: list[QualityIssue]) -> list[RepairTask]:
        grouped: dict[tuple[str, str, int | None], list[QualityIssue]] = defaultdict(list)
        for issue in issues:
            task_type = cls._task_type_for_issue(issue)
            if task_type is None:
                continue
            grouped[(task_type, issue.scope, issue.beat_index)].append(issue)
        return [
            cls._build_task(chapter_id, task_type, scope, beat_index, grouped_issues)
            for (task_type, scope, beat_index), grouped_issues in grouped.items()
        ]

    @staticmethod
    def _task_type_for_issue(issue: QualityIssue) -> str | None:
        if issue.repairability not in {"auto", "guided"}:
            return None
        mapping = {
            "beat_cohesion": "cohesion_repair",
            "plan_boundary_violation": "cohesion_repair",
            "text_integrity": "integrity_repair",
            "ai_flavor": "prose_polish",
            "language_style": "prose_polish",
            "word_count_drift": "prose_polish",
            "required_payoff": "hook_repair",
            "hook_strength": "hook_repair",
            "characterization": "character_repair",
            "continuity_audit": "continuity_repair",
            "consistency": "continuity_repair",
        }
        return mapping.get(issue.code)

    @classmethod
    def _build_task(
        cls,
        chapter_id: str,
        task_type: str,
        scope: str,
        beat_index: int | None,
        issues: list[QualityIssue],
    ) -> RepairTask:
        return RepairTask(
            task_id=f"repair_{uuid.uuid4().hex[:12]}",
            chapter_id=chapter_id,
            issue_codes=[issue.code for issue in issues],
            task_type=task_type,  # type: ignore[arg-type]
            scope="beat" if beat_index is not None else "chapter",
            beat_index=beat_index,
            constraints=cls._constraints_for_task(task_type),
            success_criteria=cls._success_criteria_for_task(task_type),
        )

    @staticmethod
    def _constraints_for_task(task_type: str) -> list[str]:
        common = ["不得新增章节计划外人物、物件、证据、威胁实体或背景因果。"]
        by_type = {
            "cohesion_repair": ["只调整重复、转场、时序和动作因果。"],
            "integrity_repair": ["只修复截断句、孤立标点和残缺段落。"],
            "prose_polish": ["只压缩表达、替换模板化心理说明和重复比喻。"],
            "hook_repair": ["只使用本章已出现材料强化章末停点。"],
            "character_repair": ["只增加动作、语气、反应差异，不新增背景设定。"],
            "continuity_repair": ["按既有实体状态、时间线和设定修复硬冲突。"],
        }
        return by_type.get(task_type, []) + common

    @staticmethod
    def _success_criteria_for_task(task_type: str) -> list[str]:
        return {
            "cohesion_repair": ["无跨 beat 重复段", "转场因果清楚", "事件顺序不变"],
            "integrity_repair": ["句读完整", "无孤立标点段落", "无明显截断"],
            "prose_polish": ["AI 腔密度下降", "有效冲突不被删减", "句群更紧凑"],
            "hook_repair": ["兑现计划停点", "不新增计划外事实", "形成未完成动作或已知风险逼近"],
            "character_repair": ["角色态度可区分", "行为标记更具体", "人物功能不变"],
            "continuity_repair": ["符合既有设定", "符合实体状态", "不破坏时间线"],
        }.get(task_type, ["问题证据消失"])
```

- [ ] **Step 4: Run tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_services/test_repair_planner_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/services/repair_planner_service.py tests/test_services/test_repair_planner_service.py
git commit -m "feat: plan typed quality repairs"
```

### Task 7: Store Quality Issues And Repair Tasks From Fast Review

**Files:**
- Modify: `src/novel_dev/agents/fast_review_agent.py`
- Test: `tests/test_agents/test_fast_review_agent.py`

- [ ] **Step 1: Add test for repair task checkpoint**

In `tests/test_agents/test_fast_review_agent.py`, add a focused test near existing quality gate repair tests:

```python
async def test_fast_review_stores_standard_issues_and_repair_tasks_for_block(async_session, monkeypatch):
    novel_id = "novel-quality-repair"
    chapter_id = "ch-quality-repair"
    state_repo = NovelStateRepository(async_session)
    chapter_repo = ChapterRepository(async_session)
    await state_repo.save_checkpoint(
        novel_id,
        "fast_reviewing",
        checkpoint_data={
            "acceptance_scope": "real-contract",
            "edit_attempt_count": 2,
            "chapter_context": {
                "chapter_plan": {
                    "target_word_count": 1000,
                    "writing_cards": [],
                }
            },
        },
        current_volume_id="vol-quality",
        current_chapter_id=chapter_id,
    )
    await chapter_repo.create(
        novel_id=novel_id,
        volume_id="vol-quality",
        chapter_id=chapter_id,
        chapter_number=1,
        title="质量修复",
    )
    await chapter_repo.update_text(chapter_id, raw_draft="第一段。", polished_text="第一段。\n\n第一段。")
    await async_session.commit()

    async def fake_llm_check(self, polished, raw, chapter_context, novel_id=""):
        return FastReviewLLMCheck(
            consistency_fixed=True,
            beat_cohesion_ok=False,
            notes=["BEAT1 与 BEAT2 重复"],
        )

    async def fake_score(self, **kwargs):
        return 82, {"summary_feedback": "结构重复", "per_dim_issues": []}

    monkeypatch.setattr(FastReviewAgent, "_safe_llm_check_consistency_and_cohesion", fake_llm_check)
    monkeypatch.setattr(FastReviewAgent, "_score_final_text", fake_score)

    await FastReviewAgent(async_session).review(novel_id, chapter_id)

    state = await NovelStateRepository(async_session).get_state("novel-quality-repair")

    assert state.current_phase == "editing"
    checkpoint = state.checkpoint_data
    assert checkpoint["quality_issues"][0]["code"] == "beat_cohesion"
    assert checkpoint["quality_issue_summary"]["by_code"]["beat_cohesion"] == 1
    assert checkpoint["repair_tasks"][0]["task_type"] == "cohesion_repair"
```

- [ ] **Step 2: Run nearest existing quality repair test**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_fast_review_agent.py::test_fast_review_returns_to_editing_for_recoverable_quality_gate_block -q
```

Expected: PASS before changes. This confirms the local baseline.

- [ ] **Step 3: Implement issue and task storage**

Modify `src/novel_dev/agents/fast_review_agent.py`.

Add imports:

```python
from novel_dev.services.quality_issue_service import QualityIssueService
from novel_dev.services.repair_planner_service import RepairPlanner
```

After `gate = _apply_continuity_audit_to_gate(gate, continuity_audit)`, add:

```python
quality_issues = QualityGateService.to_quality_issues(gate)
quality_issues.extend(
    QualityIssueService.from_structure_guard(
        checkpoint.get("chapter_structure_guard") or {},
        source="structure_guard",
    )
)
checkpoint["quality_issues"] = [issue.model_dump() for issue in quality_issues]
checkpoint["quality_issue_summary"] = QualityIssueService.summarize(quality_issues)
```

Inside the `if gate.status == QUALITY_BLOCK:` branch, before saving checkpoint for a repairable block, add:

```python
repair_tasks = RepairPlanner.plan(chapter_id, quality_issues)
if repair_tasks:
    checkpoint["repair_tasks"] = [task.model_dump() for task in repair_tasks]
```

Do not remove `final_polish_issues`; it remains compatibility input for `EditorAgent`.

- [ ] **Step 4: Run focused tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_fast_review_agent.py::test_fast_review_returns_to_editing_for_recoverable_quality_gate_block tests/test_services/test_repair_planner_service.py tests/test_services/test_quality_issue_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Run the new checkpoint test**

Run the specific test name added in Step 1:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_fast_review_agent.py::test_fast_review_stores_standard_issues_and_repair_tasks_for_block -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/agents/fast_review_agent.py tests/test_agents/test_fast_review_agent.py
git commit -m "feat: store quality issues and repair tasks"
```

### Task 8: Add Editor Repair Task Execution

**Files:**
- Modify: `src/novel_dev/agents/editor_agent.py`
- Test: `tests/test_agents/test_editor_agent.py`

- [ ] **Step 1: Add unit tests for repair prompt routing**

In `tests/test_agents/test_editor_agent.py`, add:

```python
def test_editor_formats_cohesion_repair_task_prompt():
    task = {
        "task_type": "cohesion_repair",
        "issue_codes": ["beat_cohesion"],
        "constraints": ["只调整重复、转场、时序和动作因果。"],
        "success_criteria": ["无跨 beat 重复段", "转场因果清楚"],
    }

    prompt = EditorAgent._build_repair_task_prompt(
        source_text="林照推门。\n\n林照推门。",
        task=task,
        chapter_context={"chapter_plan": {"title": "雨夜旧信"}},
    )

    assert "cohesion_repair" in prompt
    assert "只调整重复、转场、时序和动作因果" in prompt
    assert "无跨 beat 重复段" in prompt
    assert "不得新增章节计划外" in prompt


def test_editor_selects_repair_tasks_for_beat():
    tasks = [
        {"task_type": "cohesion_repair", "beat_index": 1, "issue_codes": ["beat_cohesion"]},
        {"task_type": "prose_polish", "beat_index": None, "issue_codes": ["ai_flavor"]},
    ]

    selected = EditorAgent._repair_tasks_for_beat(tasks, 1)

    assert [task["task_type"] for task in selected] == ["cohesion_repair", "prose_polish"]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_editor_agent.py::test_editor_formats_cohesion_repair_task_prompt tests/test_agents/test_editor_agent.py::test_editor_selects_repair_tasks_for_beat -q
```

Expected: FAIL with missing helper methods.

- [ ] **Step 3: Add editor helper methods**

Modify `src/novel_dev/agents/editor_agent.py`:

```python
    @staticmethod
    def _repair_tasks_for_beat(tasks: list[dict], beat_index: int) -> list[dict]:
        selected = []
        for task in tasks or []:
            if not isinstance(task, dict):
                continue
            task_beat = task.get("beat_index")
            if task_beat is None or task_beat == beat_index:
                selected.append(task)
        return selected

    @staticmethod
    def _build_repair_task_prompt(source_text: str, task: dict, chapter_context: dict) -> str:
        constraints = "\n".join(f"- {item}" for item in task.get("constraints") or [])
        success = "\n".join(f"- {item}" for item in task.get("success_criteria") or [])
        chapter_plan = chapter_context.get("chapter_plan", {}) if isinstance(chapter_context, dict) else {}
        title = chapter_plan.get("title") or chapter_plan.get("chapter_title") or ""
        return (
            "你是一位小说编辑。请执行指定修复任务，只返回修复后的正文。\n\n"
            f"### 章节\n{title}\n\n"
            f"### 修复任务\n{task.get('task_type')}\n\n"
            f"### 问题代码\n{', '.join(str(code) for code in task.get('issue_codes') or [])}\n\n"
            "### 约束\n"
            f"{constraints}\n"
            "- 不得新增章节计划外人物、物件、证据、威胁实体或背景因果。\n\n"
            "### 成功标准\n"
            f"{success}\n\n"
            f"### 原文\n{source_text}\n\n"
            "修复后正文:"
        )
```

- [ ] **Step 4: Route repair tasks before generic rewrite**

In both `polish()` and `polish_standalone()`, after `chapter_context` and `beats` are available, read:

```python
repair_tasks = checkpoint.get("repair_tasks") or []
```

Inside the beat loop, before computing `needs_rewrite`, add:

```python
beat_repair_tasks = self._repair_tasks_for_beat(repair_tasks, idx)
if beat_repair_tasks:
    all_issues = all_issues + [
        {
            "dim": task.get("task_type") or "repair_task",
            "problem": "质量修复任务：" + "、".join(str(code) for code in task.get("issue_codes") or []),
            "suggestion": "；".join(str(item) for item in task.get("success_criteria") or []),
        }
        for task in beat_repair_tasks
    ]
```

For the first implementation, keep using `_rewrite_beat()` after injecting task issues. Do not add a separate LLM call yet; the prompt routing helpers are groundwork and the behavior remains compatible.

- [ ] **Step 5: Record repair history**

After each rewritten beat is accepted or reverted, append:

```python
if beat_repair_tasks:
    checkpoint.setdefault("repair_history", []).append({
        "beat_index": idx,
        "task_types": [task.get("task_type") for task in beat_repair_tasks],
        "issue_codes": [
            code
            for task in beat_repair_tasks
            for code in (task.get("issue_codes") or [])
        ],
        "source_chars": len(beat_text),
        "polished_chars": len(polished),
    })
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_editor_agent.py::test_editor_formats_cohesion_repair_task_prompt tests/test_agents/test_editor_agent.py::test_editor_selects_repair_tasks_for_beat -q
```

Expected: PASS.

- [ ] **Step 7: Run editor suite**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_editor_agent.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/novel_dev/agents/editor_agent.py tests/test_agents/test_editor_agent.py
git commit -m "feat: route editor repair tasks"
```

### Task 9: Add Chapter Run Trace Helpers

**Files:**
- Create: `src/novel_dev/services/chapter_run_trace_service.py`
- Test: `tests/test_services/test_chapter_run_trace_service.py`

- [ ] **Step 1: Write trace helper tests**

Create `tests/test_services/test_chapter_run_trace_service.py`:

```python
from novel_dev.schemas.quality import QualityIssue
from novel_dev.services.chapter_run_trace_service import ChapterRunTraceService


def test_start_trace_creates_started_event():
    trace = ChapterRunTraceService.start_trace(
        novel_id="novel-a",
        chapter_id="ch-1",
        run_id="run-1",
        phase="drafting",
    )

    assert trace.current_phase == "drafting"
    assert trace.terminal_status == "repairing"
    assert trace.phase_events[0].phase == "drafting"
    assert trace.phase_events[0].status == "started"


def test_mark_blocked_adds_issue_summary():
    trace = ChapterRunTraceService.start_trace("novel-a", "ch-1", "run-1", "fast_reviewing")
    issue = QualityIssue(
        code="beat_cohesion",
        category="structure",
        severity="block",
        scope="beat",
        repairability="guided",
        source="quality_gate",
    )

    updated = ChapterRunTraceService.mark_blocked(trace, phase="fast_reviewing", issues=[issue], reason="quality_blocked")

    assert updated.terminal_status == "blocked"
    assert updated.terminal_reason == "quality_blocked"
    assert updated.issue_summary["by_code"]["beat_cohesion"] == 1
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_services/test_chapter_run_trace_service.py -q
```

Expected: FAIL with missing module.

- [ ] **Step 3: Implement trace helper**

Create `src/novel_dev/services/chapter_run_trace_service.py`:

```python
from __future__ import annotations

from datetime import datetime

from novel_dev.schemas.quality import ChapterRunTrace, PhaseEvent, QualityIssue
from novel_dev.services.quality_issue_service import QualityIssueService


class ChapterRunTraceService:
    @classmethod
    def start_trace(cls, novel_id: str, chapter_id: str, run_id: str, phase: str) -> ChapterRunTrace:
        return ChapterRunTrace(
            novel_id=novel_id,
            chapter_id=chapter_id,
            run_id=run_id,
            current_phase=phase,
            terminal_status="repairing",
            phase_events=[
                PhaseEvent(
                    phase=phase,
                    status="started",
                    started_at=cls._now(),
                )
            ],
        )

    @classmethod
    def append_event(
        cls,
        trace: ChapterRunTrace,
        *,
        phase: str,
        status: str,
        issues: list[QualityIssue] | None = None,
        input_summary: dict | None = None,
        output_summary: dict | None = None,
    ) -> ChapterRunTrace:
        trace.phase_events.append(
            PhaseEvent(
                phase=phase,
                status=status,  # type: ignore[arg-type]
                started_at=cls._now(),
                ended_at=cls._now(),
                input_summary=input_summary or {},
                output_summary=output_summary or {},
                issues=issues or [],
            )
        )
        trace.current_phase = phase
        return trace

    @classmethod
    def mark_blocked(
        cls,
        trace: ChapterRunTrace,
        *,
        phase: str,
        issues: list[QualityIssue],
        reason: str,
    ) -> ChapterRunTrace:
        cls.append_event(trace, phase=phase, status="blocked", issues=issues)
        trace.terminal_status = "blocked"
        trace.terminal_reason = reason
        trace.quality_status = "block"
        trace.issue_summary = QualityIssueService.summarize(issues)
        return trace

    @staticmethod
    def _now() -> str:
        return datetime.utcnow().isoformat() + "Z"
```

- [ ] **Step 4: Run tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_services/test_chapter_run_trace_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/services/chapter_run_trace_service.py tests/test_services/test_chapter_run_trace_service.py
git commit -m "feat: add chapter run trace helpers"
```

### Task 10: Integrate Run Trace With Auto Chapter Generation

**Files:**
- Modify: `src/novel_dev/services/chapter_generation_service.py`
- Test: `tests/test_api/test_auto_chapter_generation_routes.py`

- [ ] **Step 1: Add assertion to existing quality-block auto-run test**

Add a new test to `tests/test_api/test_auto_chapter_generation_routes.py`:

```python
@pytest.mark.asyncio
async def test_auto_run_records_trace_for_quality_block(async_session, monkeypatch):
    plan = build_test_volume("vol_quality_block", "ch_quality_block", count=1)
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_auto_quality_block",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={
            "current_volume_plan": plan.model_dump(),
            "current_chapter_plan": plan.chapters[0].model_dump(),
            "quality_issues": [
                {
                    "code": "beat_cohesion",
                    "category": "structure",
                    "severity": "block",
                    "scope": "beat",
                    "repairability": "guided",
                    "source": "quality_gate",
                }
            ],
        },
        volume_id="vol_quality_block",
        chapter_id="ch_quality_block_1",
    )
    await ChapterRepository(async_session).ensure_from_plan(
        "n_auto_quality_block",
        "vol_quality_block",
        plan.chapters[0],
    )
    chapter = await ChapterRepository(async_session).get_by_id("ch_quality_block_1")
    chapter.quality_status = "block"
    chapter.quality_reasons = {
        "status": "block",
        "blocking_items": [{"code": "beat_cohesion", "message": "连贯性不足"}],
    }
    await async_session.commit()

    service = ChapterGenerationService(async_session)
    result = await service.auto_run("n_auto_quality_block", max_chapters=1)

    assert result.stopped_reason == "quality_blocked"
    state = await director.resume("n_auto_quality_block")
    trace = state.checkpoint_data["chapter_run_trace"]
    assert trace["chapter_id"] == "ch_quality_block_1"
    assert trace["terminal_status"] == "blocked"
    assert trace["terminal_reason"] == "quality_blocked"
    assert trace["issue_summary"]["by_code"]["beat_cohesion"] == 1
```

- [ ] **Step 2: Run focused test to verify failure**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_api/test_auto_chapter_generation_routes.py::test_auto_run_records_trace_for_quality_block -q
```

Expected: FAIL with missing `chapter_run_trace`.

- [ ] **Step 3: Write trace at quality block**

Modify `src/novel_dev/services/chapter_generation_service.py`.

Add imports:

```python
from novel_dev.schemas.quality import QualityIssue
from novel_dev.services.chapter_run_trace_service import ChapterRunTraceService
from novel_dev.services.quality_issue_service import QualityIssueService
```

In the `except QualityGateBlockedError as exc:` branch, before `_release_lock`, add:

```python
if state is not None:
    checkpoint = dict(state.checkpoint_data or {})
    raw_issues = checkpoint.get("quality_issues") or []
    quality_issues = [
        QualityIssue.model_validate(item)
        for item in raw_issues
        if isinstance(item, dict)
    ]
    trace = ChapterRunTraceService.start_trace(
        novel_id=novel_id,
        chapter_id=exc.chapter_id,
        run_id=token,
        phase=state.current_phase,
    )
    trace = ChapterRunTraceService.mark_blocked(
        trace,
        phase=state.current_phase,
        issues=quality_issues,
        reason="quality_blocked",
    )
    checkpoint["chapter_run_trace"] = trace.model_dump()
    checkpoint["quality_issue_summary"] = QualityIssueService.summarize(quality_issues)
    state = await self.director.save_checkpoint(
        novel_id,
        Phase(state.current_phase),
        checkpoint,
        volume_id=state.current_volume_id,
        chapter_id=state.current_chapter_id,
    )
    await self.session.commit()
```

- [ ] **Step 4: Run focused test**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_api/test_auto_chapter_generation_routes.py::test_auto_run_records_trace_for_quality_block -q
```

Expected: PASS.

- [ ] **Step 5: Run auto chapter route tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_api/test_auto_chapter_generation_routes.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/services/chapter_generation_service.py tests/test_api/test_auto_chapter_generation_routes.py
git commit -m "feat: record auto-run quality blocks"
```

### Task 11: Improve Generation Contracts And Export Diagnosis

**Files:**
- Modify: `src/novel_dev/testing/generation_contracts.py`
- Test: `tests/test_testing/test_generation_contracts.py`

- [ ] **Step 1: Add tests for chapter counts and export classification**

Append to `tests/test_testing/test_generation_contracts.py`:

```python
from novel_dev.testing.generation_contracts import classify_export_result, summarize_chapter_counts


def test_summarize_chapter_counts_separates_generated_archived_blocked_pending():
    chapters = [
        {"chapter_id": "ch-1", "status": "archived", "polished_text": "正文", "quality_status": "pass"},
        {"chapter_id": "ch-2", "status": "edited", "polished_text": "正文", "quality_status": "block"},
        {"chapter_id": "ch-3", "status": "pending", "polished_text": "", "quality_status": "unchecked"},
    ]

    counts = summarize_chapter_counts(chapters)

    assert counts["planned"] == 3
    assert counts["generated_text"] == 2
    assert counts["archived"] == 1
    assert counts["blocked"] == 1
    assert counts["pending"] == 1


def test_classify_export_result_distinguishes_missing_reasons():
    assert classify_export_result({}, archived_chapter_count=0) == "no_archived_chapters"
    assert classify_export_result({}, archived_chapter_count=2) == "export_not_requested"
    assert classify_export_result({"exported_path": ""}, archived_chapter_count=2) == "export_failed"
    assert classify_export_result({"exported_path": "/tmp/out.md"}, archived_chapter_count=2) == "export_succeeded"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_generation_contracts.py::test_summarize_chapter_counts_separates_generated_archived_blocked_pending tests/test_testing/test_generation_contracts.py::test_classify_export_result_distinguishes_missing_reasons -q
```

Expected: FAIL with missing functions.

- [ ] **Step 3: Implement helpers**

Modify `src/novel_dev/testing/generation_contracts.py`:

```python
def summarize_chapter_counts(chapters: list[dict[str, Any]]) -> dict[str, int]:
    planned = len(chapters or [])
    generated_text = 0
    archived = 0
    blocked = 0
    pending = 0
    for chapter in chapters or []:
        if not isinstance(chapter, dict):
            continue
        text_status = detect_chapter_text(_ChapterDictAdapter(chapter))
        if text_status.has_text:
            generated_text += 1
        if chapter.get("status") == "archived":
            archived += 1
        if chapter.get("quality_status") == "block":
            blocked += 1
        if chapter.get("status") == "pending":
            pending += 1
    return {
        "planned": planned,
        "generated_text": generated_text,
        "archived": archived,
        "blocked": blocked,
        "pending": pending,
    }


def classify_export_result(response: dict[str, Any], *, archived_chapter_count: int) -> str:
    if archived_chapter_count <= 0:
        return "no_archived_chapters"
    if "exported_path" not in response:
        return "export_not_requested"
    if not _normalize_text(response.get("exported_path")):
        return "export_failed"
    return "export_succeeded"


class _ChapterDictAdapter:
    def __init__(self, data: dict[str, Any]):
        self.raw_draft = data.get("raw_draft")
        self.polished_text = data.get("polished_text")
```

- [ ] **Step 4: Run contract tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_generation_contracts.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/testing/generation_contracts.py tests/test_testing/test_generation_contracts.py
git commit -m "feat: classify generation contract status"
```

### Task 12: Aggregate Quality Issues In Summary Reports

**Files:**
- Modify: `src/novel_dev/testing/quality_summary.py`
- Test: `tests/test_testing/test_quality_summary.py`

- [ ] **Step 1: Add quality issue aggregation test**

Append to `tests/test_testing/test_quality_summary.py`:

```python
def test_quality_summary_aggregates_standard_quality_issues():
    report = build_quality_summary_report(
        {
            "novel_id": "novel-issues",
            "checkpoint": {
                "setting_quality_report": {"passed": True},
                "synopsis_data": {"review_status": {"synopsis_quality_report": {"passed": True}}},
                "current_volume_plan": {
                    "review_status": {"writability_status": {"passed": True, "failed_chapter_numbers": []}}
                },
                "quality_issues": [
                    {
                        "code": "beat_cohesion",
                        "category": "structure",
                        "severity": "block",
                        "scope": "beat",
                        "repairability": "guided",
                        "source": "quality_gate",
                    },
                    {
                        "code": "ai_flavor",
                        "category": "prose",
                        "severity": "warn",
                        "scope": "chapter",
                        "repairability": "guided",
                        "source": "quality_gate",
                    },
                ],
            },
            "chapters": [{"chapter_id": "ch_1", "quality_status": "block", "final_review_score": 72}],
        },
        run_id="quality-issues",
    )

    assert report.artifacts["quality_issue_total"] == "2"
    assert report.artifacts["quality_issue_by_category"] == "prose=1,structure=1"
    assert report.artifacts["quality_issue_by_code"] == "ai_flavor=1,beat_cohesion=1"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_quality_summary.py::test_quality_summary_aggregates_standard_quality_issues -q
```

Expected: FAIL with missing artifact keys.

- [ ] **Step 3: Implement aggregation**

Modify `src/novel_dev/testing/quality_summary.py`.

Add imports:

```python
from novel_dev.schemas.quality import QualityIssue
from novel_dev.services.quality_issue_service import QualityIssueService
```

In `build_quality_summary_report`, after artifacts are initialized and checkpoint is available, add:

```python
raw_quality_issues = checkpoint.get("quality_issues") or []
quality_issues = [
    QualityIssue.model_validate(item)
    for item in raw_quality_issues
    if isinstance(item, dict)
]
if quality_issues:
    summary = QualityIssueService.summarize(quality_issues)
    artifacts["quality_issue_total"] = str(summary["total"])
    artifacts["quality_issue_by_category"] = _format_counter_artifact(summary["by_category"])
    artifacts["quality_issue_by_code"] = _format_counter_artifact(summary["by_code"])
    artifacts["quality_issue_by_severity"] = _format_counter_artifact(summary["by_severity"])
    artifacts["quality_issue_by_repairability"] = _format_counter_artifact(summary["by_repairability"])
```

Add helper near other formatting helpers:

```python
def _format_counter_artifact(values: dict) -> str:
    return ",".join(f"{key}={values[key]}" for key in sorted(values))
```

- [ ] **Step 4: Run summary tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_quality_summary.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/testing/quality_summary.py tests/test_testing/test_quality_summary.py
git commit -m "feat: report quality issue aggregates"
```

### Task 13: Add Golden Quality Fixtures

**Files:**
- Create: `tests/generation/fixtures/quality/repeated_beat.json`
- Create: `tests/generation/fixtures/quality/ai_flavor.json`
- Create: `tests/generation/fixtures/quality/weak_hook.json`
- Create: `tests/generation/fixtures/quality/text_integrity.json`
- Test: `tests/test_testing/test_quality_fixtures.py`

- [ ] **Step 1: Add fixture tests**

Create `tests/test_testing/test_quality_fixtures.py`:

```python
import json
from pathlib import Path


FIXTURE_DIR = Path("tests/generation/fixtures/quality")


def test_quality_fixtures_have_required_fields():
    paths = sorted(FIXTURE_DIR.glob("*.json"))

    assert {path.name for path in paths} == {
        "ai_flavor.json",
        "repeated_beat.json",
        "text_integrity.json",
        "weak_hook.json",
    }
    for path in paths:
        data = json.loads(path.read_text())
        assert data["id"]
        assert data["category"]
        assert data["chapter_plan"]["beats"]
        assert data["raw_text"]
        assert data["expected_issue_codes"]
```

- [ ] **Step 2: Create fixtures**

Create `tests/generation/fixtures/quality/repeated_beat.json`:

```json
{
  "id": "repeated_beat",
  "category": "structure",
  "chapter_plan": {
    "title": "雨夜旧信",
    "beats": [
      {"summary": "主角发现旧信"},
      {"summary": "主角藏起旧信并试探来人"}
    ]
  },
  "raw_text": "主角推门进屋，看见桌上的旧信。\n\n主角推门进屋，看见桌上的旧信。\n\n门外脚步停住。",
  "expected_issue_codes": ["beat_cohesion"]
}
```

Create `tests/generation/fixtures/quality/ai_flavor.json`:

```json
{
  "id": "ai_flavor",
  "category": "prose",
  "chapter_plan": {
    "title": "雨夜旧信",
    "beats": [{"summary": "主角读到旧信"}]
  },
  "raw_text": "他不禁心头一震，仿佛这一切都在无声地告诉他，命运的齿轮已经缓缓转动。",
  "expected_issue_codes": ["ai_flavor"]
}
```

Create `tests/generation/fixtures/quality/weak_hook.json`:

```json
{
  "id": "weak_hook",
  "category": "plot",
  "chapter_plan": {
    "title": "雨夜旧信",
    "beats": [{"summary": "主角发现旧信", "hook": "门外脚步停住"}]
  },
  "raw_text": "主角把旧信收好，决定明天再查。夜色安静下来。",
  "expected_issue_codes": ["required_payoff", "hook_strength"]
}
```

Create `tests/generation/fixtures/quality/text_integrity.json`:

```json
{
  "id": "text_integrity",
  "category": "structure",
  "chapter_plan": {
    "title": "断句",
    "beats": [{"summary": "主角逃离"}]
  },
  "raw_text": "他撑着墙站起来，回头看向雨幕深处，还是。",
  "expected_issue_codes": ["text_integrity"]
}
```

- [ ] **Step 3: Run fixture test**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_quality_fixtures.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/generation/fixtures/quality tests/test_testing/test_quality_fixtures.py
git commit -m "test: add golden quality fixtures"
```

### Task 14: Final Verification

**Files:**
- No new files.

- [ ] **Step 1: Run focused quality system tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest \
  tests/test_schemas/test_quality.py \
  tests/test_services/test_quality_gate_service.py \
  tests/test_services/test_quality_issue_service.py \
  tests/test_services/test_beat_boundary_service.py \
  tests/test_services/test_repair_planner_service.py \
  tests/test_services/test_chapter_run_trace_service.py \
  tests/test_testing/test_generation_contracts.py \
  tests/test_testing/test_quality_summary.py \
  tests/test_testing/test_quality_fixtures.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run relevant agent/API tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest \
  tests/test_agents/test_writer_agent.py \
  tests/test_agents/test_editor_agent.py \
  tests/test_agents/test_fast_review_agent.py \
  tests/test_api/test_auto_chapter_generation_routes.py \
  -q
```

Expected: PASS.

- [ ] **Step 3: Run stable test suite**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/ -q
```

Expected: PASS. If failures occur outside files touched by this plan, record them in the final handoff with file names and failure messages.

- [ ] **Step 4: Commit any final fixes**

If Step 1 or Step 2 required small fixes in files from this plan, commit them:

```bash
git add \
  src/novel_dev/schemas/quality.py \
  src/novel_dev/services/quality_gate_service.py \
  src/novel_dev/services/quality_issue_service.py \
  src/novel_dev/services/beat_boundary_service.py \
  src/novel_dev/services/repair_planner_service.py \
  src/novel_dev/services/chapter_run_trace_service.py \
  src/novel_dev/agents/context_agent.py \
  src/novel_dev/agents/writer_agent.py \
  src/novel_dev/agents/editor_agent.py \
  src/novel_dev/agents/fast_review_agent.py \
  src/novel_dev/services/chapter_generation_service.py \
  src/novel_dev/testing/generation_contracts.py \
  src/novel_dev/testing/quality_summary.py \
  tests/test_schemas/test_quality.py \
  tests/test_services/test_quality_gate_service.py \
  tests/test_services/test_quality_issue_service.py \
  tests/test_services/test_beat_boundary_service.py \
  tests/test_services/test_repair_planner_service.py \
  tests/test_services/test_chapter_run_trace_service.py \
  tests/test_agents/test_context_agent_chapters.py \
  tests/test_agents/test_writer_agent.py \
  tests/test_agents/test_editor_agent.py \
  tests/test_agents/test_fast_review_agent.py \
  tests/test_api/test_auto_chapter_generation_routes.py \
  tests/test_testing/test_generation_contracts.py \
  tests/test_testing/test_quality_summary.py \
  tests/test_testing/test_quality_fixtures.py \
  tests/generation/fixtures/quality
git commit -m "fix: stabilize quality system tests"
```

Do not commit unrelated pre-existing workspace changes.

## Self-Review Notes

- Spec coverage: Tasks 1-3 cover standardized quality issues; Tasks 4-5 cover beat boundaries; Tasks 6-8 cover typed repair tasks; Tasks 9-10 cover run traces and resume diagnostics; Tasks 11-12 cover contract/reporting; Task 13 covers golden fixtures; Task 14 covers verification.
- Red-flag scan: This plan intentionally includes exact file paths, test names, command lines, expected outcomes, and implementation snippets. No unresolved markers are required for implementation.
- Type consistency: Shared models are defined in Task 1 and reused by later tasks. `QualityIssueService`, `RepairPlanner`, and `ChapterRunTraceService` use those same model names.
