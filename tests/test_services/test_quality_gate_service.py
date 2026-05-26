from novel_dev.schemas.review import FastReviewReport
from novel_dev.services.quality_gate_service import QualityGateResult, QualityGateService


def test_evaluate_fast_review_real_contract_downgrades_word_count_drift_to_warn():
    report = FastReviewReport(
        word_count_ok=False,
        consistency_fixed=True,
        ai_flavor_reduced=True,
        beat_cohesion_ok=True,
        language_style_ok=True,
        notes=["字数偏离目标超过10%"],
    )

    gate = QualityGateService.evaluate_fast_review(
        report,
        target_word_count=1000,
        polished_word_count=1800,
        final_review_score=82,
        acceptance_scope="real-contract",
    )

    assert gate.status == "warn"
    assert gate.blocking_items == []
    assert any(item["code"] == "word_count_drift" for item in gate.warning_items)


def test_evaluate_fast_review_real_longform_downgrades_word_count_drift_to_warn():
    report = FastReviewReport(
        word_count_ok=False,
        consistency_fixed=True,
        ai_flavor_reduced=True,
        beat_cohesion_ok=True,
        language_style_ok=True,
        notes=["字数偏离目标超过10%"],
    )

    gate = QualityGateService.evaluate_fast_review(
        report,
        target_word_count=1667,
        polished_word_count=5410,
        final_review_score=82,
        acceptance_scope="real-longform-volume1",
    )

    assert gate.status == "warn"
    assert gate.blocking_items == []
    assert any(item["code"] == "word_count_drift" for item in gate.warning_items)


def test_evaluate_fast_review_non_acceptance_keeps_word_count_drift_blocking():
    report = FastReviewReport(
        word_count_ok=False,
        consistency_fixed=True,
        ai_flavor_reduced=True,
        beat_cohesion_ok=True,
        language_style_ok=True,
        notes=["字数偏离目标超过10%"],
    )

    gate = QualityGateService.evaluate_fast_review(
        report,
        target_word_count=1000,
        polished_word_count=1800,
        final_review_score=72,
    )

    assert gate.status == "block"
    assert any(item["code"] == "word_count_drift" for item in gate.blocking_items)


def test_evaluate_fast_review_blocks_incomplete_final_text():
    report = FastReviewReport(
        word_count_ok=True,
        consistency_fixed=True,
        ai_flavor_reduced=True,
        beat_cohesion_ok=True,
        language_style_ok=True,
        notes=[],
    )

    gate = QualityGateService.evaluate_fast_review(
        report,
        target_word_count=1000,
        polished_word_count=1000,
        final_review_score=82,
        polished_text="林照撑",
        acceptance_scope="real-contract",
    )

    assert gate.status == "block"
    assert any(item["code"] == "text_integrity" for item in gate.blocking_items)


def test_evaluate_fast_review_blocks_isolated_punctuation_paragraph():
    report = FastReviewReport(
        word_count_ok=True,
        consistency_fixed=True,
        ai_flavor_reduced=True,
        beat_cohesion_ok=True,
        language_style_ok=True,
        notes=[],
    )

    gate = QualityGateService.evaluate_fast_review(
        report,
        target_word_count=1000,
        polished_word_count=1000,
        final_review_score=82,
        polished_text="林照停在树影下。\n\n。\n\n密林深处传来短促哨音。",
        acceptance_scope="real-contract",
    )

    assert gate.status == "block"
    assert any(item["code"] == "text_integrity" for item in gate.blocking_items)


def test_evaluate_fast_review_blocks_semantically_truncated_sentence():
    report = FastReviewReport(
        word_count_ok=True,
        consistency_fixed=True,
        ai_flavor_reduced=True,
        beat_cohesion_ok=True,
        language_style_ok=True,
        notes=[],
    )

    gate = QualityGateService.evaluate_fast_review(
        report,
        target_word_count=1000,
        polished_word_count=1000,
        final_review_score=82,
        polished_text="林照用肩膀抵地，试图撑起膝盖。逃，还是搏？他连站都站不。",
        acceptance_scope="real-contract",
    )

    assert gate.status == "block"
    assert any(item["code"] == "text_integrity" for item in gate.blocking_items)


