# tests/test_services/test_issue_hints.py
from novel_dev.services.issue_hints import (
    IssueHintsService,
    IssueHint,
)


def test_hints_match_when_count_meets_threshold():
    cfg = {
        "AI_FLAVOR_HIGH": {"severity": "warn", "threshold": 3, "hint": "..."}
    }
    svc = IssueHintsService(cfg)
    hits = svc.matched_hints([("AI_FLAVOR_HIGH", 3), ("OTHER", 1)])
    assert len(hits) == 2
    assert hits[0].code == "AI_FLAVOR_HIGH"
    assert hits[0].matches is True
    assert hits[1].matches is False


def test_hints_omit_match_when_count_below_threshold():
    cfg = {"X": {"severity": "warn", "threshold": 5, "hint": "..."}}
    svc = IssueHintsService(cfg)
    hits = svc.matched_hints([("X", 2)])
    assert len(hits) == 1
    assert hits[0].matches is False


def test_hints_returns_record_for_unknown_codes():
    svc = IssueHintsService({})
    hits = svc.matched_hints([("UNKNOWN_CODE", 10)])
    assert len(hits) == 1
    assert hits[0].matches is False
    assert hits[0].severity == "unknown"
