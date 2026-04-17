import json
import logging
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.agents._llm_helpers import call_and_parse
from novel_dev.schemas.context import ChapterContext, ChapterPlan, EntityState, LocationContext
from novel_dev.schemas.similar_document import SimilarDocument
from novel_dev.services.embedding_service import EmbeddingService
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.version_repo import EntityVersionRepository
from novel_dev.repositories.spaceline_repo import SpacelineRepository
from novel_dev.repositories.timeline_repo import TimelineRepository
from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.agents.director import NovelDirector, Phase

logger = logging.getLogger(__name__)


class ContextAgent:
    def __init__(self, session: AsyncSession, embedding_service: EmbeddingService | None = None):
        self.session = session
        self.state_repo = NovelStateRepository(session)
        self.doc_repo = DocumentRepository(session)
        self.entity_repo = EntityRepository(session)
        self.version_repo = EntityVersionRepository(session)
        self.spaceline_repo = SpacelineRepository(session)
        self.timeline_repo = TimelineRepository(session)
        self.foreshadowing_repo = ForeshadowingRepository(session)
        self.chapter_repo = ChapterRepository(session)
        self.director = NovelDirector(session)
        self.embedding_service = embedding_service

    async def assemble(self, novel_id: str, chapter_id: str) -> ChapterContext:
        state = await self.state_repo.get_state(novel_id)
        if not state:
            raise ValueError(f"Novel state not found for {novel_id}")

        if not self.director.can_transition(Phase(state.current_phase), Phase.DRAFTING):
            raise ValueError(f"Cannot prepare context from phase {state.current_phase}")

        checkpoint = dict(state.checkpoint_data or {})
        chapter_plan_data = checkpoint.get("current_chapter_plan")
        if not chapter_plan_data:
            raise ValueError("current_chapter_plan missing in checkpoint_data")

        chapter_plan = ChapterPlan.model_validate(chapter_plan_data)

        key_entity_names = self._extract_key_entities_from_plan(chapter_plan)
        active_entities = await self._load_active_entities(key_entity_names, novel_id)
        location_context = await self._load_location_context(chapter_plan, novel_id)
        timeline_events = await self._load_timeline_events(checkpoint, novel_id)
        pending_foreshadowings = await self._load_foreshadowings(chapter_plan, active_entities, checkpoint, novel_id)
        style_profile = await self._load_style_profile(novel_id, checkpoint)
        worldview_doc = await self.doc_repo.get_latest_by_type(novel_id, "worldview")
        worldview_summary = worldview_doc.content if worldview_doc else ""
        prev_summary = await self._load_previous_chapter_summary(
            state.current_volume_id, chapter_plan
        )

        # Semantic search augmentation
        relevant_docs: list[SimilarDocument] = []
        if self.embedding_service:
            query_text = self._build_search_query(chapter_plan)
            try:
                results = await self.embedding_service.search_similar(
                    novel_id=novel_id, query_text=query_text, limit=3)
                exclude_id = worldview_doc.id if worldview_doc else None
                relevant_docs = [r for r in results if r.doc_id != exclude_id]
            except Exception as exc:
                logger.warning("semantic_search_failed", extra={"novel_id": novel_id, "error": str(exc)})

        context = ChapterContext(
            chapter_plan=chapter_plan,
            style_profile=style_profile,
            worldview_summary=worldview_summary,
            active_entities=active_entities,
            location_context=location_context,
            timeline_events=timeline_events,
            pending_foreshadowings=pending_foreshadowings,
            previous_chapter_summary=prev_summary,
            relevant_documents=relevant_docs,
        )

        checkpoint["chapter_context"] = context.model_dump()
        checkpoint["drafting_progress"] = {
            "beat_index": 0,
            "total_beats": len(chapter_plan.beats),
            "current_word_count": 0,
        }
        await self.director.save_checkpoint(
            novel_id,
            phase=Phase.DRAFTING,
            checkpoint_data=checkpoint,
            volume_id=state.current_volume_id,
            chapter_id=state.current_chapter_id,
        )

        return context

    def _extract_key_entities_from_plan(self, chapter_plan: ChapterPlan) -> List[str]:
        names = set()
        for beat in chapter_plan.beats:
            names.update(beat.key_entities)
        return list(names)

    async def _load_active_entities(self, names: List[str], novel_id: str) -> List[EntityState]:
        if not names:
            return []
        entities = await self.entity_repo.find_by_names(names, novel_id=novel_id)
        result = []
        for entity in entities:
            latest = await self.version_repo.get_latest(entity.id)
            state_str = str(latest.state) if latest else ""
            result.append(
                EntityState(
                    entity_id=entity.id,
                    name=entity.name,
                    type=entity.type,
                    current_state=state_str,
                )
            )
        return result

    async def _analyze_context_needs(self, chapter_plan: ChapterPlan, novel_id: str) -> dict:
        prompt = (
            "你是一位小说场景分析师。请根据以下章节计划，分析写这一章需要哪些上下文信息。\n"
            "返回严格 JSON：\n"
            "{\n"
            '  "locations": ["地点名1"],\n'
            '  "entities": ["实体名1"],\n'
            '  "time_range": {"start_tick": -3, "end_tick": 2},\n'
            '  "foreshadowing_keywords": ["关键词1"]\n'
            "}\n\n"
            "说明：\n"
            "- locations: 场景涉及的主要地点\n"
            "- entities: 需要知道最新状态的关键人物/物品（超出章节计划已有实体）\n"
            "- time_range: 相对于 current_tick 的时间范围\n"
            "- foreshadowing_keywords: 用于筛选相关伏笔的关键词\n\n"
            f"章节计划：\n{chapter_plan.model_dump_json()}"
        )
        return await call_and_parse(
            "ContextAgent", "analyze_context_needs", prompt,
            json.loads, max_retries=3
        )

    async def _load_location_context(
        self, chapter_plan: ChapterPlan, novel_id: str
    ) -> LocationContext:
        needs = await self._analyze_context_needs(chapter_plan, novel_id)

        location_names = needs.get("locations", [])
        locations = []
        if location_names:
            all_locs = await self.spaceline_repo.list_by_novel(novel_id)
            locations = [loc for loc in all_locs if loc.name in location_names]

        entity_names = list(set(
            needs.get("entities", []) + self._extract_key_entities_from_plan(chapter_plan)
        ))
        entity_states = []
        if entity_names:
            entities = await self.entity_repo.find_by_names(entity_names, novel_id=novel_id)
            for entity in entities:
                latest = await self.version_repo.get_latest(entity.id)
                entity_states.append({
                    "name": entity.name,
                    "type": entity.type,
                    "state": str(latest.state) if latest else "",
                })

        state = await self.state_repo.get_state(novel_id)
        current_tick = state.checkpoint_data.get("current_time_tick") if state else None
        timeline_events = []
        if current_tick is not None:
            time_range = needs.get("time_range", {})
            start = current_tick + time_range.get("start_tick", -2)
            end = current_tick + time_range.get("end_tick", 2)
            events = await self.timeline_repo.list_between(start, end, novel_id)
            timeline_events = [{"tick": e.tick, "narrative": e.narrative} for e in events]

        keywords = needs.get("foreshadowing_keywords", [])
        all_foreshadowings = await self.foreshadowing_repo.list_active(novel_id=novel_id)
        pending_fs = [
            {"id": fs.id, "content": fs.content}
            for fs in all_foreshadowings
            if any(kw in fs.content for kw in keywords) or not keywords
        ]

        prompt = (
            "你是一位导演，正在为下一幕戏撰写场景说明。请根据以下所有信息，"
            "写一段 200-300 字的场景镜头描述。这段文字将被直接交给小说家作为写作参考，"
            "所以请用具体、可感知的细节，不要抽象概括。必须包含：\n"
            "- 空间环境（地点、光线、声音、气味、天气等感官细节）\n"
            "- 时间状态（时辰、季节、时间推移感）\n"
            "- 在场人物（谁在场、他们在做什么、彼此的空间关系）\n"
            "- 物品线索（场景中有什么道具、伏笔物品、环境线索）\n"
            "- 情绪基调（压抑、紧张、欢快等，用氛围描写传达）\n"
            "- 与上一场景的衔接\n"
            "返回严格 JSON 格式：\n"
            "{\n"
            '  "current": "当前主要地点名称",\n'
            '  "parent": "上级地点/区域（如有）",\n'
            '  "narrative": "完整的场景镜头描述（200-300字）"\n'
            "}\n\n"
            f"地点：{[{'name': loc.name, 'narrative': loc.narrative, 'meta': loc.meta} for loc in locations]}\n"
            f"实体状态：{entity_states}\n"
            f"近期时间线：{timeline_events}\n"
            f"待回收伏笔：{pending_fs}\n"
        )
        return await call_and_parse(
            "ContextAgent", "build_scene_context", prompt,
            LocationContext.model_validate_json, max_retries=3
        )

    async def _load_timeline_events(self, checkpoint: dict, novel_id: str) -> List[dict]:
        tick = checkpoint.get("current_time_tick")
        if tick is None:
            return []
        events = await self.timeline_repo.get_around_tick(tick, radius=3, novel_id=novel_id)
        return [{"tick": e.tick, "narrative": e.narrative} for e in events]

    async def _load_foreshadowings(
        self,
        chapter_plan: ChapterPlan,
        active_entities: List[EntityState],
        checkpoint: dict,
        novel_id: str,
    ) -> List[dict]:
        active_ids = {e.entity_id for e in active_entities}
        all_active = await self.foreshadowing_repo.list_active(novel_id=novel_id)
        result = []
        for fs in all_active:
            match = False
            if fs.相关人物_ids and active_ids:
                if any(eid in active_ids for eid in fs.相关人物_ids):
                    match = True
            if fs.埋下_time_tick == checkpoint.get("current_time_tick"):
                match = True
            if match:
                result.append(
                    {
                        "id": fs.id,
                        "content": fs.content,
                        "role_in_chapter": "embed",
                    }
                )
        return result

    async def _load_style_profile(self, novel_id: str, checkpoint: dict) -> dict:
        version = checkpoint.get("active_style_profile_version")
        if version:
            doc = await self.doc_repo.get_by_type_and_version(novel_id, "style_profile", version)
        else:
            doc = await self.doc_repo.get_latest_by_type(novel_id, "style_profile")
        if doc:
            try:
                return json.loads(doc.content)
            except Exception:
                return {"style_guide": doc.content}
        return {}

    def _build_search_query(self, chapter_plan: ChapterPlan) -> str:
        parts = []
        if chapter_plan.title:
            parts.append(chapter_plan.title)
        for beat in chapter_plan.beats[:2]:
            parts.append(beat.summary)
        return "\n".join(parts)[:8000]

    async def _load_previous_chapter_summary(
        self,
        volume_id: Optional[str],
        chapter_plan: ChapterPlan,
    ) -> Optional[str]:
        if not volume_id or chapter_plan.chapter_number <= 1:
            return None
        prev = await self.chapter_repo.get_previous_chapter(volume_id, chapter_plan.chapter_number)
        if not prev:
            return None
        text = prev.polished_text or prev.raw_draft
        if not text:
            return None
        return text[-200:] if len(text) > 200 else text
