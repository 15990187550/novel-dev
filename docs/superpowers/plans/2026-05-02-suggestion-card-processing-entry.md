# Suggestion Card Processing Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a complete processing entry for brainstorm suggestion cards, with smart action hints, safe single-card state changes, pending-setting conversion, and UI actions that only fill the conversation input until the user sends.

**Architecture:** Keep suggestion cards inside `BrainstormWorkspace`; do not add tables. The backend owns card action classification and mutation rules, and the frontend renders those hints, opens a detail drawer, and delegates mutations through the store. Conversation refill is a local UI action that calls `OutlineConversation.setDraft()` only.

**Tech Stack:** FastAPI, SQLAlchemy async session, Pydantic v2, pytest, Vue 3 Composition API, Pinia, Vitest, Element Plus already present in the app.

---

## File Structure

- Modify `src/novel_dev/schemas/brainstorm_workspace.py`: add action-hint, update request, pending summary, and update response schemas.
- Modify `src/novel_dev/services/brainstorm_workspace_service.py`: add action-hint classification, serialize hints into cards, and implement `update_suggestion_card()`.
- Modify `src/novel_dev/api/routes.py`: add PATCH route for single-card actions.
- Modify `tests/test_services/test_brainstorm_workspace_service.py`: cover backend classification and mutation rules.
- Modify `tests/test_api/test_brainstorm_workspace_routes.py`: cover route success and error mapping.
- Modify `src/novel_dev/web/src/api.js`: add `updateBrainstormSuggestionCard()`.
- Modify `src/novel_dev/web/src/stores/novel.js`: add update action and loading state.
- Modify `src/novel_dev/web/src/stores/novel.test.js`: cover store success and failure behavior.
- Modify `src/novel_dev/web/src/components/outline/BrainstormSuggestionCards.vue`: render smart primary actions, detail drawer, history section, and emit events.
- Modify `src/novel_dev/web/src/components/outline/BrainstormSuggestionCards.test.js`: cover card UI behavior.
- Modify `src/novel_dev/web/src/views/VolumePlan.vue`: wire component events to store and `OutlineConversation.setDraft()`.
- Modify `src/novel_dev/web/src/views/VolumePlan.test.js`: verify refill does not submit feedback and processing calls the store.

---

### Task 1: Backend Schemas And Action Hints

**Files:**
- Modify: `src/novel_dev/schemas/brainstorm_workspace.py`
- Modify: `src/novel_dev/services/brainstorm_workspace_service.py`
- Test: `tests/test_services/test_brainstorm_workspace_service.py`

- [ ] **Step 1: Write failing action-hint tests**

Add these tests near the other suggestion-card tests in `tests/test_services/test_brainstorm_workspace_service.py`:

```python
from novel_dev.schemas.brainstorm_workspace import SettingSuggestionCardPayload


def _suggestion_card(
    *,
    card_type: str,
    payload: dict,
    summary: str = "建议补充设定。",
    status: str = "active",
) -> SettingSuggestionCardPayload:
    return SettingSuggestionCardPayload.model_validate(
        {
            "card_id": f"card_{card_type}",
            "card_type": card_type,
            "merge_key": f"{card_type}:sample",
            "title": "示例建议卡",
            "summary": summary,
            "status": status,
            "source_outline_refs": ["synopsis"],
            "payload": payload,
            "display_order": 1,
        }
    )


@pytest.mark.asyncio
async def test_suggestion_card_action_hint_recommends_pending_for_named_entity(async_session):
    service = BrainstormWorkspaceService(async_session)
    hint = service.build_suggestion_card_action_hint(
        _suggestion_card(
            card_type="character",
            payload={"canonical_name": "林风", "goal": "逆天改命"},
        )
    )

    assert hint.recommended_action == "submit_to_pending"
    assert hint.primary_label == "转设定"
    assert "submit_to_pending" in hint.available_actions
    assert "可转为待审批设定" in hint.reason


@pytest.mark.asyncio
async def test_suggestion_card_action_hint_keeps_outline_revision_in_conversation(async_session):
    service = BrainstormWorkspaceService(async_session)
    hint = service.build_suggestion_card_action_hint(
        _suggestion_card(
            card_type="revision",
            payload={"focus": "结尾钩子"},
            summary="结尾钩子需要从开放解读改成主题闭环。",
        )
    )

    assert hint.recommended_action == "continue_outline_feedback"
    assert hint.primary_label == "继续优化"
    assert "fill_conversation" in hint.available_actions
    assert "submit_to_pending" not in hint.available_actions


@pytest.mark.asyncio
async def test_suggestion_card_action_hint_requests_more_info_for_sparse_entity(async_session):
    service = BrainstormWorkspaceService(async_session)
    hint = service.build_suggestion_card_action_hint(
        _suggestion_card(card_type="character", payload={}, summary="角色动机不足。")
    )

    assert hint.recommended_action == "request_more_info"
    assert hint.primary_label == "补充信息"
    assert "fill_conversation" in hint.available_actions
    assert "submit_to_pending" not in hint.available_actions


@pytest.mark.asyncio
async def test_suggestion_card_action_hint_does_not_submit_relationship_cards(async_session):
    service = BrainstormWorkspaceService(async_session)
    hint = service.build_suggestion_card_action_hint(
        _suggestion_card(
            card_type="relationship",
            payload={"source_entity_ref": "林风", "target_entity_ref": "苏雪"},
            summary="林风与苏雪的盟友关系需要明确。",
        )
    )

    assert hint.recommended_action == "continue_outline_feedback"
    assert hint.primary_label == "继续优化"
    assert "submit_to_pending" not in hint.available_actions
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src pytest tests/test_services/test_brainstorm_workspace_service.py -k "suggestion_card_action_hint" -q
```

Expected: fails because `SettingSuggestionCardPayload.action_hint` and `BrainstormWorkspaceService.build_suggestion_card_action_hint()` do not exist.

- [ ] **Step 3: Add schema models**

In `src/novel_dev/schemas/brainstorm_workspace.py`, replace the current `SettingSuggestionCardPayload` block with this expanded schema section:

```python
SuggestionCardRecommendedAction = Literal[
    "submit_to_pending",
    "continue_outline_feedback",
    "request_more_info",
    "open_detail",
]
SuggestionCardAvailableAction = Literal[
    "open_detail",
    "fill_conversation",
    "resolve",
    "dismiss",
    "submit_to_pending",
    "reactivate",
]
SuggestionCardUpdateAction = Literal[
    "resolve",
    "dismiss",
    "submit_to_pending",
    "reactivate",
]


class SuggestionCardActionHint(BaseModel):
    recommended_action: SuggestionCardRecommendedAction
    primary_label: str
    available_actions: list[SuggestionCardAvailableAction] = Field(default_factory=list)
    reason: str


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
    action_hint: Optional[SuggestionCardActionHint] = None
```

- [ ] **Step 4: Add action-hint implementation**

