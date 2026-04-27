import re
from typing import Literal
from pydantic import BaseModel

from novel_dev.agents._llm_helpers import call_and_parse_model
from novel_dev.services.log_service import logged_agent_step, log_service


class FileClassificationResult(BaseModel):
    file_type: Literal["setting", "style_sample"]
    confidence: float
    reason: str


CHAPTER_HEADING_RE = re.compile(r"^\s*第[一二三四五六七八九十百千万\d]+[章节回卷部集]\b", re.MULTILINE)
BOOK_TITLE_TXT_RE = re.compile(r"《[^》]{1,80}》.*\.txt$", re.IGNORECASE)


class FileClassifier:
    def _classify_by_structure(self, filename: str, content_preview: str) -> FileClassificationResult | None:
        chapter_headings = CHAPTER_HEADING_RE.findall(content_preview[:20000])
        looks_like_book_txt = bool(BOOK_TITLE_TXT_RE.search(filename.strip()))
        prose_markers = sum(content_preview.count(marker) for marker in ("。", "，", "“", "”", "：", "？", "！"))

        if len(chapter_headings) >= 2 or (looks_like_book_txt and chapter_headings and prose_markers >= 8):
            return FileClassificationResult(
                file_type="style_sample",
                confidence=0.95,
                reason="检测到小说正文的章节结构，应作为风格样本处理",
            )

        return None

    @logged_agent_step("FileClassifier", "分类文件", node="file_classify", task="classify_file")
    async def classify(self, filename: str, content_preview: str, novel_id: str = "") -> FileClassificationResult:
        if novel_id:
            log_service.add_log(novel_id, "FileClassifier", f"开始分类文件: {filename}")

        structured_result = self._classify_by_structure(filename, content_preview)
        if structured_result is not None:
            if novel_id:
                log_service.add_log(
                    novel_id,
                    "FileClassifier",
                    f"文件分类结果: {structured_result.file_type} (置信度 {structured_result.confidence:.2f})",
                )
            return structured_result

        MAX_CHARS = 3000
        safe_filename = filename.replace("{", "{{").replace("}", "}}")[:200]
        safe_preview = content_preview.replace("{", "{{").replace("}", "}}")[:MAX_CHARS]
        prompt = (
            "你是一位文件分类专家。请根据文件名和内容片段，判断这是小说设定文档还是风格样本。"
            "返回严格符合 FileClassificationResult Schema 的 JSON：\n"
            "file_type: 'setting' 或 'style_sample'\n"
            "confidence: 0.0-1.0 的置信度\n"
            "reason: 分类理由（简短）\n\n"
            "分类规则：\n"
            "- setting: 世界观、人物卡、势力、地点、物品、修炼体系、术语表、剧情梗概等设定材料。\n"
            "- style_sample: 小说正文、章节文本、成书全文、作者作品片段、用于学习文风的样章。\n"
            "- 出现“第一章/第1章”等章节结构，或文件名像《书名》.txt 的正文文件，优先判为 style_sample。\n\n"
            f"文件名：{safe_filename}\n"
            f"内容片段：\n{safe_preview}"
        )
        result = await call_and_parse_model(
            "FileClassifier", "classify_file", prompt,
            FileClassificationResult, max_retries=3, novel_id=novel_id,
        )
        if novel_id:
            log_service.add_log(novel_id, "FileClassifier", f"文件分类结果: {result.file_type} (置信度 {result.confidence:.2f})")
        return result
