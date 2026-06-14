import pytest
from novel_dev.services.beat_coverage_validator import BeatCoverageValidator
from novel_dev.schemas.quality import BeatBoundaryCard


@pytest.mark.asyncio
async def test_phase2_end_to_end_beat_violation(async_session):
    cards = [
        BeatBoundaryCard(beat_index=0, must_cover=["陆照"], forbidden_materials=["追兵"]),
    ]
    validator = BeatCoverageValidator(async_session, use_llm=False)
    results = await validator.validate(cards, "陆照听见追兵逼近。")
    assert results[0].severity == "block"
    assert results[0].to_issue_code() == "BEAT_BOUNDARY_VIOLATION"