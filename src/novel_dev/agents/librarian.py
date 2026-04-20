import json
import logging
import re
import uuid
from typing import Optional
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


from novel_dev.repositories.timeline_repo import TimelineRepository
from novel_dev.repositories.spaceline_repo import SpacelineRepository
from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
from novel_dev.repositories.relationship_repo import RelationshipRepository
from novel_dev.services.entity_service import EntityService
from novel_dev.services.embedding_service import EmbeddingService
from novel_dev.services.log_service import log_service
from novel_dev.agents._llm_helpers import call_and_parse, call_and_parse_model


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

        def parser(text: str) -> dict:
            return _parse_soft_state_json(text)

        try:
            payload = await call_and_parse(
                "LibrarianAgent", "extract_relationships", prompt,
                parser, max_retries=2, novel_id=novel_id
            )
            updates_raw = payload.get("character_updates", []) or []
            rels_raw = payload.get("new_relationships", []) or []
            updates = []
            for u in updates_raw:
                try:
                    updates.append(EntityUpdate(
                        entity_id=u.get("entity_id") or u.get("name", ""),
                        state=u.get("state", {}) or {},
                        diff_summary=u.get("diff_summary", {}) or {"source": "soft_state_pass"},
                    ))
                except Exception as exc:
                    log_service.add_log(novel_id, "LibrarianAgent", f"软状态更新解析失败: {exc}", level="warning")
                    continue
            rels = []
            for r in rels_raw:
                try:
                    rels.append(NewRelationship(
                        source_entity_id=r.get("source_entity_id") or r.get("source", ""),
                        target_entity_id=r.get("target_entity_id") or r.get("target", ""),
                        relation_type=r.get("relation_type") or r.get("type", "unspecified"),
                        meta=r.get("meta") or {},
                    ))
                except Exception as exc:
                    log_service.add_log(novel_id, "LibrarianAgent", f"软状态关系解析失败: {exc}", level="warning")
                    continue
            return updates, rels
        except Exception as exc:
            logger.warning("librarian_soft_state_pass_failed", extra={"error": str(exc)})
            log_service.add_log(novel_id, "LibrarianAgent", f"软状态提取失败: {exc}", level="warning")
            return [], []

    async def extract(self, novel_id: str, chapter_id: str, polished_text: str) -> ExtractionResult:
        log_service.add_log(novel_id, "LibrarianAgent", f"开始提取世界状态: {chapter_id}")
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
        log_service.add_log(
            novel_id, "LibrarianAgent",
            f"提取完成: 时间线 {len(extraction.timeline_events)} 条, 新实体 {len(extraction.new_entities)} 个, "
            f"角色更新 {len(extraction.character_updates)} 条, 回收伏笔 {len(extraction.foreshadowings_recovered)} 条, "
            f"新伏笔 {len(extraction.new_foreshadowings)} 条, 新关系 {len(extraction.new_relationships)} 条"
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

    async def persist(self, extraction: ExtractionResult, chapter_id: str, novel_id: str) -> None:
        log_service.add_log(novel_id, "LibrarianAgent", f"开始持久化提取结果: {chapter_id}")
        timeline_repo = TimelineRepository(self.session)
        spaceline_repo = SpacelineRepository(self.session)
        entity_svc = EntityService(self.session, self.embedding_service)
        foreshadowing_repo = ForeshadowingRepository(self.session)
        relationship_repo = RelationshipRepository(self.session)

        # Track name -> entity_id for relationship resolution
        name_to_id: dict[str, str] = {}

        for event in extraction.timeline_events:
            await timeline_repo.create(event.tick, event.narrative, anchor_chapter_id=chapter_id, anchor_event_id=event.anchor_event_id, novel_id=novel_id)

        for change in extraction.spaceline_changes:
            node = await spaceline_repo.get_by_id(change.location_id)
            if node:
                node.name = change.name
                node.parent_id = change.parent_id
                node.narrative = change.narrative or node.narrative
                await self.session.flush()
            else:
                await spaceline_repo.create(change.location_id, change.name, change.parent_id, change.narrative, novel_id=novel_id)

        for entity in extraction.new_entities:
            eid = str(uuid.uuid4())
            await entity_svc.create_entity(eid, entity.type, entity.name, chapter_id=chapter_id, novel_id=novel_id)
            await entity_svc.update_state(eid, entity.state, chapter_id=chapter_id, diff_summary={"created": True})
            name_to_id[entity.name] = eid

        for update in extraction.concept_updates + extraction.character_updates:
            await entity_svc.update_state(update.entity_id, update.state, chapter_id=chapter_id, diff_summary=update.diff_summary)
            if update.entity_id:
                name_to_id[update.entity_id] = update.entity_id

        for fs_id in extraction.foreshadowings_recovered:
            await foreshadowing_repo.mark_recovered(fs_id, chapter_id=chapter_id)

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

        for rel in extraction.new_relationships:
            source_id = name_to_id.get(rel.source_entity_id, rel.source_entity_id)
            target_id = name_to_id.get(rel.target_entity_id, rel.target_entity_id)
            await relationship_repo.create(
                source_id=source_id,
                target_id=target_id,
                relation_type=rel.relation_type,
                meta=rel.meta,
                chapter_id=chapter_id,
                novel_id=novel_id,
            )
        log_service.add_log(novel_id, "LibrarianAgent", "持久化完成")
