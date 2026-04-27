import re
from typing import Any, List

from pydantic import BaseModel, Field, field_validator

from novel_dev.agents._llm_helpers import call_and_parse_model, coerce_to_str_list, coerce_to_text
from novel_dev.services.log_service import logged_agent_step, log_service


GENRE_STYLE_TERMS = {
    "修仙",
    "仙侠",
    "玄幻",
    "都市",
    "都市异能",
    "武侠",
    "奇幻",
    "科幻",
    "末世",
    "悬疑",
    "灵异",
    "历史",
    "架空",
    "系统流",
    "升级流",
    "凡人流",
    "无敌流",
    "群像",
    "爽文",
    "权谋",
    "修炼",
    "境界",
    "法宝",
    "宗门",
}

PROPER_NOUN_SUFFIXES = (
    "大陆",
    "世界",
    "仙界",
    "魔界",
    "神界",
    "秘境",
    "禁地",
    "王朝",
    "帝国",
    "宗",
    "门",
    "派",
    "宫",
    "殿",
    "阁",
    "府",
    "盟",
    "会",
    "族",
    "家",
    "城",
    "镇",
    "村",
    "山",
    "峰",
    "谷",
    "岛",
    "海",
    "江",
    "湖",
    "洲",
    "学院",
)

SUFFIX_REPLACEMENTS = {
    "大陆": "修炼世界",
    "世界": "世界背景",
    "仙界": "高阶位面",
    "魔界": "敌对位面",
    "神界": "高阶位面",
    "秘境": "探索区域",
    "禁地": "危险区域",
    "王朝": "王朝势力",
    "帝国": "帝国势力",
    "宗": "宗门势力",
    "门": "宗门势力",
    "派": "宗门势力",
    "宫": "宗门势力",
    "殿": "宗门势力",
    "阁": "组织势力",
    "府": "家族势力",
    "盟": "联盟势力",
    "会": "组织势力",
    "族": "族群势力",
    "家": "家族势力",
    "城": "城镇地域",
    "镇": "城镇地域",
    "村": "村镇地域",
    "山": "山地场景",
    "峰": "山地场景",
    "谷": "山谷场景",
    "岛": "岛屿场景",
    "海": "海域场景",
    "江": "江河场景",
    "湖": "湖泊场景",
    "洲": "地域板块",
    "学院": "学院势力",
}


class StyleConfig(BaseModel):
    sentence_patterns: dict = Field(default_factory=dict)
    dialogue_style: dict = Field(default_factory=dict)
    narration_voice: dict = Field(default_factory=dict)
    humor_strategy: dict = Field(default_factory=dict)
    information_reveal: dict = Field(default_factory=dict)
    scene_preferences: dict = Field(default_factory=dict)
    rhetoric_devices: List[str] = Field(default_factory=list)
    pacing: str = ""
    vocabulary_preferences: List[str] = Field(default_factory=list)
    perspective: str = ""
    tone: str = ""
    writing_rules: List[str] = Field(default_factory=list)
    style_boundary: List[str] = Field(default_factory=list)
    evolution_notes: str = ""

    @field_validator("pacing", "perspective", "tone", "evolution_notes", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)

    @field_validator("rhetoric_devices", "vocabulary_preferences", "writing_rules", "style_boundary", mode="before")
    @classmethod
    def _coerce_string_list_fields(cls, value: Any) -> List[str]:
        return coerce_to_str_list(value)


class StyleProfile(BaseModel):
    style_guide: str = ""
    style_config: StyleConfig

    @field_validator("style_guide", mode="before")
    @classmethod
    def _coerce_style_guide(cls, value: Any) -> str:
        return coerce_to_text(value)


def _contains_genre_term(value: str) -> bool:
    return any(term in value for term in GENRE_STYLE_TERMS)


def _generic_replacement_for_term(term: str, *, person: bool = False) -> str:
    if person:
        return "角色"
    for suffix, replacement in sorted(SUFFIX_REPLACEMENTS.items(), key=lambda item: len(item[0]), reverse=True):
        if term.endswith(suffix):
            return replacement
    if term.endswith(("诀", "经", "功", "法", "术", "典", "录")):
        return "功法"
    if term.endswith(("剑", "刀", "鼎", "塔", "印", "珠", "镜", "符", "丹", "器")):
        return "法宝资源"
    return "专有元素"


def _extract_reference_specific_terms(text: str) -> dict[str, str]:
    terms: dict[str, str] = {}
    for match in re.finditer(r"[《「『“\"]([^》」』”\"]{2,20})[》」』”\"]", text):
        term = match.group(1).strip()
        if term and not _contains_genre_term(term):
            terms[term] = _generic_replacement_for_term(term)

    suffix_pattern = "|".join(re.escape(suffix) for suffix in PROPER_NOUN_SUFFIXES)
    for match in re.finditer(rf"[\u4e00-\u9fff]{{2,10}}(?:{suffix_pattern})", text):
        term = match.group(0).strip("，。！？；：、,.!?;:()（）[]【】")
        if 2 <= len(term) <= 14 and not _contains_genre_term(term):
            terms[term] = _generic_replacement_for_term(term)
            for suffix in PROPER_NOUN_SUFFIXES:
                if not term.endswith(suffix):
                    continue
                min_len = len(suffix) + 1
                max_len = min(len(term), len(suffix) + 4)
                for size in range(min_len, max_len + 1):
                    tail = term[-size:]
                    if not _contains_genre_term(tail):
                        terms[tail] = _generic_replacement_for_term(tail)

    for match in re.finditer(
        r"([\u4e00-\u9fff]{2,4})(?:说|道|问|笑|怒|喝|叹|心想|心中|来到|进入|击败|面对|望向|看着|握住|转身)",
        text,
    ):
        term = match.group(1).strip()
        if 2 <= len(term) <= 4 and not _contains_genre_term(term):
            terms[term] = _generic_replacement_for_term(term, person=True)

    return terms


