# Novel Genre Template System Design

Date: 2026-05-15
Status: Draft for user review

## Purpose

This design adds first-level and second-level novel categories to `novel-dev`, then uses the selected category to drive type-specific prompt rules and quality-gate behavior across the formal novel generation workflow.

The system should support common web-novel categories such as 玄幻、仙侠、都市、科幻、悬疑、历史、奇幻, with second-level categories such as 玄幻/诸天文 and 都市/职场商战. A novel must choose both a first-level and second-level category when it is created. Each selected category resolves to a reusable template that affects generation prompts and quality-left-shift checks.

The goal is to make genre behavior explicit, configurable, and testable without scattering hardcoded category branches through individual agents.

## Confirmed Product Decisions

- Use built-in default categories and templates, with database overrides.
- Compose templates in three layers: global base template, first-level category template, second-level category template.
- First phase affects agent prompts and quality-gate or validation parameters.
- First phase does not change the pipeline phase order or enable per-genre workflow engines.
- First phase ships a core high-frequency category set and leaves room to add more categories later.
- Creating a novel requires both first-level and second-level category selection.
- Historical novels without category data fall back to 通用/未分类.

## Scope

In scope:

- Add a category taxonomy for first-level and second-level novel categories.
- Add genre template storage with built-in defaults and database overrides.
- Store selected category metadata on each novel.
- Add a template resolution service with deterministic merge rules.
- Inject resolved template blocks into key agent prompts.
- Feed resolved quality configuration into prose hygiene and quality gates.
- Update create-novel API, frontend creation flow, test scripts, and reports.
- Add tests for category validation, template merging, prompt injection, quality behavior, and historical compatibility.

Out of scope:

- A full backend UI for editing templates.
- Per-genre changes to pipeline phase order.
- Per-genre agent selection or workflow branching.
- Using category templates to inject concrete story content, names, places, plot events, or external IP facts.
- Replacing existing style profiles, source-material constraints, or user-provided settings.

## Chosen Approach

Use a category domain model plus a centralized `GenreTemplateService`.

Individual agents should not contain logic such as `if genre == "xuanhuan"`. Instead, they ask the service for a resolved template:

```python
template = await genre_template_service.resolve(
    novel_id=novel_id,
    agent_name="WriterAgent",
    task_name="generate_beat",
)
```

The returned template includes the selected genre metadata, merged prompt blocks, and merged quality configuration. Agents only consume those generic blocks.

Rejected alternatives:

- Prompt-only configuration: too weak because quality gates would still apply generic assumptions.
- Hardcoding category branches in agents: fast initially, but untestable and hard to maintain.
- Full genre workflow engine: powerful but too much scope for the first phase and risky for the current formal-generation workflow.

## Category Model

Add `novel_categories`:

```text
id
slug
name
level
parent_slug
description
sort_order
enabled
source
created_at
updated_at
```

Rules:

- `level=1` rows are first-level categories.
- `level=2` rows must have `parent_slug`.
- `slug` is stable and used by API payloads, config files, and templates.
- `enabled=false` categories are hidden from creation and rejected by create-novel validation.
- Built-in defaults are seeded from repository config.
- Database rows may override display metadata and enabled status.

First-phase built-in categories:

```text
通用: 未分类
玄幻: 东方玄幻、异世大陆、诸天文、系统流
仙侠: 古典仙侠、修真文明、凡人流、洪荒流
都市: 都市生活、都市异能、职场商战、都市修真
科幻: 未来世界、星际文明、末世危机、赛博朋克
悬疑: 推理探案、民俗悬疑、无限流、心理悬疑
历史: 架空历史、穿越历史、权谋争霸、历史军事
奇幻: 西方奇幻、史诗奇幻、魔法学院、异界冒险
```

## Template Model

Add `novel_genre_templates`:

```text
id
scope
category_slug
parent_slug
agent_name
task_name
prompt_blocks
quality_config
merge_policy
enabled
version
source
created_at
updated_at
```

Field rules:

- `scope` is `global`, `primary`, or `secondary`.
- `category_slug` is empty only for `global`.
- `agent_name="*"` applies to all agents unless a more specific template exists.
- `task_name="*"` applies to all tasks unless a more specific template exists.
- `prompt_blocks` is JSON grouped by semantic block names.
- `quality_config` is JSON consumed by quality services.
- `merge_policy` can mark specific prompt blocks as `append` or `replace`.
- Built-in templates live in repository config and are used when no database override exists.

