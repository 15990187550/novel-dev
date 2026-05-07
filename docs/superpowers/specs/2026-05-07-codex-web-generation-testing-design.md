# Codex Web And Generation Testing Design

Date: 2026-05-07
Status: Draft for user review

## Purpose

This design defines a Codex-executable testing system for the current `novel-dev` project. It covers backend generation flow tests, Vue web tests, browser E2E tests, structured visual checks, real LLM validation, fallback diagnosis, and unified failure reporting.

The goal is not only to know whether tests pass. The goal is to let Codex run the right checks, classify failures correctly, preserve evidence, and give a fast path for repair and re-verification.

## Current Project Context

The project is a Python 3.11+ FastAPI application with SQLAlchemy async persistence and a Vue 3/Vite/Element Plus SPA in `src/novel_dev/web`.

Existing validation includes:

- Python tests under `tests/`, run with `PYTHONPATH=src python3.11 -m pytest`.
- Web component and unit tests under `src/novel_dev/web/src`, run with Vitest.
- `scripts/verify_local.sh`, which currently runs Python tests, compile checks, Web tests, and Web build.
- Existing generation-related services and agents for setting workbench, brainstorming, outline planning, chapter generation, review, editing, librarian extraction, and export.

The repository does not currently have a browser E2E framework such as Playwright or Cypress.

## Chosen Approach

Use a layered testing matrix with a generation-level dual-track runner.

The stable gate stays fast and deterministic. Real LLM generation validation moves into a dedicated entrypoint. When real LLM execution fails, the failure is classified before fallback. External blockers may trigger Fake/Mock reruns for diagnosis. System and quality failures remain failures even if a Fake/Mock rerun later passes.

Rejected alternatives:

- Only enhancing `scripts/verify_local.sh`: too shallow for full generation validation.
- Running every test in a full real environment by default: too slow, expensive, and noisy for daily work.

## Testing Layers

### 1. Stable Gate

`scripts/verify_local.sh` remains the daily deterministic gate.

It should run:

- Python pytest.
- Python compile checks.
- Web Vitest.
- Web build.
- A Fake/Mock LLM minimal generation flow.

It should not call real LLM providers by default.

### 2. Real Generation Acceptance

Add a dedicated entrypoint:

```bash
scripts/verify_generation_real.sh
```

This runner defaults to real LLMs and validates the minimum complete novel generation path:

1. Environment preflight.
2. Create isolated test novel.
3. AI-generate settings.
4. Consolidate and review settings.
5. Brainstorm synopsis and outline.
6. Generate volume and chapter plan.
7. Prepare chapter context.
8. Generate at least one chapter draft or rewrite.
9. Run review, editing, fast review, librarian/archive updates.
10. Export and verify output consistency.

The runner supports two data sources:

- Built-in minimal fixture data committed to the repository.
- Optional real project data directory passed by parameter.

### 3. Web E2E

Add Playwright for real browser testing.

Suggested root wrapper:

```bash
scripts/verify_web_e2e.sh
```

Suggested Web scripts:

```bash
cd src/novel_dev/web
npm run test:e2e
npm run test:visual
```

E2E tests should cover:

- App boot and default dashboard route.
- Creating or selecting a test novel.
- Documents/settings workflow entry points.
- Setting workbench status display.
- Brainstorm/outline/volume plan visibility.
- Chapter list and chapter detail.
- Entity list, search, grouping, and detail panel.
- Logs page and EventSource/history handling.
- Config page without exposing secret values.
- Export action visibility and result handling.

Web E2E should normally use seeded backend state or the output of generation acceptance tests. It should not re-run long real LLM flows unless the specific purpose is an end-to-end real generation acceptance run.

### 4. Structured Visual Checks

Structured visual checks are the default visual gate because the app has dynamic generated content, logs, charts, Chinese text, and variable data.

Each key page should be checked on desktop and mobile viewports for:

- No blank page.
- No uncaught page error.
- No unexpected console error.
- No failed critical API request.
- Key title and primary content visible.
- Primary actions visible and clickable.
- Main content has no horizontal overflow.
- Important panels and buttons have valid bounding boxes.
- No obvious text overlap or loading state stuck after navigation.
- Dark mode coverage where the page supports it.

