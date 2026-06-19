import pytest
from novel_dev.services.ab_decision_recorder import ABDecisionRecorder


@pytest.mark.asyncio
async def test_record_writes_db_row_and_logs(async_session):
    from novel_dev.repositories.ab_decision_repo import ABDecisionRepository
    recorder = ABDecisionRecorder(async_session)
    decision = await recorder.record(
        experiment_id="exp_1",
        action="accept",
        prompt_version_id="pv_1",
        scores={"v1": 75.0, "v2": 80.0},
        p_value=0.03,
        meta={"reason": "weighted_score_lift"},
    )
    assert decision.id is not None
    assert decision.action == "accept"
    repo = ABDecisionRepository(async_session)
    recent = await repo.list_recent(window_minutes=5)
    assert len(recent) == 1