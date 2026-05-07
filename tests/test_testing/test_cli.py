import json

from novel_dev.testing.cli import main


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
