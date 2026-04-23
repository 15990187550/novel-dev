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
    BrainstormWorkspacePayload,
    BrainstormWorkspaceSubmitResponse,
    SettingDocDraftPayload,
    SettingSuggestionCardMergePayload,
    SettingSuggestionCardPayload,
)
from novel_dev.schemas.outline import SynopsisData
from novel_dev.services.extraction_service import ExtractionService


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

            incoming = SettingSuggestionCardPayload.model_validate(
                normalized_update.model_dump(exclude={"operation"}, exclude_none=True)
            ).model_dump()
            existing = by_merge_key.get(merge_key)
            if existing is None:
                if merge_key in superseded_merge_keys:
                    incoming["status"] = "superseded"
                by_merge_key[merge_key] = incoming
                continue

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
            existing["display_order"] = incoming["display_order"]
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

    def list_active_suggestion_cards(
        self,
        workspace_payload: BrainstormWorkspacePayload,
    ) -> list[SettingSuggestionCardPayload]:
        return [
            card
            for card in workspace_payload.setting_suggestion_cards
            if card.status in {"active", "unresolved"}
        ]

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
        entity_cards_by_name = {
            self._extract_card_entity_name(card): card
            for card in entity_cards
            if self._extract_card_entity_name(card)
        }

        for card in cards:
            source_id, source_error = await self._resolve_relationship_endpoint(
                novel_id=novel_id,
                endpoint="source",
                payload=card.payload,
                entity_cards=entity_cards,
                entity_cards_by_key=entity_cards_by_key,
                entity_cards_by_name=entity_cards_by_name,
            )
            target_id, target_error = await self._resolve_relationship_endpoint(
                novel_id=novel_id,
                endpoint="target",
                payload=card.payload,
                entity_cards=entity_cards,
                entity_cards_by_key=entity_cards_by_key,
                entity_cards_by_name=entity_cards_by_name,
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
        entity_cards_by_name: dict[str, SettingSuggestionCardPayload],
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
            card_match = entity_cards_by_name.get(entity_ref) or self._find_entity_card_by_name(
                entity_cards,
                entity_ref,
            )
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
        if normalized_matches:
            return normalized_matches

        close_matches = [
            entity
            for entity in candidates
            if repo._is_close_name_match(repo.normalize_name(entity.name), normalized_ref)
        ]
        return close_matches

    def _find_entity_card_by_name(
        self,
        entity_cards: list[SettingSuggestionCardPayload],
        entity_ref: str,
    ) -> SettingSuggestionCardPayload | None:
        normalize_name = self.extraction_service.entity_svc.entity_repo.normalize_name
        normalized_ref = normalize_name(entity_ref)
        for card in entity_cards:
            card_name = self._extract_card_entity_name(card)
            if card_name == entity_ref:
                return card
            if normalized_ref and normalize_name(card_name) == normalized_ref:
                return card
        return None

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
