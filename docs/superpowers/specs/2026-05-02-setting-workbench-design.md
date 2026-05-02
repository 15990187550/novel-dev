# Setting Workbench Design

**Date:** 2026-05-02
**Scope:** Add a first-class setting workbench that combines existing setting import with AI-assisted setting generation and review.

## Goals

Users should be able to start from either existing material or only an initial idea:

- If they already have files, they use **导入已有资料**.
- If they only have a rough idea, they use **从想法生成设定**.

Both paths produce unified **审核记录**. AI-generated output must not write directly into formal setting cards, entities, or relationships. Formal data is updated only after user review.

## Non-Goals

- Do not reuse **设定建议卡** for the setting workbench generation path.
- Do not directly write AI-generated cards/entities/relationships into the entity encyclopedia.
- Do not replace the existing outline brainstorm suggestion-card flow; that remains scoped to outline conversations.
- Do not hard-delete approved entities or setting cards by default.

## Product Model

The navigation gets a first-class page named **设定工作台**.

The workbench landing page has two primary entries:

- **导入已有资料**: keeps the existing upload/parse/review flow, but the downstream list is renamed from **导入审核记录** to **审核记录**.
- **从想法生成设定**: creates or resumes persistent AI generation sessions.

AI generation sessions are persistent. A user may have multiple sessions per novel, such as:

- 修炼体系补全
- 主角阵营设定
- 法宝与秘境设定

Each session keeps its own clarification context, generated review batches, approved setting cards, approved entities, and approved relationships.

## AI Generation Flow

The generation path reuses the total-outline generation pattern: multi-round clarification before producing durable review output.

1. The user creates a setting generation session and enters an initial idea.
2. The backend evaluates whether the setting requirements are clear enough.
3. If information is insufficient, the AI returns clarification questions instead of writing review records.
4. The user answers; the session keeps messages, round count, target categories, and conversation summary.
5. When information is sufficient, or when the clarification round limit is reached, the session becomes ready to generate.
6. The user clicks **生成待审核设定**.
7. The backend creates one **审核记录** batch containing setting-card, entity, and relationship changes.

Category selection is flexible:

- By default, AI attempts a broad setting expansion: characters, factions, locations, cultivation systems, treasures, heavenly materials, items, rules, and other domain-specific setting types.
- If the user limits scope in the input, such as "只生成势力和修炼体系", the session generates only those categories.

Generated output is a review batch, not suggestion cards and not formal data.

## Review Records

The existing **导入审核记录** surface becomes **审核记录**. It covers:

- Import-generated review batches.
- AI setting-workbench review batches.
- Future AI optimization batches for existing approved settings.

The review list summary should include setting-card changes as well as entity changes. Example:

`新增 3 张设定卡片，81 个实体，116 个关系变更`

Review detail is grouped into:

- **设定卡片变更**: create/update/delete setting cards such as 修炼体系、势力格局、地点设定.
- **实体变更**: create/update/delete characters, factions, locations, items, cultivation concepts, treasures, materials, and other entities.
- **关系变更**: create/update/delete relationships such as master-disciple, faction membership, possession, hostility, cultivation source, family, and direct narrative relationships.

List-level actions default to whole-batch approve/reject. Detail view allows partial approval:

- approve one change
- reject one change
- edit then approve one change
- approve or reject all remaining changes

## Change Semantics

Each review change has a target type and an operation:

- Target types: `setting_card`, `entity`, `relationship`
- Operations: `create`, `update`, `delete`

Each change stores enough data for review:

- target identity when updating or deleting existing data
- before snapshot for update/delete
- after snapshot for create/update
- source AI session and source review batch when applicable
- duplicate/conflict hints when the generated change may overlap existing data

Deletion is conservative:

- Setting card deletion marks the card as discarded or archived by default.
- Entity deletion soft-deletes or archives the entity when relationships or history exist.
- Relationship deletion follows the existing relationship soft-delete/upsert strategy.

## AI Source Marking And Backlinks

AI-generated approved content must be visibly marked and traceable.

Formal setting cards, entities, and relationships created or updated from AI review batches store:

- `source_type = ai`
- `source_session_id`
- `source_review_batch_id`
- `source_review_change_id`

The UI exposes backlinks:

- Setting card title area shows an `AI` badge, optionally `AI · 修炼体系补全`.
- Entity detail shows `AI 生成 · 查看会话`.
- Relationship detail or graph edge detail shows `AI 生成 · 查看会话`.
- Review batch detail shows `来源会话`.

Clicking the badge opens **设定工作台** at the source AI session and focuses the relevant generated item or review change.

## Continuing Optimization

Approved AI-generated content can be optimized from its source session.

From a setting card, entity, relationship, or review batch, the user can jump back to the AI session and submit requests such as:

