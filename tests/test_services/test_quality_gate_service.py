from novel_dev.schemas.review import FastReviewReport
from novel_dev.services.quality_gate_service import QualityGateService


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
        final_review_score=72,
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
        final_review_score=72,
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

    assert gate.status == "warn"
    assert any(item["code"] == "required_payoff" for item in gate.warning_items)
