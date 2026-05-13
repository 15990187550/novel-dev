from novel_dev.schemas.quality import (
    BeatBoundaryCard,
    ChapterRunTrace,
    PhaseEvent,
    QualityIssue,
    RepairTask,
)


def test_quality_issue_defaults_are_isolated():
    first = QualityIssue(
        code="ai_flavor",
        category="prose",
        severity="warn",
        scope="chapter",
        repairability="guided",
        source="quality_gate",
    )
    second = QualityIssue(
        code="beat_cohesion",
        category="structure",
        severity="block",
        scope="beat",
        repairability="guided",
        source="fast_review",
    )

    first.evidence.append("模板化表达密集")

    assert first.evidence == ["模板化表达密集"]
    assert second.evidence == []


def test_repair_task_defaults_are_isolated():
    first = RepairTask(
        task_id="repair-1",
        chapter_id="ch-1",
        issue_codes=["text_integrity"],
        task_type="integrity_repair",
        scope="paragraph",
    )
    second = RepairTask(
        task_id="repair-2",
        chapter_id="ch-1",
        issue_codes=["required_payoff"],
        task_type="hook_repair",
        scope="beat",
        beat_index=2,
    )

    first.constraints.append("只修复断句")

    assert first.constraints == ["只修复断句"]
    assert second.constraints == []


def test_chapter_run_trace_serializes_nested_events():
    issue = QualityIssue(
        code="beat_cohesion",
        category="structure",
        severity="block",
        scope="beat",
        beat_index=1,
        repairability="guided",
        evidence=["BEAT1 与 BEAT2 重复"],
        suggestion="删除重复承接段",
        source="structure_guard",
    )
    trace = ChapterRunTrace(
        novel_id="novel-a",
        chapter_id="ch-1",
        run_id="run-1",
        current_phase="fast_reviewing",
        terminal_status="blocked",
        phase_events=[
            PhaseEvent(
                phase="fast_reviewing",
                status="blocked",
                started_at="2026-05-13T00:00:00Z",
                issues=[issue],
            )
        ],
    )

    data = trace.model_dump()

    assert data["phase_events"][0]["issues"][0]["code"] == "beat_cohesion"
    assert data["terminal_status"] == "blocked"


def test_beat_boundary_card_round_trip():
    card = BeatBoundaryCard(
        beat_index=0,
        must_cover=["主角发现线索"],
        allowed_materials=["旧信", "雨夜"],
        forbidden_materials=["新敌人现身"],
        reveal_boundary="只能暗示有人跟踪，不确认身份",
        ending_policy="停在未完成动作",
    )

    assert BeatBoundaryCard.model_validate(card.model_dump()).ending_policy == "停在未完成动作"
