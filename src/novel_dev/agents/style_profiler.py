from typing import List
from pydantic import BaseModel

from novel_dev.agents._llm_helpers import call_and_parse


class StyleConfig(BaseModel):
    sentence_patterns: dict = {}
    dialogue_style: dict = {}
    rhetoric_devices: list = []
    pacing: str = ""
    vocabulary_preferences: List[str] = []
    perspective: str = ""
    tone: str = ""
    evolution_notes: str = ""


class StyleProfile(BaseModel):
    style_guide: str
    style_config: StyleConfig


class StyleProfilerAgent:
    async def profile(self, text: str) -> StyleProfile:
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
        return await call_and_parse(
            "StyleProfilerAgent", "profile_style", prompt,
            StyleProfile.model_validate_json, max_retries=3
        )
