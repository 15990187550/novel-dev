from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.context_agent import ContextAgent
from novel_dev.schemas.context import ChapterPlan, BeatPlan, LocationContext
from novel_dev.llm.models import LLMResponse


@pytest.mark.asyncio
async def test_load_location_context(async_session):
    from novel_dev.repositories.spaceline_repo import SpacelineRepository
    from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
    from novel_dev.repositories.timeline_repo import TimelineRepository

    sp_repo = SpacelineRepository(async_session)
    await sp_repo.create(location_id="loc1", name="青云宗", novel_id="n_test")

    fs_repo = ForeshadowingRepository(async_session)
    await fs_repo.create(
        fs_id="fs1", content="玉佩发光", 埋下_time_tick=1,
        相关人物_ids=[], novel_id="n_test"
    )

    tl_repo = TimelineRepository(async_session)
    await tl_repo.create(tick=1, narrative="入门测试", novel_id="n_test")

    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text='{"locations": ["青云宗"], "entities": ["林风"], "time_range": {"start_tick": -1, "end_tick": 1}, "foreshadowing_keywords": ["玉佩"]}'),
        LLMResponse(text='{"current": "青云宗大殿", "parent": "青云宗", "narrative": "晨光透过雕花窗棂，洒落在青石地面上..."}'),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = ContextAgent(async_session)
        plan = ChapterPlan(
            chapter_number=1, title="测试", target_word_count=3000,
            beats=[BeatPlan(summary="开场", target_mood="tense", key_entities=["林风"])]
        )
        result = await agent._load_location_context(plan, "n_test")

    assert result.current == "青云宗大殿"
    assert "晨光" in result.narrative
    assert mock_client.acomplete.call_count == 2