Prompt block names:

```text
role_rules
source_rules
setting_rules
structure_rules
prose_rules
forbidden_rules
quality_rules
output_rules
```

Templates may describe type-level rules only. They must not include concrete story facts, character names, place names, sect names, plot fragments, or one-off fallback content.

## Novel Metadata

The selected category is stored in `NovelState.checkpoint_data`:

```json
{
  "genre": {
    "primary_slug": "xuanhuan",
    "primary_name": "玄幻",
    "secondary_slug": "zhutian",
    "secondary_name": "诸天文"
  }
}
```

This avoids an immediate schema migration on `novel_state` columns while keeping current state serialization compatible. If later filtering or analytics need indexed category fields, add dedicated columns in a separate change.

Historical novels without `genre` resolve to:

```json
{
  "primary_slug": "general",
  "primary_name": "通用",
  "secondary_slug": "uncategorized",
  "secondary_name": "未分类"
}
```

## Template Resolution

Resolution order:

```text
global built-in
-> global database override
-> first-level built-in
-> first-level database override
-> second-level built-in
-> second-level database override
-> runtime context
```

Lookup specificity inside each layer:

```text
agent_name="*", task_name="*"
agent_name=current, task_name="*"
agent_name="*", task_name=current
agent_name=current, task_name=current
```

Merge rules:

- `prompt_blocks` append by default.
- A block marked `replace` replaces the same block from previous layers.
- Lists are appended and de-duplicated while preserving order.
- Dictionaries are deep-merged.
- Scalars such as booleans, numbers, and strings are overridden by later layers.
- Disabled templates are ignored.
- Missing category-specific templates fall back to global and record a `genre_template_missing` warning.
- Invalid template schema is a hard error because it can corrupt every generation step.

## Agent Integration

First batch, required for the formal generation path:

- `BrainstormAgent`: type-level story structure, selling points, long-horizon suspense rules.
- `SettingWorkbenchAgent`: type-specific setting field priorities and source-grounded generation rules.
- `VolumePlannerAgent`: volume structure, chapter rhythm, hook patterns, and review focus.
- `WriterAgent`: prose rules, forbidden drift, type-specific readability constraints.
- `FastReviewAgent`: type consistency and quality-gate behavior.
- `ProseHygieneService` and `QualityGateService`: context-aware drift and blocking rules.

Second batch:

- `CriticAgent`: type-specific scoring weights and review language.
- `EditorAgent`: type-specific repair boundaries so edits do not shift genre.
- `ContextAgent`: type-specific context retrieval priorities and guardrails.

Third batch:

- `LibrarianAgent`: type-relevant world-state extraction fields.
- `EntityClassificationService`: category-aware entity grouping where useful.
- `ArchiveService`: optional type-specific archive sections.

Prompt construction pattern:

```text
agent base prompt
+ resolved global genre blocks
+ resolved primary genre blocks
+ resolved secondary genre blocks
+ source material / current chapter context
+ output schema or formatting constraints
```

Output schema constraints remain closest to the final prompt so genre text cannot weaken structured-output requirements.

## Quality Configuration

First-phase `quality_config` supports:

```json
{
  "modern_terms_policy": "allow|block|contextual",
  "foreign_terms_policy": "allow|block|contextual",
  "required_setting_dimensions": ["power_system", "social_order"],
  "forbidden_drift_patterns": ["互联网黑话"],
  "dimension_weights": {
    "setting_consistency": 1.2,
    "plot_cohesion": 1.1,
    "readability": 1.0
  },
  "blocking_rules": {
    "type_drift": true,
    "source_conflict": true,
    "unresolved_required_setting": true
  }
}
```

Expected behavior examples:

- 玄幻/诸天文 strengthens world-rule compatibility, power-system boundaries, and cross-world information isolation.
- 玄幻/诸天文 blocks unauthorized modern workplace or internet drift.
- 都市/职场商战 allows company, contract, law, financing, and internet vocabulary.
- 都市/职场商战 blocks sect, cultivation-realm, and spiritual-energy assumptions unless the selected second-level category allows them.
- 悬疑/推理探案 strengthens clue fairness, suspect progression, information-disclosure boundaries, and blocks unforeshadowed supernatural solutions unless the template allows them.

Quality checks should move left where possible:

- Setting generation should require type-relevant setting dimensions before outline generation.
- Volume planning should surface type-drift and missing type obligations before chapter drafting.
- Writer prompts should carry forbidden drift and required type rules before prose is generated.
- Fast review remains the final gate, not the first place type mismatch is discovered.

