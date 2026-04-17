from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.setting_extractor import SettingExtractorAgent, ExtractedSetting
from novel_dev.llm.models import LLMResponse


@pytest.mark.asyncio
async def test_extract_success():
    extracted = ExtractedSetting(
        worldview="天玄大陆",
        power_system="炼气筑基金丹",
        factions="青云宗",
        character_profiles=[
            {"name": "林风", "identity": "弟子", "personality": "坚韧", "goal": "报仇"}
        ],
        important_items=[
            {"name": "玉佩", "description": "信物", "significance": "身世"}
        ],
        plot_synopsis="林风拜入青云宗",
    )
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text=extracted.model_dump_json())

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = SettingExtractorAgent()
        result = await agent.extract("任意文本")

    assert result.worldview == "天玄大陆"
    assert len(result.character_profiles) == 1
    assert result.character_profiles[0].name == "林风"


@pytest.mark.asyncio
async def test_extract_retry_then_success():
    extracted = ExtractedSetting(worldview="大陆")
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text="invalid"),
        LLMResponse(text=extracted.model_dump_json()),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = SettingExtractorAgent()
        result = await agent.extract("任意文本")

    assert result.worldview == "大陆"
    assert mock_client.acomplete.call_count == 2
