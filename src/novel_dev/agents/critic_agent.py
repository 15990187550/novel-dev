import json
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.review import ScoreResult, DimensionScore
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.llm.models import ChatMessage


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

        score_result = await self._generate_score(ch.raw_draft or "", context_data)
        beat_scores = await self._generate_beat_scores(context_data)

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

    async def _generate_score(self, raw_draft: str, context_data: dict) -> ScoreResult:
        from novel_dev.llm import llm_factory
        prompt = (
            "你是一位小说评审专家。请根据以下章节草稿和章节上下文，"
            "从 plot_tension、characterization、readability、consistency、humanity "
            "五个维度进行评分（0-100），并给出 overall 和 summary_feedback。"
            "返回严格符合 ScoreResult Schema 的 JSON。\n\n"
            f"### 章节上下文\n{json.dumps(context_data, ensure_ascii=False)}\n\n"
            f"### 草稿\n{raw_draft}\n\n"
            "请评分："
        )
        client = llm_factory.get("CriticAgent", task="score_chapter")
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        return ScoreResult.model_validate_json(response.text)

    async def _generate_beat_scores(self, context_data: dict) -> List[dict]:
        from novel_dev.llm import llm_factory
        beats = context_data.get("chapter_plan", {}).get("beats", [])
        if not beats:
            return []
        prompt = (
            "你是一位小说评审专家。请根据以下节拍列表和章节上下文，"
            "为每个节拍给出 plot_tension 和 humanity 评分。"
            "返回 JSON 数组，每个元素格式为："
            '{"beat_index": 0, "scores": {"plot_tension": 75, "humanity": 75}}'
            f"\n\n章节上下文：\n{json.dumps(context_data, ensure_ascii=False)}"
            "\n\n请评分："
        )
        client = llm_factory.get("CriticAgent", task="score_beats")
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        return json.loads(response.text)
