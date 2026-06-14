import pytest
from novel_dev.services.beat_coverage_validator import BeatCoverageResult, BeatCoverageValidator


@pytest.mark.asyncio
async def test_validator_scaffold_exists(async_session):
    validator = BeatCoverageValidator(async_session, use_llm=False)
    assert validator.use_llm is False
    result = BeatCoverageResult(beat_index=0, covered=True, deviation=None, severity="ok")
    assert result.beat_index == 0
