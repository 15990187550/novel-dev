import json

from novel_dev.testing import cli
from novel_dev.testing.cli import main


def test_generation_parser_accepts_longform_volume1_options():
    parser = cli._build_parser()

    args = parser.parse_args(
        [
            "generation",
            "--llm-mode",
            "real",
            "--acceptance-scope",
            "real-longform-volume1",
            "--source-dir",
            "/Users/xuhuibin/Desktop/novel",
            "--target-volumes",
            "18",
            "--target-chapters",
            "1200",
            "--target-word-count",
            "2000000",
            "--target-volume-number",
            "1",
            "--target-volume-chapters",
            "67",
        ]
    )

    assert args.acceptance_scope == "real-longform-volume1"
    assert args.source_dir == "/Users/xuhuibin/Desktop/novel"
    assert args.target_volumes == 18
    assert args.target_chapters == 1200
    assert args.target_word_count == 2_000_000
    assert args.target_volume_number == 1
    assert args.target_volume_chapters == 67


def test_generation_command_writes_summary_report(tmp_path):
    exit_code = main(
        [
            "generation",
            "--llm-mode",
            "fake",
            "--dataset",
            "minimal_builtin",
            "--report-root",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    summaries = list(tmp_path.glob("*/summary.json"))
    assert len(summaries) == 1

    summary = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert summary["entrypoint"] == "scripts/verify_generation_real.sh"
    assert summary["dataset"] == "minimal_builtin"
    assert summary["llm_mode"] == "fake"


def test_generation_command_accepts_safe_run_id(tmp_path):
    exit_code = main(
        [
            "generation",
            "--llm-mode",
            "fake",
            "--dataset",
            "minimal_builtin",
            "--report-root",
            str(tmp_path),
            "--run-id",
            "review-fix-run",
        ]
    )

    assert exit_code == 0
    summary_path = tmp_path / "review-fix-run" / "summary.json"
    assert summary_path.exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["run_id"] == "review-fix-run"


def test_generation_command_rejects_unsafe_run_id(tmp_path, capsys):
    exit_code = main(
        [
            "generation",
            "--llm-mode",
            "fake",
            "--dataset",
            "minimal_builtin",
            "--report-root",
            str(tmp_path / "reports"),
            "--run-id",
            "../escape",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Unsafe run_id" in captured.err
    assert "Traceback" not in captured.err
    assert not (tmp_path / "escape" / "summary.json").exists()


def test_generation_command_invalid_dataset_returns_config_error(tmp_path, capsys):
    exit_code = main(
        [
            "generation",
            "--llm-mode",
            "fake",
            "--dataset",
            "missing_dataset",
            "--report-root",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Unknown generation fixture source: missing_dataset" in captured.err
    assert "Traceback" not in captured.err
    assert list(tmp_path.glob("*/summary.json")) == []


def test_generation_command_rejects_unknown_stage(tmp_path, capsys):
    exit_code = main(
        [
            "generation",
            "--llm-mode",
            "fake",
            "--dataset",
            "minimal_builtin",
            "--report-root",
            str(tmp_path),
            "--stage",
            "chapter_draft",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Unknown generation stage: chapter_draft" in captured.err
    assert "Traceback" not in captured.err
    assert list(tmp_path.glob("*/summary.json")) == []
