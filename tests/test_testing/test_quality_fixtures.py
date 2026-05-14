import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "tests" / "generation" / "fixtures" / "quality"
EXPECTED_FIXTURES = {
    "ai_flavor.json",
    "repeated_beat.json",
    "text_integrity.json",
    "weak_hook.json",
}
EXPECTED_ISSUE_CODES = {
    "ai_flavor",
    "beat_cohesion",
    "hook_strength",
    "required_payoff",
    "text_integrity",
}
EXPECTED_CATEGORIES_BY_CODE = {
    "ai_flavor": "prose",
    "beat_cohesion": "structure",
    "hook_strength": "plot",
    "required_payoff": "plot",
    "text_integrity": "structure",
}


def test_quality_fixtures_have_required_fields():
    fixture_paths = sorted(FIXTURE_DIR.glob("*.json"))

    assert {path.name for path in fixture_paths} == EXPECTED_FIXTURES

    for path in fixture_paths:
        fixture = json.loads(path.read_text(encoding="utf-8"))
        issue_codes = fixture["expected_issue_codes"]
        beats = fixture["chapter_plan"]["beats"]

        assert fixture["id"] == path.stem
        assert isinstance(fixture["category"], str)
        assert fixture["category"].strip()
        assert isinstance(fixture["chapter_plan"], dict)
        assert isinstance(beats, list)
        assert beats
        assert all(isinstance(beat, dict) and str(beat.get("summary") or "").strip() for beat in beats)
        assert isinstance(fixture["raw_text"], str)
        assert fixture["raw_text"].strip()
        assert isinstance(issue_codes, list)
        assert issue_codes
        assert len(issue_codes) == len(set(issue_codes))
        assert set(issue_codes) <= EXPECTED_ISSUE_CODES
        assert all(isinstance(code, str) and code == code.lower() for code in issue_codes)
        assert all(EXPECTED_CATEGORIES_BY_CODE[code] == fixture["category"] for code in issue_codes)
