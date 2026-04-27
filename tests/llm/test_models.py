import pytest
from pydantic import ValidationError
from novel_dev.llm.models import ChatMessage, LLMResponse, StructuredOutputConfig, TokenUsage, TaskConfig, RetryConfig

def test_chat_message_creation():
    msg = ChatMessage(role="user", content="hello")
    assert msg.role == "user"
    assert msg.content == "hello"

def test_llm_response_with_usage():
    usage = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    resp = LLMResponse(text="hi", usage=usage)
    assert resp.text == "hi"
    assert resp.usage.prompt_tokens == 10

def test_task_config_defaults():
    cfg = TaskConfig(provider="anthropic", model="claude-opus-4-6")
    assert cfg.timeout == 30
    assert cfg.retries == 2
    assert cfg.temperature == 0.7

def test_retry_config():
    rc = RetryConfig(retries=3, timeout=60)
    assert rc.retries == 3
    assert rc.timeout == 60

def test_llm_response_with_reasoning_content():
    resp = LLMResponse(text="answer", reasoning_content="step-by-step reasoning")
    assert resp.text == "answer"
    assert resp.reasoning_content == "step-by-step reasoning"

def test_task_config_fallback_recursive():
    inner = TaskConfig(provider="openai", model="gpt-4")
    outer = TaskConfig(provider="anthropic", model="claude-opus-4-6", fallback=inner)
    assert outer.fallback is not None
    assert outer.fallback.provider == "openai"
    assert outer.fallback.model == "gpt-4"

def test_task_config_accepts_structured_output():
    cfg = TaskConfig(
        provider="anthropic",
        model="claude-opus-4-6",
        structured_output=StructuredOutputConfig(
            mode="anthropic_tool",
            schema_name="emit_payload",
            tool_choice="auto",
        ),
    )
    assert cfg.structured_output.mode == "anthropic_tool"
    assert cfg.structured_output.tool_choice == "auto"
    assert cfg.structured_output.fallback_to_text is True

def test_llm_response_with_structured_payload():
    resp = LLMResponse(text="", structured_payload={"answer": 42}, finish_reason="tool_use")
    assert resp.structured_payload == {"answer": 42}
    assert resp.finish_reason == "tool_use"

def test_invalid_chat_message_role():
    with pytest.raises(ValidationError):
        ChatMessage(role="foo", content="hello")
