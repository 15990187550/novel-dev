import json

from novel_dev.testing.quality_summary import build_quality_summary_report


def test_quality_summary_reports_blocking_quality_issues():
    snapshot = {
        "novel_id": "novel-q",
        "checkpoint": {
            "setting_quality_report": {
                "passed": False,
                "missing_sections": ["power_system"],
                "weaknesses": ["缺少核心冲突或明确阻力来源。"],
            },
            "synopsis_data": {
                "review_status": {
                    "synopsis_quality_report": {
                        "passed": False,
                        "conflict_score": 45,
                        "blocking_issues": ["总纲缺少具体对抗关系。"],
                    }
                }
            },
            "current_volume_plan": {
                "review_status": {
                    "writability_status": {
                        "passed": False,
                        "failed_chapter_numbers": [1],
                    }
                }
            },
        },
        "chapters": [
            {
                "chapter_id": "ch_1",
                "quality_status": "block",
                "quality_reasons": {
                    "blocking_items": [{"code": "consistency", "message": "设定冲突"}]
                },
                "final_review_score": 55,
            }
        ],
    }

    report = build_quality_summary_report(
        snapshot,
        run_id="quality-run",
        duration_seconds=1.5,
    )

    assert report.status == "failed"
    issue_ids = [issue.id for issue in report.issues]
    assert issue_ids == [
        "SETTING-QUALITY-001",
        "SYNOPSIS-QUALITY-001",
        "VOLUME-WRITABILITY-001",
        "CHAPTER-QUALITY-001",
    ]
    assert report.artifacts["novel_id"] == "novel-q"
    assert report.artifacts["chapter_count"] == "1"


def test_quality_summary_passes_clean_snapshot():
    report = build_quality_summary_report(
        {
            "novel_id": "novel-clean",
            "checkpoint": {
                "setting_quality_report": {"passed": True},
                "synopsis_data": {
                    "review_status": {
                        "synopsis_quality_report": {"passed": True}
                    }
                },
                "current_volume_plan": {
                    "review_status": {
                        "writability_status": {"passed": True, "failed_chapter_numbers": []}
                    }
                },
            },
            "chapters": [{"chapter_id": "ch_1", "quality_status": "pass", "final_review_score": 82}],
        },
        run_id="quality-clean",
        duration_seconds=0.2,
    )

    assert report.status == "passed"
    assert report.issues == []


def test_quality_summary_records_passed_stage_quality_details():
    report = build_quality_summary_report(
        {
            "novel_id": "novel-stages",
            "checkpoint": {
                "setting_quality_report": {
                    "passed": True,
                    "coverage": {"worldview": True, "power_system": True, "core_conflict": True},
                },
                "synopsis_data": {
                    "core_conflict": "林照追查家族覆灭真相，对抗血煞盟。",
                    "review_status": {
                        "overall": 88,
                        "synopsis_quality_report": {"passed": True, "conflict_score": 86},
                    },
                },
                "current_volume_plan": {
                    "review_status": {
                        "overall": 82,
                        "writability_status": {
                            "passed": True,
                            "failed_chapter_numbers": [],
                            "warnings": ["最后一章钩子可更强"],
                        },
                    },
                    "chapters": [{"chapter_number": 1, "summary": "林照找到父亲玉佩"}],
                },
                "critique_feedback": {
                    "overall": 84,
                    "breakdown": {"plot_tension": {"score": 86}},
                    "summary": "推进清楚。",
                },
            },
            "setting_review_changes": [
                {
                    "object_type": "setting_card",
                    "after_snapshot": {
                        "doc_type": "plot",
                        "title": "第一章启动事件",
                        "content": "第一章让林照找到父亲玉佩。",
                    },
                }
            ],
            "chapters": [{"chapter_id": "ch_1", "quality_status": "pass", "final_review_score": 84}],
        },
        run_id="quality-stages",
    )

    assert report.status == "passed"
    assert report.issues == []
    stages = [detail.stage for detail in report.details]
    assert stages == [
        "setting_generation",
        "brainstorm",
        "volume_plan",
        "chapter_final_review",
    ]
    assert any("worldview=True" in item for item in report.details[0].evidence)
    assert any("conflict_score=86" in item for item in report.details[1].evidence)
    assert any("最后一章钩子可更强" in item for item in report.details[2].recommendation)
    assert any("protagonist_goal" in item for item in report.details[2].evidence)


