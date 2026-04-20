import json
import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.review import FastReviewReport
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.llm.models import ChatMessage
from novel_dev.services.log_service import log_service

logger = logging.getLogger(__name__)

FAST_REVIEW_PASS_SCORE = 100
FAST_REVIEW_FAIL_SCORE = 50
# Editor ↔ FastReview 最大循环次数,防止极端情况下无限翻译
MAX_EDIT_ATTEMPTS = 2

# 典型 AI 腔中文书面语词汇,Editor 应该减少其密度
AI_FLAVOR_KEYWORDS = (
    "于是", "总之", "综上所述", "综合来看", "总的来说", "这一切", "一切的一切",
    "仿佛", "似乎", "无疑", "显然", "不可否认", "不得不", "不禁",
    "深深地", "静静地", "默默地", "悄悄地", "轻轻地", "缓缓地",
    "然而", "与此同时", "不知不觉", "恍然大悟", "油然而生", "涌上心头",
    "心头一震", "心中暗暗", "万分", "无比地", "令人难以忘怀",
)


def _count_ai_flavor(text: str) -> int:
    if not text:
        return 0
    return sum(text.count(kw) for kw in AI_FLAVOR_KEYWORDS)


def _word_count(text: str) -> int:
    """CJK word count: strip whitespace and count characters."""
    if not text:
        return 0
    return len(text.replace(" ", "").replace("\n", "").replace("\t", "").replace("\r", ""))


_MD_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)
_FIRST_OBJ_RE = re.compile(r"\{[\s\S]*\}")


