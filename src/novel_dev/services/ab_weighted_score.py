from __future__ import annotations
from typing import Optional


DEFAULT_WEIGHTS = {"critic": 0.5, "hook": 0.3, "thrill": 0.2}


class WeightedScoreCalculator:
    def __init__(self, weights: Optional[dict] = None):
        self.weights = weights or DEFAULT_WEIGHTS

    def compute(self, critic_mean: float, hook_rate: float, thrill_rate: float) -> float:
        return (
            critic_mean * self.weights["critic"]
            + hook_rate * 100 * self.weights["hook"]
            + thrill_rate * 100 * self.weights["thrill"]
        )

    def compute_batch(self, samples_by_version: dict) -> dict[str, Optional[float]]:
        result = {}
        for version, samples in samples_by_version.items():
            critics = samples.get("critic_scores", [])
            hooks = samples.get("hook_achieved", [])
            thrills = samples.get("thrill_verified", [])
            if not critics:
                result[version] = None
                continue
            critic_mean = sum(critics) / len(critics)
            hook_rate = sum(1 for h in hooks if h) / len(hooks) if hooks else 0.0
            thrill_rate = sum(1 for t in thrills if t) / len(thrills) if thrills else 0.0
            result[version] = self.compute(critic_mean, hook_rate, thrill_rate)
        return result