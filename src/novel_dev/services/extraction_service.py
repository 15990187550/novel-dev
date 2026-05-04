import uuid
import json
import logging
import re
from typing import Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.agents.file_classifier import FileClassificationResult, FileClassifier
from novel_dev.agents.setting_extractor import SettingExtractorAgent
from novel_dev.agents.style_profiler import StyleProfilerAgent, StyleProfile, StyleConfig
from novel_dev.agents.profile_merger import ProfileMerger
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.knowledge_domain_repo import KnowledgeDomainRepository
from novel_dev.repositories.pending_extraction_repo import PendingExtractionRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.services.entity_service import EntityService
from novel_dev.services.embedding_service import EmbeddingService
from novel_dev.services.relationship_extraction_service import RelationshipExtractionService
from novel_dev.services.log_service import log_service
from novel_dev.db.models import NovelDocument, PendingExtraction
from novel_dev.llm import llm_factory
from novel_dev.llm.models import ChatMessage
from novel_dev.schemas.brainstorm_workspace import (
    PendingExtractionPayload,
    SettingDocDraftPayload,
    SettingSuggestionCardPayload,
)

logger = logging.getLogger(__name__)

SETTING_MERGE_RETRY_LIMIT = 2
APPROVE_ENTITY_BATCH_SIZE = 25

AUTO_APPLY_FIELDS = {
    "appearance",
    "background",
    "ability",
    "resources",
    "notes",
    "description",
    "significance",
}

CHARACTER_SUGGESTION_STATE_FIELDS = (
    "identity",
    "personality",
    "goal",
    "appearance",
    "background",
    "ability",
    "realm",
    "relationships",
    "resources",
    "secrets",
    "conflict",
    "arc",
    "notes",
)

FIELD_LABELS = {
    "identity": "身份",
    "personality": "性格",
    "goal": "目标",
    "appearance": "外貌",
    "background": "背景",
    "ability": "能力",
    "realm": "境界",
    "relationships": "关系",
    "resources": "资源",
    "secrets": "秘密",
    "conflict": "冲突",
    "arc": "人物弧光",
    "notes": "备注",
    "description": "描述",
    "significance": "重要性",
    "position": "定位",
    "region": "区域",
    "relationship_with_protagonist": "与主角关系",
}

PENDING_ENTITY_BUCKETS = {
    "character": "character_profiles",
    "faction": "factions",
    "location": "locations",
    "item": "important_items",
}

MERGEABLE_LIBRARY_DOC_TYPES = {"worldview", "setting", "synopsis", "concept"}


