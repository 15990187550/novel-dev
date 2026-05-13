from novel_dev.services.quality_issue_service import QualityIssueService


def test_from_dimension_issue_maps_readability_to_prose():
    issues = QualityIssueService.from_dimension_issues(
        [
            {
                "dim": "readability",
                "beat_idx": 0,
                "problem": "解释性旁白过多",
                "suggestion": "改成动作呈现",
            }
        ]
    )

    assert len(issues) == 1
    assert issues[0].code == "readability"
    assert issues[0].category == "prose"
    assert issues[0].scope == "beat"
    assert issues[0].beat_index == 0
    assert issues[0].source == "critic"


def test_from_structure_guard_maps_boundary_violation():
    evidence = {
        "beat_index": 1,
        "issues": ["提前写入后续 beat 的核心事件", "新增计划外事实"],
        "suggested_rewrite_focus": "聚焦当前 beat",
    }

    issues = QualityIssueService.from_structure_guard(evidence, source="structure_guard")

    assert len(issues) == 1
    assert issues[0].code == "plan_boundary_violation"
    assert issues[0].category == "structure"
    assert issues[0].severity == "block"
    assert issues[0].beat_index == 1
    assert "提前写入后续 beat 的核心事件" in issues[0].evidence


def test_summarize_counts_by_category_code_and_repairability():
    issues = QualityIssueService.from_dimension_issues(
        [
            {"dim": "readability", "problem": "AI 腔", "suggestion": "压缩"},
            {"dim": "characterization", "problem": "配角扁平", "suggestion": "增加反应差异"},
        ]
    )

    summary = QualityIssueService.summarize(issues)

    assert summary["total"] == 2
    assert summary["by_category"]["prose"] == 1
    assert summary["by_category"]["character"] == 1
    assert summary["by_repairability"]["guided"] == 2
