import json
import logging
import re
import uuid
from typing import Optional
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.librarian import (
    ExtractionResult,
    TimelineEvent,
    SpacelineChange,
    NewEntity,
    EntityUpdate,
    NewForeshadowing,
    NewRelationship,
)
from novel_dev.llm.models import ChatMessage

logger = logging.getLogger(__name__)

_MD_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)
_FIRST_OBJ_RE = re.compile(r"\{[\s\S]*\}")
_POLICY_EVENT_LOG_LIMIT = 20


from novel_dev.repositories.timeline_repo import TimelineRepository
from novel_dev.repositories.spaceline_repo import SpacelineRepository
from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
from novel_dev.repositories.relationship_repo import RelationshipRepository
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.services.entity_service import EntityService
from novel_dev.services.entity_state_policy import EntityStatePolicy
from novel_dev.services.embedding_service import EmbeddingService
from novel_dev.services.log_service import logged_agent_step, log_service
from novel_dev.services.world_state_diff_guard_service import WorldStateDiffGuardService
from novel_dev.agents._llm_helpers import call_and_parse_model
from novel_dev.agents._log_helpers import log_agent_detail, named_items, preview_text


def _parse_soft_state_json(text: str) -> dict:
    if not text:
        return {}
    cleaned = _MD_FENCE_RE.sub("", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    m = _FIRST_OBJ_RE.search(cleaned)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {}


class SoftStateUpdate(EntityUpdate):
    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_fields(cls, value):
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        if "entity_id" not in normalized:
            normalized["entity_id"] = normalized.get("name", "")
        if "state" not in normalized:
            normalized["state"] = {}
        if "diff_summary" not in normalized:
            normalized["diff_summary"] = {"source": "soft_state_pass"}
        return normalized


class SoftStateRelationship(NewRelationship):
    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_fields(cls, value):
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        if "source_entity_id" not in normalized:
            normalized["source_entity_id"] = normalized.get("source", "")
        if "target_entity_id" not in normalized:
            normalized["target_entity_id"] = normalized.get("target", "")
        if "relation_type" not in normalized:
            normalized["relation_type"] = normalized.get("type", "unspecified")
        if "meta" not in normalized:
            normalized["meta"] = {}
        return normalized


class SoftStateExtraction(BaseModel):
    character_updates: list[SoftStateUpdate] = Field(default_factory=list)
    new_relationships: list[SoftStateRelationship] = Field(default_factory=list)


class LibrarianAgent:
    def __init__(self, session: AsyncSession, embedding_service: Optional[EmbeddingService] = None):
        self.session = session
        self.embedding_service = embedding_service

    async def _load_context(self, novel_id: str, chapter_id: str) -> dict:
        entity_svc = EntityService(self.session, self.embedding_service)
        foreshadowing_repo = ForeshadowingRepository(self.session)
        spaceline_repo = SpacelineRepository(self.session)
        timeline_repo = TimelineRepository(self.session)

        active_fs = await foreshadowing_repo.list_active(novel_id=novel_id)
        current_tick = await timeline_repo.get_current_tick(novel_id=novel_id) or 0

        return {
            "novel_id": novel_id,
            "chapter_id": chapter_id,
            "pending_foreshadowings": [
                {"id": fs.id, "content": fs.content} for fs in active_fs
            ],
            "current_tick": current_tick,
        }

    def _build_prompt(self, polished_text: str, context: dict) -> str:
        return (
            "你是一个小说世界状态提取器。从以下精修章节文本中提取对世界状态的变更。\n"
            "返回严格 JSON，包含以下顶级键："
            "timeline_events, spaceline_changes, new_entities, concept_updates, "
            "character_updates, foreshadowings_recovered, new_foreshadowings, new_relationships。\n"
            "规则：只提取文本中明确发生或暗示的变更；人物状态变更必须是具体键值对；"
            "若 pending_foreshadowings 中的内容在文本中被解答，将其 ID 放入 foreshadowings_recovered；"
            "new_relationships 的 source_entity_id 和 target_entity_id 必须是已存在的实体名（匹配 new_entities 或 character_updates 中的 name）。\n"
            f"当前 pending_foreshadowings: {json.dumps(context.get('pending_foreshadowings', []), ensure_ascii=False)}\n"
            f"当前时间 tick: {context.get('current_tick', 0)}\n"
            f"章节文本：\n{polished_text}\n"
        )

    async def _call_llm(self, prompt: str) -> str:
        client = llm_factory.get("LibrarianAgent", task="extract")
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        return response.text

    def _build_soft_state_prompt(self, polished_text: str, primary: ExtractionResult) -> str:
        """第二 pass:专攻隐性的角色情感/关系变化,这些在一 pass 里容易被硬事实挤掉。"""
        primary_names = [e.name for e in primary.new_entities]
        primary_updates = [u.entity_id for u in primary.character_updates if u.entity_id]
        return (
            "你是一位小说关系分析师。请从以下章节文本中**只**提取隐性的角色情感与关系变化,"
            "忽略已经被明确记录的事件/地点/新实体(第一 pass 已处理)。严格 JSON 返回,"
            "格式为 {\"character_updates\": [...], \"new_relationships\": [...]}\n\n"
            "## 抽取准则\n"
            "- character_updates:关注角色内在状态(态度、信念、情绪基调、对某人看法)发生的**变化**,"
            "不抽取首次出现的静态设定。每条 state 写成具体的键值(如 {\"attitude_to_X\": \"从冷漠转为戒备\"})。\n"
            "- new_relationships:关注本章新建立或显著变更的角色间关系(信任、敌对、债务、师承、情感投射等),"
            "relation_type 写具体词(如 trust/rival/debt/romantic_interest),不要抽象标签。\n"
            "- 如果本章确无隐性变化,两个字段都可以是空数组。\n"
            "- source_entity_id/target_entity_id/entity_id 用角色名字即可,后续会映射到实体 ID。\n\n"
            f"## 本章已识别实体(避免重复): {primary_names + primary_updates}\n\n"
            f"## 章节文本\n{polished_text}\n\n请返回 JSON:"
        )

    async def _extract_soft_state(
        self, polished_text: str, primary: ExtractionResult, novel_id: str = ""
    ) -> tuple[list, list]:
        """返回 (character_updates, new_relationships) 补充列表。失败时返回空以不影响硬事实抽取。"""
        prompt = self._build_soft_state_prompt(polished_text, primary)

        try:
            payload = await call_and_parse_model(
                "LibrarianAgent", "extract_relationships", prompt,
                SoftStateExtraction, max_retries=2, novel_id=novel_id
            )
            updates_raw = payload.character_updates
            rels_raw = payload.new_relationships
            updates = []
            for u in updates_raw:
                try:
                    updates.append(u)
                except Exception as exc:
                    log_service.add_log(novel_id, "LibrarianAgent", f"软状态更新解析失败: {exc}", level="warning")
                    continue
            rels = []
            for r in rels_raw:
                try:
                    rels.append(r)
                except Exception as exc:
                    log_service.add_log(novel_id, "LibrarianAgent", f"软状态关系解析失败: {exc}", level="warning")
                    continue
            return updates, rels
        except Exception as exc:
            logger.warning("librarian_soft_state_pass_failed", extra={"error": str(exc)})
            log_service.add_log(novel_id, "LibrarianAgent", f"软状态提取失败: {exc}", level="warning")
            return [], []

    @logged_agent_step("LibrarianAgent", "提取世界状态", node="librarian_extract", task="extract")
    async def extract(self, novel_id: str, chapter_id: str, polished_text: str) -> ExtractionResult:
        log_agent_detail(
            novel_id,
            "LibrarianAgent",
            "世界状态抽取输入已准备",
            node="librarian_extract_input",
            task="extract",
            status="started",
            metadata={
                "chapter_id": chapter_id,
                "polished_chars": len(polished_text or ""),
                "polished_preview": preview_text(polished_text, 300),
            },
        )
        context = await self._load_context(novel_id, chapter_id)
        prompt = self._build_prompt(polished_text, context)
        extraction = await call_and_parse_model(
            "LibrarianAgent", "extract", prompt, ExtractionResult, novel_id=novel_id
        )

        # 第二 pass:补抽隐性的情感/关系变化(硬事实常挤掉软状态)
        log_service.add_log(novel_id, "LibrarianAgent", "开始第二 pass (软状态/关系) 提取")
        soft_updates, soft_rels = await self._extract_soft_state(polished_text, extraction, novel_id=novel_id)
        if soft_updates:
            existing_ids = {u.entity_id for u in extraction.character_updates}
            extraction.character_updates.extend(u for u in soft_updates if u.entity_id not in existing_ids)
            log_service.add_log(novel_id, "LibrarianAgent", f"补充软状态更新: {len(soft_updates)} 条")
        if soft_rels:
            existing_pairs = {
                (r.source_entity_id, r.target_entity_id, r.relation_type)
                for r in extraction.new_relationships
            }
            extraction.new_relationships.extend(
                r for r in soft_rels
                if (r.source_entity_id, r.target_entity_id, r.relation_type) not in existing_pairs
            )
            log_service.add_log(novel_id, "LibrarianAgent", f"补充关系更新: {len(soft_rels)} 条")
        log_agent_detail(
            novel_id, "LibrarianAgent",
            f"提取完成: 时间线 {len(extraction.timeline_events)} 条, 新实体 {len(extraction.new_entities)} 个, "
            f"角色更新 {len(extraction.character_updates)} 条, 回收伏笔 {len(extraction.foreshadowings_recovered)} 条, "
            f"新伏笔 {len(extraction.new_foreshadowings)} 条, 新关系 {len(extraction.new_relationships)} 条",
            node="librarian_extract_result",
            task="extract",
            metadata={
                "chapter_id": chapter_id,
                "counts": {
                    "timeline_events": len(extraction.timeline_events),
                    "spaceline_changes": len(extraction.spaceline_changes),
                    "new_entities": len(extraction.new_entities),
                    "concept_updates": len(extraction.concept_updates),
                    "character_updates": len(extraction.character_updates),
                    "foreshadowings_recovered": len(extraction.foreshadowings_recovered),
                    "new_foreshadowings": len(extraction.new_foreshadowings),
                    "new_relationships": len(extraction.new_relationships),
                },
                "timeline_events": named_items([event.model_dump() for event in extraction.timeline_events], limit=8),
                "new_entities": named_items([entity.model_dump() for entity in extraction.new_entities], limit=8),
                "character_updates": named_items([update.model_dump() for update in extraction.character_updates], limit=8),
                "new_foreshadowings": named_items([fs.model_dump() for fs in extraction.new_foreshadowings], limit=8),
                "relationships": [
                    {
                        "source": rel.source_entity_id,
                        "target": rel.target_entity_id,
                        "type": rel.relation_type,
                    }
                    for rel in extraction.new_relationships[:8]
                ],
            },
        )
        return extraction

    def fallback_extract(self, polished_text: str, checkpoint_data: dict) -> ExtractionResult:
        timeline_events = []
        spaceline_changes = []
        new_entities = []
        character_updates = []
        concept_updates = []
        foreshadowings_recovered = []
        new_foreshadowings = []
        new_relationships = []

        # Timeline heuristic
        time_matches = re.findall(r'\d+\s*天[前后]|三[天日]后|一[个]?月[前后]', polished_text)
        base_tick = checkpoint_data.get("current_tick", 0) if isinstance(checkpoint_data, dict) else 0
        for m in time_matches:
            digit_match = re.search(r'(\d+)', m)
            if digit_match:
                base_tick += int(digit_match.group(1))
            else:
                base_tick += 3
            timeline_events.append(TimelineEvent(tick=base_tick, narrative=m))

        # Spaceline heuristic
        loc_matches = re.findall(r'(?:来到|抵达|进入)\s*([\u4e00-\u9fa5A-Z][\u4e00-\u9fa5A-Za-z\s]+)', polished_text)
        for loc in loc_matches:
            spaceline_changes.append(SpacelineChange(location_id=f"loc_{loc.strip()}", name=loc.strip()))

        # New entities / character updates heuristic
        known_names = checkpoint_data.get("active_entities", []) if isinstance(checkpoint_data, dict) else []
        candidates = re.findall(r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+', polished_text)
        for cand in candidates:
            if cand not in known_names:
                new_entities.append(NewEntity(type="character", name=cand, state={"mentioned": True}))

        # Foreshadowing heuristics
        pending = checkpoint_data.get("pending_foreshadowings", []) if isinstance(checkpoint_data, dict) else []
        for fs in pending:
            if fs.get("content") and fs["content"] in polished_text:
                foreshadowings_recovered.append(fs["id"])
        if re.search(r'谜团|未解|悬念|秘密', polished_text):
            new_foreshadowings.append(NewForeshadowing(content="文本中检测到新的悬念线索"))

        return ExtractionResult(
            timeline_events=timeline_events,
            spaceline_changes=spaceline_changes,
            new_entities=new_entities,
            character_updates=character_updates,
            concept_updates=concept_updates,
            foreshadowings_recovered=foreshadowings_recovered,
            new_foreshadowings=new_foreshadowings,
            new_relationships=new_relationships,
        )

    @logged_agent_step("LibrarianAgent", "持久化世界状态", node="librarian_persist", task="persist")
    async def persist(self, extraction: ExtractionResult, chapter_id: str, novel_id: str) -> None:
        log_agent_detail(
            novel_id,
            "LibrarianAgent",
            "世界状态持久化输入已准备",
            node="librarian_persist_input",
            task="persist",
            status="started",
            metadata={
                "chapter_id": chapter_id,
                "counts": {
                    "timeline_events": len(extraction.timeline_events),
                    "spaceline_changes": len(extraction.spaceline_changes),
                    "new_entities": len(extraction.new_entities),
                    "concept_updates": len(extraction.concept_updates),
                    "character_updates": len(extraction.character_updates),
                    "foreshadowings_recovered": len(extraction.foreshadowings_recovered),
                    "new_foreshadowings": len(extraction.new_foreshadowings),
                    "new_relationships": len(extraction.new_relationships),
                },
            },
        )
        timeline_repo = TimelineRepository(self.session)
        spaceline_repo = SpacelineRepository(self.session)
        entity_svc = EntityService(self.session, self.embedding_service)
        foreshadowing_repo = ForeshadowingRepository(self.session)
        relationship_repo = RelationshipRepository(self.session)
        entity_repo = EntityRepository(self.session)
        world_state_diff = await WorldStateDiffGuardService(self.session).analyze(extraction, novel_id)
        log_agent_detail(
            novel_id,
            "LibrarianAgent",
            f"世界状态 diff 审核: {world_state_diff.status}",
            node="librarian_world_state_diff",
            task="persist",
            status="failed" if world_state_diff.status == "confirm_required" else "succeeded",
            level="warning" if world_state_diff.status != "safe" else "info",
            metadata=world_state_diff.model_dump(),
        )
        if world_state_diff.status == "confirm_required":
            raise RuntimeError("World state diff requires confirmation before librarian persistence")

        # Track name -> entity_id for relationship resolution
        name_to_id: dict[str, str] = {}
        persist_stats = {
            "created": {
                "timeline_events": 0,
                "spaceline_changes": 0,
                "new_entities": 0,
                "foreshadowings": 0,
                "relationships": 0,
            },
            "updated": {
                "timeline_events": 0,
                "spaceline_changes": 0,
                "entities": 0,
                "foreshadowings_recovered": 0,
            },
            "normalized": {
                "spaceline_parent_ids": [],
            },
            "policy_events": [],
            "policy_event_count": 0,
            "world_state_diff": world_state_diff.model_dump(),
            "skipped": [],
            "failed": [],
        }

        for event in extraction.timeline_events:
            _entry, created = await timeline_repo.create_or_merge(
                event.tick,
                event.narrative,
                anchor_chapter_id=chapter_id,
                anchor_event_id=event.anchor_event_id,
                novel_id=novel_id,
            )
            if created:
                persist_stats["created"]["timeline_events"] += 1
            else:
                persist_stats["updated"]["timeline_events"] += 1

        for change in extraction.spaceline_changes:
            parent_id = await self._normalize_spaceline_parent_id(
                change.location_id,
                change.parent_id,
                novel_id,
                spaceline_repo,
                persist_stats,
            )
            node = await spaceline_repo.get_by_id(change.location_id)
            if node:
                node.name = change.name
                node.parent_id = parent_id
                node.narrative = change.narrative or node.narrative
                await self.session.flush()
                persist_stats["updated"]["spaceline_changes"] += 1
            else:
                await spaceline_repo.create(change.location_id, change.name, parent_id, change.narrative, novel_id=novel_id)
                persist_stats["created"]["spaceline_changes"] += 1

        for entity in extraction.new_entities:
            eid = str(uuid.uuid4())
            existing, ambiguous = await self._find_existing_new_entity(
                entity.name,
                entity.type,
                novel_id,
                entity_repo,
            )
            if ambiguous:
                reason = {
                    "type": "new_entity",
                    "entity_name": entity.name,
                    "entity_type": entity.type,
                    "reason": "ambiguous_existing_entity",
                }
                persist_stats["skipped"].append(reason)
                log_agent_detail(
                    novel_id,
                    "LibrarianAgent",
                    f"新实体跳过：同名实体不唯一 {entity.name}",
                    node="librarian_persist_skip",
                    task="persist",
                    status="failed",
                    level="warning",
                    metadata=reason,
                )
                continue
            if existing is None:
                persisted = await entity_repo.create(eid, entity.type, entity.name, chapter_id, novel_id)
                persist_stats["created"]["new_entities"] += 1
            else:
                persisted = existing
                persist_stats["updated"]["entities"] += 1
            name_to_id[entity.name] = persisted.id
            await self._apply_entity_state_policy(
                entity_svc=entity_svc,
                entity_repo=entity_repo,
                entity_id=persisted.id,
                entity_ref=entity.name,
                extracted_state=entity.state,
                chapter_id=chapter_id,
                diff_summary={"created": existing is None},
                persist_stats=persist_stats,
            )

        for update in extraction.concept_updates + extraction.character_updates:
            resolved = await self._resolve_entity_id(update.entity_id, novel_id, name_to_id, entity_repo)
            if not resolved:
                reason = {"type": "entity_update", "entity_id": update.entity_id, "reason": "entity_not_found"}
                persist_stats["skipped"].append(reason)
                log_agent_detail(
                    novel_id,
                    "LibrarianAgent",
                    f"角色更新跳过：实体未找到 {update.entity_id}",
                    node="librarian_persist_skip",
                    task="persist",
                    status="failed",
                    level="warning",
                    metadata=reason,
                )
                continue
            entity_obj = await self._apply_entity_state_policy(
                entity_svc=entity_svc,
                entity_repo=entity_repo,
                entity_id=resolved,
                entity_ref=update.entity_id,
                extracted_state=update.state,
                chapter_id=chapter_id,
                diff_summary=update.diff_summary,
                persist_stats=persist_stats,
            )
            if entity_obj and entity_obj.name:
                name_to_id[entity_obj.name] = resolved
            if update.entity_id:
                name_to_id[update.entity_id] = resolved
            persist_stats["updated"]["entities"] += 1

        for fs_id in extraction.foreshadowings_recovered:
            await foreshadowing_repo.mark_recovered(fs_id, chapter_id=chapter_id)
            persist_stats["updated"]["foreshadowings_recovered"] += 1

        for fs in extraction.new_foreshadowings:
            fs_id = str(uuid.uuid4())
            await foreshadowing_repo.create(
                fs_id=fs_id,
                content=fs.content,
                埋下_chapter_id=fs.埋下_chapter_id or chapter_id,
                埋下_time_tick=fs.埋下_time_tick,
                埋下_location_id=fs.埋下_location_id,
                回收条件=fs.回收条件,
                novel_id=novel_id,
            )
            persist_stats["created"]["foreshadowings"] += 1

        for rel in extraction.new_relationships:
            source_id = await self._resolve_entity_id(rel.source_entity_id, novel_id, name_to_id, entity_repo)
            target_id = await self._resolve_entity_id(rel.target_entity_id, novel_id, name_to_id, entity_repo)
            if not source_id or not target_id:
                reason = {
                    "type": "relationship",
                    "source_entity_id": rel.source_entity_id,
                    "target_entity_id": rel.target_entity_id,
                    "relation_type": rel.relation_type,
                    "reason": "entity_not_found",
                }
                persist_stats["skipped"].append(reason)
                log_agent_detail(
                    novel_id,
                    "LibrarianAgent",
                    f"关系跳过：实体未找到 {rel.source_entity_id} -> {rel.target_entity_id}",
                    node="librarian_persist_skip",
                    task="persist",
                    status="failed",
                    level="warning",
                    metadata=reason,
                )
                continue
            await relationship_repo.upsert(
                source_id=source_id,
                target_id=target_id,
                relation_type=rel.relation_type,
                meta=rel.meta,
                chapter_id=chapter_id,
                novel_id=novel_id,
                replace_existing_pair=True,
            )
            persist_stats["created"]["relationships"] += 1
        log_agent_detail(
            novel_id,
            "LibrarianAgent",
            "持久化完成",
            node="librarian_persist_result",
            task="persist",
            metadata=persist_stats,
        )

    async def _apply_entity_state_policy(
        self,
        *,
        entity_svc: EntityService,
        entity_repo: EntityRepository,
        entity_id: str,
        entity_ref: str,
        extracted_state: dict,
        chapter_id: str,
        diff_summary: Optional[dict],
        persist_stats: dict,
    ):
        entity_obj = await entity_repo.get_by_id(entity_id)
        latest_version = await entity_svc.version_repo.get_latest(entity_id)
        policy_result = EntityStatePolicy.normalize_update(
            entity_type=entity_obj.type if entity_obj else "",
            entity_name=entity_obj.name if entity_obj else entity_ref,
            latest_state=latest_version.state if latest_version else None,
            extracted_state=extracted_state,
            chapter_id=chapter_id,
            diff_summary=diff_summary,
        )
        self._record_policy_events(
            persist_stats,
            policy_result.events,
            entity_id=entity_id,
            entity_ref=entity_ref,
        )
        await entity_svc.update_state(
            entity_id,
            policy_result.state,
            chapter_id=chapter_id,
            diff_summary=diff_summary,
        )
        return entity_obj

    def _record_policy_events(
        self,
        persist_stats: dict,
        events: list[dict],
        *,
        entity_id: str,
        entity_ref: str,
    ) -> None:
        if not events:
            return
        persist_stats["policy_event_count"] += len(events)
        remaining = _POLICY_EVENT_LOG_LIMIT - len(persist_stats["policy_events"])
        if remaining <= 0:
            return
        persist_stats["policy_events"].extend(
            self._preview_policy_event(
                {
                    **event,
                    "entity_id": entity_id,
                    "entity_ref": entity_ref,
                }
            )
            for event in events[:remaining]
        )

    def _preview_policy_event(self, event: dict) -> dict:
        return {key: self._preview_policy_value(value) for key, value in event.items()}

    def _preview_policy_value(self, value):
        if isinstance(value, str):
            return preview_text(value)
        if isinstance(value, dict):
            return {key: self._preview_policy_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._preview_policy_value(item) for item in value[:_POLICY_EVENT_LOG_LIMIT]]
        return value

    async def _find_existing_new_entity(
        self,
        name: str,
        entity_type: str,
        novel_id: str,
        entity_repo: EntityRepository,
    ) -> tuple[object | None, bool]:
        candidates = [
            entity for entity in await entity_repo.list_by_novel(novel_id)
            if entity.type == entity_type
        ]

        exact_matches = [entity for entity in candidates if entity.name == name]
        if len(exact_matches) > 1:
            return None, True
        if len(exact_matches) == 1:
            return exact_matches[0], False

        normalized = EntityRepository.normalize_name(name)
        if not normalized:
            return None, False

        normalized_matches = [
            entity for entity in candidates
            if EntityRepository.normalize_name(entity.name) == normalized
        ]
        if len(normalized_matches) > 1:
            return None, True
        if len(normalized_matches) == 1:
            return normalized_matches[0], False

        close_matches = [
            entity for entity in candidates
            if EntityRepository._is_close_name_match(
                EntityRepository.normalize_name(entity.name),
                normalized,
            )
        ]
        if len(close_matches) > 1:
            return None, True
        if len(close_matches) == 1:
            return close_matches[0], False
        return None, False

    async def _resolve_entity_id(
        self,
        raw_ref: str,
        novel_id: str,
        name_to_id: dict[str, str],
        entity_repo: EntityRepository,
    ) -> Optional[str]:
        if not raw_ref:
            return None
        if raw_ref in name_to_id:
            return name_to_id[raw_ref]

        entity = await entity_repo.get_by_id(raw_ref)
        if entity and entity.novel_id == novel_id:
            name_to_id[raw_ref] = entity.id
            name_to_id[entity.name] = entity.id
            return entity.id

        entity = await entity_repo.find_by_name(raw_ref, novel_id=novel_id)
        if entity is None:
            return None
        name_to_id[raw_ref] = entity.id
        name_to_id[entity.name] = entity.id
        return entity.id

    async def _normalize_spaceline_parent_id(
        self,
        location_id: str,
        parent_id: Optional[str],
        novel_id: str,
        spaceline_repo: SpacelineRepository,
        persist_stats: dict,
    ) -> Optional[str]:
        if not parent_id:
            return None

        if parent_id == location_id:
            reason = {
                "type": "spaceline_parent",
                "location_id": location_id,
                "parent_id": parent_id,
                "reason": "self_parent",
                "normalized_to": None,
            }
            persist_stats["normalized"]["spaceline_parent_ids"].append(reason)
            log_agent_detail(
                novel_id,
                "LibrarianAgent",
                f"地点父级已清理：{location_id} 不能指向自身",
                node="librarian_persist_normalize",
                task="persist",
                status="succeeded",
                level="warning",
                metadata=reason,
            )
            return None

        parent = await spaceline_repo.get_by_id(parent_id)
        if parent and parent.novel_id in {None, novel_id}:
            return parent_id

        reason = {
            "type": "spaceline_parent",
            "location_id": location_id,
            "parent_id": parent_id,
            "reason": "parent_not_found",
            "normalized_to": None,
        }
        persist_stats["normalized"]["spaceline_parent_ids"].append(reason)
        log_agent_detail(
            novel_id,
            "LibrarianAgent",
            f"地点父级已清理：父地点未找到 {parent_id}",
            node="librarian_persist_normalize",
            task="persist",
            status="succeeded",
            level="warning",
            metadata=reason,
        )
        return None
