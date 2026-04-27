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


class StructuredOutputConfig(BaseModel):
    mode: Literal["auto", "anthropic_tool", "openai_tool", "json_text"] = "auto"
    schema_name: str = "emit_payload"
    tool_choice: Literal["force", "auto", "none"] = "force"
    fallback_to_text: bool = True
    wrap_array: bool = False


class TaskConfig(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None
    timeout: int = 30
    retries: int = 2
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    api_key: Optional[str] = None
    structured_output: Optional[StructuredOutputConfig] = None
    response_tool_name: Optional[str] = None
    response_json_schema: Optional[dict[str, Any]] = None
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
