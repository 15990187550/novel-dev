"""Issue taxonomy for novel quality observability.

Adding a new code here is a deliberate act: it commits us to a stable
identifier that will appear in trend queries, dashboard aggregations,
and recommendation rule inputs. Don't add codes ad-hoc.
"""
from __future__ import annotations

from enum import Enum


class QualityIssueCode(str, Enum):
    # Structure group
    BEAT_BOUNDARY_VIOLATION = "BEAT_BOUNDARY_VIOLATION"
    EVENT_ORDER_DRIFT = "EVENT_ORDER_DRIFT"
    PLANNED_CHARACTER_DRIFT = "PLANNED_CHARACTER_DRIFT"

    # Content group
    AI_FLAVOR_HIGH = "AI_FLAVOR_HIGH"
    WORD_COUNT_DRIFT = "WORD_COUNT_DRIFT"
    CONSISTENCY_BROKEN = "CONSISTENCY_BROKEN"
    FORESHADOW_LEAKED = "FORESHADOW_LEAKED"
    HUMANITY_LOW = "HUMANITY_LOW"
    HOOK_WEAK = "HOOK_WEAK"
    PLOT_TENSION_LOW = "PLOT_TENSION_LOW"

    # Flow group
    REVIEW_TIMEOUT = "REVIEW_TIMEOUT"
    EXPORT_FAILED = "EXPORT_FAILED"
    LLM_PARSE_ERROR = "LLM_PARSE_ERROR"
    LLM_JUDGE_INCONSISTENT = "LLM_JUDGE_INCONSISTENT"


class QualityIssueSeverity(str, Enum):
    BLOCK = "block"
    WARN = "warn"
    MANUAL_REVIEW = "manual_review"