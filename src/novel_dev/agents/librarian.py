import json
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
)
from novel_dev.repositories.timeline_repo import TimelineRepository
from novel_dev.repositories.spaceline_repo import SpacelineRepository
from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
from novel_dev.repositories.relationship_repo import RelationshipRepository
from novel_dev.services.entity_service import EntityService
from novel_dev.llm import llm_factory
from novel_dev.services.embedding_service import EmbeddingService


class LibrarianAgent:
    def __init__(self, session: AsyncSession, embedding_service: Optional[EmbeddingService] = None):
        self.session = session
        self.embedding_service = embedding_service

    async def _load_context(self, novel_id: str, chapter_id: str) -> dict:
        entity_svc = EntityService(self.session, self.embedding_service)
        foreshadowing_repo = ForeshadowingRepository(self.session)
        spaceline_repo = SpacelineRepository(self.session)
        timeline_repo = TimelineRepository(self.session)

        active_fs = await foreshadowing_repo.list_active()
        current_tick = await timeline_repo.get_current_tick() or 0

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
        response = await client.acomplete(prompt)
        return response.text

    async def extract(self, novel_id: str, chapter_id: str, polished_text: str) -> ExtractionResult:
        context = await self._load_context(novel_id, chapter_id)
        prompt = self._build_prompt(polished_text, context)
        response = await self._call_llm(prompt)
        extraction = ExtractionResult.model_validate_json(response)
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
