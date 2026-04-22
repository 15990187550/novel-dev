import uuid
import json
import logging
from typing import Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.agents.file_classifier import FileClassifier
from novel_dev.agents.setting_extractor import SettingExtractorAgent
from novel_dev.agents.style_profiler import StyleProfilerAgent, StyleProfile, StyleConfig
from novel_dev.agents.profile_merger import ProfileMerger
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.pending_extraction_repo import PendingExtractionRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.services.entity_service import EntityService
from novel_dev.services.embedding_service import EmbeddingService
from novel_dev.services.log_service import log_service
from novel_dev.db.models import NovelDocument, PendingExtraction
from novel_dev.llm import llm_factory
from novel_dev.llm.models import ChatMessage
from novel_dev.schemas.brainstorm_workspace import (
    PendingExtractionPayload,
    SettingDocDraftPayload,
)

logger = logging.getLogger(__name__)

AUTO_APPLY_FIELDS = {
    "appearance",
    "background",
    "ability",
    "resources",
    "notes",
    "description",
    "significance",
}

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
}


class ExtractionService:
    def __init__(self, session: AsyncSession, embedding_service: Optional[EmbeddingService] = None):
        self.session = session
        self.embedding_service = embedding_service
        self.classifier = FileClassifier()
        self.setting_agent = SettingExtractorAgent()
        self.style_agent = StyleProfilerAgent()
        self.merger = ProfileMerger()
        self.doc_repo = DocumentRepository(session)
        self.pending_repo = PendingExtractionRepository(session)
        self.state_repo = NovelStateRepository(session)
        self.entity_svc = EntityService(session, embedding_service)

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
            "factions": "",
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
        log_service.add_log(novel_id, "ExtractionService", f"字段自动合并完成: {entity_name}.{field}")
        return merged_text

    async def _build_setting_diff(self, novel_id: str, raw_result: dict) -> dict:
        entity_diffs = []
        summary_parts = []

        for char in raw_result.get("character_profiles", []):
            entity_diff = await self._build_entity_diff(novel_id, "character", char)
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

    async def _apply_entity_diff(self, novel_id: str, entity_diff: dict, field_resolutions: Optional[List[dict]] = None) -> list[dict]:
        entity_name = entity_diff.get("entity_name", "unknown")
        entity_type = entity_diff.get("entity_type", "other")
        resolution_log: list[dict] = []
        if entity_diff.get("operation") == "create":
            initial_state = {change["field"]: change.get("new_value") for change in entity_diff.get("field_changes", [])}
            initial_state["name"] = entity_name
            await self.entity_svc.create_entity(
                entity_id=f"ent_{uuid.uuid4().hex[:8]}",
                entity_type=entity_type,
                name=entity_name,
                novel_id=novel_id,
                initial_state=initial_state,
            )
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
            await self.entity_svc.update_state(entity_id, merged_state, diff_summary={"merged_from_pending": True})
        return resolution_log

    async def process_upload(self, novel_id: str, filename: str, content: str) -> PendingExtraction:
        log_service.add_log(novel_id, "ExtractionService", f"处理上传文件: {filename}")
        payload = await self._build_pending_payload_from_content(novel_id, filename, content)
        if payload.extraction_type == "setting":
            proposed_entity_count = len(payload.proposed_entities or [])
            log_service.add_log(
                novel_id,
                "ExtractionService",
                f"设定提取完成，待审核: {proposed_entity_count} 个实体",
            )
            return await self.persist_pending_payload(novel_id, payload)
        else:
            log_service.add_log(novel_id, "ExtractionService", "风格样本提取完成，待审核")
            return await self.persist_pending_payload(novel_id, payload)

    async def create_processing_upload(self, novel_id: str, filename: str) -> PendingExtraction:
        log_service.add_log(novel_id, "ExtractionService", f"受理上传文件: {filename}")
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
    ) -> None:
        log_service.add_log(novel_id, "ExtractionService", f"开始后台提取: {filename}")
        payload = await self._build_pending_payload_from_content(novel_id, filename, content)
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
            log_service.add_log(
                novel_id,
                "ExtractionService",
                f"设定提取完成，待审核: {proposed_entity_count} 个实体",
            )
        else:
            log_service.add_log(novel_id, "ExtractionService", "风格样本提取完成，待审核")

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
    ) -> PendingExtractionPayload:
        classification = await self.classifier.classify(filename, content, novel_id)

        if classification.file_type == "setting":
            extracted = await self.setting_agent.extract(content, novel_id)
            raw_result = extracted.model_dump()
            proposed_entities = []
            for c in extracted.character_profiles:
                proposed_entities.append({"type": "character", "name": c.name, "data": c.model_dump()})
            for i in extracted.important_items:
                proposed_entities.append({"type": "item", "name": i.name, "data": i.model_dump()})
            if extracted.factions:
                proposed_entities.append({"type": "faction", "name": "extracted_factions", "data": {"factions": extracted.factions}})
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
            raw = pe.raw_result
            mappings = [
                ("worldview", "worldview", "世界观"),
                ("power_system", "setting", "修炼体系"),
                ("factions", "setting", "势力格局"),
                ("plot_synopsis", "synopsis", "剧情梗概"),
            ]
            for key, doc_type, title in mappings:
                val = raw.get(key)
                if val:
                    text_val = val if isinstance(val, str) else str(val)
                    doc = await self.doc_repo.create(
                        doc_id=f"doc_{uuid.uuid4().hex[:8]}",
                        novel_id=pe.novel_id,
                        doc_type=doc_type,
                        title=title,
                        content=text_val,
                    )
                    docs.append(doc)

            chars = raw.get("character_profiles", [])
            if chars:
                text = "\n".join(f"{c.get('name')}: {c.get('identity')} {c.get('personality')}" for c in chars)
                doc = await self.doc_repo.create(
                    doc_id=f"doc_{uuid.uuid4().hex[:8]}",
                    novel_id=pe.novel_id,
                    doc_type="concept",
                    title="人物设定",
                    content=text,
                )
                docs.append(doc)

            items = raw.get("important_items", [])
            if items:
                text = "\n".join(f"{i.get('name')}: {i.get('description')}" for i in items)
                doc = await self.doc_repo.create(
                    doc_id=f"doc_{uuid.uuid4().hex[:8]}",
                    novel_id=pe.novel_id,
                    doc_type="concept",
                    title="物品设定",
                    content=text,
                )
                docs.append(doc)

            diff_result = pe.diff_result
            if not diff_result:
                diff_result = await self._build_setting_diff(pe.novel_id, raw)
            for entity_diff in diff_result.get("entity_diffs", []):
                resolution_result["field_resolutions"].extend(
                    await self._apply_entity_diff(pe.novel_id, entity_diff, field_resolutions=field_resolutions)
                )

        else:
            latest = await self.doc_repo.get_latest_by_type(pe.novel_id, "style_profile")
            new_profile = StyleProfile(**pe.raw_result)
            if latest:
                old_config = StyleConfig()
                if latest.title:
                    try:
                        old_config = StyleConfig(**json.loads(latest.title))
                    except Exception as exc:
                        log_service.add_log(pe.novel_id, "ExtractionService", f"旧风格配置解析失败: {exc}", level="warning")
                old = StyleProfile(style_guide=latest.content, style_config=old_config)
                merged = self.merger.merge(old, new_profile)
                version = latest.version + 1
                doc = await self.doc_repo.create(
                    doc_id=f"doc_{uuid.uuid4().hex[:8]}",
                    novel_id=pe.novel_id,
                    doc_type="style_profile",
                    title=merged.merged_profile.style_config.model_dump_json(),
                    content=merged.merged_profile.style_guide,
                    version=version,
                )
            else:
                doc = await self.doc_repo.create(
                    doc_id=f"doc_{uuid.uuid4().hex[:8]}",
                    novel_id=pe.novel_id,
                    doc_type="style_profile",
                    title=new_profile.style_config.model_dump_json(),
                    content=new_profile.style_guide,
                    version=1,
                )
            docs.append(doc)

        await self.pending_repo.update_status(pe_id, "approved", resolution_result=resolution_result)
        log_service.add_log(pe.novel_id, "ExtractionService", f"审核通过，生成 {len(docs)} 份文档")
        return docs

    async def reject_pending(self, pe_id: str) -> bool:
        pe = await self.pending_repo.get_by_id(pe_id)
        if not pe or pe.status != "pending":
            return False
        deleted = await self.pending_repo.delete(pe_id)
        if deleted:
            log_service.add_log(pe.novel_id, "ExtractionService", f"已拒绝并丢弃待审核记录: {pe.source_filename or pe.id}")
        return deleted

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
