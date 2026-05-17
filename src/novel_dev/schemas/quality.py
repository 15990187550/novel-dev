from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


QualityCategory = Literal[
    "structure",
    "prose",
    "character",
    "plot",
    "continuity",
    "style",
    "process",
]
QualitySeverity = Literal["info", "warn", "block"]
QualityScope = Literal["chapter", "beat", "paragraph", "flow"]
Repairability = Literal["auto", "guided", "manual", "none"]
QualitySource = Literal[
    "critic",
    "fast_review",
    "quality_gate",
    "structure_guard",
    "continuity_audit",
    "testing",
]


class QualityIssue(BaseModel):
    code: str
    category: QualityCategory
    severity: QualitySeverity
    scope: QualityScope
    beat_index: int | None = None
    repairability: Repairability
    evidence: list[str] = Field(default_factory=list)
    suggestion: str = ""
    source: QualitySource


class BeatBoundaryCard(BaseModel):
    beat_index: int
    must_cover: list[str] = Field(default_factory=list)
    allowed_materials: list[str] = Field(default_factory=list)
    allowed_bridge_details: list[str] = Field(default_factory=list)
    forbidden_materials: list[str] = Field(default_factory=list)
    reveal_boundary: str = ""
    ending_policy: str = ""


class RepairTask(BaseModel):
    task_id: str
    chapter_id: str
    issue_codes: list[str] = Field(default_factory=list)
    task_type: Literal[
        "prose_polish",
        "cohesion_repair",
        "hook_repair",
        "character_repair",
        "integrity_repair",
        "continuity_repair",
    ]
    scope: Literal["chapter", "beat", "paragraph"]
    beat_index: int | None = None
    allowed_materials: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    attempt: int = 0


class PhaseEvent(BaseModel):
    phase: str
    status: Literal["started", "succeeded", "failed", "blocked", "skipped"]
    started_at: str
    ended_at: str | None = None
    input_summary: dict = Field(default_factory=dict)
    output_summary: dict = Field(default_factory=dict)
    issues: list[QualityIssue] = Field(default_factory=list)


class ChapterRunTrace(BaseModel):
    novel_id: str
    chapter_id: str
    run_id: str
    phase_events: list[PhaseEvent] = Field(default_factory=list)
    current_phase: str
    terminal_status: Literal["succeeded", "blocked", "failed", "cancelled", "repairing"]
    terminal_reason: str | None = None
    quality_status: str = "unchecked"
    issue_summary: dict = Field(default_factory=dict)
    repair_attempts: int = 0
    archived: bool = False
    exported: bool | None = None
