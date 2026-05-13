from novel_dev.schemas.quality import QualityIssue
from novel_dev.services.repair_planner_service import RepairPlanner


def _issue(
    code: str,
    *,
    category: str = "prose",
    severity: str = "warn",
    scope: str = "chapter",
    beat_index: int | None = None,
    repairability: str = "guided",
) -> QualityIssue:
    return QualityIssue(
        code=code,
        category=category,
        severity=severity,
        scope=scope,
        beat_index=beat_index,
        repairability=repairability,
        evidence=[f"{code} evidence"],
        suggestion=f"{code} suggestion",
        source="testing",
    )


def test_plan_maps_supported_issue_codes_to_repair_task_types():
    issues = [
        _issue("beat_cohesion", category="structure", scope="beat", beat_index=1),
        _issue("plan_boundary_violation", category="structure", scope="beat", beat_index=2),
        _issue("text_integrity", scope="paragraph"),
        _issue("ai_flavor"),
        _issue("language_style", category="style"),
        _issue("word_count_drift"),
        _issue("final_review_score"),
        _issue("required_payoff", category="plot"),
        _issue("hook_strength", category="plot"),
        _issue("characterization", category="character"),
        _issue("continuity_audit", category="continuity"),
        _issue("consistency", category="continuity"),
        _issue("dead_entity_acted", category="continuity"),
        _issue("canonical_identity_drift", category="continuity"),
        _issue("story_contract_terms_missing", category="continuity"),
    ]

    tasks = RepairPlanner.plan("ch-1", issues)

    by_code = {code: task.task_type for task in tasks for code in task.issue_codes}
    assert by_code == {
        "beat_cohesion": "cohesion_repair",
        "plan_boundary_violation": "cohesion_repair",
        "text_integrity": "integrity_repair",
        "ai_flavor": "prose_polish",
        "language_style": "prose_polish",
        "word_count_drift": "prose_polish",
        "final_review_score": "prose_polish",
        "required_payoff": "hook_repair",
        "hook_strength": "hook_repair",
        "characterization": "character_repair",
        "continuity_audit": "continuity_repair",
        "consistency": "continuity_repair",
        "dead_entity_acted": "continuity_repair",
        "canonical_identity_drift": "continuity_repair",
        "story_contract_terms_missing": "continuity_repair",
    }


def test_plan_groups_issues_by_task_type_scope_and_beat_index():
    issues = [
        _issue("beat_cohesion", category="structure", scope="beat", beat_index=3),
        _issue("plan_boundary_violation", category="structure", scope="beat", beat_index=3),
        _issue("beat_cohesion", category="structure", scope="beat", beat_index=4),
        _issue("ai_flavor", scope="chapter"),
        _issue("language_style", category="style", scope="chapter"),
    ]

    tasks = RepairPlanner.plan("ch-2", issues)

    grouped = {(task.task_type, task.scope, task.beat_index): task.issue_codes for task in tasks}
    assert grouped[("cohesion_repair", "beat", 3)] == [
        "beat_cohesion",
        "plan_boundary_violation",
    ]
    assert grouped[("cohesion_repair", "beat", 4)] == ["beat_cohesion"]
    assert grouped[("prose_polish", "chapter", None)] == ["ai_flavor", "language_style"]
    assert len(tasks) == 3


def test_plan_skips_non_repairable_manual_and_unknown_codes():
    issues = [
        _issue("ai_flavor", repairability="auto"),
        _issue("language_style", category="style", repairability="guided"),
        _issue("word_count_drift", repairability="manual"),
        _issue("text_integrity", scope="paragraph", repairability="none"),
        _issue("unknown_quality_code", repairability="guided"),
    ]

    tasks = RepairPlanner.plan("ch-3", issues)

    assert [task.issue_codes for task in tasks] == [["ai_flavor", "language_style"]]


def test_plan_outputs_stable_task_fields_and_chinese_guidance():
    issues = [
        _issue("text_integrity", scope="paragraph", repairability="auto"),
        _issue("text_integrity", scope="paragraph", repairability="auto"),
    ]

    first = RepairPlanner.plan("Chapter 6/第一章", issues)
    second = RepairPlanner.plan("Chapter 6/第一章", list(reversed(issues)))

    assert [task.model_dump() for task in first] == [task.model_dump() for task in second]
    task = first[0]
    assert task.task_id.startswith("repair-chapter-6-")
    assert task.task_id.endswith("-integrity_repair-paragraph-all-text_integrity")
    assert task.chapter_id == "Chapter 6/第一章"
    assert task.task_type == "integrity_repair"
    assert task.scope == "paragraph"
    assert task.beat_index is None
    assert task.issue_codes == ["text_integrity"]
    assert task.attempt == 0
    assert any("中文" in criterion or "文本" in criterion for criterion in task.success_criteria)
    assert any("不得" in constraint or "只" in constraint for constraint in task.constraints)


def test_cohesion_repair_guidance_mentions_duplicate_text_and_transitions():
    tasks = RepairPlanner.plan(
        "ch-cohesion",
        [_issue("beat_cohesion", category="structure", scope="beat", beat_index=1)],
    )

    guidance = " ".join(tasks[0].constraints + tasks[0].success_criteria)
    assert "重复" in guidance
    assert "转场" in guidance


def test_task_ids_do_not_collide_for_pure_cjk_chapter_ids():
    first = RepairPlanner.plan("第一章", [_issue("ai_flavor")])
    second = RepairPlanner.plan("第二章", [_issue("ai_flavor")])

    assert first[0].task_id != second[0].task_id
    assert first[0].task_id.startswith("repair-chapter-")
    assert second[0].task_id.startswith("repair-chapter-")
