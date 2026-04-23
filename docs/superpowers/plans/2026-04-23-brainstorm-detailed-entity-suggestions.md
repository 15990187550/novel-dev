# Brainstorm Detailed Entity Suggestions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add workspace-scoped structured suggestion cards so brainstorm and outline optimization can continuously refine characters, factions, locations, artifacts/skills, and relationships without polluting the legacy `setting_docs_draft` pipeline.

**Architecture:** Keep `outline_drafts` as the authority for synopsis/volume snapshots, add a parallel `setting_suggestion_cards` JSON column plus Pydantic schema set for structured suggestions, and update the outline workbench so each optimization round writes both summary highlights and card deltas. Final confirmation stays transactional but now splits entity-like suggestions into pending extractions and resolved relationship suggestions into `EntityRelationship`, while unresolved cards surface as warnings instead of silently failing.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic, pytest, Vue 3, Pinia, Axios, Vitest

---

## File Structure

### Backend Persistence

- Modify: `src/novel_dev/db/models.py`
  - Add `setting_suggestion_cards` JSON column to `BrainstormWorkspace`.
- Create: `migrations/versions/20260423_add_brainstorm_suggestion_cards.py`
  - Backfill existing rows with an empty list.

### Backend Schemas and Services

- Modify: `src/novel_dev/schemas/brainstorm_workspace.py`
  - Add `SettingSuggestionCardPayload`, typed payload variants, workspace response fields, and submit warnings.
- Modify: `src/novel_dev/services/brainstorm_workspace_service.py`
  - Add `merge_suggestion_cards()`, `list_active_suggestion_cards()`, and transactional submit helpers.
- Modify: `src/novel_dev/services/extraction_service.py`
  - Add a mapper from entity-like suggestion cards to `PendingExtractionPayload`.
- Modify: `src/novel_dev/services/outline_workbench_service.py`
  - Produce outline highlights, run a dedicated suggestion update pass, and return per-round card summaries.

### Backend Tests

- Modify: `tests/test_services/test_brainstorm_workspace_service.py`
- Modify: `tests/test_services/test_outline_workbench_service.py`
- Modify: `tests/test_services/test_extraction_service_setting_drafts.py`
- Create: `tests/test_services/test_brainstorm_suggestion_cards.py`

### Frontend

- Modify: `src/novel_dev/web/src/api.js`
  - Accept suggestion cards and submit warnings in workspace payloads.
- Modify: `src/novel_dev/web/src/stores/novel.js`
  - Store suggestion cards, last round summaries, and submit warnings.
- Modify: `src/novel_dev/web/src/views/VolumePlan.vue`
  - Render suggestion highlights, current cards, and submit warnings.
- Create: `src/novel_dev/web/src/components/outline/BrainstormSuggestionCards.vue`
  - List active cards with expand/collapse details and unresolved badges.
- Modify: `src/novel_dev/web/src/views/VolumePlan.test.js`
- Modify: `src/novel_dev/web/src/stores/novel.test.js`
- Create: `src/novel_dev/web/src/components/outline/BrainstormSuggestionCards.test.js`

### Final Verification

- Modify: no additional docs beyond this plan
- Verify with targeted pytest and vitest suites plus one transactional submit flow

---

### Task 1: Add Workspace Suggestion Card Persistence

**Files:**
- Modify: `src/novel_dev/db/models.py:220-227`
- Create: `migrations/versions/20260423_add_brainstorm_suggestion_cards.py`
- Modify: `src/novel_dev/schemas/brainstorm_workspace.py`
- Test: `tests/test_services/test_brainstorm_suggestion_cards.py`

- [ ] **Step 1: Write the failing persistence and schema tests**