In `src/novel_dev/services/brainstorm_workspace_service.py`, import `SuggestionCardActionHint` from the schema module. Add these constants near the imports:

```python
SETTING_SUGGESTION_ENTITY_TYPES = {
    "character",
    "faction",
    "location",
    "item",
    "artifact",
    "skill",
    "artifact_or_skill",
}
OUTLINE_SUGGESTION_TYPES = {
    "revision",
    "addition",
    "outline",
    "structure",
    "theme",
    "pacing",
    "hook",
    "arc",
}
OUTLINE_SUGGESTION_KEYWORDS = (
    "总纲",
    "卷纲",
    "篇幅",
    "钩子",
    "动机",
    "结构",
    "主题",
    "闭环",
    "转折",
    "节奏",
    "结尾",
    "弧光",
)
```

Add these methods inside `BrainstormWorkspaceService` before `_serialize_workspace()`:

```python
    def build_suggestion_card_action_hint(
        self,
        card: SettingSuggestionCardPayload,
    ) -> SuggestionCardActionHint:
        available_actions = self._base_suggestion_card_actions(card.status)
        card_type = (card.card_type or "").strip().lower()
        payload = card.payload or {}
        summary = card.summary or ""

        if card.status in {"resolved", "dismissed", "submitted", "superseded"}:
            return SuggestionCardActionHint(
                recommended_action="open_detail",
                primary_label="查看处理",
                available_actions=available_actions,
                reason=self._terminal_suggestion_card_reason(card.status),
            )

        if card_type in SETTING_SUGGESTION_ENTITY_TYPES:
            if self._extract_suggestion_card_name_value(payload):
                return SuggestionCardActionHint(
                    recommended_action="submit_to_pending",
                    primary_label="转设定",
                    available_actions=[*available_actions, "submit_to_pending"],
                    reason="这张卡包含可识别名称，可转为待审批设定。",
                )
            return SuggestionCardActionHint(
                recommended_action="request_more_info",
                primary_label="补充信息",
                available_actions=available_actions,
                reason="这张设定类建议缺少可识别名称，需要先补充信息。",
            )

        if card_type == "relationship":
            return SuggestionCardActionHint(
                recommended_action="continue_outline_feedback",
                primary_label="继续优化",
                available_actions=available_actions,
                reason="关系建议将在最终确认时解析处理，当前适合先回填到大纲会话补充上下文。",
            )

        if card_type in OUTLINE_SUGGESTION_TYPES or self._looks_like_outline_suggestion(summary, payload):
            return SuggestionCardActionHint(
                recommended_action="continue_outline_feedback",
                primary_label="继续优化",
                available_actions=available_actions,
                reason="这张卡是大纲结构或主题表达建议，不是可落库的实体设定。",
            )

        return SuggestionCardActionHint(
            recommended_action="request_more_info",
            primary_label="补充信息",
            available_actions=available_actions,
            reason="这张卡类型或结构不明确，需要先补充信息。",
        )

    def _base_suggestion_card_actions(self, status: str) -> list[str]:
        if status in {"active", "unresolved"}:
            return ["open_detail", "fill_conversation", "resolve", "dismiss"]
        if status in {"resolved", "dismissed"}:
            return ["open_detail", "reactivate"]
        return ["open_detail"]

    def _terminal_suggestion_card_reason(self, status: str) -> str:
        if status == "submitted":
            return "这张卡已转为待审批设定，请在设定审批入口继续处理。"
        if status == "superseded":
            return "这张卡已被新建议覆盖，仅保留历史记录。"
        if status == "resolved":
            return "这张卡已标记解决，可重新激活后继续处理。"
        if status == "dismissed":
            return "这张卡已忽略，可重新激活后继续处理。"
        return "这张卡当前只支持查看。"

    def _extract_suggestion_card_name_value(self, payload: dict[str, Any]) -> str:
        for key in ("canonical_name", "name", "title"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _looks_like_outline_suggestion(self, summary: str, payload: dict[str, Any]) -> bool:
        text = f"{summary} {json.dumps(payload, ensure_ascii=False)}"
        return any(keyword in text for keyword in OUTLINE_SUGGESTION_KEYWORDS)
```

Add `import json` at the top of the service file if it is not already imported.

- [ ] **Step 5: Serialize action hints**

Update `_serialize_workspace()` in `src/novel_dev/services/brainstorm_workspace_service.py` so each card includes an action hint:

```python
    def _serialize_workspace(self, workspace: Any) -> BrainstormWorkspacePayload:
        suggestion_cards = []
        for item in workspace.setting_suggestion_cards or []:
            card = SettingSuggestionCardPayload.model_validate(item)
            card.action_hint = self.build_suggestion_card_action_hint(card)
            suggestion_cards.append(card)

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
            setting_suggestion_cards=suggestion_cards,
        )
```

- [ ] **Step 6: Run action-hint tests**

Run:

```bash
PYTHONPATH=src pytest tests/test_services/test_brainstorm_workspace_service.py -k "suggestion_card_action_hint" -q
```

Expected: all new action-hint tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/novel_dev/schemas/brainstorm_workspace.py src/novel_dev/services/brainstorm_workspace_service.py tests/test_services/test_brainstorm_workspace_service.py
git commit -m "Add suggestion card action hints"
```

---

### Task 2: Backend Suggestion Card Mutation Service

**Files:**
- Modify: `src/novel_dev/schemas/brainstorm_workspace.py`
- Modify: `src/novel_dev/services/brainstorm_workspace_service.py`
- Test: `tests/test_services/test_brainstorm_workspace_service.py`

- [ ] **Step 1: Write failing mutation tests**

Add these tests to `tests/test_services/test_brainstorm_workspace_service.py`:

```python
async def _prepare_workspace_card(
    async_session,
    *,
    novel_id: str,
    status: str = "active",
    card_type: str = "character",
    payload: dict | None = None,
) -> BrainstormWorkspaceService:
    director = NovelDirector(async_session)
    await director.save_checkpoint(
        novel_id,
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )
    service = BrainstormWorkspaceService(async_session)
    await service.merge_suggestion_cards(
        novel_id,
        [
            {
                "operation": "upsert",
                "card_id": "card_1",
                "card_type": card_type,
                "merge_key": f"{card_type}:sample",
                "title": "示例建议卡",
                "summary": "建议补充设定。",
                "status": status,
                "source_outline_refs": ["synopsis"],
                "payload": payload if payload is not None else {"canonical_name": "林风"},
                "display_order": 1,
            }
        ],
    )
    return service


@pytest.mark.asyncio
async def test_update_suggestion_card_resolves_active_card(async_session):
    service = await _prepare_workspace_card(async_session, novel_id="novel_card_resolve")

    result = await service.update_suggestion_card("novel_card_resolve", "card_1", "resolve")

    assert result.workspace.setting_suggestion_cards[0].status == "resolved"
    assert result.pending_extraction is None


