from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.style_profiler import StyleProfilerAgent, StyleProfile
from novel_dev.llm.models import LLMResponse


@pytest.mark.asyncio
async def test_profile_success():
    profile = StyleProfile(
        style_guide="节奏快，第三人称有限视角",
        style_config={
            "sentence_patterns": {"avg_length": 25, "complexity": "moderate"},
            "dialogue_style": {"direct_speech_ratio": 0.3},
            "rhetoric_devices": ["比喻", "排比"],
            "pacing": "fast",
            "vocabulary_preferences": ["剑", "血", "杀"],
            "perspective": "limited",
            "tone": "intense",
            "evolution_notes": "",
        },
    )
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text=profile.model_dump_json())

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = StyleProfilerAgent()
        result = await agent.profile("测试文本")

    assert result.style_guide != ""
    assert result.style_config.perspective == "limited"
    assert result.style_config.tone == "intense"
