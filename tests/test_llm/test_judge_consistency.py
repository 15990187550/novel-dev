# tests/test_llm/test_judge_consistency.py
import pytest
from novel_dev.llm.judge_consistency import (
    compute_variance_metrics,
    interpret_cv,
    JudgeConsistencyReport,
)


def test_compute_variance_metrics_identical():
    m = compute_variance_metrics([80, 80, 80])
    assert m["mean"] == 80
    assert m["std_dev"] == 0
    assert m["variance_coefficient"] == 0


def test_compute_variance_metrics_spread():
    m = compute_variance_metrics([70, 80, 90])
    assert m["mean"] == 80
    assert m["std_dev"] > 0
    assert m["variance_coefficient"] > 0


def test_compute_variance_metrics_empty():
    m = compute_variance_metrics([])
    assert m == {"mean": 0, "std_dev": 0, "variance_coefficient": 0}


def test_compute_variance_metrics_all_zeros():
    m = compute_variance_metrics([0, 0, 0])
    assert m["mean"] == 0
    assert m["variance_coefficient"] == 0


def test_interpret_cv_thresholds():
    assert interpret_cv(0.02, {"stable_max_cv": 0.05, "moderate_max_cv": 0.10}) == "stable"
    assert interpret_cv(0.08, {"stable_max_cv": 0.05, "moderate_max_cv": 0.10}) == "moderate"
    assert interpret_cv(0.20, {"stable_max_cv": 0.05, "moderate_max_cv": 0.10}) == "unstable"


def test_empty_scores_dataclass():
    report = JudgeConsistencyReport(
        chapter_id="ch1", model="x", n=0, scores=[], mean=0,
        std_dev=0, variance_coefficient=0, dimension_variance={},
        interpretation="stable",
    )
    assert report.interpretation == "stable"
    assert report.scores == []