def _parse_review_json(text: str) -> dict:
    """容错解析:剥 markdown 代码块 + 抓第一个 JSON 对象,失败回退空白对象让调用方用默认值。"""
    if not text:
        return {}
    cleaned = _MD_FENCE_RE.sub("", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    m = _FIRST_OBJ_RE.search(cleaned)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    logger.warning("fast_review_json_parse_failed", extra={"raw_preview": cleaned[:200]})
    return {}


def _check_ai_flavor_reduced(raw: str, polished: str) -> bool:
    """精修后需满足:AI 腔关键词密度下降 + 内容未被过度删减。"""
    if not raw:
        return bool(polished)
    raw_count = _count_ai_flavor(raw)
    polished_count = _count_ai_flavor(polished)
    if raw_count > 0:
        flavor_ok = polished_count <= raw_count * 0.7
    else:
        flavor_ok = polished_count <= max(1, len(polished) // 1000)
    length_ok = _word_count(polished) >= _word_count(raw) * 0.5
    return flavor_ok and length_ok


class FastReviewAgent:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.state_repo = NovelStateRepository(session)
        self.chapter_repo = ChapterRepository(session)
        self.director = NovelDirector(session)

    async def _llm_check_consistency_and_cohesion(
        self, polished: str, raw: str, chapter_context: dict, novel_id: str = ""
    ) -> dict:
        prompt = (
            "你是一位小说质量检查员。请根据以下精修文本、原始草稿和章节上下文,"
            "检查两点并返回严格 JSON:\n"
            "1. consistency_fixed: 精修文本是否修复了与设定/上下文的不一致\n"
            "2. beat_cohesion_ok: 节拍之间是否连贯\n"
            "3. notes: 问题列表(字符串数组)\n"
            "只返回 JSON 对象本体,不要 markdown 代码块。\n\n"
            f"### 章节上下文\n{json.dumps(chapter_context, ensure_ascii=False)}\n\n"
            f"### 原始草稿\n{raw}\n\n"
            f"### 精修文本\n{polished}\n\n"
            "请返回 JSON:"
        )
        from novel_dev.llm import llm_factory
        client = llm_factory.get("FastReviewAgent", task="fast_review_check")
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        result = _parse_review_json(response.text)
        if novel_id:
            log_service.add_log(novel_id, "FastReviewAgent", f"LLM 一致性检查: consistency={result.get('consistency_fixed')}, cohesion={result.get('beat_cohesion_ok')}")
        return result

    async def review(self, novel_id: str, chapter_id: str) -> FastReviewReport:
        log_service.add_log(novel_id, "FastReviewAgent", f"开始快速评审: {chapter_id}")
        state = await self.state_repo.get_state(novel_id)
        if not state:
            log_service.add_log(novel_id, "FastReviewAgent", "小说状态未找到", level="error")
            raise ValueError(f"Novel state not found for {novel_id}")
        if state.current_phase != Phase.FAST_REVIEWING.value:
            log_service.add_log(novel_id, "FastReviewAgent", f"当前阶段 {state.current_phase} 不允许快速评审", level="error")
            raise ValueError(f"Cannot fast-review from phase {state.current_phase}")

        ch = await self.chapter_repo.get_by_id(chapter_id)
        if not ch:
            log_service.add_log(novel_id, "FastReviewAgent", f"章节未找到: {chapter_id}", level="error")
            raise ValueError(f"Chapter not found: {chapter_id}")

        checkpoint = dict(state.checkpoint_data or {})
        target = checkpoint.get("chapter_context", {}).get("chapter_plan", {}).get("target_word_count", 3000)
        raw = ch.raw_draft or ""
        polished = ch.polished_text or ""

        word_count_ok = abs(_word_count(polished) - target) <= target * 0.1 if target > 0 else True
        ai_flavor_reduced = _check_ai_flavor_reduced(raw, polished)

        # Trim context to only what FastReview needs, avoiding retrieval bloat
        chapter_context = checkpoint.get("chapter_context", {})
        trimmed_context = {
            "chapter_plan": chapter_context.get("chapter_plan", {}),
            "style_profile": chapter_context.get("style_profile", {}),
            "worldview_summary": chapter_context.get("worldview_summary", ""),
            "previous_chapter_summary": chapter_context.get("previous_chapter_summary", ""),
            "active_entities": [
                {"name": e.get("name"), "type": e.get("type"), "current_state": e.get("current_state", "")[:200]}
                for e in chapter_context.get("active_entities", [])
            ],
            "pending_foreshadowings": chapter_context.get("pending_foreshadowings", []),
        }
        llm_result = await self._llm_check_consistency_and_cohesion(polished, raw, trimmed_context, novel_id)
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
        log_service.add_log(novel_id, "FastReviewAgent", f"快速评审结果: {'通过' if passed else '未通过'} (字数={word_count_ok}, 一致性={consistency_fixed}, AI腔={ai_flavor_reduced}, 连贯={beat_cohesion_ok})")

        await self.chapter_repo.update_fast_review(
            chapter_id,
            score=FAST_REVIEW_PASS_SCORE if passed else FAST_REVIEW_FAIL_SCORE,
            feedback=report.model_dump(),
        )

        edit_attempts = checkpoint.get("edit_attempt_count", 0)
        if passed or edit_attempts >= MAX_EDIT_ATTEMPTS:
            # 通过或已达编辑上限,都放行进 Librarian,避免死循环阻塞连载
            if not passed:
                report.notes.append(
                    f"edit_attempts={edit_attempts} 已达上限 {MAX_EDIT_ATTEMPTS},跳过精修轮转"
                )
                log_service.add_log(novel_id, "FastReviewAgent", f"未通过但已达编辑上限({edit_attempts}/{MAX_EDIT_ATTEMPTS})，放行进入 librarian")
            else:
                log_service.add_log(novel_id, "FastReviewAgent", "快速评审通过，进入 librarian 阶段")
            checkpoint.pop("edit_attempt_count", None)
            await self.director.save_checkpoint(
                novel_id,
                phase=Phase.LIBRARIAN,
                checkpoint_data=checkpoint,
                volume_id=state.current_volume_id,
                chapter_id=state.current_chapter_id,
            )
        else:
            log_service.add_log(novel_id, "FastReviewAgent", "快速评审未通过，退回 editing 阶段")
            await self.director.save_checkpoint(
                novel_id,
                phase=Phase.EDITING,
                checkpoint_data=checkpoint,
                volume_id=state.current_volume_id,
                chapter_id=state.current_chapter_id,
            )

        return report
