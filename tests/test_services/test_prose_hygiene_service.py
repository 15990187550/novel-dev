from novel_dev.services.prose_hygiene_service import ProseHygieneService


def test_plan_language_blocks_fallback_summary_phrases():
    issues = ProseHygieneService.find_plan_language_issues(
        "他按当前计划做第一次确认，只能权衡是否继续，最后不能替未知部分补结论。"
    )

    assert any("当前计划" in issue for issue in issues)
    assert any("只能权衡" in issue for issue in issues)


def test_plan_language_does_not_block_specific_failed_prose_phrases():
    issues = ProseHygieneService.find_plan_language_issues(
        "他的选择也只落在眼前，停点收在既有风险上。"
    )

    assert issues == []


def test_modern_terms_are_blocked_without_context():
    issues = ProseHygieneService.find_modern_drift_issues("他被送进ICU，醒来后还惦记KPI。")

    assert any("ICU" in issue for issue in issues)
    assert any("KPI" in issue for issue in issues)


def test_modern_terms_are_allowed_when_context_authorizes_modern_setting():
    issues = ProseHygieneService.find_modern_drift_issues(
        "他被送进ICU，醒来后还惦记KPI。",
        context={"genre_quality_config": {"modern_terms_policy": "allow"}, "genre": "现代都市职场"},
    )

    assert issues == []


def test_modern_terms_need_explicit_policy_not_free_text_authorization():
    issues = ProseHygieneService.find_modern_drift_issues(
        "他被送进ICU，醒来后还惦记KPI。",
        context={"genre": "现代都市职场", "style_guide": "现实主义"},
    )

    assert any("ICU" in issue for issue in issues)
    assert any("KPI" in issue for issue in issues)


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
