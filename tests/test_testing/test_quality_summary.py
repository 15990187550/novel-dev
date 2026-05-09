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
