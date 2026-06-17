from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


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
    is_last_beat: bool = False
    required_open_question: Optional[str] = None

    @model_validator(mode="after")
    def _last_beat_requires_question(self):
        if self.is_last_beat and not self.required_open_question:
            import warnings
            warnings.warn(f"last beat (index={self.beat_index}) has is_last_beat=True but no required_open_question set")
        return self


class RepairTask(BaseModel):
    task_id: str
    chapter_id: str
    issue_codes: list[str] = Field(default_factory=list)
    task_type: Literal[
        "prose_polish",
        "cohesion_repair",
        "hook_repair",
        "character_repair",
        "scene_pressure_repair",
        "integrity_repair",
        "continuity_repair",
    ]
    scope: Literal["chapter", "beat", "paragraph"]
    beat_index: int | None = None
    allowed_materials: list[str] = Field(default_factory=list)
    problem: str = ""
    evidence: list[str] = Field(default_factory=list)
    suggestion: str = ""
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
