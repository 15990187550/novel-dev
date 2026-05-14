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


def test_quality_summary_records_longform_scale_and_import_metrics():
    report = build_quality_summary_report(
        {
            "novel_id": "novel-longform",
            "acceptance_target": {
                "target_volumes": 18,
                "target_chapters": 1200,
                "target_word_count": 2_000_000,
                "target_volume_number": 1,
                "target_volume_chapters": 67,
                "target_volume_word_count": 111_689,
                "chapter_target_word_count": 1667,
            },
            "source_materials": [
                {"filename": "世界观.md", "status": "approved", "char_count": 100},
                {"filename": "原文.txt", "status": "approved", "char_count": 1000},
            ],
            "checkpoint": {
                "setting_quality_report": {"passed": True},
                "synopsis_data": {
                    "estimated_volumes": 18,
                    "estimated_total_chapters": 1200,
                    "estimated_total_words": 2_000_000,
                    "review_status": {"synopsis_quality_report": {"passed": True}},
                },
                "current_volume_plan": {
                    "chapters": [{"chapter_number": 1}, {"chapter_number": 2}],
                    "review_status": {
                        "writability_status": {"passed": True, "failed_chapter_numbers": []}
                    },
                },
            },
            "chapters": [
                {"chapter_id": "ch_1", "quality_status": "pass", "final_review_score": 82, "polished_text": "甲" * 1700},
                {"chapter_id": "ch_2", "quality_status": "pass", "final_review_score": 84, "polished_text": "乙" * 1600},
            ],
        },
        run_id="quality-longform",
    )

    assert report.status == "passed"
    assert report.artifacts["target_volumes"] == "18"
    assert report.artifacts["target_chapters"] == "1200"
    assert report.artifacts["target_word_count"] == "2000000"
    assert report.artifacts["target_volume_chapters"] == "67"
    assert report.artifacts["generated_chapter_count"] == "2"
    assert report.artifacts["generated_word_count"] == "3300"
    assert report.artifacts["source_material_count"] == "2"
    assert report.artifacts["source_material_approved_count"] == "2"
    detail = next(item for item in report.details if item.stage == "longform_scale")
    assert "target_volume_word_count=111689" in detail.evidence
    assert "source_material_char_count=1100" in detail.evidence


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


def test_quality_summary_recomputes_synopsis_quality_from_snapshot():
    snapshot = {
        "novel_id": "novel-synopsis-recompute",
        "checkpoint": {
            "setting_quality_report": {"passed": True},
            "synopsis_data": {
                "title": "青云烬",
                "logline": "林照为查明家族覆灭真相，在青云宗内鬼追杀下争夺父亲留下的禁术证据。",
                "core_conflict": "林照 vs 渗透青云宗高层的神秘结社，为争夺家族血书与禁术真相生死对抗。",
                "themes": ["复仇", "信任", "代价"],
                "character_arcs": [
                    {
                        "name": "林照",
                        "arc_summary": "从隐忍求生到主动揭开宗门阴谋。",
                        "key_turning_points": ["家族覆灭后隐忍", "与沈青衣结盟", "被迫暴露实力", "放弃邪物血脉"],
                    }
                ],
                "milestones": [
                    {
                        "act": "第一幕",
                        "summary": "家族覆灭后，林照失去修为沦为外门废柴；他与沈青衣结盟追查线索。",
                        "climax_event": "林照发现父亲血书，确认青云宗长老涉案，被黑衣人围杀后逃入禁地。",
                    },
                    {
                        "act": "第二幕",
                        "summary": "林照获得残缺上古功法，实力暴涨但反噬埋下隐患。",
                        "climax_event": "沈青衣当众护他，谢渊拔剑指向林照，临时联盟破裂。",
                    },
                    {
                        "act": "第三幕",
                        "summary": "林照得知身世与千年前封印邪物有关，必须在接受血脉力量和以凡人之躯反抗之间选择。",
                        "climax_event": "林照揭开结社阴谋，放弃融合邪物血脉，以父亲禁器击碎阵眼，青云宗根基崩塌。",
                    },
                ],
                "estimated_volumes": 1,
                "estimated_total_chapters": 3,
                "estimated_total_words": 9000,
                "volume_outlines": [
                    {
                        "volume_number": 1,
                        "title": "灰烬",
                        "summary": "林照在青云宗内追查家族覆灭真相。",
                        "narrative_role": "首卷",
                        "main_goal": "拿到第一部关键证据",
                        "main_conflict": "林照 vs 青云宗内鬼",
                        "start_state": "失去修为",
                        "end_state": "获得证据",
                        "climax": "祖师堂揭露阴谋",
                        "hook_to_next": "天穹裂痕出现",
                        "target_chapter_range": "1-3",
                    }
                ],
                "review_status": {
                    "synopsis_quality_report": {
                        "passed": False,
                        "structure_score": 60,
                        "warning_issues": ["总纲里程碑不足 4 个，结构推进可能偏薄。"],
                    }
                },
            },
            "current_volume_plan": {
                "review_status": {
                    "writability_status": {"passed": True, "failed_chapter_numbers": []}
                }
            },
        },
        "chapters": [{"chapter_id": "ch_1", "quality_status": "pass", "final_review_score": 82}],
    }

    report = build_quality_summary_report(snapshot, run_id="quality-synopsis-recompute")

    assert report.status == "passed"
    assert "SYNOPSIS-QUALITY-001" not in [issue.id for issue in report.issues]
    synopsis_detail = next(detail for detail in report.details if detail.stage == "brainstorm")
    assert "passed=True" in synopsis_detail.evidence
    assert "structure_score=85" in synopsis_detail.evidence
    assert not any("里程碑不足" in item for item in synopsis_detail.evidence)


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
