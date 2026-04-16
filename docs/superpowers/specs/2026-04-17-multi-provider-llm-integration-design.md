# Multi-Provider LLM Integration Design

> **Goal:** Build a unified multi-provider LLM client layer that replaces hard-coded stubs across all agents, supporting Anthropic Claude, OpenAI-compatible providers (GPT / Kimi / GLM), and MiniMax, with per-agent configuration, retry policies, and async usage tracking.

---

## 1. Architecture Overview

The system introduces a dedicated `llm/` package with four responsibilities:

1. **Driver layer** – One adapter per provider family (`anthropic`, `openai_compatible`, `minimax` placeholder). Each adapter translates a unified `ChatMessage`-based request into the provider’s native API call and returns a normalized `LLMResponse`.
2. **Factory layer** – `LLMFactory` reads `llm_config.yaml`, resolves the correct `TaskConfig` for an `(agent_name, task_name)` pair, and caches driver instances by `(provider, model, base_url, api_key)`.
3. **Resilience layer** – `RetryableDriver` applies per-task retry policies. `FallbackDriver` wraps a primary `RetryableDriver` and an optional fallback `RetryableDriver`; if the primary fails after all retries, the fallback model is invoked automatically.
4. **Tracking layer** – `UsageTracker` logs token consumption asynchronously after every call. The default implementation writes structured logs; a database-backed implementation can be swapped in later without touching agents.

Agents no longer contain stub logic. They call `llm_factory.get(agent_name, task=task_name)` and await `acomplete()`. The returned driver may transparently fallback to a backup model on failure.

---

## 2. File Structure

### New files

| File | Responsibility |
|------|----------------|
| `src/novel_dev/llm/__init__.py` | Package init, exports `llm_factory` singleton |
| `src/novel_dev/llm/models.py` | Pydantic models: `ChatMessage`, `LLMResponse`, `TokenUsage`, `TaskConfig`, `RetryConfig` |
| `src/novel_dev/llm/exceptions.py` | `LLMError` hierarchy: `LLMTimeoutError`, `LLMRateLimitError`, `LLMContentPolicyError`, `LLMConfigError` |
| `src/novel_dev/llm/drivers/base.py` | `BaseDriver` abstract class with `acomplete(messages, config) -> LLMResponse` |
| `src/novel_dev/llm/drivers/openai_compatible.py` | `OpenAICompatibleDriver` for GPT, Kimi, GLM, and any OpenAI-compatible endpoint |
| `src/novel_dev/llm/drivers/anthropic.py` | `AnthropicDriver` using the native Anthropic SDK |
| `src/novel_dev/llm/drivers/minimax.py` | `MinimaxDriver` (placeholder inheriting from `OpenAICompatibleDriver` for now, reserved for future native extension) |
| `src/novel_dev/llm/fallback_driver.py` | `FallbackDriver`: transparent failover from primary model to fallback model |
| `src/novel_dev/llm/factory.py` | `LLMFactory`: config loading, driver caching, retry wrapper injection, custom `user-agent` header setup |
| `src/novel_dev/llm/usage_tracker.py` | `UsageTracker` protocol / ABC, `LoggingUsageTracker` default implementation |
| `llm_config.yaml` | Per-agent and per-task LLM configuration (non-sensitive only) |

### Modified files

| File | Change |
|------|--------|
| `src/novel_dev/config.py` | Add `llm_config_path`, `llm_user_agent`, and provider API key fields to `Settings` |
| `src/novel_dev/agents/librarian.py` | Replace `_call_llm` dummy implementation with real factory call |
| `src/novel_dev/agents/brainstorm_agent.py` | Replace `_generate_synopsis` TODO with real factory call |

---

## 3. Data Models

```python
from typing import Literal
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
    reasoning_content: str | None = None
    usage: TokenUsage | None = None

class TaskConfig(BaseModel):
    provider: str
    model: str
    base_url: str | None = None
    timeout: int = 30
    retries: int = 2
    temperature: float = 0.7
    max_tokens: int | None = None
    fallback: "TaskConfig" | None = None


class RetryConfig(BaseModel):
    retries: int = 2
    timeout: int = 30
```

---

## 4. Exception Hierarchy

```python
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
```

All drivers must catch provider-specific SDK exceptions and re-raise as the appropriate `LLMError` subclass.

---

## 5. Driver Interface

```python
from abc import ABC, abstractmethod

class BaseDriver(ABC):
    @abstractmethod
    async def acomplete(
        self,
        messages: str | list[ChatMessage],
        config: TaskConfig,
    ) -> LLMResponse:
        """
        Accepts either a plain string (auto-wrapped as user message)
        or a list of ChatMessage, and returns a normalized LLMResponse.
        """
```

### 5.1 OpenAICompatibleDriver

- Uses `openai.AsyncOpenAI` client.
- Accepts `base_url`, `api_key`, `timeout`.
- Translates `messages` to OpenAI `chat.completions.create(messages=[...])`.
- Extracts `content` and `usage` from response.

