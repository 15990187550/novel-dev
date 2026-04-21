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
            {
                "name": "林风",
                "identity": "弟子",
                "personality": "坚韧",
                "goal": "报仇",
                "appearance": "黑衣瘦削",
                "background": "寒门出身",
                "ability": "剑术",
                "realm": "筑基",
                "relationships": "与苏雪为盟友",
                "resources": "祖传玉佩",
                "secrets": "体内藏有残魂",
                "conflict": "与长老一脉对立",
                "arc": "从隐忍走向担当",
                "notes": "逢险更冷静",
            }
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
    assert result.character_profiles[0].appearance == "黑衣瘦削"
    assert result.character_profiles[0].realm == "筑基"
    assert result.character_profiles[0].relationships == "与苏雪为盟友"


@pytest.mark.asyncio
async def test_extract_prompt_requests_richer_character_fields():
    extracted = ExtractedSetting(worldview="大陆")
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text=extracted.model_dump_json())

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = SettingExtractorAgent()
        await agent.extract("任意文本")

    prompt = mock_client.acomplete.call_args.args[0][0].content
    assert "appearance" in prompt
    assert "background" in prompt
    assert "relationships" in prompt
    assert "resources" in prompt
    assert "不要编造" in prompt


@pytest.mark.asyncio
async def test_extract_coerces_dict_power_system_to_string():
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(
        text='''{
  "worldview": "天玄大陆",
  "power_system": {
    "体系名称": "一世法",
    "阶段": ["凡境", "神通境"],
    "说明": "以道果为核心"
  },
  "factions": "青云宗",
  "character_profiles": [],
  "important_items": [],
  "plot_synopsis": "林风拜入青云宗"
}'''
    )

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = SettingExtractorAgent()
        result = await agent.extract("任意文本")

    assert "体系名称: 一世法" in result.power_system
    assert "阶段: ['凡境', '神通境']" in result.power_system
    assert "说明: 以道果为核心" in result.power_system


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
