from typing import Any, List

from pydantic import BaseModel, Field, field_validator

from novel_dev.agents._llm_helpers import call_and_parse_model, coerce_to_str_list, coerce_to_text
from novel_dev.services.log_service import log_service


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


class StyleProfilerAgent:
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
            "- 输出要具体、可执行，避免空泛评论。\n"
            "- 如果原文幽默与庄重并存，要说明切换条件。\n"
            "- scene_preferences 和 information_reveal 要服务'如何写正文'，不是文学赏析。\n\n"
            f"文本样本：\n\n{sampled}"
        )
        result = await call_and_parse_model(
            "StyleProfilerAgent", "profile_style", prompt, StyleProfile, max_retries=3, novel_id=novel_id,
        )
        if novel_id:
            log_service.add_log(novel_id, "StyleProfilerAgent", f"风格分析完成: perspective={result.style_config.perspective}, tone={result.style_config.tone}")
        return result