### 5.2 AnthropicDriver

- Uses `anthropic.AsyncAnthropic` client.
- Accepts `api_key`, `timeout`.
- Translates `messages` to Anthropic `messages.create(model=..., messages=[...])`.
- System messages are extracted and passed via the `system` parameter.
- Extracts `content[0].text` and `usage` from response.

### 5.3 MinimaxDriver (placeholder)

- Inherits from `OpenAICompatibleDriver`.
- Reserved for future native MiniMax SDK integration without breaking existing consumers.

---

## 6. Retry, Timeout & Fallback Layer

### 6.1 RetryableDriver

`RetryableDriver` wraps any `BaseDriver` and applies runtime retry logic using `tenacity.AsyncRetrying`.

```python
import tenacity

class RetryableDriver(BaseDriver):
    def __init__(
        self,
        inner: BaseDriver,
        retry_config: RetryConfig,
        usage_tracker: UsageTracker | None = None,
        agent: str | None = None,
        task: str | None = None,
    ):
        self.inner = inner
        self.retry_config = retry_config
        self.usage_tracker = usage_tracker
        self.agent = agent
        self.task = task

    async def acomplete(self, messages, config: TaskConfig) -> LLMResponse:
        retryer = tenacity.AsyncRetrying(
            stop=tenacity.stop_after_attempt(self.retry_config.retries),
            retry=tenacity.retry_if_exception_type((LLMRateLimitError, LLMTimeoutError)),
            wait=tenacity.wait_exponential(multiplier=1, min=2, max=10),
            reraise=True,
        )
        response = await retryer(self.inner.acomplete, messages, config)
        if self.usage_tracker and response.usage:
            asyncio.create_task(
                self.usage_tracker.log(agent=self.agent, task=self.task, usage=response.usage)
            )
        return response
```

`LLMContentPolicyError` and `LLMConfigError` are **not** retried.

### 6.2 FallbackDriver

`FallbackDriver` wraps a primary `RetryableDriver` and an optional fallback `RetryableDriver`. When the primary fails after all retries, the fallback model is invoked transparently.

```python
class FallbackDriver(BaseDriver):
    def __init__(
        self,
        primary: BaseDriver,
        fallback: BaseDriver | None,
        fallback_config: TaskConfig | None = None,
        usage_tracker: UsageTracker | None = None,
        agent: str | None = None,
        task: str | None = None,
    ):
        self.primary = primary
        self.fallback = fallback
        self.fallback_config = fallback_config
        self.usage_tracker = usage_tracker
        self.agent = agent
        self.task = task

    async def acomplete(self, messages, config: TaskConfig) -> LLMResponse:
        try:
            return await self.primary.acomplete(messages, config)
        except LLMConfigError:
            raise
        except LLMError as exc:
            if self.fallback is None or self.fallback_config is None:
                raise
            if self.usage_tracker:
                asyncio.create_task(
                    self.usage_tracker.log(
                        agent=self.agent,
                        task=self.task,
                        usage=None,
                        meta={"event": "fallback_triggered", "reason": str(exc)},
                    )
                )
            return await self.fallback.acomplete(messages, self.fallback_config)
```

**Fallback rules:**
- `LLMConfigError` is **not** fall-backed (bad config should fail fast).
- Any other `LLMError` subclass (`LLMTimeoutError`, `LLMRateLimitError`, `LLMContentPolicyError`) triggers fallback.
- The fallback call uses the **fallback model's own** `TaskConfig` (provider, model, temperature, retries, etc.).

---

## 7. Factory Behavior

```python
class LLMFactory:
    def __init__(self, settings: Settings, usage_tracker: UsageTracker | None = None):
        self.settings = settings
        self.usage_tracker = usage_tracker or LoggingUsageTracker()
        self._config = self._load_yaml(settings.llm_config_path)
        self._cache: dict[tuple, BaseDriver] = {}

    def get(self, agent_name: str, task: str | None = None) -> BaseDriver:
        task_cfg = self._resolve_config(agent_name, task)
        primary = self._build_retryable_driver(task_cfg, agent_name, task)

        fallback_driver = None
        if task_cfg.fallback:
            fallback_driver = self._build_retryable_driver(task_cfg.fallback, agent_name, task)

        if fallback_driver:
            from novel_dev.llm.fallback_driver import FallbackDriver
            return FallbackDriver(
                primary=primary,
                fallback=fallback_driver,
                fallback_config=task_cfg.fallback,
                usage_tracker=self.usage_tracker,
                agent=agent_name,
                task=task,
            )
        return primary

    def _build_retryable_driver(self, config: TaskConfig, agent_name: str, task: str | None) -> BaseDriver:
        inner = self._get_cached_driver(config)
        retry_cfg = RetryConfig(retries=config.retries, timeout=config.timeout)
        return RetryableDriver(
            inner=inner,
            retry_config=retry_cfg,
            usage_tracker=self.usage_tracker,
            agent=agent_name,
            task=task,
        )
```

### 7.1 Config resolution order