- 把这个修炼体系改成十二境
- 这个势力不够有压迫感，重写
- 删除这个实体相关的设定
- 把这个人物和主角改成师徒关系

The optimization context includes the current object plus directly related entities and relationships by default. It does not load the entire novel unless the user explicitly asks for broader context.

Optimization creates a new review batch. It may contain create, update, and delete changes. It never mutates formal data directly.

## Backend Structure

Add dedicated setting-workbench persistence while reusing the existing review/import application path where possible.

### `setting_generation_sessions`

Persistent AI sessions per novel.

Core fields:

- `id`
- `novel_id`
- `title`
- `status`
- `target_categories`
- `clarification_round`
- `conversation_summary`
- `created_at`
- `updated_at`

Suggested statuses:

- `clarifying`
- `ready_to_generate`
- `generating`
- `generated`
- `failed`
- `archived`

### `setting_generation_messages`

Stores session conversation messages.

Core fields:

- `id`
- `session_id`
- `role`
- `content`
- `metadata`
- `created_at`

Roles include user, assistant, and system.

### `setting_review_batches`

Unified review record batch.

Core fields:

- `id`
- `novel_id`
- `source_type`
- `source_file`
- `source_session_id`
- `status`
- `summary`
- `created_at`
- `updated_at`

`source_type` includes `import` and `ai_session`.

Statuses:

- `pending`
- `partially_approved`
- `approved`
- `rejected`
- `superseded`
- `failed`

### `setting_review_changes`

One reviewable change inside a batch.

Core fields:

- `id`
- `batch_id`
- `target_type`
- `operation`
- `target_id`
- `status`
- `before_snapshot`
- `after_snapshot`
- `conflict_hints`
- `source_session_id`
- `created_at`
- `updated_at`

Statuses:

- `pending`
- `approved`
- `rejected`
- `edited_approved`
- `failed`

## Frontend Structure

### Setting Workbench Landing

The landing view shows:

- entry card: **导入已有资料**
- entry card: **从想法生成设定**
- recent review records
- recent AI setting sessions

### AI Session View

Layout:

- left: session list
- right: selected session conversation and generation controls

Controls and labels:

- input placeholder focuses on describing the setting idea or desired optimization
- clarification-stage button: **发送回答**
- ready-stage button: **生成待审核设定**
- session status chip: 澄清中 / 可生成 / 生成中 / 已生成 / 失败

The session view also shows:

- target categories
- generated review batches
- approved output linked to the session
- focused source object when opened from an `AI` badge

### Review Record List And Detail

Rename **导入审核记录** to **审核记录**.

List rows show:

- source: import file or AI session title
- type: 导入 / AI
- status
- summary including setting cards, entities, and relationships
- created time
- actions

Detail page groups changes by setting cards, entities, and relationships, and supports whole-batch and per-change review.

### AI Badges

Setting cards, entity detail panels, and relationship details display AI source badges when `source_type = ai`.

The badge is clickable and routes to:

`设定工作台 -> AI 会话 -> 对应审核记录/变更项`

## Error Handling

- Clarification LLM failure keeps the user message and current round; user can retry.
- Generation failure does not create partial approved data. If a review batch exists, it is marked `failed` with error details.
- Applying review changes is per-change. Successful changes remain approved; failed changes are marked `failed`; the batch becomes `partially_approved` or `failed` based on result.
- Duplicate entities are surfaced as conflict hints in review detail.
- Delete operations involving referenced data become archive/discard operations unless explicitly safe.
- Update operations show before/after diffs.

## Testing

Backend coverage:

- create setting generation session
- clarification returns questions without creating review records
- ready generation creates one review batch
- review batch contains setting-card, entity, and relationship changes
- whole-batch approval writes formal data and AI source fields
- partial approval applies only selected changes
- edit-then-approve applies edited snapshots
- source object optimization includes current object and direct related entities/relationships
- delete changes use archive/soft-delete behavior for referenced data
- import-generated review records still work under the unified review record model

Frontend coverage:

- setting workbench landing shows both entry cards
- AI session list and session selection work
- clarification messages and ready-to-generate state render correctly
- generation creates or links a review batch
- review list title is **审核记录**
- review detail shows setting-card, entity, and relationship sections
- whole-batch and per-change review controls update state correctly
- AI badges route to the source session and focused review change

## Open Implementation Notes

- Existing pending extraction structures may be adaptable, but the implementation should verify whether they can represent setting-card changes and update/delete operations cleanly. If not, add the explicit review batch/change tables described here.
- Existing outline brainstorm suggestion-card code should remain separate. The workbench AI generation path should not produce suggestion cards.
- Existing entity and relationship repositories already have duplicate and soft-delete concerns; implementation should reuse those policies instead of adding independent deletion behavior.