```python
import pytest

from novel_dev.repositories.brainstorm_workspace_repo import BrainstormWorkspaceRepository
from novel_dev.schemas.brainstorm_workspace import (
    BrainstormWorkspacePayload,
    SettingSuggestionCardPayload,
)


@pytest.mark.asyncio
async def test_workspace_payload_exposes_suggestion_cards(async_session):
    repo = BrainstormWorkspaceRepository(async_session)
    workspace = await repo.get_or_create("novel_cards")
    workspace.setting_suggestion_cards = [
        {
            "card_id": "card_1",
            "card_type": "character",
            "merge_key": "character:lu-zhao",
            "title": "陆照",
            "summary": "补充主角目标",
            "status": "active",
            "source_outline_refs": ["synopsis"],
            "payload": {"canonical_name": "陆照", "goal": "改命"},
            "display_order": 10,
        }
    ]
    await async_session.flush()

    payload = BrainstormWorkspacePayload.model_validate(
        {
            "workspace_id": workspace.id,
            "novel_id": workspace.novel_id,
            "status": workspace.status,
            "outline_drafts": workspace.outline_drafts,
            "setting_docs_draft": workspace.setting_docs_draft,
            "setting_suggestion_cards": workspace.setting_suggestion_cards,
        }
    )

    assert payload.setting_suggestion_cards[0].merge_key == "character:lu-zhao"


def test_setting_suggestion_card_requires_structured_fields():
    card = SettingSuggestionCardPayload.model_validate(
        {
            "card_id": "card_rel",
            "card_type": "relationship",
            "merge_key": "relationship:lu-zhao:su-qinghan",
            "title": "陆照 / 苏清寒",
            "summary": "互疑转合作",
            "status": "unresolved",
            "source_outline_refs": ["vol_1"],
            "payload": {
                "source_entity_ref": "陆照",
                "target_entity_ref": "苏清寒",
                "relation_type": "亦敌亦友",
                "unresolved_references": ["target_entity_card_key"],
            },
            "display_order": 20,
        }
    )

    assert card.status == "unresolved"
    assert card.payload["relation_type"] == "亦敌亦友"
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `pytest tests/test_services/test_brainstorm_suggestion_cards.py -v`

Expected: FAIL with `ImportError` or schema validation errors because `setting_suggestion_cards` types do not exist yet.

- [ ] **Step 3: Add the new JSON column and migration**

```python
class BrainstormWorkspace(Base):
    __tablename__ = "brainstorm_workspaces"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    novel_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    workspace_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outline_drafts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    setting_docs_draft: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    setting_suggestion_cards: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    last_saved_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
