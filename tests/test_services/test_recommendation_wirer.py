import pytest
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch
from novel_dev.config.quality_config import ConfigError
from novel_dev.services.recommendation_wirer import RecommendationWirer, WireResult
from novel_dev.services.recommendation_service import RecommendationService, RecommendationType
from novel_dev.services.chapter_rewrite_service import ChapterRewriteService


@dataclass
class FakeChapter:
    id: str = "ch_1"
    final_review_score: int = 80
    quality_status: str = "unchecked"
    attempt_index: int = 0
    score_breakdown: dict = None

    def __post_init__(self):
        if self.score_breakdown is None:
            self.score_breakdown = {}


def _chapter_with(quality_status="unchecked", final_review_score=80, attempt_index=0):
    return FakeChapter(
        quality_status=quality_status,
        final_review_score=final_review_score,
        attempt_index=attempt_index,
    )


@pytest.mark.asyncio
async def test_wirer_scaffold_exists(async_session):
    wirer = RecommendationWirer(async_session, max_auto_rewrites=0)
    assert wirer.max_auto_rewrites == 0
    assert WireResult(action="accept", recommendation=None, rewrite_job_id=None)


@pytest.mark.asyncio
async def test_wirer_accept(async_session):
    wirer = RecommendationWirer(async_session, max_auto_rewrites=2)
    with patch.object(wirer.chapter_repo, "get_by_id", new=AsyncMock(return_value=_chapter_with("pass", 85, 0))):
        result = await wirer.evaluate_and_dispatch("novel_1", "ch_1")
    assert result.action == "accept"


@pytest.mark.asyncio
async def test_wirer_minor_within_budget_queues(async_session):
    wirer = RecommendationWirer(async_session, max_auto_rewrites=2)
    ch = _chapter_with("warn", 80, 0)
    with patch.object(wirer.chapter_repo, "get_by_id", new=AsyncMock(return_value=ch)):
        with patch.object(ChapterRewriteService, "rewrite", new=AsyncMock(return_value=None)) as mock_rewrite:
            with patch.object(wirer.job_repo, "get_active", new=AsyncMock(return_value=None)):
                result = await wirer.evaluate_and_dispatch("novel_1", "ch_1")
    assert result.action == "auto_rewrite_queued"
    mock_rewrite.assert_awaited_once()


@pytest.mark.asyncio
async def test_wirer_minor_exceeds_budget_manual(async_session):
    wirer = RecommendationWirer(async_session, max_auto_rewrites=2)
    ch = _chapter_with("warn", 80, 2)
    with patch.object(wirer.chapter_repo, "get_by_id", new=AsyncMock(return_value=ch)):
        result = await wirer.evaluate_and_dispatch("novel_1", "ch_1")
    assert result.action == "manual_review"


@pytest.mark.asyncio
async def test_wirer_stop_and_inspect_always_manual(async_session):
    wirer = RecommendationWirer(async_session, max_auto_rewrites=2)
    ch = _chapter_with("block", 55, 0)
    with patch.object(wirer.chapter_repo, "get_by_id", new=AsyncMock(return_value=ch)):
        result = await wirer.evaluate_and_dispatch("novel_1", "ch_1")
    assert result.action == "manual_review"


@pytest.mark.asyncio
async def test_wirer_attempt_drift_detection(async_session):
    wirer = RecommendationWirer(async_session, max_auto_rewrites=2)
    ch = _chapter_with("warn", 80, 10)
    with patch.object(wirer.chapter_repo, "get_by_id", new=AsyncMock(return_value=ch)):
        result = await wirer.evaluate_and_dispatch("novel_1", "ch_1")
    assert result.action == "manual_review"


@pytest.mark.asyncio
async def test_wirer_respects_configured_max(async_session):
    wirer = RecommendationWirer(async_session, max_auto_rewrites=2)
    ch = type("Chapter", (), {"id": "ch_1", "final_review_score": 80, "quality_status": "warn", "attempt_index": 1, "score_breakdown": {}})()
    with patch.object(wirer.chapter_repo, "get_by_id", new=AsyncMock(return_value=ch)):
        with patch.object(ChapterRewriteService, "rewrite", new=AsyncMock()) as mock_rewrite:
            result = await wirer.evaluate_and_dispatch("novel_1", "ch_1")
    assert result.action == "auto_rewrite_queued"
    mock_rewrite.assert_awaited_once()


