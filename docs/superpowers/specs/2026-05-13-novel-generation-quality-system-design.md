# Novel Generation Quality System Design

Date: 2026-05-13
Status: Draft for user review

## Purpose

This design improves the general novel generation workflow and output quality in `novel-dev`.

The goal is not to tune one test novel. Recent long-form runs exposed common weaknesses in the pipeline: unclear quality diagnostics, beat-boundary drift, editor rewrites that introduce new problems, weak repair loops, ambiguous resume state, and over-reliance on one real-LLM sample. This design turns those findings into reusable infrastructure for any novel, genre, or dataset.

The system should make each generation run answer four questions clearly:

- What was generated?
- Where did the flow stop?
- Which quality issues caused the stop?
- What repair or resume action is safe next?

## Scope

In scope:

- Standardize quality issues across critic, fast review, quality gate, structure guard, continuity audit, and testing reports.
- Add explicit beat-boundary guidance before generation and retain post-generation structure guards.
- Replace broad final polishing with typed repair tasks.
- Improve continuous-writing traceability and resume behavior.
- Add cross-genre fixtures and reporting metrics that avoid overfitting to a single test novel.

Out of scope:

- No novel-specific prompt, rule, entity, plot, or chapter patch.
- No lowering of quality gates to make acceptance pass.
- No redesign of setting generation, entity encyclopedia, or source-material ingestion.
- No frontend redesign beyond exposing existing diagnostic fields where needed.

## Current Context

The current generation pipeline is:

```text
context_preparation -> drafting -> reviewing -> editing -> fast_reviewing -> librarian -> completed
```

Important existing components:

- `WriterAgent` writes beat-anchored chapter drafts.
- `CriticAgent` scores draft quality and emits per-dimension issues.
- `EditorAgent` rewrites weak beats and runs editor structure guard checks.
- `FastReviewAgent` checks polished text, runs final scoring, applies `QualityGateService`, and can route once back to editing for repair.
- `ChapterStructureGuardService` detects plan-boundary violations.
- `ChapterGenerationService` drives continuous chapter generation and stops on quality blocks, cancellation, global review, or failure.
- Testing tools under `src/novel_dev/testing/` generate real-run summaries and contract evidence.

Recent runs show that the system can detect many problems, but the detected problems do not yet form a clean repair contract. Reports also mix chapter state, run state, and acceptance state, making flow-level diagnosis harder than it should be.

## Chosen Approach

Use a layered quality system:

1. Normalize all quality findings into a shared `QualityIssue` model.
2. Generate and enforce beat-boundary cards for Writer and Editor.
3. Convert repairable issues into typed `RepairTask` objects.
4. Track each chapter attempt with a structured run trace.
5. Evaluate improvements with deterministic fixtures and a small set of real-LLM scenarios across genres.

This approach keeps existing pipeline phases and data fields compatible while adding a clearer contract between review, repair, flow control, and reporting.

Rejected alternatives:

- Prompt-only tuning: faster to try, but it does not fix diagnosis, repair routing, or resume ambiguity.
- Acceptance-only fixes: can make one run pass while preserving low-quality output.
- Full rewrite of the pipeline: too much risk for a system that already has useful agents, guards, and tests.

## Quality Issue Model

Add shared quality schemas in `src/novel_dev/schemas/quality.py`.

```python
class QualityIssue(BaseModel):
    code: str
    category: Literal[
        "structure",
        "prose",
        "character",
        "plot",
        "continuity",
        "style",
        "process",
    ]
    severity: Literal["info", "warn", "block"]
    scope: Literal["chapter", "beat", "paragraph", "flow"]
    beat_index: int | None = None
    repairability: Literal["auto", "guided", "manual", "none"]
    evidence: list[str] = Field(default_factory=list)
    suggestion: str = ""
    source: Literal[
        "critic",
        "fast_review",
        "quality_gate",
        "structure_guard",
        "continuity_audit",
        "testing",
    ]
```

### Mapping Rules

Initial mappings:

- `beat_cohesion` -> `structure/block/beat/guided`
- `text_integrity` -> `structure/block/paragraph/auto`
- `ai_flavor` -> `prose/warn/chapter/guided`
- `language_style` -> `style/warn/chapter/guided`
- `required_payoff` -> `plot/warn or block/chapter/guided`
- `hook_strength` -> `plot/warn/beat/guided`
- `continuity_audit` -> `continuity/block or warn/chapter/guided`
- generation job failures -> `process/block/flow/manual`

### Integration

