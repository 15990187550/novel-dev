import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.agents.brainstorm_agent import BrainstormAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.brainstorm_workspace_repo import BrainstormWorkspaceRepository
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
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

        pending_payloads = [
            await self.extraction_service.build_pending_payload_from_setting_draft(
                novel_id,
                draft,
            )
            for draft in (workspace.setting_docs_draft or [])
        ]
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
