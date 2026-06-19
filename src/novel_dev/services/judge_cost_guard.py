from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Protocol

from novel_dev.config.ab_judge_config import JudgeConfig


class CallLogRepoProtocol(Protocol):
    async def sum_cost_for_experiment(self, experiment_id: str) -> float: ...


@dataclass
class CostCheckResult:
    allow: bool
    reason: str = ""
    current: float = 0.0


class JudgeCostGuard:
    # Sonnet 级模型定价(input $3/1M, output $15/1M)
    PRICE_INPUT_PER_TOKEN = 3.0 / 1_000_000
    PRICE_OUTPUT_PER_TOKEN = 15.0 / 1_000_000

    def __init__(self, config: JudgeConfig, call_log_repo: CallLogRepoProtocol):
        self.config = config
        self.call_log = call_log_repo

    async def check_can_call(self, experiment_id: str) -> CostCheckResult:
        if not self.config.enabled:
            return CostCheckResult(allow=False, reason="judge_disabled")

        current = await self.call_log.sum_cost_for_experiment(experiment_id)
        if current >= self.config.max_cost_per_experiment_usd:
            return CostCheckResult(allow=False, reason="experiment_cost_cap", current=current)

        return CostCheckResult(allow=True, current=current)

    def estimate_call_cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.PRICE_INPUT_PER_TOKEN
            + output_tokens * self.PRICE_OUTPUT_PER_TOKEN
        )

    def allow_single_call(self, input_tokens: int, output_tokens: int) -> bool:
        cost = self.estimate_call_cost(input_tokens, output_tokens)
        return cost < self.config.max_cost_per_decision_usd
