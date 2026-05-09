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
    if isinstance(review_status, dict):
        status = str(review_status.get("status") or "missing")
        reason = str(review_status.get("reason") or "").strip()

    accepted = status == "accepted"
    message = "Volume plan is accepted for chapter generation"
    if not accepted:
        message = f"Volume plan is not accepted for chapter generation: status={status}"
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
