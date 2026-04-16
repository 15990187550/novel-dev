from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.agents.director import NovelDirector, Phase


class EditorAgent:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.state_repo = NovelStateRepository(session)
        self.chapter_repo = ChapterRepository(session)
        self.director = NovelDirector(session)

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
                polished = self._rewrite_beat(beat_text, scores)
            else:
                polished = beat_text
            polished_beats.append(polished)

        polished_text = "\n\n".join(polished_beats)
        await self.chapter_repo.update_text(chapter_id, polished_text=polished_text)
        await self.chapter_repo.update_status(chapter_id, "edited")

        await self.director.save_checkpoint(
            novel_id,
            phase=Phase.FAST_REVIEWING,
            checkpoint_data=checkpoint,
            volume_id=state.current_volume_id,
            chapter_id=state.current_chapter_id,
        )

    def _rewrite_beat(self, text: str, scores: dict) -> str:
        if scores.get("humanity", 100) < 70:
            return text + "（润色后：增强人味儿）"
        if scores.get("readability", 100) < 70:
            return text + "（润色后：优化读感）"
        return text + "（润色后）"
