# Setting Consolidation Design

**Date:** 2026-05-04
**Scope:** Add a one-click consolidation flow for scattered novel settings produced by manual imports and AI generation.

## Goals

Users can consolidate scattered setting material without directly mutating formal data.

The flow should:

- use approved, currently effective settings as the default source of truth
- allow selected pending review records to participate in consolidation
- generate a new review record instead of applying AI output directly
- archive old scattered content only after review approval
- keep conflicts visible for user confirmation instead of letting AI decide silently

## Non-Goals

- Do not hard-delete old settings during consolidation.
- Do not automatically include failed records, unreviewed AI session drafts, or all pending records.
- Do not bypass the existing review-first product boundary.
- Do not let "approve all" silently approve unresolved conflicts.
- Do not replace the broader setting workbench AI generation flow.

## Product Model

Add a primary **一键整合设定** action in **设定工作台**.

The action opens a confirmation dialog that shows:

- currently effective settings are included automatically
- pending review records are optional and must be explicitly selected
- failed records and unconfirmed AI drafts are excluded
- the result will be a new review record, not an immediate rewrite

The submitted consolidation creates a task and returns immediately. The user sees task progress and, when successful, a new consolidation review record.

## Input Scope

Default included sources:

- approved effective setting documents and setting cards
- approved effective entities
- approved effective relationships

Optional sources:

- user-selected pending review records

Excluded sources:

- failed review records
- rejected review records
- unconfirmed AI session drafts
- pending records not selected by the user

The backend snapshots the selected inputs when the task starts. Retries use the same input snapshot so results do not drift if the user edits settings while the task is running.

## Consolidation Review Record

Consolidation produces a review batch with `source_type = "consolidation"`.

The batch can contain these change types:

- `create setting_card` or `update setting_card`: integrated setting cards, such as cultivation system overview or faction structure overview
- `create entity` or `update entity`: merged or enriched characters, factions, locations, items, concepts, and other entities
- `create relationship` or `update relationship`: validated relationship changes, still constrained by entity types
- `archive setting_card`, `archive entity`, or `archive relationship`: old scattered content that has been absorbed into the integrated version
- `conflict`: contradictory source material that requires user confirmation

Review approval is the only step that mutates formal data.

Before approval:

- formal settings stay unchanged
- archive changes are only recommendations
- conflicts are visible but unresolved

After approval:

- integrated settings become the effective version
- old absorbed content is archived and hidden from normal lists
- source links record which consolidation batch absorbed each old item
- no content is physically deleted

## Conflict Handling

AI must not automatically choose a winner when source material conflicts.

Examples:

- two incompatible cultivation realm ladders
- the same faction has two incompatible allegiance descriptions
- a location belongs to two mutually exclusive regions
- an item has contradictory ownership or origin

Each conflict stores:

- affected target type and target identity when known
- conflicting source excerpts or snapshots
- a short AI explanation of why they conflict
- candidate resolutions when available

The user must resolve conflicts by choosing a candidate or editing the proposed result. A batch with unresolved conflicts cannot be approved as a whole. Non-conflict changes may still be approved individually, leaving the batch `partially_approved`.

## Archive Semantics

Archiving means old content is no longer treated as current effective setting.

Archived items:

- are hidden by default from normal setting, entity, and relationship lists
- remain available through an **已归档 / 已整合** filter
- keep source metadata pointing to the consolidation batch and change that archived them
- can be restored or referenced later if a consolidation was wrong

Hard deletion is out of scope.

## Backend Structure

Extend the setting workbench review model rather than adding a separate direct-write path.

Expected additions:

- a consolidation task/job record or reuse of the existing generation job infrastructure
- review batch support for `source_type = "consolidation"`
- review change support for `archive` and `conflict`
- input snapshot storage on the job or batch
- archive metadata on formal setting cards, entities, and relationships

The consolidation service should:

1. Validate the novel and selected pending review records.
2. Snapshot effective settings plus selected pending records.
3. Create a consolidation job with status `queued`.
4. Run AI consolidation asynchronously.
5. Create a review batch with grouped changes.
6. Mark the job `ready_for_review` when the batch is available.
7. Mark failures without applying partial formal data.

Suggested job statuses:

- `queued`
- `collecting_inputs`
- `consolidating`
- `ready_for_review`
- `failed`

## Frontend Structure

The setting workbench should expose:

- **一键整合设定** button
- confirmation dialog with source scope summary
- pending review record selector
- consolidation task status row
- consolidation review detail view

The review detail should group changes into:

- 整合后设定
- 实体变更
- 关系变更
- 旧内容归档
- 冲突待确认

Normal setting/entity/relationship lists hide archived items by default. Add an **已归档 / 已整合** filter for audit and restoration.

## Error Handling

- If input validation fails, no job is created.
- If AI consolidation fails, the job becomes `failed` and formal data remains unchanged.
- If a draft review batch exists when failure occurs, it is marked `failed`.
- Retrying uses the original input snapshot.
- Applying review changes is per-change. Successful changes remain approved if later changes fail.
- Whole-batch approval is blocked while unresolved conflict changes remain.

## Logging And Observability

Use existing agent logs for concise task progress.

Main log entries should include:

- consolidation task started
- input snapshot counts
- AI consolidation started
- review batch created
- conflict count
- archive recommendation count
- failure reason when applicable

Detailed metadata should include source IDs, selected pending IDs, generated change counts, and error details.

## Testing

Backend tests:

- consolidation without selected pending records reads only effective approved settings
- selected pending records are included in the input snapshot
- unselected pending records, failed records, and AI drafts are excluded
- successful consolidation creates a review batch and does not mutate formal data
- approving the batch creates or updates integrated content
- approving archive changes hides old content by default
- archived content remains visible through an archive filter
- unresolved conflicts block whole-batch approval
- non-conflict changes can be approved while conflicts remain unresolved
- failed consolidation does not create partially effective formal data
- retry reuses the original snapshot

Frontend tests:

- setting workbench shows the one-click consolidation entry
- dialog explains default source scope and optional pending records
- selected pending records are submitted with the consolidation request
- task status renders queued, running, ready, and failed states
- review detail groups integrated settings, entity changes, relationship changes, archive changes, and conflicts
- whole-batch approve is disabled when conflicts are unresolved
- archived items are hidden by default and visible through the archive filter

## Open Implementation Notes

- The existing setting workbench persistence currently covers AI sessions and messages. Implementation should first verify whether review batch/change tables have already landed in the working tree before adding new tables.
- Existing pending extraction records can be input sources, but consolidation output should use unified review batches instead of writing new pending extraction rows.
- Existing entity relationship type guards should be reused when generating relationship changes.
- Existing log detail patterns should be reused so the main feed remains concise while detail metadata stays inspectable.
