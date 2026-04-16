import re
from typing import Optional
from pydantic import BaseModel


class FileClassificationResult(BaseModel):
    file_type: str  # "setting" | "style_sample"
    confidence: float
    reason: str


class FileClassifier:
    SETTING_KEYWORDS = ["设定", "世界观", "大纲", "setting", "worldview", "outline"]
    STYLE_KEYWORDS = ["样本", "风格", "sample", "style"]

    def classify(self, filename: str, content_preview: str) -> FileClassificationResult:
        lower_name = filename.lower()
        lower_preview = content_preview[:500].lower()

        for kw in self.SETTING_KEYWORDS:
            if kw in lower_name:
                return FileClassificationResult(
                    file_type="setting",
                    confidence=0.95,
                    reason=f"Filename contains '{kw}'",
                )

        for kw in self.STYLE_KEYWORDS:
            if kw in lower_name:
                return FileClassificationResult(
                    file_type="style_sample",
                    confidence=0.95,
                    reason=f"Filename contains '{kw}'",
                )

        # Simple heuristic fallback
        if "修炼" in lower_preview or "境界" in lower_preview or "world" in lower_preview:
            return FileClassificationResult(
                file_type="setting",
                confidence=0.7,
                reason="Content heuristic matched setting terms",
            )

        return FileClassificationResult(
            file_type="style_sample",
            confidence=0.6,
            reason="Default fallback to style_sample",
        )
