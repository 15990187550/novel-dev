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
    人物：张三，反派头目，阴险狡诈。
    重要物品：残缺玉佩，上古魔宗信物，揭示主角身世。
    剧情：林风因家族被灭门，拜入青云宗。
    """
    result = await agent.extract(text)
    assert isinstance(result, ExtractedSetting)
    assert "天玄大陆" in result.worldview

    linfeng = next((c for c in result.character_profiles if c.name == "林风"), None)
    assert linfeng is not None
    assert "外门弟子" in linfeng.identity

    zhangsan = next((c for c in result.character_profiles if c.name == "张三"), None)
    assert zhangsan is not None
    assert "反派头目" in zhangsan.identity

    jade = next((i for i in result.important_items if i.name == "残缺玉佩"), None)
    assert jade is not None
    assert "上古魔宗" in jade.description
