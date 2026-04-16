import pytest

from novel_dev.agents.setting_extractor import SettingExtractorAgent, ExtractedSetting


@pytest.mark.asyncio
async def test_extract_from_text():
    agent = SettingExtractorAgent()
    text = """
    世界观：天玄大陆，万族林立。
    修炼体系：炼气、筑基、金丹。
    势力：青云宗是正道魁首。
    主角林风，青云宗外门弟子，性格坚韧隐忍，目标为父报仇。
    重要物品：残缺玉佩，上古魔宗信物，揭示主角身世。
    剧情：林风因家族被灭门，拜入青云宗。
    """
    result = await agent.extract(text)
    assert isinstance(result, ExtractedSetting)
    assert "天玄大陆" in result.worldview
    assert any(c.name == "林风" for c in result.character_profiles)
    assert any(i.name == "残缺玉佩" for i in result.important_items)