- `QualityGateService` keeps returning current `blocking_items` and `warning_items`, and additionally exposes conversion to `QualityIssue`.
- `FastReviewAgent._build_final_polish_issues()` consumes `QualityIssue` first, then falls back to legacy items.
- Testing summaries aggregate issues by `category`, `code`, `severity`, and `repairability`.

Compatibility is required. Existing API fields remain available until consumers migrate.

## Beat Boundaries

The pipeline should provide explicit boundaries before generation and editing, not only after the model has already produced text.

Add a beat-level boundary card:

```python
class BeatBoundaryCard(BaseModel):
    beat_index: int
    must_cover: list[str]
    allowed_materials: list[str]
    forbidden_materials: list[str]
    reveal_boundary: str
    ending_policy: str
```

### Writer Behavior

`WriterAgent` receives the current `BeatBoundaryCard` with the beat plan. The prompt should require:

- Cover `must_cover`.
- Use only `allowed_materials` for risk, suspense, action, and emotional escalation.
- Do not introduce `forbidden_materials`.
- Do not execute later beat events early.
- Preserve beat anchors such as `<!--BEAT:n-->`.

### Editor Behavior

`EditorAgent` should move from one generic rewrite path to typed edit modes:

- `prose_polish`: expression, rhythm, redundancy, AI-flavor reduction.
- `cohesion_repair`: repeated segments, broken transitions, event order confusion.
- `hook_repair`: stronger stopping point using already allowed materials.
- `character_repair`: distinct action, dialogue, or reaction markers without new backstory.
- `integrity_repair`: truncation, isolated punctuation, broken sentence endings.
- `continuity_repair`: conflict with established world state or timeline.

The existing `ChapterStructureGuardService` remains the post-generation guard. Its evidence should be converted into standard `QualityIssue` objects.

## Repair Tasks

Add a typed repair task model. It can start as checkpoint data and later move to a table if needed.

```python
class RepairTask(BaseModel):
    task_id: str
    chapter_id: str
    issue_codes: list[str]
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
```

### Repair Planner

Introduce a small `RepairPlanner` service that groups `QualityIssue` objects into a bounded set of `RepairTask` objects.

Mapping examples:

- `beat_cohesion` -> `cohesion_repair`
- `text_integrity` -> `integrity_repair`
- `ai_flavor`, explanation-heavy prose, dense metaphor -> `prose_polish`
- `required_payoff`, weak hook -> `hook_repair`
- flat supporting character -> `character_repair`
- hard continuity conflict -> `continuity_repair`

### Repair Execution

Repair flow:

1. `FastReviewAgent` produces standard issues.
2. `RepairPlanner` creates tasks.
3. `EditorAgent` executes task-specific prompts.
4. The relevant guard runs for each task.
5. Final review and quality gate run once after all tasks finish.

Retry policy:

- Each task type may retry once.
- A chapter may run at most two repair rounds.
- `integrity_repair` may be auto-fixed when deterministic repair is possible.
- `cohesion_repair`, `hook_repair`, and `continuity_repair` require guard validation.
- `prose_polish` and `character_repair` should normally warn rather than block unless combined with low final score or structural failures.

Repair state stored in checkpoint:

```python
{
  "repair_tasks": [...],
  "repair_history": [...],
  "quality_issue_summary": {...}
}
```

## Chapter Run Trace

Continuous generation needs one source of truth for chapter progress and failure diagnosis.

Add a structured trace model:

```python
class ChapterRunTrace(BaseModel):
    novel_id: str
    chapter_id: str
    run_id: str
    phase_events: list[PhaseEvent] = Field(default_factory=list)
    current_phase: str
    terminal_status: Literal[
        "succeeded",
        "blocked",
        "failed",
        "cancelled",
        "repairing",
    ]
    terminal_reason: str | None = None
    quality_status: str = "unchecked"
    issue_summary: dict = Field(default_factory=dict)
    repair_attempts: int = 0
    archived: bool = False
    exported: bool | None = None
```

```python
class PhaseEvent(BaseModel):
    phase: str
    status: Literal["started", "succeeded", "failed", "blocked", "skipped"]
    started_at: str
    ended_at: str | None = None
    input_summary: dict = Field(default_factory=dict)
    output_summary: dict = Field(default_factory=dict)
    issues: list[QualityIssue] = Field(default_factory=list)
```

### Flow Integration

- `ChapterGenerationService._run_current_chapter()` appends phase events as each phase starts and finishes.
- Quality blocks record `blocked` or `repairing`, not a generic failed state.
- `FastReviewAgent` writes quality issue summary and repair task status into the trace.
- `EditorAgent` records repair attempts and guard results.
- Testing contracts read generated, archived, blocked, pending, and exported counts from a common helper.

