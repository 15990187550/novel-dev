import math
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
from novel_dev.agents._llm_helpers import call_and_parse


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

        volume_plan = await self._generate_volume_plan(synopsis, volume_number)

        attempt = checkpoint.get("volume_plan_attempt_count", 0)
        while True:
            score = await self._generate_score(volume_plan)
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
            volume_plan = await self._revise_volume_plan(volume_plan, score.summary_feedback)

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

    async def _generate_volume_plan(
        self, synopsis: SynopsisData, volume_number: int
    ) -> VolumePlan:
        MAX_CHARS = 12000
        truncated_synopsis = synopsis.model_dump_json()[:MAX_CHARS]

        prompt = (
            "你是一位小说分卷规划专家。请根据以下大纲数据，"
            "生成一个完整的分卷规划 VolumePlan，返回严格符合 VolumePlan Schema 的 JSON。\n"
            "要求：\n"
            "1. 每章必须有有意义的标题和摘要，不能是'第X章'这种占位符\n"
            "2. 每章拆分为 2-4 个节拍（beats），每个节拍有明确的情节推进\n"
            "3. 章节之间要有连贯性，伏笔要合理分布\n"
            "4. 估算字数要合理\n\n"
            f"大纲数据：\n{truncated_synopsis}\n\n"
            f"当前卷号：{volume_number}"
        )
        return await call_and_parse(
            "VolumePlannerAgent", "generate_volume_plan", prompt,
            VolumePlan.model_validate_json, max_retries=3
        )

    async def _generate_score(self, plan: VolumePlan) -> VolumeScoreResult:
        prompt = (
            "你是一个小说分卷规划评审专家。请根据以下 VolumePlan JSON 进行多维度评分，"
            "返回严格符合 VolumeScoreResult Schema 的 JSON。"
            f"\n\n{plan.model_dump_json()}"
        )
        return await call_and_parse(
            "VolumePlannerAgent", "score_volume_plan", prompt,
            VolumeScoreResult.model_validate_json, max_retries=3
        )

    async def _revise_volume_plan(self, plan: VolumePlan, feedback: str) -> VolumePlan:
        prompt = (
            "你是一个小说分卷规划专家。请根据以下 VolumePlan 和评审反馈进行修正，"
            "返回严格符合 VolumePlan Schema 的 JSON。"
            f"\n\nVolumePlan:\n{plan.model_dump_json()}"
            f"\n\n反馈：{feedback}"
        )
        return await call_and_parse(
            "VolumePlannerAgent", "revise_volume_plan", prompt,
            VolumePlan.model_validate_json, max_retries=3
        )

    def _extract_chapter_plan(self, volume_beat: VolumeBeat) -> dict:
        """Extract chapter plan from VolumeBeat without mutating input."""
        chapter_plan = volume_beat.model_dump()
        beats = [b.model_dump() for b in volume_beat.beats]
        if volume_beat.foreshadowings_to_embed and beats:
            if not beats[0].get("foreshadowings_to_embed"):
                beats[0]["foreshadowings_to_embed"] = list(volume_beat.foreshadowings_to_embed)
        chapter_plan["beats"] = beats
        return chapter_plan
