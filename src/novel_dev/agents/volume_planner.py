import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.outline import (
    VolumePlan,
    VolumeBeat,
    VolumeScoreResult,
    SynopsisData,
)
from novel_dev.schemas.context import BeatPlan
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.version_repo import EntityVersionRepository
from novel_dev.repositories.timeline_repo import TimelineRepository
from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
from novel_dev.agents.director import NovelDirector, Phase


class VolumePlannerAgent:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.state_repo = NovelStateRepository(session)
        self.doc_repo = DocumentRepository(session)
        self.chapter_repo = ChapterRepository(session)
        self.entity_repo = EntityRepository(session)
        self.version_repo = EntityVersionRepository(session)
        self.timeline_repo = TimelineRepository(session)
        self.foreshadowing_repo = ForeshadowingRepository(session)
        self.director = NovelDirector(session)

    async def plan(self, novel_id: str, volume_number: Optional[int] = None) -> VolumePlan:
        state = await self.state_repo.get_state(novel_id)
        if not state:
            raise ValueError(f"Novel state not found for {novel_id}")
        if state.current_phase != Phase.VOLUME_PLANNING.value:
            raise ValueError(f"Cannot plan volume from phase {state.current_phase}")

        checkpoint = dict(state.checkpoint_data or {})
        synopsis_data = checkpoint.get("synopsis_data")
        if not synopsis_data:
            raise ValueError("synopsis_data missing in checkpoint_data")

        synopsis = SynopsisData.model_validate(synopsis_data)

        if volume_number is None:
            volume_number = self._infer_volume_number(checkpoint, state)

        volume_plan = self._generate_volume_plan(synopsis, volume_number)

        attempt = checkpoint.get("volume_plan_attempt_count", 0)
        while True:
            score = self._generate_score(volume_plan)
            if score.overall >= 85:
                break
            attempt += 1
            checkpoint["volume_plan_attempt_count"] = attempt
            if attempt >= 3:
                await self.director.save_checkpoint(
                    novel_id,
                    phase=Phase.VOLUME_PLANNING,
                    checkpoint_data=checkpoint,
                    volume_id=state.current_volume_id,
                    chapter_id=state.current_chapter_id,
                )
                raise RuntimeError("Max volume plan attempts exceeded")
            volume_plan = self._revise_volume_plan(volume_plan, score.summary_feedback)

        checkpoint["current_volume_plan"] = volume_plan.model_dump()
        checkpoint["current_chapter_plan"] = self._extract_chapter_plan(volume_plan.chapters[0])
        checkpoint["volume_plan_attempt_count"] = 0

        await self.doc_repo.create(
            doc_id=f"doc_{uuid.uuid4().hex[:8]}",
            novel_id=novel_id,
            doc_type="volume_plan",
            title=f"{volume_plan.title}",
            content=volume_plan.model_dump_json(),
        )

        await self.director.save_checkpoint(
            novel_id,
            phase=Phase.CONTEXT_PREPARATION,
            checkpoint_data=checkpoint,
            volume_id=volume_plan.volume_id,
            chapter_id=volume_plan.chapters[0].chapter_id,
        )

        return volume_plan

    def _infer_volume_number(self, checkpoint: dict, state) -> int:
        if state.current_volume_id and state.current_volume_id.startswith("vol_"):
            try:
                return int(state.current_volume_id.replace("vol_", ""))
            except ValueError:
                pass
        return 1

    def _generate_volume_plan(self, synopsis: SynopsisData, volume_number: int) -> VolumePlan:
        total_chapters = max(1, synopsis.estimated_total_chapters // max(1, synopsis.estimated_volumes))
        chapters_per_volume = total_chapters
        chapters = []
        for i in range(chapters_per_volume):
            chapters.append(
                VolumeBeat(
                    chapter_id=str(uuid.uuid4()),
                    chapter_number=i + 1,
                    title=f"第{i + 1}章",
                    summary=f"第{i + 1}章剧情",
                    target_word_count=3000,
                    target_mood="tense",
                    beats=[
                        BeatPlan(summary=f"节拍 {j}", target_mood="tense")
                        for j in range(1, 4)
                    ],
                )
            )
        return VolumePlan(
            volume_id=f"vol_{volume_number}",
            volume_number=volume_number,
            title=f"第{volume_number}卷",
            summary=f"第{volume_number}卷总述",
            total_chapters=len(chapters),
            estimated_total_words=len(chapters) * 3000,
            chapters=chapters,
        )

    def _generate_score(self, plan: VolumePlan) -> VolumeScoreResult:
        # TODO: replace with LLM-based scoring
        base = 88 if plan.total_chapters > 0 else 50
        return VolumeScoreResult(
            overall=base,
            outline_fidelity=base,
            character_plot_alignment=base,
            hook_distribution=base,
            foreshadowing_management=base,
            chapter_hooks=base,
            page_turning=base,
            summary_feedback="基础评分通过",
        )

    def _revise_volume_plan(self, plan: VolumePlan, feedback: str) -> VolumePlan:
        # TODO: replace with LLM-based revision
        return plan

    def _extract_chapter_plan(self, volume_beat: VolumeBeat) -> dict:
        """Extract chapter plan from VolumeBeat without mutating input."""
        chapter_plan = volume_beat.model_dump()
        beats = [b.model_dump() for b in volume_beat.beats]
        if volume_beat.foreshadowings_to_embed and beats:
            if not beats[0].get("foreshadowings_to_embed"):
                beats[0]["foreshadowings_to_embed"] = list(volume_beat.foreshadowings_to_embed)
        chapter_plan["beats"] = beats
        return chapter_plan
