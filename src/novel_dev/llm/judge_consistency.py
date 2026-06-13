# src/novel_dev/llm/judge_consistency.py
"""LLM judge consistency measurement.

Run the same chapter through a critic N times and compute variance.
Useful for calibrating whether a given model is stable enough to use
as a primary quality judge. See spec section 7.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class JudgeConsistencyReport:
    chapter_id: str
    model: str
    n: int
    scores: list
    mean: float
    std_dev: float
    variance_coefficient: float
    dimension_variance: dict = field(default_factory=dict)
    interpretation: str = "stable"


def compute_variance_metrics(scores: list) -> dict:
    n = len(scores)
    if n == 0:
        return {"mean": 0, "std_dev": 0, "variance_coefficient": 0}
    mean = sum(scores) / n
    if mean == 0:
        return {"mean": 0, "std_dev": 0, "variance_coefficient": 0}
    variance = sum((s - mean) ** 2 for s in scores) / n
    std_dev = math.sqrt(variance)
    return {
        "mean": mean,
        "std_dev": std_dev,
        "variance_coefficient": std_dev / mean,
    }


def interpret_cv(cv: float, thresholds: dict) -> str:
    if cv <= thresholds["stable_max_cv"]:
        return "stable"
    if cv <= thresholds["moderate_max_cv"]:
        return "moderate"
    return "unstable"
