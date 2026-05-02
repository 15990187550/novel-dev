import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import EntityRelationship, NovelDocument, SettingReviewBatch, SettingReviewChange
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.relationship_repo import RelationshipRepository
from novel_dev.repositories.setting_workbench_repo import SettingWorkbenchRepository
from novel_dev.services.entity_service import EntityService


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex}"


class SettingWorkbenchService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = SettingWorkbenchRepository(session)
        self.doc_repo = DocumentRepository(session)
        self.entity_service = EntityService(session)
        self.relationship_repo = RelationshipRepository(session)

    async def apply_review_decisions(self, novel_id: str, batch_id: str, decisions: list[dict]) -> dict:
        batch = await self.repo.get_review_batch(batch_id)
        if batch is None or batch.novel_id != novel_id:
            raise ValueError("Review batch not found")
        if batch.status not in {"pending", "partially_approved", "failed"}:
            raise ValueError("Review batch is not reviewable")

        decision_by_change_id = {
            decision.get("change_id"): decision
            for decision in decisions
            if decision.get("change_id")
        }
        changes = await self.repo.list_review_changes(batch.id)
        applied = 0
        rejected = 0
        failed = 0

        for change in changes:
            if change.status != "pending":
                continue
            decision = decision_by_change_id.get(change.id)
            if decision is None:
                continue

            decision_value = decision.get("decision")
            if decision_value == "reject":
                await self.repo.update_change_status(change.id, "rejected", error_message=None)
                rejected += 1
                continue

            if decision_value not in {"approve", "edit_approve"}:
                await self.repo.update_change_status(
                    change.id,
                    "failed",
                    error_message=f"Unsupported review decision: {decision_value}",
                )
                failed += 1
                continue

            snapshot = change.after_snapshot or {}
            if decision_value == "edit_approve":
                snapshot = decision.get("edited_after_snapshot") or {}

            try:
                async with self.session.begin_nested():
                    await self._apply_change(novel_id, batch, change, snapshot)
            except Exception as exc:
                await self.repo.update_change_status(change.id, "failed", error_message=str(exc))
                failed += 1
                continue

            status = "edited_approved" if decision_value == "edit_approve" else "approved"
            await self.repo.update_change_status(change.id, status, error_message=None)
            applied += 1

        changes = await self.repo.list_review_changes(batch.id)
        batch_status = self._resolve_batch_status(changes, batch.status)
        await self.repo.update_batch_status(batch.id, batch_status, error_message=None)
        return {"status": batch_status, "applied": applied, "rejected": rejected, "failed": failed}

    async def _apply_change(
        self,
        novel_id: str,
        batch: SettingReviewBatch,
        change: SettingReviewChange,
        snapshot: dict,
    ) -> None:
        if change.target_type == "setting_card":
            await self._apply_setting_card_change(novel_id, batch, change, snapshot)
            return
        if change.target_type == "entity":
            await self._apply_entity_change(novel_id, batch, change, snapshot)
            return
        if change.target_type == "relationship":
            await self._apply_relationship_change(novel_id, batch, change, snapshot)
            return
        raise ValueError(f"Unsupported setting review target_type: {change.target_type}")

    async def _apply_setting_card_change(
        self,
        novel_id: str,
        batch: SettingReviewBatch,
        change: SettingReviewChange,
        snapshot: dict,
    ) -> NovelDocument:
        operation = change.operation
        if operation == "create":
            content = self._required_content(snapshot)
            document = await self.doc_repo.create(
                doc_id=snapshot.get("id") or _new_id("doc_"),
                novel_id=novel_id,
                doc_type=(snapshot.get("doc_type") or "setting").strip() or "setting",
                title=(snapshot.get("title") or "未命名设定").strip() or "未命名设定",
                content=content,
                version=1,
            )
        elif operation == "update":
            existing = await self._get_target_document(novel_id, change)
            content = self._required_content(snapshot)
            document = await self.doc_repo.create(
                doc_id=snapshot.get("id") or _new_id("doc_"),
                novel_id=novel_id,
                doc_type=(snapshot.get("doc_type") or existing.doc_type).strip() or existing.doc_type,
                title=(snapshot.get("title") or existing.title).strip() or existing.title,
                content=content,
                version=(existing.version or 0) + 1,
            )
        elif operation == "delete":
            document = await self._get_target_document(novel_id, change)
            if not document.content.startswith("[已归档]\n"):
                document.content = f"[已归档]\n{document.content}"
        else:
            raise ValueError(f"Unsupported setting_card operation: {operation}")

        self._stamp_source(document, batch, change)
        await self.session.flush()
        return document

    async def _apply_entity_change(
        self,
        novel_id: str,
        batch: SettingReviewBatch,
        change: SettingReviewChange,
        snapshot: dict,
    ):
        operation = change.operation
        if operation in {"create", "update"}:
            name = (snapshot.get("name") or "").strip()
            if not name:
                raise ValueError("Entity name is required")
            entity_type = (snapshot.get("type") or snapshot.get("entity_type") or "other").strip() or "other"
            initial_state = snapshot.get("state") or snapshot.get("data") or {}
            if not isinstance(initial_state, dict):
                raise ValueError("Entity state must be an object")
            entity = await self.entity_service.create_or_update_entity(
                snapshot.get("id") or change.target_id or _new_id("ent_"),
                entity_type,
                name,
                novel_id=novel_id,
                initial_state=initial_state,
            )
        elif operation == "delete":
            if not change.target_id:
                raise ValueError("Entity target_id is required")
            entity = await self.entity_service.update_entity_fields(
                change.target_id,
                state_fields={
                    "_archived": True,
                    "_archive_reason": snapshot.get("archive_reason") or "setting_workbench_delete",
                },
            )
        else:
            raise ValueError(f"Unsupported entity operation: {operation}")

        self._stamp_source(entity, batch, change)
        await self.session.flush()
        return entity

    async def _apply_relationship_change(
        self,
        novel_id: str,
        batch: SettingReviewBatch,
        change: SettingReviewChange,
        snapshot: dict,
    ) -> EntityRelationship | None:
        operation = change.operation
        if operation in {"create", "update"}:
            source_id = snapshot.get("source_id")
            target_id = snapshot.get("target_id")
            relation_type = snapshot.get("relation_type")
            if not source_id or not target_id or not relation_type:
                raise ValueError("Relationship source_id, target_id, and relation_type are required")
            meta = dict(snapshot.get("meta") or {})
            meta["source"] = "setting_workbench"
            relationship = await self.relationship_repo.upsert(
                source_id=source_id,
                target_id=target_id,
                relation_type=relation_type,
                meta=meta,
                novel_id=novel_id,
            )
            self._stamp_source(relationship, batch, change)
            await self.session.flush()
            return relationship
        if operation == "delete":
            if not change.target_id:
                raise ValueError("Relationship target_id is required")
            await self.relationship_repo.deactivate(int(change.target_id))
            return None
        raise ValueError(f"Unsupported relationship operation: {operation}")

    async def _get_target_document(self, novel_id: str, change: SettingReviewChange) -> NovelDocument:
        if not change.target_id:
            raise ValueError("Setting card target_id is required")
        document = await self.doc_repo.get_by_id(change.target_id)
        if document is None or document.novel_id != novel_id:
            raise ValueError("Setting card not found")
        return document

    @staticmethod
    def _required_content(snapshot: dict) -> str:
        content = (snapshot.get("content") or "").strip()
        if not content:
            raise ValueError("Setting card content is required")
        return content

    @staticmethod
    def _stamp_source(target: Any, batch: SettingReviewBatch, change: SettingReviewChange) -> None:
        target.source_type = "ai"
        target.source_session_id = change.source_session_id or batch.source_session_id
        target.source_review_batch_id = batch.id
        target.source_review_change_id = change.id

    @staticmethod
    def _resolve_batch_status(changes: list[SettingReviewChange], current_status: str) -> str:
        statuses = [change.status for change in changes]
        if not statuses or all(status == "pending" for status in statuses):
            return current_status

        approved_statuses = {"approved", "edited_approved"}
        approved_count = sum(1 for status in statuses if status in approved_statuses)
        rejected_count = sum(1 for status in statuses if status == "rejected")
        failed_count = sum(1 for status in statuses if status == "failed")

        if approved_count == len(statuses):
            return "approved"
        if rejected_count == len(statuses):
            return "rejected"
        if failed_count > 0 and approved_count == 0:
            return "failed"
        return "partially_approved"
