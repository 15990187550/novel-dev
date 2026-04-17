from typing import List
from pydantic import BaseModel

from novel_dev.agents._llm_helpers import call_and_parse


class CharacterProfile(BaseModel):
    name: str
    identity: str = ""
    personality: str = ""
    goal: str = ""


class ImportantItem(BaseModel):
    name: str
    description: str = ""
    significance: str = ""


class ExtractedSetting(BaseModel):
    worldview: str = ""
    power_system: str = ""
    factions: str = ""
    character_profiles: List[CharacterProfile] = []
    important_items: List[ImportantItem] = []
    plot_synopsis: str = ""


class SettingExtractorAgent:
    async def extract(self, text: str) -> ExtractedSetting:
        MAX_CHARS = 24000
        truncated = text[:MAX_CHARS]
        prompt = (
            "你是一位小说设定提取专家。请从以下设定文档中提取结构化信息，"
            "返回严格符合 ExtractedSetting Schema 的 JSON：\n"
            "1. worldview: 世界观概述\n"
            "2. power_system: 修炼/力量体系\n"
            "3. factions: 势力/宗门分布\n"
            "4. character_profiles: 人物列表（每人含 name, identity, personality, goal）\n"
            "5. important_items: 重要物品列表（每件含 name, description, significance）\n"
            "6. plot_synopsis: 剧情梗概\n\n"
            f"文档内容：\n\n{truncated}"
        )
        return await call_and_parse(
            "SettingExtractorAgent", "extract_setting", prompt,
            ExtractedSetting.model_validate_json, max_retries=3
        )
