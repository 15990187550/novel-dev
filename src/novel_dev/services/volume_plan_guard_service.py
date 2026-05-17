from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VolumePlanReadiness:
    accepted: bool
    status: str
    reason: str
    message: str


def evaluate_volume_plan_readiness(checkpoint: dict[str, Any] | None) -> VolumePlanReadiness:
    checkpoint = checkpoint or {}
    volume_plan = checkpoint.get("current_volume_plan")
    review_status = volume_plan.get("review_status") if isinstance(volume_plan, dict) else None
    status = "missing"
    reason = ""
    writability_passed = False
    quality_preflight_blocked = False
    quality_preflight_status = ""
    manual_override_approved = False
    if isinstance(review_status, dict):
        status = str(review_status.get("status") or "missing")
        reason = str(review_status.get("reason") or "").strip()
        writability = review_status.get("writability_status")
        if isinstance(writability, dict):
            writability_passed = bool(writability.get("passed"))
        quality_preflight = review_status.get("quality_preflight_status")
        if isinstance(quality_preflight, dict):
            quality_preflight_status = str(quality_preflight.get("status") or "")
            quality_preflight_blocked = quality_preflight_status == "block"
        override = review_status.get("manual_generation_override")
        if isinstance(override, dict):
            manual_override_approved = (
                bool(override.get("approved"))
                and bool(str(override.get("reason") or "").strip())
            )

    accepted = status == "accepted" and not quality_preflight_blocked
    if (
        not accepted
        and status == "needs_manual_review"
        and writability_passed
        and quality_preflight_status in {"pass", "warn"}
        and manual_override_approved
    ):
        accepted = True
        reason = reason or "manual generation override approved"
    message = "Volume plan is accepted for chapter generation"
    if not accepted:
        message = f"Volume plan is not accepted for chapter generation: status={status}"
        if quality_preflight_blocked:
            message += ", quality_preflight_status=block"
        elif status == "needs_manual_review" and quality_preflight_status not in {"pass", "warn"}:
            message += ", quality_preflight_status=missing"
        if status == "needs_manual_review" and writability_passed and not manual_override_approved:
            message += ", manual_generation_override=missing"
        if reason:
            message += f", reason={reason}"
    return VolumePlanReadiness(
        accepted=accepted,
        status=status,
        reason=reason,
        message=message,
    )


def ensure_volume_plan_accepted(checkpoint: dict[str, Any] | None) -> None:
    readiness = evaluate_volume_plan_readiness(checkpoint)
    if not readiness.accepted:
        raise ValueError(readiness.message)
