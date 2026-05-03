# Librarian Entity State Policy Design

## Problem

`LibrarianAgent` persists chapter extraction results into entity versions. Today, extracted entity updates are written as the next full state without a policy layer that distinguishes long-term canon from the current chapter state.

That creates a narrative correctness risk. For example, if the protagonist is canonically the main character or a future Dao inheritor, but chapter 1 presents him as a poor herb gatherer, the extracted state may overwrite the protagonist profile with a temporary "small person" role. The system needs to preserve authoritative character setup while still allowing chapter-by-chapter state changes.

## Goals

- Separate stable entity profile from rolling story state.
- Let chapter extraction update `current_state` as the story advances.
- Prevent chapter extraction from overwriting existing canonical fields.
- Preserve useful chapter facts as observations instead of dropping them.
- Keep the first implementation backend-only and testable.
- Avoid a database schema migration in the first pass.

## Non-Goals

- No frontend conflict-review UI in this pass.
- No global entity deduplication or merge workflow.
- No model-based second-pass conflict arbitration.
- No broad refactor of entity storage or graph rendering.
- No full data migration over every existing entity.

## Chosen Approach

Use a deterministic backend policy layer between `LibrarianAgent.persist()` and `EntityService.update_state()`.

The policy treats an entity state as a logical three-part document:

```json
{
  "canonical_profile": {},
  "current_state": {},
  "observations": {},
  "canonical_meta": {}
}
```

`canonical_profile` stores long-term authoritative setup. `current_state` stores the latest story slice and may change every chapter. `observations` stores chapter-scoped facts and ambiguous extracted text. `canonical_meta` records where inferred canonical fields came from.

The first pass keeps this structure inside the existing `EntityVersion.state` JSON column. Existing flat states are lazily normalized when an entity is updated.

## State Layers

### `canonical_profile`

Long-term identity and setting facts. Chapter extraction may fill missing canonical fields, but it may not overwrite existing canonical values.

Initial canonical field group:

- `name`
- `身份定位`, `identity_role`, `protagonist_role`
- `出身`, `origin`, `background_core`
- `核心性格`, `core_traits`
- `长期目标`, `long_term_goal`
- `核心能力`, `core_ability`
- `金手指`, `cheat`, `artifact_core`
- `阵营归属`, `faction_affiliation`
- `师承`, `lineage`

### `current_state`

Rolling story state. Chapter extraction can update these fields as the plot advances.

Initial current-state field group:

- `位置`, `location`
- `状态`, `condition`
- `伤势`, `injury`
- `境界`, `cultivation_level`
- `职业`, `occupation`
- `当前身份`, `current_identity`
- `社会位置`, `social_position`
- `情绪`, `emotional_state`
- `认知状态`, `knowledge_state`
- `持有物`, `possessions`
- `attitude_to_*`

### `observations`

Chapter-scoped facts and ambiguous extracted statements. Observations preserve evidence without polluting canonical profile fields.

Examples:

- First appearance style.
- One-off chapter actions.
- Unclassified fields.
- Whole-sentence extracted changes such as `变化`.
- Facts useful for audit, but not necessarily state fields.

The observations key is the chapter id:

```json
{
  "observations": {
    "vol_1_ch_1": [
      "以底层采药人身份登场",
      "接触无名古经后昏迷"
    ]
  }
}
```

## Conflict Rules

1. Current-state fields update `current_state` normally.
2. Canonical fields fill `canonical_profile` only when the canonical field is empty.
3. If a chapter extraction tries to overwrite an existing canonical field, keep the canonical value and demote the extracted value into `current_state` or `observations`.
4. Unclassified fields go into `observations` or `current_state.notes`.
5. Every demotion records a policy event for logs.

Example conflict:

Existing state:

```json
{
  "canonical_profile": {
    "identity_role": "主角"
  },
  "current_state": {}
}
```

Extracted chapter update:

```json
{
  "身份": "小人物",
  "职业": "采药人",
  "状态": "昏迷"
}
```

Normalized result:

```json
{
  "canonical_profile": {
    "identity_role": "主角"
  },
  "current_state": {
    "social_position": "小人物",
    "occupation": "采药人",
    "condition": "昏迷"
  },
  "observations": {
    "vol_1_ch_1": []
  },
  "canonical_meta": {
    "identity_role": {
      "source": "setting"
    }
  }
}
```

