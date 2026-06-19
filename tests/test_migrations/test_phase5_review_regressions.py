from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def test_chapters_attempt_index_has_schema_migration():
    migration_texts = [
        path.read_text(encoding="utf-8")
        for path in (ROOT / "migrations" / "versions").glob("*.py")
    ]

    assert any(
        "attempt_index" in text
        and re.search(r"add_column\(\s*['\"]chapters['\"]", text)
        for text in migration_texts
    )


def test_prompt_version_extension_backfills_non_nullable_defaults():
    migration_text = (
        ROOT
        / "migrations"
        / "versions"
        / "20260619_e5b2bfeacd39_phase5_prompt_version_extension.py"
    ).read_text(encoding="utf-8")

    assert "server_default" in migration_text
    assert "experiment_state" in migration_text
    assert "experiment_history" in migration_text
    assert "none" in migration_text
    assert "[]" in migration_text
