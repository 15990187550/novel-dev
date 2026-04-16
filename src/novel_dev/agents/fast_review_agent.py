from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.review import FastReviewReport
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.agents.director import NovelDirector, Phase

FAST_REVIEW_PASS_SCORE = 100
FAST_REVIEW_FAIL_SCORE = 50


class FastReviewAgent:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.state_repo = NovelStateRepository(session)
        self.chapter_repo = ChapterRepository(session)
        self.director = NovelDirector(session)

    async def review(self, novel_id: str, chapter_id: str) -> FastReviewReport:
        state = await self.state_repo.get_state(novel_id)
        if not state:
            raise ValueError(f"Novel state not found for {novel_id}")
        if state.current_phase != Phase.FAST_REVIEWING.value:
            raise ValueError(f"Cannot fast-review from phase {state.current_phase}")

        ch = await self.chapter_repo.get_by_id(chapter_id)
        if not ch:
            raise ValueError(f"Chapter not found: {chapter_id}")

        checkpoint = dict(state.checkpoint_data or {})
        target = checkpoint.get("chapter_context", {}).get("chapter_plan", {}).get("target_word_count", 3000)
        raw = ch.raw_draft or ""
        polished = ch.polished_text or ""

        word_count_ok = abs(len(polished) - target) <= target * 0.1 if target > 0 else True
        # TODO: replace with actual heuristic checks
        consistency_fixed = True
        ai_flavor_reduced = len(polished) >= len(raw) * 0.5 if raw else len(polished) > 0
        # TODO: replace with actual heuristic checks
        beat_cohesion_ok = True
        notes = []

        if not word_count_ok:
            notes.append("字数偏离目标超过10%")

        report = FastReviewReport(
            word_count_ok=word_count_ok,
            consistency_fixed=consistency_fixed,
            ai_flavor_reduced=ai_flavor_reduced,
            beat_cohesion_ok=beat_cohesion_ok,
            notes=notes,
        )

        passed = all([word_count_ok, consistency_fixed, ai_flavor_reduced, beat_cohesion_ok])

        await self.chapter_repo.update_fast_review(
            chapter_id,
            score=FAST_REVIEW_PASS_SCORE if passed else FAST_REVIEW_FAIL_SCORE,
            feedback=report.model_dump(),
        )

        if passed:
            await self.director.save_checkpoint(
                novel_id,
                phase=Phase.LIBRARIAN,
                checkpoint_data=checkpoint,
                volume_id=state.current_volume_id,
                chapter_id=state.current_chapter_id,
            )
        else:
            await self.director.save_checkpoint(
                novel_id,
                phase=Phase.EDITING,
                checkpoint_data=checkpoint,
                volume_id=state.current_volume_id,
                chapter_id=state.current_chapter_id,
            )

        return report
