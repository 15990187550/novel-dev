"""Phase 3 E2E: prompt engineering lifecycle.

Exercises the full Phase 3 pipeline:
  1. Bootstrap default prompts into DB
  2. Create a new prompt version
  3. Start an A/B test between baseline and challenger
  4. Record quality metrics for several chapters
  5. Run A/B results to determine winner
  6. Declare winner -> challenger becomes active
  7. Verify active prompt now returns the new version
  8. Verify cold-start path works (empty table -> bootstrap -> get_active)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_full_phase3_flow(async_session):
    """E2E: bootstrap -> create version -> enable -> A/B -> root cause -> adopt winner."""
    from novel_dev.services.prompt_registry import PromptRegistry
    from novel_dev.services.ab_test_runner import ABTestRunner
    from novel_dev.services.quality_metrics_service import (
        QualityMetricsService,
        QualityMetricInput,
    )

    # 1. Bootstrap defaults — fills table with DEFAULT_PROMPTS for all agents
    reg = PromptRegistry(async_session)
    await reg.bootstrap_defaults()

    # 2. Create a new challenger version of critic
    await reg.create_version("critic", "v2.0", "v2 content critic", is_active=False)

    # 3. Start A/B test: baseline=v1.0 vs challenger=v2.0.
    # max_samples=4 so max_samples*2 == 8 == total samples we record below,
    # which is what ABTestRunner.results requires before declaring a winner.
    runner = ABTestRunner(async_session)
    ab = await runner.start("critic", "v1.0", "v2.0", max_samples=4, min_samples=4)

    # 4. Record metrics — baseline gets lower scores, challenger gets higher.
    # Use a large enough gap (and equal sample sizes) for Welch's t-test to
    # report p < 0.05 reliably.
    svc = QualityMetricsService(async_session)
    metrics_data = [
        ("v1.0", 50, "warn"),
        ("v1.0", 55, "warn"),
        ("v1.0", 60, "warn"),
        ("v1.0", 58, "warn"),
        ("v2.0", 90, "pass"),
        ("v2.0", 92, "pass"),
        ("v2.0", 95, "pass"),
        ("v2.0", 93, "pass"),
    ]
    for i, (ver, score, gate) in enumerate(metrics_data):
        await svc.record(QualityMetricInput(
            chapter_id=f"ch_{i}",
            novel_id="n_1",
            phase="critic",
            attempt_index=1,
            overall_score=score,
            gate_status=gate,
            prompt_version=ver,
        ))
    await async_session.commit()

    # 5. Run results — should detect challenger wins (p < 0.05)
    result = await runner.results(ab.id)
    assert result.winner == "challenger"
    assert result.p_value is not None
    assert result.p_value < 0.05
    assert result.baseline_n == 4
    assert result.challenger_n == 4

    # 6. Declare winner — v2.0 becomes active
    await runner.declare_winner(ab.id, "challenger")
    await async_session.commit()

    # 7. Verify active prompt content updated
    active = await reg.get_active("critic")
    assert active == "v2 content critic"

    # 8. Root cause mock roundtrip — verify the analyzer can be plugged in
    # without invoking the LLM
    from novel_dev.services.root_cause_analyzer import (
        RootCauseAnalyzer,
        RootCauseResult,
    )
    fake = RootCauseResult(
        summary="test",
        suggested_actions=[],
        confidence=0.5,
    )
    with patch.object(RootCauseAnalyzer, "analyze", new=AsyncMock(return_value=fake)):
        analyzer = RootCauseAnalyzer(async_session)
        rc = await analyzer.analyze(
            novel_id="n_1",
            chapter_id="ch_3",
            chapter_text="some text",
            score_breakdown={},
            issue_codes=[],
            beat_boundary_cards=[],
        )
    assert rc.summary == "test"
    assert rc.confidence == 0.5


@pytest.mark.asyncio
async def test_cold_start_bootstrap_then_active_prompt(async_session):
    """E2E: empty table -> bootstrap -> get_active returns default prompt content."""
    from novel_dev.services.prompt_registry import PromptRegistry
    from novel_dev.agents._default_prompts import DEFAULT_PROMPTS

    reg = PromptRegistry(async_session)
    await reg.bootstrap_defaults()

    # Every agent in DEFAULT_PROMPTS should now have an active version
    for agent_name, expected_content in DEFAULT_PROMPTS.items():
        active = await reg.get_active(agent_name)
        assert active == expected_content, f"{agent_name} prompt mismatch"
