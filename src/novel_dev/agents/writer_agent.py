from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.context import ChapterContext, DraftMetadata, BeatPlan
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.agents.director import NovelDirector, Phase


class WriterAgent:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.chapter_repo = ChapterRepository(session)
        self.state_repo = NovelStateRepository(session)
        self.director = NovelDirector(session)

    async def write(self, novel_id: str, context: ChapterContext, chapter_id: str) -> DraftMetadata:
        state = await self.state_repo.get_state(novel_id)
        if not state:
            raise ValueError(f"Novel state not found for {novel_id}")

        if state.current_phase != Phase.DRAFTING.value:
            raise ValueError(f"Cannot write draft from phase {state.current_phase}")

        checkpoint = state.checkpoint_data or {}
        if not checkpoint.get("chapter_context"):
            raise ValueError("chapter_context missing in checkpoint_data")

        raw_draft = ""
        beat_coverage = []
        embedded_foreshadowings = []
        style_violations = []
        total_beats = len(context.chapter_plan.beats)

        for idx, beat in enumerate(context.chapter_plan.beats):
            beat_text = await self._generate_beat(beat, context, raw_draft)
            if len(beat_text) < 50:
                beat_text = await self._rewrite_angle(beat, beat_text, context)

            raw_draft += beat_text + "\n\n"
            beat_coverage.append({"beat_index": idx, "word_count": len(beat_text)})

            for fs in context.pending_foreshadowings:
                if fs["content"] in beat_text and fs["id"] not in embedded_foreshadowings:
                    embedded_foreshadowings.append(fs["id"])

            checkpoint["drafting_progress"] = {
                "beat_index": idx + 1,
                "total_beats": total_beats,
                "current_word_count": len(raw_draft),
            }
            await self.state_repo.save_checkpoint(
                novel_id,
                current_phase=Phase.DRAFTING.value,
                checkpoint_data=checkpoint,
                current_volume_id=state.current_volume_id,
                current_chapter_id=state.current_chapter_id,
            )

        metadata = DraftMetadata(
            total_words=len(raw_draft),
            beat_coverage=beat_coverage,
            style_violations=style_violations,
            embedded_foreshadowings=embedded_foreshadowings,
        )

        await self.chapter_repo.update_text(chapter_id, raw_draft=raw_draft.strip())
        await self.chapter_repo.update_status(chapter_id, "drafted")

        checkpoint["draft_metadata"] = metadata.model_dump()
        await self.director.save_checkpoint(
            novel_id,
            phase=Phase.REVIEWING,
            checkpoint_data=checkpoint,
            volume_id=state.current_volume_id,
            chapter_id=state.current_chapter_id,
        )

        return metadata

    async def _generate_beat(self, beat: BeatPlan, context: ChapterContext, previous_text: str) -> str:
        text = f"{beat.summary}。气氛{beat.target_mood}。"
        if context.pending_foreshadowings:
            text += context.pending_foreshadowings[0]["content"]
        return text

    async def _rewrite_angle(self, beat: BeatPlan, original_text: str, context: ChapterContext) -> str:
        return original_text + "（重写后）"
