import asyncio
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.llm.models import ChatMessage
from novel_dev.services.embedding_service import EmbeddingService


class EditorAgent:
    def __init__(self, session: AsyncSession, embedding_service: Optional[EmbeddingService] = None):
        self.session = session
        self.state_repo = NovelStateRepository(session)
        self.chapter_repo = ChapterRepository(session)
        self.director = NovelDirector(session)
        self.embedding_service = embedding_service

    async def polish(self, novel_id: str, chapter_id: str):
        state = await self.state_repo.get_state(novel_id)
        if not state:
            raise ValueError(f"Novel state not found for {novel_id}")
        if state.current_phase != Phase.EDITING.value:
            raise ValueError(f"Cannot edit from phase {state.current_phase}")

        ch = await self.chapter_repo.get_by_id(chapter_id)
        if not ch:
            raise ValueError(f"Chapter not found: {chapter_id}")

        checkpoint = dict(state.checkpoint_data or {})
        beat_scores = checkpoint.get("beat_scores", [])
        raw_draft = ch.raw_draft or ""
        beats = raw_draft.split("\n\n") if raw_draft else []

        polished_beats = []
        for idx, beat_text in enumerate(beats):
            score_entry = beat_scores[idx] if idx < len(beat_scores) else {}
            scores = score_entry.get("scores", {})
            if any(s < 70 for s in scores.values()):
                polished = await self._rewrite_beat(beat_text, scores)
            else:
                polished = beat_text
            polished_beats.append(polished)

        polished_text = "\n\n".join(polished_beats)
        await self.chapter_repo.update_text(chapter_id, polished_text=polished_text)
        if self.embedding_service:
            try:
                asyncio.create_task(self.embedding_service.index_chapter(chapter_id))
            except Exception:
                pass
        await self.chapter_repo.update_status(chapter_id, "edited")

        await self.director.save_checkpoint(
            novel_id,
            phase=Phase.FAST_REVIEWING,
            checkpoint_data=checkpoint,
            volume_id=state.current_volume_id,
            chapter_id=state.current_chapter_id,
        )

    async def _rewrite_beat(self, text: str, scores: dict) -> str:
        low_dims = [k for k, v in scores.items() if v < 70]
        prompt = (
            "你是一位小说编辑。请根据以下低分维度对文本进行润色重写，"
            "只返回重写后的正文，不添加解释。\n\n"
            f"低分维度：{', '.join(low_dims)}\n\n"
            f"原文：\n{text}\n\n"
            "重写："
        )
        from novel_dev.llm import llm_factory
        client = llm_factory.get("EditorAgent", task="polish_beat")
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        return response.text.strip()
