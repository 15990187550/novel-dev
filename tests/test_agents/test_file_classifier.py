from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.file_classifier import FileClassifier, FileClassificationResult
from novel_dev.llm.models import LLMResponse


@pytest.mark.asyncio
async def test_classify_setting():
    result = FileClassificationResult(file_type="setting", confidence=0.95, reason="设定文档")
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text=result.model_dump_json())

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        classifier = FileClassifier()
        classification = await classifier.classify("setting.txt", "世界观内容")

    assert classification.file_type == "setting"
    assert classification.confidence == 0.95


@pytest.mark.asyncio
async def test_classify_full_novel_text_as_style_sample_without_llm():
    mock_client = AsyncMock()

    novel_text = "\n".join(
        [
            "第一章 少年游",
            "孟奇睁开眼时，只觉得耳畔钟声悠远。",
            "他低声道：这是什么地方？",
            "第二章 江湖夜雨",
            "长街尽头有人拔刀，刀光映得雨幕发白。",
        ]
    )

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        classifier = FileClassifier()
        classification = await classifier.classify("《一世之尊》-+爱潜水的乌贼.txt", novel_text)

    assert classification.file_type == "style_sample"
    assert classification.confidence >= 0.9
    mock_client.acomplete.assert_not_called()
