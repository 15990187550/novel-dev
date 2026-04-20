from typing import Literal
from pydantic import BaseModel

from novel_dev.agents._llm_helpers import call_and_parse
from novel_dev.services.log_service import log_service


class FileClassificationResult(BaseModel):
    file_type: Literal["setting", "style_sample"]
    confidence: float
    reason: str


class FileClassifier:
    async def classify(self, filename: str, content_preview: str, novel_id: str = "") -> FileClassificationResult:
        if novel_id:
            log_service.add_log(novel_id, "FileClassifier", f"开始分类文件: {filename}")
        MAX_CHARS = 3000
        safe_filename = filename.replace("{", "{{").replace("}", "}}")[:200]
        safe_preview = content_preview.replace("{", "{{").replace("}", "}}")[:MAX_CHARS]
        prompt = (
            "你是一位文件分类专家。请根据文件名和内容片段，判断这是小说设定文档还是风格样本。"
            "返回严格符合 FileClassificationResult Schema 的 JSON：\n"
            "file_type: 'setting' 或 'style_sample'\n"
            "confidence: 0.0-1.0 的置信度\n"
            "reason: 分类理由（简短）\n\n"
            f"文件名：{safe_filename}\n"
            f"内容片段：\n{safe_preview}"
        )
        result = await call_and_parse(
            "FileClassifier", "classify_file", prompt,
            FileClassificationResult.model_validate_json, max_retries=3, novel_id=novel_id,
        )
        if novel_id:
            log_service.add_log(novel_id, "FileClassifier", f"文件分类结果: {result.file_type} (置信度 {result.confidence:.2f})")
        return result
