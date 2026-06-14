"""Integration test for RecommendationWirer auto-rewrite dispatch loop."""
import pytest
from unittest.mock import AsyncMock, patch
from novel_dev.services.recommendation_wirer import RecommendationWirer


@pytest.mark.asyncio
async def test_recommendation_wirer_queues_then_manual(async_session):
    wirer = RecommendationWirer(async_session, max_auto_rewrites=2)
    ch = type("Chapter", (), {
        "id": "ch_1", "final_review_score": 80, "quality_status": "warn",
        "attempt_index": 0, "score_breakdown": {},
    })()
    with patch.object(wirer.chapter_repo, "get_by_id", new=AsyncMock(return_value=ch)):
        with patch("novel_dev.services.recommendation_wirer.ChapterRewriteService.rewrite", new=AsyncMock()) as mock_rewrite:
            result = await wirer.evaluate_and_dispatch("novel_1", "ch_1")
    assert result.action == "auto_rewrite_queued"
    assert ch.attempt_index == 1
    assert ch.quality_status == "rewriting"
    mock_rewrite.assert_awaited_once()