@pytest.mark.asyncio
async def test_update_suggestion_card_dismisses_unresolved_card(async_session):
    service = await _prepare_workspace_card(
        async_session,
        novel_id="novel_card_dismiss",
        status="unresolved",
    )

    result = await service.update_suggestion_card("novel_card_dismiss", "card_1", "dismiss")

    assert result.workspace.setting_suggestion_cards[0].status == "dismissed"


@pytest.mark.asyncio
async def test_update_suggestion_card_reactivates_resolved_card(async_session):
    service = await _prepare_workspace_card(
        async_session,
        novel_id="novel_card_reactivate",
        status="resolved",
    )

    result = await service.update_suggestion_card("novel_card_reactivate", "card_1", "reactivate")

    assert result.workspace.setting_suggestion_cards[0].status == "active"


@pytest.mark.asyncio
async def test_update_suggestion_card_submits_pending_and_marks_submitted(async_session):
    service = await _prepare_workspace_card(
        async_session,
        novel_id="novel_card_submit",
        payload={"canonical_name": "林风", "identity": "外门弟子"},
    )

    result = await service.update_suggestion_card(
        "novel_card_submit",
        "card_1",
        "submit_to_pending",
    )

    pending = await PendingExtractionRepository(async_session).list_by_novel("novel_card_submit")
    card = result.workspace.setting_suggestion_cards[0]
    assert card.status == "submitted"
    assert len(pending) == 1
    assert result.pending_extraction is not None
    assert result.pending_extraction.id == pending[0].id


@pytest.mark.asyncio
async def test_update_suggestion_card_rejects_outline_revision_submit(async_session):
    service = await _prepare_workspace_card(
        async_session,
        novel_id="novel_card_revision_submit",
        card_type="revision",
        payload={"focus": "结尾钩子"},
    )

    with pytest.raises(ValueError, match="cannot be submitted"):
        await service.update_suggestion_card(
            "novel_card_revision_submit",
            "card_1",
            "submit_to_pending",
        )