def test_evaluate_fast_review_warns_when_required_payoff_missing():
    report = FastReviewReport(
        word_count_ok=True,
        consistency_fixed=True,
        ai_flavor_reduced=True,
        beat_cohesion_ok=True,
        language_style_ok=True,
        notes=[],
    )

    gate = QualityGateService.evaluate_fast_review(
        report,
        target_word_count=1000,
        polished_word_count=1000,
        final_review_score=82,
        polished_text="林照击倒监视者后离开试炼林，夜色重新安静下来。",
        required_payoffs=["林照搜查遗物发现密函", "新的危险信号逼近"],
        acceptance_scope="real-contract",
    )

    assert gate.status == "manual_review_required"
    assert any(item["code"] == "required_payoff" for item in gate.warning_items)


def test_evaluate_fast_review_accepts_abstract_required_payoff_when_semantically_covered():
    report = FastReviewReport(
        word_count_ok=True,
        consistency_fixed=True,
        ai_flavor_reduced=True,
        beat_cohesion_ok=True,
        language_style_ok=True,
        notes=[],
    )

    gate = QualityGateService.evaluate_fast_review(
        report,
        target_word_count=1000,
        polished_word_count=1000,
        final_review_score=82,
        polished_text=(
            "他重新引气入脉，原本浑浊如雾的真气被绞紧、淬炼，"
            "凝成一丝近乎实质的细流，澄澈远超往日。"
        ),
        required_payoffs=["真气品质提升"],
        acceptance_scope="real-longform-volume1",
    )

    assert gate.status == "pass"
    assert not any(item["code"] == "required_payoff" for item in gate.warning_items)


def test_evaluate_fast_review_keeps_abstract_required_payoff_missing_without_progress_marker():
    report = FastReviewReport(
        word_count_ok=True,
        consistency_fixed=True,
        ai_flavor_reduced=True,
        beat_cohesion_ok=True,
        language_style_ok=True,
        notes=[],
    )

    gate = QualityGateService.evaluate_fast_review(
        report,
        target_word_count=1000,
        polished_word_count=1000,
        final_review_score=82,
        polished_text="他闭目调息，真气沿着经脉缓慢运转，屋内很快安静下来。",
        required_payoffs=["真气品质提升"],
        acceptance_scope="real-longform-volume1",
    )

    assert gate.status == "manual_review_required"
    assert any(item["code"] == "required_payoff" for item in gate.warning_items)


def test_evaluate_fast_review_requires_manual_review_for_low_final_score():
    report = FastReviewReport(
        word_count_ok=True,
        consistency_fixed=True,
        ai_flavor_reduced=True,
        beat_cohesion_ok=True,
        language_style_ok=True,
        notes=[],
    )

    gate = QualityGateService.evaluate_fast_review(
        report,
        target_word_count=1000,
        polished_word_count=1000,
        final_review_score=72,
        polished_text="林照离开试炼林，夜色重新安静下来。",
        acceptance_scope="real-contract",
    )

    assert gate.status == "manual_review_required"
    assert any(item["code"] == "final_review_score" for item in gate.warning_items)


def test_evaluate_fast_review_requires_repair_for_sub_publishable_final_score():
    report = FastReviewReport(
        word_count_ok=True,
        consistency_fixed=True,
        ai_flavor_reduced=True,
        beat_cohesion_ok=True,
        language_style_ok=True,
        notes=[],
    )

    gate = QualityGateService.evaluate_fast_review(
        report,
        target_word_count=1000,
        polished_word_count=1000,
        final_review_score=78,
        polished_text="林照吹灭油灯，识海中的碎片仍在黑暗里缓缓转动。",
        acceptance_scope="real-longform-volume1",
    )

    assert gate.status == "manual_review_required"
    assert any(item["code"] == "final_review_score" for item in gate.warning_items)


