import json

from novel_dev.testing.report import Issue, ReportWriter, TestRunReport


def test_report_writer_creates_json_and_markdown(tmp_path):
    report = TestRunReport(
        run_id="2026-05-07T153000-generation-real",
        entrypoint="scripts/verify_generation_real.sh",
        status="failed",
        duration_seconds=12.5,
        dataset="minimal_builtin",
        llm_mode="real_then_fake_on_external_block",
        environment={"python": "3.11"},
        artifacts={
            "novel_id": "novel-test",
            "exported_path": "./novel_output/novel-test/novel.md",
        },
    )
    report.add_issue(
        Issue(
            id="GEN-QUALITY-001",
            type="GENERATION_QUALITY",
            severity="high",
            stage="chapter_draft",
            is_external_blocker=False,
            real_llm=True,
            fake_rerun_status="passed",
            message="Chapter draft missed a required beat.",
            evidence=["artifacts/generation/stage-07-chapter.md"],
            reproduce="scripts/verify_generation_real.sh --stage chapter_draft",
        )
    )

    writer = ReportWriter(tmp_path)
    paths = writer.write(report)

    summary_json = json.loads(paths.summary_json.read_text(encoding="utf-8"))
    assert summary_json["status"] == "failed"
    assert summary_json["issues"][0]["id"] == "GEN-QUALITY-001"
    assert summary_json["issues"][0]["reproduce"].endswith("--stage chapter_draft")

    summary_md = paths.summary_md.read_text(encoding="utf-8")
    assert "# Test Run 2026-05-07T153000-generation-real" in summary_md
    assert "## Artifacts" in summary_md
    assert "`novel_id`" in summary_md
    assert "`exported_path`" in summary_md
    assert "GEN-QUALITY-001" in summary_md
    assert "Chapter draft missed a required beat." in summary_md


def test_report_status_becomes_failed_when_blocking_issue_is_added():
    report = TestRunReport(
        run_id="run",
        entrypoint="entry",
        status="passed",
        duration_seconds=1,
        dataset="minimal_builtin",
        llm_mode="fake",
    )
    report.add_issue(
        Issue(
            id="SYSTEM-001",
            type="SYSTEM_BUG",
            severity="high",
            stage="preflight",
            is_external_blocker=False,
            real_llm=False,
            fake_rerun_status=None,
            message="API health check failed.",
            evidence=[],
            reproduce="scripts/verify_generation_real.sh --stage preflight",
        )
    )

    assert report.status == "failed"