### 5. Screenshot Baseline

Screenshot diff is reserved for manual, release, or large UI-change validation.

Baseline candidates:

- Dashboard.
- Documents and settings workbench.
- Volume plan.
- Chapter detail.
- Entities.
- Logs.
- Config.

Screenshot failures must include the page, viewport, baseline image, actual image, diff image, trace path, and re-verification command.

## Generation Quality Evaluation

Generated novel material is evaluated with four layers.

### Hard Validation

Hard validation is deterministic and runs before model-based quality judgment.

Settings, outline, and prose must satisfy:

- Non-empty output.
- Minimum length thresholds.
- Required structured fields.
- No obvious placeholder markers, incomplete filler text, empty arrays, repeated boilerplate, or model apology text.
- Valid JSON or Markdown where required.
- Output can feed the next pipeline stage.

Settings must include enough material for downstream generation, including worldbuilding, characters, factions or forces, locations, rules, core conflicts, and source or rationale notes where the workflow supports them.

Outlines must include a coherent main line, staged goals, conflicts, character motivation, and executable chapter planning material.

Chapter prose must include title or chapter identity, minimum word or character count, meaningful paragraphs, and coverage of required beats.

### LLM Rubric Review

Real LLM outputs should be reviewed with a structured rubric. The reviewer may be a separate configured model or the same provider with a strict review prompt. The review returns scores, evidence snippets, and failure reasons.

Settings rubric:

- Completeness.
- Internal consistency.
- Writeability.
- Distinctiveness.
- Clarity of constraints.

Outline rubric:

- Main-line clarity.
- Conflict escalation.
- Chapter executability.
- Character motivation.
- Consistency with approved settings.

Chapter prose rubric:

- Completion of chapter goal.
- Beat coverage.
- Character and setting consistency.
- Scene effectiveness.
- Style stability.
- Absence of topic drift, filler, repetition, and hallucinated major facts.

The gate does not require excellent fiction. It requires complete, consistent, usable generated material with no obvious quality accident.

### Cross-Stage Consistency

The test must compare generated stages against each other.

Examples:

- Chapter prose should not introduce core characters, factions, locations, or rules that do not exist in settings or outline unless the current step explicitly creates them.
- Chapter prose should execute the chapter plan and cover required beats.
- Librarian-extracted state should match the generated chapter.
- Entity relationships should not overwrite approved facts without review.
- Exported Markdown should match database chapter and archive state.

### Human Review Support

The system should preserve quality artifacts so humans can inspect failures quickly:

- Generated settings.
- Outline and volume plan.
- Chapter draft and edited version.
- Rubric scores.
- Evidence snippets.
- Cross-stage consistency findings.

## Real LLM Failure Policy

Real LLM validation is expected to catch real defects. Fallback must not hide those defects.

Failures are classified before fallback:

- External blockers: rate limits, quota exhaustion, provider outage, network outage, or provider authentication outage.
- System abnormalities: parse failure, invalid structure, state machine stuck, non-reasonable timeout, API contract mismatch, database write failure, quality gate failure, unusable generated output, or pipeline state that cannot advance.

Only external blockers allow the final result to be considered externally blocked after Fake/Mock continuation. System abnormalities remain final failures. Fake/Mock reruns are still useful in those cases, but only for diagnosis.

Timeout classification:

- Provider-side rate limit, queueing, or outage timeout is external blocked when evidence supports it.
- Prompt, parser, polling, task state, queue handling, or internal orchestration timeout is a system abnormality.

## Failure Categories

All test entrypoints use shared categories:

- `SYSTEM_BUG`: code logic, state transition, API contract, persistence, or Web interaction defect.
- `GENERATION_QUALITY`: real LLM result is structurally present but not usable enough.
- `LLM_PARSE_ERROR`: model output cannot be parsed or misses required fields. Unless provider failure is clear, this is a system problem to improve through prompt, parser, or retry logic.
- `TIMEOUT_INTERNAL`: task, polling, status, or orchestration timeout inside the system.
- `EXTERNAL_BLOCKED`: rate limit, quota, provider unavailable, authentication outage, or network outage.
- `TEST_INFRA`: fixture, script, selector, or environment setup defect.
- `VISUAL_REGRESSION`: blank page, overlap, overflow, screenshot diff, or broken responsive layout.
- `FLAKY_SUSPECTED`: inconsistent result after retry. This stays visible and requires targeted follow-up.

