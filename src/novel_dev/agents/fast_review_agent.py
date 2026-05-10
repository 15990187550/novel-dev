import json
import logging
import re

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.review import FastReviewReport
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.agents._llm_helpers import call_and_parse_model
from novel_dev.agents._log_helpers import log_agent_detail, preview_text
from novel_dev.services.log_service import logged_agent_step, log_service
from novel_dev.services.quality_gate_service import QUALITY_BLOCK, QualityGateService
from novel_dev.services.continuity_audit_service import ContinuityAuditService

logger = logging.getLogger(__name__)

FAST_REVIEW_PASS_SCORE = 100
FAST_REVIEW_FAIL_SCORE = 50
# Editor ↔ FastReview 最大循环次数,防止极端情况下无限翻译
MAX_EDIT_ATTEMPTS = 2


def _apply_continuity_audit_to_gate(gate, audit):
    if audit.status == QUALITY_BLOCK:
        gate.status = QUALITY_BLOCK
        gate.blocking_items.append({
            "code": "continuity_audit",
            "message": audit.summary or "连续性审计发现硬冲突",
            "detail": audit.blocking_items,
        })
        gate.warning_items.extend(audit.warning_items)
        gate.summary = audit.summary or gate.summary
    elif audit.status == "warn" and gate.status == "pass":
        gate.status = "warn"
        gate.warning_items.extend(audit.warning_items)
        gate.summary = audit.summary or "连续性审计发现可接受告警。"
    return gate

# 典型 AI 腔中文书面语词汇,Editor 应该减少其密度
AI_FLAVOR_KEYWORDS = (
    "于是", "总之", "综上所述", "综合来看", "总的来说", "这一切", "一切的一切",
    "仿佛", "似乎", "无疑", "显然", "不可否认", "不得不", "不禁",
    "深深地", "静静地", "默默地", "悄悄地", "轻轻地", "缓缓地",
    "然而", "与此同时", "不知不觉", "恍然大悟", "油然而生", "涌上心头",
    "心头一震", "心中暗暗", "万分", "无比地", "令人难以忘怀",
)


def _is_acceptance_contract_checkpoint(checkpoint: dict) -> bool:
    return str(checkpoint.get("acceptance_scope") or "") == "real-contract"


class FastReviewLLMCheck(BaseModel):
    consistency_fixed: bool = True
    beat_cohesion_ok: bool = True
    notes: list[str] = Field(default_factory=list)


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
_LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_'-]*")