@pytest.mark.asyncio
async def test_wirer_raises_config_error_when_key_missing(async_session, monkeypatch):
    def bad_config():
        return {"recommendation": {}}
    monkeypatch.setattr("novel_dev.services.recommendation_wirer.get_quality_config", bad_config)
    with pytest.raises(ConfigError):
        RecommendationWirer(async_session)


@pytest.mark.asyncio
async def test_wirer_chapter_not_found(async_session):
    wirer = RecommendationWirer(async_session, max_auto_rewrites=2)
    with patch.object(wirer.chapter_repo, "get_by_id", new=AsyncMock(return_value=None)):
        result = await wirer.evaluate_and_dispatch("novel_1", "missing_ch")
    assert result.action == "manual_review"
    assert result.recommendation is None
    assert result.rewrite_job_id is None


@pytest.mark.asyncio
async def test_wirer_recommendation_service_exception(async_session):
    wirer = RecommendationWirer(async_session, max_auto_rewrites=2)
    with patch.object(wirer.chapter_repo, "get_by_id", new=AsyncMock(return_value=_chapter_with("warn", 80, 0))):
        with patch(
            "novel_dev.services.recommendation_wirer.RecommendationService.recommend",
            side_effect=RuntimeError("scoring failed"),
        ):
            result = await wirer.evaluate_and_dispatch("novel_1", "ch_1")
    assert result.action == "manual_review"
    assert result.recommendation is None


@pytest.mark.asyncio
async def test_wirer_rewrite_integrity_error_with_active_job(async_session):
    from sqlalchemy.exc import IntegrityError

    wirer = RecommendationWirer(async_session, max_auto_rewrites=2)
    ch = _chapter_with("warn", 80, 0)
    active_job = type("Job", (), {"id": "job_active"})()
    with patch.object(wirer.chapter_repo, "get_by_id", new=AsyncMock(return_value=ch)):
        with patch.object(
            ChapterRewriteService,
            "rewrite",
            new=AsyncMock(side_effect=IntegrityError("insert", {}, None)),
        ):
            with patch.object(wirer.job_repo, "get_active", new=AsyncMock(return_value=active_job)):
                result = await wirer.evaluate_and_dispatch("novel_1", "ch_1")
    assert result.action == "auto_rewrite_queued"
    assert result.rewrite_job_id == "job_active"


@pytest.mark.asyncio
async def test_wirer_rewrite_integrity_error_no_active_job(async_session):
    from sqlalchemy.exc import IntegrityError

    wirer = RecommendationWirer(async_session, max_auto_rewrites=2)
    ch = _chapter_with("warn", 80, 0)
    with patch.object(wirer.chapter_repo, "get_by_id", new=AsyncMock(return_value=ch)):
        with patch.object(
            ChapterRewriteService,
            "rewrite",
            new=AsyncMock(side_effect=IntegrityError("insert", {}, None)),
        ):
            with patch.object(wirer.job_repo, "get_active", new=AsyncMock(return_value=None)):
                result = await wirer.evaluate_and_dispatch("novel_1", "ch_1")
    assert result.action == "manual_review"
    assert result.rewrite_job_id is None


@pytest.mark.asyncio
async def test_wirer_rewrite_generic_exception(async_session):
    wirer = RecommendationWirer(async_session, max_auto_rewrites=2)
    ch = _chapter_with("warn", 80, 0)
    with patch.object(wirer.chapter_repo, "get_by_id", new=AsyncMock(return_value=ch)):
        with patch.object(
            ChapterRewriteService,
            "rewrite",
            new=AsyncMock(side_effect=RuntimeError("db down")),
        ):
            result = await wirer.evaluate_and_dispatch("novel_1", "ch_1")
    assert result.action == "manual_review"
    assert result.rewrite_job_id is None
