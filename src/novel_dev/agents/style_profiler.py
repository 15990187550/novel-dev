from typing import Any, List

from pydantic import BaseModel, Field, field_validator

from novel_dev.agents._llm_helpers import call_and_parse_model, coerce_to_str_list, coerce_to_text
from novel_dev.services.log_service import log_service


class StyleConfig(BaseModel):
    sentence_patterns: dict = Field(default_factory=dict)
    dialogue_style: dict = Field(default_factory=dict)
    rhetoric_devices: List[str] = Field(default_factory=list)
    pacing: str = ""
    vocabulary_preferences: List[str] = Field(default_factory=list)
    perspective: str = ""
    tone: str = ""
    evolution_notes: str = ""

    @field_validator("pacing", "perspective", "tone", "evolution_notes", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)

    @field_validator("rhetoric_devices", "vocabulary_preferences", mode="before")
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
        MAX_CHARS = 24000
        sampled = text[:MAX_CHARS]
        prompt = (
            "你是一位文学风格分析师。请分析以下小说文本的写作风格，"
            "返回严格符合 StyleProfile Schema 的 JSON：\n"
            "1. style_guide: 一段自然语言风格描述（100字以内）\n"
            "2. style_config:\n"
            "   - sentence_patterns: 句式特点（如 avg_length、complexity）\n"
            "   - dialogue_style: 对话风格（如 direct_speech_ratio、dialogue_tag_style）\n"
            "   - rhetoric_devices: 常用修辞手法\n"
            "   - pacing: 叙事节奏（fast/moderate/slow）\n"
            "   - vocabulary_preferences: 高频或特色词汇列表（5-10个）\n"
            "   - perspective: 叙事视角（first_person/limited/omniscient）\n"
            "   - tone: 整体基调（intense/dark/hopeful/romantic 等）\n"
            "   - evolution_notes: 风格演变迹象\n\n"
            f"文本样本：\n\n{sampled}"
        )
        result = await call_and_parse_model(
            "StyleProfilerAgent", "profile_style", prompt, StyleProfile, max_retries=3, novel_id=novel_id,
        )
        if novel_id:
            log_service.add_log(novel_id, "StyleProfilerAgent", f"风格分析完成: perspective={result.style_config.perspective}, tone={result.style_config.tone}")
        return result
