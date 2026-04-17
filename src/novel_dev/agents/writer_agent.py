from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.context import ChapterContext, DraftMetadata, BeatPlan
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.llm.models import ChatMessage


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

        checkpoint = dict(state.checkpoint_data or {})
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
        prompt = (
            "你是一位小说创作助手。请根据以下节拍计划和上下文，生成该节拍的正文。"
            "要求：只返回正文内容，不添加解释。\n\n"
            f"### 节拍计划\n{beat.model_dump_json()}\n\n"
            f"### 章节上下文\n{context.model_dump_json()}\n\n"
            f"### 已写文本\n{previous_text}\n\n"
            "请生成正文："
        )
        from novel_dev.llm import llm_factory
        client = llm_factory.get("WriterAgent", task="generate_beat")
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        return response.text.strip()

    async def _rewrite_angle(self, beat: BeatPlan, original_text: str, context: ChapterContext) -> str:
        prompt = (
            "你是一位小说创作助手。当前节拍过短，请扩写并保持与上下文的连贯。"
            "只返回扩写后的正文，不添加解释。\n\n"
            f"### 节拍计划\n{beat.model_dump_json()}\n\n"
            f"### 章节上下文\n{context.model_dump_json()}\n\n"
            f"### 当前过短文本\n{original_text}\n\n"
            "请扩写："
        )
        from novel_dev.llm import llm_factory
        client = llm_factory.get("WriterAgent", task="rewrite_beat")
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        return response.text.strip()