## API Design

Add:

```text
GET /api/novel-categories
```

Returns enabled category tree:

```json
[
  {
    "slug": "xuanhuan",
    "name": "玄幻",
    "children": [
      {"slug": "zhutian", "name": "诸天文"}
    ]
  }
]
```

Update:

```text
POST /api/novels
```

Request:

```json
{
  "title": "小说标题",
  "primary_category_slug": "xuanhuan",
  "secondary_category_slug": "zhutian"
}
```

Validation:

- `title` is required and non-empty.
- `primary_category_slug` is required and must be an enabled first-level category.
- `secondary_category_slug` is required and must be an enabled second-level category under the selected first-level category.
- Missing or mismatched category data returns `422`.

State response includes:

```json
{
  "genre": {
    "primary_slug": "xuanhuan",
    "primary_name": "玄幻",
    "secondary_slug": "zhutian",
    "secondary_name": "诸天文"
  }
}
```

## Frontend Flow

The create-novel dialog adds two required selectors:

```text
标题
一级分类
二级分类
创建
```

The frontend loads categories from `GET /api/novel-categories`, then filters second-level options by selected first-level category. The create button is disabled until title, first-level category, and second-level category are valid.

Novel list and dashboard state should display the selected category as `一级 / 二级`, falling back to `通用 / 未分类` for historical novels.

## Migration and Compatibility

Migration steps:

- Create `novel_categories`.
- Create `novel_genre_templates`.
- Seed built-in categories and built-in templates.
- Keep historical novels readable with runtime fallback.
- Optionally backfill historical checkpoint data to `通用/未分类`.

Formal workflow scripts must pass category fields when creating novels. Reports should include:

- selected first-level and second-level category,
- resolved template layer count,
- missing-template warnings,
- quality-config summary,
- type-drift findings.

If imported source materials appear to conflict with the selected category, the system should not silently change the category. It should surface a setting or quality preflight warning and continue only if the user or test configuration accepts that selection.

## Testing Plan

Category and API tests:

- Return category tree.
- Create novel requires first-level and second-level category.
- Reject disabled first-level category.
- Reject disabled second-level category.
- Reject second-level category not belonging to selected first-level category.
- Historical novel without `genre` resolves to `通用/未分类`.

Template tests:

- Merge global, first-level, and second-level templates in order.
- Database overrides beat built-in defaults.
- Specific agent/task templates beat wildcard templates.
- Lists de-duplicate while preserving order.
- Dictionaries deep-merge correctly.
- `replace` block replaces previous block content.
- Missing category template falls back to global and logs warning.
- Invalid template schema fails fast.
- Production templates reject concrete story content, names, places, and plot fragments.

Agent prompt tests:

- `BrainstormAgent` receives type structure rules.
- `SettingWorkbenchAgent` receives type setting priorities.
- `VolumePlannerAgent` receives type rhythm and hook rules.
- `WriterAgent` receives prose and forbidden-drift rules.
- `FastReviewAgent` receives type quality configuration.
- 玄幻/诸天文 does not receive 都市 modern-term allowances.
- 都市/职场商战 allows modern workplace vocabulary.

Quality tests:

- 玄幻 text with unauthorized internet or workplace drift blocks.
- 都市 text with company, contract, law, or internet vocabulary does not block.
- 悬疑 template strengthens clue fairness checks.
- 诸天文 template strengthens cross-world boundary checks.
- Quality behavior uses resolved template config rather than hardcoded agent branches.

Workflow tests:

- Test runner creates formal novels with category fields.
- Reports include category and template resolution evidence.
- Existing novels without category still load and can continue.
- Missing category-specific template does not crash generation.

## Implementation Order

1. Add category and template config files plus schema validation.
2. Add database models, repositories, and seed logic.
3. Add create-novel validation and category-tree API.
4. Update frontend creation dialog and state display.
5. Add `GenreTemplateService` and merge tests.
6. Integrate first-batch agents and quality services.
7. Update test scripts and real-run reports.
8. Add cross-category fixture tests.

## Generalization Rule

Formal workflow templates must remain genre-general and source-driven. They may encode type expectations such as "玄幻 usually needs a power-system boundary" or "悬疑 needs fair clue disclosure", but they must not encode a specific novel's characters, places, plot events, one-off fallback paragraphs, or external-IP facts.

This rule should be added to `AGENTS.md` alongside the existing formal workflow generalization rules.
