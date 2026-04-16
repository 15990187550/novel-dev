from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.context import ChapterContext, ChapterPlan, EntityState, LocationContext
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.version_repo import EntityVersionRepository
from novel_dev.repositories.spaceline_repo import SpacelineRepository
from novel_dev.repositories.timeline_repo import TimelineRepository
from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.agents.director import NovelDirector, Phase


class ContextAgent:
    def __init__(self, session: AsyncSession):
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
        active_entities = await self._load_active_entities(key_entity_names)
        location_context = await self._load_location_context(key_entity_names)
        timeline_events = await self._load_timeline_events(checkpoint)
        pending_foreshadowings = await self._load_foreshadowings(chapter_plan, active_entities, checkpoint)
        style_profile = await self._load_style_profile(novel_id, checkpoint)
        worldview_doc = await self.doc_repo.get_latest_by_type(novel_id, "worldview")
        worldview_summary = worldview_doc.content if worldview_doc else ""
        prev_summary = await self._load_previous_chapter_summary(
            state.current_volume_id, chapter_plan
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

    async def _load_active_entities(self, names: List[str]) -> List[EntityState]:
        if not names:
            return []
        entities = await self.entity_repo.find_by_names(names)
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

    async def _load_location_context(self, names: List[str]) -> LocationContext:
        return LocationContext(current="")

    async def _load_timeline_events(self, checkpoint: dict) -> List[dict]:
        tick = checkpoint.get("current_time_tick")
        if tick is None:
            return []
        events = await self.timeline_repo.get_around_tick(tick, radius=3)
        return [{"tick": e.tick, "narrative": e.narrative} for e in events]

    async def _load_foreshadowings(
        self,
        chapter_plan: ChapterPlan,
        active_entities: List[EntityState],
        checkpoint: dict,
    ) -> List[dict]:
        active_ids = {e.entity_id for e in active_entities}
        all_active = await self.foreshadowing_repo.list_active()
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
            import json
            try:
                return json.loads(doc.content)
            except Exception:
                return {"style_guide": doc.content}
        return {}

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
