import json
import logging
import re

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.review import FastReviewReport
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.agents._default_prompts import render_prompt_template
from novel_dev.agents._llm_helpers import call_and_parse_model
from novel_dev.agents._log_helpers import log_agent_detail, preview_text
from novel_dev.services.log_service import logged_agent_step, log_service
from novel_dev.services.genre_template_service import GenreTemplateService
from novel_dev.services.prompt_registry import PromptRegistry
from novel_dev.services.quality_gate_service import (
    QUALITY_BLOCK,
    QUALITY_MANUAL_REVIEW_REQUIRED,
    QUALITY_PASS,
    QUALITY_UNCHECKED,
    QUALITY_WARN,
    QualityGateService,
)
from novel_dev.services.quality_issue_service import QualityIssueService
from novel_dev.services.repair_planner_service import RepairPlanner
from novel_dev.services.continuity_audit_service import ContinuityAuditService
from novel_dev.services.cross_chapter_continuity_service import CrossChapterContinuityService
from novel_dev.services.prose_hygiene_service import ProseHygieneService
from novel_dev.services.chapter_acceptance_service import ChapterAcceptanceService
from novel_dev.services.chapter_obligation_service import ChapterObligationService
from novel_dev.services.root_cause_analyzer import RootCauseAnalyzer
from novel_dev.schemas.quality import BeatBoundaryCard, QualityIssue
from novel_dev.prompting.style_contract import StyleContractCompiler

logger = logging.getLogger(__name__)

FAST_REVIEW_PASS_SCORE = 100
FAST_REVIEW_FAIL_SCORE = 50
# Editor ↔ FastReview 最大循环次数,防止极端情况下无限翻译
MAX_EDIT_ATTEMPTS = 2
LONGFORM_MAX_EDIT_ATTEMPTS = 3
MAX_QUALITY_GATE_REPAIR_ATTEMPTS = 1
EXCELLENT_FINAL_REVIEW_SCORE = 90


