import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.agents._llm_helpers import call_and_parse_model
from novel_dev.agents.setting_workbench_agent import (
    SettingBatchDraft,
    SettingBatchChangeDraft,
    SettingClarificationDecision,
    SettingWorkbenchAgent,
)
from novel_dev.db.models import EntityRelationship, NovelDocument, SettingReviewBatch, SettingReviewChange
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.relationship_repo import RelationshipRepository
from novel_dev.repositories.setting_workbench_repo import SettingWorkbenchRepository
from novel_dev.services.entity_service import EntityService


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex}"


class SettingWorkbenchService:
    MAX_CLARIFICATION_ROUNDS = 5

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = SettingWorkbenchRepository(session)
        self.doc_repo = DocumentRepository(session)
        self.entity_service = EntityService(session)
        self.relationship_repo = RelationshipRepository(session)

    async def _release_connection_before_external_call(self) -> None:
        if self.session.in_transaction():
            await self.session.commit()

    async def create_generation_session(
        self,
        *,
        novel_id: str,
        title: str,
        initial_idea: str = "",
        target_categories: list[str] | None = None,
        focused_target: dict[str, Any] | None = None,
    ):
        setting_session = await self.repo.create_session(
            novel_id=novel_id,
            title=title,
            target_categories=target_categories or [],
            focused_target=focused_target,
        )
        if initial_idea.strip():
            await self.repo.add_message(
                session_id=setting_session.id,
                role="user",
                content=initial_idea.strip(),
            )
        await self.session.flush()
        return setting_session

    async def reply_to_session(self, *, novel_id: str, session_id: str, content: str) -> dict[str, Any]:
        setting_session = await self.repo.get_session(session_id)
        if setting_session is None or setting_session.novel_id != novel_id:
            raise ValueError("Setting generation session not found")

        await self.repo.add_message(session_id=session_id, role="user", content=content.strip())
        messages = await self.repo.list_messages(session_id)
        prompt = SettingWorkbenchAgent.build_clarification_prompt(
            title=setting_session.title,
            target_categories=setting_session.target_categories or [],
            messages=self._message_items(messages),
            conversation_summary=setting_session.conversation_summary,
            max_rounds=self.MAX_CLARIFICATION_ROUNDS,
        )
        await self._release_connection_before_external_call()
        decision = await call_and_parse_model(
            agent_name="SettingWorkbenchService",
            task="setting_workbench_clarify",
            prompt=prompt,
            model_cls=SettingClarificationDecision,
            config_agent_name="setting_workbench_service",
            novel_id=novel_id,
            max_retries=2,
        )

        next_round = setting_session.clarification_round + 1
        next_status = (
            "ready_to_generate"
            if decision.status == "ready" or next_round >= self.MAX_CLARIFICATION_ROUNDS
            else "clarifying"
        )
        updated = await self.repo.update_session_state(
            session_id,
            status=next_status,
            clarification_round=next_round,
            conversation_summary=decision.conversation_summary,
        )
        if updated is None:
            raise ValueError("Setting generation session not found")
        if decision.target_categories:
            updated.target_categories = decision.target_categories
        await self.repo.add_message(
            session_id=session_id,
            role="assistant",
            content=decision.assistant_message,
            metadata={
                "questions": decision.questions,
                "status": decision.status,
                "ready_to_generate": next_status == "ready_to_generate",
            },
        )
        await self.session.flush()
        return {
            "session": updated,
            "assistant_message": decision.assistant_message,
            "questions": decision.questions,
        }

    async def generate_review_batch(self, *, novel_id: str, session_id: str):
        setting_session = await self.repo.get_session(session_id)
        if setting_session is None or setting_session.novel_id != novel_id:
            raise ValueError("Setting generation session not found")
        if setting_session.status not in {"ready_to_generate", "generated"}:
            raise ValueError("Setting session is not ready to generate")

        await self.repo.update_session_state(session_id, status="generating")
        messages = await self.repo.list_messages(session_id)
        prompt = SettingWorkbenchAgent.build_generation_prompt(
            title=setting_session.title,
            target_categories=setting_session.target_categories or [],
            messages=self._message_items(messages),
            conversation_summary=setting_session.conversation_summary,
            focused_context=setting_session.focused_target,
        )
        await self._release_connection_before_external_call()
        try:
            draft = await call_and_parse_model(
                agent_name="SettingWorkbenchService",
                task="setting_workbench_generate_batch",
                prompt=prompt,
                model_cls=SettingBatchDraft,
                config_agent_name="setting_workbench_service",
                novel_id=novel_id,
                max_retries=2,
            )
            self._validate_batch_draft(draft)

            batch = await self.repo.create_review_batch(
                novel_id=novel_id,
                source_type="ai_session",
                source_session_id=session_id,
                summary=draft.summary,
            )
            for item in draft.changes:
                await self.repo.add_review_change(
                    batch_id=batch.id,
                    target_type=item.target_type,
                    operation=item.operation,
                    target_id=item.target_id,
                    before_snapshot=item.before_snapshot,
                    after_snapshot=item.after_snapshot,
                    conflict_hints=item.conflict_hints,
                    source_session_id=session_id,
                )
            await self.repo.update_session_state(session_id, status="generated")
            await self.repo.add_message(
                session_id=session_id,
                role="assistant",
                content=f"已生成审核记录：{draft.summary}",
                metadata={"batch_id": batch.id},
            )
            await self.session.flush()
            return batch
        except Exception as exc:
            await self._restore_generation_ready_after_failure(session_id, exc)
            raise

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
                doc_id=_new_id("doc_"),
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
        if operation == "create":
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
        elif operation == "update":
            entity = await self._get_target_entity(novel_id, change)
            state_fields = snapshot.get("state") or snapshot.get("data") or {}
            if not isinstance(state_fields, dict):
                raise ValueError("Entity state must be an object")
            name = (snapshot.get("name") or entity.name or "").strip()
            entity_type = (snapshot.get("type") or snapshot.get("entity_type") or entity.type or "").strip()
            entity = await self.entity_service.update_entity_fields(
                entity.id,
                name=name,
                entity_type=entity_type,
                state_fields=state_fields,
            )
        elif operation == "delete":
            entity = await self._get_target_entity(novel_id, change)
            entity = await self.entity_service.update_entity_fields(
                entity.id,
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
        if operation == "create":
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
        if operation == "update":
            relationship = await self._get_target_relationship(novel_id, change)
            if "source_id" in snapshot:
                relationship.source_id = snapshot["source_id"]
            if "target_id" in snapshot:
                relationship.target_id = snapshot["target_id"]
            if "relation_type" in snapshot:
                relationship.relation_type = snapshot["relation_type"]
            meta = dict(snapshot.get("meta") if "meta" in snapshot else (relationship.meta or {}))
            meta["source"] = "setting_workbench"
            relationship.meta = meta
            self._stamp_source(relationship, batch, change)
            await self.session.flush()
            return relationship
        if operation == "delete":
            relationship = await self._get_target_relationship(novel_id, change)
            self._stamp_source(relationship, batch, change)
            relationship.is_active = False
            await self.session.flush()
            return relationship
        raise ValueError(f"Unsupported relationship operation: {operation}")

    async def _get_target_document(self, novel_id: str, change: SettingReviewChange) -> NovelDocument:
        if not change.target_id:
            raise ValueError("Setting card target_id is required")
        document = await self.doc_repo.get_by_id(change.target_id)
        if document is None or document.novel_id != novel_id:
            raise ValueError("Setting card not found")
        return document

    async def _get_target_entity(self, novel_id: str, change: SettingReviewChange):
        if not change.target_id:
            raise ValueError("Entity target_id is required")
        entity = await self.entity_service.entity_repo.get_by_id(change.target_id)
        if entity is None or entity.novel_id != novel_id:
            raise ValueError("Entity not found")
        return entity

    async def _get_target_relationship(self, novel_id: str, change: SettingReviewChange) -> EntityRelationship:
        if not change.target_id:
            raise ValueError("Relationship target_id is required")
        try:
            relationship_id = int(change.target_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("Relationship target_id is invalid") from exc
        relationship = await self.relationship_repo.get_by_id(relationship_id)
        if relationship is None or relationship.novel_id != novel_id:
            raise ValueError("Relationship not found")
        return relationship

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
    def _message_items(messages: list[Any]) -> list[dict[str, Any]]:
        return [{"role": message.role, "content": message.content} for message in messages]

    def _validate_batch_draft(self, draft: SettingBatchDraft) -> None:
        if not draft.changes:
            raise ValueError("Draft must contain at least one change")
        same_batch_entity_ids = self._same_batch_entity_create_ids(draft.changes)
        same_batch_entity_names_without_ids = self._same_batch_entity_create_names_without_ids(draft.changes)
        for index, item in enumerate(draft.changes):
            self._validate_draft_change(
                item,
                index=index,
                same_batch_entity_ids=same_batch_entity_ids,
                same_batch_entity_names_without_ids=same_batch_entity_names_without_ids,
            )

    @staticmethod
    def _same_batch_entity_create_ids(changes: list[SettingBatchChangeDraft]) -> set[str]:
        entity_ids: set[str] = set()
        for item in changes:
            if item.target_type != "entity" or item.operation != "create":
                continue
            snapshot = item.after_snapshot or {}
            entity_id = str(snapshot.get("id") or "").strip()
            if entity_id:
                entity_ids.add(entity_id)
        return entity_ids

    @staticmethod
    def _same_batch_entity_create_names_without_ids(changes: list[SettingBatchChangeDraft]) -> set[str]:
        entity_names: set[str] = set()
        for item in changes:
            if item.target_type != "entity" or item.operation != "create":
                continue
            snapshot = item.after_snapshot or {}
            if str(snapshot.get("id") or "").strip():
                continue
            name = str(snapshot.get("name") or "").strip()
            if name:
                entity_names.add(name)
        return entity_names

    @staticmethod
    def _validate_draft_change(
        item: SettingBatchChangeDraft,
        *,
        index: int,
        same_batch_entity_ids: set[str] | None = None,
        same_batch_entity_names_without_ids: set[str] | None = None,
    ) -> None:
        if item.operation in {"update", "delete"} and not (item.target_id or "").strip():
            raise ValueError(f"Draft change {index} {item.target_type} {item.operation} target_id is required")

        if item.target_type == "relationship" and item.operation == "create":
            snapshot = item.after_snapshot or {}
            ref_fields = [
                field
                for field in ("source_ref", "target_ref")
                if str(snapshot.get(field) or "").strip()
            ]
            if (item.target_ref or "").strip():
                ref_fields.append("target_ref")
            if ref_fields:
                raise ValueError(
                    f"Draft change {index} relationship create must not use ref fields: {', '.join(ref_fields)}"
                )
            missing = [
                field
                for field in ("source_id", "target_id", "relation_type")
                if not str(snapshot.get(field) or "").strip()
            ]
            if missing:
                raise ValueError(
                    f"Draft change {index} relationship create after_snapshot missing: {', '.join(missing)}"
                )
            same_batch_entity_ids = same_batch_entity_ids or set()
            same_batch_entity_names_without_ids = same_batch_entity_names_without_ids or set()
            endpoints = {
                "source_id": str(snapshot.get("source_id") or "").strip(),
                "target_id": str(snapshot.get("target_id") or "").strip(),
            }
            for field, endpoint in endpoints.items():
                if endpoint in same_batch_entity_ids:
                    continue
                if endpoint in same_batch_entity_names_without_ids:
                    raise ValueError(
                        f"Draft change {index} relationship create {field} references same-batch entity create "
                        "without after_snapshot.id"
                    )

    async def _restore_generation_ready_after_failure(self, session_id: str, exc: Exception) -> None:
        if self.session.in_transaction():
            await self.session.rollback()

        await self.repo.update_session_state(session_id, status="ready_to_generate")
        await self.repo.add_message(
            session_id=session_id,
            role="assistant",
            content=f"生成审核批次失败：{exc}",
            metadata={
                "status": "error",
                "error": str(exc),
                "stage": "setting_workbench_generate_batch",
            },
        )
        await self.session.commit()

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
