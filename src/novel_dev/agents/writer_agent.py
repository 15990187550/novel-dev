import asyncio
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.context import ChapterContext, DraftMetadata, BeatPlan
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.llm.models import ChatMessage
from novel_dev.services.embedding_service import EmbeddingService


class WriterAgent:
    def __init__(self, session: AsyncSession, embedding_service: Optional[EmbeddingService] = None):
        self.session = session
        self.chapter_repo = ChapterRepository(session)
        self.state_repo = NovelStateRepository(session)
        self.director = NovelDirector(session)
        self.embedding_service = embedding_service

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
        if self.embedding_service:
            try:
                asyncio.create_task(self.embedding_service.index_chapter(chapter_id))
            except Exception:
                pass
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

    def _build_relevant_docs_text(self, context: ChapterContext) -> str:
        if not context.relevant_documents:
            return ""
        docs_block = "\n\n".join(
            f"[{d.doc_type}] {d.title}\n{d.content_preview}"
            for d in context.relevant_documents
        )
        return (
            f"\n\n### 相关设定补充（与本节拍高度相关，写作时请优先参考）\n"
            f"{docs_block}\n"
        )

    def _build_related_entities_text(self, context: ChapterContext) -> str:
        if not context.related_entities:
            return ""
        entities_block = "\n".join(
            f"- [{e.type}] {e.name}：{e.current_state}"
            for e in context.related_entities
        )
        return (
            f"\n\n### 相关角色/势力/地点（请注意设定一致性）\n"
            f"{entities_block}\n"
        )

    def _build_similar_chapters_text(self, context: ChapterContext) -> str:
        if not context.similar_chapters:
            return ""
        chapters_block = "\n\n".join(
            f"[{ch.doc_type}] {ch.title}\n{ch.content_preview}"
            for ch in context.similar_chapters
        )
        return (
            f"\n\n### 参考章节（保持风格一致性）\n"
            f"{chapters_block}\n"
        )

    async def _generate_beat(self, beat: BeatPlan, context: ChapterContext, previous_text: str) -> str:
        prompt = self._build_beat_prompt(beat, context, previous_text)
        from novel_dev.llm import llm_factory
        client = llm_factory.get("WriterAgent", task="generate_beat")
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        return response.text.strip()

    def _build_beat_prompt(self, beat: BeatPlan, context: ChapterContext, previous_text: str) -> str:
        relevant_docs_text = self._build_relevant_docs_text(context)
        related_entities_text = self._build_related_entities_text(context)
        similar_chapters_text = self._build_similar_chapters_text(context)
        return (
            "你是一位小说家。请根据以下节拍计划和上下文，生成该节拍的正文。"
            "要求：只返回正文内容，不添加解释。\n\n"
            f"### 节拍计划\n{beat.model_dump_json()}\n\n"
            f"### 章节上下文\n{context.model_dump_json()}\n\n"
            f"{relevant_docs_text}"
            f"{related_entities_text}"
            f"{similar_chapters_text}"
            f"### 已写文本\n{previous_text}\n\n"
            "请生成正文："
        )

    async def _rewrite_angle(self, beat: BeatPlan, original_text: str, context: ChapterContext) -> str:
        relevant_docs_text = self._build_relevant_docs_text(context)
        related_entities_text = self._build_related_entities_text(context)
        similar_chapters_text = self._build_similar_chapters_text(context)
        prompt = (
            "你是一位小说家。当前节拍过短，请扩写并保持与上下文的连贯。"
            "只返回扩写后的正文，不添加解释。\n\n"
            f"### 节拍计划\n{beat.model_dump_json()}\n\n"
            f"### 章节上下文\n{context.model_dump_json()}\n\n"
            f"{relevant_docs_text}"
            f"{related_entities_text}"
            f"{similar_chapters_text}"
            f"### 当前过短文本\n{original_text}\n\n"
            "请扩写："
        )
        from novel_dev.llm import llm_factory
        client = llm_factory.get("WriterAgent", task="rewrite_beat")
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        return response.text.strip()
