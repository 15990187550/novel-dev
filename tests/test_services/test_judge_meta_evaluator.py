import pytest
from datetime import datetime
from unittest.mock import AsyncMock
from novel_dev.config.ab_judge_config import JudgeConfig
from novel_dev.services.judge_meta_evaluator import JudgeMetaEvaluator, MetaEvalResult


@pytest.mark.asyncio
async def test_returns_insufficient_when_no_data():
    config = JudgeConfig(min_samples=30)
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=AsyncMock(scalars=lambda: AsyncMock(all=lambda: [])))
    evaluator = JudgeMetaEvaluator(mock_session, config)
    result = await evaluator.evaluate("jpv_1")
    assert result.sample_size == 0
    assert result.agreement_rate is None


@pytest.mark.asyncio
async def test_agreement_rate_all_correct():
    """所有 clear-cut 决策,judge 跟 hard metric 一致 → 1.0"""
    config = JudgeConfig(min_samples=1, clear_cut_threshold_pct=5.0, calibration_window_days=14)

    # Mock 2 条决策:hard metric 都说 v2 胜,judge 也说 v2 胜
    class MockDecision:
        def __init__(self, baseline_w, challenger_w, judge_tb_baseline, judge_tb_challenger):
            self.baseline_w = baseline_w
            self.challenger_w = challenger_w
            self.judge_tie_breaker_baseline = judge_tb_baseline
            self.judge_tie_breaker_challenger = judge_tb_challenger

    decisions = [
        MockDecision(75.0, 85.0, 7.0, 8.5),  # hard: v2 胜,judge: v2 胜 → 一致
        MockDecision(70.0, 80.0, 6.5, 8.0),  # hard: v2 胜,judge: v2 胜 → 一致
    ]
    mock_session = AsyncMock()
    mock_result = AsyncMock()
    mock_result.scalars.return_value.all.return_value = decisions
    mock_session.execute = AsyncMock(return_value=mock_result)

    evaluator = JudgeMetaEvaluator(mock_session, config)
    result = await evaluator.evaluate("jpv_1")
    assert result.sample_size == 2
    assert result.agreement_rate == 1.0


@pytest.mark.asyncio
async def test_agreement_rate_partial():
    """3 条决策:2 一致 + 1 不一致 → 0.667"""
    config = JudgeConfig(min_samples=1, clear_cut_threshold_pct=5.0, calibration_window_days=14)

    class MockDecision:
        def __init__(self, baseline_w, challenger_w, jtbb, jtbc):
            self.baseline_w = baseline_w
            self.challenger_w = challenger_w
            self.judge_tie_breaker_baseline = jtbb
            self.judge_tie_breaker_challenger = jtbc

    decisions = [
        MockDecision(75.0, 85.0, 7.0, 8.5),  # 一致
        MockDecision(70.0, 80.0, 6.5, 8.0),  # 一致
        MockDecision(85.0, 75.0, 8.0, 7.0),  # hard v1 胜,judge v1 胜 → 一致(反转也算)
    ]
    # 改第三条:hard 跟 judge 矛盾
    decisions[2] = MockDecision(85.0, 75.0, 7.0, 8.0)  # hard: v1,judge: v2 → 不一致

    mock_session = AsyncMock()
    mock_result = AsyncMock()
    mock_result.scalars.return_value.all.return_value = decisions
    mock_session.execute = AsyncMock(return_value=mock_result)

    evaluator = JudgeMetaEvaluator(mock_session, config)
    result = await evaluator.evaluate("jpv_1")
    assert result.sample_size == 3
    assert abs(result.agreement_rate - (2 / 3)) < 0.01


@pytest.mark.asyncio
async def test_filters_by_clear_cut_threshold():
    """hard gap < 5% 的不计入 clear-cut"""
    config = JudgeConfig(min_samples=1, clear_cut_threshold_pct=5.0, calibration_window_days=14)

    class MockDecision:
        def __init__(self, baseline_w, challenger_w, jtbb, jtbc):
            self.baseline_w = baseline_w
            self.challenger_w = challenger_w
            self.judge_tie_breaker_baseline = jtbb
            self.judge_tie_breaker_challenger = jtbc

    # 4% 差距 - 不到 5%,不算 clear-cut
    decisions = [MockDecision(75.0, 78.0, 7.0, 8.0)]

    mock_session = AsyncMock()
    mock_result = AsyncMock()
    mock_result.scalars.return_value.all.return_value = decisions
    mock_session.execute = AsyncMock(return_value=mock_result)

    evaluator = JudgeMetaEvaluator(mock_session, config)
    result = await evaluator.evaluate("jpv_1")
    # 不算 clear-cut,样本数 0
    assert result.sample_size == 0
