from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from novel_dev.schemas.quality import ChapterRunTrace, PhaseEvent, QualityIssue
from novel_dev.services.quality_issue_service import QualityIssueService


PhaseStatus = Literal["started", "succeeded", "failed", "blocked", "skipped"]


class ChapterRunTraceService:
    """Build and update chapter quality run traces."""

    @classmethod
    def start_trace(
        cls,
        novel_id: str,
        chapter_id: str,
        run_id: str,
        phase: str,
    ) -> ChapterRunTrace:
        now = cls._now()
        return ChapterRunTrace(
            novel_id=novel_id,
            chapter_id=chapter_id,
            run_id=run_id,
            current_phase=phase,
            terminal_status="repairing",
            phase_events=[
                PhaseEvent(
                    phase=phase,
                    status="started",
                    started_at=now,
                )
            ],
        )

    @classmethod
    def start_phase(
        cls,
        trace: ChapterRunTrace,
        phase: str,
        input_summary: dict[str, Any] | None = None,
    ) -> ChapterRunTrace:
        trace.current_phase = phase
        trace.phase_events.append(
            PhaseEvent(
                phase=phase,
                status="started",
                started_at=cls._now(),
                input_summary=input_summary or {},
            )
        )
        return trace

    @classmethod
    def append_event(
        cls,
        trace: ChapterRunTrace,
        *,
        phase: str,
        status: PhaseStatus,
        issues: list[QualityIssue] | None = None,
        input_summary: dict[str, Any] | None = None,
        output_summary: dict[str, Any] | None = None,
    ) -> ChapterRunTrace:
        now = cls._now()
        trace.phase_events.append(
            PhaseEvent(
                phase=phase,
                status=status,
                started_at=now,
                ended_at=None if status == "started" else now,
                input_summary=input_summary or {},
                output_summary=output_summary or {},
                issues=issues or [],
            )
        )
        trace.current_phase = phase
        return trace

    @classmethod
    def mark_phase(
        cls,
        trace: ChapterRunTrace,
        phase: str,
        status: PhaseStatus,
        output_summary: dict[str, Any] | None = None,
        issues: list[QualityIssue] | None = None,
    ) -> ChapterRunTrace:
        trace.current_phase = phase
        cls._upsert_phase_event(
            trace,
            phase=phase,
            status=status,
            output_summary=output_summary,
            issues=issues,
        )
        return trace

    @classmethod
    def mark_blocked(
        cls,
        trace: ChapterRunTrace,
        phase: str,
        issues: list[QualityIssue],
        reason: str,
    ) -> ChapterRunTrace:
        trace.terminal_status = "blocked"
        trace.terminal_reason = reason
        trace.current_phase = phase
        trace.issue_summary = QualityIssueService.summarize(issues)
        trace.quality_status = "block"
        return cls.mark_phase(trace, phase, "blocked", issues=issues)

    @classmethod
    def mark_succeeded(
        cls,
        trace: ChapterRunTrace,
        phase: str,
        quality_status: str = "pass",
        archived: bool = False,
        exported: bool | None = None,
    ) -> ChapterRunTrace:
        trace.terminal_status = "succeeded"
        trace.terminal_reason = None
        trace.current_phase = phase
        trace.quality_status = quality_status
        trace.archived = archived
        trace.exported = exported
        return cls.mark_phase(trace, phase, "succeeded")

    @classmethod
    def mark_failed(
        cls,
        trace: ChapterRunTrace,
        phase: str,
        reason: str,
        issues: list[QualityIssue] | None = None,
    ) -> ChapterRunTrace:
        trace.terminal_status = "failed"
        trace.terminal_reason = reason
        trace.current_phase = phase
        if issues:
            trace.issue_summary = QualityIssueService.summarize(issues)
        return cls.mark_phase(trace, phase, "failed", issues=issues)

    @classmethod
    def _upsert_phase_event(
        cls,
        trace: ChapterRunTrace,
        phase: str,
        status: PhaseStatus,
        output_summary: dict[str, Any] | None = None,
        issues: list[QualityIssue] | None = None,
    ) -> PhaseEvent:
        now = cls._now()
        event = cls._latest_open_event(trace, phase)
        if event is None:
            event = PhaseEvent(
                phase=phase,
                status="started",
                started_at=now,
            )
            trace.phase_events.append(event)

        event.status = status
        event.ended_at = now
        event.output_summary = output_summary or {}
        event.issues = issues or []
        return event

    @staticmethod
    def _latest_open_event(trace: ChapterRunTrace, phase: str) -> PhaseEvent | None:
        for event in reversed(trace.phase_events):
            if event.phase == phase and event.ended_at is None:
                return event
        return None

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