def test_evaluate_fast_review_requires_repair_for_weak_critical_dimension():
    report = FastReviewReport(
        word_count_ok=True,
        consistency_fixed=True,
        ai_flavor_reduced=True,
        beat_cohesion_ok=True,
        language_style_ok=True,
        notes=[],
    )

    gate = QualityGateService.evaluate_fast_review(
        report,
        target_word_count=1000,
        polished_word_count=1000,
        final_review_score=84,
        final_review_feedback={
            "breakdown": {
                "hook_strength": {"score": 72, "comment": "章末只是计划预告"},
                "plot_tension": {"score": 81, "comment": "基本推进"},
            }
        },
        polished_text="林照吹灭油灯，决定明早再去后山查看。",
        acceptance_scope="real-longform-volume1",
    )

    assert gate.status == "manual_review_required"
    assert any(item["code"] == "critical_dimension_score" for item in gate.warning_items)


def test_quality_gate_converts_blocking_and_warning_items_to_standard_issues():
    report = FastReviewReport(
        word_count_ok=True,
        consistency_fixed=True,
        ai_flavor_reduced=False,
        beat_cohesion_ok=False,
        language_style_ok=True,
        notes=["节拍之间重复拼接", "模板化表达未降低"],
    )

    gate = QualityGateService.evaluate_fast_review(
        report,
        target_word_count=1000,
        polished_word_count=1000,
        final_review_score=72,
        polished_text="林照推门进屋。窗外雨声忽然停了。",
        acceptance_scope="real-contract",
    )

    issues = QualityGateService.to_quality_issues(gate)

    assert [issue.code for issue in issues] == ["beat_cohesion", "final_review_score", "ai_flavor"]
    assert issues[0].category == "structure"
    assert issues[0].severity == "block"
    assert issues[0].repairability == "guided"
    assert issues[1].category == "prose"
    assert issues[1].severity == "warn"
    assert issues[2].code == "ai_flavor"


def test_quality_gate_converts_required_payoff_to_plot_issue():
    report = FastReviewReport(
        word_count_ok=True,
        consistency_fixed=True,
        ai_flavor_reduced=True,
        beat_cohesion_ok=True,
        language_style_ok=True,
        notes=[],
    )

    gate = QualityGateService.evaluate_fast_review(
        report,
        target_word_count=1000,
        polished_word_count=1000,
        final_review_score=82,
        polished_text="林照离开试炼林，夜色重新安静下来。",
        required_payoffs=["林照搜查遗物发现密函"],
        acceptance_scope="real-contract",
    )

    issues = QualityGateService.to_quality_issues(gate)

    assert len(issues) == 1
    assert issues[0].code == "required_payoff"
    assert issues[0].category == "plot"
    assert issues[0].repairability == "guided"


def test_quality_gate_classifies_continuity_audit_codes_as_guided_continuity_issues():
    gate = QualityGateResult(
        status="block",
        blocking_items=[
            {"code": "continuity_audit", "message": "连续性审计发现阻断问题"},
            {"code": "dead_entity_acted", "message": "已死亡角色继续行动"},
        ],
        warning_items=[
            {"code": "canonical_identity_drift", "message": "角色标准身份发生漂移"},
            {"code": "story_contract_terms_missing", "message": "故事契约术语缺失"},
        ],
    )

    issues = QualityGateService.to_quality_issues(gate)

    assert [issue.code for issue in issues] == [
        "continuity_audit",
        "dead_entity_acted",
        "canonical_identity_drift",
        "story_contract_terms_missing",
    ]
    assert [issue.severity for issue in issues] == ["block", "block", "warn", "warn"]
    for issue in issues:
        assert issue.category == "continuity"
        assert issue.scope == "chapter"
        assert issue.repairability == "guided"
        assert issue.source == "quality_gate"


def test_quality_gate_builds_genre_type_drift_items():
    items = QualityGateService.genre_type_drift_items(
        "董事会刚结束，他突然回宗门境界突破。",
        {
            "blocking_rules": {"type_drift": True},
            "forbidden_drift_patterns": ["宗门", "境界突破"],
        },
    )
    assert items == [
        "type_drift: 命中类型漂移规则：宗门",
        "type_drift: 命中类型漂移规则：境界突破",
    ]


def test_quality_gate_genre_type_drift_ignores_blank_and_duplicate_patterns():
    items = QualityGateService.genre_type_drift_items(
        "他回宗门突破境界。",
        {
            "blocking_rules": {"type_drift": True},
            "forbidden_drift_patterns": [" ", "宗门", "宗门", None, "境界突破"],
        },
    )
    assert items == ["type_drift: 命中类型漂移规则：宗门"]
