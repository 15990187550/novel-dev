from __future__ import annotations
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.agents.judge_agent import JudgeAgent, JudgeParseError, NoActiveVersionError
from novel_dev.config.ab_judge_config import JudgeConfig, get_ab_judge_config
from novel_dev.db.models import ABTest, PromptVersion
from novel_dev.repositories.ab_decision_repo import ABDecisionRepository
from novel_dev.repositories.judge_call_log_repo import JudgeCallLogRepository
from novel_dev.repositories.judge_prompt_version_repo import JudgePromptVersionRepository
from novel_dev.repositories.prompt_version_repo import PromptVersionRepository
from novel_dev.services.ab_significance import SignificanceTester
from novel_dev.services.ab_weighted_score import WeightedScoreCalculator
from novel_dev.services.ab_decision_recorder import ABDecisionRecorder
from novel_dev.services.judge_cost_guard import JudgeCostGuard
from novel_dev.services.tie_random import tie_random_pick

logger = logging.getLogger(__name__)


@dataclass
class DeciderResult:
    action: str  # "accepted" | "no_action" | "skipped" | "no_improvement" | "error"
    winner: Optional[str] = None
    p_value: Optional[float] = None
    scores: Optional[dict] = None
    reason: Optional[str] = None
    judge_triggered: bool = False
    judge_tie_breaker_baseline: Optional[float] = None
    judge_tie_breaker_challenger: Optional[float] = None
    judge_scores_baseline: Optional[dict] = None
    judge_scores_challenger: Optional[dict] = None
    judge_rationale_baseline: Optional[str] = None
    judge_rationale_challenger: Optional[str] = None
    judge_model: Optional[str] = None
    judge_error: Optional[str] = None


