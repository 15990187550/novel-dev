from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.review import ScoreResult, DimensionScore
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.agents.director import NovelDirector, Phase


class CriticAgent:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.state_repo = NovelStateRepository(session)
        self.chapter_repo = ChapterRepository(session)
        self.director = NovelDirector(session)

    async def review(self, novel_id: str, chapter_id: str) -> ScoreResult:
        state = await self.state_repo.get_state(novel_id)
        if not state:
            raise ValueError(f"Novel state not found for {novel_id}")
        if state.current_phase != Phase.REVIEWING.value:
            raise ValueError(f"Cannot review from phase {state.current_phase}")

        ch = await self.chapter_repo.get_by_id(chapter_id)
        if not ch:
            raise ValueError(f"Chapter not found: {chapter_id}")

        checkpoint = dict(state.checkpoint_data or {})
        context_data = checkpoint.get("chapter_context")
        if not context_data:
            raise ValueError("chapter_context missing in checkpoint_data")

        score_result = self._generate_score(ch.raw_draft or "", context_data)
        beat_scores = self._generate_beat_scores(context_data)

        await self.chapter_repo.update_scores(
            chapter_id,
            overall=score_result.overall,
            breakdown={d.name: {"score": d.score, "comment": d.comment} for d in score_result.dimensions},
            feedback={"summary": score_result.summary_feedback},
        )

        checkpoint["beat_scores"] = beat_scores
        checkpoint["critique_feedback"] = {
            "overall": score_result.overall,
            "summary": score_result.summary_feedback,
        }

        overall = score_result.overall
        dimensions = {d.name: d.score for d in score_result.dimensions}

        red_line_failed = dimensions.get("consistency", 100) < 30 or dimensions.get("humanity", 100) < 40

        if overall < 70 or red_line_failed:
            attempt = checkpoint.get("draft_attempt_count", 0) + 1
            if attempt >= 3:
                raise RuntimeError("Max draft attempts exceeded")
            checkpoint["draft_attempt_count"] = attempt
            await self.director.save_checkpoint(
                novel_id,
                phase=Phase.DRAFTING,
                checkpoint_data=checkpoint,
                volume_id=state.current_volume_id,
                chapter_id=state.current_chapter_id,
            )
        else:
            checkpoint.pop("draft_attempt_count", None)
            await self.director.save_checkpoint(
                novel_id,
                phase=Phase.EDITING,
                checkpoint_data=checkpoint,
                volume_id=state.current_volume_id,
                chapter_id=state.current_chapter_id,
            )

        return score_result

    def _generate_score(self, raw_draft: str, context_data: dict) -> ScoreResult:
        target = context_data.get("chapter_plan", {}).get("target_word_count", 3000)
        word_count = len(raw_draft)
        base = 80 if word_count > 50 else 50
        dimensions = [
            DimensionScore(name="plot_tension", score=base, comment="节奏稳定"),
            DimensionScore(name="characterization", score=base, comment="人物行为一致"),
            DimensionScore(name="readability", score=base, comment="可读性良好"),
            DimensionScore(name="consistency", score=base, comment="设定无冲突"),
            DimensionScore(name="humanity", score=base, comment="自然流畅"),
        ]
        weights = {"plot_tension": 1.0, "characterization": 1.0, "readability": 1.0, "consistency": 1.2, "humanity": 1.2}
        total_weight = sum(weights.values())
        overall = int(sum(d.score * weights.get(d.name, 1.0) for d in dimensions) / total_weight)
        return ScoreResult(overall=overall, dimensions=dimensions, summary_feedback="基础评分通过")

    def _generate_beat_scores(self, context_data: dict) -> List[dict]:
        beats = context_data.get("chapter_plan", {}).get("beats", [])
        return [{"beat_index": i, "scores": {"plot_tension": 75, "humanity": 75}} for i in range(len(beats))]
