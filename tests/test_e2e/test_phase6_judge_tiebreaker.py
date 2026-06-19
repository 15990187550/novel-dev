import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from novel_dev.db.models import (
    PromptVersion, ABTest, JudgePromptVersion, JudgeCallLog, ABDecision,
)
from novel_dev.services.ab_acceptance_decider import ABAcceptanceDecider
from novel_dev.config.ab_judge_config import JudgeConfig
from novel_dev.llm.models import ChatMessage


def _judge_llm_response(scores_dict):
    return ChatMessage(role="assistant", content=json.dumps({**scores_dict, "理由": "ok"}))


@pytest.mark.asyncio
async def test_e2e_happy_path_tie_triggers_judge_challenger_wins(async_session):
    """场景 1: tie → judge 给出 challenger 更高分 → challenger 胜。"""
    pv_b = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_e1", sample_count=50)
    pv_c = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_e1", sample_count=50)
    ab = ABTest(id="ab_e1", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running")
    jpv = JudgePromptVersion(version="judge-v1", agent_name="judge_agent", prompt_text="{chapter_text}", is_active=True)
    async_session.add_all([pv_b, pv_c, ab, jpv])
    await async_session.flush()

    decider = ABAcceptanceDecider(async_session, judge_config=JudgeConfig())
    decider.significance_tester = MagicMock()
    decider.significance_tester.test = MagicMock(return_value=MagicMock(is_significant=False, p_value=0.6, effect_size=0.1, threshold_used="strict", reason="not_significant"))
    decider.weighted_calc = MagicMock()
    decider.weighted_calc.compute_batch = MagicMock(return_value={"v1": 75.1, "v2": 75.5})  # 0.4% gap, tie

    judge_responses = iter([
        _judge_llm_response({"口吻": 7.0, "叙事连贯": 7.5, "风格调性": 7.5}),  # baseline
        _judge_llm_response({"口吻": 8.0, "叙事连贯": 8.5, "风格调性": 8.0}),  # challenger
    ])
    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(side_effect=lambda *a, **k: next(judge_responses))
        mock_factory.get.return_value = mock_client
        result = await decider.evaluate(experiment_id="ab_e1", sample_scores={
            "v1": {"critic_scores": [80.0]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
            "v2": {"critic_scores": [80.5]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
        })

    assert result.action == "accepted"
    assert result.winner == "v2"
    assert result.judge_triggered is True
    assert result.judge_tie_breaker_challenger > result.judge_tie_breaker_baseline

    from sqlalchemy import select
    decisions = (await async_session.execute(
        select(ABDecision).where(ABDecision.experiment_id == "ab_e1")
    )).scalars().all()
    judge_decisions = [d for d in decisions if d.judge_triggered]
    assert len(judge_decisions) >= 1
    assert judge_decisions[0].judge_tie_breaker_challenger > 7.5

    call_logs = (await async_session.execute(
        select(JudgeCallLog).where(JudgeCallLog.experiment_id == "ab_e1")
    )).scalars().all()
    assert len(call_logs) == 2


@pytest.mark.asyncio
async def test_e2e_clear_winner_skips_judge(async_session):
    """场景 2: 硬指标差距 > 1% → judge 不调,走原 Phase 5 路径。"""
    pv_b = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_e2", sample_count=50)
    pv_c = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_e2", sample_count=50)
    ab = ABTest(id="ab_e2", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running")
    jpv = JudgePromptVersion(version="judge-v1", agent_name="judge_agent", prompt_text="{chapter_text}", is_active=True)
    async_session.add_all([pv_b, pv_c, ab, jpv])
    await async_session.flush()

    decider = ABAcceptanceDecider(async_session, judge_config=JudgeConfig())
    decider.significance_tester = MagicMock()
    decider.significance_tester.test = MagicMock(return_value=MagicMock(is_significant=True, p_value=0.03, effect_size=4.0, threshold_used="strict", reason=None))
    decider.weighted_calc = MagicMock()
    decider.weighted_calc.compute_batch = MagicMock(return_value={"v1": 75.0, "v2": 85.0})  # 13% gap

    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(side_effect=AssertionError("judge should not be called"))
        mock_factory.get.return_value = mock_client
        result = await decider.evaluate(experiment_id="ab_e2", sample_scores={
            "v1": {"critic_scores": [80.0]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
            "v2": {"critic_scores": [85.0]*50, "hook_achieved": [True]*50, "thrill_verified": [True]*50},
        })

    assert result.action == "accepted"
    assert result.winner == "v2"
    assert result.judge_triggered is False


@pytest.mark.asyncio
async def test_e2e_judge_parse_failed_degrades_to_random(async_session):
    """场景 3: judge 解析失败 → tie_random 选 winner,记录 judge_error=parse_failed。"""
    pv_b = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_e3", sample_count=50)
    pv_c = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_e3", sample_count=50)
    ab = ABTest(id="ab_e3", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running")
    jpv = JudgePromptVersion(version="judge-v1", agent_name="judge_agent", prompt_text="{chapter_text}", is_active=True)
    async_session.add_all([pv_b, pv_c, ab, jpv])
    await async_session.flush()

    decider = ABAcceptanceDecider(async_session, judge_config=JudgeConfig())
    decider.significance_tester = MagicMock()
    decider.significance_tester.test = MagicMock(return_value=MagicMock(is_significant=False, p_value=0.6, effect_size=0.1, threshold_used="strict", reason="not_significant"))
    decider.weighted_calc = MagicMock()
    decider.weighted_calc.compute_batch = MagicMock(return_value={"v1": 75.1, "v2": 75.5})

    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(return_value=ChatMessage(role="assistant", content="无法打分"))
        mock_factory.get.return_value = mock_client
        result = await decider.evaluate(experiment_id="ab_e3", sample_scores={
            "v1": {"critic_scores": [80.0]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
            "v2": {"critic_scores": [80.5]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
        })

    from novel_dev.services.tie_random import tie_random_pick
    expected_winner = tie_random_pick("ab_e3", ["v1", "v2"])
    assert result.winner == expected_winner
    assert result.judge_triggered is False
    assert result.judge_error == "parse_failed"


@pytest.mark.asyncio
async def test_e2e_cost_cap_blocks_judge(async_session):
    """场景 4: experiment cost 已超 cap → judge 不调,降级到 tie_random。"""
    pv_b = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_e4", sample_count=50)
    pv_c = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_e4", sample_count=50)
    ab = ABTest(id="ab_e4", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running")
    jpv = JudgePromptVersion(version="judge-v1", agent_name="judge_agent", prompt_text="{chapter_text}", is_active=True)
    async_session.add_all([pv_b, pv_c, ab, jpv])
    await async_session.flush()
    # jpv.id populated now — create log after flush
    log = JudgeCallLog(experiment_id="ab_e4", prompt_version_id=jpv.id, model="m",
                       input_tokens=100, output_tokens=10, latency_ms=100, cost_usd=0.60)
    async_session.add(log)
    await async_session.flush()

    decider = ABAcceptanceDecider(async_session, judge_config=JudgeConfig(max_cost_per_experiment_usd=0.50))
    decider.significance_tester = MagicMock()
    decider.significance_tester.test = MagicMock(return_value=MagicMock(is_significant=False, p_value=0.6, effect_size=0.1, threshold_used="strict", reason="not_significant"))
    decider.weighted_calc = MagicMock()
    decider.weighted_calc.compute_batch = MagicMock(return_value={"v1": 75.1, "v2": 75.5})

    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(side_effect=AssertionError("judge should not be called"))
        mock_factory.get.return_value = mock_client
        result = await decider.evaluate(experiment_id="ab_e4", sample_scores={
            "v1": {"critic_scores": [80.0]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
            "v2": {"critic_scores": [80.5]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
        })

    assert result.judge_triggered is False
    assert result.judge_error == "experiment_cost_cap"


@pytest.mark.asyncio
async def test_e2e_meta_eval_agreement_rate_computation(async_session):
    """场景 5: meta-eval 计算 judge vs hard metric 在 clear-cut 上的一致率。"""
    from novel_dev.services.judge_meta_evaluator import JudgeMetaEvaluator

    jpv = JudgePromptVersion(id="jpv_meta", version="v1", agent_name="judge_agent", prompt_text="x", is_active=True)
    async_session.add(jpv)
    await async_session.flush()

    decisions_data = [
        ABDecision(experiment_id="ab_meta_1", action="evaluate", decision_at=datetime.utcnow(),
                   scores={"baseline": 75.0, "challenger": 85.0}, judge_triggered=True,
                   judge_tie_breaker_baseline=7.0, judge_tie_breaker_challenger=8.5,
                   judge_model="claude-sonnet-4-6"),
        ABDecision(experiment_id="ab_meta_2", action="evaluate", decision_at=datetime.utcnow(),
                   scores={"baseline": 70.0, "challenger": 80.0}, judge_triggered=True,
                   judge_tie_breaker_baseline=6.5, judge_tie_breaker_challenger=8.0,
                   judge_model="claude-sonnet-4-6"),
        ABDecision(experiment_id="ab_meta_3", action="evaluate", decision_at=datetime.utcnow(),
                   scores={"baseline": 85.0, "challenger": 75.0}, judge_triggered=True,
                   judge_tie_breaker_baseline=7.0, judge_tie_breaker_challenger=8.0,
                   judge_model="claude-sonnet-4-6"),
    ]
    for d in decisions_data:
        async_session.add(d)
    await async_session.flush()

    config = JudgeConfig(min_samples=1, clear_cut_threshold_pct=5.0, calibration_window_days=14)
    evaluator = JudgeMetaEvaluator(async_session, config)
    result = await evaluator.evaluate("jpv_meta")

    assert result.sample_size == 3
    assert abs(result.agreement_rate - 2 / 3) < 0.01
