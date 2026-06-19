import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from novel_dev.db.models import PromptVersion, ABTest
from novel_dev.services.prompt_registry import PromptRegistry


@pytest.mark.asyncio
async def test_increment_sample_count_triggers_decider(async_session):
    pv = PromptVersion(agent_name="writer", version="v1", content="x", sample_count=10, ab_test_id="ab_1")
    ab = ABTest(id="ab_1", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running")
    async_session.add_all([pv, ab])
    await async_session.flush()

    reg = PromptRegistry(async_session)
    with patch("novel_dev.services.ab_acceptance_decider.ABAcceptanceDecider") as MockDecider:
        mock_instance = AsyncMock()
        mock_instance.evaluate = AsyncMock(return_value=MagicMock(action="no_action"))
        MockDecider.return_value = mock_instance
        await reg.increment_sample_count("writer", "v1")

    mock_instance.evaluate.assert_called_once()