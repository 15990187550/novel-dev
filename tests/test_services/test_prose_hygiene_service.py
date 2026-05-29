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


def test_narration_hygiene_detects_analytic_choice_question():
    issues = ProseHygieneService.find_narration_hygiene_issues(
        "继续推进，还是强行收束？他在剧痛里清楚地权衡两种代价。"
    )

    assert any(issue.code == "analytic_choice_question" for issue in issues)


def test_narration_hygiene_detects_conditional_risk_calculus():
    issues = ProseHygieneService.find_narration_hygiene_issues(
        "若此刻失控，经脉尽断都是轻的；但若强行中断，明日是否还能重现全是未知。"
    )

    assert any(issue.code == "conditional_risk_calculus" for issue in issues)


def test_narration_hygiene_detects_abstract_verdict():
    issues = ProseHygieneService.find_narration_hygiene_issues(
        "山川虚影压在眼睑上，此刻却成了失控的佐证。"
    )

    assert any(issue.code == "abstract_verdict" for issue in issues)


def test_narration_hygiene_allows_concrete_failed_action():
    issues = ProseHygieneService.find_narration_hygiene_issues(
        "他咬住舌尖想截断真气，牙关却僵住，喉咙里只挤出一声气音。"
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


def test_contextual_modern_terms_can_require_nearby_in_story_markers():
    context = {
        "genre_quality_config": {
            "modern_terms_policy": "contextual",
            "modern_drift_patterns": ["界面"],
            "contextual_modern_term_rules": [
                {
                    "terms": ["界面"],
                    "context_markers": ["系统"],
                    "near_markers": ["系统", "任务", "光幕"],
                }
            ],
        },
        "active_entities": [{"name": "系统", "type": "concept"}],
    }

    allowed = ProseHygieneService.find_modern_drift_issues(
        "赵元眼前的系统界面裂开，猩红警告一行行碎成梵文。",
        context=context,
    )
    blocked = ProseHygieneService.find_modern_drift_issues(
        "陆照站在山门前，看见一块陌生界面浮在石碑上。",
        context=context,
    )

    assert allowed == []
    assert any("界面" in issue for issue in blocked)
