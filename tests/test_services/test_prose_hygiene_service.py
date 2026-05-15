from novel_dev.services.prose_hygiene_service import ProseHygieneService


def test_modern_terms_are_blocked_without_context():
    issues = ProseHygieneService.find_modern_drift_issues("他被送进ICU，醒来后还惦记KPI。")

    assert any("ICU" in issue for issue in issues)
    assert any("KPI" in issue for issue in issues)


def test_modern_terms_are_allowed_when_context_authorizes_modern_setting():
    issues = ProseHygieneService.find_modern_drift_issues(
        "他被送进ICU，醒来后还惦记KPI。",
        context={"genre": "现代都市职场", "style_guide": "现实主义"},
    )

    assert issues == []


def test_modern_terms_block_when_genre_policy_blocks_even_with_ambiguous_context():
    issues = ProseHygieneService.find_issues(
        "他忍不住吐槽这套 KPI 和互联网黑话。",
        context={"genre_quality_config": {"modern_terms_policy": "block"}},
    )
    assert any(issue.code == "modern_drift" for issue in issues)


def test_modern_terms_allow_when_genre_policy_allows():
    issues = ProseHygieneService.find_issues(
        "他用 KPI 和互联网项目复盘解释眼前的危机。",
        context={"genre_quality_config": {"modern_terms_policy": "allow"}},
    )
    assert not any(issue.code == "modern_drift" for issue in issues)
