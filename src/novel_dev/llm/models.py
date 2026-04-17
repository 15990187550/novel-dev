from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel


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


class TaskConfig(BaseModel):
    provider: str
    model: str
    base_url: Optional[str] = None
    timeout: int = 30
    retries: int = 2
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    fallback: Optional["TaskConfig"] = None


class RetryConfig(BaseModel):
    retries: int = 2
    timeout: int = 30
