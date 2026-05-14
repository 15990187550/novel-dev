from __future__ import annotations

from datetime import datetime

from novel_dev.schemas.quality import QualityIssue
from novel_dev.services.chapter_run_trace_service import ChapterRunTraceService


def _issue(
    code: str = "plan_boundary_violation",
    category: str = "structure",
    severity: str = "block",
) -> QualityIssue:
    return QualityIssue(
        code=code,
        category=category,
        severity=severity,
        scope="beat",
        beat_index=1,
        repairability="guided",
        evidence=["提前写入后续 beat 的核心事件"],
        suggestion="聚焦当前 beat",
        source="structure_guard",
    )


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_start_trace_creates_repairing_trace_with_started_event():
    trace = ChapterRunTraceService.start_trace(
        novel_id="novel-a",
        chapter_id="ch-1",
        run_id="run-1",
        phase="drafting",
    )

    assert trace.novel_id == "novel-a"
    assert trace.chapter_id == "ch-1"
    assert trace.run_id == "run-1"
    assert trace.current_phase == "drafting"
    assert trace.terminal_status == "repairing"
    assert trace.quality_status == "unchecked"
    assert len(trace.phase_events) == 1
    event = trace.phase_events[0]
    assert event.phase == "drafting"
    assert event.status == "started"
    assert event.ended_at is None
    assert _parse_timestamp(event.started_at)


def test_start_phase_appends_started_event_and_mark_phase_updates_it():
    trace = ChapterRunTraceService.start_trace("novel-a", "ch-1", "run-1", "drafting")

    ChapterRunTraceService.start_phase(trace, "fast_reviewing", input_summary={"draft_chars": 1200})
    ChapterRunTraceService.mark_phase(
        trace,
        "fast_reviewing",
        "succeeded",
        output_summary={"score": 91},
    )

    assert trace.current_phase == "fast_reviewing"
    assert len(trace.phase_events) == 2
    event = trace.phase_events[-1]
    assert event.phase == "fast_reviewing"
    assert event.status == "succeeded"
    assert event.input_summary == {"draft_chars": 1200}
    assert event.output_summary == {"score": 91}
    assert event.ended_at is not None
    assert _parse_timestamp(event.ended_at) >= _parse_timestamp(event.started_at)


def test_append_event_adds_completed_event_without_requiring_open_phase():
    trace = ChapterRunTraceService.start_trace("novel-a", "ch-1", "run-1", "drafting")

    ChapterRunTraceService.append_event(
        trace,
        phase="editing",
        status="failed",
        input_summary={"attempt": 1},
        output_summary={"rolled_back": True},
        issues=[_issue()],
    )

    assert trace.current_phase == "editing"
    assert len(trace.phase_events) == 2
    event = trace.phase_events[-1]
    assert event.phase == "editing"
    assert event.status == "failed"
    assert event.input_summary == {"attempt": 1}
    assert event.output_summary == {"rolled_back": True}
    assert [issue.code for issue in event.issues] == ["plan_boundary_violation"]
    assert event.ended_at is not None


def test_mark_phase_appends_completed_event_when_no_open_phase_exists():
    trace = ChapterRunTraceService.start_trace("novel-a", "ch-1", "run-1", "drafting")

    ChapterRunTraceService.mark_phase(
        trace,
        "editing",
        "failed",
        output_summary={"attempt": 1},
        issues=[_issue()],
    )

    assert len(trace.phase_events) == 2
    event = trace.phase_events[-1]
    assert event.phase == "editing"
    assert event.status == "failed"
    assert event.output_summary == {"attempt": 1}
    assert [issue.code for issue in event.issues] == ["plan_boundary_violation"]
    assert event.ended_at is not None


def test_mark_blocked_sets_terminal_fields_and_issue_summary():
    trace = ChapterRunTraceService.start_trace("novel-a", "ch-1", "run-1", "fast_reviewing")
    issues = [
        _issue(),
        _issue(code="text_integrity", category="prose", severity="warn"),
    ]

    ChapterRunTraceService.mark_blocked(
        trace,
        "fast_reviewing",
        issues,
        reason="quality gate blocked chapter",
    )

    assert trace.terminal_status == "blocked"
    assert trace.terminal_reason == "quality gate blocked chapter"
    assert trace.current_phase == "fast_reviewing"
    assert trace.quality_status == "block"
    assert trace.issue_summary["total"] == 2
    assert trace.issue_summary["by_category"] == {"structure": 1, "prose": 1}
    assert trace.issue_summary["by_code"] == {"plan_boundary_violation": 1, "text_integrity": 1}
    assert trace.phase_events[-1].status == "blocked"
    assert trace.phase_events[-1].issues == issues


def test_mark_succeeded_sets_terminal_fields_archive_and_export_state():
    trace = ChapterRunTraceService.start_trace("novel-a", "ch-1", "run-1", "librarian")

    ChapterRunTraceService.mark_succeeded(
        trace,
        "librarian",
        quality_status="pass",
        archived=True,
        exported=False,
    )

    assert trace.terminal_status == "succeeded"
    assert trace.terminal_reason is None
    assert trace.current_phase == "librarian"
    assert trace.quality_status == "pass"
    assert trace.archived is True
    assert trace.exported is False
    assert trace.phase_events[-1].status == "succeeded"
    assert trace.phase_events[-1].ended_at is not None


def test_mark_failed_sets_terminal_reason_and_summarizes_issues():
    trace = ChapterRunTraceService.start_trace("novel-a", "ch-1", "run-1", "editing")

    ChapterRunTraceService.mark_failed(
        trace,
        "editing",
        reason="editor failed after retries",
        issues=[_issue(code="rewrite_failed", category="process", severity="warn")],
    )

    assert trace.terminal_status == "failed"
    assert trace.terminal_reason == "editor failed after retries"
    assert trace.current_phase == "editing"
    assert trace.issue_summary["total"] == 1
    assert trace.issue_summary["by_code"] == {"rewrite_failed": 1}
    assert trace.phase_events[-1].status == "failed"
    assert trace.phase_events[-1].issues[0].code == "rewrite_failed"
