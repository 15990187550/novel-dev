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
