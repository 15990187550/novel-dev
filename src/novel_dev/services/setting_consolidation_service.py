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
            current_docs = await self.doc_repo.get_current_by_type(novel_id, doc_type)
            for doc in current_docs:
                if getattr(doc, "archived_at", None) is not None:
                    continue
                documents.append(
                    {
                        "id": doc.id,
                        "doc_type": doc.doc_type,
                        "title": doc.title,
                        "content": doc.content,
                        "version": doc.version,
                    }
                )

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

        result = await self.session.execute(
            select(EntityRelationship)
            .where(
                EntityRelationship.novel_id == novel_id,
                EntityRelationship.is_active == True,
            )
            .order_by(EntityRelationship.id.asc())
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
