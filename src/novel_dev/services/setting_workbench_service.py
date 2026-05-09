import asyncio
import re
import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.agents._llm_helpers import call_and_parse_model, orchestrated_call_and_parse_model
from novel_dev.agents.setting_workbench_agent import (
    SettingBatchDraft,
    SettingBatchChangeDraft,
    SettingClarificationDecision,
    SettingWorkbenchAgent,
)
from novel_dev.db.models import EntityRelationship, NovelDocument, SettingReviewBatch, SettingReviewChange
from novel_dev.llm import llm_factory
from novel_dev.llm.context_tools import build_mcp_context_tools
from novel_dev.llm.exceptions import LLMTimeoutError
from novel_dev.llm.orchestrator import LLMToolSpec, OrchestratedTaskConfig
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.relationship_repo import RelationshipRepository
from novel_dev.repositories.setting_workbench_repo import SettingWorkbenchRepository
from novel_dev.services.entity_context_sanitizer import INTERNAL_ENTITY_STATE_KEYS, sanitize_entity_state_for_context
from novel_dev.services.entity_service import EntityService
from novel_dev.services.log_service import log_service
from novel_dev.services.story_quality_service import SettingQualityReport, StoryQualityService


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex}"


class SettingWorkbenchService:
    MAX_CLARIFICATION_ROUNDS = 5
    GENERATE_BATCH_WALL_TIMEOUT_SECONDS = 300
    SOURCE_CRITICAL_MARKERS = (
        "外部宇宙",
        "跨作品",
        "对标",
        "境界映射",
        "境界对标",
        "联动",
    )
    SOURCE_TOPIC_KEYWORDS = (
        "修炼",
        "境界",
        "体系",
        "人物",
        "主角",
        "世界观",
        "设定",
    )
    SOURCE_COVERAGE_DOC_TYPES = (
        "domain_setting",
        "domain_worldview",
        "domain_synopsis",
        "domain_concept",
        "setting",
        "worldview",
        "synopsis",
        "concept",
    )
    KNOWN_EXTERNAL_DOMAINS = (
        "一世之尊",
        "仙逆",
        "遮天",
        "灭运图录",
        "阳神",
        "完美世界",
        "吞噬星空",
        "莽荒纪",
        "凡人修仙传",
        "星辰变",
    )
    CANONICAL_WORLD_PROTAGONISTS = {
        "一世之尊": "孟奇",
        "仙逆": "王林",
        "遮天": "叶凡",
        "灭运图录": "石轩",
        "阳神": "洪易",
        "完美世界": "石昊",
        "吞噬星空": "罗峰",
        "莽荒纪": "纪宁",
        "凡人修仙传": "韩立",
        "星辰变": "秦羽",
    }
    YISHI_REALM_RANKS = {
        "开窍": 1,
        "外景": 2,
        "法身": 3,
        "传说": 4,
        "造化": 5,
        "彼岸": 6,
    }

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
        current_setting_context = await self._build_generation_context(novel_id)
        prompt = SettingWorkbenchAgent.build_clarification_prompt(
            title=setting_session.title,
            target_categories=setting_session.target_categories or [],
            messages=self._message_items(messages),
            conversation_summary=setting_session.conversation_summary,
            max_rounds=self.MAX_CLARIFICATION_ROUNDS,
            current_setting_context=current_setting_context,
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
        generation_started_at = time.perf_counter()
        setting_session = await self.repo.get_session(session_id)
        if setting_session is None or setting_session.novel_id != novel_id:
            raise ValueError("Setting generation session not found")
        if setting_session.status not in {"ready_to_generate", "generated"}:
            raise ValueError("Setting session is not ready to generate")

        await self.repo.update_session_state(session_id, status="generating")
        messages = await self.repo.list_messages(session_id)
        message_items = self._message_items(messages)
        generation_message_items = self._message_items_for_generation(messages)
        required_sections = self._extract_suggested_generation_batches(messages)
        current_setting_context = await self._build_generation_context(novel_id)
        source_coverage = await self._build_source_coverage(
            novel_id=novel_id,
            title=setting_session.title,
            target_categories=setting_session.target_categories or [],
            messages=message_items,
            required_sections=required_sections,
        )
        current_setting_context["source_coverage"] = source_coverage
        orchestration_config = llm_factory.resolve_orchestration_config(
            "setting_workbench_service",
            "setting_workbench_generate_batch",
        )
        prompt_context = (
            self._build_generation_context_catalog(current_setting_context)
            if orchestration_config is not None
            else current_setting_context
        )
        prompt = SettingWorkbenchAgent.build_generation_prompt(
            title=setting_session.title,
            target_categories=setting_session.target_categories or [],
            messages=generation_message_items,
            conversation_summary=setting_session.conversation_summary,
            focused_context=setting_session.focused_target,
            current_setting_context=prompt_context,
            required_sections=required_sections,
        )
        context_stats = self._generation_context_stats(current_setting_context)
        common_metadata = {
            "session_id": session_id,
            "session_title": setting_session.title,
            "session_status": setting_session.status,
            "clarification_round": setting_session.clarification_round,
            "target_categories": setting_session.target_categories or [],
            "message_count": len(messages),
            "required_section_count": len(required_sections),
            "required_sections": required_sections,
            "context": context_stats,
            "source_coverage": source_coverage,
            "prompt_chars": len(prompt),
            "orchestration_enabled": orchestration_config is not None,
            "timeout_seconds": self.GENERATE_BATCH_WALL_TIMEOUT_SECONDS,
        }
        log_service.add_log(
            novel_id,
            "SettingWorkbenchService",
            "设定审核记录生成开始",
            event="agent.progress",
            status="started",
            node="setting_generate_prepare",
            task="setting_workbench_generate_batch",
            metadata=common_metadata,
        )
        await self._release_connection_before_external_call()
        try:
            self._validate_source_coverage(source_coverage)
            llm_started_at = time.perf_counter()
            log_service.add_log(
                novel_id,
                "SettingWorkbenchService",
                "开始调用模型生成设定审核草稿",
                event="agent.progress",
                status="started",
                node="setting_generate_llm",
                task="setting_workbench_generate_batch",
                metadata={
                    **common_metadata,
                    "model_path": "orchestrated" if orchestration_config is not None else "direct",
                    "tool_allowlist": list(orchestration_config.tool_allowlist) if orchestration_config is not None else [],
                    "max_tool_calls": orchestration_config.max_tool_calls if orchestration_config is not None else 0,
                },
            )
            try:
                async with asyncio.timeout(self.GENERATE_BATCH_WALL_TIMEOUT_SECONDS):
                    draft = await self._generate_draft_with_optional_section_split(
                        novel_id=novel_id,
                        setting_session=setting_session,
                        message_items=generation_message_items,
                        current_setting_context=current_setting_context,
                        prompt_context=prompt_context,
                        required_sections=required_sections,
                        orchestration_config=orchestration_config,
                        common_metadata=common_metadata,
                    )
            except TimeoutError as exc:
                raise LLMTimeoutError(
                    "Setting workbench generation timed out "
                    f"after {self.GENERATE_BATCH_WALL_TIMEOUT_SECONDS}s"
                ) from exc
            llm_duration_ms = self._elapsed_ms(llm_started_at)
            draft_stats = self._draft_stats(draft)
            log_service.add_log(
                novel_id,
                "SettingWorkbenchService",
                "模型已返回设定审核草稿",
                event="agent.progress",
                status="succeeded",
                node="setting_generate_llm",
                task="setting_workbench_generate_batch",
                metadata={
                    **common_metadata,
                    "draft": draft_stats,
                },
                duration_ms=llm_duration_ms,
            )

            self._validate_batch_draft(draft, required_sections=required_sections)
            setting_quality_report = self._evaluate_generated_setting_quality(draft)
            await self._validate_draft_source_evidence(novel_id, draft)
            log_service.add_log(
                novel_id,
                "SettingWorkbenchService",
                "设定审核草稿校验完成",
                event="agent.progress",
                status="succeeded",
                node="setting_generate_validate",
                task="setting_workbench_generate_batch",
                metadata={
                    **common_metadata,
                    "draft": draft_stats,
                },
                duration_ms=self._elapsed_ms(generation_started_at),
            )

            batch = await self.repo.create_review_batch(
                novel_id=novel_id,
                source_type="ai_session",
                source_session_id=session_id,
                summary=draft.summary,
                input_snapshot={"setting_quality_report": setting_quality_report.model_dump()},
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
            log_service.add_log(
                novel_id,
                "SettingWorkbenchService",
                f"设定审核记录已生成：{draft.summary}",
                event="agent.progress",
                status="succeeded",
                node="setting_generate_persist",
                task="setting_workbench_generate_batch",
                metadata={
                    **common_metadata,
                    "batch_id": batch.id,
                    "summary": draft.summary,
                    "change_count": len(draft.changes),
                    "draft": draft_stats,
                },
                duration_ms=self._elapsed_ms(generation_started_at),
            )
            return batch
        except Exception as exc:
            restore_error: Exception | None = None
            try:
                await self._restore_generation_ready_after_failure(session_id, exc)
            except Exception as restore_exc:
                restore_error = restore_exc
            self._log_generation_failure(
                novel_id=novel_id,
                metadata=common_metadata if "common_metadata" in locals() else {"session_id": session_id},
                started_at=generation_started_at,
                exc=exc,
                restore_error=restore_error,
            )
            if restore_error is not None:
                raise restore_error from exc
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

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return max(0, int((time.perf_counter() - started_at) * 1000))

    @staticmethod
    def _generation_context_stats(context: dict[str, Any]) -> dict[str, int]:
        return {
            "document_count": len(context.get("documents") or []),
            "entity_count": len(context.get("entities") or []),
            "relationship_count": len(context.get("relationships") or []),
        }

    @staticmethod
    def _draft_stats(draft: SettingBatchDraft) -> dict[str, Any]:
        target_counts: dict[str, int] = {}
        operation_counts: dict[str, int] = {}
        setting_titles: list[str] = []
        entity_names: list[str] = []
        for change in draft.changes:
            target_counts[change.target_type] = target_counts.get(change.target_type, 0) + 1
            operation_counts[change.operation] = operation_counts.get(change.operation, 0) + 1
            snapshot = change.after_snapshot or {}
            if change.target_type == "setting_card" and snapshot.get("title"):
                setting_titles.append(str(snapshot.get("title")))
            if change.target_type == "entity" and snapshot.get("name"):
                entity_names.append(str(snapshot.get("name")))
        return {
            "summary": draft.summary,
            "change_count": len(draft.changes),
            "target_counts": target_counts,
            "operation_counts": operation_counts,
            "setting_titles": setting_titles[:12],
            "entity_names": entity_names[:12],
        }

    def _log_generation_failure(
        self,
        *,
        novel_id: str,
        metadata: dict[str, Any],
        started_at: float,
        exc: Exception,
        restore_error: Exception | None = None,
    ) -> None:
        failure_metadata = {
            **metadata,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "timeout_seconds": self.GENERATE_BATCH_WALL_TIMEOUT_SECONDS,
        }
        if restore_error is not None:
            failure_metadata["restore_error_type"] = type(restore_error).__name__
            failure_metadata["restore_error"] = str(restore_error)
        log_service.add_log(
            novel_id,
            "SettingWorkbenchService",
            f"设定审核记录生成失败: {exc}",
            level="error",
            event="agent.progress",
            status="failed",
            node="setting_generate",
            task="setting_workbench_generate_batch",
            metadata=failure_metadata,
            duration_ms=self._elapsed_ms(started_at),
        )

    async def _build_generation_context(self, novel_id: str) -> dict[str, Any]:
        document_items: list[dict[str, Any]] = []
        for doc_type in (
            "worldview",
            "setting",
            "synopsis",
            "concept",
            "domain_worldview",
            "domain_setting",
            "domain_synopsis",
            "domain_concept",
        ):
            docs = await self.doc_repo.get_current_by_type(novel_id, doc_type)
            for doc in docs[:4]:
                document_items.append({
                    "id": doc.id,
                    "doc_type": doc.doc_type,
                    "title": doc.title,
                    "version": doc.version,
                    "content_preview": self._trim_text(doc.content, 900),
                })
            if len(document_items) >= 12:
                break

        entities = await self.entity_service.entity_repo.list_by_novel(novel_id)
        entities = sorted(
            entities,
            key=lambda item: (item.current_version or 0, item.name or ""),
            reverse=True,
        )[:30]
        latest_states = await self.entity_service.get_latest_states([entity.id for entity in entities])
        entity_items = [
            {
                "id": entity.id,
                "type": entity.type,
                "name": entity.name,
                "current_version": entity.current_version,
                "state": self._trim_struct(
                    sanitize_entity_state_for_context(latest_states.get(entity.id) or {}),
                    max_text=260,
                ),
            }
            for entity in entities
        ]

        relationship_result = await self.session.execute(
            select(EntityRelationship)
            .where(
                EntityRelationship.novel_id == novel_id,
                EntityRelationship.is_active == True,
            )
            .order_by(EntityRelationship.id.desc())
            .limit(50)
        )
        relationships = list(relationship_result.scalars().all())
        entity_name_by_id = {entity.id: entity.name for entity in entities}
        relationship_items = [
            {
                "id": relationship.id,
                "source_id": relationship.source_id,
                "source_name": entity_name_by_id.get(relationship.source_id, ""),
                "target_id": relationship.target_id,
                "target_name": entity_name_by_id.get(relationship.target_id, ""),
                "relation_type": relationship.relation_type,
            }
            for relationship in relationships
        ]

        return {
            "documents": document_items,
            "entities": entity_items,
            "relationships": relationship_items,
            "limits": {
                "documents": 12,
                "entities": 30,
                "relationships": 50,
                "content_preview_chars": 900,
            },
        }

    def _build_generation_context_catalog(self, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "documents": [
                {
                    "id": item.get("id"),
                    "doc_type": item.get("doc_type"),
                    "title": item.get("title"),
                    "version": item.get("version"),
                }
                for item in context.get("documents", [])
            ],
            "entities": [
                {
                    "id": item.get("id"),
                    "type": item.get("type"),
                    "name": item.get("name"),
                    "current_version": item.get("current_version"),
                    "state_keys": list((item.get("state") or {}).keys()) if isinstance(item.get("state"), dict) else [],
                }
                for item in context.get("entities", [])
            ],
            "relationships": context.get("relationships", []),
            "source_coverage": context.get("source_coverage") or {},
            "limits": {
                **(context.get("limits") or {}),
                "catalog_only": True,
            },
            "tool_hint": (
                "当前上下文仅保留目录。需要已有实体完整状态或关系时，"
                "按 entities[].id 调用 query_entity；需要按作品或关键词查资料时调用 search_domain_documents；"
                "需要文档全文时调用 get_novel_document_full。"
            ),
        }

    def _build_generation_tools(
        self,
        *,
        novel_id: str,
        current_setting_context: dict[str, Any],
        orchestration_config: OrchestratedTaskConfig,
    ) -> list[LLMToolSpec]:
        tools: list[LLMToolSpec] = []
        if "get_setting_workbench_context" in orchestration_config.tool_allowlist:
            async def get_setting_workbench_context(args: dict[str, Any]) -> dict[str, Any]:
                requested_novel_id = str(args.get("novel_id") or novel_id)
                if requested_novel_id != novel_id:
                    return {"error": "novel_id does not match current setting workbench session"}
                return current_setting_context

            tools.append(LLMToolSpec(
                name="get_setting_workbench_context",
                description="Read the current setting workbench context including documents, entities, and relationships.",
                input_schema={
                    "type": "object",
                    "properties": {"novel_id": {"type": "string"}},
                    "required": ["novel_id"],
                },
                handler=get_setting_workbench_context,
                read_only=True,
                timeout_seconds=orchestration_config.tool_timeout_seconds or 5.0,
                max_return_chars=orchestration_config.max_tool_result_chars,
            ))

        from novel_dev.mcp_server.server import internal_mcp_registry

        tools.extend(build_mcp_context_tools(
            internal_mcp_registry,
            allowlist=orchestration_config.tool_allowlist,
            max_return_chars=orchestration_config.max_tool_result_chars,
            timeout_seconds=orchestration_config.tool_timeout_seconds or 5.0,
        ))
        return tools

    async def _generate_draft_with_optional_section_split(
        self,
        *,
        novel_id: str,
        setting_session: Any,
        message_items: list[dict[str, Any]],
        current_setting_context: dict[str, Any],
        prompt_context: dict[str, Any],
        required_sections: list[dict[str, str]],
        orchestration_config: OrchestratedTaskConfig | None,
        common_metadata: dict[str, Any],
    ) -> SettingBatchDraft:
        if len(required_sections) <= 1:
            prompt = SettingWorkbenchAgent.build_generation_prompt(
                title=setting_session.title,
                target_categories=setting_session.target_categories or [],
                messages=message_items,
                conversation_summary=setting_session.conversation_summary,
                focused_context=setting_session.focused_target,
                current_setting_context=prompt_context,
                required_sections=required_sections,
            )
            return await self._call_and_repair_generation_model(
                novel_id=novel_id,
                prompt=prompt,
                current_setting_context=current_setting_context,
                orchestration_config=orchestration_config,
                required_sections=required_sections,
                common_metadata=common_metadata,
            )

        drafts: list[SettingBatchDraft] = []
        for index, section in enumerate(required_sections):
            section_prompt = SettingWorkbenchAgent.build_generation_prompt(
                title=setting_session.title,
                target_categories=setting_session.target_categories or [],
                messages=message_items,
                conversation_summary=setting_session.conversation_summary,
                focused_context=setting_session.focused_target,
                current_setting_context=prompt_context,
                required_sections=[section],
            )
            log_service.add_log(
                novel_id,
                "SettingWorkbenchService",
                f"开始生成建议批次 {section.get('label') or index + 1}：{section.get('title') or ''}",
                event="agent.progress",
                status="started",
                node="setting_generate_section",
                task="setting_workbench_generate_batch",
                metadata={
                    **common_metadata,
                    "section_index": index,
                    "section": section,
                    "section_prompt_chars": len(section_prompt),
                },
            )
            section_started_at = time.perf_counter()
            section_draft = await self._call_and_repair_generation_model(
                novel_id=novel_id,
                prompt=section_prompt,
                current_setting_context=current_setting_context,
                orchestration_config=orchestration_config,
                required_sections=[section],
                common_metadata={
                    **common_metadata,
                    "section_index": index,
                    "section": section,
                },
            )
            self._validate_batch_draft(section_draft, required_sections=[section])
            drafts.append(section_draft)
            log_service.add_log(
                novel_id,
                "SettingWorkbenchService",
                f"建议批次 {section.get('label') or index + 1} 生成完成",
                event="agent.progress",
                status="succeeded",
                node="setting_generate_section",
                task="setting_workbench_generate_batch",
                metadata={
                    **common_metadata,
                    "section_index": index,
                    "section": section,
                    "draft": self._draft_stats(section_draft),
                },
                duration_ms=self._elapsed_ms(section_started_at),
            )

        return self._merge_generation_drafts(drafts)

    async def _call_and_repair_generation_model(
        self,
        *,
        novel_id: str,
        prompt: str,
        current_setting_context: dict[str, Any],
        orchestration_config: OrchestratedTaskConfig | None,
        required_sections: list[dict[str, str]],
        common_metadata: dict[str, Any],
    ) -> SettingBatchDraft:
        draft = await self._call_generation_model(
            novel_id=novel_id,
            prompt=prompt,
            current_setting_context=current_setting_context,
            orchestration_config=orchestration_config,
        )
        missing_sections = self._missing_required_sections(draft, required_sections)
        if not missing_sections:
            return draft

        log_service.add_log(
            novel_id,
            "SettingWorkbenchService",
            "设定审核草稿缺少建议批次，开始补全生成",
            event="agent.progress",
            status="started",
            node="setting_generate_repair",
            task="setting_workbench_generate_batch",
            metadata={
                **common_metadata,
                "missing_required_sections": missing_sections,
                "draft": self._draft_stats(draft),
            },
        )
        return await self._call_generation_model(
            novel_id=novel_id,
            prompt=self._build_missing_required_sections_prompt(prompt, missing_sections),
            current_setting_context=current_setting_context,
            orchestration_config=orchestration_config,
        )

    @staticmethod
    def _merge_generation_drafts(drafts: list[SettingBatchDraft]) -> SettingBatchDraft:
        summaries = [draft.summary.strip() for draft in drafts if draft.summary.strip()]
        changes = [
            change
            for draft in drafts
            for change in draft.changes
        ]
        return SettingBatchDraft(summary="；".join(summaries), changes=changes)

    async def _call_generation_model(
        self,
        *,
        novel_id: str,
        prompt: str,
        current_setting_context: dict[str, Any],
        orchestration_config: OrchestratedTaskConfig | None,
    ) -> SettingBatchDraft:
        if orchestration_config is not None:
            return await orchestrated_call_and_parse_model(
                agent_name="SettingWorkbenchService",
                task="setting_workbench_generate_batch",
                prompt=prompt,
                model_cls=SettingBatchDraft,
                tools=self._build_generation_tools(
                    novel_id=novel_id,
                    current_setting_context=current_setting_context,
                    orchestration_config=orchestration_config,
                ),
                task_config=orchestration_config,
                config_agent_name="setting_workbench_service",
                novel_id=novel_id,
                max_retries=2,
            )
        return await call_and_parse_model(
            agent_name="SettingWorkbenchService",
            task="setting_workbench_generate_batch",
            prompt=prompt,
            model_cls=SettingBatchDraft,
            config_agent_name="setting_workbench_service",
            novel_id=novel_id,
            max_retries=2,
        )

    @staticmethod
    def _build_missing_required_sections_prompt(base_prompt: str, missing_sections: list[dict[str, str]]) -> str:
        missing_lines = [
            f"- {section.get('label') or '批次'}：{section.get('title') or ''}".strip("：")
            for section in missing_sections
        ]
        return "\n".join(
            [
                base_prompt,
                "",
                "上一次输出缺少以下建议批次：",
                *missing_lines,
                "请重新输出完整 SettingBatchDraft JSON。",
                "最终 changes 必须覆盖全部建议批次，而不只是补充缺失项；每个建议批次对应 1 条独立 setting_card create change。",
                "不要省略已覆盖批次，不要把多个建议批次合并到同一条 change。",
            ]
        )

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
    def _trim_text(value: Any, limit: int) -> str:
        text = str(value or "").strip()
        if len(text) <= limit:
            return text
        return f"{text[:limit]}..."

    @classmethod
    def _trim_struct(cls, value: Any, *, max_text: int) -> Any:
        if isinstance(value, str):
            return cls._trim_text(value, max_text)
        if isinstance(value, list):
            return [cls._trim_struct(item, max_text=max_text) for item in value[:8]]
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            added_count = 0
            for key, item in value.items():
                if str(key) in INTERNAL_ENTITY_STATE_KEYS:
                    continue
                if added_count >= 12:
                    result["_truncated"] = True
                    break
                result[str(key)] = cls._trim_struct(item, max_text=max_text)
                added_count += 1
            return result
        return value

    @staticmethod
    def _message_items(messages: list[Any]) -> list[dict[str, Any]]:
        return [{"role": message.role, "content": message.content} for message in messages]

    @classmethod
    def _message_items_for_generation(cls, messages: list[Any]) -> list[dict[str, Any]]:
        return [
            {
                "role": message.role,
                "content": cls._strip_suggested_generation_batches(getattr(message, "content", "") or ""),
            }
            for message in messages
        ]

    @staticmethod
    def _strip_suggested_generation_batches(content: str) -> str:
        for marker in ("**建议生成批次", "建议生成批次"):
            marker_index = content.find(marker)
            if marker_index >= 0:
                return content[:marker_index].strip()
        return content

    @classmethod
    def _extract_suggested_generation_batches(cls, messages: list[Any]) -> list[dict[str, str]]:
        for message in reversed(messages):
            sections = cls._parse_suggested_generation_batches(getattr(message, "content", "") or "")
            if sections:
                return sections
        return []

    @staticmethod
    def _parse_suggested_generation_batches(content: str) -> list[dict[str, str]]:
        sections: list[dict[str, str]] = []
        collecting = False
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not collecting:
                if "建议生成批次" in line:
                    collecting = True
                continue

            if not line:
                continue
            if sections and line.startswith("**"):
                break

            match = re.match(r"^(?:[-*]\s*)?(批次\s*[0-9一二三四五六七八九十]+)\s*[：:]\s*(.+)$", line)
            if match:
                sections.append(
                    {
                        "label": re.sub(r"\s+", "", match.group(1)),
                        "title": match.group(2).strip(),
                    }
                )
                continue
            if sections:
                break
        return sections

    def _validate_batch_draft(
        self,
        draft: SettingBatchDraft,
        *,
        required_sections: list[dict[str, str]] | None = None,
    ) -> None:
        if not draft.changes:
            raise ValueError("Draft must contain at least one change")
        missing_sections = self._missing_required_sections(draft, required_sections or [])
        if missing_sections:
            labels = [
                f"{section.get('label') or '批次'}：{section.get('title') or ''}".strip("：")
                for section in missing_sections
            ]
            raise ValueError(f"Missing required suggested batches: {'; '.join(labels)}")
        same_batch_entity_ids = self._same_batch_entity_create_ids(draft.changes)
        has_same_batch_entity_create_without_id = self._has_same_batch_entity_create_without_id(draft.changes)
        for index, item in enumerate(draft.changes):
            self._validate_draft_change(
                item,
                index=index,
                same_batch_entity_ids=same_batch_entity_ids,
                has_same_batch_entity_create_without_id=has_same_batch_entity_create_without_id,
            )
            self._validate_accuracy_guardrails(item, index=index)

    @staticmethod
    def _evaluate_generated_setting_quality(draft: SettingBatchDraft) -> SettingQualityReport:
        payload: dict[str, Any] = {
            "worldview": "",
            "power_system": "",
            "plot_synopsis": "",
            "character_profiles": [],
            "core_conflicts": [],
        }
        for change in draft.changes:
            snapshot = change.after_snapshot or {}
            if not isinstance(snapshot, dict):
                continue
            doc_type = str(snapshot.get("doc_type") or snapshot.get("type") or "").lower()
            title = str(snapshot.get("title") or snapshot.get("name") or "")
            content = str(snapshot.get("content") or snapshot.get("description") or snapshot.get("state") or "")
            combined = f"{title}\n{content}".strip()
            if change.target_type == "entity":
                entity_state = snapshot.get("state") if isinstance(snapshot.get("state"), dict) else {}
                payload["character_profiles"].append({
                    "name": snapshot.get("name") or title,
                    "goal": entity_state.get("goal") or entity_state.get("motivation") or "",
                    "conflict": entity_state.get("conflict") or "",
                })
            if doc_type in {"worldview", "domain_worldview"} or "世界" in title:
                payload["worldview"] = f"{payload['worldview']}\n{combined}".strip()
            if doc_type in {"power_system", "domain_power_system"} or any(token in title for token in ("力量", "修炼", "境界")):
                payload["power_system"] = f"{payload['power_system']}\n{combined}".strip()
            if doc_type in {"synopsis", "plot", "concept"} or any(token in title for token in ("剧情", "主线", "冲突", "梗概")):
                payload["plot_synopsis"] = f"{payload['plot_synopsis']}\n{combined}".strip()
                payload["core_conflicts"].append(combined)
        return StoryQualityService.evaluate_setting_payload(payload)

    async def _build_source_coverage(
        self,
        *,
        novel_id: str,
        title: str,
        target_categories: list[str],
        messages: list[dict[str, Any]],
        required_sections: list[dict[str, str]],
    ) -> dict[str, Any]:
        source_text = "\n".join(
            [
                title,
                " ".join(target_categories),
                *[item.get("content", "") for item in messages],
                *[section.get("title", "") for section in required_sections],
            ]
        )
        domains = [domain for domain in self.KNOWN_EXTERNAL_DOMAINS if domain in source_text]
        required = bool(domains and any(marker in source_text for marker in self.SOURCE_CRITICAL_MARKERS))
        if not required:
            return {"required": False, "domains": [], "missing_domains": []}

        domain_docs = []
        for doc_type in self.SOURCE_COVERAGE_DOC_TYPES:
            domain_docs.extend(await self.doc_repo.get_current_by_type(novel_id, doc_type))

        coverage_domains: list[dict[str, Any]] = []
        missing_domains: list[str] = []
        for domain in domains:
            matches = []
            for doc in domain_docs:
                haystack = f"{doc.title}\n{doc.content}"
                if not self._document_matches_domain(doc, domain):
                    continue
                if not any(keyword in haystack for keyword in self.SOURCE_TOPIC_KEYWORDS):
                    continue
                matches.append({
                    "id": doc.id,
                    "doc_type": doc.doc_type,
                    "title": doc.title,
                    "version": doc.version,
                })
            if not matches:
                missing_domains.append(domain)
            coverage_domains.append({
                "name": domain,
                "status": "covered" if matches else "missing",
                "matched_doc_ids": [item["id"] for item in matches[:5]],
                "matched_documents": matches[:5],
            })
        return {
            "required": True,
            "reason": "accuracy_first_external_setting_generation",
            "domains": coverage_domains,
            "missing_domains": missing_domains,
        }

    @staticmethod
    def _document_matches_domain(doc: NovelDocument, domain: str) -> bool:
        title = doc.title or ""
        if str(doc.doc_type or "").startswith("domain_"):
            return domain in title
        return domain in f"{title}\n{doc.content or ''}"

    @staticmethod
    def _validate_source_coverage(source_coverage: dict[str, Any]) -> None:
        if not source_coverage.get("required"):
            return
        missing_domains = [str(item) for item in source_coverage.get("missing_domains") or [] if str(item)]
        if not missing_domains:
            return
        raise ValueError(
            "Source coverage insufficient for accuracy-first setting generation: "
            f"{', '.join(missing_domains)}. "
            "请先导入这些世界的修炼体系/人物/世界观资料，或在会话中提供可核验资料后再生成。"
        )

    def _validate_accuracy_guardrails(self, item: SettingBatchChangeDraft, *, index: int) -> None:
        if item.target_type != "setting_card" or item.operation not in {"create", "update"}:
            return
        snapshot = item.after_snapshot or {}
        text = "\n".join(
            str(snapshot.get(key) or "")
            for key in ("title", "content", "description")
        )
        if not text.strip():
            return
        self._validate_source_doc_ids_for_source_critical_snapshot(snapshot, text, index=index)
        self._validate_canonical_world_protagonists(text, index=index)
        self._validate_realm_mapping_order(text, index=index)

    async def _validate_draft_source_evidence(self, novel_id: str, draft: SettingBatchDraft) -> None:
        for index, item in enumerate(draft.changes):
            if item.target_type != "setting_card" or item.operation not in {"create", "update"}:
                continue
            snapshot = item.after_snapshot or {}
            text = "\n".join(
                str(snapshot.get(key) or "")
                for key in ("title", "content", "description")
            )
            source_doc_ids = self._source_doc_ids(snapshot)
            if not source_doc_ids:
                continue

            docs = []
            for doc_id in source_doc_ids:
                doc = await self.doc_repo.get_by_id_for_novel(novel_id, doc_id)
                if doc is None:
                    raise ValueError(
                        f"Draft change {index} source evidence document not found: {doc_id}"
                    )
                docs.append(doc)

            mentioned_domains = [domain for domain in self.KNOWN_EXTERNAL_DOMAINS if domain in text]
            if not mentioned_domains:
                continue
            evidence_text = "\n".join(f"{doc.title}\n{doc.content}" for doc in docs)
            missing_domains = [domain for domain in mentioned_domains if domain not in evidence_text]
            if missing_domains:
                raise ValueError(
                    f"Draft change {index} Source evidence mismatch for domains: "
                    f"{', '.join(missing_domains)}"
                )

    def _validate_source_doc_ids_for_source_critical_snapshot(
        self,
        snapshot: dict[str, Any],
        text: str,
        *,
        index: int,
    ) -> None:
        mentions_domain = any(domain in text for domain in self.KNOWN_EXTERNAL_DOMAINS)
        source_critical = mentions_domain and any(marker in text for marker in self.SOURCE_CRITICAL_MARKERS)
        if not source_critical:
            return
        source_doc_ids = self._source_doc_ids(snapshot)
        if not source_doc_ids:
            raise ValueError(
                f"Draft change {index} source evidence required for external/cross-work setting content"
            )

    @staticmethod
    def _source_doc_ids(snapshot: dict[str, Any]) -> list[str]:
        source_doc_ids = snapshot.get("source_doc_ids") or snapshot.get("evidence_doc_ids") or []
        if isinstance(source_doc_ids, str):
            source_doc_ids = [source_doc_ids]
        if not isinstance(source_doc_ids, list):
            return []
        return [str(doc_id).strip() for doc_id in source_doc_ids if str(doc_id).strip()]

    def _validate_canonical_world_protagonists(self, text: str, *, index: int) -> None:
        protagonist_home = {
            protagonist: world
            for world, protagonist in self.CANONICAL_WORLD_PROTAGONISTS.items()
        }
        segments = [segment.strip() for segment in re.split(r"[\n。；;]", text) if segment.strip()]
        for segment in segments:
            mentioned_worlds = [world for world in self.CANONICAL_WORLD_PROTAGONISTS if world in segment]
            if not mentioned_worlds:
                continue
            for protagonist, home_world in protagonist_home.items():
                if protagonist not in segment:
                    continue
                for world in mentioned_worlds:
                    if world == home_world or home_world in segment:
                        continue
                    raise ValueError(
                        f"Draft change {index} Canonical world/protagonist mismatch: "
                        f"{world} segment mentions {protagonist}, whose canonical world is {home_world}"
                    )

    def _validate_realm_mapping_order(self, text: str, *, index: int) -> None:
        rows = self._extract_yishi_mapping_rows(text)
        if len(rows) < 2:
            return
        previous_rank = None
        previous_source = ""
        for source_realm, target_mapping in rows:
            rank = self._yishi_mapping_rank(target_mapping)
            if rank is None:
                continue
            if previous_rank is not None and rank < previous_rank:
                raise ValueError(
                    f"Draft change {index} Realm mapping order regression: "
                    f"{source_realm} maps to {target_mapping}, below previous row {previous_source}"
                )
            previous_rank = rank
            previous_source = source_realm

    @staticmethod
    def _extract_yishi_mapping_rows(text: str) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        in_mapping_table = False
        source_index = 0
        target_index = 1
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line.startswith("|") or "|" not in line[1:]:
                in_mapping_table = False
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) < 2:
                continue
            if all(re.fullmatch(r":?-{2,}:?", cell.replace(" ", "")) for cell in cells):
                continue
            if any("对标一世之尊" in cell for cell in cells):
                in_mapping_table = True
                source_index = 0
                target_index = next(
                    (idx for idx, cell in enumerate(cells) if "对标一世之尊" in cell),
                    1,
                )
                continue
            if not in_mapping_table or len(cells) <= max(source_index, target_index):
                continue
            rows.append((cells[source_index], cells[target_index]))
        return rows

    @classmethod
    def _yishi_mapping_rank(cls, target_mapping: str) -> int | None:
        ranks = [
            rank
            for realm, rank in cls.YISHI_REALM_RANKS.items()
            if realm in target_mapping
        ]
        if not ranks:
            return None
        return max(ranks)

    @classmethod
    def _missing_required_sections(
        cls,
        draft: SettingBatchDraft,
        required_sections: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        if not required_sections:
            return []

        change_texts = [
            cls._review_change_search_text(change)
            for change in draft.changes
            if change.target_type == "setting_card"
        ]
        matched_change_indexes: set[int] = set()
        missing = []
        for section in required_sections:
            terms = cls._required_section_match_terms(section)
            if not terms:
                continue
            matched_index = next(
                (
                    index
                    for index, text in enumerate(change_texts)
                    if index not in matched_change_indexes and any(term and term in text for term in terms)
                ),
                None,
            )
            if matched_index is None:
                missing.append(section)
            else:
                matched_change_indexes.add(matched_index)
        return missing

    @staticmethod
    def _review_change_search_text(change: SettingBatchChangeDraft) -> str:
        snapshot = change.after_snapshot or {}
        pieces = [
            snapshot.get("title"),
            snapshot.get("content"),
            snapshot.get("name"),
            snapshot.get("description"),
        ]
        return "\n".join(str(piece) for piece in pieces if piece)

    @staticmethod
    def _required_section_match_terms(section: dict[str, str]) -> list[str]:
        title = (section.get("title") or "").strip()
        label = (section.get("label") or "").strip()
        if not title:
            return [label] if label else []
        base = re.split(r"[（(]", title, maxsplit=1)[0].strip()
        variants = [title, base]
        if label:
            variants.append(f"{label}：{title}")
            variants.append(f"{label}:{title}")
            if base:
                variants.append(f"{label}：{base}")
                variants.append(f"{label}:{base}")
        return [variant for variant in dict.fromkeys(variants) if variant]

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
    def _has_same_batch_entity_create_without_id(changes: list[SettingBatchChangeDraft]) -> bool:
        for item in changes:
            if item.target_type != "entity" or item.operation != "create":
                continue
            snapshot = item.after_snapshot or {}
            if not str(snapshot.get("id") or "").strip():
                return True
        return False

    @staticmethod
    def _validate_draft_change(
        item: SettingBatchChangeDraft,
        *,
        index: int,
        same_batch_entity_ids: set[str] | None = None,
        has_same_batch_entity_create_without_id: bool = False,
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
            if (getattr(item, "source_ref", None) or "").strip():
                ref_fields.append("source_ref")
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
            if has_same_batch_entity_create_without_id:
                raise ValueError(
                    f"Draft change {index} relationship create cannot be emitted when same-batch entity create "
                    "is missing after_snapshot.id"
                )
            same_batch_entity_ids = same_batch_entity_ids or set()

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