@pytest.mark.asyncio
async def test_update_suggestion_card_rejects_submitted_reactivation(async_session):
    service = await _prepare_workspace_card(
        async_session,
        novel_id="novel_card_submitted_reactivate",
        status="submitted",
    )

    with pytest.raises(ValueError, match="cannot be reactivated"):
        await service.update_suggestion_card(
            "novel_card_submitted_reactivate",
            "card_1",
            "reactivate",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src pytest tests/test_services/test_brainstorm_workspace_service.py -k "update_suggestion_card" -q
```

Expected: fails because `update_suggestion_card()` and update response schemas do not exist.

- [ ] **Step 3: Add update response schemas**

Append these models to `src/novel_dev/schemas/brainstorm_workspace.py` after `BrainstormWorkspaceSubmitResponse`:

```python
class BrainstormSuggestionCardUpdateRequest(BaseModel):
    action: SuggestionCardUpdateAction


class PendingExtractionSummary(BaseModel):
    id: str
    status: str
    source_filename: Optional[str] = None
    extraction_type: str


class BrainstormSuggestionCardUpdateResponse(BaseModel):
    workspace: BrainstormWorkspacePayload
    pending_extraction: Optional[PendingExtractionSummary] = None
```

- [ ] **Step 4: Implement service mutation**

In `src/novel_dev/services/brainstorm_workspace_service.py`, import `BrainstormSuggestionCardUpdateResponse` and `PendingExtractionSummary`. Add this method inside `BrainstormWorkspaceService` after `merge_suggestion_cards()`:

```python
    async def update_suggestion_card(
        self,
        novel_id: str,
        card_id_or_merge_key: str,
        action: str,
    ) -> BrainstormSuggestionCardUpdateResponse:
        workspace = await self.workspace_repo.get_active_by_novel(novel_id)
        if workspace is None:
            raise ValueError(f"Active brainstorm workspace not found: {novel_id}")

        state = await self.state_repo.get_state(novel_id)
        if state is None:
            raise ValueError("Novel state not found for suggestion card update")
        if state.current_phase != Phase.BRAINSTORMING.value:
            raise ValueError("Suggestion cards can only be updated during the brainstorming phase")

        cards = [
            SettingSuggestionCardPayload.model_validate(item).model_dump()
            for item in (workspace.setting_suggestion_cards or [])
        ]
        target_index = self._find_suggestion_card_index(cards, card_id_or_merge_key)
        if target_index is None:
            raise ValueError(f"Suggestion card not found: {card_id_or_merge_key}")

        target = SettingSuggestionCardPayload.model_validate(cards[target_index])
        pending_summary: PendingExtractionSummary | None = None

        if action == "resolve":
            self._ensure_suggestion_card_status(target, {"active", "unresolved"}, action)
            cards[target_index]["status"] = "resolved"
        elif action == "dismiss":
            self._ensure_suggestion_card_status(target, {"active", "unresolved"}, action)
            cards[target_index]["status"] = "dismissed"
        elif action == "reactivate":
            self._ensure_suggestion_card_status(target, {"resolved", "dismissed"}, action)
            cards[target_index]["status"] = "active"
        elif action == "submit_to_pending":
            self._ensure_suggestion_card_status(target, {"active", "unresolved"}, action)
            hint = self.build_suggestion_card_action_hint(target)
            if "submit_to_pending" not in hint.available_actions:
                raise ValueError(f"Suggestion card cannot be submitted: {target.card_id}")
            pending_payload = await self.extraction_service.build_pending_payload_from_suggestion_card(
                novel_id,
                target,
            )
            pending = await self.extraction_service.persist_pending_payload(novel_id, pending_payload)
            pending_summary = PendingExtractionSummary(
                id=pending.id,
                status=pending.status,
                source_filename=pending.source_filename,
                extraction_type=pending.extraction_type,
            )
            cards[target_index]["status"] = "submitted"
        else:
            raise ValueError(f"Unsupported suggestion card action: {action}")

        workspace.setting_suggestion_cards = cards
        workspace.last_saved_at = datetime.utcnow()
        await self.session.flush()
        return BrainstormSuggestionCardUpdateResponse(
            workspace=self._serialize_workspace(workspace),
            pending_extraction=pending_summary,
        )
```

Add these helper methods near `list_active_suggestion_cards()`:

```python
    def _find_suggestion_card_index(
        self,
        cards: list[dict[str, Any]],
        card_id_or_merge_key: str,
    ) -> int | None:
        for index, item in enumerate(cards):
            if item.get("card_id") == card_id_or_merge_key:
                return index
            if item.get("merge_key") == card_id_or_merge_key:
                return index
        return None

    def _ensure_suggestion_card_status(
        self,
        card: SettingSuggestionCardPayload,
        allowed_statuses: set[str],
        action: str,
    ) -> None:
        if card.status in {"submitted", "superseded"} and action == "reactivate":
            raise ValueError(f"Suggestion card status {card.status} cannot be reactivated")
        if card.status not in allowed_statuses:
            allowed = ", ".join(sorted(allowed_statuses))
            raise ValueError(
                f"Suggestion card action {action} requires status in [{allowed}], got {card.status}"
            )
```

- [ ] **Step 5: Run mutation tests**

Run:

```bash
PYTHONPATH=src pytest tests/test_services/test_brainstorm_workspace_service.py -k "update_suggestion_card" -q
```

Expected: all mutation tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/novel_dev/schemas/brainstorm_workspace.py src/novel_dev/services/brainstorm_workspace_service.py tests/test_services/test_brainstorm_workspace_service.py
git commit -m "Add suggestion card mutation service"
```

---

### Task 3: API Route For Suggestion Card Actions

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Test: `tests/test_api/test_brainstorm_workspace_routes.py`

- [ ] **Step 1: Write failing API tests**

Add these tests to `tests/test_api/test_brainstorm_workspace_routes.py`:

```python
async def _seed_route_suggestion_card(async_session, novel_id: str, status: str = "active"):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        novel_id,
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )
    service = BrainstormWorkspaceService(async_session)
    await service.merge_suggestion_cards(
        novel_id,
        [
            {
                "operation": "upsert",
                "card_id": "card_route_1",
                "card_type": "character",
                "merge_key": "character:route",
                "title": "林风",
                "summary": "主角建议卡",
                "status": status,
                "source_outline_refs": ["synopsis"],
                "payload": {"canonical_name": "林风"},
                "display_order": 1,
            }
        ],
    )
    await async_session.commit()


@pytest.mark.asyncio
async def test_patch_suggestion_card_resolves_card(async_session, test_client):
    await _seed_route_suggestion_card(async_session, "n_workspace_card_patch")

    async with test_client as client:
        resp = await client.patch(
            "/api/novels/n_workspace_card_patch/brainstorm/suggestion_cards/card_route_1",
            json={"action": "resolve"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["workspace"]["setting_suggestion_cards"][0]["status"] == "resolved"
    assert data["pending_extraction"] is None


@pytest.mark.asyncio
async def test_patch_suggestion_card_returns_404_for_missing_card(async_session, test_client):
    await _seed_route_suggestion_card(async_session, "n_workspace_card_missing")

    async with test_client as client:
        resp = await client.patch(
            "/api/novels/n_workspace_card_missing/brainstorm/suggestion_cards/nope",
            json={"action": "resolve"},
        )

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_patch_suggestion_card_returns_409_for_illegal_status(async_session, test_client):
    await _seed_route_suggestion_card(
        async_session,
        "n_workspace_card_illegal_status",
        status="submitted",
    )

    async with test_client as client:
        resp = await client.patch(
            "/api/novels/n_workspace_card_illegal_status/brainstorm/suggestion_cards/card_route_1",
            json={"action": "reactivate"},
        )

    assert resp.status_code == 409
    assert "cannot be reactivated" in resp.json()["detail"]
```

- [ ] **Step 2: Run API tests to verify they fail**

Run:

```bash
PYTHONPATH=src pytest tests/test_api/test_brainstorm_workspace_routes.py -k "suggestion_card" -q
```

Expected: fails with 404 because the PATCH route does not exist.

- [ ] **Step 3: Add route imports**

Update the brainstorm schema import in `src/novel_dev/api/routes.py`:

```python
from novel_dev.schemas.brainstorm_workspace import (
    BrainstormSuggestionCardUpdateRequest,
    BrainstormSuggestionCardUpdateResponse,
    BrainstormWorkspacePayload,
    BrainstormWorkspaceSubmitResponse,
)
```

- [ ] **Step 4: Add PATCH route**

Add this route after `submit_brainstorm_workspace()` in `src/novel_dev/api/routes.py`:

```python
@router.patch(
    "/api/novels/{novel_id}/brainstorm/suggestion_cards/{card_id}",
    response_model=BrainstormSuggestionCardUpdateResponse,
)
async def update_brainstorm_suggestion_card(
    novel_id: str,
    card_id: str,
    payload: BrainstormSuggestionCardUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    service = BrainstormWorkspaceService(session)
    try:
        return await service.update_suggestion_card(novel_id, card_id, payload.action)
    except ValueError as e:
        detail = str(e)
        lowered = detail.lower()
        if "not found" in lowered:
            raise HTTPException(status_code=404, detail=detail)
        if "unsupported suggestion card action" in lowered:
            raise HTTPException(status_code=400, detail=detail)
        raise HTTPException(status_code=409, detail=detail)
```

- [ ] **Step 5: Run API tests**

Run:

```bash
PYTHONPATH=src pytest tests/test_api/test_brainstorm_workspace_routes.py -k "suggestion_card" -q
```

Expected: all new API tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/novel_dev/api/routes.py tests/test_api/test_brainstorm_workspace_routes.py
git commit -m "Expose suggestion card action API"
```

---

### Task 4: Frontend API And Store Action

**Files:**
- Modify: `src/novel_dev/web/src/api.js`
- Modify: `src/novel_dev/web/src/stores/novel.js`
- Test: `src/novel_dev/web/src/stores/novel.test.js`

- [ ] **Step 1: Write failing store tests**

Update the `vi.mock('@/api.js', ...)` block in `src/novel_dev/web/src/stores/novel.test.js` to include:

```javascript
  updateBrainstormSuggestionCard: vi.fn(),
```

Add these tests near the other brainstorm workspace store tests:

```javascript
  it('updateBrainstormSuggestionCard updates workspace data from API response', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.brainstormWorkspace.data = {
      workspace_id: 'ws-1',
      novel_id: 'novel-1',
      status: 'active',
      setting_suggestion_cards: [{ card_id: 'card-1', status: 'active' }],
    }
    vi.mocked(api.updateBrainstormSuggestionCard).mockResolvedValue({
      workspace: {
        workspace_id: 'ws-1',
        novel_id: 'novel-1',
        status: 'active',
        setting_suggestion_cards: [{ card_id: 'card-1', status: 'resolved' }],
      },
      pending_extraction: null,
    })

    const result = await store.updateBrainstormSuggestionCard('card-1', 'resolve')

    expect(api.updateBrainstormSuggestionCard).toHaveBeenCalledWith(
      'novel-1',
      'card-1',
      { action: 'resolve' }
    )
    expect(result.pending_extraction).toBeNull()
    expect(store.brainstormWorkspace.data.setting_suggestion_cards[0].status).toBe('resolved')
    expect(store.brainstormWorkspace.updatingCardId).toBe('')
  })

  it('updateBrainstormSuggestionCard keeps workspace and records error on failure', async () => {
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.brainstormWorkspace.data = {
      workspace_id: 'ws-1',
      novel_id: 'novel-1',
      status: 'active',
      setting_suggestion_cards: [{ card_id: 'card-1', status: 'active' }],
    }
    vi.mocked(api.updateBrainstormSuggestionCard).mockRejectedValue(new Error('状态不允许'))

    await expect(store.updateBrainstormSuggestionCard('card-1', 'resolve')).rejects.toThrow('状态不允许')

    expect(store.brainstormWorkspace.data.setting_suggestion_cards[0].status).toBe('active')
    expect(store.brainstormWorkspace.error).toBe('状态不允许')
    expect(store.brainstormWorkspace.updatingCardId).toBe('')
  })