Policy event:

```json
{
  "type": "canonical_conflict_demoted",
  "field": "身份",
  "from": "主角",
  "to": "小人物",
  "written_to": "current_state.social_position"
}
```

## Data Flow

Current flow:

```text
LibrarianAgent.extract()
  -> ExtractionResult.character_updates / concept_updates
  -> LibrarianAgent.persist()
  -> EntityService.update_state()
  -> EntityVersion
```

New flow:

```text
LibrarianAgent.extract()
  -> ExtractionResult.character_updates / concept_updates
  -> LibrarianAgent.persist()
  -> EntityStatePolicy.normalize_update()
  -> EntityService.update_state()
  -> EntityVersion
```

`LibrarianAgent.extract()` stays focused on extraction. It does not need to perfectly classify every state field.

`EntityStatePolicy.normalize_update()` owns:

- Lazy normalization of old flat state.
- Field classification.
- Canonical conflict demotion.
- Observation append.
- Canonical inference metadata.
- Policy event reporting.

`EntityService.update_state()` continues to persist a complete state version.

## Lazy Normalization

If the latest state already has any of these keys, it is treated as structured:

- `canonical_profile`
- `current_state`
- `observations`

If not, the policy converts the old flat state on the next update.

Example flat state:

```json
{
  "name": "陆照",
  "身份": "主角",
  "境界": "凡人"
}
```

Normalized state:

```json
{
  "canonical_profile": {
    "name": "陆照",
    "身份": "主角"
  },
  "current_state": {
    "境界": "凡人"
  },
  "observations": {},
  "canonical_meta": {}
}
```

This avoids a mandatory all-entity migration.

## Logging

`LibrarianAgent.persist()` should include policy events in its detail metadata.

Events should be concise and machine-readable:

- `canonical_conflict_demoted`
- `canonical_field_inferred`
- `unclassified_observed`
- `flat_state_normalized`

The log should make it clear when the model attempted to overwrite a protected field and where the extracted value was stored instead.

## Error Handling

- Policy normalization should never raise for an unknown field.
- Unknown fields should be preserved in observations.
- Invalid or non-dict extracted state should be converted to an observation string.
- Missing latest state should start from empty structured state.
- Policy failures should be logged and should not block unrelated timeline, foreshadowing, or relationship persistence unless the state itself cannot be serialized.

## Testing

Add focused unit tests for the policy:

- Flat state is lazily normalized.
- Current-state fields update and replace prior current values.
- Existing canonical fields are not overwritten by chapter extraction.
- Empty canonical fields can be filled from chapter extraction and tagged in `canonical_meta` with `source=chapter_inferred` and `chapter_id`.
- Unclassified fields are preserved as observations.
- Non-dict extracted state is preserved as an observation.

Add Librarian integration tests:

- `LibrarianAgent.persist()` uses the policy for character updates.
- Policy events appear in log metadata.
- Existing entity version and classification refresh flows still run.
- Relationship persistence still resolves entities from names after state normalization.

## Implementation Scope

Create a small backend policy module at `src/novel_dev/services/entity_state_policy.py`.

The module should expose a simple interface:

```python
normalize_update(
    *,
    entity_type: str,
    entity_name: str,
    latest_state: dict | None,
    extracted_state: dict | str | None,
    chapter_id: str,
    diff_summary: dict | None,
) -> EntityStatePolicyResult
```

`EntityStatePolicyResult` should include:

- `state`: normalized full state to persist.
- `events`: policy events for logging.

The first implementation should not add database columns. If later the UI needs filtering or review, the same logical structure can be promoted into explicit tables or a review queue.

## Field Mapping Details

The first pass should use deterministic aliases before falling back to observations.

Required mappings:

- `身份` maps to `canonical_profile.identity_role` only when no identity role exists.
- `身份` maps to `current_state.social_position` when a canonical identity role already exists and the extracted value differs.
- `职业` maps to `current_state.occupation`.
- `状态` maps to `current_state.condition`.
- `位置` maps to `current_state.location`.
- `境界` maps to `current_state.cultivation_level`.
- `变化`, `描述`, and `summary` map to `observations[chapter_id]`.