```

```python
def upgrade() -> None:
    op.add_column(
        "brainstorm_workspaces",
        sa.Column("setting_suggestion_cards", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.alter_column("brainstorm_workspaces", "setting_suggestion_cards", server_default=None)


def downgrade() -> None:
    op.drop_column("brainstorm_workspaces", "setting_suggestion_cards")
```

- [ ] **Step 4: Add the schema models**

```python
class SettingSuggestionCardPayload(BaseModel):
    card_id: str
    card_type: str
    merge_key: str
    title: str
    summary: str
    status: str
    source_outline_refs: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    display_order: int = 0


class BrainstormWorkspacePayload(BaseModel):
    workspace_id: str
    novel_id: str
    status: str
    workspace_summary: Optional[str] = None
    outline_drafts: dict[str, dict[str, Any]] = Field(default_factory=dict)
    setting_docs_draft: list[SettingDocDraftPayload] = Field(default_factory=list)
    setting_suggestion_cards: list[SettingSuggestionCardPayload] = Field(default_factory=list)
```

- [ ] **Step 5: Run the new tests**

Run: `pytest tests/test_services/test_brainstorm_suggestion_cards.py -v`

Expected: PASS with `2 passed`

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/db/models.py migrations/versions/20260423_add_brainstorm_suggestion_cards.py src/novel_dev/schemas/brainstorm_workspace.py tests/test_services/test_brainstorm_suggestion_cards.py
git commit -m "feat: add brainstorm suggestion card persistence"
```

---

### Task 2: Add Workspace Merge Logic for Suggestion Cards

**Files:**
- Modify: `src/novel_dev/services/brainstorm_workspace_service.py`
- Modify: `src/novel_dev/schemas/brainstorm_workspace.py`
- Test: `tests/test_services/test_brainstorm_workspace_service.py`

- [ ] **Step 1: Write the failing merge tests**

```python
@pytest.mark.asyncio
async def test_merge_suggestion_cards_upserts_by_merge_key(async_session):
    service = BrainstormWorkspaceService(async_session)

    await service.merge_suggestion_cards(
        "novel_merge_cards",
        [
            {
                "operation": "upsert",
                "card_id": "card_old",
                "card_type": "character",
                "merge_key": "character:lu-zhao",
                "title": "陆照",
                "summary": "主角初版建议",
                "status": "active",
                "source_outline_refs": ["synopsis"],
                "payload": {"canonical_name": "陆照", "goal": "改命"},
                "display_order": 10,
            }
        ],
    )

    cards = await service.merge_suggestion_cards(
        "novel_merge_cards",
        [
            {
                "operation": "upsert",
                "card_id": "card_new",
                "card_type": "character",
                "merge_key": "character:lu-zhao",
                "title": "陆照",
                "summary": "补充主角资源",
                "status": "active",
                "source_outline_refs": ["vol_1"],
                "payload": {"canonical_name": "陆照", "goal": "改命", "resources": "祖传黑刀"},
                "display_order": 10,
            }
        ],
    )

    assert len(cards) == 1
    assert cards[0].summary == "补充主角资源"
    assert cards[0].source_outline_refs == ["synopsis", "vol_1"]
    assert cards[0].payload["resources"] == "祖传黑刀"


@pytest.mark.asyncio
async def test_merge_suggestion_cards_marks_superseded_cards(async_session):
    service = BrainstormWorkspaceService(async_session)

    await service.merge_suggestion_cards(
        "novel_supersede_cards",
        [
            {
                "operation": "upsert",
                "card_id": "card_faction",
                "card_type": "faction",
                "merge_key": "faction:tian-xing-zong",
                "title": "天刑宗",
                "summary": "旧版设定",
                "status": "active",
                "source_outline_refs": ["synopsis"],
                "payload": {"canonical_name": "天刑宗", "position": "铁板一块"},
                "display_order": 20,
            },
            {
                "operation": "supersede",
                "merge_key": "faction:tian-xing-zong",
            },
        ],
    )

    payload = await service.get_workspace_payload("novel_supersede_cards")
    assert payload.setting_suggestion_cards[0].status == "superseded"
```

- [ ] **Step 2: Run the service tests to verify they fail**

Run: `pytest tests/test_services/test_brainstorm_workspace_service.py -k suggestion_cards -v`

Expected: FAIL because `merge_suggestion_cards()` is undefined.

- [ ] **Step 3: Implement typed merge behavior in the service**

```python
async def merge_suggestion_cards(
    self,
    novel_id: str,
    card_updates: list[dict[str, Any]],
) -> list[SettingSuggestionCardPayload]:
    workspace = await self.workspace_repo.get_or_create(novel_id)
    cards = [
        SettingSuggestionCardPayload.model_validate(item).model_dump()
        for item in (workspace.setting_suggestion_cards or [])
    ]

    by_merge_key = {item["merge_key"]: item for item in cards}

    for update in card_updates:
        operation = update.get("operation", "upsert")
        merge_key = update["merge_key"]

        if operation == "supersede":
            if merge_key in by_merge_key:
                by_merge_key[merge_key]["status"] = "superseded"
            continue

        incoming = SettingSuggestionCardPayload.model_validate(update).model_dump()
        existing = by_merge_key.get(merge_key)
        if existing is None:
            by_merge_key[merge_key] = incoming
            continue

        existing["summary"] = incoming["summary"]
        existing["title"] = incoming["title"]
        existing["status"] = incoming["status"]
        existing["payload"] = incoming["payload"]
        existing["display_order"] = incoming["display_order"]
        existing["source_outline_refs"] = sorted(
            set(existing.get("source_outline_refs", [])) | set(incoming.get("source_outline_refs", []))
        )

    merged = sorted(by_merge_key.values(), key=lambda item: (item["display_order"], item["merge_key"]))
    workspace.setting_suggestion_cards = merged
    workspace.last_saved_at = datetime.utcnow()
    await self.session.flush()
    return [SettingSuggestionCardPayload.model_validate(item) for item in merged]
```

- [ ] **Step 4: Expose active-card helpers and workspace serialization**

```python
def _serialize_workspace(self, workspace: Any) -> BrainstormWorkspacePayload:
    return BrainstormWorkspacePayload(
        workspace_id=workspace.id,
        novel_id=workspace.novel_id,
        status=workspace.status,
        workspace_summary=workspace.workspace_summary,
        outline_drafts=dict(workspace.outline_drafts or {}),
        setting_docs_draft=[
            SettingDocDraftPayload.model_validate(item)
            for item in (workspace.setting_docs_draft or [])
        ],
        setting_suggestion_cards=[
            SettingSuggestionCardPayload.model_validate(item)
            for item in (workspace.setting_suggestion_cards or [])
        ],
    )


def list_active_suggestion_cards(self, workspace_payload: BrainstormWorkspacePayload) -> list[SettingSuggestionCardPayload]:
    return [
        card
        for card in workspace_payload.setting_suggestion_cards
        if card.status in {"active", "unresolved"}
    ]
```

- [ ] **Step 5: Run the targeted service tests**

Run: `pytest tests/test_services/test_brainstorm_workspace_service.py -k suggestion_cards -v`

Expected: PASS with the new suggestion-card merge tests green.

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/services/brainstorm_workspace_service.py src/novel_dev/schemas/brainstorm_workspace.py tests/test_services/test_brainstorm_workspace_service.py
git commit -m "feat: add suggestion card merge logic"
```

---

### Task 3: Update Outline Workbench to Produce Highlights and Card Deltas

**Files:**
- Modify: `src/novel_dev/services/outline_workbench_service.py`
- Modify: `tests/test_services/test_outline_workbench_service.py`

- [ ] **Step 1: Write the failing workbench tests**

```python
@pytest.mark.asyncio
async def test_submit_feedback_merges_suggestion_cards_in_brainstorm_mode(async_session, monkeypatch):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_outline_cards",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )

    service = OutlineWorkbenchService(async_session)

    async def fake_optimize_outline(**kwargs):
        return {
            "content": "已更新第一卷卷纲，并细化主要人物与关系。",
            "result_snapshot": {
                "title": "第一卷",
                "summary": "卷一摘要",
                "entity_highlights": {"characters": ["陆照：主角"]},
                "relationship_highlights": ["陆照 / 苏清寒：互疑转合作"],
            },
            "setting_draft_updates": [],
            "setting_suggestion_card_updates": [
                {
                    "operation": "upsert",
                    "card_id": "card_rel",
                    "card_type": "relationship",
                    "merge_key": "relationship:lu-zhao:su-qinghan",
                    "title": "陆照 / 苏清寒",
                    "summary": "互疑转合作",
                    "status": "active",
                    "source_outline_refs": ["vol_1"],
                    "payload": {
                        "source_entity_ref": "陆照",
                        "target_entity_ref": "苏清寒",
                        "relation_type": "亦敌亦友",
                    },
                    "display_order": 30,
                }
            ],
            "setting_update_summary": {"created": 1, "updated": 0, "superseded": 0, "unresolved": 0},
        }

    monkeypatch.setattr(service, "_optimize_outline", fake_optimize_outline)

    response = await service.submit_feedback(
        novel_id="novel_outline_cards",
        outline_type="volume",
        outline_ref="vol_1",
        feedback="强化第一卷主角与女主关系推进",
    )

    assert "细化主要人物与关系" in response.assistant_message.content
    workspace = await service.workspace_service.get_workspace_payload("novel_outline_cards")
    assert workspace.setting_suggestion_cards[0].merge_key == "relationship:lu-zhao:su-qinghan"
    assert response.last_result_snapshot["relationship_highlights"] == ["陆照 / 苏清寒：互疑转合作"]
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run: `pytest tests/test_services/test_outline_workbench_service.py -k suggestion_cards -v`

Expected: FAIL because the response contract and merge call path do not exist yet.

- [ ] **Step 3: Add a dedicated suggestion update pass**

```python
async def _build_suggestion_card_updates(
    self,
    *,
    novel_id: str,
    outline_type: str,
    outline_ref: str,
    feedback: str,
    context_window: OutlineContextWindow,
    result_snapshot: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    workspace = await self.workspace_service.get_workspace_payload(novel_id)
    active_cards = self.workspace_service.list_active_suggestion_cards(workspace)
    update_prompt = (
        "根据新的 outline 快照、已有建议卡、历史摘要与用户最新意见，"
        "返回 suggestion card 增量更新 JSON。"
    )
    updates = await call_and_parse_model(
        "OutlineWorkbenchService",
        "build_suggestion_card_updates",
        update_prompt,
        SuggestionCardUpdateEnvelope,
        novel_id=novel_id,
    )
    return [item.model_dump() for item in updates.cards], updates.summary.model_dump()
```

- [ ] **Step 4: Thread the new updates through `submit_feedback()`**

```python
optimize_result = await self._optimize_outline(
    novel_id=novel_id,
    outline_type=outline_type,
    outline_ref=outline_ref,
    feedback=feedback,
    context_window=context_window,
)

if self._is_brainstorming_phase(state.current_phase):
    if optimize_result.get("result_snapshot"):
        await self.workspace_service.save_outline_draft(
            novel_id=novel_id,
            outline_type=outline_type,
            outline_ref=outline_ref,
            result_snapshot=optimize_result["result_snapshot"],
        )
    if optimize_result.get("setting_suggestion_card_updates"):
        await self.workspace_service.merge_suggestion_cards(
            novel_id=novel_id,
            card_updates=optimize_result["setting_suggestion_card_updates"],
        )
```

- [ ] **Step 5: Run the targeted workbench tests**

Run: `pytest tests/test_services/test_outline_workbench_service.py -k suggestion_cards -v`

Expected: PASS with the new brainstorm merge flow green.

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/services/outline_workbench_service.py tests/test_services/test_outline_workbench_service.py
git commit -m "feat: generate suggestion cards from outline feedback"
```

---

### Task 4: Split Final Confirmation into Entity Suggestions and Relationship Suggestions

**Files:**
- Modify: `src/novel_dev/services/brainstorm_workspace_service.py`
- Modify: `src/novel_dev/services/extraction_service.py`
- Modify: `tests/test_services/test_brainstorm_workspace_service.py`
- Modify: `tests/test_services/test_extraction_service_setting_drafts.py`

- [ ] **Step 1: Write the failing submit tests**

```python
@pytest.mark.asyncio
async def test_submit_workspace_materializes_entity_suggestions_and_relationships(async_session):
    director = NovelDirector(async_session)
    await director.save_checkpoint(
        "novel_submit_cards",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )

    service = BrainstormWorkspaceService(async_session)
    await service.save_outline_draft(
        novel_id="novel_submit_cards",
        outline_type="synopsis",
        outline_ref="synopsis",
        result_snapshot={
            "title": "九霄行",
            "logline": "林风逆势修行",
            "core_conflict": "林风 vs 长老会",
            "themes": ["成长"],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 2,
            "estimated_total_chapters": 200,
            "estimated_total_words": 600000,
        },
    )
    await service.merge_suggestion_cards(
        "novel_submit_cards",
        [
            {
                "operation": "upsert",
                "card_id": "card_char",
                "card_type": "character",
                "merge_key": "character:lin-feng",
                "title": "林风",
                "summary": "主角建议卡",
                "status": "active",
                "source_outline_refs": ["synopsis"],
                "payload": {"canonical_name": "林风", "identity": "外门弟子", "goal": "改命"},
                "display_order": 10,
            },
            {
                "operation": "upsert",
                "card_id": "card_rel",
                "card_type": "relationship",
                "merge_key": "relationship:lin-feng:su-xue",
                "title": "林风 / 苏雪",
                "summary": "盟友关系",
                "status": "active",
                "source_outline_refs": ["vol_1"],
                "payload": {
                    "source_entity_ref": "林风",
                    "target_entity_ref": "苏雪",
                    "relation_type": "盟友",
                    "source_entity_card_key": "character:lin-feng",
                    "target_entity_card_key": "character:su-xue",
                },
                "display_order": 20,
            },
        ],
    )

    result = await service.submit_workspace("novel_submit_cards")

    assert result.pending_setting_count == 1
    assert result.relationship_count == 1
    assert result.submit_warnings == []
```

- [ ] **Step 2: Run the targeted submit tests to verify they fail**

Run: `pytest tests/test_services/test_brainstorm_workspace_service.py -k relationship_count -v`

Expected: FAIL because submit results do not include relationship handling.

- [ ] **Step 3: Add card-to-pending mapper for entity suggestions**

```python
async def build_pending_payload_from_suggestion_card(
    self,
    novel_id: str,
    card: SettingSuggestionCardPayload,
) -> PendingExtractionPayload:
    payload = card.payload
    if card.card_type == "character":
        content = payload.get("identity", "")
        return PendingExtractionPayload(
            source_filename=f"brainstorm-{card.merge_key}.md",
            extraction_type="setting",
            raw_result={"character_profiles": [{**payload, "name": payload["canonical_name"]}]},
            proposed_entities=[
                {
                    "type": "character",
                    "name": payload["canonical_name"],
                    "data": {
                        "identity": payload.get("identity", ""),
                        "goal": payload.get("goal", ""),
                        "resources": payload.get("resources", ""),
                    },
                }
            ],
        )
    raise ValueError(f"Unsupported suggestion card type for pending payload: {card.card_type}")
```

- [ ] **Step 4: Update `submit_workspace()` to split entities and relationships**

```python
active_cards = self.list_active_suggestion_cards(self._serialize_workspace(workspace))
entity_cards = [card for card in active_cards if card.card_type != "relationship"]
relationship_cards = [card for card in active_cards if card.card_type == "relationship"]

pending_payloads = [
    await self.extraction_service.build_pending_payload_from_suggestion_card(novel_id, card)
    for card in entity_cards
]

resolved_relationships, warnings = await self._resolve_relationship_cards(
    novel_id=novel_id,
    cards=relationship_cards,
    active_cards=active_cards,
)
for item in resolved_relationships:
    await self.relationship_repo.upsert(
        source_id=item["source_id"],
        target_id=item["target_id"],
        relation_type=item["relation_type"],
        meta=item["meta"],
        novel_id=novel_id,
    )
```

- [ ] **Step 5: Run the targeted submit and mapper tests**

Run: `pytest tests/test_services/test_brainstorm_workspace_service.py -k relationship_count -v`

Run: `pytest tests/test_services/test_extraction_service_setting_drafts.py -k suggestion_card -v`

Expected: PASS with relationship counts and warning behavior verified.

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/services/brainstorm_workspace_service.py src/novel_dev/services/extraction_service.py tests/test_services/test_brainstorm_workspace_service.py tests/test_services/test_extraction_service_setting_drafts.py
git commit -m "feat: submit brainstorm suggestion cards transactionally"
```

---

### Task 5: Render Suggestion Cards and Submit Warnings in the Frontend

**Files:**
- Modify: `src/novel_dev/web/src/api.js`
- Modify: `src/novel_dev/web/src/stores/novel.js`
- Modify: `src/novel_dev/web/src/views/VolumePlan.vue`
- Create: `src/novel_dev/web/src/components/outline/BrainstormSuggestionCards.vue`
- Create: `src/novel_dev/web/src/components/outline/BrainstormSuggestionCards.test.js`
- Modify: `src/novel_dev/web/src/stores/novel.test.js`
- Modify: `src/novel_dev/web/src/views/VolumePlan.test.js`

- [ ] **Step 1: Write the failing frontend tests**

```javascript
it('renders active suggestion cards and unresolved warnings in brainstorm mode', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useNovelStore()
  store.novelId = 'novel-1'
  store.novelState.current_phase = 'brainstorming'
  store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()
  store.brainstormWorkspace.data = {
    workspace_id: 'ws-1',
    novel_id: 'novel-1',
    status: 'active',
    outline_drafts: { 'synopsis:synopsis': { title: '总纲' } },
    setting_docs_draft: [],
    setting_suggestion_cards: [
      {
        card_id: 'card_rel',
        card_type: 'relationship',
        merge_key: 'relationship:lu-zhao:su-qinghan',
        title: '陆照 / 苏清寒',
        summary: '互疑转合作',
        status: 'unresolved',
        source_outline_refs: ['vol_1'],
        payload: { relation_type: '亦敌亦友' },
        display_order: 20,
      },
    ],
    submit_warnings: ['1 条关系建议待解析实体引用'],
  }

  const wrapper = mount(VolumePlan, {
    global: {
      plugins: [pinia],
      stubs: {
        OutlineSidebar: true,
        OutlineDetailPanel: true,
        OutlineConversation: true,
      },
    },
  })

  await flushPromises()
  expect(wrapper.text()).toContain('建议卡')
  expect(wrapper.text()).toContain('陆照 / 苏清寒')
  expect(wrapper.text()).toContain('待解析')
  expect(wrapper.text()).toContain('1 条关系建议待解析实体引用')
})
```

- [ ] **Step 2: Run the frontend tests to verify they fail**

Run: `cd src/novel_dev/web && npm run test -- VolumePlan.test.js BrainstormSuggestionCards.test.js`

Expected: FAIL because the component and store fields do not exist yet.

- [ ] **Step 3: Add API/store fields for suggestion cards**

```javascript
function createBrainstormWorkspaceState() {
  return {
    state: 'idle',
    error: '',
    data: null,
    submitting: false,
    requestToken: 0,
    lastRoundSummary: null,
  }
}

// after submit feedback refresh
if (workspace) {
  this.brainstormWorkspace.data = workspace
  this.brainstormWorkspace.lastRoundSummary = response.setting_update_summary || null
}
```

```javascript
export const getBrainstormWorkspace = (id) =>
  api.get(`/novels/${id}/brainstorm_workspace`).then((r) => r.data)
```

- [ ] **Step 4: Render the new card list component in `VolumePlan.vue`**

```vue
<BrainstormSuggestionCards
  v-if="isBrainstormMode"
  :cards="store.brainstormWorkspace.data?.setting_suggestion_cards || []"
  :warnings="store.brainstormWorkspace.data?.submit_warnings || []"
  :last-round-summary="store.brainstormWorkspace.lastRoundSummary"
/>
```

```vue
<template>
  <section class="rounded-3xl border border-gray-200 bg-white p-5">
    <div class="text-xs font-medium uppercase tracking-[0.24em] text-gray-400">Suggestion Cards</div>
    <div v-if="warnings.length" class="mt-3 rounded-2xl bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <div v-for="warning in warnings" :key="warning">{{ warning }}</div>
    </div>
    <article v-for="card in visibleCards" :key="card.card_id" class="mt-4 rounded-2xl border border-gray-200 px-4 py-4">
      <div class="flex items-center justify-between">
        <div>
          <div class="font-semibold text-gray-900">{{ card.title }}</div>
          <div class="text-sm text-gray-500">{{ card.summary }}</div>
        </div>
        <span class="rounded-full bg-gray-100 px-3 py-1 text-xs">{{ statusLabel(card.status) }}</span>
      </div>
    </article>
  </section>
</template>
```

- [ ] **Step 5: Run the frontend tests**

Run: `cd src/novel_dev/web && npm run test -- VolumePlan.test.js BrainstormSuggestionCards.test.js`

Expected: PASS with the new brainstorm card UI covered.

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/web/src/api.js src/novel_dev/web/src/stores/novel.js src/novel_dev/web/src/views/VolumePlan.vue src/novel_dev/web/src/components/outline/BrainstormSuggestionCards.vue src/novel_dev/web/src/components/outline/BrainstormSuggestionCards.test.js src/novel_dev/web/src/stores/novel.test.js src/novel_dev/web/src/views/VolumePlan.test.js
git commit -m "feat: show brainstorm suggestion cards in workbench"
```

---

### Task 6: Run Focused Verification Before Execution Handoff

**Files:**
- Modify: no source files
- Test: `tests/test_services/test_brainstorm_suggestion_cards.py`
- Test: `tests/test_services/test_brainstorm_workspace_service.py`
- Test: `tests/test_services/test_outline_workbench_service.py`
- Test: `tests/test_services/test_extraction_service_setting_drafts.py`
- Test: `src/novel_dev/web/src/components/outline/BrainstormSuggestionCards.test.js`
- Test: `src/novel_dev/web/src/views/VolumePlan.test.js`

- [ ] **Step 1: Run backend suggestion-card tests**

Run: `pytest tests/test_services/test_brainstorm_suggestion_cards.py tests/test_services/test_brainstorm_workspace_service.py -v`

Expected: PASS with all suggestion-card and submit-flow tests green.

- [ ] **Step 2: Run backend outline workbench tests**

Run: `pytest tests/test_services/test_outline_workbench_service.py -k "suggestion_cards or brainstorm" -v`

Expected: PASS with brainstorm workbench integration tests green.

- [ ] **Step 3: Run backend extraction mapper tests**

Run: `pytest tests/test_services/test_extraction_service_setting_drafts.py -k "suggestion_card or pending_payload" -v`

Expected: PASS with card-to-pending conversion tests green.

- [ ] **Step 4: Run frontend tests**

Run: `cd src/novel_dev/web && npm run test -- BrainstormSuggestionCards.test.js VolumePlan.test.js`

Expected: PASS with the new card list and warning rendering covered.

- [ ] **Step 5: Run a final mixed smoke command**

Run: `pytest tests/test_services/test_brainstorm_workspace_service.py::test_submit_workspace_materializes_entity_suggestions_and_relationships -v`

Expected: PASS with `1 passed`

- [ ] **Step 6: Commit verification-only if any harness fixes were needed**

```bash
git add -A
git commit -m "test: cover brainstorm suggestion card flow"
```

---

## Self-Review

### Spec Coverage

- `outline_drafts` 只保留摘要层：Task 3 covers `entity_highlights` and `relationship_highlights`.
- 新增 `setting_suggestion_cards`：Tasks 1 and 2.
- 每轮联动生成详细设定建议：Task 3.
- 最终确认时实体建议和关系建议分渠道提交：Task 4.
- 前端展示建议卡、状态和 warning：Task 5.
- 渐进落地与 focused verification：Task 6.

No uncovered spec requirement remains.

### Placeholder Scan

- No `TODO`, `TBD`, or “implement later” placeholders remain.
- Each task includes exact file paths, explicit tests, commands, and code snippets.

### Type Consistency

- JSON column name is consistently `setting_suggestion_cards`.
- Merge API is consistently `merge_suggestion_cards()`.
- Relationship card identity is consistently `relationship:<source-ref>:<target-ref>`.
- Submit response fields are consistently `relationship_count` and `submit_warnings`.

