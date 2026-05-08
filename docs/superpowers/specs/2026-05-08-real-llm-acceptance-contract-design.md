# Real LLM Acceptance Contract Design

Date: 2026-05-08
Status: Draft for user review

## Purpose

This design updates the real LLM generation acceptance test so it reports stable, stage-specific signals instead of treating every failure as a single full-flow failure.

The current runner already caught several real issues: empty exports, overly broad real brainstorm output, cross-novel chapter id collisions, slow chapter jobs, quality gate blocks, and missing `current_chapter_plan` after volume planning. Those are useful findings, but the acceptance path now mixes too many assumptions into one test. The result is slow reruns and failure messages that move from one implicit assumption to the next.

The next step is to make each stage declare and validate its own contract.

## Current Context

The real generation entrypoint is:

```bash
scripts/verify_generation_real.sh
```

It runs `novel_dev.testing.generation_runner` against the local API and writes reports under `reports/test-runs`.

Recent fixes already improved the runner:

- `summary.md` now includes artifacts.
- Exported Markdown is checked for missing or empty files.
- `ExportService.export_novel()` filters chapters by `novel_id`.
- The acceptance flow now invokes chapter auto-run before export.
- The runner shrinks real brainstorm output toward a one-volume, one-chapter acceptance scenario.
- The runner isolates acceptance volume and chapter ids to avoid reusing stale chapter rows from old novels.

The latest observed real run failed with:

```text
current_chapter_plan missing after volume_plan
```

That failure should not be handled by adding another hard-coded assumption. It should become a clear `volume_plan` contract failure with evidence about what the API and checkpoint actually contained.

## Chosen Approach

Use two layers:

1. `real-contract`: the default real LLM acceptance path.
2. `real-e2e-export`: a slower, stricter export path for manual or scheduled validation.

`real-contract` is the recommended default because it turns failures into precise stage diagnostics. It should prove that each stage produces the next stage's minimum usable input.

`real-e2e-export` remains valuable, but it should not be the only real test. It depends on generation quality, quality gate behavior, archiving, and export all succeeding in one long run.

Rejected alternatives:

- Continue chasing one full-flow pass first. This keeps hiding stage contracts behind long reruns.
- Count edited or draft text as a full pass. That makes the test stable, but weakens the meaning of "complete real test."

## Stage Contracts

### Brainstorm Contract

After `brainstorm`, the runner must verify that checkpoint data contains usable `synopsis_data`.

Minimum contract:

- A synopsis object exists.
- It has enough text to support volume planning.
- It can be reduced to a one-volume, one-chapter acceptance scope.
- The report records the original estimated volume/chapter scale before shrinking.

Failure stage:

```text
brainstorm_contract
```

### Volume Plan Contract

After `volume_plan`, the runner must extract one usable chapter plan.

Acceptable sources, in priority order:

1. `checkpoint.current_chapter_plan`
2. first item in `checkpoint.current_volume_plan.chapters`
3. an equivalent chapter object returned directly by the API response

Minimum contract:

- Chapter id or a deterministic acceptance id can be assigned.
- Chapter number can be resolved to `1`.
- Title or summary exists.
- Target word count can be set to the fixture minimum.
- Beat or summary material exists for the writer.

Failure stage:

```text
volume_plan_contract
```

Failure evidence must include:

- response keys from `/volume_plan`
- checkpoint keys after `/volume_plan`
- keys under `current_volume_plan`, if present
- whether `current_chapter_plan` was present
- chapter count under `current_volume_plan.chapters`, if present

### Chapter Generation Contract

After `auto_run_chapters`, the runner must distinguish text generation from quality gate and archive behavior.

Minimum contract for `real-contract`:

- the generation job reaches a terminal status
- at least one target chapter has generated text in `raw_draft` or `polished_text`
- report artifacts include chapter id, text field used, text length, job id, and job stopped reason

Quality gate behavior:

- If text exists but quality gate blocks archival, record a separate quality issue.
- A quality block should not be reported as an export bug.
- The report should include `quality_status` and quality reasons where available.

