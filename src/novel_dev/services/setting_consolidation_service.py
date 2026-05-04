from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.agents.setting_consolidation_agent import SettingConsolidationAgent
from novel_dev.db.models import EntityRelationship
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.pending_extraction_repo import PendingExtractionRepository
from novel_dev.repositories.relationship_repo import RelationshipRepository
from novel_dev.repositories.setting_workbench_repo import SettingWorkbenchRepository
from novel_dev.services.log_service import log_service


class SettingConsolidationService:
    def __init__(self, session: AsyncSession, agent: SettingConsolidationAgent | None = None):
        self.session = session
        self.agent = agent or SettingConsolidationAgent()
        self.doc_repo = DocumentRepository(session)
        self.pending_repo = PendingExtractionRepository(session)
        self.setting_repo = SettingWorkbenchRepository(session)
        self.entity_repo = EntityRepository(session)
        self.relationship_repo = RelationshipRepository(session)

    async def build_input_snapshot(self, novel_id: str, selected_pending_ids: list[str]) -> dict[str, Any]:
        documents = []
        for doc_type in ("worldview", "setting", "synopsis", "concept"):
            active_docs_by_title = {}
            for doc in await self.doc_repo.get_by_type(novel_id, doc_type):
                if doc.archived_at is not None:
                    continue
                current = active_docs_by_title.get(doc.title)
                if current is None or self._is_newer_document(doc, current):
                    active_docs_by_title[doc.title] = doc
            for doc in active_docs_by_title.values():
                documents.append(
                    {
                        "id": doc.id,
                        "doc_type": doc.doc_type,
                        "title": doc.title,
                        "content": doc.content,
                        "version": doc.version,
                    }
                )
        documents.sort(key=lambda doc: (doc["doc_type"] or "", doc["title"] or "", doc["id"] or ""))

        selected_pending = []
        for pending_id in selected_pending_ids:
            pending = await self.pending_repo.get_by_id(pending_id)
            if pending is None or pending.novel_id != novel_id:
                raise ValueError(f"待审核记录不存在或不属于当前小说: {pending_id}")
            if pending.status != "pending":
                raise ValueError(f"只能选择 pending 状态的审核记录: {pending_id}")
            selected_pending.append(
                {
                    "id": pending.id,
                    "source_filename": pending.source_filename,
                    "extraction_type": pending.extraction_type,
                    "raw_result": pending.raw_result,
                    "proposed_entities": pending.proposed_entities or [],
                    "diff_result": pending.diff_result or {},
                }
            )

        entities = []
        for entity in await self.entity_repo.list_by_novel(novel_id):
            if getattr(entity, "archived_at", None) is not None:
                continue
            entities.append(
                {
                    "id": entity.id,
                    "type": entity.type,
                    "name": entity.name,
                    "current_version": entity.current_version,
                    "system_category": entity.system_category,
                    "manual_category": entity.manual_category,
                    "search_document": entity.search_document,
                }
            )
        entities.sort(key=lambda entity: (entity["type"] or "", entity["name"] or "", entity["id"] or ""))

        result = await self.session.execute(
            select(EntityRelationship)
            .where(
                EntityRelationship.novel_id == novel_id,
                EntityRelationship.is_active == True,
            )
        )
        relationships = []
        for relationship in result.scalars().all():
            if getattr(relationship, "archived_at", None) is not None:
                continue
            relationships.append(
                {
                    "id": relationship.id,
                    "source_id": relationship.source_id,
                    "target_id": relationship.target_id,
                    "relation_type": relationship.relation_type,
                    "meta": relationship.meta or {},
                }
            )
        relationships.sort(
            key=lambda relationship: (
                relationship["source_id"] or "",
                relationship["target_id"] or "",
                relationship["relation_type"] or "",
                relationship["id"] or 0,
            )
        )

        return {
            "novel_id": novel_id,
            "created_at": datetime.utcnow().isoformat(),
            "documents": documents,
            "entities": entities,
            "relationships": relationships,
            "selected_pending": selected_pending,
        }

    async def run_consolidation(
        self,
        *,
        novel_id: str,
        selected_pending_ids: list[str],
        job_id: str | None = None,
        input_snapshot: dict[str, Any] | None = None,
    ):
        snapshot = input_snapshot or await self.build_input_snapshot(novel_id, selected_pending_ids)
        log_service.add_log(
            novel_id,
            "SettingConsolidationService",
            "设定整合开始",
            metadata={
                "document_count": len(snapshot.get("documents", [])),
                "selected_pending_count": len(snapshot.get("selected_pending", [])),
            },
        )

        result = await self.agent.consolidate(snapshot)
        batch = await self.setting_repo.create_review_batch(
            novel_id=novel_id,
            source_type="consolidation",
            summary=result.get("summary") or "",
            input_snapshot=snapshot,
            job_id=job_id,
        )
        for change in result.get("changes") or []:
            await self.setting_repo.add_review_change(
                batch_id=batch.id,
                target_type=change["target_type"],
                operation=change["operation"],
                target_id=change.get("target_id"),
                before_snapshot=change.get("before_snapshot"),
                after_snapshot=change.get("after_snapshot"),
                conflict_hints=change.get("conflict_hints") or [],
            )

        log_service.add_log(
            novel_id,
            "SettingConsolidationService",
            f"设定整合生成审核记录：{batch.summary}",
            metadata={"batch_id": batch.id, "job_id": job_id},
        )
        return batch

    async def approve_review_batch(
        self,
        batch_id: str,
        *,
        change_ids: list[str] | None = None,
        approve_all: bool = False,
    ):
        batch = await self.setting_repo.get_review_batch(batch_id)
        if batch is None:
            raise ValueError("审核记录不存在")

        changes = await self.setting_repo.list_review_changes(batch.id)
        pending_changes = [change for change in changes if change.status == "pending"]
        unresolved_conflicts = [
            change for change in pending_changes
            if change.target_type == "conflict"
        ]
        if approve_all and unresolved_conflicts:
            raise ValueError("存在未解决冲突，不能整体通过")

        if approve_all:
            selected_changes = pending_changes
        else:
            selected_ids = set(change_ids or [])
            if not selected_ids:
                raise ValueError("未选择审核变更")
            changes_by_id = {change.id: change for change in changes}
            missing_ids = selected_ids - set(changes_by_id)
            if missing_ids:
                raise ValueError(f"审核变更不存在或不属于当前批次: {', '.join(sorted(missing_ids))}")
            non_pending_ids = sorted(
                change_id
                for change_id in selected_ids
                if changes_by_id[change_id].status != "pending"
            )
            if non_pending_ids:
                raise ValueError(f"审核变更不是 pending 状态: {', '.join(non_pending_ids)}")
            selected_changes = [
                change for change in pending_changes
                if change.id in selected_ids
            ]
        selected_conflicts = [
            change for change in selected_changes
            if change.target_type == "conflict"
        ]
        if selected_conflicts:
            raise ValueError("存在未解决冲突，不能直接通过")

        for change in selected_changes:
            try:
                async with self.session.begin_nested():
                    await self._apply_change(batch, change)
            except Exception as exc:
                await self.setting_repo.mark_change_status(change.id, "failed", error_message=str(exc))
            else:
                await self.setting_repo.mark_change_status(change.id, "approved", error_message=None)

        latest_changes = await self.setting_repo.list_review_changes(batch.id)
        approved_count = sum(
            1
            for change in latest_changes
            if change.status in {"approved", "edited_approved"}
        )
        pending_count = sum(1 for change in latest_changes if change.status == "pending")
        failed_count = sum(1 for change in latest_changes if change.status == "failed")
        if pending_count == 0 and failed_count == 0:
            await self.setting_repo.update_batch_status(batch.id, "approved")
        elif approved_count > 0:
            await self.setting_repo.update_batch_status(batch.id, "partially_approved")
        elif failed_count > 0 and pending_count == 0:
            await self.setting_repo.update_batch_status(batch.id, "failed")
        return await self.setting_repo.get_review_batch(batch.id)

    async def resolve_conflict_change(
        self,
        batch_id: str,
        *,
        change_id: str,
        resolved_after_snapshot: dict[str, Any],
    ):
        batch = await self.setting_repo.get_review_batch(batch_id)
        if batch is None:
            raise ValueError("审核记录不存在")
        change = await self.setting_repo.get_review_change(change_id)
        if change is None or change.batch_id != batch.id:
            raise ValueError("冲突项不存在或不属于当前审核记录")
        if change.status != "pending":
            raise ValueError("冲突项不是 pending 状态")
        if change.target_type != "conflict":
            raise ValueError("只能解决冲突项")
        title = (resolved_after_snapshot.get("title") or "").strip()
        content = (resolved_after_snapshot.get("content") or "").strip()
        if not title or not content:
            raise ValueError("解决后的设定卡必须包含标题和内容")

        await self.setting_repo.mark_change_status(
            change.id,
            "resolved",
            after_snapshot=resolved_after_snapshot,
            error_message=None,
        )
        await self.setting_repo.add_review_change(
            batch_id=batch.id,
            target_type="setting_card",
            operation="create",
            after_snapshot={
                **resolved_after_snapshot,
                "doc_type": resolved_after_snapshot.get("doc_type") or "setting",
            },
            conflict_hints=change.conflict_hints or [],
            source_session_id=change.source_session_id,
        )
        await self.setting_repo.update_batch_status(batch.id, "ready_for_review")
        return await self.setting_repo.get_review_batch(batch.id)

    async def _apply_change(self, batch, change) -> None:
        if change.target_type == "conflict":
            raise ValueError("冲突项必须先提交解决结果")
        if change.operation == "archive":
            await self._archive_target(batch, change)
        elif change.target_type == "setting_card" and change.operation == "create":
            snapshot = change.after_snapshot or {}
            title = (snapshot.get("title") or "").strip()
            if not title:
                raise ValueError("设定卡标题不能为空")
            doc_id = f"setting_{change.id}"
            existing = await self.doc_repo.get_by_id(doc_id)
            if existing is not None:
                if existing.source_review_change_id == change.id:
                    return
                raise ValueError(f"设定卡已存在且来源不匹配: {doc_id}")
            doc = await self.doc_repo.create(
                doc_id,
                batch.novel_id,
                snapshot.get("doc_type") or "setting",
                title,
                snapshot.get("content") or "",
                version=1,
            )
            doc.source_type = "consolidation"
            doc.source_review_batch_id = batch.id
            doc.source_review_change_id = change.id
        else:
            raise ValueError(f"暂不支持的设定审核变更: {change.target_type}/{change.operation}")

    async def _archive_target(self, batch, change) -> None:
        if not change.target_id:
            raise ValueError("归档目标不存在: 空目标")
        if change.target_type == "setting_card":
            archived = await self.doc_repo.archive_for_consolidation(
                change.target_id,
                novel_id=batch.novel_id,
                batch_id=batch.id,
                change_id=change.id,
            )
        elif change.target_type == "entity":
            archived = await self.entity_repo.archive_for_consolidation(
                change.target_id,
                novel_id=batch.novel_id,
                batch_id=batch.id,
                change_id=change.id,
            )
        elif change.target_type == "relationship":
            archived = await self.relationship_repo.archive_for_consolidation(
                change.target_id,
                novel_id=batch.novel_id,
                batch_id=batch.id,
                change_id=change.id,
            )
        else:
            raise ValueError(f"不支持归档目标类型: {change.target_type}")
        if archived is None:
            raise ValueError(f"归档目标不存在: {change.target_id}")

    @staticmethod
    def _is_newer_document(candidate, current) -> bool:
        candidate_version = candidate.version or 0
        current_version = current.version or 0
        if candidate_version != current_version:
            return candidate_version > current_version
        candidate_updated = candidate.updated_at or datetime.min
        current_updated = current.updated_at or datetime.min
        if candidate_updated != current_updated:
            return candidate_updated > current_updated
        return candidate.id > current.id
