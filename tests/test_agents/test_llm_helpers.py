from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from novel_dev.agents._llm_helpers import call_and_parse, call_and_parse_model
from novel_dev.llm.models import LLMResponse


class ExamplePayload(BaseModel):
    title: str
    tags: list[str] = []


@pytest.mark.asyncio
async def test_call_and_parse_success():
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text='{"key": "value"}')

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await call_and_parse(
            "TestAgent", "test_task", "prompt",
            lambda text: {"key": "value"}, max_retries=3
        )

    assert result == {"key": "value"}


@pytest.mark.asyncio
async def test_call_and_parse_retry_on_validation_error():
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text="invalid json"),
        LLMResponse(text='{"key": "value"}'),
    ]

    def parser(text):
        import json
        return json.loads(text)

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await call_and_parse(
            "TestAgent", "test_task", "prompt",
            parser, max_retries=3
        )

    assert result == {"key": "value"}
    assert mock_client.acomplete.call_count == 2


@pytest.mark.asyncio
async def test_call_and_parse_raises_after_max_retries():
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="invalid json")

    def parser(text):
        import json
        return json.loads(text)

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        with pytest.raises(RuntimeError, match="LLM parse failed after 3 retries"):
            await call_and_parse(
                "TestAgent", "test_task", "prompt",
                parser, max_retries=3
            )

    assert mock_client.acomplete.call_count == 3


@pytest.mark.asyncio
async def test_call_and_parse_model_extracts_markdown_json_array():
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(
        text='''结果如下：\n```json\n[{"title": "主线", "tags": ["成长"]}]\n```'''
    )

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await call_and_parse_model(
            "TestAgent", "test_task", "prompt", list[ExamplePayload], max_retries=3
        )

    assert len(result) == 1
    assert result[0].title == "主线"
    assert result[0].tags == ["成长"]
