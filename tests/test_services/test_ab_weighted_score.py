import pytest
from novel_dev.services.ab_weighted_score import WeightedScoreCalculator


def test_default_weights_compute_correctly():
    calc = WeightedScoreCalculator()
    score = calc.compute(critic_mean=80.0, hook_rate=0.5, thrill_rate=0.3)
    # 80 * 0.5 + 50 * 0.3 + 30 * 0.2 = 40 + 15 + 6 = 61
    assert score == pytest.approx(61.0)


def test_custom_weights():
    calc = WeightedScoreCalculator(weights={"critic": 0.7, "hook": 0.2, "thrill": 0.1})
    score = calc.compute(critic_mean=90.0, hook_rate=0.5, thrill_rate=0.5)
    # 90 * 0.7 + 50 * 0.2 + 50 * 0.1 = 63 + 10 + 5 = 78
    assert score == pytest.approx(78.0)


def test_compute_batch_returns_per_version():
    calc = WeightedScoreCalculator()
    samples = {
        "v1": {"critic_scores": [80, 82], "hook_achieved": [True, False], "thrill_verified": [True, True]},
        "v2": {"critic_scores": [78, 79], "hook_achieved": [True, True], "thrill_verified": [False, True]},
    }
    scores = calc.compute_batch(samples)
    # v1: critic=81, hook=0.5, thrill=1.0 → 81*0.5 + 50*0.3 + 100*0.2 = 40.5+15+20=75.5
    # v2: critic=78.5, hook=1.0, thrill=0.5 → 78.5*0.5 + 100*0.3 + 50*0.2 = 39.25+30+10=79.25
    assert scores["v1"] == pytest.approx(75.5)
    assert scores["v2"] == pytest.approx(79.25)


def test_returns_none_for_empty_samples():
    calc = WeightedScoreCalculator()
    scores = calc.compute_batch({"v1": {"critic_scores": [], "hook_achieved": [], "thrill_verified": []}})
    assert scores["v1"] is None