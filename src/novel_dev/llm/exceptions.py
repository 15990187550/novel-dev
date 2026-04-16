class LLMError(Exception):
    """Base exception for all LLM-layer failures."""


class LLMTimeoutError(LLMError):
    """Request exceeded configured timeout."""


class LLMRateLimitError(LLMError):
    """Hit rate limit or quota exceeded."""


class LLMContentPolicyError(LLMError):
    """Content filtered or blocked by provider safety policy."""


class LLMConfigError(LLMError):
    """Missing or invalid configuration (API key, model name, etc.)."""