class ExtractionService:
    def __init__(self, session: AsyncSession, embedding_service: Optional[EmbeddingService] = None):
        self.session = session
        self.embedding_service = embedding_service
        self.classifier = FileClassifier()
        self.setting_agent = SettingExtractorAgent()
        self.style_agent = StyleProfilerAgent()
        self.merger = ProfileMerger()
        self.doc_repo = DocumentRepository(session)
        self.domain_repo = KnowledgeDomainRepository(session)
        self.pending_repo = PendingExtractionRepository(session)
        self.state_repo = NovelStateRepository(session)
        self.entity_svc = EntityService(session, embedding_service)

    def _source_metadata(self, source_filename: str | None = None) -> dict[str, Any]:
        source_filename = (source_filename or "").strip()
        return {"source_filename": source_filename} if source_filename else {}

    def _log(
        self,
        novel_id: str,
        message: str,
        *,
        source_filename: str | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        merged_metadata = {**self._source_metadata(source_filename), **(metadata or {})}
        if source_filename and source_filename not in message:
            message = f"{message}（文件: {source_filename}）"
        log_service.add_log(
            novel_id,
            "ExtractionService",
            message,
            metadata=merged_metadata or None,
            **kwargs,
        )

    def _normalize_setting_draft(self, draft: dict[str, Any]) -> dict[str, Any]:
        payload = SettingDocDraftPayload.model_validate(draft)
        return {
            "draft_id": payload.draft_id,
            "source_outline_ref": payload.source_outline_ref,
            "source_kind": payload.source_kind,
            "target_import_mode": payload.target_import_mode,
            "target_doc_type": payload.target_doc_type,
            "title": payload.title,
            "content": payload.content,
            "order_index": payload.order_index,
        }

    def validate_setting_draft(self, draft: dict[str, Any]) -> dict[str, Any]:
        normalized_draft = self._normalize_setting_draft(draft)
        if normalized_draft["target_import_mode"] == "auto_classify":
            return normalized_draft
        if normalized_draft["target_import_mode"] != "explicit_type":
            raise ValueError(
                f"Unsupported target_import_mode: {normalized_draft['target_import_mode']}"
            )

        self._build_explicit_setting_payload(normalized_draft)
        return normalized_draft

    def _build_explicit_setting_payload(
        self,
        draft: dict[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        raw_result = {
            "worldview": "",
            "power_system": "",
            "factions": [],
            "locations": [],
            "character_profiles": [],
            "important_items": [],
            "plot_synopsis": "",
        }
        proposed_entities: list[dict[str, Any]] = []

        source_kind = draft["source_kind"]
        target_doc_type = draft["target_doc_type"]
        title = draft["title"]
        content = draft["content"]

        if target_doc_type == "worldview" and source_kind == "worldview":
            raw_result["worldview"] = content
        elif target_doc_type == "setting" and source_kind == "power_system":
            raw_result["power_system"] = content
        elif target_doc_type == "synopsis" and source_kind == "synopsis":
            raw_result["plot_synopsis"] = content
        elif target_doc_type == "concept":
            if source_kind == "item":
                item = {
                    "name": title,
                    "description": content,
                    "significance": "",
                }
                raw_result["important_items"] = [item]
                proposed_entities.append(
                    {
                        "type": "item",
                        "name": title,
                        "data": item,
                    }
                )
            elif source_kind == "character":
                character = {
                    "name": title,
                    "identity": content,
                    "personality": "",
                    "goal": "",
                    "appearance": "",
                    "background": "",
                    "ability": "",
                    "realm": "",
                    "relationships": "",
                    "resources": "",
                    "secrets": "",
                    "conflict": "",
                    "arc": "",
                    "notes": "",
                }
                raw_result["character_profiles"] = [character]
                proposed_entities.append(
                    {
                        "type": "character",
                        "name": title,
                        "data": character,
                    }
                )
            else:
                raise ValueError(
                    f"Unsupported explicit draft combination: source_kind={source_kind}, "
                    f"target_doc_type={target_doc_type}"
                )
        elif target_doc_type == "setting" and source_kind == "faction":
            raise ValueError(
                "Explicit faction drafts are not supported by the pending-setting approval flow; "
                "use auto_classify or extend the approval path first"
            )
        else:
            raise ValueError(
                f"Unsupported explicit draft combination: source_kind={source_kind}, "
                f"target_doc_type={target_doc_type}"
            )

        return raw_result, proposed_entities

    def _stringify_value(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def _pending_entity_bucket(self, entity_type: str) -> str:
        bucket = PENDING_ENTITY_BUCKETS.get((entity_type or "").strip())
        if not bucket:
            raise ValueError(f"Unsupported pending draft entity type: {entity_type}")
        return bucket

    def _find_pending_entity_index(self, entities: list[dict[str, Any]], entity_name: str) -> int:
        for index, entity in enumerate(entities):
            if (entity.get("name") or "").strip() == entity_name.strip():
                return index
        return -1

    async def update_pending_draft_field(
        self,
        pending_id: str,
        *,
        entity_type: str,
        entity_name: str,
        field: str,
        value: str,
    ) -> PendingExtraction:
        pe = await self.pending_repo.get_by_id(pending_id)
        if not pe:
            raise ValueError("待审核记录不存在")
        if pe.status != "pending":
            raise ValueError("只有待审核记录可以编辑")
        if pe.extraction_type != "setting":
            raise ValueError("只有设定提取记录支持字段编辑")

        bucket = self._pending_entity_bucket(entity_type)
        raw_result = dict(pe.raw_result or {})
        raw_entities = [dict(item) for item in raw_result.get(bucket, [])]
        entity_index = self._find_pending_entity_index(raw_entities, entity_name)
        if entity_index < 0:
            raise ValueError("未找到要编辑的草稿实体")

        raw_entities[entity_index] = {
            **raw_entities[entity_index],
            field: value,
        }
        raw_result[bucket] = raw_entities

        proposed_entities = [dict(item) for item in (pe.proposed_entities or [])]
        updated_name = raw_entities[entity_index].get("name", entity_name)
        for proposed in proposed_entities:
            if proposed.get("type") != entity_type:
                continue
            if (proposed.get("name") or "").strip() != entity_name.strip():
                continue
            proposed["name"] = updated_name
            proposed["data"] = {
                **dict(proposed.get("data") or {}),
                field: value,
            }
            break

        diff_result = await self._build_setting_diff(pe.novel_id, raw_result)
        updated = await self.pending_repo.update_draft_content(
            pending_id,
            raw_result=raw_result,
            proposed_entities=proposed_entities,
            diff_result=diff_result,
        )
        if updated is None:
            raise ValueError("待审核记录不存在")
        return updated

    async def _build_entity_diff(self, novel_id: str, entity_type: str, incoming_state: dict) -> dict:
        entity_name = incoming_state.get("name", "unknown")
        existing = await self.entity_svc.entity_repo.find_by_name(entity_name, entity_type=entity_type, novel_id=novel_id)
        if existing is None:
            field_changes = []
            for field, value in incoming_state.items():
                if self._stringify_value(value):
                    field_changes.append({
                        "field": field,
                        "label": FIELD_LABELS.get(field, field),
                        "old_value": "",
                        "new_value": value,
                        "change_type": "add",
                        "auto_applicable": True,
                        "reason": "新实体字段",
                    })
            return {
                "entity_type": entity_type,
                "entity_name": entity_name,
                "existing_entity_id": None,
                "operation": "create",
                "field_changes": field_changes,
            }

        latest_state = await self.entity_svc.get_latest_state(existing.id) or {}
        field_changes = []
        operation = "update"
        for field, new_value in incoming_state.items():
            if field == "name":
                continue
            new_text = self._stringify_value(new_value)
            if not new_text:
                continue
            old_value = latest_state.get(field)
            old_text = self._stringify_value(old_value)
            if not old_text:
                field_changes.append({
                    "field": field,
                    "label": FIELD_LABELS.get(field, field),
                    "old_value": old_value,
                    "new_value": new_value,
                    "change_type": "add",
                    "auto_applicable": True,
                    "reason": "旧值为空，可自动补充",
                })
                continue
            if old_text == new_text:
                continue
            operation = "conflict"
            field_changes.append({
                "field": field,
                "label": FIELD_LABELS.get(field, field),
                "old_value": old_value,
                "new_value": new_value,
                "change_type": "conflict",
                "auto_applicable": False,
                "reason": "字段值不一致，需人工审核",
            })

        return {
            "entity_type": entity_type,
            "entity_name": entity_name,
            "existing_entity_id": existing.id,
            "operation": operation if field_changes else "noop",
            "field_changes": field_changes,
        }

    async def _merge_field_values(
        self,
        novel_id: str,
        entity_type: str,
        entity_name: str,
        field: str,
        old_value: Any,
        new_value: Any,
        source_filename: str | None = None,
    ) -> str:
        old_text = self._stringify_value(old_value)
        new_text = self._stringify_value(new_value)
        client = llm_factory.get("EditorAgent", task="polish_beat")
        prompt = (
            "你要合并小说设定中的同一字段的旧值与新值，输出一个最终采用的合并版本。\n\n"
            "要求:\n"
            "1. 只返回合并后的字段内容，不要解释。\n"
            "2. 尽量保留双方不冲突的信息。\n"
            "3. 如果信息冲突，优先保留更新、更具体、更完整的内容。\n"
            "4. 保持适合设定字段直接存储的文本格式，不要加标题。\n"
            "5. 不要编造原文中不存在的新事实。\n\n"
            f"实体类型: {entity_type}\n"
            f"实体名称: {entity_name}\n"
            f"字段: {field}\n\n"
            f"旧值:\n{old_text or '[空]'}\n\n"
            f"新值:\n{new_text or '[空]'}"
        )
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        merged_text = (response.text or "").strip()
        if not merged_text:
            raise RuntimeError(f"LLM merge returned empty result for {entity_type}/{entity_name}/{field}")
        self._log(novel_id, f"字段自动合并完成: {entity_name}.{field}", source_filename=source_filename)
        return merged_text

    async def _request_setting_document_merge(
        self,
        *,
        novel_id: str,
        doc_type: str,
        title: str,
        existing_content: str,
        incoming_content: str,
    ) -> str:
        client = llm_factory.get("EditorAgent", task="polish_beat")
        prompt = (
            "你要把同一小说资料库中同类型、同标题的两份设定文档合并成一份新的当前版本。\n\n"
            "要求:\n"
            "1. 只输出合并后的最终正文，不要解释。\n"
            "2. 去重，保留不冲突信息。\n"
            "3. 如果信息冲突，优先保留更新、更具体、更完整的描述。\n"
            "4. 不要编造原文中不存在的新事实。\n"
            "5. 输出应适合直接写入资料库。\n\n"
            f"资料类型: {doc_type}\n"
            f"资料标题: {title}\n\n"
            f"已有版本:\n{existing_content or '[空]'}\n\n"
            f"新批准内容:\n{incoming_content or '[空]'}"
        )
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        merged_text = (response.text or "").strip()
        if not merged_text:
            raise RuntimeError(f"LLM returned empty merged content for {doc_type}/{title}")
        return merged_text

    async def _merge_setting_document_content(
        self,
        *,
        novel_id: str,
        doc_type: str,
        title: str,
        existing_content: str,
        incoming_content: str,
        source_filename: str | None = None,
    ) -> str:
        last_error: Exception | None = None
        for attempt in range(1, SETTING_MERGE_RETRY_LIMIT + 1):
            try:
                merged = await self._request_setting_document_merge(
                    novel_id=novel_id,
                    doc_type=doc_type,
                    title=title,
                    existing_content=existing_content,
                    incoming_content=incoming_content,
                )
                self._log(
                    novel_id,
                    f"资料自动合并完成: {title}（第 {attempt} 次尝试成功）",
                    source_filename=source_filename,
                )
                return merged
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "setting_document_merge_failed",
                    extra={
                        "novel_id": novel_id,
                        "doc_type": doc_type,
                        "title": title,
                        "attempt": attempt,
                        "error": str(exc),
                    },
                )
        self._log(
            novel_id,
            f"资料自动合并失败，已保留最新批准内容: {title} ({last_error})",
            level="warning",
            source_filename=source_filename,
        )
        return incoming_content

    async def _create_or_merge_setting_document(
        self,
        *,
        novel_id: str,
        doc_type: str,
        title: str,
        content: str,
        source_filename: str | None = None,
    ) -> NovelDocument:
        latest = await self.doc_repo.get_latest_by_type_and_title(novel_id, doc_type, title)
        next_version = (latest.version + 1) if latest else 1
        final_content = content
        if latest and latest.content:
            final_content = await self._merge_setting_document_content(
                novel_id=novel_id,
                doc_type=doc_type,
                title=title,
                existing_content=latest.content,
                incoming_content=content,
                source_filename=source_filename,
            )
        return await self.doc_repo.create(
            doc_id=f"doc_{uuid.uuid4().hex[:8]}",
            novel_id=novel_id,
            doc_type=doc_type,
            title=title,
            content=final_content,
            version=next_version,
        )

    async def _create_domain_setting_document(
        self,
        *,
        novel_id: str,
        domain_name: str,
        doc_type: str,
        title: str,
        content: str,
    ) -> NovelDocument:
        return await self.doc_repo.create(
            doc_id=f"doc_{uuid.uuid4().hex[:8]}",
            novel_id=novel_id,
            doc_type=f"domain_{doc_type}",
            title=f"{domain_name} / {title}",
            content=content,
            version=1,
        )

    async def merge_existing_library_duplicates(self, novel_id: str) -> list[NovelDocument]:
        grouped_docs: dict[tuple[str, str], list[NovelDocument]] = {}
        for doc_type in MERGEABLE_LIBRARY_DOC_TYPES:
            docs = await self.doc_repo.get_by_type(novel_id, doc_type)
            for doc in docs:
                grouped_docs.setdefault((doc.doc_type, doc.title), []).append(doc)

        merged_docs: list[NovelDocument] = []
        for (doc_type, title), docs in grouped_docs.items():
            if len(docs) < 2:
                continue

            docs.sort(key=lambda item: (item.version or 0, item.updated_at))
            merged_content = docs[0].content or ""
            for doc in docs[1:]:
                merged_content = await self._merge_setting_document_content(
                    novel_id=novel_id,
                    doc_type=doc_type,
                    title=title,
                    existing_content=merged_content,
                    incoming_content=doc.content or "",
                )

            next_version = max((doc.version or 0) for doc in docs) + 1
            merged_doc = await self.doc_repo.create(
                doc_id=f"doc_{uuid.uuid4().hex[:8]}",
                novel_id=novel_id,
                doc_type=doc_type,
                title=title,
                content=merged_content,
                version=next_version,
            )
            merged_docs.append(merged_doc)
            log_service.add_log(
                novel_id,
                "ExtractionService",
                f"已合并重复资料: {doc_type}/{title} -> v{next_version}",
            )

        return merged_docs

    async def _build_setting_diff(self, novel_id: str, raw_result: dict) -> dict:
        entity_diffs = []
        summary_parts = []

        for char in raw_result.get("character_profiles", []):
            entity_diff = await self._build_entity_diff(novel_id, "character", char)
            if entity_diff["operation"] != "noop":
                entity_diffs.append(entity_diff)

        for faction in self._normalize_setting_entities(raw_result.get("factions")):
            entity_diff = await self._build_entity_diff(novel_id, "faction", faction)
            if entity_diff["operation"] != "noop":
                entity_diffs.append(entity_diff)

        for location in self._normalize_setting_entities(raw_result.get("locations")):
            entity_diff = await self._build_entity_diff(novel_id, "location", location)
            if entity_diff["operation"] != "noop":
                entity_diffs.append(entity_diff)

        for item in raw_result.get("important_items", []):
            entity_diff = await self._build_entity_diff(novel_id, "item", item)
            if entity_diff["operation"] != "noop":
                entity_diffs.append(entity_diff)

        create_count = sum(1 for d in entity_diffs if d["operation"] == "create")
        update_count = sum(1 for d in entity_diffs if d["operation"] == "update")
        conflict_count = sum(1 for d in entity_diffs if d["operation"] == "conflict")
        if create_count:
            summary_parts.append(f"{create_count} 个新增实体")
        if update_count:
            summary_parts.append(f"{update_count} 个可自动补充实体")
        if conflict_count:
            summary_parts.append(f"{conflict_count} 个冲突实体")

        return {
            "entity_diffs": entity_diffs,
            "document_changes": [],
            "summary": "，".join(summary_parts) if summary_parts else "无实体变更",
        }

    @staticmethod
    def _merge_entity_field_value(old_value: Any, new_value: Any) -> Any:
        if new_value in (None, "", []):
            return old_value
        if old_value in (None, "", []):
            return new_value
        if isinstance(old_value, list) or isinstance(new_value, list):
            merged: list[Any] = []
            for item in [*(old_value if isinstance(old_value, list) else [old_value]), *(new_value if isinstance(new_value, list) else [new_value])]:
                if item not in (None, "") and item not in merged:
                    merged.append(item)
            return merged
        old_text = str(old_value).strip()
        new_text = str(new_value).strip()
        if not new_text or old_text == new_text:
            return old_value
        if new_text in old_text:
            return old_value
        if old_text in new_text:
            return new_value
        return f"{old_text}\n{new_text}"

    @staticmethod
    def _aliases_from_incoming_name(incoming_name: str, canonical_name: str) -> list[str]:
        incoming = (incoming_name or "").strip()
        canonical_normalized = EntityRepository.normalize_name(canonical_name)
        aliases: list[str] = []
        if incoming and EntityRepository.normalize_name(incoming) != canonical_normalized:
            aliases.append(incoming)
        for part in re.split(r"[/／|｜、;；]+", incoming):
            cleaned = part.strip()
            if cleaned and EntityRepository.normalize_name(cleaned) != canonical_normalized and cleaned not in aliases:
                aliases.append(cleaned)
        for match in re.finditer(r"（(.*?)）|\((.*?)\)|【(.*?)】|\[(.*?)\]", incoming):
            for part in match.groups():
                cleaned = (part or "").strip()
                if cleaned and EntityRepository.normalize_name(cleaned) != canonical_normalized and cleaned not in aliases:
                    aliases.append(cleaned)
        return aliases

    def _merge_entity_state_for_alias(self, existing_name: str, latest_state: dict[str, Any], incoming_state: dict[str, Any]) -> dict[str, Any]:
        merged_state = dict(latest_state or {})
        incoming_name = str(incoming_state.get("name") or "").strip()
        for field, value in incoming_state.items():
            if field == "name":
                continue
            merged_state[field] = self._merge_entity_field_value(merged_state.get(field), value)
        aliases = self._merge_entity_field_value(
            merged_state.get("aliases") or [],
            self._aliases_from_incoming_name(incoming_name, existing_name),
        )
        if aliases:
            merged_state["aliases"] = aliases
        merged_state["name"] = existing_name
        return merged_state

    def _domain_scope_from_entity_diff(self, entity_diff: dict[str, Any]) -> tuple[str | None, str | None]:
        domain_id = None
        domain_name = None
        for change in entity_diff.get("field_changes", []):
            if change.get("field") == "_knowledge_domain_id":
                domain_id = change.get("new_value")
            elif change.get("field") == "_knowledge_domain_name":
                domain_name = change.get("new_value")
        return domain_id, domain_name

    async def _find_existing_domain_entity(
        self,
        novel_id: str,
        entity_type: str,
        entity_name: str,
        *,
        domain_id: str | None,
        domain_name: str | None,
    ):
        target_variants = EntityRepository.name_variants(entity_name)
        if not target_variants:
            return None
        candidates = [
            entity for entity in await self.entity_svc.entity_repo.list_by_novel(novel_id)
            if entity.type == entity_type
        ]
        domain_matches = []
        for entity in candidates:
            latest_state = await self.entity_svc.get_latest_state(entity.id) or {}
            if latest_state.get("_knowledge_usage") != "domain":
                continue
            if domain_id and latest_state.get("_knowledge_domain_id") != domain_id:
                continue
            if not domain_id and domain_name and latest_state.get("_knowledge_domain_name") != domain_name:
                continue
            entity_variants = EntityRepository.name_variants(entity.name)
            state_aliases = latest_state.get("aliases") or []
            if isinstance(state_aliases, list):
                for alias in state_aliases:
                    entity_variants.update(EntityRepository.name_variants(str(alias)))
            if entity_variants & target_variants:
                domain_matches.append(entity)
                continue
            if any(
                EntityRepository._is_close_name_match(candidate_variant, target_variant)
                for candidate_variant in entity_variants
                for target_variant in target_variants
            ):
                domain_matches.append(entity)
        if len(domain_matches) == 1:
            return domain_matches[0]
        return None

    async def _apply_entity_diff(
        self,
        novel_id: str,
        entity_diff: dict,
        field_resolutions: Optional[List[dict]] = None,
        applied_entity_ids: Optional[list[str]] = None,
        source_filename: str | None = None,
    ) -> list[dict]:
        entity_name = entity_diff.get("entity_name", "unknown")
        entity_type = entity_diff.get("entity_type", "other")
        resolution_log: list[dict] = []
        if entity_diff.get("operation") == "create":
            initial_state = {change["field"]: change.get("new_value") for change in entity_diff.get("field_changes", [])}
            initial_state["name"] = entity_name
            domain_id, domain_name = self._domain_scope_from_entity_diff(entity_diff)
            existing = None
            if domain_id or domain_name:
                existing = await self._find_existing_domain_entity(
                    novel_id,
                    entity_type,
                    entity_name,
                    domain_id=domain_id,
                    domain_name=domain_name,
                )
            else:
                existing = await self.entity_svc.entity_repo.find_by_name(
                    entity_name,
                    entity_type=entity_type,
                    novel_id=novel_id,
                )
            if existing is not None:
                latest_state = await self.entity_svc.get_latest_state(existing.id) or {"name": existing.name}
                merged_state = self._merge_entity_state_for_alias(existing.name, latest_state, initial_state)
                await self.entity_svc.update_state_from_import(
                    existing.id,
                    merged_state,
                    diff_summary={"merged_from_pending": True, "deduplicated_create": True},
                )
                if applied_entity_ids is not None:
                    applied_entity_ids.append(existing.id)
                for change in entity_diff.get("field_changes", []):
                    resolution_log.append({
                        "entity_type": entity_type,
                        "entity_name": entity_name,
                        "field": change["field"],
                        "action": "merged_create",
                        "applied": True,
                    })
                return resolution_log
            entity_id = f"ent_{uuid.uuid4().hex[:8]}"
            await self.entity_svc.create_entity(
                entity_id=entity_id,
                entity_type=entity_type,
                name=entity_name,
                novel_id=novel_id,
                initial_state=initial_state,
                use_llm_for_classification=False,
            )
            if applied_entity_ids is not None:
                applied_entity_ids.append(entity_id)
            for change in entity_diff.get("field_changes", []):
                resolution_log.append({
                    "entity_type": entity_type,
                    "entity_name": entity_name,
                    "field": change["field"],
                    "action": "created",
                    "applied": True,
                })
            return resolution_log

        entity_id = entity_diff.get("existing_entity_id")
        if not entity_id:
            return resolution_log
        latest_state = await self.entity_svc.get_latest_state(entity_id) or {"name": entity_name}
        merged_state = dict(latest_state)
        applied = False
        resolutions_by_field = {
            item.get("field"): item
            for item in (field_resolutions or [])
            if item.get("entity_type") == entity_type and item.get("entity_name") == entity_name
        }
        for change in entity_diff.get("field_changes", []):
            field = change["field"]
            resolution = resolutions_by_field.get(field)
            if resolution:
                action = resolution.get("action")
                if action == "use_new":
                    merged_state[field] = change.get("new_value")
                    applied = True
                    resolution_log.append({"entity_type": entity_type, "entity_name": entity_name, "field": field, "action": "use_new", "applied": True})
                elif action == "merge":
                    merged_value = resolution.get("merged_value")
                    if not merged_value:
                        merged_value = await self._merge_field_values(
                            novel_id=novel_id,
                            entity_type=entity_type,
                            entity_name=entity_name,
                            field=field,
                            old_value=change.get("old_value"),
                            new_value=change.get("new_value"),
                            source_filename=source_filename,
                        )
                    merged_state[field] = merged_value
                    applied = True
                    resolution_log.append({"entity_type": entity_type, "entity_name": entity_name, "field": field, "action": "merge", "applied": True})
                elif action == "skip":
                    resolution_log.append({"entity_type": entity_type, "entity_name": entity_name, "field": field, "action": "skip", "applied": False})
                else:
                    resolution_log.append({"entity_type": entity_type, "entity_name": entity_name, "field": field, "action": "keep_old", "applied": False})
                continue
            if not change.get("auto_applicable"):
                resolution_log.append({"entity_type": entity_type, "entity_name": entity_name, "field": field, "action": "keep_old", "applied": False})
                continue
            merged_state[field] = change.get("new_value")
            applied = True
            resolution_log.append({"entity_type": entity_type, "entity_name": entity_name, "field": field, "action": "auto_apply", "applied": True})
        if applied:
            await self.entity_svc.update_state_from_import(entity_id, merged_state, diff_summary={"merged_from_pending": True})
            if applied_entity_ids is not None:
                applied_entity_ids.append(entity_id)
        return resolution_log

    async def _apply_entity_diffs_in_batches(
        self,
        novel_id: str,
        pending_id: str,
        entity_diffs: list[dict],
        *,
        field_resolutions: Optional[List[dict]] = None,
        batch_size: int = APPROVE_ENTITY_BATCH_SIZE,
        source_filename: str | None = None,
    ) -> dict[str, Any]:
        total = len(entity_diffs)
        result: dict[str, Any] = {
            "field_resolutions": [],
            "entity_batches": [],
            "entity_failures": [],
            "entity_classification_batches": [],
            "entity_total": total,
            "entity_applied": 0,
            "batch_size": batch_size,
        }
        if not total:
            return result

        self._log(
            novel_id,
            f"开始批量写入实体: {total} 个，每批 {batch_size} 个",
            event="agent.progress",
            status="started",
            node="approve_entities",
            task="approve_pending",
            metadata={"pending_id": pending_id, "entity_total": total, "batch_size": batch_size},
            source_filename=source_filename,
        )

        for start in range(0, total, batch_size):
            batch = entity_diffs[start:start + batch_size]
            batch_index = start // batch_size + 1
            batch_log = {
                "batch_index": batch_index,
                "start": start + 1,
                "end": start + len(batch),
                "total": total,
                "applied": 0,
                "failed": 0,
            }
            applied_entity_ids: list[str] = []
            self._log(
                novel_id,
                f"写入实体批次 {batch_index}: {batch_log['start']}-{batch_log['end']}/{total}",
                event="agent.progress",
                status="started",
                node="approve_entities_batch",
                task="approve_pending",
                metadata={**batch_log, "pending_id": pending_id},
                source_filename=source_filename,
            )

            for entity_diff in batch:
                entity_name = entity_diff.get("entity_name", "unknown")
                entity_type = entity_diff.get("entity_type", "other")
                try:
                    field_logs = await self._apply_entity_diff(
                        novel_id,
                        entity_diff,
                        field_resolutions=field_resolutions,
                        applied_entity_ids=applied_entity_ids,
                        source_filename=source_filename,
                    )
                    result["field_resolutions"].extend(field_logs)
                    result["entity_applied"] += 1
                    batch_log["applied"] += 1
                except Exception as exc:
                    failure = {
                        "entity_type": entity_type,
                        "entity_name": entity_name,
                        "operation": entity_diff.get("operation"),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    result["entity_failures"].append(failure)
                    batch_log["failed"] += 1
                    self._log(
                        novel_id,
                        f"实体写入失败: {entity_type}/{entity_name}: {exc}",
                        level="error",
                        event="agent.progress",
                        status="failed",
                        node="approve_entity",
                        task="approve_pending",
                        metadata={**failure, "pending_id": pending_id},
                        source_filename=source_filename,
                    )

            await self.session.flush()
            if applied_entity_ids:
                unique_entity_ids = list(dict.fromkeys(applied_entity_ids))
                self._log(
                    novel_id,
                    f"批量分类实体批次 {batch_index}: {len(unique_entity_ids)} 个",
                    event="agent.progress",
                    status="started",
                    node="entity_classify_batch",
                    task="approve_pending",
                    metadata={"pending_id": pending_id, "batch_index": batch_index, "entity_count": len(unique_entity_ids)},
                    source_filename=source_filename,
                )
                classification_result = await self.entity_svc.classify_entities_batch(unique_entity_ids)
                result["entity_classification_batches"].append({
                    "batch_index": batch_index,
                    **classification_result,
                })
                self._log(
                    novel_id,
                    f"实体批量分类完成 {batch_index}: {classification_result.get('updated', 0)}/{classification_result.get('total', 0)}",
                    event="agent.progress",
                    status="succeeded",
                    node="entity_classify_batch",
                    task="approve_pending",
                    metadata={"pending_id": pending_id, "batch_index": batch_index, **classification_result},
                    source_filename=source_filename,
                )
            result["entity_batches"].append(dict(batch_log))
            self._log(
                novel_id,
                f"实体批次 {batch_index} 完成: 成功 {batch_log['applied']}，失败 {batch_log['failed']}",
                event="agent.progress",
                status="succeeded" if batch_log["failed"] == 0 else "failed",
                node="approve_entities_batch",
                task="approve_pending",
                metadata={**batch_log, "pending_id": pending_id},
                source_filename=source_filename,
            )

        return result

    def _build_domain_entity_diffs(self, raw_result: dict, *, domain_id: str, domain_name: str) -> list[dict[str, Any]]:
        proposed_entities: list[tuple[str, dict[str, Any]]] = []
        for char in raw_result.get("character_profiles", []):
            proposed_entities.append(("character", dict(char)))
        for faction in self._normalize_setting_entities(raw_result.get("factions")):
            proposed_entities.append(("faction", dict(faction)))
        for location in self._normalize_setting_entities(raw_result.get("locations")):
            proposed_entities.append(("location", dict(location)))
        for item in raw_result.get("important_items", []):
            proposed_entities.append(("item", dict(item)))

        entity_diffs: list[dict[str, Any]] = []
        for entity_type, data in proposed_entities:
            entity_name = str(data.get("name") or "").strip()
            if not entity_name:
                continue
            local_state = {
                **data,
                "_knowledge_usage": "domain",
                "_knowledge_domain_id": domain_id,
                "_knowledge_domain_name": domain_name,
            }
            entity_diffs.append({
                "entity_type": entity_type,
                "entity_name": entity_name,
                "operation": "create",
                "field_changes": [
                    {
                        "field": key,
                        "label": key,
                        "old_value": "",
                        "new_value": value,
                    }
                    for key, value in local_state.items()
                    if value not in (None, "")
                ],
            })
        return entity_diffs

    async def _approve_knowledge_domain_pending(
        self,
        pe: PendingExtraction,
        *,
        domain,
        field_resolutions: Optional[List[dict]] = None,
    ) -> tuple[list[NovelDocument], dict[str, Any]]:
        raw = pe.raw_result or {}
        domain_name = domain.name if domain else "局部规则域"
        docs: list[NovelDocument] = []
        mappings = [
            ("worldview", "worldview", "世界观"),
            ("power_system", "setting", "修炼体系"),
            ("factions", "setting", "势力格局"),
            ("locations", "setting", "地点设定"),
            ("plot_synopsis", "synopsis", "剧情梗概"),
        ]
        for key, doc_type, title in mappings:
            val = raw.get(key)
            if not val:
                continue
            docs.append(await self._create_domain_setting_document(
                novel_id=pe.novel_id,
                domain_name=domain_name,
                doc_type=doc_type,
                title=title,
                content=self._format_setting_document_value(key, val),
            ))

        chars = raw.get("character_profiles", [])
        if chars:
            text = "\n".join(f"{c.get('name')}: {c.get('identity')} {c.get('personality')}" for c in chars)
            docs.append(await self._create_domain_setting_document(
                novel_id=pe.novel_id,
                domain_name=domain_name,
                doc_type="concept",
                title="人物设定",
                content=text,
            ))

        items = raw.get("important_items", [])
        if items:
            text = "\n".join(f"{i.get('name')}: {i.get('description')}" for i in items)
            docs.append(await self._create_domain_setting_document(
                novel_id=pe.novel_id,
                domain_name=domain_name,
                doc_type="concept",
                title="物品设定",
                content=text,
            ))

        entity_result = await self._apply_entity_diffs_in_batches(
            pe.novel_id,
            pe.id,
            self._build_domain_entity_diffs(raw, domain_id=domain.id if domain else "", domain_name=domain_name),
            field_resolutions=field_resolutions,
            source_filename=pe.source_filename or pe.id,
        )
        relationship_result = await RelationshipExtractionService(self.session).extract_and_persist_from_setting(
            novel_id=pe.novel_id,
            source_text=self._build_relationship_source_text(raw),
            source_ref=pe.source_filename or pe.id,
            domain_id=domain.id if domain else None,
            domain_name=domain_name,
        )
        resolution_result: dict[str, Any] = {
            "field_resolutions": [],
            "knowledge_usage": "domain",
            "domain_id": domain.id if domain else None,
            "domain_name": domain_name,
            "isolated_from_global_library": True,
            "local_document_ids": [doc.id for doc in docs],
            "relationship_extraction": relationship_result,
        }
        resolution_result.update(entity_result)
        if domain:
            source_doc_ids = list(domain.source_doc_ids or [])
            for doc_id in [pe.id, *resolution_result["local_document_ids"]]:
                if doc_id not in source_doc_ids:
                    source_doc_ids.append(doc_id)
            await self.domain_repo.update(domain, source_doc_ids=source_doc_ids)
        return docs, resolution_result


    async def process_upload(
        self,
        novel_id: str,
        filename: str,
        content: str,
        *,
        force_setting: bool = False,
    ) -> PendingExtraction:
        self._log(novel_id, "处理上传文件", source_filename=filename)
        payload = await self._build_pending_payload_from_content(
            novel_id,
            filename,
            content,
            force_setting=force_setting,
        )
        if payload.extraction_type == "setting":
            proposed_entity_count = len(payload.proposed_entities or [])
            self._log(
                novel_id,
                f"设定提取完成，待审核: {proposed_entity_count} 个实体",
                source_filename=filename,
            )
            return await self.persist_pending_payload(novel_id, payload)
        else:
            self._log(novel_id, "风格样本提取完成，待审核", source_filename=filename)
            return await self.persist_pending_payload(novel_id, payload)

    async def create_processing_upload(self, novel_id: str, filename: str) -> PendingExtraction:
        self._log(novel_id, "受理上传文件", source_filename=filename)
        return await self.pending_repo.create(
            pe_id=f"pe_{uuid.uuid4().hex[:8]}",
            novel_id=novel_id,
            source_filename=filename,
            extraction_type="processing",
            raw_result={},
            status="processing",
        )

    async def complete_processing_upload(
        self,
        pe_id: str,
        novel_id: str,
        filename: str,
        content: str,
        *,
        force_setting: bool = False,
    ) -> None:
        self._log(novel_id, "开始后台提取", source_filename=filename)
        payload = await self._build_pending_payload_from_content(
            novel_id,
            filename,
            content,
            force_setting=force_setting,
        )
        await self.pending_repo.update_payload(
            pe_id,
            extraction_type=payload.extraction_type,
            raw_result=payload.raw_result,
            proposed_entities=payload.proposed_entities,
            diff_result=payload.diff_result,
            status="pending",
            error_message=None,
        )
        if payload.extraction_type == "setting":
            proposed_entity_count = len(payload.proposed_entities or [])
            self._log(
                novel_id,
                f"设定提取完成，待审核: {proposed_entity_count} 个实体",
                source_filename=filename,
            )
        else:
            self._log(novel_id, "风格样本提取完成，待审核", source_filename=filename)

    async def fail_processing_upload(self, pe_id: str, error_message: str) -> None:
        await self.pending_repo.update_status(
            pe_id,
            "failed",
            error_message=error_message,
        )

    async def _build_pending_payload_from_content(
        self,
        novel_id: str,
        filename: str,
        content: str,
        *,
        force_setting: bool = False,
    ) -> PendingExtractionPayload:
        if force_setting:
            classification = FileClassificationResult(
                file_type="setting",
                confidence=1.0,
                reason="用户选择局部生效规则域，跳过文件分类并按设定资料处理",
            )
            self._log(
                novel_id,
                "跳过文件分类，按设定资料导入",
                event="agent.progress",
                status="succeeded",
                node="file_classify",
                task="classify_file",
                metadata={"force_setting": True},
                source_filename=filename,
            )
        else:
            classification = await self.classifier.classify(filename, content, novel_id)

        if classification.file_type == "setting":
            extracted = await self.setting_agent.extract(content, novel_id, source_filename=filename)
            raw_result = extracted.model_dump()
            if force_setting:
                raw_result["_knowledge_usage"] = "domain"
            proposed_entities = []
            for c in extracted.character_profiles:
                proposed_entities.append({"type": "character", "name": c.name, "data": c.model_dump()})
            for faction in extracted.factions:
                proposed_entities.append({"type": "faction", "name": faction.name, "data": faction.model_dump()})
            for location in extracted.locations:
                proposed_entities.append({"type": "location", "name": location.name, "data": location.model_dump()})
            for i in extracted.important_items:
                proposed_entities.append({"type": "item", "name": i.name, "data": i.model_dump()})
            diff_result = await self._build_setting_diff(novel_id, raw_result)
            return PendingExtractionPayload(
                source_filename=filename,
                extraction_type="setting",
                raw_result=raw_result,
                proposed_entities=proposed_entities,
                diff_result=diff_result,
            )

        profile = await self.style_agent.profile(content, novel_id)
        return PendingExtractionPayload(
            source_filename=filename,
            extraction_type="style_profile",
            raw_result=profile.model_dump(),
        )

    async def build_pending_payload_from_setting_draft(
        self,
        novel_id: str,
        draft: dict[str, Any],
    ) -> PendingExtractionPayload:
        normalized_draft = self.validate_setting_draft(draft)
        filename = (
            f"brainstorm-{normalized_draft['source_outline_ref']}-{normalized_draft['draft_id']}.md"
        )

        if normalized_draft["target_import_mode"] == "auto_classify":
            return await self._build_pending_payload_from_content(
                novel_id=novel_id,
                filename=filename,
                content=normalized_draft["content"],
            )

        raw_result, proposed_entities = self._build_explicit_setting_payload(normalized_draft)
        diff_result = await self._build_setting_diff(novel_id, raw_result)
        return PendingExtractionPayload(
            source_filename=filename,
            extraction_type="setting",
            raw_result=raw_result,
            proposed_entities=proposed_entities,
            diff_result=diff_result,
        )

    async def build_pending_payload_from_suggestion_card(
        self,
        novel_id: str,
        card: SettingSuggestionCardPayload,
    ) -> PendingExtractionPayload:
        payload = card.payload
        canonical_name = self._extract_suggestion_card_name(card)

        if card.card_type == "character":
            character_state = self._build_character_suggestion_state(canonical_name, payload)
            raw_result = {
                "character_profiles": [character_state],
            }
            diff_result = await self._build_suggestion_card_diff(
                novel_id=novel_id,
                entity_type="character",
                incoming_state=character_state,
            )
            return PendingExtractionPayload(
                source_filename=f"brainstorm-{card.merge_key}.md",
                extraction_type="setting",
                raw_result=raw_result,
                proposed_entities=[
                    {
                        "type": "character",
                        "name": canonical_name,
                        "data": character_state,
                    }
                ],
                diff_result=diff_result,
            )

        if card.card_type == "faction":
            faction_state = {
                "name": canonical_name,
                "position": payload.get("position", ""),
                "description": payload.get("description", ""),
            }
            return PendingExtractionPayload(
                source_filename=f"brainstorm-{card.merge_key}.md",
                extraction_type="setting",
                raw_result={},
                proposed_entities=[
                    {
                        "type": "faction",
                        "name": canonical_name,
                        "data": faction_state,
                    }
                ],
                diff_result=await self._build_suggestion_card_diff(
                    novel_id=novel_id,
                    entity_type="faction",
                    incoming_state=faction_state,
                ),
            )

        if card.card_type == "location":
            location_state = {
                "name": canonical_name,
                "description": payload.get("description", ""),
                "position": payload.get("position", ""),
            }
            return PendingExtractionPayload(
                source_filename=f"brainstorm-{card.merge_key}.md",
                extraction_type="setting",
                raw_result={},
                proposed_entities=[
                    {
                        "type": "location",
                        "name": canonical_name,
                        "data": location_state,
                    }
                ],
                diff_result=await self._build_suggestion_card_diff(
                    novel_id=novel_id,
                    entity_type="location",
                    incoming_state=location_state,
                ),
            )

        if card.card_type in {"item", "artifact_or_skill", "artifact", "skill"}:
            item_state = {
                "name": canonical_name,
                "description": payload.get("description", ""),
                "significance": payload.get("significance", ""),
            }
            return PendingExtractionPayload(
                source_filename=f"brainstorm-{card.merge_key}.md",
                extraction_type="setting",
                raw_result={"important_items": [item_state]},
                proposed_entities=[
                    {
                        "type": "item",
                        "name": canonical_name,
                        "data": item_state,
                    }
                ],
                diff_result=await self._build_suggestion_card_diff(
                    novel_id=novel_id,
                    entity_type="item",
                    incoming_state=item_state,
                ),
            )

        raise ValueError(f"Unsupported suggestion card type for pending payload: {card.card_type}")

    async def _build_suggestion_card_diff(
        self,
        novel_id: str,
        entity_type: str,
        incoming_state: dict[str, Any],
    ) -> dict[str, Any]:
        entity_diff = await self._build_entity_diff(novel_id, entity_type, incoming_state)
        entity_diffs = [] if entity_diff["operation"] == "noop" else [entity_diff]
        summary = "无实体变更"
        if entity_diff["operation"] == "create":
            summary = "1 个新增实体"
        elif entity_diff["operation"] == "update":
            summary = "1 个可自动补充实体"
        elif entity_diff["operation"] == "conflict":
            summary = "1 个冲突实体"
        return {
            "entity_diffs": entity_diffs,
            "document_changes": [],
            "summary": summary,
        }

    def _extract_suggestion_card_name(self, card: SettingSuggestionCardPayload) -> str:
        payload_name = card.payload.get("canonical_name") or card.payload.get("name")
        if isinstance(payload_name, str) and payload_name.strip():
            return payload_name.strip()
        return card.title.strip()

    def _build_character_suggestion_state(
        self,
        canonical_name: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        state = {"name": canonical_name}
        for field in CHARACTER_SUGGESTION_STATE_FIELDS:
            state[field] = payload.get(field, "")
        return state

    def _normalize_setting_entities(self, value: Any) -> list[dict[str, Any]]:
        if value in (None, "", []):
            return []
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict) and item.get("name")]
        if isinstance(value, dict):
            if value.get("name"):
                return [value]
            return [
                {"name": str(key).strip(), "description": self._stringify_value(item)}
                for key, item in value.items()
                if str(key).strip()
            ]

        result = []
        for line in str(value).splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            for separator in ("：", ":"):
                if separator in stripped:
                    name, desc = stripped.split(separator, 1)
                    result.append({"name": name.strip(), "description": desc.strip()})
                    break
            else:
                result.append({"name": stripped, "description": ""})
        return result

    def _format_setting_document_value(self, key: str, value: Any) -> str:
        if isinstance(value, str):
            return value
        if key == "factions":
            rows = []
            for item in self._normalize_setting_entities(value):
                relation = item.get("relationship_with_protagonist", "")
                suffix = f" (与主角关系: {relation})" if relation else ""
                rows.append(f"{item.get('name', '')}: {item.get('description', '')}{suffix}".rstrip())
            return "\n".join(row for row in rows if row.strip())
        if key == "locations":
            rows = []
            for item in self._normalize_setting_entities(value):
                region = item.get("region", "")
                suffix = f" [{region}]" if region else ""
                rows.append(f"{item.get('name', '')}: {item.get('description', '')}{suffix}".rstrip())
            return "\n".join(row for row in rows if row.strip())
        return str(value)

    async def persist_pending_payload(
        self,
        novel_id: str,
        payload: PendingExtractionPayload,
    ) -> PendingExtraction:
        return await self.pending_repo.create(
            pe_id=f"pe_{uuid.uuid4().hex[:8]}",
            novel_id=novel_id,
            source_filename=payload.source_filename,
            extraction_type=payload.extraction_type,
            raw_result=payload.raw_result,
            proposed_entities=payload.proposed_entities,
            diff_result=payload.diff_result,
        )

    async def create_pending_from_setting_draft(self, novel_id: str, draft: dict[str, Any]) -> PendingExtraction:
        payload = await self.build_pending_payload_from_setting_draft(novel_id, draft)
        return await self.persist_pending_payload(novel_id, payload)

    async def approve_pending(self, pe_id: str, field_resolutions: Optional[List[dict]] = None) -> List[NovelDocument]:
        pe = await self.pending_repo.get_by_id(pe_id)
        if not pe or pe.status != "pending":
            return []

        docs: List[NovelDocument] = []
        resolution_result = {"field_resolutions": []}
        if pe.extraction_type == "setting":
            domain = await self._get_knowledge_domain_for_pending(pe)
            if domain:
                docs, resolution_result = await self._approve_knowledge_domain_pending(
                    pe,
                    domain=domain,
                    field_resolutions=field_resolutions,
                )
                await self.pending_repo.update_status(pe_id, "approved", resolution_result=resolution_result)
                self._log(
                    pe.novel_id,
                    f"规则域资料审核通过，生成 {len(docs)} 份局部文档，写入 {resolution_result.get('entity_applied', 0)} 个局部实体: {pe.source_filename or pe.id}",
                    source_filename=pe.source_filename or pe.id,
                )
                return docs

            raw = pe.raw_result
            mappings = [
                ("worldview", "worldview", "世界观"),
                ("power_system", "setting", "修炼体系"),
                ("factions", "setting", "势力格局"),
                ("locations", "setting", "地点设定"),
                ("plot_synopsis", "synopsis", "剧情梗概"),
            ]
            for key, doc_type, title in mappings:
                val = raw.get(key)
                if val:
                    text_val = self._format_setting_document_value(key, val)
                    doc = await self._create_or_merge_setting_document(
                        novel_id=pe.novel_id,
                        doc_type=doc_type,
                        title=title,
                        content=text_val,
                        source_filename=pe.source_filename or pe.id,
                    )
                    docs.append(doc)

            chars = raw.get("character_profiles", [])
            if chars:
                text = "\n".join(f"{c.get('name')}: {c.get('identity')} {c.get('personality')}" for c in chars)
                doc = await self._create_or_merge_setting_document(
                    novel_id=pe.novel_id,
                    doc_type="concept",
                    title="人物设定",
                    content=text,
                    source_filename=pe.source_filename or pe.id,
                )
                docs.append(doc)

            items = raw.get("important_items", [])
            if items:
                text = "\n".join(f"{i.get('name')}: {i.get('description')}" for i in items)
                doc = await self._create_or_merge_setting_document(
                    novel_id=pe.novel_id,
                    doc_type="concept",
                    title="物品设定",
                    content=text,
                    source_filename=pe.source_filename or pe.id,
                )
                docs.append(doc)

            diff_result = pe.diff_result
            if not diff_result:
                diff_result = await self._build_setting_diff(pe.novel_id, raw)
            entity_result = await self._apply_entity_diffs_in_batches(
                pe.novel_id,
                pe_id,
                diff_result.get("entity_diffs", []),
                field_resolutions=field_resolutions,
                source_filename=pe.source_filename or pe.id,
            )
            resolution_result.update(entity_result)
            relationship_result = await RelationshipExtractionService(self.session).extract_and_persist_from_setting(
                novel_id=pe.novel_id,
                source_text=self._build_relationship_source_text(raw),
                source_ref=pe.source_filename or pe.id,
            )
            resolution_result["relationship_extraction"] = relationship_result

        else:
            latest = await self.doc_repo.get_latest_by_type(pe.novel_id, "style_profile")
            new_profile = StyleProfile(**pe.raw_result)
            if latest:
                old_config = StyleConfig()
                if latest.title:
                    try:
                        old_config = StyleConfig(**json.loads(latest.title))
                    except Exception as exc:
                        self._log(
                            pe.novel_id,
                            f"旧风格配置解析失败: {exc}",
                            level="warning",
                            source_filename=pe.source_filename or pe.id,
                        )
                old = StyleProfile(style_guide=latest.content, style_config=old_config)
                merged = self.merger.merge(old, new_profile)
                doc = await self.doc_repo.save_new_version(
                    doc_id=f"doc_{uuid.uuid4().hex[:8]}",
                    novel_id=pe.novel_id,
                    doc_type="style_profile",
                    title=merged.merged_profile.style_config.model_dump_json(),
                    content=merged.merged_profile.style_guide,
                )
            else:
                doc = await self.doc_repo.save_new_version(
                    doc_id=f"doc_{uuid.uuid4().hex[:8]}",
                    novel_id=pe.novel_id,
                    doc_type="style_profile",
                    title=new_profile.style_config.model_dump_json(),
                    content=new_profile.style_guide,
                )
            docs.append(doc)

        await self.pending_repo.update_status(pe_id, "approved", resolution_result=resolution_result)
        await self._index_documents(docs)
        self._log(
            pe.novel_id,
            f"审核通过，生成 {len(docs)} 份文档",
            source_filename=pe.source_filename or pe.id,
        )
        return docs

    def _build_relationship_source_text(self, raw_result: dict[str, Any]) -> str:
        return json.dumps(raw_result or {}, ensure_ascii=False)

    async def _get_knowledge_domain_for_pending(self, pe: PendingExtraction):
        raw_result = pe.raw_result or {}
        domains = await self.domain_repo.list_by_novel(pe.novel_id, include_disabled=True)
        matched = next((domain for domain in domains if pe.id in (domain.source_doc_ids or [])), None)
        if matched:
            return matched
        if raw_result.get("_knowledge_usage") == "domain":
            return next((domain for domain in domains if domain.name in (pe.source_filename or "")), None)
        return None

    async def reject_pending(self, pe_id: str) -> bool:
        pe = await self.pending_repo.get_by_id(pe_id)
        if not pe or pe.status != "pending":
            return False
        deleted = await self.pending_repo.delete(pe_id)
        if deleted:
            self._log(
                pe.novel_id,
                "已拒绝并丢弃待审核记录",
                source_filename=pe.source_filename or pe.id,
            )
        return deleted

    async def delete_cancelable_pending(self, pe_id: str) -> bool:
        pe = await self.pending_repo.get_by_id(pe_id)
        if not pe or pe.status not in {"failed", "processing"}:
            return False
        deleted = await self.pending_repo.delete(pe_id)
        if deleted:
            action = "取消导入" if pe.status == "processing" else "删除失败记录"
            self._log(pe.novel_id, action, source_filename=pe.source_filename or pe.id)
        return deleted

    async def delete_failed_pending(self, pe_id: str) -> bool:
        return await self.delete_cancelable_pending(pe_id)

    async def list_approved_documents(self, novel_id: str) -> List[NovelDocument]:
        return await self.doc_repo.list_by_novel(novel_id)

    async def get_approved_document(self, novel_id: str, doc_id: str) -> Optional[NovelDocument]:
        return await self.doc_repo.get_by_id_for_novel(novel_id, doc_id)

    async def list_document_versions(self, novel_id: str, doc_type: str) -> List[NovelDocument]:
        return await self.doc_repo.list_versions(novel_id, doc_type)

    async def list_document_versions_for_document(self, novel_id: str, doc_id: str) -> List[NovelDocument]:
        doc = await self.doc_repo.get_by_id_for_novel(novel_id, doc_id)
        if doc is None:
            return []
        return await self.doc_repo.list_versions(novel_id, doc.doc_type)

    async def save_document_version(self, novel_id: str, doc_id: str, title: str, content: str) -> Optional[NovelDocument]:
        doc = await self.doc_repo.get_by_id_for_novel(novel_id, doc_id)
        if doc is None:
            return None
        saved = await self.doc_repo.save_new_version(
            doc_id=f"doc_{uuid.uuid4().hex[:8]}",
            novel_id=novel_id,
            doc_type=doc.doc_type,
            title=title,
            content=content,
        )
        await self._index_documents([saved])
        return saved

    async def reindex_document(self, novel_id: str, doc_id: str) -> Optional[NovelDocument]:
        doc = await self.doc_repo.get_by_id_for_novel(novel_id, doc_id)
        if doc is None:
            return None
        await self._index_documents([doc])
        return doc

    async def _index_documents(self, docs: List[NovelDocument]) -> None:
        if self.embedding_service is None:
            return
        index_document = getattr(self.embedding_service, "index_document", None)
        if not callable(index_document):
            return
        for doc in docs:
            await index_document(doc.id)

    async def get_active_style_profile(self, novel_id: str) -> Optional[NovelDocument]:
        state = await self.state_repo.get_state(novel_id)
        active_version = None
        if state and state.checkpoint_data:
            active_version = state.checkpoint_data.get("active_style_profile_version")
        if active_version:
            return await self.doc_repo.get_by_type_and_version(novel_id, "style_profile", active_version)
        return await self.doc_repo.get_latest_by_type(novel_id, "style_profile")

    async def rollback_style_profile(self, novel_id: str, version: int) -> None:
        state = await self.state_repo.get_state(novel_id)
        if state is None:
            await self.state_repo.save_checkpoint(
                novel_id=novel_id,
                current_phase="context_preparation",
                checkpoint_data={"active_style_profile_version": version},
            )
        else:
            checkpoint = dict(state.checkpoint_data)
            checkpoint["active_style_profile_version"] = version
            await self.state_repo.save_checkpoint(
                novel_id=novel_id,
                current_phase=state.current_phase,
                checkpoint_data=checkpoint,
                current_volume_id=state.current_volume_id,
                current_chapter_id=state.current_chapter_id,
            )

    async def update_library_document(
        self,
        novel_id: str,
        *,
        doc_id: str,
        content: str,
    ) -> NovelDocument:
        existing = await self.doc_repo.get_by_id(doc_id)
        if not existing or existing.novel_id != novel_id:
            raise ValueError("资料文档不存在")

        latest = await self.doc_repo.get_latest_by_type_and_title(
            novel_id,
            existing.doc_type,
            existing.title,
        )
        next_version = ((latest.version if latest else existing.version) or 0) + 1
        updated = await self.doc_repo.create(
            doc_id=f"doc_{uuid.uuid4().hex[:8]}",
            novel_id=novel_id,
            doc_type=existing.doc_type,
            title=existing.title,
            content=content,
            version=next_version,
        )
        if existing.doc_type == "style_profile":
            await self.rollback_style_profile(novel_id, updated.version)
        log_service.add_log(
            novel_id,
            "ExtractionService",
            f"资料库文档已更新: {existing.doc_type}/{existing.title} -> v{updated.version}",
        )
        return updated
