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
