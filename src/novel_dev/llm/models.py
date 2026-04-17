from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator


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


class EmbeddingConfig(BaseModel):
    provider: str
    model: str
    base_url: Optional[str] = None
    timeout: int = 30
    retries: int = 3
    dimensions: int = Field(default=1536, gt=0)

    @field_validator("dimensions")
    @classmethod
    def validate_dimensions(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("dimensions must be positive")
        return v
