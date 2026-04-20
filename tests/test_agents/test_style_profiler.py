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


@pytest.mark.asyncio
async def test_profile_coerces_text_and_string_list_fields():
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(
        text='''{
  "style_guide": {"核心": "冷峻压迫", "节奏": "紧绷"},
  "style_config": {
    "sentence_patterns": {"avg_length": 25, "complexity": "moderate"},
    "dialogue_style": {"direct_speech_ratio": 0.3},
    "rhetoric_devices": {"主要": "比喻", "次要": "排比"},
    "pacing": ["fast", "with pauses"],
    "vocabulary_preferences": {"高频": "剑", "意象": "血"},
    "perspective": {"main": "limited"},
    "tone": ["intense", "dark"],
    "evolution_notes": {"前期": "克制", "后期": "更疯狂"}
  }
}'''
    )

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = StyleProfilerAgent()
        result = await agent.profile("测试文本")

    assert "核心: 冷峻压迫" in result.style_guide
    assert result.style_config.rhetoric_devices == ["主要: 比喻", "次要: 排比"]
    assert result.style_config.vocabulary_preferences == ["高频: 剑", "意象: 血"]
    assert result.style_config.pacing == "fast\nwith pauses"
    assert result.style_config.perspective == "main: limited"
    assert result.style_config.tone == "intense\ndark"
    assert "前期: 克制" in result.style_config.evolution_notes
