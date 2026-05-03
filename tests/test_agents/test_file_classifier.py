from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.file_classifier import FileClassifier, FileClassificationResult
from novel_dev.llm.models import LLMResponse
from novel_dev.services.log_service import LogService


@pytest.fixture(autouse=True)
def clear_log_service_state():
    LogService._buffers.clear()
    LogService._listeners.clear()
    LogService._pending_tasks.clear()


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


@pytest.mark.asyncio
async def test_classify_markdown_setting_with_chapter_headings_as_setting_without_llm():
    mock_client = AsyncMock()

    setting_doc = "\n".join(
        [
            "# 第一章 人界设定",
            "世界观：人界灵气稀薄，修士以宗门和坊市为核心活动。",
            "修炼体系：炼气、筑基、结丹、元婴逐级推进。",
            "势力：黄枫谷、掩月宗、魔道六宗互相牵制。",
            "# 第二章 灵界设定",
            "物品：掌天瓶用于催熟灵药，是主角核心外挂。",
        ]
    )

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        classifier = FileClassifier()
        classification = await classifier.classify("凡人修仙传.md", setting_doc)

    assert classification.file_type == "setting"
    assert classification.confidence >= 0.85
    assert "设定资料标记" in classification.reason
    mock_client.acomplete.assert_not_called()


@pytest.mark.asyncio
async def test_classify_logs_filename_reason_and_structure_metadata():
    novel_text = "\n".join(
        [
            "第一章 少年游",
            "孟奇睁开眼时，只觉得耳畔钟声悠远。",
            "第二章 江湖夜雨",
            "长街尽头有人拔刀，刀光映得雨幕发白。",
        ]
    )

    classifier = FileClassifier()
    classification = await classifier.classify("凡人修仙传.md", novel_text, novel_id="novel-log")

    assert classification.file_type == "style_sample"
    entries = list(LogService._buffers["novel-log"])
    result_entry = next(entry for entry in entries if entry["message"].startswith("文件分类结果"))
    assert "凡人修仙传.md" in result_entry["message"]
    assert "检测到小说正文的章节结构" in result_entry["message"]
    assert result_entry["metadata"]["source_filename"] == "凡人修仙传.md"
    assert result_entry["metadata"]["classification_source"] == "structure"
    assert result_entry["metadata"]["chapter_heading_count"] == 2