def _find_language_style_issues(text: str) -> list[str]:
    words = []
    seen = set()
    for match in _LATIN_WORD_RE.finditer(text or ""):
        word = match.group(0)
        key = word.lower()
        if len(set(key)) == 1:
            continue
        if key in seen:
            continue
        seen.add(key)
        words.append(word)
    if not words:
        return []
    preview = "、".join(words[:8])
    suffix = " 等" if len(words) > 8 else ""
    return [f"发现英文/外文词: {preview}{suffix}。正文应改为中文表达，除非章节计划明确要求保留原文。"]


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
    ) -> FastReviewLLMCheck:
        prompt = (
            "你是一位小说质量检查员。请根据以下精修文本、原始草稿和章节上下文,"
            "从读者体验出发检查两点并返回严格 JSON:\n"
            "1. consistency_fixed: 精修文本是否修复了与设定/上下文的不一致\n"
            "2. beat_cohesion_ok: 节拍之间是否连贯\n"
            "3. notes: 问题列表(字符串数组),最多 3 条,每条不超过 60 个汉字。"
            "简短指出最影响读感的问题和正向改写目标；若没有问题返回空数组。"
            "检查读者是否看得懂、是否相信人物、是否愿意继续读。"
            "如果精修文本仍有比喻过密、抽象玄幻词复读、感官平均用力、模板化奇遇/入体演出或现代吐槽突兀,"
            "请写入 notes 并说明下一版应呈现什么效果。\n"
            "只返回 JSON 对象本体,不要 markdown 代码块。\n\n"
            f"### 章节上下文\n{json.dumps(chapter_context, ensure_ascii=False)}\n\n"
            f"### 原始草稿\n{raw}\n\n"
            f"### 精修文本\n{polished}\n\n"
            "请返回 JSON:"
        )
        result = await call_and_parse_model(
            "FastReviewAgent",
            "fast_review_check",
            prompt,
            FastReviewLLMCheck,
            max_retries=2,
            novel_id=novel_id,
        )
        if novel_id:
            log_service.add_log(
                novel_id,
                "FastReviewAgent",
                f"LLM 一致性检查: consistency={result.consistency_fixed}, cohesion={result.beat_cohesion_ok}",
        )
        return result

    async def _safe_llm_check_consistency_and_cohesion(
        self, polished: str, raw: str, chapter_context: dict, novel_id: str = ""
    ) -> FastReviewLLMCheck:
        try:
            return await self._llm_check_consistency_and_cohesion(polished, raw, chapter_context, novel_id)
        except Exception as exc:
            log_agent_detail(
                novel_id,
                "FastReviewAgent",
                "快速评审模型解析失败，退回 editing",
                node="fast_review_llm_fallback",
                task="review",
                status="failed",
                level="warning",
                metadata={"error": f"{type(exc).__name__}: {exc}"},
            )
            return FastReviewLLMCheck(
                consistency_fixed=False,
                beat_cohesion_ok=False,
                notes=["快速评审模型输出解析失败，需退回精修复核"],
            )

    async def _score_final_text(
        self,
        *,
        novel_id: str,
        chapter_id: str,
        polished: str,
        chapter_context: dict,
        fallback_score: int | None,
        fallback_feedback: dict | None,
    ) -> tuple[int | None, dict]:
        if not polished:
            return fallback_score, fallback_feedback or {}
        try:
            from novel_dev.agents.critic_agent import CriticAgent

            score = await CriticAgent(self.session)._generate_score(polished, chapter_context, novel_id)
            feedback = {
                "summary_feedback": score.summary_feedback,
                "breakdown": {
                    dim.name: {"score": dim.score, "comment": dim.comment}
                    for dim in score.dimensions
                },
                "per_dim_issues": [issue.model_dump() for issue in score.per_dim_issues],
            }
            log_agent_detail(
                novel_id,
                "FastReviewAgent",
                f"成稿复评完成：overall={score.overall}",
                node="final_review_score",
                task="review",
                metadata={"chapter_id": chapter_id, "overall": score.overall},
            )
            return score.overall, feedback
        except Exception as exc:
            log_agent_detail(
                novel_id,
                "FastReviewAgent",
                "成稿复评失败，回退到草稿评分",
                node="final_review_score",
                task="review",
                status="failed",
                level="warning",
                metadata={"chapter_id": chapter_id, "error": f"{type(exc).__name__}: {exc}"},
            )
            return fallback_score, fallback_feedback or {}

    @logged_agent_step("FastReviewAgent", "快速评审章节", node="fast_review", task="review")
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
        is_acceptance_contract = _is_acceptance_contract_checkpoint(checkpoint)
        log_agent_detail(
            novel_id,
            "FastReviewAgent",
            "快速评审输入已准备",
            node="fast_review_input",
            task="review",
            status="started",
            metadata={
                "chapter_id": chapter_id,
                "target_word_count": target,
                "raw_chars": len(raw),
                "polished_chars": len(polished),
                "polished_preview": preview_text(polished, 300),
                "edit_attempt_count": checkpoint.get("edit_attempt_count", 0),
                "acceptance_scope": checkpoint.get("acceptance_scope"),
            },
        )

        if is_acceptance_contract:
            word_count_ok = True
        else:
            word_count_ok = abs(_word_count(polished) - target) <= target * 0.1 if target > 0 else True
        ai_flavor_reduced = _check_ai_flavor_reduced(raw, polished)
        language_issues = _find_language_style_issues(polished)
        language_style_ok = not language_issues

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
        if language_style_ok:
            llm_result = await self._safe_llm_check_consistency_and_cohesion(polished, raw, trimmed_context, novel_id)
            consistency_fixed = llm_result.consistency_fixed
            beat_cohesion_ok = llm_result.beat_cohesion_ok
            notes = list(llm_result.notes)
        else:
            consistency_fixed = True
            beat_cohesion_ok = True
            notes = []

        if not word_count_ok:
            notes.append("字数偏离目标超过10%")
        notes.extend(language_issues)

        report = FastReviewReport(
            word_count_ok=word_count_ok,
            consistency_fixed=consistency_fixed,
            ai_flavor_reduced=ai_flavor_reduced,
            beat_cohesion_ok=beat_cohesion_ok,
            language_style_ok=language_style_ok,
            notes=notes,
        )

        passed = all([word_count_ok, consistency_fixed, ai_flavor_reduced, beat_cohesion_ok, language_style_ok])
        log_agent_detail(
            novel_id,
            "FastReviewAgent",
            f"快速评审结果: {'通过' if passed else '未通过'} "
            f"(字数={word_count_ok}, 一致性={consistency_fixed}, AI腔={ai_flavor_reduced}, "
            f"连贯={beat_cohesion_ok}, 语言={language_style_ok})",
            node="fast_review_result",
            task="review",
            status="succeeded" if passed else "failed",
            level="info" if passed else "warning",
            metadata={
                "chapter_id": chapter_id,
                "passed": passed,
                "word_count_ok": word_count_ok,
                "consistency_fixed": consistency_fixed,
                "ai_flavor_reduced": ai_flavor_reduced,
                "beat_cohesion_ok": beat_cohesion_ok,
                "language_style_ok": language_style_ok,
                "notes": notes,
                "target_word_count": target,
                "raw_word_count": _word_count(raw),
                "polished_word_count": _word_count(polished),
                "acceptance_scope": checkpoint.get("acceptance_scope"),
            },
        )

        await self.chapter_repo.update_fast_review(
            chapter_id,
            score=FAST_REVIEW_PASS_SCORE if passed else FAST_REVIEW_FAIL_SCORE,
            feedback=report.model_dump(),
        )

        edit_attempts = checkpoint.get("edit_attempt_count", 0)
        if passed or edit_attempts >= MAX_EDIT_ATTEMPTS:
            final_score, final_feedback = await self._score_final_text(
                novel_id=novel_id,
                chapter_id=chapter_id,
                polished=polished,
                chapter_context=checkpoint.get("chapter_context", {}),
                fallback_score=ch.final_review_score if ch.final_review_score is not None else ch.score_overall,
                fallback_feedback=ch.final_review_feedback or ch.review_feedback,
            )
            gate = QualityGateService.evaluate_fast_review(
                report,
                target_word_count=target,
                polished_word_count=_word_count(polished),
                final_review_score=final_score,
                polished_text=polished,
                required_payoffs=self._required_payoffs_from_context(checkpoint.get("chapter_context", {})),
                acceptance_scope=checkpoint.get("acceptance_scope"),
            )
            continuity_audit = ContinuityAuditService.audit_chapter(
                polished,
                checkpoint.get("chapter_context", {}),
            )
            checkpoint["continuity_audit"] = continuity_audit.model_dump()
            gate = _apply_continuity_audit_to_gate(gate, continuity_audit)
            checkpoint["quality_gate"] = gate.model_dump()
            await self.chapter_repo.update_quality_gate(
                chapter_id,
                quality_status=gate.status,
                quality_reasons=gate.model_dump(),
                final_review_score=final_score,
                final_review_feedback=final_feedback,
                draft_review_score=ch.draft_review_score if ch.draft_review_score is not None else ch.score_overall,
                draft_review_feedback=ch.draft_review_feedback or ch.review_feedback,
                world_state_ingested=False,
            )

            if gate.status == QUALITY_BLOCK:
                log_agent_detail(
                    novel_id,
                    "FastReviewAgent",
                    "质量门禁阻断，停止进入 librarian",
                    node="quality_gate_decision",
                    task="review",
                    status="failed",
                    level="warning",
                    metadata=gate.model_dump(),
                )
                await self.director.save_checkpoint(
                    novel_id,
                    phase=Phase.FAST_REVIEWING,
                    checkpoint_data=checkpoint,
                    volume_id=state.current_volume_id,
                    chapter_id=state.current_chapter_id,
                )
            elif not passed:
                report.notes.append(
                    f"edit_attempts={edit_attempts} 已达上限 {MAX_EDIT_ATTEMPTS},跳过精修轮转"
                )
                log_agent_detail(
                    novel_id,
                    "FastReviewAgent",
                    "未通过但质量门禁为告警，放行进入 librarian",
                    node="fast_review_decision",
                    task="review",
                    level="warning",
                    metadata={
                        "passed": passed,
                        "edit_attempts": edit_attempts,
                        "max_edit_attempts": MAX_EDIT_ATTEMPTS,
                        "target_phase": Phase.LIBRARIAN.value,
                        "quality_gate": gate.model_dump(),
                        "notes": report.notes,
                    },
                )
                checkpoint.pop("edit_attempt_count", None)
                await self.director.save_checkpoint(
                    novel_id,
                    phase=Phase.LIBRARIAN,
                    checkpoint_data=checkpoint,
                    volume_id=state.current_volume_id,
                    chapter_id=state.current_chapter_id,
                )
            else:
                log_agent_detail(
                    novel_id,
                    "FastReviewAgent",
                    "快速评审通过，进入 librarian 阶段",
                    node="fast_review_decision",
                    task="review",
                    metadata={"passed": passed, "target_phase": Phase.LIBRARIAN.value, "quality_gate": gate.model_dump()},
                )
                checkpoint.pop("edit_attempt_count", None)
                await self.director.save_checkpoint(
                    novel_id,
                    phase=Phase.LIBRARIAN,
                    checkpoint_data=checkpoint,
                    volume_id=state.current_volume_id,
                    chapter_id=state.current_chapter_id,
                )
        else:
            log_agent_detail(
                novel_id,
                "FastReviewAgent",
                "快速评审未通过，退回 editing 阶段",
                node="fast_review_decision",
                task="review",
                status="failed",
                level="warning",
                metadata={
                    "passed": passed,
                    "edit_attempts": edit_attempts,
                    "max_edit_attempts": MAX_EDIT_ATTEMPTS,
                    "target_phase": Phase.EDITING.value,
                    "notes": report.notes,
                },
            )
            await self.director.save_checkpoint(
                novel_id,
                phase=Phase.EDITING,
                checkpoint_data=checkpoint,
                volume_id=state.current_volume_id,
                chapter_id=state.current_chapter_id,
            )
        return report

    @staticmethod
    def _required_payoffs_from_context(chapter_context: dict) -> list[str]:
        if not isinstance(chapter_context, dict):
            return []
        payoffs: list[str] = []
        for card in chapter_context.get("writing_cards") or []:
            if not isinstance(card, dict):
                continue
            for key in ("required_payoffs", "ending_hook"):
                value = card.get(key)
                if isinstance(value, list):
                    payoffs.extend(str(item) for item in value if str(item or "").strip())
                elif value:
                    payoffs.append(str(value))
        seen = set()
        result = []
        for item in payoffs:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

    async def review_standalone(self, novel_id: str, chapter_id: str, checkpoint: dict) -> FastReviewReport:
        log_service.add_log(novel_id, "FastReviewAgent", f"开始独立快速评审: {chapter_id}")
        ch = await self.chapter_repo.get_by_id(chapter_id)
        if not ch:
            raise ValueError(f"Chapter not found: {chapter_id}")

        target = checkpoint.get("chapter_context", {}).get("chapter_plan", {}).get("target_word_count", 3000)
        raw = ch.raw_draft or ""
        polished = ch.polished_text or ""
        is_acceptance_contract = _is_acceptance_contract_checkpoint(checkpoint)

        if is_acceptance_contract:
            word_count_ok = True
        else:
            word_count_ok = abs(_word_count(polished) - target) <= target * 0.1 if target > 0 else True
        ai_flavor_reduced = _check_ai_flavor_reduced(raw, polished)
        language_issues = _find_language_style_issues(polished)
        language_style_ok = not language_issues

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
        if language_style_ok:
            llm_result = await self._safe_llm_check_consistency_and_cohesion(polished, raw, trimmed_context, novel_id)
            consistency_fixed = llm_result.consistency_fixed
            beat_cohesion_ok = llm_result.beat_cohesion_ok
            notes = list(llm_result.notes)
        else:
            consistency_fixed = True
            beat_cohesion_ok = True
            notes = []
        if not word_count_ok:
            notes.append("字数偏离目标超过10%")
        notes.extend(language_issues)
        report = FastReviewReport(
            word_count_ok=word_count_ok,
            consistency_fixed=consistency_fixed,
            ai_flavor_reduced=ai_flavor_reduced,
            beat_cohesion_ok=beat_cohesion_ok,
            language_style_ok=language_style_ok,
            notes=notes,
        )
        passed = all([
            word_count_ok,
            report.consistency_fixed,
            ai_flavor_reduced,
            report.beat_cohesion_ok,
            language_style_ok,
        ])
        await self.chapter_repo.update_fast_review(
            chapter_id,
            score=FAST_REVIEW_PASS_SCORE if passed else FAST_REVIEW_FAIL_SCORE,
            feedback=report.model_dump(),
        )
        edit_attempts = checkpoint.get("edit_attempt_count", 0)
        if passed or edit_attempts >= MAX_EDIT_ATTEMPTS:
            final_score, final_feedback = await self._score_final_text(
                novel_id=novel_id,
                chapter_id=chapter_id,
                polished=polished,
                chapter_context=checkpoint.get("chapter_context", {}),
                fallback_score=ch.final_review_score if ch.final_review_score is not None else ch.score_overall,
                fallback_feedback=ch.final_review_feedback or ch.review_feedback,
            )
            gate = QualityGateService.evaluate_fast_review(
                report,
                target_word_count=target,
                polished_word_count=_word_count(polished),
                final_review_score=final_score,
                polished_text=polished,
                required_payoffs=self._required_payoffs_from_context(checkpoint.get("chapter_context", {})),
                acceptance_scope=checkpoint.get("acceptance_scope"),
            )
            continuity_audit = ContinuityAuditService.audit_chapter(
                polished,
                checkpoint.get("chapter_context", {}),
            )
            checkpoint["continuity_audit"] = continuity_audit.model_dump()
            gate = _apply_continuity_audit_to_gate(gate, continuity_audit)
            checkpoint["quality_gate"] = gate.model_dump()
            await self.chapter_repo.update_quality_gate(
                chapter_id,
                quality_status=gate.status,
                quality_reasons=gate.model_dump(),
                final_review_score=final_score,
                final_review_feedback=final_feedback,
                draft_review_score=ch.draft_review_score if ch.draft_review_score is not None else ch.score_overall,
                draft_review_feedback=ch.draft_review_feedback or ch.review_feedback,
                world_state_ingested=False,
            )
        return report
