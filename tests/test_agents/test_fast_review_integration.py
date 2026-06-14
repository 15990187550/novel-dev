import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from novel_dev.agents.fast_review_agent import FastReviewAgent
from novel_dev.services.recommendation_wirer import WireResult


def test_fast_review_has_run_recommendation_wirer_method():
    """Verify the helper method exists (TDD green phase)."""
    agent = FastReviewAgent(MagicMock())
    assert hasattr(agent, "_run_recommendation_wirer")


@pytest.mark.asyncio
async def test_fast_review_calls_recommendation_wirer(async_session):
    agent = FastReviewAgent(async_session)
    with patch.object(agent, "_finalize_and_record_metric", new=AsyncMock()):
        with patch.object(agent.chapter_repo, "update_quality_gate", new=AsyncMock()):
            with patch.object(agent.director, "save_checkpoint", new=AsyncMock()):
                # Patch the deferred import inside the method
                with patch("novel_dev.services.recommendation_wirer.RecommendationWirer") as MockWirer:
                    instance = MockWirer.return_value
                    instance.evaluate_and_dispatch = AsyncMock(
                        return_value=WireResult(action="accept", recommendation=None, rewrite_job_id=None)
                    )
                    await agent._run_recommendation_wirer("novel_1", "ch_1")
                    instance.evaluate_and_dispatch.assert_awaited_once_with("novel_1", "ch_1")