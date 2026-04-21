from typing import List, Union
from pydantic import BaseModel, field_validator

from novel_dev.agents._llm_helpers import call_and_parse_model
from novel_dev.services.log_service import log_service


class CharacterProfile(BaseModel):
    name: str
    identity: str = ""
    personality: str = ""
    goal: str = ""
    appearance: str = ""
    background: str = ""
    ability: str = ""
    realm: str = ""
    relationships: str = ""
    resources: str = ""
    secrets: str = ""
    conflict: str = ""
    arc: str = ""
    notes: str = ""


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
        max_chars = 24000
        truncated = text[:max_chars]
        prompt = (
            "你是一位小说设定提取专家。请从以下设定文档中提取结构化信息，"
            "返回严格符合 ExtractedSetting Schema 的 JSON。只提取文档明确写出或强烈暗示的信息，不要自行补完剧情。\n"
            "1. worldview: 世界观概述\n"
            "2. power_system: 修炼/力量体系\n"
            "3. factions: 势力/宗门分布\n"
            "4. character_profiles: 人物列表，每个人物尽量完整填写：\n"
            "   - name: 姓名/称号\n"
            "   - identity: 身份、定位、阵营、叙事功能\n"
            "   - personality: 性格、行为方式、价值观、情绪底色\n"
            "   - goal: 显性目标、长期追求、当前动机\n"
            "   - appearance: 外貌、气质、辨识特征\n"
            "   - background: 出身、前史、重要经历\n"
            "   - ability: 能力、功法、权柄、特长\n"
            "   - realm: 境界、实力层级、修为状态\n"
            "   - relationships: 与主角/其他人物/势力的关系\n"
            "   - resources: 拥有的资源、传承、法宝、身份优势\n"
            "   - secrets: 隐秘身份、未公开目的、伏笔信息\n"
            "   - conflict: 核心矛盾、阻碍、敌对关系\n"
            "   - arc: 人物成长/转变方向\n"
            "   - notes: 其他无法归类但对正文写作有用的信息\n"
            "5. important_items: 重要物品列表（每件含 name, description, significance）\n"
            "6. plot_synopsis: 剧情梗概\n\n"
            "要求：\n"
            "- 人物字段不要只写一句泛泛概括；同一人物在文档中出现多次时要整合信息。\n"
            "- 没有依据的字段留空字符串，不要编造。\n"
            "- relationships 要优先记录人物之间的具体关系和立场。\n"
            "- ability/realm/resources/secrets/conflict/arc 只要文档有线索就提取。\n\n"
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
