import json

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.review import FastReviewReport
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.llm.models import ChatMessage

FAST_REVIEW_PASS_SCORE = 100
FAST_REVIEW_FAIL_SCORE = 50


class FastReviewAgent:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.state_repo = NovelStateRepository(session)
        self.chapter_repo = ChapterRepository(session)
        self.director = NovelDirector(session)

    async def _llm_check_consistency_and_cohesion(
        self, polished: str, raw: str, chapter_context: dict
    ) -> dict:
        prompt = (
            "你是一位小说质量检查员。请根据以下精修文本、原始草稿和章节上下文，"
            "检查两点并返回严格 JSON：\n"
            "1. consistency_fixed: 精修文本是否修复了与设定/上下文的不一致\n"
            "2. beat_cohesion_ok: 节拍之间是否连贯\n"
            '3. notes: 问题列表（字符串数组）\n\n'
            f"### 章节上下文\n{json.dumps(chapter_context, ensure_ascii=False)}\n\n"
            f"### 原始草稿\n{raw}\n\n"
            f"### 精修文本\n{polished}\n\n"
            "请返回 JSON："
        )
        from novel_dev.llm import llm_factory
        client = llm_factory.get("FastReviewAgent", task="fast_review_check")
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        return json.loads(response.text)

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
        ai_flavor_reduced = len(polished) >= len(raw) * 0.5 if raw else len(polished) > 0

        chapter_context = checkpoint.get("chapter_context", {})
        llm_result = await self._llm_check_consistency_and_cohesion(polished, raw, chapter_context)
        consistency_fixed = llm_result.get("consistency_fixed", True)
        beat_cohesion_ok = llm_result.get("beat_cohesion_ok", True)
        notes = llm_result.get("notes", [])

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
