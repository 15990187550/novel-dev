import pytest

from novel_dev.services.volume_plan_guard_service import (
    ensure_volume_plan_accepted,
    evaluate_volume_plan_readiness,
)


def test_volume_plan_readiness_blocks_quality_preflight_block_even_when_accepted():
    readiness = evaluate_volume_plan_readiness(
        {
            "current_volume_plan": {
                "review_status": {
                    "status": "accepted",
                    "quality_preflight_status": {
                        "status": "block",
                        "blocked_chapter_numbers": [1],
                    },
                }
            }
        }
    )

    assert readiness.accepted is False
    assert "quality_preflight_status=block" in readiness.message


def test_volume_plan_readiness_manual_override_requires_preflight_not_blocked():
    readiness = evaluate_volume_plan_readiness(
        {
            "acceptance_scope": "real-longform-volume1",
            "current_volume_plan": {
                "review_status": {
                    "status": "needs_manual_review",
                    "writability_status": {"passed": True},
                    "manual_generation_override": {"approved": True, "reason": "acceptance test"},
                    "quality_preflight_status": {"status": "block"},
                }
            },
        }
    )

    assert readiness.accepted is False


def test_volume_plan_readiness_needs_manual_review_requires_explicit_override():
    readiness = evaluate_volume_plan_readiness(
        {
            "acceptance_scope": "real-longform-volume1",
            "current_volume_plan": {
                "review_status": {
                    "status": "needs_manual_review",
                    "writability_status": {"passed": True},
                    "quality_preflight_status": {"status": "warn"},
                }
            },
        }
    )

    assert readiness.accepted is False
    assert "manual_generation_override=missing" in readiness.message


def test_volume_plan_readiness_allows_needs_manual_review_with_explicit_override():
    readiness = evaluate_volume_plan_readiness(
        {
            "current_volume_plan": {
                "review_status": {
                    "status": "needs_manual_review",
                    "writability_status": {"passed": True},
                    "manual_generation_override": {"approved": True, "reason": "human accepted risk"},
                    "quality_preflight_status": {"status": "warn"},
                }
            },
        }
    )

    assert readiness.accepted is True


def test_volume_plan_readiness_needs_manual_review_requires_preflight_result():
    readiness = evaluate_volume_plan_readiness(
        {
            "current_volume_plan": {
                "review_status": {
                    "status": "needs_manual_review",
                    "writability_status": {"passed": True},
                    "manual_generation_override": {"approved": True, "reason": "human accepted risk"},
                }
            },
        }
    )

    assert readiness.accepted is False
    assert "quality_preflight_status=missing" in readiness.message


def test_ensure_volume_plan_accepted_allows_preflight_warn():
    ensure_volume_plan_accepted(
        {
            "current_volume_plan": {
                "review_status": {
                    "status": "accepted",
                    "quality_preflight_status": {"status": "warn"},
                }
            }
        }
    )


def test_ensure_volume_plan_accepted_raises_on_preflight_block():
    with pytest.raises(ValueError, match="quality_preflight_status=block"):
        ensure_volume_plan_accepted(
            {
                "current_volume_plan": {
                    "review_status": {
                        "status": "accepted",
                        "quality_preflight_status": {"status": "block"},
                    }
                }
            }
        )
