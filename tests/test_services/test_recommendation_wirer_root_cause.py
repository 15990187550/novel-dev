import pytest
from unittest.mock import AsyncMock, patch
from novel_dev.services.recommendation_wirer import RecommendationWirer


@pytest.mark.asyncio
async def test_wirer_accept_path_includes_root_cause(async_session):
    wirer = RecommendationWirer(async_session, max_auto_rewrites=2)
    ch = type("Chapter", (), {
        "id": "ch_1", "final_review_score": 90, "quality_status": "pass",
        "attempt_index": 0, "score_breakdown": {},
    })()
    fake_rc = type("RC", (), {
        "summary": "ok",
        "suggested_actions": {"items": []},
        "confidence": 0.9,
        "analyzer_version": "v1.0",
    })()
    with patch.object(wirer.chapter_repo, "get_by_id", new=AsyncMock(return_value=ch)):
        with patch("novel_dev.services.recommendation_wirer.RootCauseRepository") as MockRepo:
            MockRepo.return_value.get_latest_for_chapter = AsyncMock(return_value=fake_rc)
            result = await wirer.evaluate_and_dispatch("n_1", "ch_1")
    assert result.action == "accept"
    assert result.root_cause is not None
    assert result.root_cause.summary == "ok"


@pytest.mark.asyncio
async def test_wirer_root_cause_none_when_no_record(async_session):
    wirer = RecommendationWirer(async_session, max_auto_rewrites=2)
    ch = type("Chapter", (), {
        "id": "ch_1", "final_review_score": 90, "quality_status": "pass",
        "attempt_index": 0, "score_breakdown": {},
    })()
    with patch.object(wirer.chapter_repo, "get_by_id", new=AsyncMock(return_value=ch)):
        with patch("novel_dev.services.recommendation_wirer.RootCauseRepository") as MockRepo:
            MockRepo.return_value.get_latest_for_chapter = AsyncMock(return_value=None)
            result = await wirer.evaluate_and_dispatch("n_1", "ch_1")
    assert result.action == "accept"
    assert result.root_cause is None
