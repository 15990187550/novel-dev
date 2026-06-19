import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from novel_dev.agents.judge_agent import JudgeAgent
from novel_dev.config.ab_judge_config import JudgeConfig
from novel_dev.db.models import JudgePromptVersion, PromptVersion, ABTest
from novel_dev.llm.models import ChatMessage
from novel_dev.services.ab_acceptance_decider import ABAcceptanceDecider


@pytest.mark.asyncio
async def test_accepts_challenger_when_significant(async_session):
    # Setup A/B test
    pv_baseline = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_1", sample_count=50)
    pv_challenger = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_1", sample_count=50)
    ab = ABTest(id="ab_1", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running")
    async_session.add_all([pv_baseline, pv_challenger, ab])
    await async_session.flush()

    decider = ABAcceptanceDecider(async_session)
    # Inject deterministic significant test + score
    decider.significance_tester = MagicMock()
    decider.significance_tester.test = MagicMock(return_value=MagicMock(is_significant=True, p_value=0.03, effect_size=4.0, threshold_used="strict", reason=None))
    decider.weighted_calc = MagicMock()
    decider.weighted_calc.compute_batch = MagicMock(return_value={"v1": 75.0, "v2": 80.0})

    result = await decider.evaluate(experiment_id="ab_1", sample_scores={
        "v1": {"critic_scores": [80.0]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
        "v2": {"critic_scores": [85.0]*50, "hook_achieved": [True]*50, "thrill_verified": [True]*50},
    })
    assert result.action == "accepted"
    assert result.winner == "v2"
    await async_session.refresh(pv_challenger)
    assert pv_challenger.experiment_state == "auto_accepted"
    assert pv_challenger.is_active is True


@pytest.mark.asyncio
async def test_no_action_when_samples_below_min(async_session):
    pv1 = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_1", sample_count=5)
    pv2 = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_1", sample_count=5)
    async_session.add_all([pv1, pv2])
    await async_session.flush()

    decider = ABAcceptanceDecider(async_session)
    result = await decider.evaluate(experiment_id="ab_1", sample_scores={
        "v1": {"critic_scores": [80.0], "hook_achieved": [True], "thrill_verified": [True]},
        "v2": {"critic_scores": [85.0], "hook_achieved": [True], "thrill_verified": [True]},
    })
    assert result.action == "no_action"


@pytest.mark.asyncio
async def test_returns_skipped_on_calculator_failure(async_session):
    pv1 = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_1", sample_count=50)
    pv2 = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_1", sample_count=50)
    ab = ABTest(id="ab_1", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running")
    async_session.add_all([pv1, pv2, ab])
    await async_session.flush()

    decider = ABAcceptanceDecider(async_session)
    decider.weighted_calc = MagicMock()
    decider.weighted_calc.compute_batch = MagicMock(return_value={"v1": None, "v2": None})
    result = await decider.evaluate(experiment_id="ab_1", sample_scores={
        "v1": {"critic_scores": [], "hook_achieved": [], "thrill_verified": []},
        "v2": {"critic_scores": [], "hook_achieved": [], "thrill_verified": []},
    })
    assert result.action == "skipped"


@pytest.mark.asyncio
async def test_evaluate_triggers_judge_on_tie(async_session):
    """硬指标差距 < 1% 触发 judge,tie_breaker challenger 高 → challenger 胜。"""
    pv_baseline = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_1", sample_count=50)
    pv_challenger = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_1", sample_count=50)
    ab = ABTest(id="ab_1", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running")
    jpv = JudgePromptVersion(version="judge-v1", agent_name="judge_agent", prompt_text="{chapter_text}", is_active=True)
    async_session.add_all([pv_baseline, pv_challenger, ab, jpv])
    await async_session.flush()

    # weighted_score 几乎打平:75.1 vs 75.5 → gap 0.4 < 1%
    decider = ABAcceptanceDecider(async_session)
    decider.significance_tester = MagicMock()
    decider.significance_tester.test = MagicMock(return_value=MagicMock(is_significant=False, p_value=0.6, effect_size=0.1, threshold_used="strict", reason="not_significant"))
    decider.weighted_calc = MagicMock()
    decider.weighted_calc.compute_batch = MagicMock(return_value={"v1": 75.1, "v2": 75.5})

    judge_json_baseline = json.dumps({"口吻": 7.0, "叙事连贯": 7.0, "风格调性": 7.0, "理由": "baseline ok"})
    judge_json_challenger = json.dumps({"口吻": 8.5, "叙事连贯": 8.5, "风格调性": 8.5, "理由": "challenger 更紧凑"})
    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        # 第一次调 judge_sample 返回 baseline,第二次返回 challenger
        mock_client.acomplete = AsyncMock(side_effect=[
            ChatMessage(role="assistant", content=judge_json_baseline),
            ChatMessage(role="assistant", content=judge_json_challenger),
        ])
        mock_factory.get.return_value = mock_client
        result = await decider.evaluate(experiment_id="ab_1", sample_scores={
            "v1": {"critic_scores": [80.0]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
            "v2": {"critic_scores": [80.5]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
        })

    assert result.action == "accepted"
    assert result.winner == "v2"
    assert result.judge_triggered is True
    assert result.judge_tie_breaker_challenger > result.judge_tie_breaker_baseline


@pytest.mark.asyncio
async def test_evaluate_skips_judge_on_clear_winner(async_session):
    """硬指标差距 > 1% 不触发 judge,直接走原 Phase 5 路径。"""
    pv_baseline = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_1", sample_count=50)
    pv_challenger = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_1", sample_count=50)
    ab = ABTest(id="ab_1", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running")
    async_session.add_all([pv_baseline, pv_challenger, ab])
    await async_session.flush()

    decider = ABAcceptanceDecider(async_session)
    decider.significance_tester = MagicMock()
    decider.significance_tester.test = MagicMock(return_value=MagicMock(is_significant=True, p_value=0.03, effect_size=4.0, threshold_used="strict", reason=None))
    decider.weighted_calc = MagicMock()
    decider.weighted_calc.compute_batch = MagicMock(return_value={"v1": 75.0, "v2": 85.0})  # 10 分差距

    result = await decider.evaluate(experiment_id="ab_1", sample_scores={
        "v1": {"critic_scores": [80.0]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
        "v2": {"critic_scores": [85.0]*50, "hook_achieved": [True]*50, "thrill_verified": [True]*50},
    })

    assert result.action == "accepted"
    assert result.winner == "v2"
    assert result.judge_triggered is False


@pytest.mark.asyncio
async def test_evaluate_tie_falls_back_to_random_when_judge_fails(async_session):
    """tie 时 judge 解析失败 → tie_random 选 baseline。"""
    pv_baseline = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_1", sample_count=50)
    pv_challenger = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_1", sample_count=50)
    ab = ABTest(id="ab_1", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running")
    jpv = JudgePromptVersion(version="judge-v1", agent_name="judge_agent", prompt_text="{chapter_text}", is_active=True)
    async_session.add_all([pv_baseline, pv_challenger, ab, jpv])
    await async_session.flush()

    decider = ABAcceptanceDecider(async_session)
    decider.significance_tester = MagicMock()
    decider.significance_tester.test = MagicMock(return_value=MagicMock(is_significant=False, p_value=0.6, effect_size=0.1, threshold_used="strict", reason="not_significant"))
    decider.weighted_calc = MagicMock()
    decider.weighted_calc.compute_batch = MagicMock(return_value={"v1": 75.1, "v2": 75.5})

    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(return_value=ChatMessage(role="assistant", content="I cannot judge"))
        mock_factory.get.return_value = mock_client
        result = await decider.evaluate(experiment_id="ab_1", sample_scores={
            "v1": {"critic_scores": [80.0]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
            "v2": {"critic_scores": [80.5]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
        })

    # tie_random 选 baseline
    assert result.action == "accepted"
    assert result.winner == "v1"  # baseline (deterministic via experiment_id hash)
    assert result.judge_triggered is False
    assert result.judge_error == "parse_failed"
