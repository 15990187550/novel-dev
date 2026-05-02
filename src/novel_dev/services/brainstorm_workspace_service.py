import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.agents.brainstorm_agent import BrainstormAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.brainstorm_workspace_repo import BrainstormWorkspaceRepository
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.relationship_repo import RelationshipRepository
from novel_dev.schemas.brainstorm_workspace import (
    BrainstormSuggestionCardUpdateResponse,
    BrainstormWorkspacePayload,
    BrainstormWorkspaceSubmitResponse,
    PendingExtractionPayload,
    PendingExtractionSummary,
    SettingDocDraftPayload,
    SettingSuggestionCardMergePayload,
    SettingSuggestionCardPayload,
    SuggestionCardActionHint,
)
from novel_dev.schemas.outline import SynopsisData
from novel_dev.services.extraction_service import ExtractionService


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


class BrainstormWorkspaceService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.workspace_repo = BrainstormWorkspaceRepository(session)
        self.state_repo = NovelStateRepository(session)
        self.doc_repo = DocumentRepository(session)
        self.relationship_repo = RelationshipRepository(session)
        self.director = NovelDirector(session)
        self.extraction_service = ExtractionService(session)

    async def get_workspace_payload(self, novel_id: str) -> BrainstormWorkspacePayload:
        workspace = await self.workspace_repo.get_or_create(novel_id)
        return self._serialize_workspace(workspace)

    async def save_outline_draft(
        self,
        novel_id: str,
        outline_type: str,
        outline_ref: str,
        result_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        workspace = await self.workspace_repo.get_or_create(novel_id)
        outline_drafts = dict(workspace.outline_drafts or {})
        outline_drafts[self._build_outline_key(outline_type, outline_ref)] = dict(result_snapshot)
        workspace.outline_drafts = outline_drafts
        workspace.last_saved_at = datetime.utcnow()
        await self.session.flush()
        return outline_drafts[self._build_outline_key(outline_type, outline_ref)]

    async def merge_setting_drafts(
        self,
        novel_id: str,
        setting_draft_updates: list[dict[str, Any]],
    ) -> list[SettingDocDraftPayload]:
        workspace = await self.workspace_repo.get_or_create(novel_id)
        existing_by_id = {}
        for item in workspace.setting_docs_draft or []:
            normalized = self.extraction_service.validate_setting_draft(item)
            existing_by_id[normalized["draft_id"]] = normalized

        for item in setting_draft_updates:
            normalized = self.extraction_service.validate_setting_draft(item)
            existing_by_id[normalized["draft_id"]] = normalized

        merged = sorted(
            existing_by_id.values(),
            key=lambda item: (item.get("order_index", 0), item.get("draft_id", "")),
        )
        workspace.setting_docs_draft = merged
        workspace.last_saved_at = datetime.utcnow()
        await self.session.flush()
        return [SettingDocDraftPayload.model_validate(item) for item in merged]

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
        superseded_merge_keys = {
            item["merge_key"]
            for item in cards
            if item.get("status") == "superseded"
        }

        for update in card_updates:
            normalized_update = SettingSuggestionCardMergePayload.model_validate(update)
            merge_key = normalized_update.merge_key

            if normalized_update.operation == "supersede":
                superseded_merge_keys.add(merge_key)
                existing = by_merge_key.get(merge_key)
                if existing is None:
                    by_merge_key[merge_key] = self._build_superseded_placeholder_card(merge_key)
                else:
                    existing["status"] = "superseded"
                continue

            incoming_payload = normalized_update.model_dump(
                exclude={"operation"},
                exclude_none=True,
            )
            existing = by_merge_key.get(merge_key)
            if existing is None:
                # For new cards, default display_order to 0 if omitted.
                incoming_payload.setdefault("display_order", normalized_update.display_order or 0)
                incoming = SettingSuggestionCardPayload.model_validate(incoming_payload).model_dump()
                if merge_key in superseded_merge_keys:
                    incoming["status"] = "superseded"
                by_merge_key[merge_key] = incoming
                continue

            # For existing cards, rely on validated upsert fields, but don't let an omitted
            # display_order clobber the current ordering.
            incoming = SettingSuggestionCardPayload.model_validate(
                {
                    **incoming_payload,
                    # Required by SettingSuggestionCardPayload even if merge payload omits it.
                    "display_order": incoming_payload.get("display_order", 0),
                }
            ).model_dump()
            existing["card_id"] = incoming["card_id"]
            existing["card_type"] = incoming["card_type"]
            existing["summary"] = incoming["summary"]
            existing["title"] = incoming["title"]
            existing["status"] = (
                "superseded" if merge_key in superseded_merge_keys else incoming["status"]
            )
            existing["payload"] = {
                **existing.get("payload", {}),
                **incoming["payload"],
            }
            # Preserve ordering unless the update explicitly provides display_order.
            if normalized_update.display_order is not None:
                existing["display_order"] = normalized_update.display_order
            existing["source_outline_refs"] = sorted(
                set(existing.get("source_outline_refs", []))
                | set(incoming.get("source_outline_refs", []))
            )

        merged = sorted(
            by_merge_key.values(),
            key=lambda item: (item["display_order"], item["merge_key"]),
        )
        workspace.setting_suggestion_cards = merged
        workspace.last_saved_at = datetime.utcnow()
        await self.session.flush()
        return [SettingSuggestionCardPayload.model_validate(item) for item in merged]

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
            raise ValueError(
                "Suggestion cards can only be updated during the brainstorming phase"
            )

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
            pending_payload = (
                await self.extraction_service.build_pending_payload_from_suggestion_card(
                    novel_id,
                    target,
                )
            )
            pending = await self.extraction_service.persist_pending_payload(
                novel_id,
                pending_payload,
            )
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

    async def submit_workspace(self, novel_id: str) -> BrainstormWorkspaceSubmitResponse:
        workspace = await self.workspace_repo.get_active_by_novel(novel_id)
        if workspace is None:
            raise ValueError(f"Active brainstorm workspace not found: {novel_id}")

        state = await self.state_repo.get_state(novel_id)
        if state is None:
            raise ValueError("Novel state not found for brainstorm submission")
        if state.current_phase != Phase.BRAINSTORMING.value:
            raise ValueError(
                "Brainstorm workspace can only be submitted during the brainstorming phase"
            )

        synopsis_snapshot = (workspace.outline_drafts or {}).get("synopsis:synopsis")
        if synopsis_snapshot is None:
            raise ValueError("Synopsis draft is required before final confirmation")

        workspace_payload = self._serialize_workspace(workspace)
        active_cards = self.list_active_suggestion_cards(workspace_payload)
        submit_warnings: list[str] = []
        relationship_count = 0

        if active_cards:
            entity_cards = [
                card for card in active_cards if card.card_type != "relationship"
            ]
            relationship_cards = [
                card for card in active_cards if card.card_type == "relationship"
            ]
            pending_payloads = [
                await self.extraction_service.build_pending_payload_from_suggestion_card(
                    novel_id,
                    card,
                )
                for card in entity_cards
            ]
            legacy_pending_payloads = [
                await self.extraction_service.build_pending_payload_from_setting_draft(
                    novel_id,
                    draft,
                )
                for draft in (workspace.setting_docs_draft or [])
            ]
            # Legacy setting drafts are still part of final confirmation even when
            # suggestion cards exist. Keep them, but avoid creating duplicate
            # pending items for the same entity-level suggestion.
            pending_payloads = self._merge_pending_payloads(
                primary_payloads=pending_payloads,
                secondary_payloads=legacy_pending_payloads,
            )
            (
                resolved_relationships,
                submit_warnings,
            ) = await self._resolve_relationship_cards(
                novel_id=novel_id,
                cards=relationship_cards,
                active_cards=active_cards,
            )
        else:
            pending_payloads = [
                await self.extraction_service.build_pending_payload_from_setting_draft(
                    novel_id,
                    draft,
                )
                for draft in (workspace.setting_docs_draft or [])
            ]
            resolved_relationships = []

        volume_outline_drafts = self._collect_submitted_volume_outline_drafts(
            workspace.outline_drafts or {}
        )
        synopsis = SynopsisData.model_validate(synopsis_snapshot)
        synopsis_text = BrainstormAgent(self.session).format_synopsis_text(synopsis)
        synopsis_doc = await self.doc_repo.create(
            doc_id=f"doc_{uuid.uuid4().hex[:8]}",
            novel_id=novel_id,
            doc_type="synopsis",
            title=synopsis.title,
            content=synopsis_text,
        )

        pending_items = []
        for payload in pending_payloads:
            pending_items.append(
                await self.extraction_service.persist_pending_payload(
                    novel_id,
                    payload,
                )
            )

        for item in resolved_relationships:
            await self.relationship_repo.upsert(
                source_id=item["source_id"],
                target_id=item["target_id"],
                relation_type=item["relation_type"],
                meta=item["meta"],
                novel_id=novel_id,
            )
        relationship_count = len(resolved_relationships)

        checkpoint = dict(state.checkpoint_data or {})
        checkpoint["synopsis_data"] = synopsis.model_dump()
        checkpoint["synopsis_doc_id"] = synopsis_doc.id
        checkpoint["submitted_volume_outline_drafts"] = volume_outline_drafts

        await self.director.save_checkpoint(
            novel_id=novel_id,
            phase=Phase.VOLUME_PLANNING,
            checkpoint_data=checkpoint,
            volume_id=state.current_volume_id,
            chapter_id=state.current_chapter_id,
        )
        await self.workspace_repo.mark_submitted(workspace.id)
        await self.session.commit()

        return BrainstormWorkspaceSubmitResponse(
            synopsis_title=synopsis.title,
            pending_setting_count=len(pending_items),
            volume_outline_count=sum(
                1
                for key in (workspace.outline_drafts or {})
                if key.startswith("volume:")
            ),
            relationship_count=relationship_count,
            submit_warnings=submit_warnings,
        )

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

        if card_type in OUTLINE_SUGGESTION_TYPES or self._looks_like_outline_suggestion(
            summary,
            payload,
        ):
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

    def list_active_suggestion_cards(
        self,
        workspace_payload: BrainstormWorkspacePayload,
    ) -> list[SettingSuggestionCardPayload]:
        return [
            card
            for card in workspace_payload.setting_suggestion_cards
            if card.status in {"active", "unresolved"}
        ]

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
                f"Suggestion card action {action} requires status in [{allowed}], "
                f"got {card.status}"
            )

    def _merge_pending_payloads(
        self,
        *,
        primary_payloads: list[PendingExtractionPayload],
        secondary_payloads: list[PendingExtractionPayload],
    ) -> list[PendingExtractionPayload]:
        merged = list(primary_payloads)
        seen_keys = {
            key
            for payload in primary_payloads
            if (key := self._build_pending_payload_dedupe_key(payload)) is not None
        }
        for payload in secondary_payloads:
            key = self._build_pending_payload_dedupe_key(payload)
            if key is not None and key in seen_keys:
                continue
            merged.append(payload)
            if key is not None:
                seen_keys.add(key)
        return merged

    def _build_pending_payload_dedupe_key(
        self,
        payload: PendingExtractionPayload,
    ) -> str | None:
        proposed_entities = payload.proposed_entities or []
        if len(proposed_entities) != 1:
            return None
        entity = proposed_entities[0]
        entity_type = entity.get("type")
        entity_name = entity.get("name")
        if not isinstance(entity_type, str) or not isinstance(entity_name, str):
            return None
        normalized_name = self.extraction_service.entity_svc.entity_repo.normalize_name(entity_name)
        if not normalized_name:
            return None
        return f"entity:{entity_type}:{normalized_name}"

    def _build_outline_key(self, outline_type: str, outline_ref: str) -> str:
        return f"{outline_type}:{outline_ref}"

    def _collect_submitted_volume_outline_drafts(
        self,
        outline_drafts: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        submitted_drafts = []
        for outline_key, snapshot in sorted(
            outline_drafts.items(),
            key=lambda item: (self._extract_outline_ref(item[0]), item[0]),
        ):
            if not outline_key.startswith("volume:"):
                continue
            submitted_drafts.append(
                {
                    "outline_ref": self._extract_outline_ref(outline_key),
                    "outline_key": outline_key,
                    "snapshot": dict(snapshot),
                }
            )
        return submitted_drafts

    def _extract_outline_ref(self, outline_key: str) -> str:
        _, _, outline_ref = outline_key.partition(":")
        return outline_ref

    def _build_superseded_placeholder_card(self, merge_key: str) -> dict[str, Any]:
        card_type, _, _ = merge_key.partition(":")
        return {
            "card_id": f"superseded:{merge_key}",
            "card_type": card_type or "unknown",
            "merge_key": merge_key,
            "title": merge_key,
            "summary": "Superseded before first upsert.",
            "status": "superseded",
            "source_outline_refs": [],
            "payload": {},
            "display_order": 0,
        }

    async def _resolve_relationship_cards(
        self,
        novel_id: str,
        cards: list[SettingSuggestionCardPayload],
        active_cards: list[SettingSuggestionCardPayload],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        resolved_relationships: list[dict[str, Any]] = []
        warnings: list[str] = []
        entity_cards = [card for card in active_cards if card.card_type != "relationship"]
        entity_cards_by_key = {card.merge_key: card for card in entity_cards}

        for card in cards:
            source_id, source_error = await self._resolve_relationship_endpoint(
                novel_id=novel_id,
                endpoint="source",
                payload=card.payload,
                entity_cards=entity_cards,
                entity_cards_by_key=entity_cards_by_key,
            )
            target_id, target_error = await self._resolve_relationship_endpoint(
                novel_id=novel_id,
                endpoint="target",
                payload=card.payload,
                entity_cards=entity_cards,
                entity_cards_by_key=entity_cards_by_key,
            )
            if source_error:
                warnings.append(
                    f"Skipped relationship card {card.merge_key}: {source_error}"
                )
                continue
            if target_error:
                warnings.append(
                    f"Skipped relationship card {card.merge_key}: {target_error}"
                )
                continue
            relation_type = (card.payload.get("relation_type") or "").strip()
            if not relation_type:
                warnings.append(
                    f"Skipped relationship card {card.merge_key}: relation_type missing"
                )
                continue

            resolved_relationships.append(
                {
                    "source_id": source_id,
                    "target_id": target_id,
                    "relation_type": relation_type,
                    "meta": {
                        "card_id": card.card_id,
                        "card_type": card.card_type,
                        "merge_key": card.merge_key,
                        "title": card.title,
                        "summary": card.summary,
                        "source_outline_refs": list(card.source_outline_refs),
                        "source_entity_ref": card.payload.get("source_entity_ref"),
                        "target_entity_ref": card.payload.get("target_entity_ref"),
                        "source_entity_card_key": card.payload.get("source_entity_card_key"),
                        "target_entity_card_key": card.payload.get("target_entity_card_key"),
                    },
                }
            )

        return resolved_relationships, warnings

    async def _resolve_relationship_endpoint(
        self,
        novel_id: str,
        endpoint: str,
        payload: dict[str, Any],
        entity_cards: list[SettingSuggestionCardPayload],
        entity_cards_by_key: dict[str, SettingSuggestionCardPayload],
    ) -> tuple[str | None, str | None]:
        card_key = payload.get(f"{endpoint}_entity_card_key")
        if card_key:
            card = entity_cards_by_key.get(card_key)
            if card is None:
                return None, f"{endpoint} entity card {card_key} not found"
            return await self._resolve_persisted_entity_id_from_card(
                novel_id=novel_id,
                endpoint=endpoint,
                card=card,
                card_key=card_key,
            )

        entity_ref = (payload.get(f"{endpoint}_entity_ref") or "").strip()
        if entity_ref:
            (
                card_match,
                card_match_error,
            ) = self._find_unique_entity_card_by_name(
                endpoint=endpoint,
                entity_cards=entity_cards,
                entity_ref=entity_ref,
            )
            if card_match_error:
                return None, card_match_error
            if card_match is not None:
                entity_id, entity_error = await self._resolve_persisted_entity_id_from_card(
                    novel_id=novel_id,
                    endpoint=endpoint,
                    card=card_match,
                )
                if entity_id is not None:
                    return entity_id, None
                return None, entity_error

            entity_id, entity_error = await self._resolve_unique_entity_id_by_name(
                novel_id=novel_id,
                endpoint=endpoint,
                entity_ref=entity_ref,
            )
            if entity_id is not None:
                return entity_id, None
            return None, entity_error

        if entity_ref:
            return None, f"{endpoint} entity ref {entity_ref} not found"
        return None, f"{endpoint} entity reference missing"

    async def _resolve_persisted_entity_id_from_card(
        self,
        novel_id: str,
        endpoint: str,
        card: SettingSuggestionCardPayload,
        card_key: str | None = None,
    ) -> tuple[str | None, str | None]:
        entity_name = self._extract_card_entity_name(card)
        entity_type = self._normalize_card_entity_type(card.card_type)
        entity_id, entity_error = await self._resolve_unique_entity_id_by_name(
            novel_id=novel_id,
            endpoint=endpoint,
            entity_ref=entity_name,
            entity_type=entity_type,
        )
        if entity_id is not None:
            return entity_id, None

        if card_key is not None:
            return None, (
                f"{endpoint} entity card {card_key} resolved to {entity_name} "
                f"but {entity_error}"
            )
        return None, entity_error

    async def _resolve_unique_entity_id_by_name(
        self,
        novel_id: str,
        endpoint: str,
        entity_ref: str,
        entity_type: str | None = None,
    ) -> tuple[str | None, str]:
        candidates = await self.extraction_service.entity_svc.entity_repo.list_by_novel(novel_id)
        if entity_type is not None:
            candidates = [entity for entity in candidates if entity.type == entity_type]

        matches = self._match_entities_by_name(candidates, entity_ref)
        if len(matches) == 1:
            return matches[0].id, ""
        if len(matches) > 1:
            return None, f"{endpoint} entity ref {entity_ref} is ambiguous"
        return None, f"{endpoint} entity ref {entity_ref} not found"

    def _match_entities_by_name(
        self,
        candidates: list[Any],
        entity_ref: str,
    ) -> list[Any]:
        repo = self.extraction_service.entity_svc.entity_repo
        exact_matches = [entity for entity in candidates if entity.name == entity_ref]
        if exact_matches:
            return exact_matches

        normalized_ref = repo.normalize_name(entity_ref)
        if not normalized_ref:
            return []

        normalized_matches = [
            entity
            for entity in candidates
            if repo.normalize_name(entity.name) == normalized_ref
        ]
        return normalized_matches

    def _find_unique_entity_card_by_name(
        self,
        endpoint: str,
        entity_cards: list[SettingSuggestionCardPayload],
        entity_ref: str,
    ) -> tuple[SettingSuggestionCardPayload | None, str | None]:
        normalize_name = self.extraction_service.entity_svc.entity_repo.normalize_name
        exact_matches = []
        for card in entity_cards:
            card_name = self._extract_card_entity_name(card)
            if card_name == entity_ref:
                exact_matches.append(card)
        if len(exact_matches) == 1:
            return exact_matches[0], None
        if len(exact_matches) > 1:
            return None, f"{endpoint} entity ref {entity_ref} is ambiguous"

        normalized_ref = normalize_name(entity_ref)
        if not normalized_ref:
            return None, None

        normalized_matches = []
        for card in entity_cards:
            card_name = self._extract_card_entity_name(card)
            if normalized_ref and normalize_name(card_name) == normalized_ref:
                normalized_matches.append(card)
        if len(normalized_matches) == 1:
            return normalized_matches[0], None
        if len(normalized_matches) > 1:
            return None, f"{endpoint} entity ref {entity_ref} is ambiguous"
        return None, None

    def _extract_card_entity_name(
        self,
        card: SettingSuggestionCardPayload,
    ) -> str:
        payload_name = card.payload.get("canonical_name") or card.payload.get("name")
        if isinstance(payload_name, str) and payload_name.strip():
            return payload_name.strip()
        return card.title.strip()

    def _normalize_card_entity_type(self, card_type: str) -> str:
        if card_type in {"item", "artifact_or_skill", "artifact", "skill"}:
            return "item"
        return card_type
