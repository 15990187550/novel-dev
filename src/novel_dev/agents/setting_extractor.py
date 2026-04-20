from typing import List, Union
from pydantic import BaseModel, field_validator

from novel_dev.agents._llm_helpers import call_and_parse_model
from novel_dev.services.log_service import log_service


class CharacterProfile(BaseModel):
    name: str
    identity: str = ""
    personality: str = ""
    goal: str = ""


class ImportantItem(BaseModel):
    name: str
    description: str = ""
    significance: str = ""


class FactionInfo(BaseModel):
    name: str = ""
    description: str = ""
    relationship_with_protagonist: str = ""


def _stringify_structured_value(value):
    if isinstance(value, dict):
        parts = []
        for key, val in value.items():
            if isinstance(val, dict):
                sub = ", ".join(f"{k}={sub_v}" for k, sub_v in val.items())
                parts.append(f"{key}: {sub}")
            else:
                parts.append(f"{key}: {val}")
        return "\n".join(parts)
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(_stringify_structured_value(item))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return value


class ExtractedSetting(BaseModel):
    worldview: Union[str, dict, list] = ""
    power_system: Union[str, dict, list] = ""
    factions: Union[str, List[FactionInfo], dict] = ""
    character_profiles: List[CharacterProfile] = []
    important_items: List[ImportantItem] = []
    plot_synopsis: Union[str, dict, list] = ""

    @field_validator("worldview", "power_system", "plot_synopsis", mode="before")
    @classmethod
    def _coerce_text_fields(cls, v):
        return _stringify_structured_value(v)

    @field_validator("factions", mode="before")
    @classmethod
    def _coerce_factions(cls, v):
        if isinstance(v, dict):
            return _stringify_structured_value(v)
        if isinstance(v, list):
            parts = []
            for item in v:
                if isinstance(item, dict):
                    name = item.get("name", "")
                    desc = item.get("description", "")
                    rel = item.get("relationship_with_protagonist", "")
                    parts.append(f"{name}: {desc}" + (f" (与主角关系: {rel})" if rel else ""))
                else:
                    parts.append(str(item))
            return "\n".join(parts)
        return v


class SettingExtractorAgent:
    async def extract(self, text: str, novel_id: str = "") -> ExtractedSetting:
        if novel_id:
            log_service.add_log(novel_id, "SettingExtractorAgent", f"开始提取设定，文本长度: {len(text)} 字")
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
        result = await call_and_parse_model(
            "SettingExtractorAgent", "extract_setting", prompt, ExtractedSetting, max_retries=3, novel_id=novel_id,
        )
        if novel_id:
            log_service.add_log(
                novel_id, "SettingExtractorAgent",
                f"设定提取完成: 人物 {len(result.character_profiles)} 个, 物品 {len(result.important_items)} 个"
            )
        return result