```

- [ ] **Step 2: Run store tests to verify they fail**

Run:

```bash
cd src/novel_dev/web && npm test -- --run src/stores/novel.test.js -t "updateBrainstormSuggestionCard"
```

Expected: fails because API and store actions do not exist.

- [ ] **Step 3: Add frontend API function**

In `src/novel_dev/web/src/api.js`, add after `submitBrainstormWorkspace`:

```javascript
export const updateBrainstormSuggestionCard = (id, cardId, payload) =>
  api.patch(`/novels/${id}/brainstorm/suggestion_cards/${encodeURIComponent(cardId)}`, payload).then(r => r.data)
```

- [ ] **Step 4: Extend brainstorm workspace state**

In `src/novel_dev/web/src/stores/novel.js`, update `createBrainstormWorkspaceState()`:

```javascript
const createBrainstormWorkspaceState = () => ({
  state: 'idle',
  error: '',
  submitting: false,
  updatingCardId: '',
  data: null,
  lastRoundSummary: null,
  requestToken: 0,
})
```

- [ ] **Step 5: Add store action**

In the Pinia actions block near `submitBrainstormWorkspace()`, add:

```javascript
    async updateBrainstormSuggestionCard(cardId, action) {
      if (!this.novelId || !cardId || !action) return null
      if (this.brainstormWorkspace.updatingCardId) return null

      this.brainstormWorkspace.updatingCardId = cardId
      this.brainstormWorkspace.error = ''
      try {
        const result = await api.updateBrainstormSuggestionCard(this.novelId, cardId, { action })
        this.brainstormWorkspace.data = result.workspace
        this.brainstormWorkspace.state = 'ready'
        return result
      } catch (error) {
        this.brainstormWorkspace.error = error?.message || '请求失败'
        throw error
      } finally {
        this.brainstormWorkspace.updatingCardId = ''
      }
    },
```

- [ ] **Step 6: Run store tests**

Run:

```bash
cd src/novel_dev/web && npm test -- --run src/stores/novel.test.js -t "updateBrainstormSuggestionCard"
```

Expected: the new store tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/novel_dev/web/src/api.js src/novel_dev/web/src/stores/novel.js src/novel_dev/web/src/stores/novel.test.js
git commit -m "Add suggestion card store action"
```

---

### Task 5: Suggestion Card Component UI

**Files:**
- Modify: `src/novel_dev/web/src/components/outline/BrainstormSuggestionCards.vue`
- Test: `src/novel_dev/web/src/components/outline/BrainstormSuggestionCards.test.js`

- [ ] **Step 1: Write failing component tests**

Replace `src/novel_dev/web/src/components/outline/BrainstormSuggestionCards.test.js` with:

```javascript
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import BrainstormSuggestionCards from './BrainstormSuggestionCards.vue'

const baseCard = {
  card_id: 'card-1',
  card_type: 'character',
  merge_key: 'character:lin-feng',
  title: '林风',
  summary: '青云宗外门弟子，身负机缘。',
  status: 'active',
  source_outline_refs: ['synopsis', 'vol_1'],
  payload: { canonical_name: '林风', goal: '逆天改命' },
  display_order: 1,
}

describe('BrainstormSuggestionCards', () => {
  it('renders smart primary actions and opens the detail drawer', async () => {
    const wrapper = mount(BrainstormSuggestionCards, {
      props: {
        workspace: {
          setting_suggestion_cards: [
            {
              ...baseCard,
              action_hint: {
                recommended_action: 'submit_to_pending',
                primary_label: '转设定',
                available_actions: ['open_detail', 'fill_conversation', 'resolve', 'dismiss', 'submit_to_pending'],
                reason: '这张卡包含可识别名称，可转为待审批设定。',
              },
            },
            {
              ...baseCard,
              card_id: 'card-2',
              card_type: 'revision',
              merge_key: 'revision:hook',
              title: '结尾钩子新颖度提升',
              summary: '开放钩子需要更独特。',
              payload: { focus: '结尾钩子' },
              action_hint: {
                recommended_action: 'continue_outline_feedback',
                primary_label: '继续优化',
                available_actions: ['open_detail', 'fill_conversation', 'resolve', 'dismiss'],
                reason: '这张卡是大纲结构或主题表达建议，不是可落库的实体设定。',
              },
            },
            {
              ...baseCard,
              card_id: 'card-3',
              card_type: 'character',
              merge_key: 'character:unknown',
              title: '角色动机不足',
              payload: {},
              action_hint: {
                recommended_action: 'request_more_info',
                primary_label: '补充信息',
                available_actions: ['open_detail', 'fill_conversation', 'resolve', 'dismiss'],
                reason: '这张设定类建议缺少可识别名称，需要先补充信息。',
              },
            },
          ],
        },
      },
    })

    expect(wrapper.text()).toContain('转设定')
    expect(wrapper.text()).toContain('继续优化')
    expect(wrapper.text()).toContain('补充信息')

    await wrapper.findAll('[data-testid="suggestion-process"]')[0].trigger('click')

    expect(wrapper.get('[data-testid="suggestion-detail-drawer"]').text()).toContain('林风')
    expect(wrapper.get('[data-testid="suggestion-detail-drawer"]').text()).toContain('可转为待审批设定')
  })

  it('emits fill-conversation for outline optimization cards without submitting', async () => {
    const wrapper = mount(BrainstormSuggestionCards, {
      props: {
        workspace: {
          setting_suggestion_cards: [
            {
              ...baseCard,
              card_type: 'revision',
              action_hint: {
                recommended_action: 'continue_outline_feedback',
                primary_label: '继续优化',
                available_actions: ['open_detail', 'fill_conversation', 'resolve', 'dismiss'],
                reason: '适合继续优化大纲。',
              },
            },
          ],
        },
      },
    })

    await wrapper.get('[data-testid="suggestion-primary-action"]').trigger('click')

    expect(wrapper.emitted('fill-conversation')).toHaveLength(1)
    expect(wrapper.emitted('fill-conversation')[0][0].card_id).toBe('card-1')
    expect(wrapper.emitted('update-card')).toBeUndefined()
  })

  it('emits submit_to_pending for cards whose primary action is transfer to setting', async () => {
    const wrapper = mount(BrainstormSuggestionCards, {
      props: {
        workspace: {
          setting_suggestion_cards: [
            {
              ...baseCard,
              action_hint: {
                recommended_action: 'submit_to_pending',
                primary_label: '转设定',
                available_actions: ['open_detail', 'fill_conversation', 'resolve', 'dismiss', 'submit_to_pending'],
                reason: '可转为待审批设定。',
              },
            },
          ],
        },
      },
    })

    await wrapper.get('[data-testid="suggestion-primary-action"]').trigger('click')

    expect(wrapper.emitted('update-card')[0][0]).toEqual({
      card: expect.objectContaining({ card_id: 'card-1' }),
      action: 'submit_to_pending',
    })
  })

  it('shows historical cards collapsed and disables relationship submit', async () => {
    const wrapper = mount(BrainstormSuggestionCards, {
      props: {
        workspace: {
          setting_suggestion_cards: [
            {
              ...baseCard,
              card_id: 'card-history',
              status: 'resolved',
              title: '已解决卡片',
              action_hint: {
                recommended_action: 'open_detail',
                primary_label: '查看处理',
                available_actions: ['open_detail', 'reactivate'],
                reason: '这张卡已标记解决。',
              },
            },
            {
              ...baseCard,
              card_id: 'card-rel',
              card_type: 'relationship',
              merge_key: 'relationship:a-b',
              title: '关系建议',
              action_hint: {
                recommended_action: 'continue_outline_feedback',
                primary_label: '继续优化',
                available_actions: ['open_detail', 'fill_conversation', 'resolve', 'dismiss'],
                reason: '关系建议将在最终确认时解析处理。',
              },
            },
          ],
        },
      },
    })

    expect(wrapper.text()).not.toContain('已解决卡片')
    await wrapper.get('[data-testid="toggle-suggestion-history"]').trigger('click')
    expect(wrapper.text()).toContain('已解决卡片')

    await wrapper.find('[data-testid="suggestion-process"]').trigger('click')
    expect(wrapper.get('[data-testid="submit-to-pending-action"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="suggestion-detail-drawer"]').text()).toContain('关系建议将在最终确认时解析处理')
  })
})
```

