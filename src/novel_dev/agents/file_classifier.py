from typing import Literal
from pydantic import BaseModel

from novel_dev.agents._llm_helpers import call_and_parse


class FileClassificationResult(BaseModel):
    file_type: Literal["setting", "style_sample"]
    confidence: float
    reason: str


class FileClassifier:
    async def classify(self, filename: str, content_preview: str) -> FileClassificationResult:
        MAX_CHARS = 3000
        prompt = (
            "你是一位文件分类专家。请根据文件名和内容片段，判断这是小说设定文档还是风格样本。"
            "返回严格符合 FileClassificationResult Schema 的 JSON：\n"
            "file_type: 'setting' 或 'style_sample'\n"
            "confidence: 0.0-1.0 的置信度\n"
            "reason: 分类理由（简短）\n\n"
            f"文件名：{filename}\n"
            f"内容片段：\n{content_preview[:MAX_CHARS]}"
        )
        return await call_and_parse(
            "FileClassifier", "classify_file", prompt,
            FileClassificationResult.model_validate_json, max_retries=3
        )
