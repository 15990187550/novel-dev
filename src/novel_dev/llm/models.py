from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class TokenUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class LLMResponse(BaseModel):
    text: str
    reasoning_content: Optional[str] = None
    usage: Optional["TokenUsage"] = None
    structured_payload: Optional[Any] = None
    finish_reason: Optional[str] = None
    tool_calls: list["LLMToolCall"] = Field(default_factory=list)


class LLMToolCall(BaseModel):
    id: Optional[str] = None
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class LLMToolResult(BaseModel):
    tool_call_id: Optional[str] = None
    name: str
    content: Any
    is_error: bool = False


class StructuredOutputConfig(BaseModel):
    mode: Literal["auto", "anthropic_tool", "openai_tool", "json_text"] = "auto"
    schema_name: str = "emit_payload"
    tool_choice: Literal["force", "auto", "none"] = "force"
    fallback_to_text: bool = True
    wrap_array: bool = False


class CapabilityToolConfig(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})


class TaskConfig(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None
    timeout: int = 30
    retries: int = 2
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    api_key_env: Optional[str] = None
    api_key: Optional[str] = None
    structured_output: Optional[StructuredOutputConfig] = None
    response_tool_name: Optional[str] = None
    response_json_schema: Optional[dict[str, Any]] = None
    capability_tools: list[CapabilityToolConfig] = Field(default_factory=list)
    fallback: Optional["TaskConfig"] = None


class RetryConfig(BaseModel):
    retries: int = 2
    timeout: int = 30


class EmbeddingConfig(BaseModel):
    provider: str
    model: str
    base_url: Optional[str] = None
    timeout: int = 30
    retries: int = 3
    dimensions: int = Field(default=1024, gt=0)