For `(agent_name, task)`:

1. `agents.{agent_name}.tasks.{task}`
2. `agents.{agent_name}`
3. `defaults`

Missing required fields (`provider`, `model`) at any level raise `LLMConfigError`.

### 7.2 Driver caching

Cache key: `(provider, model, base_url, api_key)`.

A shared `httpx.AsyncClient` with custom headers (`X-Custom-User-Agent: {settings.llm_user_agent}`) is injected into each provider client and reused across calls.

### 7.3 API key resolution

Factory maps `provider` to a fixed `Settings` field:

| provider | Settings field |
|----------|----------------|
| `anthropic` | `anthropic_api_key` |
| `openai_compatible` | inferred from `base_url`. Known hosts map as follows: OpenAI (`api.openai.com`) → `openai_api_key`, Moonshot (`api.moonshot.cn`) → `moonshot_api_key`, Zhipu (`open.bigmodel.cn`) → `zhipu_api_key`. Any unrecognized `base_url` falls back to `openai_api_key`. |
| `minimax` | `minimax_api_key` |

If the resolved key is missing or empty, raise `LLMConfigError`.

---

## 8. Usage Tracking

```python
from typing import Protocol

class UsageTracker(Protocol):
    async def log(self, agent: str, task: str | None, usage: TokenUsage) -> None:
        ...

class LoggingUsageTracker:
    async def log(self, agent: str, task: str | None, usage: TokenUsage) -> None:
        logger.info(
            "llm_usage",
            extra={"agent": agent, "task": task, "usage": usage.model_dump()},
        )
```

`RetryableDriver` holds a reference to the `UsageTracker` provided by the factory. On a successful call, it fires `asyncio.create_task(self.usage_tracker.log(...))` so that logging never blocks the LLM response.

---

## 9. Configuration Example (`llm_config.yaml`)

```yaml
defaults:
  provider: openai_compatible
  timeout: 30
  retries: 2
  temperature: 0.7

agents:
  brainstorm_agent:
    provider: anthropic
    model: claude-opus-4-6
    timeout: 120
    retries: 3
    temperature: 0.8
    fallback:
      provider: openai_compatible
      model: gpt-4.1
      base_url: https://api.openai.com/v1
      timeout: 60
      retries: 2

  volume_planner_agent:
    provider: openai_compatible
    model: kimi-k2.5
    base_url: https://api.moonshot.cn/v1
    timeout: 60
    tasks:
      score_outline:
        model: gpt-4.1
        provider: openai_compatible
        base_url: https://api.openai.com/v1
        timeout: 30

  writer_agent:
    provider: minimax
    model: MiniMax-Text-01
    base_url: https://api.minimax.chat/v1
    timeout: 60
```

---

## 10. Agent Migration Strategy

We do **not** migrate all 8 agents in one batch. The plan is split into two milestones:

### Milestone 1: Infrastructure + first two agents
- Build the entire `llm/` package.
- Migrate `LibrarianAgent` (simplest string-to-string replacement).
- Migrate `BrainstormAgent` (`_generate_synopsis`).

### Milestone 2: Remaining agents (future plan)
- `WriterAgent`
- `VolumePlannerAgent`
- `CriticAgent`
- `EditorAgent`
- `FastReviewAgent`
- `StyleProfilerAgent`

Each migration introduces an internal `_call_llm(messages, task=None)` helper that wraps the factory.

---

## 11. Testing Strategy

### Unit tests (no external calls)
- `tests/llm/test_factory.py` – mock driver registry, verify config fallback logic, cache hits, exception translation, missing-key errors, and **fallback model resolution**.
- `tests/llm/test_retryable_driver.py` – mock a failing inner driver, assert tenacity retry behavior for `LLMRateLimitError` and no retry for `LLMConfigError`.
- `tests/llm/test_fallback_driver.py` – assert primary failure triggers fallback on `LLMRateLimitError`/`LLMTimeoutError`, `LLMConfigError` bypasses fallback, and fallback success returns valid `LLMResponse`.
- `tests/llm/test_models.py` – serialization round-trips for `TaskConfig`, `LLMResponse`, `ChatMessage`.

### Agent migration tests
- `tests/agents/test_librarian.py` – mock `LLMFactory.get`, assert `_call_llm` sends expected prompt and parses `LLMResponse.text`.
- `tests/agents/test_brainstorm_agent.py` – mock factory, assert `_generate_synopsis` constructs the correct system + user messages.

### Integration tests (optional, skipped by default)
- `tests/llm/integration/test_anthropic_driver.py`
- `tests/llm/integration/test_openai_compatible_driver.py`

These are guarded by `pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"))` and send a minimal "hello" prompt to verify end-to-end connectivity.

---

## 12. Security

- API keys live **only** in `.env` and are loaded through `pydantic-settings`.
- `llm_config.yaml` contains **no secrets**.
- Custom `user-agent` is injected at the shared `httpx.AsyncClient` level and cannot be overridden per-task.
- No API key is ever logged.
