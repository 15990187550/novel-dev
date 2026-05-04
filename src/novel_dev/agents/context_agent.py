import json
import logging
from typing import List, Optional
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.agents._llm_helpers import call_and_parse_model, orchestrated_call_and_parse_model
from novel_dev.llm import llm_factory
from novel_dev.llm.context_tools import build_mcp_context_tools
from novel_dev.llm.orchestrator import LLMToolSpec, OrchestratedTaskConfig
from novel_dev.schemas.context import ChapterContext, ChapterPlan, EntityState, LocationContext, ForeshadowingContext, BeatContext
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
from novel_dev.agents._log_helpers import log_agent_detail, preview_text
from novel_dev.services.log_service import logged_agent_step, log_service

logger = logging.getLogger(__name__)


class ContextNeeds(BaseModel):
    locations: List[str] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)
    time_range: dict = Field(default_factory=dict)
    foreshadowing_keywords: List[str] = Field(default_factory=list)


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

    @logged_agent_step("ContextAgent", "组装章节上下文", node="context", task="assemble")
    async def assemble(self, novel_id: str, chapter_id: str) -> ChapterContext:
        log_service.add_log(novel_id, "ContextAgent", f"开始组装章节上下文: {chapter_id}")
        state = await self.state_repo.get_state(novel_id)
        if not state:
            log_service.add_log(novel_id, "ContextAgent", "小说状态未找到", level="error")
            raise ValueError(f"Novel state not found for {novel_id}")

        if not self.director.can_transition(Phase(state.current_phase), Phase.DRAFTING):
            raise ValueError(f"Cannot prepare context from phase {state.current_phase}")

        checkpoint = dict(state.checkpoint_data or {})
        chapter_plan_data = checkpoint.get("current_chapter_plan")
        if not chapter_plan_data:
            raise ValueError("current_chapter_plan missing in checkpoint_data")

        chapter_plan = ChapterPlan.model_validate(chapter_plan_data)
        context = await self.assemble_for_chapter(
            novel_id,
            chapter_id,
            chapter_plan,
            volume_id=state.current_volume_id,
            checkpoint=checkpoint,
        )
        checkpoint["chapter_context"] = context.model_dump()
        checkpoint["drafting_progress"] = {
            "beat_index": 0,
            "total_beats": len(chapter_plan.beats),
            "current_word_count": 0,
        }
        checkpoint["context_debug_snapshot"] = getattr(context, "_context_debug_snapshot", None)
        if checkpoint["context_debug_snapshot"] is None:
            checkpoint.pop("context_debug_snapshot", None)
        log_service.add_log(novel_id, "ContextAgent", "章节上下文组装完成，进入 drafting 阶段")
        await self.director.save_checkpoint(
            novel_id,
            phase=Phase.DRAFTING,
            checkpoint_data=checkpoint,
            volume_id=state.current_volume_id,
            chapter_id=state.current_chapter_id,
        )

        return context

    async def assemble_for_chapter(
        self,
        novel_id: str,
        chapter_id: str,
        chapter_plan: ChapterPlan,
        *,
        volume_id: str | None,
        checkpoint: dict | None = None,
    ) -> ChapterContext:
        checkpoint = dict(checkpoint or {})
        log_agent_detail(
            novel_id,
            "ContextAgent",
            f"章节计划已读取：{chapter_plan.title}，{len(chapter_plan.beats)} 个节拍",
            node="context_chapter_plan",
            task="assemble",
            status="started",
            metadata={
                "chapter_id": chapter_id,
                "volume_id": volume_id,
                "chapter_number": chapter_plan.chapter_number,
                "title": chapter_plan.title,
                "target_word_count": chapter_plan.target_word_count,
                "beats": [
                    {
                        "index": idx,
                        "summary_preview": preview_text(beat.summary),
                        "target_mood": beat.target_mood,
                        "key_entities": beat.key_entities,
                        "foreshadowings_to_embed": beat.foreshadowings_to_embed,
                    }
                    for idx, beat in enumerate(chapter_plan.beats)
                ],
            },
        )

        key_entity_names = self._extract_key_entities_from_plan(chapter_plan)
        active_entities = await self._load_active_entities(key_entity_names, novel_id)
        log_service.add_log(
            novel_id,
            "ContextAgent",
            f"加载 {len(active_entities)} 个活跃实体: {self._join_names([e.name for e in active_entities])}",
            event="agent.progress",
            status="succeeded",
            node="context_active_entities",
            task="assemble",
            metadata={
                "planned_entity_names": key_entity_names,
                "active_entities": [self._entity_log_item(e) for e in active_entities],
            },
        )

        query_text = self._build_search_query(chapter_plan)
        log_service.add_log(
            novel_id,
            "ContextAgent",
            f"章节上下文检索 query: {query_text[:120]}",
            event="agent.progress",
            status="started",
            node="context_retrieval",
            task="assemble",
            metadata={"query": query_text, "entity_limit": 3, "document_limit": 3, "chapter_limit": 2},
        )

        # Semantic entity retrieval
        related_entities: list[EntityState] = []
        if self.embedding_service:
            try:
                results = await self.embedding_service.search_similar_entities(
                    novel_id=novel_id,
                    query_text=query_text,
                    limit=3,
                )
                active_ids = {e.entity_id for e in active_entities}
                for sim in results:
                    if sim.doc_id not in active_ids:
                        related_entities.append(EntityState(
                            entity_id=sim.doc_id,
                            name=sim.title,
                            type=sim.doc_type,
                            current_state=sim.content_preview,
                        ))
            except Exception as exc:
                logger.warning("entity_semantic_search_failed", extra={"novel_id": novel_id, "error": str(exc)})
                log_service.add_log(novel_id, "ContextAgent", f"实体语义检索失败: {exc}", level="warning")
        if related_entities:
            log_service.add_log(
                novel_id,
                "ContextAgent",
                f"语义实体命中: {self._join_names([e.name for e in related_entities])}",
                event="agent.progress",
                status="succeeded",
                node="context_semantic_entities",
                task="assemble",
                metadata={"query": query_text, "entities": [self._entity_log_item(e) for e in related_entities]},
            )

        location_context = await self._load_location_context(chapter_plan, novel_id)
        log_agent_detail(
            novel_id,
            "ContextAgent",
            f"地点上下文已准备：{location_context.current}",
            node="context_location",
            task="assemble",
            metadata={"location": location_context.model_dump()},
        )
        timeline_events = await self._load_timeline_events(checkpoint, novel_id)
        log_service.add_log(
            novel_id,
            "ContextAgent",
            f"加载 {len(timeline_events)} 条时间线事件: {self._join_names([str(e.get('tick')) for e in timeline_events])}",
            event="agent.progress",
            status="succeeded",
            node="context_timeline",
            task="assemble",
            metadata={"events": timeline_events[:8]},
        )
        pending_foreshadowings = await self._load_foreshadowings(chapter_plan, active_entities, checkpoint, novel_id)
        log_service.add_log(
            novel_id,
            "ContextAgent",
            f"待回收伏笔: {len(pending_foreshadowings)} 条: {self._join_names([fs.content for fs in pending_foreshadowings])}",
            event="agent.progress",
            status="succeeded",
            node="context_foreshadowings",
            task="assemble",
            metadata={"foreshadowings": [self._foreshadowing_log_item(fs) for fs in pending_foreshadowings]},
        )
        style_profile = await self._load_style_profile(novel_id, checkpoint)
        worldview_doc = await self.doc_repo.get_latest_by_type(novel_id, "worldview")
        worldview_summary = (worldview_doc.content or "")[:2000] if worldview_doc else ""
        if worldview_doc:
            log_service.add_log(
                novel_id,
                "ContextAgent",
                f"加载世界观文档: {worldview_doc.title} v{worldview_doc.version}",
                event="agent.progress",
                status="succeeded",
                node="context_worldview",
                task="assemble",
                metadata={"document": self._document_row_log_item(worldview_doc)},
            )
        prev_summary = await self._load_previous_chapter_summary(
            volume_id, chapter_plan
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
                log_service.add_log(novel_id, "ContextAgent", f"语义检索失败: {exc}", level="warning")
        if relevant_docs:
            log_service.add_log(
                novel_id,
                "ContextAgent",
                f"语义文档命中: {self._join_names([doc.title for doc in relevant_docs])}",
                event="agent.progress",
                status="succeeded",
                node="context_documents",
                task="assemble",
                metadata={"query": query_text, "documents": [self._similar_doc_log_item(doc) for doc in relevant_docs]},
            )

        # Semantic chapter retrieval for style consistency
        similar_chapters: list[SimilarDocument] = []
        if self.embedding_service:
            query_text = self._build_search_query(chapter_plan)
            try:
                results = await self.embedding_service.search_similar_chapters(
                    novel_id=novel_id,
                    query_text=query_text,
                    limit=2,
                )
                similar_chapters = results
            except Exception as exc:
                logger.warning("chapter_semantic_search_failed", extra={"novel_id": novel_id, "error": str(exc)})
                log_service.add_log(novel_id, "ContextAgent", f"章节语义检索失败: {exc}", level="warning")
        if similar_chapters:
            log_service.add_log(
                novel_id,
                "ContextAgent",
                f"相似章节命中: {self._join_names([doc.title for doc in similar_chapters])}",
                event="agent.progress",
                status="succeeded",
                node="context_similar_chapters",
                task="assemble",
                metadata={"query": query_text, "chapters": [self._similar_doc_log_item(doc) for doc in similar_chapters]},
            )

        guardrails = self._build_guardrails(chapter_plan, active_entities, location_context, checkpoint)

        beat_contexts = self._build_beat_contexts(
            chapter_plan,
            active_entities,
            related_entities,
            pending_foreshadowings,
            relevant_docs,
            guardrails,
        )

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
            related_entities=related_entities,
            similar_chapters=similar_chapters,
            guardrails=guardrails,
            beat_contexts=beat_contexts,
        )
        context_source_metadata = {
            "query": query_text,
            "active_entities": [self._entity_log_item(e) for e in active_entities],
            "semantic_entities": [self._entity_log_item(e) for e in related_entities],
            "documents": [self._similar_doc_log_item(doc) for doc in relevant_docs],
            "similar_chapters": [self._similar_doc_log_item(doc) for doc in similar_chapters],
            "foreshadowings": [self._foreshadowing_log_item(fs) for fs in pending_foreshadowings],
            "timeline_events": timeline_events[:8],
            "location": location_context.model_dump(),
            "worldview": self._document_row_log_item(worldview_doc) if worldview_doc else None,
            "has_style_profile": bool(style_profile),
            "has_previous_chapter_summary": bool(prev_summary),
            "guardrails": guardrails,
            "beat_contexts": [
                {
                    "beat_index": bc.beat_index,
                    "summary_preview": preview_text(bc.beat.summary),
                    "entities": [e.name for e in bc.entities],
                    "documents": [doc.title for doc in bc.relevant_documents],
                    "foreshadowings": [fs.id for fs in bc.foreshadowings],
                    "guardrail_count": len(bc.guardrails),
                }
                for bc in beat_contexts
            ],
        }
        log_service.add_log(
            novel_id,
            "ContextAgent",
            "章节上下文来源已准备："
            f"实体 {len(active_entities) + len(related_entities)} 个，"
            f"文档 {len(relevant_docs)} 个，相似章节 {len(similar_chapters)} 个，"
            f"伏笔 {len(pending_foreshadowings)} 条",
            event="agent.progress",
            status="succeeded",
            node="context_sources",
            task="assemble",
            metadata=context_source_metadata,
        )

        context_debug_snapshot = self._build_context_debug_snapshot(
            chapter_plan,
            query_text,
            active_entities,
            related_entities,
            relevant_docs,
            similar_chapters,
            pending_foreshadowings,
            beat_contexts,
            guardrails,
            location_context,
            timeline_events,
        )
        object.__setattr__(context, "_context_debug_snapshot", context_debug_snapshot)

        return context

    def _build_context_debug_snapshot(
        self,
        chapter_plan: ChapterPlan,
        query_text: str,
        active_entities: List[EntityState],
        related_entities: List[EntityState],
        relevant_docs: List[SimilarDocument],
        similar_chapters: List[SimilarDocument],
        pending_foreshadowings: List[ForeshadowingContext],
        beat_contexts: List[BeatContext],
        guardrails: List[str],
        location_context: LocationContext,
        timeline_events: List[dict],
    ) -> dict:
        return {
            "chapter": {
                "chapter_number": chapter_plan.chapter_number,
                "title": chapter_plan.title,
                "target_word_count": chapter_plan.target_word_count,
                "beat_count": len(chapter_plan.beats),
            },
            "retrieval_query": query_text,
            "selected_entities": [
                {"id": e.entity_id, "name": e.name, "type": e.type, "source": "active"}
                for e in active_entities
            ] + [
                {"id": e.entity_id, "name": e.name, "type": e.type, "source": "semantic"}
                for e in related_entities
            ],
            "selected_documents": [
                {
                    "id": doc.doc_id,
                    "type": doc.doc_type,
                    "title": doc.title,
                    "score": doc.similarity_score,
                }
                for doc in relevant_docs
            ],
            "similar_chapters": [
                {
                    "id": doc.doc_id,
                    "title": doc.title,
                    "score": doc.similarity_score,
                }
                for doc in similar_chapters
            ],
            "selected_foreshadowings": [fs.model_dump() for fs in pending_foreshadowings],
            "guardrails": guardrails,
            "location": location_context.model_dump(),
            "timeline_events": timeline_events,
            "beat_contexts": [
                {
                    "beat_index": bc.beat_index,
                    "summary": bc.beat.summary,
                    "entities": [e.name for e in bc.entities],
                    "foreshadowings": [fs.id for fs in bc.foreshadowings],
                    "documents": [doc.title for doc in bc.relevant_documents],
                    "guardrails": bc.guardrails,
                }
                for bc in beat_contexts
            ],
        }

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
            state_str = str(latest.state)[:300] if latest else ""
            state_data = latest.state if latest else {}
            result.append(
                EntityState(
                    entity_id=entity.id,
                    name=entity.name,
                    type=entity.type,
                    current_state=state_str,
                    aliases=state_data.get("aliases", []) if isinstance(state_data, dict) else [],
                )
            )
        return result

    @staticmethod
    def _join_names(values: List[str], limit: int = 6) -> str:
        cleaned = [str(value) for value in values if str(value or "").strip()]
        if not cleaned:
            return "无"
        suffix = f" 等{len(cleaned)}项" if len(cleaned) > limit else ""
        return "、".join(cleaned[:limit]) + suffix

    @staticmethod
    def _entity_log_item(entity: EntityState) -> dict:
        return {
            "id": entity.entity_id,
            "name": entity.name,
            "type": entity.type,
            "preview": (entity.current_state or "")[:120],
        }

    @staticmethod
    def _similar_doc_log_item(doc: SimilarDocument) -> dict:
        return {
            "id": doc.doc_id,
            "type": doc.doc_type,
            "title": doc.title,
            "score": doc.similarity_score,
            "preview": (doc.content_preview or "")[:120],
        }

    @staticmethod
    def _foreshadowing_log_item(fs: ForeshadowingContext) -> dict:
        return {
            "id": fs.id,
            "content": fs.content,
            "role": fs.role_in_chapter,
            "target_beat_index": fs.target_beat_index,
            "related_entity_names": fs.related_entity_names,
        }

    @staticmethod
    def _document_row_log_item(doc) -> dict:
        return {
            "id": doc.id,
            "type": doc.doc_type,
            "title": doc.title,
            "version": doc.version,
        }

    async def _analyze_context_needs(self, chapter_plan: ChapterPlan, novel_id: str = "") -> dict:
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
        result = await call_and_parse_model(
            "ContextAgent", "analyze_context_needs", prompt,
            ContextNeeds, max_retries=3, novel_id=novel_id
        )
        return result.model_dump()

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
        log_service.add_log(
            novel_id,
            "ContextAgent",
            "场景上下文查询: "
            f"地点[{self._join_names(location_names)}], "
            f"实体[{self._join_names(entity_names)}], "
            f"时间线 {len(timeline_events)} 条, 伏笔 {len(pending_fs)} 条",
            event="agent.progress",
            status="succeeded",
            node="context_scene_query",
            task="build_scene_context",
            metadata={
                "needs": needs,
                "matched_locations": [{"id": loc.id, "name": loc.name} for loc in locations],
                "matched_entities": [{"name": item["name"], "type": item["type"]} for item in entity_states],
                "timeline_events": timeline_events[:8],
                "foreshadowings": pending_fs[:8],
            },
        )

        scene_inputs = {
            "locations": [
                {"name": loc.name, "narrative": loc.narrative, "meta": loc.meta}
                for loc in locations
            ],
            "entity_states": entity_states,
            "timeline_events": timeline_events,
            "foreshadowings": pending_fs,
        }
        orchestration_config = llm_factory.resolve_orchestration_config(
            "context_agent",
            "build_scene_context",
        )
        prompt_scene_inputs = (
            self._build_scene_context_catalog(scene_inputs)
            if orchestration_config is not None
            else scene_inputs
        )

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
            f"场景上下文：{json.dumps(prompt_scene_inputs, ensure_ascii=False)}\n"
        )
        if orchestration_config is not None:
            return await orchestrated_call_and_parse_model(
                "ContextAgent",
                "build_scene_context",
                prompt,
                LocationContext,
                tools=self._build_scene_context_tools(
                    novel_id=novel_id,
                    scene_inputs=scene_inputs,
                    orchestration_config=orchestration_config,
                ),
                task_config=orchestration_config,
                novel_id=novel_id,
                max_retries=3,
            )
        return await call_and_parse_model(
            "ContextAgent", "build_scene_context", prompt,
            LocationContext, max_retries=3, novel_id=novel_id
        )

    def _build_scene_context_catalog(self, scene_inputs: dict) -> dict:
        return {
            "locations": [
                {"name": item.get("name"), "has_narrative": bool(item.get("narrative"))}
                for item in scene_inputs.get("locations", [])
            ],
            "entities": [
                {"name": item.get("name"), "type": item.get("type"), "has_state": bool(item.get("state"))}
                for item in scene_inputs.get("entity_states", [])
            ],
            "timeline_event_count": len(scene_inputs.get("timeline_events", [])),
            "foreshadowing_ids": [
                item.get("id") for item in scene_inputs.get("foreshadowings", [])
            ],
            "tool_hint": (
                "可按需调用只读工具查询详情。优先用批量工具一次查询同类数据："
                "get_context_location_details / get_context_entity_states / "
                "get_context_foreshadowing_details。需要时间线时再调用 get_context_timeline_events。"
                "最多查询 3 类最缺的细节；目录摘要足够时不要调用工具，不要全量查询。"
            ),
        }

    def _build_scene_context_tools(
        self,
        *,
        novel_id: str,
        scene_inputs: dict,
        orchestration_config: OrchestratedTaskConfig,
    ) -> list[LLMToolSpec]:
        tools: list[LLMToolSpec] = []
        timeout_seconds = orchestration_config.tool_timeout_seconds or 5.0
        max_return_chars = min(orchestration_config.max_tool_result_chars, 1600)
        batch_limit = 5

        def requested_values(args: dict, key: str, fallback_key: str | None = None) -> list[str]:
            raw_values = args.get(key)
            if raw_values is None and fallback_key:
                raw_values = args.get(fallback_key)
            if isinstance(raw_values, str):
                raw_values = [raw_values]
            if not isinstance(raw_values, list):
                raw_values = []
            values = []
            for raw in raw_values:
                value = str(raw or "").strip()
                if value and value not in values:
                    values.append(value)
            return values[:batch_limit]

        def trim_item(item: dict) -> dict:
            item_limit = max(300, min(800, max_return_chars // 2))
            trimmed = {}
            for key, value in item.items():
                if isinstance(value, str) and len(value) > item_limit:
                    trimmed[key] = value[:item_limit] + "...[truncated]"
                else:
                    trimmed[key] = value
            return trimmed

        if "get_context_location_details" in orchestration_config.tool_allowlist:
            async def get_context_location_details(args: dict) -> dict:
                names = requested_values(args, "names", "name")
                items = []
                missing = []
                for name in names:
                    match = next((item for item in scene_inputs.get("locations", []) if item.get("name") == name), None)
                    if match:
                        items.append(trim_item(match))
                    else:
                        missing.append(name)
                return {"items": items, "missing": missing, "requested": names}

            tools.append(LLMToolSpec(
                name="get_context_location_details",
                description="Read up to 5 location details from the current scene context by exact names.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": batch_limit,
                        }
                    },
                    "required": ["names"],
                },
                handler=get_context_location_details,
                read_only=True,
                timeout_seconds=timeout_seconds,
                max_return_chars=max_return_chars,
            ))
        if "get_context_entity_states" in orchestration_config.tool_allowlist:
            async def get_context_entity_states(args: dict) -> dict:
                names = requested_values(args, "names", "name")
                items = []
                missing = []
                for name in names:
                    match = next((item for item in scene_inputs.get("entity_states", []) if item.get("name") == name), None)
                    if match:
                        items.append(trim_item(match))
                    else:
                        missing.append(name)
                return {"items": items, "missing": missing, "requested": names}

            tools.append(LLMToolSpec(
                name="get_context_entity_states",
                description="Read up to 5 active entity states from the current scene context by exact names.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": batch_limit,
                        }
                    },
                    "required": ["names"],
                },
                handler=get_context_entity_states,
                read_only=True,
                timeout_seconds=timeout_seconds,
                max_return_chars=max_return_chars,
            ))
        if "get_context_foreshadowing_details" in orchestration_config.tool_allowlist:
            async def get_context_foreshadowing_details(args: dict) -> dict:
                ids = requested_values(args, "ids", "id")
                items = []
                missing = []
                for fs_id in ids:
                    match = next((item for item in scene_inputs.get("foreshadowings", []) if item.get("id") == fs_id), None)
                    if match:
                        items.append(trim_item(match))
                    else:
                        missing.append(fs_id)
                return {"items": items, "missing": missing, "requested": ids}

            tools.append(LLMToolSpec(
                name="get_context_foreshadowing_details",
                description="Read up to 5 foreshadowing details from the current scene context by ids.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": batch_limit,
                        }
                    },
                    "required": ["ids"],
                },
                handler=get_context_foreshadowing_details,
                read_only=True,
                timeout_seconds=timeout_seconds,
                max_return_chars=max_return_chars,
            ))
        if "get_context_location_detail" in orchestration_config.tool_allowlist:
            async def get_context_location_detail(args: dict) -> dict:
                name = str(args.get("name") or "").strip()
                for item in scene_inputs.get("locations", []):
                    if item.get("name") == name:
                        return item
                return {"error": "location not found", "name": name}

            tools.append(LLMToolSpec(
                name="get_context_location_detail",
                description="Read one location detail from the current scene context by exact name.",
                input_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
                handler=get_context_location_detail,
                read_only=True,
                timeout_seconds=timeout_seconds,
                max_return_chars=max_return_chars,
            ))
        if "get_context_entity_state" in orchestration_config.tool_allowlist:
            async def get_context_entity_state(args: dict) -> dict:
                name = str(args.get("name") or "").strip()
                for item in scene_inputs.get("entity_states", []):
                    if item.get("name") == name:
                        return item
                return {"error": "entity not found", "name": name}

            tools.append(LLMToolSpec(
                name="get_context_entity_state",
                description="Read one active entity state from the current scene context by exact name.",
                input_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
                handler=get_context_entity_state,
                read_only=True,
                timeout_seconds=timeout_seconds,
                max_return_chars=max_return_chars,
            ))
        if "get_context_foreshadowing_detail" in orchestration_config.tool_allowlist:
            async def get_context_foreshadowing_detail(args: dict) -> dict:
                fs_id = str(args.get("id") or "").strip()
                for item in scene_inputs.get("foreshadowings", []):
                    if item.get("id") == fs_id:
                        return item
                return {"error": "foreshadowing not found", "id": fs_id}

            tools.append(LLMToolSpec(
                name="get_context_foreshadowing_detail",
                description="Read one foreshadowing detail from the current scene context by id.",
                input_schema={
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                },
                handler=get_context_foreshadowing_detail,
                read_only=True,
                timeout_seconds=timeout_seconds,
                max_return_chars=max_return_chars,
            ))
        if "get_context_timeline_events" in orchestration_config.tool_allowlist:
            async def get_context_timeline_events(args: dict) -> list[dict]:
                limit = int(args.get("limit") or 6)
                limit = max(1, min(limit, 12))
                return scene_inputs.get("timeline_events", [])[:limit]

            tools.append(LLMToolSpec(
                name="get_context_timeline_events",
                description="Read recent timeline events already selected for the current scene context.",
                input_schema={
                    "type": "object",
                    "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 12}},
                },
                handler=get_context_timeline_events,
                read_only=True,
                timeout_seconds=timeout_seconds,
                max_return_chars=max_return_chars,
            ))

        from novel_dev.mcp_server.server import internal_mcp_registry

        tools.extend(build_mcp_context_tools(
            internal_mcp_registry,
            allowlist=orchestration_config.tool_allowlist,
            max_return_chars=orchestration_config.max_tool_result_chars,
            timeout_seconds=orchestration_config.tool_timeout_seconds or 5.0,
        ))
        return tools

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
    ) -> List[ForeshadowingContext]:
        active_ids = {e.entity_id for e in active_entities}
        entity_name_map = {e.entity_id: e.name for e in active_entities}
        all_active = await self.foreshadowing_repo.list_active(novel_id=novel_id)
        result = []
        planned_foreshadowings = {
            content: idx
            for idx, beat in enumerate(chapter_plan.beats)
            for content in beat.foreshadowings_to_embed
        }
        for fs in all_active:
            target_beat_index = planned_foreshadowings.get(fs.content)
            role = "embed"
            match = target_beat_index is not None
            if fs.相关人物_ids and active_ids:
                if any(eid in active_ids for eid in fs.相关人物_ids):
                    match = True
            if fs.埋下_time_tick == checkpoint.get("current_time_tick"):
                match = True
                role = "remind"
            if match:
                related_names = [
                    entity_name_map[eid]
                    for eid in (fs.相关人物_ids or [])
                    if eid in entity_name_map
                ]
                result.append(
                    ForeshadowingContext(
                        id=fs.id,
                        content=fs.content,
                        role_in_chapter=role,
                        related_entity_names=related_names,
                        target_beat_index=target_beat_index,
                        surface_hint="只自然露出线索，不解释其意义。",
                        payoff_requirement=(
                            f"满足回收条件时再明确回收：{json.dumps(fs.回收条件, ensure_ascii=False)}"
                            if fs.回收条件 else None
                        ),
                    )
                )
        return result

    def _build_guardrails(
        self,
        chapter_plan: ChapterPlan,
        active_entities: List[EntityState],
        location_context: LocationContext,
        checkpoint: dict,
    ) -> List[str]:
        guardrails = []
        if location_context.current:
            guardrails.append(f"当前主要场景是「{location_context.current}」，不要无铺垫切换地点。")
        if checkpoint.get("current_time_tick") is not None:
            guardrails.append(f"当前时间 tick 为 {checkpoint['current_time_tick']}，不要跳过章节计划直接推进时间线。")
        for entity in active_entities[:8]:
            if entity.current_state:
                guardrails.append(f"{entity.name} 的当前状态必须延续：{entity.current_state[:180]}")
        for idx, beat in enumerate(chapter_plan.beats):
            for name in beat.key_entities:
                guardrails.append(f"节拍 {idx + 1} 涉及「{name}」时，不要写成未参与当前事件。")
        return guardrails[:12]

    def _build_beat_contexts(
        self,
        chapter_plan: ChapterPlan,
        active_entities: List[EntityState],
        related_entities: List[EntityState],
        pending_foreshadowings: List[ForeshadowingContext],
        relevant_docs: List[SimilarDocument],
        chapter_guardrails: List[str],
    ) -> List[BeatContext]:
        all_entities = active_entities + [
            entity for entity in related_entities
            if entity.entity_id not in {active.entity_id for active in active_entities}
        ]
        beat_contexts = []
        for idx, beat in enumerate(chapter_plan.beats):
            beat_entity_names = set(beat.key_entities)
            beat_entities = [entity for entity in all_entities if entity.name in beat_entity_names]
            beat_foreshadowings = [
                fs for fs in pending_foreshadowings
                if fs.target_beat_index == idx
                or (fs.target_beat_index is None and beat_entity_names & set(fs.related_entity_names))
            ]
            beat_docs = [
                doc for doc in relevant_docs
                if any(name and name in doc.content_preview for name in beat.key_entities)
                or any(name and name in doc.title for name in beat.key_entities)
            ]
            beat_guardrails = [
                rule for rule in chapter_guardrails
                if any(name in rule for name in beat.key_entities)
            ]
            if not beat_guardrails:
                beat_guardrails = chapter_guardrails[:3]
            beat_contexts.append(
                BeatContext(
                    beat_index=idx,
                    beat=beat,
                    entities=beat_entities,
                    foreshadowings=beat_foreshadowings,
                    relevant_documents=beat_docs[:3],
                    guardrails=beat_guardrails[:6],
                )
            )
        return beat_contexts

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
        """构建结构化前情摘要:章节标题 + 章首铺垫 + 章末状态。
        纯截尾(原先 text[-200:])会丢失角色目标与情感弧线,导致本章续写断链。
        """
        if not volume_id or chapter_plan.chapter_number <= 1:
            return None
        prev = await self.chapter_repo.get_previous_chapter(volume_id, chapter_plan.chapter_number)
        if not prev:
            return None
        text = prev.polished_text or prev.raw_draft
        if not text:
            return None

        title = getattr(prev, "title", None) or f"第 {chapter_plan.chapter_number - 1} 章"
        clean = text.strip()

        OPENING_LEN = 400
        ENDING_LEN = 800
        if len(clean) <= OPENING_LEN + ENDING_LEN + 40:
            body = clean
        else:
            opening = clean[:OPENING_LEN].rstrip()
            ending = clean[-ENDING_LEN:].lstrip()
            body = f"【章首 ~{OPENING_LEN} 字】\n{opening}\n\n...(中段略)...\n\n【章末 ~{ENDING_LEN} 字】\n{ending}"

        return (
            f"# 上一章「{title}」前情摘要\n"
            f"(供本章承接人物状态、情感基调与悬念,避免重复交代已发生的事)\n\n"
            f"{body}"
        )