def test_quality_summary_records_passed_chapter_quality_details():
    report = build_quality_summary_report(
        {
            "novel_id": "novel-detail",
            "checkpoint": {
                "critique_feedback": {
                    "overall": 75,
                    "summary": "章节可读，但人物转折和人味不足。",
                    "breakdown": {
                        "plot_tension": {"score": 82},
                        "humanity": {"score": 68},
                        "readability": {"score": 72},
                    },
                },
                "per_dim_issues": [
                    {
                        "dim": "humanity",
                        "beat_idx": 1,
                        "problem": "沈瑶从敌对到放行过快，缺少识别和犹豫。",
                        "suggestion": "补一个触发点和带代价的行动。",
                    },
                    {
                        "dim": "readability",
                        "problem": "抽象玄幻词反复出现。",
                        "suggestion": "保留一个主感官，删掉重复光影词。",
                    },
                ],
                "editor_guard_warnings": [
                    {
                        "beat_index": 1,
                        "issues": ["新增计划外传音"],
                        "suggested_rewrite_focus": "删除计划外传音",
                    }
                ],
            },
            "chapters": [
                {
                    "chapter_id": "ch_1",
                    "quality_status": "pass",
                    "final_review_score": 75,
                    "quality_reasons": {},
                },
                {
                    "chapter_id": "vol_1_ch_1",
                    "quality_status": "unchecked",
                    "final_review_score": None,
                    "quality_reasons": {},
                }
            ],
        },
        run_id="quality-detail",
    )

    assert report.status == "passed"
    assert report.issues == []
    assert [detail.id for detail in report.details] == ["CHAPTER-QUALITY-DETAIL-001"]
    detail = report.details[0]
    assert detail.stage == "chapter_final_review"
    assert "overall=75" in detail.evidence
    assert "humanity=68" in detail.evidence
    assert any("沈瑶从敌对到放行过快" in item for item in detail.evidence)
    assert any("新增计划外传音" in item for item in detail.evidence)
    assert any("补一个触发点" in item for item in detail.recommendation)


def test_quality_summary_reports_target_word_count_mismatch_root_cause():
    report = build_quality_summary_report(
        {
            "novel_id": "novel-mismatch",
            "checkpoint": {
                "current_chapter_plan": {"target_word_count": 1000},
                "chapter_context": {"chapter_plan": {"target_word_count": 3000}},
                "setting_quality_report": {"passed": True},
            },
            "chapters": [{
                "chapter_id": "ch_1",
                "quality_status": "block",
                "final_review_score": 72,
                "quality_reasons": {
                    "blocking_items": [{
                        "code": "word_count_drift",
                        "message": "字数严重偏离目标",
                        "detail": {"target_word_count": 3000, "polished_word_count": 5400},
                    }]
                },
            }],
        },
        run_id="quality-mismatch",
    )

    assert report.status == "failed"
    assert report.issues[0].id == "CHAPTER-TARGET-MISMATCH-001"
    assert any("root_cause=checkpoint_target_mismatch" in item for item in report.issues[0].evidence)


def test_quality_summary_cli_writes_report(tmp_path):
    from novel_dev.testing.cli import main

    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "novel_id": "novel-cli",
                "checkpoint": {"setting_quality_report": {"passed": True}},
                "chapters": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "quality-summary",
            "--input-json",
            str(snapshot_path),
            "--report-root",
            str(tmp_path / "reports"),
            "--run-id",
            "quality-cli",
        ]
    )

    assert exit_code == 0
    summary_path = tmp_path / "reports" / "quality-cli" / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["entrypoint"] == "novel-dev-testing quality-summary"
    assert summary["artifacts"]["novel_id"] == "novel-cli"
