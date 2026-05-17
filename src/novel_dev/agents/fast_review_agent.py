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
from novel_dev.services.genre_template_service import GenreTemplateService
from novel_dev.services.quality_gate_service import QUALITY_BLOCK, QUALITY_UNCHECKED, QualityGateService
from novel_dev.services.quality_issue_service import QualityIssueService
from novel_dev.services.repair_planner_service import RepairPlanner
from novel_dev.services.continuity_audit_service import ContinuityAuditService
from novel_dev.services.prose_hygiene_service import ProseHygieneService
from novel_dev.schemas.quality import QualityIssue

logger = logging.getLogger(__name__)

FAST_REVIEW_PASS_SCORE = 100
FAST_REVIEW_FAIL_SCORE = 50
# Editor ↔ FastReview 最大循环次数,防止极端情况下无限翻译
MAX_EDIT_ATTEMPTS = 2
MAX_QUALITY_GATE_REPAIR_ATTEMPTS = 1


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
    return str(checkpoint.get("acceptance_scope") or "") in {"real-contract", "real-longform-volume1"}


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


def _modern_terms_authorized_for_fast_review(context: object | None) -> bool:
    if not isinstance(context, dict):
        return False
    quality_config = context.get("genre_quality_config")
    if isinstance(quality_config, dict):
        policy = quality_config.get("modern_terms_policy")
        if policy == "allow":
            return True
        if policy == "block":
            return False
    context_text = json.dumps(context, ensure_ascii=False)
    return any(marker in context_text for marker in ProseHygieneService.MODERN_AUTHORIZATION_MARKERS)


def _authorized_latin_terms_for_fast_review(context: object | None) -> set[str]:
    if not isinstance(context, dict):
        return set()
    quality_config = context.get("genre_quality_config")
    if not isinstance(quality_config, dict):
        return set()
    terms = quality_config.get("authorized_latin_terms") or ()
    if not isinstance(terms, (list, tuple, set)):
        return set()
    return {str(term).upper() for term in terms if str(term).strip()}


def _find_language_style_issues(text: str, context: object | None = None) -> list[str]:
    plan_issues = ProseHygieneService.find_plan_language_issues(text)
    modern_issues = [
        issue for issue in ProseHygieneService.find_modern_drift_issues(text, context=context)
        if not issue.startswith("发现英文/外文词:")
    ]
    words = []
    seen = set()
    modern_authorized = _modern_terms_authorized_for_fast_review(context)
    authorized_latin_terms = _authorized_latin_terms_for_fast_review(context)
    for match in _LATIN_WORD_RE.finditer(text or ""):
        word = match.group(0)
        key = word.lower()
        if len(set(key)) == 1:
            continue
        if key in seen:
            continue
        if modern_authorized and word.upper() in authorized_latin_terms:
            continue
        seen.add(key)
        words.append(word)
    issues = plan_issues + modern_issues
    if not words:
        return issues
    preview = "、".join(words[:8])
    suffix = " 等" if len(words) > 8 else ""
    issues.append(f"发现英文/外文词: {preview}{suffix}。正文应改为中文表达，除非章节计划明确要求保留原文。")
    return issues


