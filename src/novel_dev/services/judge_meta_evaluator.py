from __future__ import annotations
import inspect
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Protocol

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.config.ab_judge_config import JudgeConfig
from novel_dev.db.models import ABDecision


@dataclass
class MetaEvalResult:
    version_id: str
    sample_size: int
    agreement_rate: Optional[float]
    window_start: datetime
    insufficient_data: bool = False


class JudgeMetaEvaluator:
    def __init__(self, session: AsyncSession, config: JudgeConfig):
        self.session = session
        self.config = config

    async def evaluate(self, judge_version_id: str) -> MetaEvalResult:
        window_start = datetime.utcnow() - timedelta(days=self.config.calibration_window_days)

        # 拉最近 N 天的 ab_decisions,带 judge_tie_breaker_* 字段
        # clear-cut 阈值:hard metric 差距 > 5%
        # 注:Phase 5 ab_decisions 暂没存 baseline_weighted / challenger_weighted 数值列,
        # 这里用 scores 字典里的值近似(weighted_score = scores[version])
        result = await self.session.execute(
            select(ABDecision)
            .where(ABDecision.decision_at >= window_start)
            .where(ABDecision.judge_triggered.is_(True))
            .order_by(ABDecision.decision_at.desc())
        )
        scalars_result = result.scalars()
        if inspect.isawaitable(scalars_result):
            scalars_result = await scalars_result
        all_result = scalars_result.all()
        if inspect.isawaitable(all_result):
            all_result = await all_result
        decisions = list(all_result)

        clear_cut = []
        for d in decisions:
            if d.judge_tie_breaker_baseline is None or d.judge_tie_breaker_challenger is None:
                continue
            scores = getattr(d, "scores", None) or {}
            baseline_w = scores.get("baseline")
            challenger_w = scores.get("challenger")
            if baseline_w is None or challenger_w is None:
                # 回退:从直接属性读取(测试 mock 结构)
                if hasattr(d, "baseline_w") and hasattr(d, "challenger_w"):
                    baseline_w = d.baseline_w
                    challenger_w = d.challenger_w
                else:
                    continue
            if abs(baseline_w) < 1e-6:
                continue
            gap_pct = abs(challenger_w - baseline_w) / abs(baseline_w) * 100
            if gap_pct > self.config.clear_cut_threshold_pct:
                clear_cut.append((d, baseline_w, challenger_w))

        sample_size = len(clear_cut)
        if sample_size < self.config.min_samples:
            return MetaEvalResult(
                version_id=judge_version_id,
                sample_size=sample_size,
                agreement_rate=None,
                window_start=window_start,
                insufficient_data=True,
            )

        agreements = 0
        for d, baseline_w, challenger_w in clear_cut:
            hard_winner_is_challenger = challenger_w > baseline_w
            judge_winner_is_challenger = d.judge_tie_breaker_challenger > d.judge_tie_breaker_baseline
            if hard_winner_is_challenger == judge_winner_is_challenger:
                agreements += 1

        rate = agreements / sample_size
        return MetaEvalResult(
            version_id=judge_version_id,
            sample_size=sample_size,
            agreement_rate=rate,
            window_start=window_start,
        )
