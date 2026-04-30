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
SETTING_MARKER_RE = re.compile(
    r"(?im)^\s*(?:[#>*-]+\s*)?[\"'“”‘’]?"
    r"(世界观|人物(?:设定|卡|关系)?|角色(?:设定)?|主角|势力|门派|宗门|地点|地理|地图|"
    r"物品|法宝|功法|修炼(?:体系)?|境界|等级体系|术语|剧情(?:梗概|大纲)?|大纲|设定|"
    r"能力|关系|外挂|特征|背景|significance)"
    r"[\"'“”‘’]?\s*(?:[:：]|$)"
)


def _source_metadata(filename: str = "") -> dict[str, str]:
    filename = (filename or "").strip()
    return {"source_filename": filename} if filename else {}


def _classification_metadata(arguments: dict) -> dict[str, str]:
    return _source_metadata(str(arguments.get("filename") or ""))


class FileClassifier:
    def _structure_signals(self, filename: str, content_preview: str) -> dict:
        preview = content_preview[:20000]
        chapter_headings = CHAPTER_HEADING_RE.findall(preview)
        setting_markers = SETTING_MARKER_RE.findall(preview)
        return {
            "chapter_heading_count": len(chapter_headings),
            "looks_like_book_txt": bool(BOOK_TITLE_TXT_RE.search(filename.strip())),
            "prose_markers": sum(preview.count(marker) for marker in ("。", "，", "“", "”", "：", "？", "！")),
            "setting_marker_count": len(setting_markers),
            "setting_markers": list(dict.fromkeys(setting_markers))[:10],
        }

    def _classify_by_structure(self, filename: str, content_preview: str) -> FileClassificationResult | None:
        signals = self._structure_signals(filename, content_preview)
        chapter_heading_count = int(signals["chapter_heading_count"])
        looks_like_book_txt = bool(signals["looks_like_book_txt"])
        prose_markers = int(signals["prose_markers"])
        setting_marker_count = int(signals["setting_marker_count"])

        if setting_marker_count >= 2:
            return FileClassificationResult(
                file_type="setting",
                confidence=0.90,
                reason="检测到设定资料标记，应作为设定文档处理",
            )

        if chapter_heading_count >= 2 or (looks_like_book_txt and chapter_heading_count and prose_markers >= 8):
            return FileClassificationResult(
                file_type="style_sample",
                confidence=0.95,
                reason="检测到小说正文的章节结构，应作为风格样本处理",
            )

        return None

    def _log_result(
        self,
        novel_id: str,
        filename: str,
        result: FileClassificationResult,
        *,
        classification_source: str,
        structure_signals: dict | None = None,
    ) -> None:
        if not novel_id:
            return
        metadata = {
            **_source_metadata(filename),
            "classification_source": classification_source,
            "classification_reason": result.reason,
            "file_type": result.file_type,
            "confidence": result.confidence,
        }
        if structure_signals:
            metadata.update(structure_signals)
        log_service.add_log(
            novel_id,
            "FileClassifier",
            f"文件分类结果: {result.file_type} (置信度 {result.confidence:.2f})，原因: {result.reason}",
            metadata=metadata,
        )

    @logged_agent_step(
        "FileClassifier",
        "分类文件",
        node="file_classify",
        task="classify_file",
        metadata_builder=_classification_metadata,
    )
    async def classify(self, filename: str, content_preview: str, novel_id: str = "") -> FileClassificationResult:
        if novel_id:
            log_service.add_log(
                novel_id,
                "FileClassifier",
                f"开始分类文件: {filename}",
                metadata=_source_metadata(filename),
            )

        structure_signals = self._structure_signals(filename, content_preview)
        structured_result = self._classify_by_structure(filename, content_preview)
        if structured_result is not None:
            self._log_result(
                novel_id,
                filename,
                structured_result,
                classification_source="structure",
                structure_signals=structure_signals,
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
            "- 出现“第一章/第1章”等章节结构，或文件名像《书名》.txt 的正文文件，若内容是连续正文叙事，优先判为 style_sample。\n"
            "- 若章节标题只是设定文档的分节，且内容包含世界观、人物、势力、地点、物品、修炼体系、术语、剧情梗概等设定标记，应判为 setting。\n\n"
            f"文件名：{safe_filename}\n"
            f"内容片段：\n{safe_preview}"
        )
        result = await call_and_parse_model(
            "FileClassifier", "classify_file", prompt,
            FileClassificationResult, max_retries=3, novel_id=novel_id,
            context_metadata=_source_metadata(filename),
        )
        self._log_result(novel_id, filename, result, classification_source="llm")
        return result