def _genericize_reference_specific_text(value: str, replacements: dict[str, str]) -> str:
    if not value or not replacements:
        return value
    cleaned = value
    for term, replacement in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        cleaned = cleaned.replace(term, replacement)
    cleaned = re.sub(r"(不要|避免|禁止|别)(复用|照搬|使用|保留)?[^，。；;]*?(专名|设定|地名|人名)", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _sanitize_style_value(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        return _genericize_reference_specific_text(value, replacements)
    if isinstance(value, list):
        cleaned = []
        for item in value:
            cleaned_item = _sanitize_style_value(item, replacements)
            if cleaned_item not in ("", [], {}):
                cleaned.append(cleaned_item)
        return cleaned
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            cleaned_key = _genericize_reference_specific_text(str(key), replacements)
            cleaned_item = _sanitize_style_value(item, replacements)
            if cleaned_item not in ("", [], {}):
                cleaned[cleaned_key] = cleaned_item
        return cleaned
    return value


def sanitize_reference_specific_style(profile: StyleProfile, source_text: str) -> StyleProfile:
    replacements = _extract_reference_specific_terms(source_text)
    if not replacements:
        return profile
    payload = profile.model_dump()
    sanitized = _sanitize_style_value(payload, replacements)
    return StyleProfile.model_validate(sanitized)


class StyleProfilerAgent:
    @logged_agent_step("StyleProfilerAgent", "分析写作风格", node="style_profile", task="profile")
    async def profile(self, text: str, novel_id: str = "") -> StyleProfile:
        if novel_id:
            log_service.add_log(novel_id, "StyleProfilerAgent", f"开始分析写作风格，文本长度: {len(text)} 字")
        max_chars = 24000
        sampled = text[:max_chars]
        prompt = (
            "你是一位小说文风分析师。请只提取'写法与风格'，不要总结剧情，不要生成人物设定，不要扩写内容。"
            "返回严格符合 StyleProfile Schema 的 JSON，目标是让下游写作 agent 能据此稳定模仿文风写正文。\n"
            "1. style_guide: 100字以内，概括这份文本最核心的文风辨识度。\n"
            "2. style_config 字段要求：\n"
            "   - sentence_patterns: 句长、长短句切换、段落长度、停顿/断裂感\n"
            "   - dialogue_style: 对话占比、标签习惯、对白是否承担推进/塑造人物\n"
            "   - narration_voice: 旁白口吻、是否贴近主角意识、吐槽主要来自旁白还是内心\n"
            "   - humor_strategy: 幽默来源、出现频率、适用场景、需要收敛的场景\n"
            "   - information_reveal: 设定与悬念如何铺陈、是直给还是渐进揭露\n"
            "   - scene_preferences: 日常/战斗/修炼/冲突/抒情等场景各自的常见写法\n"
            "   - rhetoric_devices: 常见修辞手法列表\n"
            "   - pacing: fast/moderate/slow 三选一\n"
            "   - vocabulary_preferences: 高频或风格性词汇 5-12 个\n"
            "   - perspective: first_person/limited/omniscient 三选一\n"
            "   - tone: 用短语概括整体气质，可多项，但要可执行\n"
            "   - writing_rules: 5-8 条可直接用于正文生成的写作规则，只写风格规则，不涉及剧情\n"
            "   - style_boundary: 3-6 条风格边界/禁忌，说明什么写法会破坏这种文风\n"
            "   - evolution_notes: 文风在不同段落/阶段是否有收放变化\n"
            "要求：\n"
            "- 只描述风格，不提供剧情内容、角色关系、世界设定结论。\n"
            "- 必须去背景化: 不要保留参考小说的专有人名、地名、宗门/势力名、功法/法宝名、剧情事件、世界观专名。\n"
            "- 可以保留类型层面的写法规律: 例如修仙、仙侠、玄幻、都市、系统流、升级流、凡人流等题材/品类风格。\n"
            "- 如果样本里出现具体专名,要抽象成'主角''反派''宗门势力''关键资源''境界突破'等通用写法描述。\n"
            "- 输出要具体、可执行，避免空泛评论。\n"
            "- 如果原文幽默与庄重并存，要说明切换条件。\n"
            "- scene_preferences 和 information_reveal 要服务'如何写正文'，不是文学赏析。\n\n"
            f"文本样本：\n\n{sampled}"
        )
        result = await call_and_parse_model(
            "StyleProfilerAgent", "profile_style", prompt, StyleProfile, max_retries=3, novel_id=novel_id,
        )
        result = sanitize_reference_specific_style(result, sampled)
        if novel_id:
            log_service.add_log(novel_id, "StyleProfilerAgent", f"风格分析完成: perspective={result.style_config.perspective}, tone={result.style_config.tone}")
        return result