# Phase 4 / Task 18: 网文 8 类爽点的关键词字典。
# 匹配策略:对 polished_text 做一次"任一关键词命中即认为达成"扫描,
# 命中后回写 evidence_quote(关键词所在上下文 16 字切片),供 CriticAgent 扣分参考。
THRILL_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "face_slap": ("反手一巴掌", "一巴掌", "啪啪", "耳光", "打脸", "众目睽睽", "跪下", "磕头"),
    "show_off": ("全场哗然", "众人惊叹", "惊艳", "震惊", "一片死寂", "倒吸一口凉气", "满座皆惊"),
    "level_up": ("突破", "晋级", "境界提升", "修为大涨", "破境", "凝结", "成就", "晋升"),
    "reward_gain": ("收获", "夺得", "得到", "捡到", "获得", "赏赐", "应得", "天材地宝", "灵石"),
    "revelation": ("真相", "原来", "竟然是他", "赫然", "浮出水面", "显露", "揭秘", "真容"),
    "revenge": ("报仇", "血债血偿", "讨回", "仇人", "雪耻", "以牙还牙", "复仇", "清算"),
    "plot_twist": ("出乎意料", "万万没想到", "峰回路转", "反将一军", "反转", "变数", "意外", "骤变"),
    "recognition": ("刮目相看", "认可", "拜服", "心服口服", "认输", "佩服", "赞誉", "点头赞许", "引为同道"),
}


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
    def __init__(self, session: AsyncSession, prompt_registry: PromptRegistry | None = None):
        self.session = session
        self.state_repo = NovelStateRepository(session)
        self.chapter_repo = ChapterRepository(session)
        self.director = NovelDirector(session)
        self.prompt_registry = prompt_registry or PromptRegistry(session)

    async def _llm_check_consistency_and_cohesion(
        self,
        polished: str,
        raw: str,
        chapter_context: dict,
        novel_id: str = "",
        genre_prompt_block: str = "",
        chapter_id: str = "",
    ) -> FastReviewLLMCheck:
        genre_section = f"### 类型模板约束\n{genre_prompt_block}\n\n" if genre_prompt_block.strip() else ""
        style_contract = StyleContractCompiler.compile(chapter_context.get("style_profile", {})).render_prompt_block()
        style_contract_segment = (style_contract + "\n\n") if style_contract else ""
        visible_context = dict(chapter_context)
        visible_context.pop("style_profile", None)
        if chapter_id:
            template = await self.prompt_registry.get_active_for_chapter("fast_review", chapter_id)
        else:
            template = await self.prompt_registry.get_active("fast_review")
        version = await self.prompt_registry.get_active_version_name("fast_review")
        prompt = render_prompt_template(
            template,
            genre_section=genre_section,
            style_contract=style_contract_segment,
            visible_context=json.dumps(visible_context, ensure_ascii=False),
            raw=raw,
            polished=polished,
        )
        result = await call_and_parse_model(
            "FastReviewAgent",
            "fast_review_check",
            prompt,
            FastReviewLLMCheck,
            max_retries=2,
            novel_id=novel_id,
        )
        await self.prompt_registry.increment_sample_count("fast_review", version)
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
        chapter_id: str = "",
    ) -> FastReviewLLMCheck:
        try:
            return await self._llm_check_consistency_and_cohesion(
                polished,
                raw,
                chapter_context,
                novel_id,
                genre_prompt_block,
                chapter_id,
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
                "overall": score.overall,
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
        language_context = {
            "genre_quality_config": genre_quality_config,
            **(checkpoint.get("chapter_context", {}) if isinstance(checkpoint.get("chapter_context"), dict) else {}),
        }
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
                chapter_id,
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
            beat_coverage_results=[],
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

        # Phase 4 / Task 18: 爽点达成验证需要在 gate 构建之前先做,以便
        # 失败回到 editing 时 miss 仍能写入 report.notes。
        await self._apply_thrill_point_verification(
            novel_id=novel_id,
            chapter_id=chapter_id,
            gate=None,
            polished=polished,
            report=report,
        )

        edit_attempts = checkpoint.get("edit_attempt_count", 0)
        max_edit_attempts = self._max_edit_attempts(checkpoint)
        if passed or edit_attempts >= max_edit_attempts:
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
                final_review_feedback=final_feedback,
                polished_text=polished,
                required_payoffs=self._required_payoffs_from_context(checkpoint.get("chapter_context", {})),
                ending_driver_candidates=self._ending_driver_candidates_from_context(checkpoint.get("chapter_context", {})),
                acceptance_scope=checkpoint.get("acceptance_scope"),
            )
            # Phase 4: BeatCoverageValidator
            chapter_context = checkpoint.get("chapter_context", {})
            beat_cards = [
                BeatBoundaryCard(
                    beat_index=b.get("beat_index", i),
                    must_cover=b.get("must_cover", []),
                    forbidden_materials=b.get("forbidden_materials", []),
                )
                for i, b in enumerate(chapter_context.get("beats", []))
            ]
            if beat_cards:
                try:
                    from novel_dev.config import settings
                    from novel_dev.services.beat_coverage_validator import BeatCoverageValidator
                    use_llm = bool(getattr(settings, "phase4_beat_coverage_use_llm", True))
                    validator = BeatCoverageValidator(self.session, use_llm=use_llm)
                    coverage = await validator.validate(beat_cards, polished)
                    for r in coverage:
                        if r.severity == "block" and r.to_issue_code():
                            gate.blocking_items.append({
                                "code": r.to_issue_code(),
                                "message": f"beat {r.beat_index}: {r.deviation}",
                                "detail": {"beat_index": r.beat_index, "deviation": r.deviation},
                            })
                    report.beat_coverage_results = [
                        {"beat_index": r.beat_index, "covered": r.covered, "severity": r.severity}
                        for r in coverage
                    ]
                except Exception as exc:
                    logger.warning(
                        "beat_coverage_validator_failed",
                        extra={"error": repr(exc), "chapter_id": chapter_id},
                    )
            # Phase 4: 钩子达成验证 — 末拍 required_open_question 关键词需在成稿中可被感知
            self._apply_open_question_check_to_gate(
                gate,
                chapter_context.get("beats", []) if isinstance(chapter_context, dict) else [],
                polished,
            )
            # Phase 4 / Task 18: 把爽点达成验证 miss 同步到 gate.warning_items,
            # 这样下游 quality_issues / checkpoint.quality_gate 都能感知。
            # (DB 标记动作在 review() 入口已先做,这里只补 gate 写回。)
            try:
                from novel_dev.repositories.thrill_point_repo import ThrillPointRepository

                _tp_repo = ThrillPointRepository(self.session)
                _unverified = await _tp_repo.list_unverified(novel_id, chapter_id=chapter_id)
                if _unverified:
                    self._apply_thrill_point_check_to_gate(gate, _unverified, polished)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "thrill_point_gate_promotion_failed",
                    extra={"chapter_id": chapter_id, "error": repr(exc)},
                )
            # Persist updated report with beat_coverage_results after validator runs
            await self.chapter_repo.update_fast_review(
                chapter_id,
                score=FAST_REVIEW_PASS_SCORE if passed else FAST_REVIEW_FAIL_SCORE,
                feedback=report.model_dump(),
            )
            # Phase 4 / Task 23: cross-chapter entity drift detection
            # (post-write). Uses entity_ids surfaced by ContextAgent; falls
            # back to scanning active_entities for matching ids when none
            # were pre-staged.
            drift_entity_ids = chapter_context.get("entity_ids") or []
            if not drift_entity_ids:
                drift_entity_ids = await self._resolve_drift_entity_ids(
                    chapter_context,
                    novel_id=novel_id,
                )
            try:
                continuity_svc = CrossChapterContinuityService(self.session)
                drifts = await continuity_svc.detect_drift(
                    novel_id=novel_id,
                    chapter_id=chapter_id,
                    polished_text=polished,
                    entity_ids=drift_entity_ids,
                )
                if drifts:
                    self._apply_cross_chapter_drift_to_gate(gate, drifts)
                report.cross_chapter_drift = [
                    {
                        "entity": d.entity_name,
                        "type": d.drift_type,
                        "severity": d.severity,
                    }
                    for d in drifts
                ]
                if drifts and not passed:
                    report.notes.append(
                        "[cross_chapter_drift] "
                        + "；".join(
                            f"{d.entity_name}({d.drift_type})" for d in drifts[:4]
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "cross_chapter_drift_detection_failed",
                    extra={"chapter_id": chapter_id, "error": repr(exc)},
                )
            continuity_audit = ContinuityAuditService.audit_chapter(
                polished,
                checkpoint.get("chapter_context", {}),
            )
            checkpoint["continuity_audit"] = continuity_audit.model_dump()
            gate = _apply_continuity_audit_to_gate(gate, continuity_audit)
            gate = self._apply_structure_guard_to_gate(checkpoint, gate)
            gate = self._apply_genre_quality_issues_to_gate(gate, genre_quality_issues)
            gate = self._downgrade_exhausted_longform_quality_warnings(
                gate,
                checkpoint=checkpoint,
                edit_attempts=edit_attempts,
            )
            self._store_final_review_feedback(checkpoint, final_score=final_score, final_feedback=final_feedback)
            checkpoint["quality_gate"] = gate.model_dump()
            self._store_quality_issues_and_repairs(
                checkpoint,
                gate,
                chapter_id,
                extra_issues=genre_quality_issues,
            )
            self._store_chapter_acceptance(
                checkpoint,
                polished_text=polished,
                target_word_count=target,
                final_feedback=final_feedback,
            )
            metric_issue_codes = [
                str(item.get("code"))
                for item in (gate.blocking_items or []) + (gate.warning_items or [])
                if isinstance(item, dict) and item.get("code")
            ]
            await self._finalize_and_record_metric(
                chapter=ch,
                phase="fast_reviewing",
                attempt_index=checkpoint.get("edit_attempt_count", 0),
                final_score=final_score,
                final_feedback=final_feedback,
                gate_status=gate.status,
                issue_codes=metric_issue_codes,
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
                final_feedback=final_feedback,
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
                        "max_edit_attempts": max_edit_attempts,
                        "final_polish_issues": checkpoint["final_polish_issues"],
                        "target_score": EXCELLENT_FINAL_REVIEW_SCORE,
                    },
                )
                await self.director.save_checkpoint(
                    novel_id,
                    phase=Phase.EDITING,
                    checkpoint_data=checkpoint,
                    volume_id=state.current_volume_id,
                    chapter_id=state.current_chapter_id,
                )
            elif gate.status == QUALITY_MANUAL_REVIEW_REQUIRED:
                log_agent_detail(
                    novel_id,
                    "FastReviewAgent",
                    "质量门禁需要人工确认，停止进入 librarian",
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
                await self._run_recommendation_wirer(novel_id, chapter_id)
            elif not passed:
                report.notes.append(
                    f"edit_attempts={edit_attempts} 已达上限 {max_edit_attempts},跳过精修轮转"
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
                        "max_edit_attempts": max_edit_attempts,
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
                await self._run_recommendation_wirer(novel_id, chapter_id)
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
                await self._run_recommendation_wirer(novel_id, chapter_id)
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
                    "max_edit_attempts": max_edit_attempts,
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
    def _apply_cross_chapter_drift_to_gate(gate, drifts) -> None:
        """Phase 4 / Task 23: route drift issues into the gate.

        Block-severity drifts are appended to ``blocking_items`` and force
        the gate into ``QUALITY_BLOCK``; warn-severity drifts land in
        ``warning_items``. The gate's ``summary`` is updated when the
        first drift item lands so downstream consumers see a coherent
        reason string.
        """
        for d in drifts:
            code = f"cross_chapter_{d.drift_type}"
            item = {
                "code": code,
                "message": f"{d.entity_name} 跨章{d.drift_type}: {d.evidence_quote}",
                "detail": {
                    "evidence": d.evidence_quote,
                    "fix": d.suggested_fix,
                    "entity": d.entity_name,
                    "drift_type": d.drift_type,
                },
            }
            if d.severity == "block":
                if not any(
                    existing.get("code") == code
                    for existing in gate.blocking_items
                    if isinstance(existing, dict)
                ):
                    gate.blocking_items.append(item)
                gate.status = QUALITY_BLOCK
                gate.summary = "存在阻断级质量问题，停止归档和世界状态入库。"
            else:
                if not any(
                    existing.get("code") == code
                    for existing in gate.warning_items
                    if isinstance(existing, dict)
                ):
                    gate.warning_items.append(item)

    async def _resolve_drift_entity_ids(
        self,
        chapter_context: dict,
        *,
        novel_id: str,
    ) -> list[str]:
        """Resolve ``entity_ids`` for cross-chapter drift detection by
        looking up the ``Entity.name`` values from
        ``chapter_context.active_entities``.

        Falls back to an empty list on any failure so the post-write
        detection is non-fatal.
        """
        if not isinstance(chapter_context, dict) or not novel_id:
            return []
        names: list[str] = []
        for entity in chapter_context.get("active_entities") or []:
            if not isinstance(entity, dict):
                continue
            name = str(entity.get("name") or "").strip()
            if name:
                names.append(name)
        if not names:
            return []
        try:
            from novel_dev.repositories.entity_repo import EntityRepository

            entities = await EntityRepository(self.session).find_by_names(
                names, novel_id=novel_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "cross_chapter_drift_resolve_entity_ids_failed",
                extra={"novel_id": novel_id, "error": repr(exc)},
            )
            return []
        ids: list[str] = []
        seen: set[str] = set()
        for entity in entities:
            eid = str(getattr(entity, "id", "") or "")
            if eid and eid not in seen:
                seen.add(eid)
                ids.append(eid)
        return ids

    @staticmethod
    def _extract_open_question_keywords(question: str) -> list[str]:
        """从末拍 required_open_question 中抽取用于钩子达成的关键词。

        简化策略:剥离常见标点后,取所有 2 字滑动窗口作为关键词。
        对于 "山门外的人是谁?" -> ["山门外", "门外", "外的", "的人", "人是", "是谁"]。
        任何关键词出现在成稿中即视为达成。
        """
        if not question:
            return []
        cleaned = re.sub(r"[？?。.!！,，;；:：、\s]+", "", question)
        if len(cleaned) < 2:
            return []
        return [cleaned[i : i + 2] for i in range(len(cleaned) - 1)]

    @classmethod
    def _apply_open_question_check_to_gate(cls, gate, beats: list, polished_text: str):
        """Phase 4: 钩子达成验证。

        遍历 chapter_context.beats,若某节拍为末拍且带有 required_open_question,
        但成稿 polished_text 中未出现该问题的任何 2 字关键词,则向 gate.warning_items
        追加一条 open_question_missing 告警。同步记录 beat_index,供 EditorAgent 定点修补。
        """
        if not isinstance(beats, list) or not beats:
            return gate
        for b in beats:
            if not isinstance(b, dict):
                continue
            if not b.get("is_last_beat"):
                continue
            question = b.get("required_open_question")
            if not question:
                continue
            keywords = cls._extract_open_question_keywords(str(question))
            if not keywords:
                continue
            text = polished_text or ""
            if any(kw in text for kw in keywords):
                continue
            item = {
                "code": "open_question_missing",
                "message": f"末拍未围绕 required_open_question ({question}) 收束",
                "detail": {
                    "question": str(question),
                    "beat_index": b.get("beat_index"),
                    "keywords": keywords,
                },
            }
            existing_codes = {
                str(w.get("code"))
                for w in gate.warning_items
                if isinstance(w, dict) and w.get("code")
            }
            if "open_question_missing" not in existing_codes:
                gate.warning_items.append(item)
        return gate

    @staticmethod
    def _find_thrill_keyword_evidence(thrill_type: str, polished_text: str) -> str | None:
        """Return a short evidence slice (≤16 字) when any keyword for
        ``thrill_type`` appears in ``polished_text``.  Returns None when
        the polished text does not exhibit a recognizable signal of the
        thrill type.

        The check is intentionally shallow (keyword presence) — the goal
        is to flag obvious misses for CriticAgent to deduct plot_tension
        points, not to certify the quality of a thrill delivery.
        """
        if not polished_text or not thrill_type:
            return None
        keywords = THRILL_TYPE_KEYWORDS.get(thrill_type)
        if not keywords:
            return None
        for kw in keywords:
            idx = polished_text.find(kw)
            if idx < 0:
                continue
            start = max(0, idx - 4)
            end = min(len(polished_text), idx + len(kw) + 12)
            return polished_text[start:end]
        return None

    @classmethod
    def _apply_thrill_point_check_to_gate(cls, gate, thrills: list, polished_text: str) -> list[dict]:
        """Add ``thrill_point_missing`` warning items for each unverified
        predicted thrill and return a list of evidence-snapshot dicts so
        callers can persist ``fast_review_verified`` + ``evidence_quote``
        on the underlying ``ThrillPoint`` rows.

        ``thrills`` is a list of :class:`ThrillPoint` ORM objects.  Returns
        ``[{thrill_point_id, verified, evidence_quote}]`` so the caller
        can flip the verified flag in the database.
        """
        if not thrills:
            return []
        snapshots: list[dict] = []
        existing_codes = {
            str(w.get("code"))
            for w in gate.warning_items
            if isinstance(w, dict) and w.get("code")
        }
        for tp in thrills:
            thrill_type = getattr(tp, "thrill_type", "")
            tp_id = getattr(tp, "id", None)
            evidence = cls._find_thrill_keyword_evidence(thrill_type, polished_text)
            if evidence is not None:
                snapshots.append(
                    {
                        "thrill_point_id": tp_id,
                        "verified": True,
                        "evidence_quote": evidence,
                    }
                )
                continue
            snapshots.append({"thrill_point_id": tp_id, "verified": False, "evidence_quote": None})
            if "thrill_point_missing" in existing_codes:
                continue
            item = {
                "code": "thrill_point_missing",
                "message": f"章节未呈现规划预测的爽点类型 {thrill_type} (强度 {getattr(tp, 'intensity', '')})",
                "detail": {
                    "thrill_type": thrill_type,
                    "intensity": getattr(tp, "intensity", ""),
                    "beat_idx": getattr(tp, "beat_idx", None),
                    "thrill_point_id": tp_id,
                },
            }
            gate.warning_items.append(item)
            existing_codes.add("thrill_point_missing")
        return snapshots

    async def _apply_thrill_point_verification(
        self,
        *,
        novel_id: str,
        chapter_id: str,
        gate,
        polished: str,
        report: "FastReviewReport | None" = None,
    ) -> None:
        """Phase 4 / Task 18: 拉取本章未验证的爽点预测,扫描成稿关键词,
        对命中的调用 ``ThrillPointRepository.mark_verified`` 写入证据;
        未命中项加入 ``thrill_point_missing`` 告警。

        当 ``gate`` 为 None 时(快速评审失败回到 editing 阶段),
        miss 列表会回填到 ``report.notes`` 以便下游 UI 仍能感知。
        任何异常都被吞掉并记 warning,确保不破坏主评审路径。
        """
        if not novel_id or not chapter_id:
            return
        try:
            from novel_dev.repositories.thrill_point_repo import ThrillPointRepository

            repo = ThrillPointRepository(self.session)
            thrills = await repo.list_unverified(novel_id, chapter_id=chapter_id)
            if not thrills:
                return
            if gate is not None:
                snapshots = self._apply_thrill_point_check_to_gate(gate, thrills, polished)
            else:
                snapshots = self._apply_thrill_point_check_to_report(report, thrills, polished)
            for snap in snapshots:
                if not snap.get("verified"):
                    continue
                tp_id = snap.get("thrill_point_id")
                if not tp_id:
                    continue
                await repo.mark_verified(
                    tp_id,
                    evidence_quote=snap.get("evidence_quote"),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "thrill_point_verification_failed",
                extra={"chapter_id": chapter_id, "error": repr(exc)},
            )

    @classmethod
    def _apply_thrill_point_check_to_report(
        cls,
        report,
        thrills: list,
        polished_text: str,
    ) -> list[dict]:
        """回退路径:没有 ``gate`` 时,把未命中的爽点写入 ``report.notes``。

        与 ``_apply_thrill_point_check_to_gate`` 行为一致,只是把 warning
        容器从 gate 换到 FastReviewReport.notes。
        """
        if not thrills:
            return []
        snapshots: list[dict] = []
        for tp in thrills:
            thrill_type = getattr(tp, "thrill_type", "")
            tp_id = getattr(tp, "id", None)
            evidence = cls._find_thrill_keyword_evidence(thrill_type, polished_text)
            if evidence is not None:
                snapshots.append(
                    {
                        "thrill_point_id": tp_id,
                        "verified": True,
                        "evidence_quote": evidence,
                    }
                )
                continue
            snapshots.append({"thrill_point_id": tp_id, "verified": False, "evidence_quote": None})
            if report is not None and not any(
                isinstance(n, str) and n.startswith("[thrill_point_missing]") for n in (report.notes or [])
            ):
                report.notes.append(
                    f"[thrill_point_missing] {thrill_type} (强度 {getattr(tp, 'intensity', '')}) 未在成稿中识别"
                )
        return snapshots

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

        if gate.status in {QUALITY_BLOCK, QUALITY_MANUAL_REVIEW_REQUIRED}:
            repair_tasks = RepairPlanner.plan(chapter_id, quality_issues)
            checkpoint["repair_tasks"] = [task.model_dump() for task in repair_tasks]
        else:
            checkpoint.pop("repair_tasks", None)

    @staticmethod
    def _store_chapter_acceptance(
        checkpoint: dict,
        *,
        polished_text: str,
        target_word_count: int | None = None,
        final_feedback: dict | None = None,
    ) -> None:
        obligation_contract = ChapterObligationService.build_from_context(
            checkpoint.get("chapter_context") or {}
        )
        assessment = ChapterAcceptanceService.assess(
            content=polished_text,
            quality_issues=checkpoint.get("quality_issues") or [],
            target_word_count=target_word_count,
            obligation_contract=obligation_contract,
        )
        checkpoint["chapter_acceptance"] = assessment.model_dump()
        improvement_directives = FastReviewAgent._build_chapter_improvement_directives(
            checkpoint,
            final_feedback=final_feedback,
        )
        if improvement_directives:
            checkpoint["chapter_improvement_directives"] = improvement_directives
        else:
            checkpoint.pop("chapter_improvement_directives", None)

    @staticmethod
    def _store_final_review_feedback(
        checkpoint: dict,
        *,
        final_score: int | None,
        final_feedback: dict | None,
    ) -> None:
        if not isinstance(final_feedback, dict) or not final_feedback:
            return
        checkpoint["critique_feedback"] = {
            "overall": final_feedback.get("overall", final_score),
            "summary": final_feedback.get("summary") or final_feedback.get("summary_feedback", ""),
            "breakdown": final_feedback.get("breakdown") or {},
            "source": "final_review",
        }
        checkpoint["per_dim_issues"] = [
            item for item in (final_feedback.get("per_dim_issues") or [])
            if isinstance(item, dict)
        ]
        checkpoint["beat_scores"] = []

    async def _finalize_and_record_metric(
        self,
        chapter,
        phase: str,
        attempt_index: int,
        final_score,
        final_feedback,
        gate_status: str,
        issue_codes=None,
    ):
        """Persist a chapter_quality_metrics row for this review attempt.

        Called alongside the existing _store_final_review_feedback checkpoint
        write so that every fast review produces a queryable metric row.
        """
        from novel_dev.services.quality_metrics_service import (
            QualityMetricsService,
            QualityMetricInput,
        )
        from novel_dev.config.quality_config import get_quality_config

        # Skip cleanly if the chapter has no novel_id — chapter_quality_metrics
        # requires novel_id as a NOT NULL column, and a flush failure here
        # would poison the session and break the rest of the finalize path.
        if not getattr(chapter, "novel_id", None):
            return
        try:
            cfg = get_quality_config()
            dim_scores = (final_feedback or {}).get("breakdown") or {}
            svc = QualityMetricsService(self.session)
            await svc.record(QualityMetricInput(
                chapter_id=chapter.id,
                novel_id=chapter.novel_id,
                phase=phase,
                attempt_index=attempt_index,
                overall_score=final_score,
                dimension_scores=dim_scores if isinstance(dim_scores, dict) else {},
                gate_status=gate_status,
                issue_codes=issue_codes or [],
                model_version=cfg.get("model_version"),
            ))
        except Exception as e:  # noqa: BLE001
            # Never let metric recording fail the chapter finalize path.
            # A failed flush poisons the session, so we must roll back
            # before the caller can run any further DB operations.
            import logging
            logging.getLogger(__name__).warning("metric_record_failed", extra={"err": str(e)[:200]})
            try:
                await self.session.rollback()
            except Exception:  # noqa: BLE001
                pass

    async def _run_root_cause_for_non_pass_gate(
        self,
        *,
        novel_id: str,
        chapter_id: str,
        chapter,
        gate,
        final_feedback: dict | None,
        checkpoint: dict,
    ) -> None:
        """当门禁未通过时,调用 RootCauseAnalyzer 诊断根因并写回 checkpoint。

        - 仅在 gate.status != QUALITY_PASS 时触发(符合规格:通过即跳过)。
        - 任何异常都被吞掉并记录 warning,确保不破坏主评审路径。
        - 写入 checkpoint["root_cause"] (summary) 与
          checkpoint["root_cause_actions"] (suggested_actions),
          供下游 WriterAgent/ChapterRewriteService 消费。
        """
        gate_status = getattr(gate, "status", None) if gate is not None else None
        if gate_status == QUALITY_PASS:
            return
        try:
            score_breakdown: dict = {}
            if isinstance(final_feedback, dict):
                breakdown = final_feedback.get("breakdown")
                if isinstance(breakdown, dict):
                    score_breakdown = breakdown
            issue_codes: list[str] = []
            for bucket in (gate.blocking_items or [], gate.warning_items or []):
                for item in bucket:
                    if isinstance(item, dict):
                        code = item.get("code")
                        if code:
                            issue_codes.append(str(code))

            chapter_text = ""
            if chapter is not None:
                chapter_text = (chapter.polished_text or chapter.raw_draft or "")

            beat_cards: list = []
            chapter_context = checkpoint.get("chapter_context") or {}
            if isinstance(chapter_context, dict):
                plan = chapter_context.get("chapter_plan") or {}
                if isinstance(plan, dict):
                    raw_cards = plan.get("beat_boundary_cards") or []
                    if isinstance(raw_cards, list):
                        beat_cards = [c for c in raw_cards if c is not None]

            analyzer = RootCauseAnalyzer(self.session)
            result = await analyzer.analyze(
                novel_id=novel_id,
                chapter_id=chapter_id,
                chapter_text=chapter_text,
                score_breakdown=score_breakdown,
                issue_codes=issue_codes,
                beat_boundary_cards=beat_cards,
            )
            checkpoint["root_cause"] = result.summary
            checkpoint["root_cause_actions"] = list(result.suggested_actions or [])
            checkpoint["root_cause_confidence"] = float(result.confidence or 0.0)
            checkpoint["root_cause_analyzer_version"] = result.analyzer_version
            log_agent_detail(
                novel_id,
                "FastReviewAgent",
                f"RootCauseAnalyzer 完成: gate={gate_status} confidence={result.confidence:.2f}",
                node="root_cause_analyzer",
                task="review",
                metadata={
                    "chapter_id": chapter_id,
                    "gate_status": gate_status,
                    "confidence": result.confidence,
                    "issue_codes": issue_codes,
                },
            )
        except Exception as exc:
            logger.warning(
                "root_cause_integration_failed",
                extra={"chapter_id": chapter_id, "gate_status": gate_status, "error": repr(exc)},
            )

    async def _run_recommendation_wirer(self, novel_id: str, chapter_id: str):
        # Deferred import to avoid circular dependency
        from novel_dev.services.recommendation_wirer import RecommendationWirer

        wirer = RecommendationWirer(self.session)
        try:
            result = await wirer.evaluate_and_dispatch(novel_id, chapter_id)
            logger.info(
                "recommendation_wirer_result",
                extra={"chapter_id": chapter_id, "action": result.action},
            )
        except Exception as exc:
            logger.error("recommendation_wirer_error", extra={"chapter_id": chapter_id, "error": repr(exc)})

    @staticmethod
    def _build_chapter_improvement_directives(
        checkpoint: dict,
        *,
        final_feedback: dict | None = None,
    ) -> list[dict]:
        directives: list[dict] = []
        per_dim_issues = (
            final_feedback.get("per_dim_issues")
            if isinstance(final_feedback, dict) and isinstance(final_feedback.get("per_dim_issues"), list)
            else checkpoint.get("per_dim_issues")
        )
        if isinstance(per_dim_issues, list):
            for issue in per_dim_issues:
                if not isinstance(issue, dict):
                    continue
                suggestion = str(issue.get("suggestion") or "").strip()
                if not suggestion:
                    continue
                directive = {
                    "mode": "improve",
                    "source": "final_review",
                    "target": str(issue.get("dim") or "chapter"),
                    "instruction": suggestion,
                    "non_blocking": True,
                }
                if issue.get("beat_idx") is not None:
                    directive["beat_index"] = issue.get("beat_idx")
                if issue.get("problem"):
                    directive["problem"] = str(issue.get("problem"))
                directives.append(directive)
                if len(directives) >= 6:
                    break

        editor_guard_warnings = checkpoint.get("editor_guard_warnings")
        if isinstance(editor_guard_warnings, list):
            for warning in editor_guard_warnings:
                if not isinstance(warning, dict):
                    continue
                focus = str(warning.get("suggested_rewrite_focus") or "").strip()
                if not focus:
                    continue
                directive = {
                    "mode": "improve",
                    "source": "editor_guard",
                    "target": "structure_guard",
                    "instruction": focus,
                    "non_blocking": True,
                }
                if warning.get("beat_index") is not None:
                    directive["beat_index"] = warning.get("beat_index")
                directives.append(directive)
                if len(directives) >= 6:
                    break
        return directives

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
    def _ending_driver_candidates_from_context(chapter_context: dict) -> list[str]:
        if not isinstance(chapter_context, dict):
            return []
        cards = chapter_context.get("writing_cards") or []
        if not isinstance(cards, list):
            return []
        max_beat = None
        for card in cards:
            if isinstance(card, dict) and isinstance(card.get("beat_index"), int):
                max_beat = card["beat_index"] if max_beat is None else max(max_beat, card["beat_index"])
        candidates: list[str] = []
        for card in cards:
            if not isinstance(card, dict):
                continue
            if max_beat is not None and card.get("beat_index") != max_beat:
                continue
            value = card.get("ending_driver_candidates")
            if isinstance(value, list):
                candidates.extend(str(item) for item in value if str(item or "").strip())
        seen = set()
        result = []
        for item in candidates:
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
        final_feedback: dict | None = None,
    ) -> bool:
        if gate.status == QUALITY_BLOCK or edit_attempts >= FastReviewAgent._max_edit_attempts(checkpoint):
            return False
        warning_codes = {
            str(item.get("code"))
            for item in gate.warning_items
            if isinstance(item, dict) and item.get("code")
        }
        if isinstance(final_review_score, (int, float)) and final_review_score < 75:
            return True
        if warning_codes.intersection({"final_review_score", "critical_dimension_score", "required_payoff"}):
            return True
        editor_warnings = checkpoint.get("editor_guard_warnings")
        if isinstance(editor_warnings, list) and bool(editor_warnings):
            return True
        return FastReviewAgent._should_return_for_excellent_polish(
            gate=gate,
            final_review_score=final_review_score,
            final_feedback=final_feedback,
        )

    @staticmethod
    def _max_edit_attempts(checkpoint: dict | None) -> int:
        if isinstance(checkpoint, dict) and str(checkpoint.get("acceptance_scope") or "") == "real-longform-volume1":
            return LONGFORM_MAX_EDIT_ATTEMPTS
        return MAX_EDIT_ATTEMPTS

    @staticmethod
    def _should_return_for_excellent_polish(
        *,
        gate,
        final_review_score: int | None,
        final_feedback: dict | None,
    ) -> bool:
        if gate.status not in {QUALITY_PASS, QUALITY_WARN}:
            return False
        if not isinstance(final_review_score, (int, float)):
            return False
        if final_review_score >= EXCELLENT_FINAL_REVIEW_SCORE:
            return False
        if final_review_score < 82:
            return False
        if not isinstance(final_feedback, dict):
            return False
        return any(isinstance(item, dict) and item.get("suggestion") for item in final_feedback.get("per_dim_issues") or [])

    @staticmethod
    def _downgrade_exhausted_longform_quality_warnings(gate, *, checkpoint: dict, edit_attempts: int):
        if gate.status != QUALITY_MANUAL_REVIEW_REQUIRED:
            return gate
        if edit_attempts < FastReviewAgent._max_edit_attempts(checkpoint):
            return gate
        if str(checkpoint.get("acceptance_scope") or "") != "real-longform-volume1":
            return gate
        if gate.blocking_items:
            return gate
        warning_codes = {
            str(item.get("code"))
            for item in gate.warning_items
            if isinstance(item, dict) and item.get("code")
        }
        auto_run_safe_codes = {"word_count_drift"}
        if not warning_codes or not warning_codes.issubset(auto_run_safe_codes):
            return gate
        gate.status = QUALITY_WARN
        gate.summary = "自动精修达到上限，剩余非阻断质量告警已保留，允许长篇自动归档。"
        return gate

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

        result = {
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
        overall = final_feedback.get("overall") or final_feedback.get("score")
        if isinstance(overall, (int, float)) and overall < EXCELLENT_FINAL_REVIEW_SCORE:
            result["polish_mode"] = "excellent_candidate"
            result["target_score"] = EXCELLENT_FINAL_REVIEW_SCORE
        elif final_feedback.get("summary_feedback"):
            result["target_score"] = EXCELLENT_FINAL_REVIEW_SCORE
        return result

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
        language_context = {
            "genre_quality_config": genre_quality_config,
            **(checkpoint.get("chapter_context", {}) if isinstance(checkpoint.get("chapter_context"), dict) else {}),
        }
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
                chapter_id,
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
        if passed or edit_attempts >= self._max_edit_attempts(checkpoint):
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
                final_review_feedback=final_feedback,
                polished_text=polished,
                required_payoffs=self._required_payoffs_from_context(checkpoint.get("chapter_context", {})),
                ending_driver_candidates=self._ending_driver_candidates_from_context(checkpoint.get("chapter_context", {})),
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
            self._store_final_review_feedback(checkpoint, final_score=final_score, final_feedback=final_feedback)
            checkpoint["quality_gate"] = gate.model_dump()
            self._store_quality_issues_and_repairs(
                checkpoint,
                gate,
                chapter_id,
                extra_issues=genre_quality_issues,
            )
            self._store_chapter_acceptance(
                checkpoint,
                polished_text=polished,
                target_word_count=target,
            )
            metric_issue_codes = [
                str(item.get("code"))
                for item in (gate.blocking_items or []) + (gate.warning_items or [])
                if isinstance(item, dict) and item.get("code")
            ]
            await self._finalize_and_record_metric(
                chapter=ch,
                phase="fast_reviewing",
                attempt_index=checkpoint.get("edit_attempt_count", 0),
                final_score=final_score,
                final_feedback=final_feedback,
                gate_status=gate.status,
                issue_codes=metric_issue_codes,
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
            await self._run_root_cause_for_non_pass_gate(
                novel_id=novel_id,
                chapter_id=chapter_id,
                chapter=ch,
                gate=gate,
                final_feedback=final_feedback,
                checkpoint=checkpoint,
            )
            await self._run_recommendation_wirer(novel_id, chapter_id)
        else:
            await self._reset_quality_for_edit_retry(checkpoint, chapter_id)
        return report
