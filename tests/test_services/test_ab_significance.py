import pytest
from novel_dev.services.ab_significance import SignificanceTester, STRICT_THRESHOLDS, RELAXED_THRESHOLDS


def test_returns_not_significant_when_samples_below_min():
    tester = SignificanceTester()
    result = tester.test({"v1": [80.0] * 10, "v2": [82.0] * 10})
    assert result.is_significant is False
    assert result.threshold_used == "strict"


def test_strict_threshold_significant_with_clear_lift():
    tester = SignificanceTester()
    result = tester.test(
        {"v1": [75.0] * 50, "v2": [85.0] * 50}
    )
    assert result.is_significant is True
    assert result.p_value < 0.05


def test_relaxes_after_three_unsuccessful_attempts():
    tester = SignificanceTester(initial_mode="strict")
    # First 3 calls return not-significant
    for _ in range(3):
        tester.test({"v1": [80.0] * 10, "v2": [80.5] * 10})
    # Now mode should be relaxed
    assert tester.current_mode == "relaxed"


def test_strict_threshold_blocks_on_min_samples():
    tester = SignificanceTester(thresholds=STRICT_THRESHOLDS)
    result = tester.test({"v1": [80.0] * 49, "v2": [85.0] * 49})
    assert result.is_significant is False
    assert "samples_below_min" in (result.reason or "")


def test_zero_variance_returns_not_significant():
    tester = SignificanceTester()
    result = tester.test({"v1": [80.0] * 50, "v2": [80.0] * 50})
    assert result.is_significant is False