class ABAcceptanceDecider:
    def __init__(self, session: AsyncSession, judge_config: Optional[JudgeConfig] = None):
        self.session = session
        self.weighted_calc = WeightedScoreCalculator()
        self.significance_tester = SignificanceTester()
        self.pv_repo = PromptVersionRepository(session)
        self.decision_repo = ABDecisionRepository(session)
        self.recorder = ABDecisionRecorder(session)
        self.judge_config = judge_config if judge_config is not None else get_ab_judge_config()
        self.call_log_repo = JudgeCallLogRepository(session)
        self.cost_guard = JudgeCostGuard(self.judge_config, self.call_log_repo)

    async def evaluate(
        self, experiment_id: str, sample_scores: dict,
    ) -> DeciderResult:
        ab = await self.session.get(ABTest, experiment_id)
        if not ab or ab.status != "running":
            return DeciderResult(action="no_action", reason="experiment_not_running")

        scores = self.weighted_calc.compute_batch(sample_scores)
        if any(v is None for v in scores.values()):
            await self.recorder.record(
                experiment_id=experiment_id,
                action="evaluate",
                scores=scores,
                meta={"decision": "skipped", "reason": "calculator_returned_none"},
            )
            return DeciderResult(action="skipped", reason="calculator_returned_none")

        versions = [ab.baseline_version, ab.challenger_version]
        scores_by_version_for_test = {
            v: sample_scores.get(v, {}).get("critic_scores", [])
            for v in versions
        }
        significance = self.significance_tester.test(scores_by_version_for_test)

        await self.recorder.record(
            experiment_id=experiment_id,
            action="evaluate",
            scores=scores,
            p_value=significance.p_value,
            effect_size=significance.effect_size,
            meta={
                "decision": "accepted" if significance.is_significant else "no_action",
                "threshold": significance.threshold_used,
                "reason": significance.reason,
            },
        )

        if not significance.is_significant:
            # Phase 6: 检查是否为 tie(硬指标差距 < threshold),如果是则调 judge
            tie_result = await self._try_judge_tie_break(ab, scores, significance)
            if tie_result is not None:
                return tie_result
            return DeciderResult(
                action="no_action",
                p_value=significance.p_value,
                scores=scores,
                reason=significance.reason,
            )

        winner = max(scores, key=scores.get)
        if winner == ab.baseline_version:
            for pv in await self._get_pvs(ab):
                if pv.version == ab.challenger_version:
                    await self.pv_repo.update_experiment_state(pv.id, "no_improvement")
            await self.recorder.record(
                experiment_id=experiment_id,
                action="evaluate",
                scores=scores,
                meta={"decision": "no_improvement", "winner": winner},
            )
            return DeciderResult(action="no_improvement", winner=winner, scores=scores)

        for pv in await self._get_pvs(ab):
            if pv.version == winner:
                await self.pv_repo.update_experiment_state(
                    pv.id, "auto_accepted", last_score=scores[winner],
                    decision_at=datetime.utcnow(),
                )
                pv.is_active = True
                await self.pv_repo.append_history(pv.id, {
                    "action": "auto_accepted",
                    "experiment_id": ab.id,
                    "weighted_score": scores[winner],
                    "p_value": significance.p_value,
                    "at": datetime.utcnow().isoformat(),
                })
            elif pv.version == ab.baseline_version:
                pv.is_active = False
                await self.pv_repo.update_experiment_state(
                    pv.id, "active-rolled-back",
                    decision_at=datetime.utcnow(),
                )
                await self.pv_repo.append_history(pv.id, {
                    "action": "active-rolled-back",
                    "experiment_id": ab.id,
                    "at": datetime.utcnow().isoformat(),
                })

        ab.status = "completed"
        ab.winner = winner
        ab.ended_at = datetime.utcnow()
        await self.session.flush()

        winner_pv = next(pv for pv in await self._get_pvs(ab) if pv.version == winner)
        await self.recorder.record(
            experiment_id=experiment_id,
            action="accept",
            prompt_version_id=winner_pv.id,
            scores=scores,
            p_value=significance.p_value,
            effect_size=significance.effect_size,
            meta={"winner": winner, "monitoring_window_hours": 24},
        )

        return DeciderResult(action="accepted", winner=winner, p_value=significance.p_value, scores=scores)

    async def _get_pvs(self, ab: ABTest) -> list[PromptVersion]:
        result = await self.session.execute(
            select(PromptVersion).where(PromptVersion.ab_test_id == ab.id)
        )
        return list(result.scalars().all())

    async def _try_judge_tie_break(self, ab, scores, significance) -> Optional[DeciderResult]:
        """tie 时调 judge 打破平局;失败则降级到 tie_random。"""
        baseline_score = scores.get(ab.baseline_version, 0.0)
        challenger_score = scores.get(ab.challenger_version, 0.0)
        gap_pct = abs(challenger_score - baseline_score) / max(abs(baseline_score), 1e-6) * 100

        if gap_pct >= self.judge_config.tie_threshold_pct:
            return None  # 不是 tie,交回原路径

        if not self.judge_config.enabled:
            return self._tie_random_decide(ab, scores, "judge_disabled")

        cost_check = await self.cost_guard.check_can_call(ab.id)
        if not cost_check.allow:
            return self._tie_random_decide(ab, scores, cost_check.reason)

        # 粗估 per-decision cost(假设 input=4000, output=400)— 实际 LLM 调用后再精算
        if not self.cost_guard.allow_single_call(input_tokens=4000, output_tokens=400):
            return self._tie_random_decide(ab, scores, "cost_cap")

        # 调 judge
        try:
            judge = JudgeAgent(self.session, self.judge_config)
            # 取最新 1 个 chapter(简化:Phase 6 用 placeholder,judge 只用于框架,真值由 sample_scores 携带)
            # 实际生产:从 chapter_repo 取最近 chapter 内容
            baseline_text = f"chapter:{ab.baseline_version}:placeholder"  # Phase 6 范围:chapter_repo 接入留到 6.1 增强
            challenger_text = f"chapter:{ab.challenger_version}:placeholder"
            baseline_result = await judge.judge_sample(baseline_text, experiment_id=ab.id, decision_id=None)
            challenger_result = await judge.judge_sample(challenger_text, experiment_id=ab.id, decision_id=None)
        except JudgeParseError as exc:
            logger.warning("judge_parse_failed_in_decider", extra={"error": str(exc), "experiment_id": ab.id})
            return self._tie_random_decide(ab, scores, "parse_failed")
        except NoActiveVersionError as exc:
            logger.warning("judge_no_active_version_in_decider", extra={"error": str(exc), "experiment_id": ab.id})
            return self._tie_random_decide(ab, scores, "no_active_version")
        except Exception as exc:
            logger.error("judge_unexpected_error", extra={"error": str(exc), "experiment_id": ab.id})
            return self._tie_random_decide(ab, scores, "llm_error")

        # 决定胜负
        if challenger_result.tie_breaker > baseline_result.tie_breaker:
            winner = ab.challenger_version
        elif baseline_result.tie_breaker > challenger_result.tie_breaker:
            winner = ab.baseline_version
        else:
            # tie_breaker 也平,仍降级
            return self._tie_random_decide(ab, scores, "judge_tie")

        # 写 ab_decisions(扩展字段)
        await self.recorder.record(
            experiment_id=ab.id,
            action="accept",
            scores=scores,
            p_value=significance.p_value,
            effect_size=significance.effect_size,
            meta={
                "decision": "accepted_via_judge",
                "winner": winner,
                "judge_scores_baseline": baseline_result.scores,
                "judge_scores_challenger": challenger_result.scores,
                "judge_tie_breaker_baseline": baseline_result.tie_breaker,
                "judge_tie_breaker_challenger": challenger_result.tie_breaker,
                "judge_rationale_baseline": baseline_result.rationale,
                "judge_rationale_challenger": challenger_result.rationale,
                "judge_model": baseline_result.model,
                "judge_triggered": True,
            },
        )

        # 写 ab_decisions 的 judge 列(直接通过 SQLAlchemy session)
        from novel_dev.db.models import ABDecision as ABDecisionModel
        d = ABDecisionModel(
            experiment_id=ab.id,
            action="accept",
            decision_at=datetime.utcnow(),
            scores=scores,
            p_value=significance.p_value,
            effect_size=significance.effect_size,
            meta={"decision": "accepted_via_judge", "winner": winner},
            judge_triggered=True,
            judge_tie_breaker_baseline=baseline_result.tie_breaker,
            judge_tie_breaker_challenger=challenger_result.tie_breaker,
            judge_scores_baseline=baseline_result.scores,
            judge_scores_challenger=challenger_result.scores,
            judge_rationale_baseline=baseline_result.rationale,
            judge_rationale_challenger=challenger_result.rationale,
            judge_model=baseline_result.model,
        )
        self.session.add(d)

        # 标记 pv 状态
        for pv in await self._get_pvs(ab):
            if pv.version == winner:
                await self.pv_repo.update_experiment_state(pv.id, "auto_accepted", last_score=scores[winner], decision_at=datetime.utcnow())
                pv.is_active = True
            else:
                pv.is_active = False
                await self.pv_repo.update_experiment_state(pv.id, "active-rolled-back", decision_at=datetime.utcnow())

        ab.status = "completed"
        ab.winner = winner
        ab.ended_at = datetime.utcnow()
        await self.session.flush()

        return DeciderResult(
            action="accepted",
            winner=winner,
            p_value=significance.p_value,
            scores=scores,
            reason="judge_tie_break",
            judge_triggered=True,
            judge_tie_breaker_baseline=baseline_result.tie_breaker,
            judge_tie_breaker_challenger=challenger_result.tie_breaker,
            judge_scores_baseline=baseline_result.scores,
            judge_scores_challenger=challenger_result.scores,
            judge_rationale_baseline=baseline_result.rationale,
            judge_rationale_challenger=challenger_result.rationale,
            judge_model=baseline_result.model,
        )

    def _tie_random_decide(self, ab, scores, error_reason) -> DeciderResult:
        """tie 且 judge 失败时的降级:deterministic random 选一个。"""
        winner = tie_random_pick(ab.id, [ab.baseline_version, ab.challenger_version])
        logger.info("tie_random_decide", extra={"experiment_id": ab.id, "winner": winner, "reason": error_reason})
        return DeciderResult(
            action="accepted",  # 仍算作"决策"而非 no_action
            winner=winner,
            scores=scores,
            reason=f"tie_random:{error_reason}",
            judge_triggered=False,
            judge_error=error_reason,
        )