def _build_genre_quality_issues(text: str, genre_quality_config: dict | None = None) -> list[QualityIssue]:
    return [
        QualityIssue(
            code="type_drift",
            category="style",
            severity="block",
            scope="chapter",
            repairability="guided",
            evidence=[item],
            suggestion="按所选小说分类移除未授权类型漂移内容。",
            source="fast_review",
        )
        for item in QualityGateService.genre_type_drift_items(text, genre_quality_config)
    ]


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
        self,
        polished: str,
        raw: str,
        chapter_context: dict,
        novel_id: str = "",
        genre_prompt_block: str = "",
    ) -> FastReviewLLMCheck:
        genre_section = f"### 类型模板约束\n{genre_prompt_block}\n\n" if genre_prompt_block.strip() else ""
        prompt = (
            "你是一位小说质量检查员。请根据以下精修文本、原始草稿和章节上下文,"
            "从读者体验出发检查两点并返回严格 JSON:\n"
            "1. consistency_fixed: 精修文本是否修复了与设定/上下文的不一致\n"
            "2. beat_cohesion_ok: 节拍之间是否连贯\n"
            "3. notes: 问题列表(字符串数组),最多 3 条,每条不超过 60 个汉字。"
            "简短指出最影响读感的问题和正向改写目标；若没有问题返回空数组。"
            "检查读者是否看得懂、是否相信人物、是否愿意继续读。"
            "如果精修文本仍有比喻过密、类型概念复读、感官平均用力、模板化异常事件或跨语域表达突兀,"
            "请写入 notes 并说明下一版应呈现什么效果。\n"
            "只返回 JSON 对象本体,不要 markdown 代码块。\n\n"
            f"{genre_section}"
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
        self,
        polished: str,
        raw: str,
        chapter_context: dict,
        novel_id: str = "",
        genre_prompt_block: str = "",
    ) -> FastReviewLLMCheck:
        try:
            return await self._llm_check_consistency_and_cohesion(
                polished,
                raw,
                chapter_context,
                novel_id,
                genre_prompt_block,
            )
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
        genre_quality_config: dict = {}
        genre_prompt_block = ""
        if novel_id:
            genre_template = await GenreTemplateService(self.session).resolve(
                novel_id,
                "FastReviewAgent",
                "fast_review",
            )
            genre_quality_config = genre_template.quality_config
            genre_prompt_block = genre_template.render_prompt_block("quality_rules", "forbidden_rules")
        language_context = {"genre_quality_config": genre_quality_config}
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
        language_issues = _find_language_style_issues(polished, context=language_context)
        genre_quality_issues = _build_genre_quality_issues(polished, genre_quality_config)
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
            "genre_quality_config": genre_quality_config,
        }
        if language_style_ok:
            llm_result = await self._safe_llm_check_consistency_and_cohesion(
                polished,
                raw,
                trimmed_context,
                novel_id,
                genre_prompt_block,
            )
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
        notes.extend(issue.evidence[0] for issue in genre_quality_issues if issue.evidence)

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
            gate = self._apply_structure_guard_to_gate(checkpoint, gate)
            gate = self._apply_genre_quality_issues_to_gate(gate, genre_quality_issues)
            checkpoint["quality_gate"] = gate.model_dump()
            self._store_quality_issues_and_repairs(
                checkpoint,
                gate,
                chapter_id,
                extra_issues=genre_quality_issues,
            )
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
                repair_attempts = int(checkpoint.get("quality_gate_repair_attempt_count", 0) or 0)
                if self._can_repair_quality_gate_block(gate, checkpoint) and repair_attempts < MAX_QUALITY_GATE_REPAIR_ATTEMPTS:
                    checkpoint["quality_gate_repair_attempt_count"] = repair_attempts + 1
                    checkpoint["final_polish_issues"] = self._build_final_polish_issues(
                        final_feedback=final_feedback,
                        gate_data=gate.model_dump(),
                        checkpoint=checkpoint,
                    )
                    log_agent_detail(
                        novel_id,
                        "FastReviewAgent",
                        "质量门禁命中可修复阻断，回到 editing 定点精修",
                        node="quality_gate_repair",
                        task="review",
                        status="failed",
                        level="warning",
                        metadata={
                            "quality_gate": gate.model_dump(),
                            "quality_gate_repair_attempt_count": checkpoint["quality_gate_repair_attempt_count"],
                            "max_quality_gate_repair_attempts": MAX_QUALITY_GATE_REPAIR_ATTEMPTS,
                            "final_polish_issues": checkpoint["final_polish_issues"],
                        },
                    )
                    await self.director.save_checkpoint(
                        novel_id,
                        phase=Phase.EDITING,
                        checkpoint_data=checkpoint,
                        volume_id=state.current_volume_id,
                        chapter_id=state.current_chapter_id,
                    )
                else:
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
            elif self._should_return_to_editing_for_final_polish(
                gate=gate,
                final_review_score=final_score,
                checkpoint=checkpoint,
                edit_attempts=edit_attempts,
            ):
                checkpoint["final_polish_issues"] = self._build_final_polish_issues(
                    final_feedback=final_feedback,
                    gate_data=gate.model_dump(),
                    checkpoint=checkpoint,
                )
                await self._reset_quality_for_edit_retry(checkpoint, chapter_id)
                log_agent_detail(
                    novel_id,
                    "FastReviewAgent",
                    "成稿复评仍有读感问题，回到 editing 定点精修",
                    node="fast_review_final_polish",
                    task="review",
                    level="warning",
                    metadata={
                        "final_review_score": final_score,
                        "edit_attempts": edit_attempts,
                        "max_edit_attempts": MAX_EDIT_ATTEMPTS,
                        "final_polish_issues": checkpoint["final_polish_issues"],
                    },
                )
                await self.director.save_checkpoint(
                    novel_id,
                    phase=Phase.EDITING,
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
                checkpoint.pop("quality_gate_repair_attempt_count", None)
                await self.director.save_checkpoint(
                    novel_id,
                    phase=Phase.LIBRARIAN,
                    checkpoint_data=checkpoint,
                    volume_id=state.current_volume_id,
                    chapter_id=state.current_chapter_id,
                )
        else:
            await self._reset_quality_for_edit_retry(checkpoint, chapter_id)
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
    def _apply_structure_guard_to_gate(checkpoint: dict, gate):
        evidence = FastReviewAgent._unresolved_structure_guard(checkpoint)
        if evidence is None:
            return gate

        item = {
            "code": "plan_boundary_violation",
            "message": "章节结构守卫发现未解决的计划边界违规",
            "detail": {
                "beat_index": evidence.get("beat_index"),
                "issues": evidence.get("issues") or [],
                "suggested_rewrite_focus": evidence.get("suggested_rewrite_focus") or "",
            },
        }
        if not any(existing == item for existing in gate.blocking_items):
            gate.blocking_items.append(item)
        gate.status = QUALITY_BLOCK
        gate.summary = "存在阻断级质量问题，停止归档和世界状态入库。"
        return gate

    @staticmethod
    def _apply_genre_quality_issues_to_gate(gate, genre_quality_issues: list[QualityIssue]):
        for issue in genre_quality_issues:
            item = {
                "code": issue.code,
                "message": issue.suggestion,
                "detail": issue.evidence,
            }
            if not any(existing == item for existing in gate.blocking_items):
                gate.blocking_items.append(item)
        if genre_quality_issues:
            gate.status = QUALITY_BLOCK
            gate.summary = "存在阻断级质量问题，停止归档和世界状态入库。"
        return gate

    @staticmethod
    def _clear_terminal_quality_metadata(checkpoint: dict) -> None:
        for key in (
            "quality_gate",
            "quality_issues",
            "quality_issue_summary",
            "repair_tasks",
            "continuity_audit",
        ):
            checkpoint.pop(key, None)

    async def _reset_quality_for_edit_retry(self, checkpoint: dict, chapter_id: str) -> None:
        self._clear_terminal_quality_metadata(checkpoint)
        await self.chapter_repo.update_quality_gate(
            chapter_id,
            quality_status=QUALITY_UNCHECKED,
            quality_reasons={},
            world_state_ingested=False,
        )

    @staticmethod
    def _store_quality_issues_and_repairs(
        checkpoint: dict,
        gate,
        chapter_id: str,
        extra_issues: list[QualityIssue] | None = None,
    ) -> None:
        structure_guard = FastReviewAgent._unresolved_structure_guard(checkpoint)
        quality_issues = QualityGateService.to_quality_issues(gate)
        if structure_guard is not None:
            quality_issues = [
                issue for issue in quality_issues
                if issue.code != "plan_boundary_violation" or issue.source != "quality_gate"
            ]
        quality_issues.extend(QualityIssueService.from_structure_guard(structure_guard, source="structure_guard"))
        if extra_issues:
            extra_codes = {issue.code for issue in extra_issues}
            quality_issues = [
                issue for issue in quality_issues
                if issue.code not in extra_codes or issue.source != "quality_gate"
            ]
            quality_issues.extend(extra_issues)
        checkpoint["quality_issues"] = [issue.model_dump() for issue in quality_issues]
        checkpoint["quality_issue_summary"] = QualityIssueService.summarize(quality_issues)

        if gate.status == QUALITY_BLOCK:
            repair_tasks = RepairPlanner.plan(chapter_id, quality_issues)
            checkpoint["repair_tasks"] = [task.model_dump() for task in repair_tasks]
        else:
            checkpoint.pop("repair_tasks", None)

    @staticmethod
    def _unresolved_structure_guard(checkpoint: dict) -> dict | None:
        evidence = checkpoint.get("chapter_structure_guard")
        if not isinstance(evidence, dict):
            return None
        resolved_items = checkpoint.get("editor_guard_resolved")
        if isinstance(resolved_items, list) and any(item == evidence for item in resolved_items):
            return None
        return evidence

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

    @staticmethod
    def _should_return_to_editing_for_final_polish(
        *,
        gate,
        final_review_score: int | None,
        checkpoint: dict,
        edit_attempts: int,
    ) -> bool:
        if gate.status == QUALITY_BLOCK or edit_attempts >= MAX_EDIT_ATTEMPTS:
            return False
        warning_codes = {
            str(item.get("code"))
            for item in gate.warning_items
            if isinstance(item, dict) and item.get("code")
        }
        if isinstance(final_review_score, (int, float)) and final_review_score < 75:
            return True
        if "required_payoff" in warning_codes:
            return True
        editor_warnings = checkpoint.get("editor_guard_warnings")
        return isinstance(editor_warnings, list) and bool(editor_warnings)

    @staticmethod
    def _can_repair_quality_gate_block(gate, checkpoint: dict) -> bool:
        blocking_codes = {
            str(item.get("code"))
            for item in gate.blocking_items
            if isinstance(item, dict) and item.get("code")
        }
        if not blocking_codes:
            return False
        recoverable_codes = {
            "beat_cohesion",
            "consistency",
            "plan_boundary_violation",
            "required_payoff",
            "text_integrity",
        }
        if not blocking_codes.issubset(recoverable_codes):
            return False
        acceptance_scope = str(checkpoint.get("acceptance_scope") or "")
        return acceptance_scope in {"real-contract", "real-longform-volume1"}

    @staticmethod
    def _build_final_polish_issues(
        *,
        final_feedback: dict,
        gate_data: dict,
        checkpoint: dict,
    ) -> dict:
        beat_issues: dict[int, list[dict]] = {}
        global_issues: list[dict] = []
        for issue in final_feedback.get("per_dim_issues") or []:
            if not isinstance(issue, dict):
                continue
            beat_idx = issue.get("beat_idx")
            if isinstance(beat_idx, int):
                beat_issues.setdefault(beat_idx, []).append(issue)
            else:
                global_issues.append(issue)

        for warning in checkpoint.get("editor_guard_warnings") or []:
            if not isinstance(warning, dict):
                continue
            beat_idx = warning.get("beat_index")
            issue = {
                "dim": "editing_boundary",
                "problem": "上一轮润色触发结构守卫：" + "；".join(str(item) for item in (warning.get("issues") or [])[:4]),
                "suggestion": warning.get("suggested_rewrite_focus") or "回到当前节拍已有事实，用动作、停顿、视线或身体反应增强读感。",
                "source_stage": "editing",
            }
            if isinstance(beat_idx, int):
                beat_issues.setdefault(beat_idx, []).append(issue)
            else:
                global_issues.append(issue)

        return {
            "source": "final_review",
            "summary_feedback": final_feedback.get("summary_feedback"),
            "beat_issues": [
                {"beat_index": beat_idx, "issues": issues}
                for beat_idx, issues in sorted(beat_issues.items())
            ],
            "global_issues": global_issues,
            "quality_gate_blocking_items": gate_data.get("blocking_items") or [],
            "quality_gate_warnings": gate_data.get("warning_items") or [],
        }

    async def review_standalone(self, novel_id: str, chapter_id: str, checkpoint: dict) -> FastReviewReport:
        log_service.add_log(novel_id, "FastReviewAgent", f"开始独立快速评审: {chapter_id}")
        ch = await self.chapter_repo.get_by_id(chapter_id)
        if not ch:
            raise ValueError(f"Chapter not found: {chapter_id}")

        target = checkpoint.get("chapter_context", {}).get("chapter_plan", {}).get("target_word_count", 3000)
        raw = ch.raw_draft or ""
        polished = ch.polished_text or ""
        genre_quality_config: dict = {}
        genre_prompt_block = ""
        if novel_id:
            genre_template = await GenreTemplateService(self.session).resolve(
                novel_id,
                "FastReviewAgent",
                "fast_review",
            )
            genre_quality_config = genre_template.quality_config
            genre_prompt_block = genre_template.render_prompt_block("quality_rules", "forbidden_rules")
        language_context = {"genre_quality_config": genre_quality_config}
        is_acceptance_contract = _is_acceptance_contract_checkpoint(checkpoint)

        if is_acceptance_contract:
            word_count_ok = True
        else:
            word_count_ok = abs(_word_count(polished) - target) <= target * 0.1 if target > 0 else True
        ai_flavor_reduced = _check_ai_flavor_reduced(raw, polished)
        language_issues = _find_language_style_issues(polished, context=language_context)
        genre_quality_issues = _build_genre_quality_issues(polished, genre_quality_config)
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
            "genre_quality_config": genre_quality_config,
        }
        if language_style_ok:
            llm_result = await self._safe_llm_check_consistency_and_cohesion(
                polished,
                raw,
                trimmed_context,
                novel_id,
                genre_prompt_block,
            )
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
        notes.extend(issue.evidence[0] for issue in genre_quality_issues if issue.evidence)
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
            gate = self._apply_structure_guard_to_gate(checkpoint, gate)
            gate = self._apply_genre_quality_issues_to_gate(gate, genre_quality_issues)
            checkpoint["quality_gate"] = gate.model_dump()
            self._store_quality_issues_and_repairs(
                checkpoint,
                gate,
                chapter_id,
                extra_issues=genre_quality_issues,
            )
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
        else:
            await self._reset_quality_for_edit_retry(checkpoint, chapter_id)
        return report