## Reporting And Re-Verification

Every entrypoint writes a report directory:

```text
reports/test-runs/2026-05-07T153000-generation-real/
  summary.md
  summary.json
  commands.log
  env.json
  artifacts/
    api.log
    web.log
    playwright-report/
    screenshots/
    traces/
    generation/
      stage-01-settings.json
      stage-02-outline.json
      stage-07-chapter.md
      quality-scores.json
```

`summary.json` is machine readable and must include:

- Run id.
- Entrypoint.
- Status.
- Duration.
- Dataset.
- LLM mode.
- Environment summary.
- Issue list.
- Artifact paths.
- Reproduction commands.

Example issue shape:

```json
{
  "id": "GEN-QUALITY-001",
  "type": "GENERATION_QUALITY",
  "severity": "high",
  "stage": "chapter_draft",
  "is_external_blocker": false,
  "real_llm": true,
  "fake_rerun_status": "passed",
  "message": "Chapter draft missed the second required beat and introduced an undefined faction.",
  "evidence": [
    "artifacts/generation/quality-scores.json",
    "artifacts/generation/stage-07-chapter.md"
  ],
  "reproduce": "scripts/verify_generation_real.sh --stage chapter_draft --dataset minimal_builtin"
}
```

`summary.md` is human readable and includes:

- Entry point, dataset, LLM mode, and duration.
- Passed stages.
- Blocking system abnormalities.
- Generation quality issues.
- External blockers.
- Visual issues.
- Test infrastructure issues.
- Recommended repair order.
- Minimal re-verification commands.

Each issue receives a stable id such as:

- `GEN-STEP-001`
- `GEN-QUALITY-001`
- `WEB-E2E-001`
- `VISUAL-001`
- `INFRA-001`

After repair, Codex should re-run the minimal command for each issue id before running the broader entrypoint.

## Suggested File Layout

```text
tests/
  generation/
    test_minimal_generation_flow.py
    fixtures/
      minimal_novel.yaml
      fake_llm_profiles.yaml
    quality/
      validators.py
      rubrics.py
      report.py

src/novel_dev/web/
  playwright.config.js
  e2e/
    flows/
      generation.spec.js
      navigation.spec.js
    visual/
      layout.spec.js
      screenshots/

scripts/
  verify_generation_real.sh
  verify_web_e2e.sh

reports/
  test-runs/
```

## Codex Execution Manual

Codex should choose tests by changed files and risk.

Backend services, repositories, agents, API routes:

1. Run targeted pytest.
2. Run `scripts/verify_local.sh`.
3. If generation behavior changed, run `scripts/verify_generation_real.sh`.

Web source changes:

1. Run targeted Vitest.
2. Run related Playwright spec.
3. Run structured visual checks for affected pages.
4. Run screenshot baseline only for large UI changes or release validation.

LLM config, prompts, agents, setting, outline, chapter, review, librarian, export:

1. Run relevant pytest.
2. Run `scripts/verify_generation_real.sh`.
3. Review generated quality artifacts and issue summary.

Before claiming completion:

- Relevant unit tests pass.
- `scripts/verify_local.sh` passes.
- Real generation acceptance passes for generation-chain changes, or failures are correctly classified and non-external failures are fixed or explicitly left as known work.
- Web E2E and structured visual checks pass for Web changes.
- Reports include issue ids, evidence, and re-verification commands.
- Fixed issues have been re-verified by issue-specific commands.

## Implementation Scope

The implementation should be incremental:

1. Add shared report schema and report writer.
2. Add Fake/Mock minimal generation flow to stable gate.
3. Add real generation runner with failure classification.
4. Add generation quality validators and rubric review.
5. Add Playwright configuration and Web E2E smoke paths.
6. Add structured visual checks.
7. Add screenshot baseline workflow for release validation.

This is one cohesive testing system, but the implementation can be delivered in phases without blocking normal development.
