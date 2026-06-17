import json
from typing import List
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.review import ScoreResult, DimensionScore
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.agents._llm_helpers import call_and_parse_model
from novel_dev.agents._log_helpers import log_agent_detail, preview_text
from novel_dev.agents._default_prompts import render_prompt_template
from novel_dev.services.genre_template_service import GenreTemplateService
from novel_dev.services.log_service import logged_agent_step, log_service
from novel_dev.services.prompt_registry import PromptRegistry
from novel_dev.prompting.style_contract import StyleContractCompiler


class BeatScoreIssue(BaseModel):
    dim: str
    problem: str
    suggestion: str


class BeatScorePayload(BaseModel):
    beat_index: int
    scores: dict[str, int] = Field(default_factory=dict)
    issues: List[BeatScoreIssue] = Field(default_factory=list)


class CriticAgent:
    def __init__(self, session: AsyncSession, prompt_registry: PromptRegistry | None = None):
        self.session = session
        self.state_repo = NovelStateRepository(session)
        self.chapter_repo = ChapterRepository(session)
        self.director = NovelDirector(session)
        self.prompt_registry = prompt_registry or PromptRegistry(session)

    @logged_agent_step("CriticAgent", "评审章节", node="review", task="review")
    async def review(self, novel_id: str, chapter_id: str) -> ScoreResult:
        log_service.add_log(novel_id, "CriticAgent", f"开始评审章节: {chapter_id}")
        state = await self.state_repo.get_state(novel_id)
        if not state:
            log_service.add_log(novel_id, "CriticAgent", "小说状态未找到", level="error")
            raise ValueError(f"Novel state not found for {novel_id}")
        if state.current_phase != Phase.REVIEWING.value:
            log_service.add_log(novel_id, "CriticAgent", f"当前阶段 {state.current_phase} 不允许评审", level="error")
            raise ValueError(f"Cannot review from phase {state.current_phase}")

        ch = await self.chapter_repo.get_by_id(chapter_id)
        if not ch:
            raise ValueError(f"Chapter not found: {chapter_id}")

        checkpoint = dict(state.checkpoint_data or {})
        context_data = checkpoint.get("chapter_context")
        if not context_data:
            raise ValueError("chapter_context missing in checkpoint_data")

        score_result = await self._generate_score(ch.raw_draft or "", context_data, novel_id, chapter_id)
        log_agent_detail(
            novel_id,
            "CriticAgent",
            f"章节评分完成：overall={score_result.overall}",
            node="critic_score",
            task="score_chapter",
            metadata={
                "chapter_id": chapter_id,
                "draft_chars": len(ch.raw_draft or ""),
                "beat_count": len(context_data.get("chapter_plan", {}).get("beats", [])),
                "overall": score_result.overall,
                "dimensions": {d.name: {"score": d.score, "comment": d.comment} for d in score_result.dimensions},
                "summary_feedback": score_result.summary_feedback,
                "per_dim_issues": [issue.model_dump() for issue in score_result.per_dim_issues[:12]],
            },
        )
        beat_scores = await self._generate_beat_scores(context_data, novel_id)
        log_agent_detail(
            novel_id,
            "CriticAgent",
            f"节拍评分完成：{len(beat_scores)} 个节拍",
            node="critic_beat_scores",
            task="score_beats",
            metadata={"chapter_id": chapter_id, "beat_scores": beat_scores[:12]},
        )

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
            "breakdown": {
                d.name: {"score": d.score, "comment": d.comment}
                for d in score_result.dimensions
            },
        }
        checkpoint["per_dim_issues"] = [issue.model_dump() for issue in score_result.per_dim_issues]

        overall = score_result.overall
        dimensions = {d.name: d.score for d in score_result.dimensions}

        red_line_failed = dimensions.get("consistency", 100) < 30 or dimensions.get("humanity", 100) < 40

        if overall < 70 or red_line_failed:
            attempt = checkpoint.get("draft_attempt_count", 0) + 1
            log_agent_detail(
                novel_id,
                "CriticAgent",
                f"评分不达标，退回 drafting：overall={overall}，尝试 {attempt}/3",
                node="critic_decision",
                task="review",
                status="failed",
                level="warning",
                metadata={
                    "chapter_id": chapter_id,
                    "overall": overall,
                    "red_line_failed": red_line_failed,
                    "dimensions": dimensions,
                    "attempt": attempt,
                    "target_phase": Phase.DRAFTING.value,
                    "reason": preview_text(score_result.summary_feedback, 300),
                },
            )
            if attempt >= 3:
                if self._allow_forced_editing_after_max_draft_attempts(checkpoint):
                    checkpoint["draft_attempt_count"] = attempt
                    checkpoint["draft_rewrite_plan"] = self._build_draft_rewrite_plan(
                        score_result,
                        beat_scores,
                        beat_count=len(context_data.get("chapter_plan", {}).get("beats", [])),
                        rewrite_all=True,
                    )
                    checkpoint["critic_forced_editing"] = {
                        "attempt": attempt,
                        "overall": overall,
                        "red_line_failed": red_line_failed,
                        "summary_feedback": score_result.summary_feedback,
                        "dimensions": dimensions,
                    }
                    log_agent_detail(
                        novel_id,
                        "CriticAgent",
                        "已达最大草稿重写次数，切到 editing 做抢救式收敛",
                        node="critic_decision",
                        task="review",
                        status="failed",
                        level="warning",
                        metadata={
                            "chapter_id": chapter_id,
                            "attempt": attempt,
                            "overall": overall,
                            "red_line_failed": red_line_failed,
                            "target_phase": Phase.EDITING.value,
                            "acceptance_scope": checkpoint.get("acceptance_scope"),
                        },
                    )
                    await self.director.save_checkpoint(
                        novel_id,
                        phase=Phase.EDITING,
                        checkpoint_data=checkpoint,
                        volume_id=state.current_volume_id,
                        chapter_id=state.current_chapter_id,
                    )
                    return score_result
                log_service.add_log(novel_id, "CriticAgent", "已达最大重写次数", level="error")
                raise RuntimeError("Max draft attempts exceeded")
            checkpoint["draft_attempt_count"] = attempt
            checkpoint["drafting_progress"] = {
                "beat_index": 0,
                "total_beats": len(context_data.get("chapter_plan", {}).get("beats", [])),
                "current_word_count": 0,
            }
            checkpoint.pop("relay_history", None)
            checkpoint["draft_rewrite_plan"] = self._build_draft_rewrite_plan(
                score_result,
                beat_scores,
                beat_count=len(context_data.get("chapter_plan", {}).get("beats", [])),
                rewrite_all=True,
            )
            await self.director.save_checkpoint(
                novel_id,
                phase=Phase.DRAFTING,
                checkpoint_data=checkpoint,
                volume_id=state.current_volume_id,
                chapter_id=state.current_chapter_id,
            )
        else:
            checkpoint.pop("draft_attempt_count", None)
            # 进入新一轮编辑时重置 editor 尝试计数,确保本章 polish 循环独立
            checkpoint.pop("edit_attempt_count", None)
            log_agent_detail(
                novel_id,
                "CriticAgent",
                "评分通过，进入 editing 阶段",
                node="critic_decision",
                task="review",
                metadata={
                    "chapter_id": chapter_id,
                    "overall": overall,
                    "dimensions": dimensions,
                    "target_phase": Phase.EDITING.value,
                },
            )
            await self.director.save_checkpoint(
                novel_id,
                phase=Phase.EDITING,
                checkpoint_data=checkpoint,
                volume_id=state.current_volume_id,
                chapter_id=state.current_chapter_id,
            )

        return score_result

    @staticmethod
    def _allow_forced_editing_after_max_draft_attempts(checkpoint: dict) -> bool:
        acceptance_scope = str(checkpoint.get("acceptance_scope") or "")
        return acceptance_scope in {"real-contract", "real-longform-volume1"}

    def _build_draft_rewrite_plan(
        self,
        score_result: ScoreResult,
        beat_scores: List[dict],
        *,
        beat_count: int | None = None,
        rewrite_all: bool = False,
    ) -> dict:
        total_beats = max(beat_count or 0, len(beat_scores))
        beat_issues = [{"beat_index": idx, "issues": []} for idx in range(total_beats)]
        global_issues = []

        for issue in score_result.per_dim_issues:
            payload = issue.model_dump()
            beat_idx = payload.get("beat_idx")
            if isinstance(beat_idx, int) and 0 <= beat_idx < total_beats:
                beat_issues[beat_idx]["issues"].append(payload)
            else:
                global_issues.append(payload)

        for item in beat_scores:
            beat_idx = item.get("beat_index")
            if not isinstance(beat_idx, int) or not (0 <= beat_idx < total_beats):
                continue
            scores = item.get("scores") or {}
            issues = item.get("issues") or []
            for issue in issues:
                beat_issues[beat_idx]["issues"].append(issue)
            low_dims = [dim for dim, score in scores.items() if isinstance(score, (int, float)) and score < 70]
            for dim in low_dims:
                if not any(issue.get("dim") == dim for issue in beat_issues[beat_idx]["issues"] if isinstance(issue, dict)):
                    beat_issues[beat_idx]["issues"].append({
                        "dim": dim,
                        "problem": f"{dim} 评分低于 70",
                        "suggestion": "重写本节拍，优先补强该维度对应的冲突、细节或读感问题。",
                    })

        return {
            "rewrite_all": rewrite_all,
            "overall": score_result.overall,
            "summary_feedback": score_result.summary_feedback,
            "global_issues": global_issues,
            "beat_issues": beat_issues,
        }

    async def _generate_score(self, raw_draft: str, context_data: dict, novel_id: str = "", chapter_id: str = "") -> ScoreResult:
        log_agent_detail(
            novel_id,
            "CriticAgent",
            "章节评分输入已准备",
            node="critic_score_input",
            task="score_chapter",
            status="started",
            metadata={
                "draft_chars": len(raw_draft or ""),
                "draft_preview": preview_text(raw_draft, 300),
                "beat_count": len(context_data.get("chapter_plan", {}).get("beats", [])),
                "active_entity_count": len(context_data.get("active_entities", [])),
                "foreshadowing_count": len(context_data.get("pending_foreshadowings", [])),
            },
        )
        # Trim context to only what Critic needs, avoiding retrieval bloat
        style_contract = StyleContractCompiler.compile(context_data.get("style_profile", {})).render_prompt_block()
        trimmed_context = {
            "chapter_plan": context_data.get("chapter_plan", {}),
            "worldview_summary": context_data.get("worldview_summary", ""),
            "previous_chapter_summary": context_data.get("previous_chapter_summary", ""),
            "active_entities": [
                {"name": e.get("name"), "type": e.get("type"), "current_state": e.get("current_state", "")[:200]}
                for e in context_data.get("active_entities", [])
            ],
            "pending_foreshadowings": context_data.get("pending_foreshadowings", []),
            "genre_quality_config": context_data.get("genre_quality_config", {}),
        }
        genre_block = await self._build_genre_review_block(novel_id, context_data)
        if chapter_id:
            template = await self.prompt_registry.get_active_for_chapter("critic", chapter_id)
        else:
            template = await self.prompt_registry.get_active("critic")
        version = await self.prompt_registry.get_active_version_name("critic")
        style_contract_segment = (style_contract + "\n\n") if style_contract else ""
        prompt = render_prompt_template(
            template,
            genre_block=genre_block,
            style_contract=style_contract_segment,
            trimmed_context=json.dumps(trimmed_context, ensure_ascii=False),
            raw_draft=raw_draft,
        )
        score_result = await call_and_parse_model(
            "CriticAgent", "score_chapter", prompt, ScoreResult, novel_id=novel_id
        )
        # Phase 4 / Task 18: plot_tension 爽点扣分 — 拉取本章未验证的
        # 规划预测爽点,每项扣 5 分,最多扣 20 分。
        score_result = await self._apply_thrill_point_plot_tension_adjustment(
            score_result,
            novel_id=novel_id,
            chapter_id=chapter_id,
        )
        # Increment A/B sample count AFTER the thrill point adjustment so the
        # registry records the final, post-penalty score distribution.
        await self.prompt_registry.increment_sample_count("critic", version)
        return score_result

    THRILL_POINT_PENALTY_PER_MISS = 5
    THRILL_POINT_PENALTY_CAP = 20

    async def _apply_thrill_point_plot_tension_adjustment(
        self,
        score_result: ScoreResult,
        *,
        novel_id: str,
        chapter_id: str,
    ) -> ScoreResult:
        """Phase 4 / Task 18: 在 plot_tension 维度扣分未达成的爽点预测。

        - 拉取 ``ThrillPointRepository.list_unverified(novel_id, chapter_id=...)``;
        - 每项未验证的 thrill_type 扣 ``THRILL_POINT_PENALTY_PER_MISS`` 分;
        - 累计扣分上限 ``THRILL_POINT_PENALTY_CAP``;
        - 调整后的 plot_tension 写回 ``DimensionScore.score``;
        - ``overall`` 重新按维度平均;
        - 把扣分明细写入 ``DimensionScore.comment`` 后缀与 ``summary_feedback`` 末尾,
          便于 UI 直接展示。
        """
        if not novel_id or not chapter_id:
            return score_result
        try:
            from novel_dev.repositories.thrill_point_repo import ThrillPointRepository

            repo = ThrillPointRepository(self.session)
            unverified = await repo.list_unverified(novel_id, chapter_id=chapter_id)
        except Exception as exc:  # noqa: BLE001
            log_service.add_log(
                novel_id,
                "CriticAgent",
                f"拉取未验证爽点失败,跳过 plot_tension 调整: {exc}",
                level="warning",
            )
            return score_result
        if not unverified:
            return score_result

        miss_count = len(unverified)
        penalty = min(
            self.THRILL_POINT_PENALTY_PER_MISS * miss_count,
            self.THRILL_POINT_PENALTY_CAP,
        )
        miss_types = sorted({tp.thrill_type for tp in unverified if getattr(tp, "thrill_type", None)})

        adjusted: list[DimensionScore] = []
        for dim in score_result.dimensions:
            if dim.name != "plot_tension":
                adjusted.append(dim)
                continue
            original = dim.score
            new_score = max(0, min(100, original - penalty))
            detail = (
                f"{dim.comment} | plot_tension_adjustment=-{penalty} "
                f"(missing={miss_count}, types={','.join(miss_types) or '-'})"
            ).strip(" |")
            adjusted.append(
                DimensionScore(
                    name=dim.name,
                    score=new_score,
                    comment=detail,
                )
            )
        # The loop above mirrors every original dimension into `adjusted`; if the
        # original score_result contained no plot_tension, the early return above
        # at `if not unverified` already covers the no-op case. No further guard
        # is reachable here.

        # Recompute overall as the simple mean of dimension scores
        new_overall = round(sum(d.score for d in adjusted) / max(1, len(adjusted)))
        new_summary = score_result.summary_feedback
        if penalty > 0:
            new_summary = (
                f"{new_summary}\n\n爽点缺失调整: 未达成爽点 {miss_count} 项 "
                f"({','.join(miss_types) or '-'}), plot_tension 扣 {penalty} 分。"
            ).strip()
        log_agent_detail(
            novel_id,
            "CriticAgent",
            f"plot_tension 爽点扣分: -{penalty} (missing={miss_count})",
            node="plot_tension_thrill_penalty",
            task="score_chapter",
            metadata={
                "chapter_id": chapter_id,
                "missing_thrill_count": miss_count,
                "missing_thrill_types": miss_types,
                "penalty": penalty,
            },
        )
        return ScoreResult(
            overall=new_overall,
            dimensions=adjusted,
            summary_feedback=new_summary,
            per_dim_issues=score_result.per_dim_issues,
        )

    async def _build_genre_review_block(self, novel_id: str, context_data: dict) -> str:
        genre_block = str(context_data.get("genre_prompt_block") or "").strip()
        quality_config = context_data.get("genre_quality_config")
        warnings = context_data.get("genre_template_warnings") or []
        if novel_id:
            genre_template = await GenreTemplateService(self.session).resolve(
                novel_id,
                "CriticAgent",
                "score_chapter",
            )
            resolved_block = genre_template.render_prompt_block(
                "setting_rules",
                "structure_rules",
                "quality_rules",
                "forbidden_rules",
            ).strip()
            if resolved_block:
                genre_block = resolved_block
            quality_config = genre_template.quality_config or quality_config
            warnings = genre_template.warnings or warnings
        if not genre_block and not quality_config:
            return ""
        parts = ["## 类型模板约束"]
        if genre_block:
            parts.append(genre_block)
        if quality_config:
            parts.append("### 类型质量配置\n" + json.dumps(quality_config, ensure_ascii=False))
        if warnings:
            parts.append("### 模板诊断\n" + json.dumps(warnings, ensure_ascii=False))
        return "\n".join(parts) + "\n\n"

    async def review_standalone(
        self,
        novel_id: str,
        chapter_id: str,
        context_data: dict,
    ) -> tuple[ScoreResult, dict]:
        log_service.add_log(novel_id, "CriticAgent", f"开始独立评审章节: {chapter_id}")
        ch = await self.chapter_repo.get_by_id(chapter_id)
        if not ch:
            raise ValueError(f"Chapter not found: {chapter_id}")
        score_result = await self._generate_score(ch.raw_draft or "", context_data, novel_id, chapter_id)
        beat_scores = await self._generate_beat_scores(context_data, novel_id)
        await self.chapter_repo.update_scores(
            chapter_id,
            overall=score_result.overall,
            breakdown={d.name: {"score": d.score, "comment": d.comment} for d in score_result.dimensions},
            feedback={"summary": score_result.summary_feedback},
        )
        checkpoint = {
            "chapter_context": context_data,
            "beat_scores": beat_scores,
            "critique_feedback": {
                "overall": score_result.overall,
                "summary": score_result.summary_feedback,
                "breakdown": {
                    d.name: {"score": d.score, "comment": d.comment}
                    for d in score_result.dimensions
                },
            },
            "per_dim_issues": [issue.model_dump() for issue in score_result.per_dim_issues],
        }
        return score_result, checkpoint

    async def _generate_beat_scores(self, context_data: dict, novel_id: str = "") -> List[dict]:
        log_service.add_log(novel_id, "CriticAgent", "开始生成节拍评分")
        beats = context_data.get("chapter_plan", {}).get("beats", [])
        if not beats:
            return []
        # Only pass what beat-level scoring needs (avoid retrieval bloat)
        trimmed = {
            "chapter_plan": context_data.get("chapter_plan", {}),
            "style_profile": context_data.get("style_profile", {}),
            "worldview_summary": context_data.get("worldview_summary", ""),
            "previous_chapter_summary": context_data.get("previous_chapter_summary", ""),
            "active_entities": [
                {"name": e.get("name"), "type": e.get("type"), "current_state": e.get("current_state", "")[:200]}
                for e in context_data.get("active_entities", [])
            ],
            "pending_foreshadowings": context_data.get("pending_foreshadowings", []),
        }
        prompt = (
            "你是一位小说评审专家。请根据以下节拍列表和章节上下文,"
            "为**每一个节拍**给出 plot_tension 和 humanity 评分(0-100)及具体问题清单。\n\n"
            "## 评价总原则\n"
            "从读者体验出发判断每个节拍:读者是否看得懂目标和阻力,是否相信人物反应,"
            "是否感到场景在推进,以及是否愿意继续读下一节拍。suggestion 写成正向改写目标。\n\n"
            "## 评分 rubric(节拍级)\n"
            "- plot_tension >=85: 本节拍有明确推进(冲突/揭示/决定),并引出下一步不确定性\n"
            "- plot_tension 70-84: 有推进但缺少不确定性或节拍过长稀释张力\n"
            "- plot_tension <70: 无推进/重复前文/场景铺陈过多无事件\n"
            "- humanity >=85: 对话/动作自然,情感通过细节呈现,无 AI 腔\n"
            "- humanity 70-84: 有少量 AI 腔、心理直述、比喻过密或跨语域表达突兀,瑕疵不影响读感\n"
            "- humanity <70: 书面语堆砌、总结式情感、对话扁平、类型概念复读、奇观堆叠或模板化异常事件\n\n"
            "## 输出格式\n"
            "JSON 数组,每元素:\n"
            '{"beat_index": 0, "scores": {"plot_tension": 75, "humanity": 75}, '
            '"issues": [{"dim": "humanity", "problem": "第2句用『油然而生』直述情感", '
            '"suggestion": "改为 A 手指掐进掌心这类动作细节"}]}\n'
            "要求:\n"
            "- scores 低于 75 的维度必须在 issues 中至少给 1 条具体问题(problem 写具体,不要抽象标签)\n"
            "- suggestion 必须可直接执行,并说明下一版应呈现的正向改写目标\n"
            "- 节拍全部达标时 issues 可为空数组\n"
            f"\n章节上下文:\n{json.dumps(trimmed, ensure_ascii=False)}\n\n"
            "请评分:"
        )
        result = await call_and_parse_model(
            "CriticAgent", "score_beats", prompt, list[BeatScorePayload], novel_id=novel_id
        )
        return [item.model_dump() for item in result]
