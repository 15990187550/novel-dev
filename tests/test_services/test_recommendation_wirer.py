import pytest
from novel_dev.services.recommendation_wirer import RecommendationWirer, WireResult

@pytest.mark.asyncio
async def test_wirer_scaffold_exists(async_session):
    wirer = RecommendationWirer(async_session, max_auto_rewrites=0)
    assert wirer.max_auto_rewrites == 0
    assert WireResult(action="accept", recommendation=None, rewrite_job_id=None)