### Resume Rules

- `repairing`: resume pending repair tasks.
- `blocked` with repairable issues: allow explicit repair resume.
- `failed` in context or drafting: retry the current phase.
- `archived`: continue from the next chapter.
- On chapter change, clear chapter-scoped checkpoint keys while preserving trace and repair history.

## Export Diagnosis

Export failures should be classified:

- `no_archived_chapters`
- `export_not_requested`
- `export_failed`
- `export_succeeded`

Testing reports should show the export class instead of only saying that an exported path is missing.

## Evaluation Strategy

Use three testing layers.

### Unit Fixtures

Fast deterministic tests for:

- `QualityIssue` conversion.
- `RepairPlanner` mappings.
- Boundary card serialization.
- Trace event updates.
- Resume-state decisions.

### Golden Chapter Fixtures

Small handcrafted examples that contain one or more known problems:

- Repeated beat segment.
- Plan-boundary violation.
- AI-flavor-heavy prose.
- Weak ending hook.
- Flat supporting character.
- Truncated sentence or isolated punctuation.
- Continuity conflict.

These tests use mock LLM output or direct service calls. They must not require real LLM providers.

### Real LLM Scenarios

Keep real runs as acceptance and trend checks, not ordinary unit tests.

Use short cross-genre scenarios:

- Xianxia revenge.
- Urban mystery.
- Ensemble court or faction intrigue.
- Light comedy or daily-life fiction.

The purpose is to see whether issue categories, repair success, and scores improve across styles, not to optimize for one sample.

## Metrics

Flow metrics:

- `phase_success_rate`
- `repair_success_rate`
- `resume_success_rate`
- `archive_rate`
- `export_result`

Quality metrics:

- `issue_count_by_category`
- `block_rate_by_issue_code`
- `avg_final_review_score`
- `word_count_drift_ratio`
- `repair_regression_count`
- `plan_boundary_violation_count`

Reports should distinguish:

- Chapter quality status.
- Run status.
- Acceptance summary status.
- Export status.

## Error Handling

- Schema conversion failures should preserve legacy issue items and log a process warning.
- Repair planning with no repairable issues should leave the chapter blocked and explain why.
- Repair task failure should record the failed task and guard evidence, then stop after retry limits.
- Guard fallback may return source text only when the task is not required to fix a blocking issue.
- Real LLM provider errors remain external or process failures, separate from generation quality failures.

## Testing Plan

Add or update tests in these areas:

- `tests/test_services/test_quality_gate_service.py`: legacy issue to `QualityIssue` conversion.
- `tests/test_agents/test_fast_review_agent.py`: final review issues create repair tasks and issue summaries.
- `tests/test_agents/test_editor_agent.py`: task-specific repair modes preserve boundaries.
- `tests/test_services/test_chapter_structure_guard_service.py`: guard evidence maps to standard issues.
- `tests/test_services/test_chapter_generation_service.py` or existing auto-run route tests: trace and resume behavior.
- `tests/test_testing/test_generation_contracts.py`: unified counts and export classifications.
- `tests/test_testing/test_quality_summary.py`: category/code aggregation and status separation.

Real-LLM scripts should remain opt-in through `scripts/verify_generation_real.sh`.

## Rollout

Phase 1: Add schemas and adapters.

- Add `QualityIssue`.
- Add conversion helpers.
- Add report aggregation.
- Keep existing behavior unchanged.

Phase 2: Add boundary cards and typed repair tasks.

- Generate boundary cards from chapter plans.
- Add `RepairPlanner`.
- Route selected issues to typed editor repair modes.
- Keep old `final_polish_issues` as compatibility fallback.

Phase 3: Add run trace and resume improvements.

- Record phase events.
- Normalize run, chapter, and acceptance statuses.
- Improve export diagnosis.

Phase 4: Add fixtures and trend reporting.

- Add golden chapter fixtures.
- Add cross-genre real-LLM scenarios.
- Track issue and repair metrics over runs.

## Success Criteria

- The system contains no novel-specific quality rules.
- Existing API and checkpoint consumers continue to work during migration.
- Quality issues from critic, fast review, quality gate, guards, and tests can be reported in one taxonomy.
- A repairable quality block produces typed repair tasks with constraints and success criteria.
- Continuous writing reports exactly which chapter and phase stopped, whether repair is possible, and where resume should start.
- Test fixtures cover structure, prose, plot payoff, character, continuity, text integrity, process, and export diagnostics.
- Real-LLM reports can compare quality trends across more than one genre sample.