- [ ] **Step 2: Run component tests to verify they fail**

Run:

```bash
cd src/novel_dev/web && npm test -- --run src/components/outline/BrainstormSuggestionCards.test.js
```

Expected: fails because buttons, drawer, and emits do not exist.

- [ ] **Step 3: Implement component behavior**

In `src/novel_dev/web/src/components/outline/BrainstormSuggestionCards.vue`, add `defineEmits` and local state:

```javascript
import { computed, ref } from 'vue'

const emit = defineEmits(['fill-conversation', 'update-card'])
const selectedCard = ref(null)
const showHistory = ref(false)
```

Add these helpers in the `<script setup>` section:

```javascript
const terminalStatuses = new Set(['resolved', 'dismissed', 'submitted', 'superseded'])

const historyCards = computed(() => {
  const cards = props.workspace?.setting_suggestion_cards
  const list = Array.isArray(cards) ? cards : []
  return list
    .filter((card) => card && terminalStatuses.has(card.status))
    .slice()
    .sort(sortCards)
})

function sortCards(left, right) {
  const leftOrder = Number(left?.display_order ?? 0)
  const rightOrder = Number(right?.display_order ?? 0)
  if (leftOrder !== rightOrder) return leftOrder - rightOrder
  return String(left?.merge_key || '').localeCompare(String(right?.merge_key || ''))
}

function getActionHint(card) {
  return card?.action_hint || {
    recommended_action: 'open_detail',
    primary_label: '查看处理',
    available_actions: ['open_detail'],
    reason: '这张卡当前只支持查看。',
  }
}

function hasAction(card, action) {
  return Array.isArray(getActionHint(card).available_actions) &&
    getActionHint(card).available_actions.includes(action)
}

function openDetail(card) {
  selectedCard.value = card
}

function closeDetail() {
  selectedCard.value = null
}

function handlePrimaryAction(card) {
  const hint = getActionHint(card)
  if (hint.recommended_action === 'submit_to_pending' && hasAction(card, 'submit_to_pending')) {
    emit('update-card', { card, action: 'submit_to_pending' })
    return
  }
  if (hint.recommended_action === 'continue_outline_feedback' || hint.recommended_action === 'request_more_info') {
    emit('fill-conversation', card)
    return
  }
  openDetail(card)
}

function emitUpdate(card, action) {
  if (!hasAction(card, action)) return
  emit('update-card', { card, action })
}

function formatPayload(payload) {
  if (!payload || typeof payload !== 'object') return '{}'
  return JSON.stringify(payload, null, 2)
}
```

Update the existing `activeCards` sort to call `sortCards`.

- [ ] **Step 4: Implement template additions**

Inside each suggestion card `<article>`, after the summary paragraph, add:

```vue
        <p class="mt-3 text-xs leading-5 text-gray-500 dark:text-gray-400">
          {{ getActionHint(card).reason }}
        </p>
        <div class="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            class="brainstorm-suggestion-card__button brainstorm-suggestion-card__button--primary"
            data-testid="suggestion-primary-action"
            @click="handlePrimaryAction(card)"
          >
            {{ getActionHint(card).primary_label }}
          </button>
          <button
            type="button"
            class="brainstorm-suggestion-card__button"
            data-testid="suggestion-process"
            @click="openDetail(card)"
          >
            处理
          </button>
        </div>
```

After the active-card grid, add the history toggle and drawer:

