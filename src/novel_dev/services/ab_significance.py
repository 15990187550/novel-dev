from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from scipy import stats

STRICT_THRESHOLDS = {"min_samples": 50, "p_value": 0.05, "min_lift": 0.03}
RELAXED_THRESHOLDS = {"min_samples": 30, "p_value": 0.10, "min_lift": 0.02}


@dataclass
class SignificanceResult:
    is_significant: bool
    p_value: Optional[float]
    effect_size: Optional[float]
    threshold_used: str
    reason: Optional[str] = None


class SignificanceTester:
    def __init__(self, thresholds=None, initial_mode: str = "strict"):
        self.thresholds = thresholds or STRICT_THRESHOLDS
        self.current_mode = initial_mode
        self._unsuccessful_attempts = 0

    def _current_thresholds(self) -> dict:
        return RELAXED_THRESHOLDS if self.current_mode == "relaxed" else self.thresholds

    def test(self, scores_by_version: dict) -> SignificanceResult:
        thresholds = self._current_thresholds()
        versions = list(scores_by_version.keys())
        if len(versions) != 2:
            return SignificanceResult(False, None, None, self.current_mode, "need_exactly_two_versions")

        a_scores = scores_by_version[versions[0]]
        b_scores = scores_by_version[versions[1]]
        min_n = min(len(a_scores), len(b_scores))

        if min_n < thresholds["min_samples"]:
            self._unsuccessful_attempts += 1
            self._maybe_relax()
            return SignificanceResult(False, None, None, self.current_mode, "samples_below_min")

        if len(set(a_scores)) == 1 and len(set(b_scores)) == 1 and a_scores[0] == b_scores[0]:
            self._unsuccessful_attempts += 1
            self._maybe_relax()
            return SignificanceResult(False, None, None, self.current_mode, "zero_variance_identical")

        try:
            t_stat, p_value = stats.ttest_ind(a_scores, b_scores, equal_var=False)
        except Exception:
            self._unsuccessful_attempts += 1
            self._maybe_relax()
            return SignificanceResult(False, None, None, self.current_mode, "t_test_failed")

        a_mean = sum(a_scores) / len(a_scores)
        b_mean = sum(b_scores) / len(b_scores)
        lift = (b_mean - a_mean) / a_mean if a_mean != 0 else 0.0
        effect_size = abs(b_mean - a_mean)

        is_sig = (
            p_value < thresholds["p_value"]
            and abs(lift) >= thresholds["min_lift"]
        )

        if is_sig:
            self._unsuccessful_attempts = 0
        else:
            self._unsuccessful_attempts += 1
            self._maybe_relax()

        return SignificanceResult(is_sig, float(p_value), float(effect_size), self.current_mode)

    def _maybe_relax(self) -> None:
        if self.current_mode == "strict" and self._unsuccessful_attempts >= 3:
            self.current_mode = "relaxed"

    def reset(self) -> None:
        self._unsuccessful_attempts = 0
        self.current_mode = "strict"