Failure stages:

```text
auto_run_chapters_contract
quality_gate
```

### Export Contract

For `real-contract`, export is conditional:

- If a chapter was archived, export must return a non-empty file.
- If quality gate blocked archival but text exists, export is skipped or marked not applicable.

For `real-e2e-export`, export is mandatory:

- at least one chapter must be archived
- exported Markdown must exist and be non-empty
- exported Markdown must contain the archived chapter title or text prefix

Failure stage:

```text
export_contract
```

## Runner Behavior

The runner should expose an acceptance scope option internally or through CLI flags:

```text
real-contract
real-e2e-export
```

Default behavior should be `real-contract`.

The existing `--stage` support remains useful. Stage names should align with contracts so a developer can rerun a focused check:

```bash
scripts/verify_generation_real.sh --stage volume_plan
scripts/verify_generation_real.sh --stage auto_run_chapters
scripts/verify_generation_real.sh --stage export
```

The implementation may keep existing stage names for CLI compatibility, but reports should use contract-specific failure stages when the HTTP call succeeded and the produced data failed validation.

## Reporting

The report must continue to show artifacts in `summary.md`.

Add artifacts when available:

- `contract_scope`
- `novel_id`
- `brainstorm_original_estimated_volumes`
- `brainstorm_original_estimated_total_chapters`
- `volume_id`
- `chapter_plan_source`
- `chapter_id`
- `chapter_target_word_count`
- `chapter_auto_run_job_id`
- `chapter_text_status`
- `chapter_text_length`
- `quality_status`
- `quality_reasons`
- `archived_chapter_count`
- `exported_path`

Contract failures should include concise evidence. Evidence should describe keys and counts, not dump full generated prose into the summary.

## Data Handling

The runner should not rely on old global ids such as `vol-1` or `vol_1_ch_1` for real acceptance state.

Acceptance ids should be deterministic per novel:

```text
acceptance-{novel_id}-vol1
acceptance-{novel_id}-ch1
```

The runner may normalize checkpoint data after a successful real LLM stage only to reduce acceptance scope and avoid stale data collisions. It should not fabricate a chapter plan when volume planning failed to produce any usable chapter material.

## Error Classification

External provider failures remain external blockers when they match the existing classification rules.

Internal contract failures are system bugs. They should be separated from HTTP failures:

- HTTP request failed: stage is the API operation, such as `volume_plan`.
- HTTP request succeeded but required output is missing: stage is the contract, such as `volume_plan_contract`.
- Chapter text exists but archival is blocked by quality: stage is `quality_gate`.
- Export is empty despite archived content: stage is `export_contract`.

## Testing

Unit tests should cover:

- chapter plan extraction from `current_chapter_plan`
- chapter plan extraction from `current_volume_plan.chapters[0]`
- chapter plan extraction from a response body
- volume plan contract evidence when no chapter plan exists
- chapter text detection from `raw_draft` and `polished_text`
- quality block reporting when text exists but no chapter is archived
- export skipped or marked not applicable in `real-contract` when quality gate blocks archival
- mandatory non-empty export in `real-e2e-export`
- report artifacts for contract scope and stage diagnostics

Existing tests for report artifact rendering, export file validation, and `novel_id` export filtering should remain.

## Out Of Scope

This design does not change the fiction quality rubric itself.

It does not tune prompts for better chapter prose.

It does not require changing the production API response format. A separate future API contract change can add explicit chapter-plan fields if the runner evidence shows checkpoint-only extraction is too fragile.

It does not delete existing historical reports or generated novel output.

## Success Criteria

The next implementation is successful when:

- the default real LLM run reports `real-contract` scope
- a missing chapter plan fails at `volume_plan_contract` with useful evidence
- a quality gate block is reported as `quality_gate`, not as export failure
- archived content is required before export is treated as mandatory in the default contract run
- the stricter export path can still require archive plus non-empty Markdown
- focused unit tests pass for the new contract helpers and runner behavior
