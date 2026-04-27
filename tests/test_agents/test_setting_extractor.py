from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.setting_extractor import (
    SettingExtractorAgent,
    ExtractedSetting,
    FactionInfo,
    LocationInfo,
    CharacterProfile,
    ImportantItem,
    MAX_PARALLEL_EXTRACT_CHUNKS,
    _split_text_into_chunks,
)
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


@pytest.mark.asyncio
async def test_extract_coerces_string_factions_and_locations_to_structured_lists():
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(
        text="""{
  "worldview": "真实界",
  "power_system": "正统修炼",
  "factions": "玄天宗: 正道魁首 (与主角关系: 庇护)\\n大雷音寺: 佛门领袖",
  "locations": "天都: 中土第一城\\n灵山: 大雷音寺所在",
  "character_profiles": [],
  "important_items": [],
  "plot_synopsis": ""
}"""
    )

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = SettingExtractorAgent()
        result = await agent.extract("任意文本")

    assert result.factions == [
        FactionInfo(name="玄天宗", description="正道魁首", relationship_with_protagonist="庇护"),
        FactionInfo(name="大雷音寺", description="佛门领袖", relationship_with_protagonist=""),
    ]
    assert result.locations == [
        LocationInfo(name="天都", description="中土第一城", region=""),
        LocationInfo(name="灵山", description="大雷音寺所在", region=""),
    ]


@pytest.mark.asyncio
async def test_extract_long_text_splits_and_merges_results():
    first = ExtractedSetting(
        worldview="真实界是万界中心",
        power_system="正统修炼体系",
        factions=[FactionInfo(name="玄天宗", description="正道魁首")],
        locations=[LocationInfo(name="天都", description="中土第一城")],
        character_profiles=[CharacterProfile(name="陆照", identity="主角")],
        important_items=[ImportantItem(name="道经", description="核心传承", significance="金手指")],
        plot_synopsis="陆照入宗",
    )
    second = ExtractedSetting(
        worldview="诸天万界依附真实界",
        power_system="系统外挂会被压制",
        factions=[FactionInfo(name="大雷音寺", description="佛门领袖")],
        locations=[LocationInfo(name="灵山", description="佛门圣地")],
        character_profiles=[CharacterProfile(name="佛祖", identity="最终竞争者")],
        important_items=[ImportantItem(name="佛骨舍利", description="佛门圣物", significance="关键圣物")],
        plot_synopsis="陆照诸天历练",
    )

    mock_client = AsyncMock()
    long_text = ("# 第一部分\n" + ("设定说明\n" * 1800) + "# 第二部分\n" + ("更多设定\n" * 1800))
    chunks = _split_text_into_chunks(long_text)
    responses = [first, second]

    mock_client.acomplete.side_effect = [
        LLMResponse(text=responses[index % len(responses)].model_dump_json())
        for index in range(len(chunks))
    ]


    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = SettingExtractorAgent()
        result = await agent.extract(long_text)

    assert mock_client.acomplete.call_count == len(chunks)
    assert len(chunks) > 2
    assert MAX_PARALLEL_EXTRACT_CHUNKS == 2
    assert "真实界是万界中心" in result.worldview
    assert "诸天万界依附真实界" in result.worldview
    assert [item.name for item in result.factions] == ["玄天宗", "大雷音寺"]
    assert [item.name for item in result.locations] == ["天都", "灵山"]
    assert [item.name for item in result.character_profiles] == ["陆照", "佛祖"]
    assert [item.name for item in result.important_items] == ["道经", "佛骨舍利"]