```vue
    <div v-if="historyCards.length" class="mt-4">
      <button
        type="button"
        class="brainstorm-suggestion-card__button"
        data-testid="toggle-suggestion-history"
        @click="showHistory = !showHistory"
      >
        历史建议 {{ historyCards.length }}
      </button>
      <div v-if="showHistory" class="mt-3 grid gap-3 lg:grid-cols-2">
        <article
          v-for="card in historyCards"
          :key="card.card_id || card.merge_key"
          class="brainstorm-suggestion-card rounded-2xl border px-4 py-4"
          data-testid="suggestion-history-card"
        >
          <div class="text-sm font-semibold text-gray-900 dark:text-gray-100">{{ card.title }}</div>
          <p class="mt-1 text-xs leading-5 text-gray-500 dark:text-gray-400">
            {{ getActionHint(card).reason }}
          </p>
          <button
            type="button"
            class="brainstorm-suggestion-card__button mt-3"
            @click="openDetail(card)"
          >
            查看处理
          </button>
        </article>
      </div>
    </div>

    <div
      v-if="selectedCard"
      class="brainstorm-suggestion-drawer"
      data-testid="suggestion-detail-drawer"
    >
      <div class="brainstorm-suggestion-drawer__panel">
        <div class="flex items-start justify-between gap-3">
          <div>
            <div class="text-xs font-medium uppercase tracking-[0.2em] text-gray-400">Suggestion Detail</div>
            <h3 class="mt-2 text-lg font-semibold text-gray-900 dark:text-gray-100">{{ selectedCard.title }}</h3>
            <p class="mt-1 text-xs leading-5 text-gray-500 dark:text-gray-400">
              类型：{{ selectedCard.card_type || 'unknown' }} · 来源：{{ formatSourceRefs(selectedCard.source_outline_refs) }}
            </p>
          </div>
          <button type="button" class="brainstorm-suggestion-card__button" @click="closeDetail">关闭</button>
        </div>
        <p class="mt-4 whitespace-pre-wrap text-sm leading-6 text-gray-700 dark:text-gray-200">{{ selectedCard.summary }}</p>
        <div class="brainstorm-suggestion-summary mt-4 rounded-2xl border px-4 py-3 text-sm">
          <div class="font-semibold">{{ getActionHint(selectedCard).primary_label }}</div>
          <p class="mt-1 text-xs leading-5">{{ getActionHint(selectedCard).reason }}</p>
        </div>
        <div class="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            class="brainstorm-suggestion-card__button brainstorm-suggestion-card__button--primary"
            data-testid="submit-to-pending-action"
            :disabled="!hasAction(selectedCard, 'submit_to_pending')"
            @click="emitUpdate(selectedCard, 'submit_to_pending')"
          >
            转为待审批设定
          </button>
          <button
            type="button"
            class="brainstorm-suggestion-card__button"
            :disabled="!hasAction(selectedCard, 'fill_conversation')"
            @click="emit('fill-conversation', selectedCard)"
          >
            回填到输入区
          </button>
          <button
            type="button"
            class="brainstorm-suggestion-card__button"
            :disabled="!hasAction(selectedCard, 'resolve')"
            @click="emitUpdate(selectedCard, 'resolve')"
          >
            标记已解决
          </button>
          <button
            type="button"
            class="brainstorm-suggestion-card__button"
            :disabled="!hasAction(selectedCard, 'dismiss')"
            @click="emitUpdate(selectedCard, 'dismiss')"
          >
            忽略
          </button>
          <button
            type="button"
            class="brainstorm-suggestion-card__button"
            :disabled="!hasAction(selectedCard, 'reactivate')"
            @click="emitUpdate(selectedCard, 'reactivate')"
          >
            重新激活
          </button>
        </div>
        <pre class="brainstorm-suggestion-payload mt-4 overflow-auto rounded-xl p-3 text-xs">{{ formatPayload(selectedCard.payload) }}</pre>
        <details class="mt-4 text-xs text-gray-500 dark:text-gray-400">
          <summary>调试信息</summary>
          <div class="mt-2">card_id: {{ selectedCard.card_id }}</div>
          <div>merge_key: {{ selectedCard.merge_key }}</div>
        </details>
      </div>
    </div>
```

- [ ] **Step 5: Add scoped styles**

Append these styles to the existing scoped style block:

```css
.brainstorm-suggestion-card__button {
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-surface);
  color: var(--app-text);
  padding: 0.45rem 0.7rem;
  font-size: 0.75rem;
  font-weight: 600;
}

.brainstorm-suggestion-card__button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.brainstorm-suggestion-card__button--primary {
  border-color: color-mix(in srgb, var(--app-accent, #34d399) 45%, var(--app-border));
  color: color-mix(in srgb, var(--app-accent, #34d399) 72%, var(--app-text));
}

.brainstorm-suggestion-drawer {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  justify-content: flex-end;
  background: rgb(15 23 42 / 0.32);
}

.brainstorm-suggestion-drawer__panel {
  width: min(560px, 100vw);
  height: 100%;
  overflow-y: auto;
  border-left: 1px solid var(--app-border);
  background: var(--app-surface);
  padding: 1.25rem;
  box-shadow: -16px 0 40px rgb(15 23 42 / 0.18);
}

.brainstorm-suggestion-payload {
  border: 1px solid var(--app-border);
  background: var(--app-surface-soft);
  color: var(--app-text);
}
```

- [ ] **Step 6: Run component tests**

Run:

```bash
cd src/novel_dev/web && npm test -- --run src/components/outline/BrainstormSuggestionCards.test.js
```

Expected: component tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/novel_dev/web/src/components/outline/BrainstormSuggestionCards.vue src/novel_dev/web/src/components/outline/BrainstormSuggestionCards.test.js
git commit -m "Add suggestion card processing drawer"
```

---

### Task 6: VolumePlan Wiring And Draft Refill

**Files:**
- Modify: `src/novel_dev/web/src/views/VolumePlan.vue`
- Test: `src/novel_dev/web/src/views/VolumePlan.test.js`

- [ ] **Step 1: Write failing VolumePlan tests**

Add this test to `src/novel_dev/web/src/views/VolumePlan.test.js` near the brainstorm suggestion card tests:

```javascript
  it('fills suggestion card prompt into conversation without submitting feedback', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.novelState.current_phase = 'brainstorming'
    store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()
    store.submitOutlineFeedback = vi.fn()
    store.outlineWorkbench.selection = {
      outline_type: 'synopsis',
      outline_ref: 'synopsis',
    }
    store.brainstormWorkspace.data = {
      workspace_id: 'ws-1',
      novel_id: 'novel-1',
      status: 'active',
      outline_drafts: {
        'synopsis:synopsis': { title: '总纲' },
      },
      setting_docs_draft: [],
      setting_suggestion_cards: [
        {
          card_id: 'card-1',
          card_type: 'revision',
          merge_key: 'revision:hook',
          title: '结尾钩子新颖度提升',
          summary: '开放钩子需要更独特。',
          status: 'active',
          source_outline_refs: ['synopsis'],
          payload: { focus: '结尾钩子' },
          action_hint: {
            recommended_action: 'continue_outline_feedback',
            primary_label: '继续优化',
            available_actions: ['open_detail', 'fill_conversation', 'resolve', 'dismiss'],
            reason: '适合继续优化大纲。',
          },
        },
      ],
    }

    let submittedFeedback = null
    const wrapper = mount(VolumePlan, {
      global: {
        plugins: [pinia],
        stubs: {
          OutlineSidebar: true,
          OutlineDetailPanel: true,
          OutlineConversation: {
            template: '<div data-testid="conversation-stub" />',
            methods: {
              setDraft(value) {
                submittedFeedback = value
              },
            },
          },
        },
      },
    })

    await flushPromises()
    await wrapper.get('[data-testid="suggestion-primary-action"]').trigger('click')

    expect(submittedFeedback).toContain('请根据这张设定建议卡继续优化当前大纲')
    expect(submittedFeedback).toContain('结尾钩子新颖度提升')
    expect(submittedFeedback).toContain('开放钩子需要更独特')
    expect(store.submitOutlineFeedback).not.toHaveBeenCalled()
  })

  it('updates suggestion card through store when component emits update-card', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useNovelStore()
    store.novelId = 'novel-1'
    store.novelState.current_phase = 'brainstorming'
    store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()
    store.updateBrainstormSuggestionCard = vi.fn().mockResolvedValue()
    store.outlineWorkbench.selection = {
      outline_type: 'synopsis',
      outline_ref: 'synopsis',
    }
    store.brainstormWorkspace.data = {
      workspace_id: 'ws-1',
      novel_id: 'novel-1',
      status: 'active',
      outline_drafts: {
        'synopsis:synopsis': { title: '总纲' },
      },
      setting_docs_draft: [],
      setting_suggestion_cards: [
        {
          card_id: 'card-1',
          card_type: 'character',
          merge_key: 'character:lin-feng',
          title: '林风',
          summary: '主角建议卡',
          status: 'active',
          source_outline_refs: ['synopsis'],
          payload: { canonical_name: '林风' },
          action_hint: {
            recommended_action: 'submit_to_pending',
            primary_label: '转设定',
            available_actions: ['open_detail', 'fill_conversation', 'resolve', 'dismiss', 'submit_to_pending'],
            reason: '可转为待审批设定。',
          },
        },
      ],
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
    await wrapper.get('[data-testid="suggestion-primary-action"]').trigger('click')

    expect(store.updateBrainstormSuggestionCard).toHaveBeenCalledWith('card-1', 'submit_to_pending')
  })
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd src/novel_dev/web && npm test -- --run src/views/VolumePlan.test.js -t "suggestion card"
```

Expected: fails because `BrainstormSuggestionCards` events are not wired in `VolumePlan.vue`.

- [ ] **Step 3: Wire component events**

Update the `BrainstormSuggestionCards` usage in `src/novel_dev/web/src/views/VolumePlan.vue`:

```vue
      <BrainstormSuggestionCards
        v-if="isBrainstormWorkspaceMode"
        :workspace="store.brainstormWorkspace.data"
        :last-round-summary="store.brainstormWorkspace.lastRoundSummary"
        :submit-warnings="store.brainstormWorkspace.data?.submit_warnings || []"
        @fill-conversation="handleFillSuggestionConversation"
        @update-card="handleUpdateSuggestionCard"
      />
