import pytest
from novel_dev.services.recommendation_service import (
    RecommendationService,
    Recommendation,
    RecommendationType,
)


def _chapter(score=80, status="warn", breakdown=None, reasons=None, id="ch1"):
    return {
        "id": id,
        "final_review_score": score,
        "score_breakdown": breakdown or {"plot_tension": {"score": 80}},
        "quality_status": status,
        "quality_reasons": reasons or {"blocking_items": [], "warning_items": []},
    }


def test_pass_chapter_yields_accept():
    svc = RecommendationService(
        chapter=_chapter(score=85, status="pass"),
        recent_issue_counts=[],
        current_attempt=0,
    )
    rec = svc.recommend()
    assert rec.recommendation == RecommendationType.ACCEPT
    assert rec.confidence == 1.0


def test_block_chapter_yields_stop_and_inspect():
    svc = RecommendationService(
        chapter=_chapter(score=50, status="block", reasons={
            "blocking_items": ["consistency_fixed=false"],
            "warning_items": [],
        }),
        recent_issue_counts=[("CONSISTENCY_BROKEN", 1)],
        current_attempt=0,
    )
    rec = svc.recommend()
    assert rec.recommendation == RecommendationType.STOP_AND_INSPECT


def test_warn_high_score_with_accept_with_warn_yields_accept():
    svc = RecommendationService(
        chapter=_chapter(score=85, status="warn", breakdown={"plot_tension": {"score": 80}}),
        recent_issue_counts=[],
        current_attempt=0,
    )
    rec = svc.recommend(accept_with_warn=True)
    assert rec.recommendation == RecommendationType.ACCEPT


def test_warn_mid_score_yields_minor_repair():
    svc = RecommendationService(
        chapter=_chapter(score=80, status="warn", breakdown={"plot_tension": {"score": 80}}),
        recent_issue_counts=[],
        current_attempt=0,
    )
    rec = svc.recommend()
    assert rec.recommendation == RecommendationType.MINOR_REPAIR
    assert rec.suggested_actions


def test_warn_low_score_yields_major_repair():
    svc = RecommendationService(
        chapter=_chapter(score=72, status="warn", breakdown={"plot_tension": {"score": 75}}),
        recent_issue_counts=[],
        current_attempt=0,
    )
    rec = svc.recommend()
    assert rec.recommendation == RecommendationType.MAJOR_REPAIR


def test_pattern_failure_yields_stop_and_inspect():
    svc = RecommendationService(
        chapter=_chapter(score=78, status="warn"),
        recent_issue_counts=[("AI_FLAVOR_HIGH", 3)],
        current_attempt=0,
    )
    rec = svc.recommend()
    assert rec.recommendation == RecommendationType.STOP_AND_INSPECT


def test_attempt_cap_forces_stop():
    svc = RecommendationService(
        chapter=_chapter(score=85, status="pass"),
        recent_issue_counts=[],
        current_attempt=3,
    )
    rec = svc.recommend()
    assert rec.recommendation == RecommendationType.STOP_AND_INSPECT