```

- [ ] **Step 4: Add prompt helpers and handlers**

In `src/novel_dev/web/src/views/VolumePlan.vue`, add these functions near `handleApplySuggestion()`:

```javascript
function buildSuggestionCardPrompt(card) {
  const title = card?.title || '未命名建议卡'
  const type = card?.card_type || 'unknown'
  const refs = Array.isArray(card?.source_outline_refs) && card.source_outline_refs.length
    ? card.source_outline_refs.join('、')
    : '未知'
  const status = card?.status || 'unknown'
  const summary = card?.summary || ''
  const payloadSummary = summarizeSuggestionPayload(card?.payload)
  return [
    '请根据这张设定建议卡继续优化当前大纲：',
    `标题：${title}`,
    `类型：${type}`,
    `来源：${refs}`,
    `状态：${status}`,
    `建议：${summary}`,
    `需要补充/确认的设定字段：${payloadSummary}`,
  ].join('\n')
}

function summarizeSuggestionPayload(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return '无结构化字段'
  const entries = Object.entries(payload)
    .filter(([, value]) => value !== null && value !== undefined && String(value).trim() !== '')
    .slice(0, 12)
    .map(([key, value]) => `${key}=${formatSuggestionPayloadValue(value)}`)
  return entries.length ? entries.join('；') : '无结构化字段'
}

function formatSuggestionPayloadValue(value) {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.map(formatSuggestionPayloadValue).join('、')
  if (typeof value === 'object' && value !== null) return JSON.stringify(value)
  return String(value)
}

function handleFillSuggestionConversation(card) {
  conversationRef.value?.setDraft?.(buildSuggestionCardPrompt(card))
}

async function handleUpdateSuggestionCard({ card, action }) {
  const cardId = card?.card_id || card?.merge_key
  if (!cardId || !action) return
  await store.updateBrainstormSuggestionCard(cardId, action)
}
```

Keep the existing `handleApplySuggestion()` because `OutlineDetailPanel` still emits `apply-suggestion`.

- [ ] **Step 5: Run VolumePlan tests**

Run:

```bash
cd src/novel_dev/web && npm test -- --run src/views/VolumePlan.test.js -t "suggestion card"
```

Expected: the new VolumePlan tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/novel_dev/web/src/views/VolumePlan.vue src/novel_dev/web/src/views/VolumePlan.test.js
git commit -m "Wire suggestion card actions into outline workbench"
```

---

### Task 7: Full Verification And Local Restart

**Files:**
- No code files should be modified in this task unless verification exposes a defect.

- [ ] **Step 1: Run targeted backend tests**

Run:

```bash
PYTHONPATH=src pytest \
  tests/test_services/test_brainstorm_workspace_service.py -k "suggestion_card_action_hint or update_suggestion_card" \
  tests/test_api/test_brainstorm_workspace_routes.py -k "suggestion_card" \
  -q
```

Expected: all selected backend tests pass.

- [ ] **Step 2: Run targeted frontend tests**

Run:

```bash
cd src/novel_dev/web && npm test -- --run \
  src/components/outline/BrainstormSuggestionCards.test.js \
  src/views/VolumePlan.test.js \
  src/stores/novel.test.js
```

Expected: all selected frontend tests pass.

- [ ] **Step 3: Build frontend**

Run:

```bash
cd src/novel_dev/web && npm run build
```

Expected: build exits 0. A chunk-size warning is acceptable if it matches the existing Vite warning pattern.

- [ ] **Step 4: Run Python compile check**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/novel-dev-pycache python3.11 -m py_compile \
  src/novel_dev/schemas/brainstorm_workspace.py \
  src/novel_dev/services/brainstorm_workspace_service.py \
  src/novel_dev/api/routes.py
```

Expected: exits 0.

- [ ] **Step 5: Restart local app**

Run:

```bash
./scripts/run_local.sh
```

Expected: API health check reports ready, frontend build is served, and embedding server is ready.

- [ ] **Step 6: Smoke check service health**

Run:

```bash
curl -sf http://127.0.0.1:8000/healthz
curl -sf http://127.0.0.1:9997/v1/models
```

Expected:

```json
{"ok":true}
```

and a models response containing `bge-m3`.

- [ ] **Step 7: Final commit if verification fixes were needed**

If Tasks 1-6 already created commits and this task made no code changes, do not create an empty commit. If verification required a fix, commit only the fix:

```bash
git add <changed-files>
git commit -m "Stabilize suggestion card processing entry"
```

---

## Plan Self-Review

- Spec coverage: action hints, smart primary actions, no auto-submit on refill, card status transitions, pending conversion, route errors, frontend drawer, history cards, store refresh, and verification are each mapped to a task.
- Type consistency: backend action strings are `submit_to_pending`, `continue_outline_feedback`, `request_more_info`, `open_detail`, `resolve`, `dismiss`, and `reactivate`; frontend uses the same strings.
- Scope: this remains a single feature in the existing brainstorm workspace flow. No new table, no batch processor, and no independent handling center are included.
