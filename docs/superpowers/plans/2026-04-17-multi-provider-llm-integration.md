# Multi-Provider LLM Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the unified `llm/` package and migrate `LibrarianAgent` and `BrainstormAgent` to use real LLM calls via factory-based configuration.

**Architecture:** A driver-adapter layer (`BaseDriver`, `OpenAICompatibleDriver`, `AnthropicDriver`) sits behind `LLMFactory`, which reads `llm_config.yaml` and wraps drivers with `RetryableDriver` for per-task retry policies. `UsageTracker` logs token consumption asynchronously. Agents obtain a driver instance from the factory singleton and call `acomplete()`.

**Tech Stack:** Python 3.9+, Pydantic v2, `openai`, `anthropic`, `tenacity`, `pyyaml`, `pytest-asyncio`

---

## File Structure

### New files
- `src/novel_dev/llm/__init__.py`
- `src/novel_dev/llm/models.py`
- `src/novel_dev/llm/exceptions.py`
- `src/novel_dev/llm/drivers/__init__.py`
- `src/novel_dev/llm/drivers/base.py`
- `src/novel_dev/llm/drivers/openai_compatible.py`
- `src/novel_dev/llm/drivers/anthropic.py`
- `src/novel_dev/llm/drivers/minimax.py`
- `src/novel_dev/llm/usage_tracker.py`
- `src/novel_dev/llm/factory.py`
- `llm_config.yaml`
- `tests/llm/test_models.py`
- `tests/llm/test_openai_compatible_driver.py`
- `tests/llm/test_anthropic_driver.py`
- `tests/llm/test_usage_tracker.py`
- `tests/llm/test_factory.py`

### Modified files
- `pyproject.toml`
- `src/novel_dev/config.py`
- `src/novel_dev/agents/librarian.py`
- `src/novel_dev/agents/brainstorm_agent.py`
- `tests/test_agents/test_librarian.py`
- `tests/test_agents/test_brainstorm_agent.py`

---

### Task 1: Add Dependencies and Extend Settings

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/novel_dev/config.py`
- Test: existing test suite (smoke)

- [ ] **Step 1: Add LLM dependencies to pyproject.toml**

In `[project.dependencies]`, append:
```toml
    "anthropic>=0.28.0",
    "openai>=1.30.0",
    "tenacity>=8.3.0",
    "pyyaml>=6.0",
```

- [ ] **Step 2: Extend Settings class**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    database_url: str = "postgresql+asyncpg://localhost/novel_dev"
    markdown_output_dir: str = "./novel_output"
    llm_config_path: str = "./llm_config.yaml"
    llm_user_agent: str = "novel-dev/1.0"

    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    moonshot_api_key: str | None = None
    minimax_api_key: str | None = None
    zhipu_api_key: str | None = None
```

- [ ] **Step 3: Reinstall package with new dependencies**

Run: `python3 -m pip install -e ".[dev]"`
Expected: installs `anthropic`, `openai`, `tenacity`, `pyyaml` successfully

- [ ] **Step 4: Run existing tests to ensure no regressions**

Run: `python3 -m pytest tests/ -q --ignore=tests/test_integration_end_to_end.py`
Expected: all existing tests pass (currently 100+)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/novel_dev/config.py
git commit -m "chore: add LLM dependencies and settings fields"
```

---

### Task 2: LLM Data Models and Exceptions

**Files:**
- Create: `src/novel_dev/llm/models.py`
- Create: `src/novel_dev/llm/exceptions.py`
- Create: `src/novel_dev/llm/__init__.py`
- Test: `tests/llm/test_models.py`

- [ ] **Step 1: Write failing model tests**

Create `tests/llm/test_models.py`:
```python
from novel_dev.llm.models import ChatMessage, LLMResponse, TokenUsage, TaskConfig, RetryConfig

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/llm/test_models.py -v`
Expected: `ModuleNotFoundError: No module named 'novel_dev.llm.models'`

- [ ] **Step 3: Implement models and exceptions**

Create `src/novel_dev/llm/models.py`:
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


class RetryConfig(BaseModel):
    retries: int = 2
    timeout: int = 30
```

Create `src/novel_dev/llm/exceptions.py`:
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

Create `src/novel_dev/llm/__init__.py`:
```python
from novel_dev.llm.exceptions import (
    LLMError,
    LLMConfigError,
    LLMContentPolicyError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from novel_dev.llm.models import ChatMessage, LLMResponse, RetryConfig, TaskConfig, TokenUsage

__all__ = [
    "LLMError",
    "LLMConfigError",
    "LLMContentPolicyError",
    "LLMRateLimitError",
    "LLMTimeoutError",
    "ChatMessage",
    "LLMResponse",
    "RetryConfig",
    "TaskConfig",
    "TokenUsage",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/llm/test_models.py -v`
Expected: 4 tests pass

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/llm/ tests/llm/test_models.py
git commit -m "feat(llm): add core models and exceptions"
```

---

### Task 3: BaseDriver and OpenAICompatibleDriver

**Files:**
- Create: `src/novel_dev/llm/drivers/__init__.py`
- Create: `src/novel_dev/llm/drivers/base.py`
- Create: `src/novel_dev/llm/drivers/openai_compatible.py`
- Test: `tests/llm/test_openai_compatible_driver.py`

- [ ] **Step 1: Write failing driver tests**

Create `tests/llm/test_openai_compatible_driver.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from novel_dev.llm.drivers.openai_compatible import OpenAICompatibleDriver
from novel_dev.llm.models import ChatMessage, LLMResponse, TaskConfig, TokenUsage


@pytest.mark.asyncio
async def test_openai_compatible_acomplete_with_string():
    mock_client = MagicMock()
    mock_chat = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content="hello"))],
            usage=MagicMock(prompt_tokens=2, completion_tokens=1, total_tokens=3),
        )
    )
    driver = OpenAICompatibleDriver(client=mock_client)
    config = TaskConfig(provider="openai_compatible", model="gpt-4")
    response = await driver.acomplete("say hi", config)
    assert response.text == "hello"
    assert response.usage.total_tokens == 3


@pytest.mark.asyncio
async def test_openai_compatible_acomplete_with_messages():
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content="world"))],
            usage=MagicMock(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        )
    )
    driver = OpenAICompatibleDriver(client=mock_client)
    config = TaskConfig(provider="openai_compatible", model="kimi-k2.5")
    messages = [ChatMessage(role="system", content="sys"), ChatMessage(role="user", content="usr")]
    response = await driver.acomplete(messages, config)
    assert response.text == "world"
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "kimi-k2.5"
    assert call_kwargs["messages"][0]["role"] == "system"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/llm/test_openai_compatible_driver.py -v`
Expected: `ModuleNotFoundError: No module named 'novel_dev.llm.drivers.openai_compatible'`

- [ ] **Step 3: Implement BaseDriver and OpenAICompatibleDriver**

Create `src/novel_dev/llm/drivers/__init__.py`:
```python
from novel_dev.llm.drivers.base import BaseDriver
from novel_dev.llm.drivers.openai_compatible import OpenAICompatibleDriver

__all__ = ["BaseDriver", "OpenAICompatibleDriver"]
```

Create `src/novel_dev/llm/drivers/base.py`:
```python
from abc import ABC, abstractmethod

from novel_dev.llm.models import LLMResponse, TaskConfig


class BaseDriver(ABC):
    @abstractmethod
    async def acomplete(
        self,
        messages: str | list,
        config: TaskConfig,
    ) -> LLMResponse:
        """
        Accepts either a plain string (auto-wrapped as user message)
        or a list of ChatMessage, and returns a normalized LLMResponse.
        """
```

Create `src/novel_dev/llm/drivers/openai_compatible.py`:
```python
from openai import AsyncOpenAI

from novel_dev.llm.drivers.base import BaseDriver
from novel_dev.llm.models import ChatMessage, LLMResponse, TaskConfig, TokenUsage


class OpenAICompatibleDriver(BaseDriver):
    def __init__(self, client: AsyncOpenAI | None = None):
        self._client = client

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            raise RuntimeError("OpenAICompatibleDriver client not initialized")
        return self._client

    async def acomplete(self, messages: str | list[ChatMessage], config: TaskConfig) -> LLMResponse:
        if isinstance(messages, str):
            msgs = [{"role": "user", "content": messages}]
        else:
            msgs = [{"role": m.role, "content": m.content} for m in messages]

        resp = await self.client.chat.completions.create(
            model=config.model,
            messages=msgs,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout=config.timeout,
        )
        content = resp.choices[0].message.content or ""
        usage = None
        if resp.usage:
            usage = TokenUsage(
                prompt_tokens=resp.usage.prompt_tokens,
                completion_tokens=resp.usage.completion_tokens,
                total_tokens=resp.usage.total_tokens,
            )
        return LLMResponse(text=content, usage=usage)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/llm/test_openai_compatible_driver.py -v`
Expected: 2 tests pass

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/llm/drivers/ tests/llm/test_openai_compatible_driver.py
git commit -m "feat(llm): add BaseDriver and OpenAICompatibleDriver"
```

---

### Task 4: AnthropicDriver and MinimaxDriver

**Files:**
- Create: `src/novel_dev/llm/drivers/anthropic.py`
- Create: `src/novel_dev/llm/drivers/minimax.py`
- Modify: `src/novel_dev/llm/drivers/__init__.py`
- Test: `tests/llm/test_anthropic_driver.py`

- [ ] **Step 1: Write failing Anthropic driver tests**

Create `tests/llm/test_anthropic_driver.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from novel_dev.llm.drivers.anthropic import AnthropicDriver
from novel_dev.llm.models import ChatMessage, LLMResponse, TaskConfig


@pytest.mark.asyncio
async def test_anthropic_acomplete_with_string():
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=MagicMock(
            content=[MagicMock(text="anthropic says hi")],
            usage=MagicMock(input_tokens=4, output_tokens=2),
        )
    )
    driver = AnthropicDriver(client=mock_client)
    config = TaskConfig(provider="anthropic", model="claude-opus-4-6")
    response = await driver.acomplete("say hi", config)
    assert response.text == "anthropic says hi"
    assert response.usage.prompt_tokens == 4


@pytest.mark.asyncio
async def test_anthropic_acomplete_extracts_system_message():
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=MagicMock(
            content=[MagicMock(text="ok")],
            usage=MagicMock(input_tokens=2, output_tokens=1),
        )
    )
    driver = AnthropicDriver(client=mock_client)
    config = TaskConfig(provider="anthropic", model="claude-sonnet")
    messages = [
        ChatMessage(role="system", content="be helpful"),
        ChatMessage(role="user", content="hello"),
    ]
    await driver.acomplete(messages, config)
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["system"] == "be helpful"
    assert call_kwargs["messages"][0]["role"] == "user"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/llm/test_anthropic_driver.py -v`
Expected: `ModuleNotFoundError: No module named 'novel_dev.llm.drivers.anthropic'`

- [ ] **Step 3: Implement AnthropicDriver and MinimaxDriver**

Create `src/novel_dev/llm/drivers/anthropic.py`:
```python
from anthropic import AsyncAnthropic

from novel_dev.llm.drivers.base import BaseDriver
from novel_dev.llm.models import ChatMessage, LLMResponse, TaskConfig, TokenUsage


class AnthropicDriver(BaseDriver):
    def __init__(self, client: AsyncAnthropic | None = None):
        self._client = client

    @property
    def client(self) -> AsyncAnthropic:
        if self._client is None:
            raise RuntimeError("AnthropicDriver client not initialized")
        return self._client

    async def acomplete(self, messages: str | list[ChatMessage], config: TaskConfig) -> LLMResponse:
        if isinstance(messages, str):
            msgs = [{"role": "user", "content": messages}]
            system = None
        else:
            system_msgs = [m.content for m in messages if m.role == "system"]
            system = system_msgs[0] if system_msgs else None
            msgs = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]

        resp = await self.client.messages.create(
            model=config.model,
            messages=msgs,
            system=system,
            max_tokens=config.max_tokens or 4096,
            timeout=config.timeout,
        )
        content = resp.content[0].text if resp.content else ""
        usage = None
        if resp.usage:
            usage = TokenUsage(
                prompt_tokens=resp.usage.input_tokens,
                completion_tokens=resp.usage.output_tokens,
                total_tokens=resp.usage.input_tokens + resp.usage.output_tokens,
            )
        return LLMResponse(text=content, usage=usage)
```

Create `src/novel_dev/llm/drivers/minimax.py`:
```python
from novel_dev.llm.drivers.openai_compatible import OpenAICompatibleDriver


class MinimaxDriver(OpenAICompatibleDriver):
    """Placeholder for future native MiniMax integration."""
```

Update `src/novel_dev/llm/drivers/__init__.py`:
```python
from novel_dev.llm.drivers.anthropic import AnthropicDriver
from novel_dev.llm.drivers.base import BaseDriver
from novel_dev.llm.drivers.minimax import MinimaxDriver
from novel_dev.llm.drivers.openai_compatible import OpenAICompatibleDriver

__all__ = ["BaseDriver", "OpenAICompatibleDriver", "AnthropicDriver", "MinimaxDriver"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/llm/test_anthropic_driver.py -v`
Expected: 2 tests pass

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/llm/drivers/ tests/llm/test_anthropic_driver.py
git commit -m "feat(llm): add AnthropicDriver and MinimaxDriver placeholder"
```

---

### Task 5: UsageTracker

**Files:**
- Create: `src/novel_dev/llm/usage_tracker.py`
- Test: `tests/llm/test_usage_tracker.py`

- [ ] **Step 1: Write failing usage tracker tests**

Create `tests/llm/test_usage_tracker.py`:
```python
import pytest
from unittest.mock import MagicMock, patch

from novel_dev.llm.models import TokenUsage
from novel_dev.llm.usage_tracker import LoggingUsageTracker


@pytest.mark.asyncio
async def test_logging_usage_tracker_logs_info():
    tracker = LoggingUsageTracker()
    usage = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    with patch("novel_dev.llm.usage_tracker.logger") as mock_logger:
        await tracker.log(agent="brainstorm_agent", task="generate_synopsis", usage=usage)
    mock_logger.info.assert_called_once()
    call_args = mock_logger.info.call_args
    assert call_args[1]["extra"]["agent"] == "brainstorm_agent"
    assert call_args[1]["extra"]["usage"]["total_tokens"] == 15
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/llm/test_usage_tracker.py -v`
Expected: `ModuleNotFoundError: No module named 'novel_dev.llm.usage_tracker'`

- [ ] **Step 3: Implement UsageTracker**

Create `src/novel_dev/llm/usage_tracker.py`:
```python
import logging
from typing import Protocol

from novel_dev.llm.models import TokenUsage

logger = logging.getLogger(__name__)


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

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/llm/test_usage_tracker.py -v`
Expected: 1 test passes

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/llm/usage_tracker.py tests/llm/test_usage_tracker.py
git commit -m "feat(llm): add UsageTracker protocol and logging implementation"
```

---

### Task 6: LLMFactory, RetryableDriver, and Config YAML

**Files:**
- Create: `src/novel_dev/llm/factory.py`
- Create: `llm_config.yaml`
- Modify: `src/novel_dev/llm/__init__.py`
- Test: `tests/llm/test_factory.py`

- [ ] **Step 1: Write failing factory tests**

Create `tests/llm/test_factory.py`:
```python
import os
import pytest
from unittest.mock import MagicMock, patch

from novel_dev.config import Settings
from novel_dev.llm.exceptions import LLMConfigError
from novel_dev.llm.factory import LLMFactory


@pytest.fixture
def temp_yaml(tmp_path):
    path = tmp_path / "llm_config.yaml"
    path.write_text("""
defaults:
  provider: openai_compatible
  model: gpt-4
  timeout: 30
  retries: 2

agents:
  test_agent:
    provider: anthropic
    model: claude-opus-4-6
    timeout: 120
    retries: 3
    tasks:
      special_task:
        model: claude-sonnet
        timeout: 60
""")
    return str(path)


def test_resolve_config_fallback_to_defaults(temp_yaml):
    settings = Settings(llm_config_path=temp_yaml, anthropic_api_key="ak")
    factory = LLMFactory(settings)
    cfg = factory._resolve_config("unknown_agent", None)
    assert cfg.provider == "openai_compatible"
    assert cfg.model == "gpt-4"


def test_resolve_config_agent_level(temp_yaml):
    settings = Settings(llm_config_path=temp_yaml, anthropic_api_key="ak")
    factory = LLMFactory(settings)
    cfg = factory._resolve_config("test_agent", None)
    assert cfg.provider == "anthropic"
    assert cfg.model == "claude-opus-4-6"
    assert cfg.retries == 3


def test_resolve_config_task_level(temp_yaml):
    settings = Settings(llm_config_path=temp_yaml, anthropic_api_key="ak")
    factory = LLMFactory(settings)
    cfg = factory._resolve_config("test_agent", "special_task")
    assert cfg.model == "claude-sonnet"
    assert cfg.timeout == 60
    assert cfg.retries == 3  # inherited from agent level


def test_missing_api_key_raises(temp_yaml):
    settings = Settings(llm_config_path=temp_yaml)
    factory = LLMFactory(settings)
    with pytest.raises(LLMConfigError, match="anthropic_api_key"):
        factory.get("test_agent")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/llm/test_factory.py -v`
Expected: `ModuleNotFoundError: No module named 'novel_dev.llm.factory'`

- [ ] **Step 3: Implement Factory, RetryableDriver, and YAML config**

Create `llm_config.yaml`:
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

  volume_planner_agent:
    provider: openai_compatible
    model: kimi-k2.5
    base_url: https://api.moonshot.cn/v1
    timeout: 60

  writer_agent:
    provider: minimax
    model: MiniMax-Text-01
    base_url: https://api.minimax.chat/v1
    timeout: 60
```

Create `src/novel_dev/llm/factory.py`:
```python
import asyncio
from urllib.parse import urlparse

import tenacity
import yaml
import httpx

from novel_dev.config import Settings
from novel_dev.llm.drivers.anthropic import AnthropicDriver
from novel_dev.llm.drivers.base import BaseDriver
from novel_dev.llm.drivers.minimax import MinimaxDriver
from novel_dev.llm.drivers.openai_compatible import OpenAICompatibleDriver
from novel_dev.llm.exceptions import LLMConfigError, LLMRateLimitError, LLMTimeoutError
from novel_dev.llm.models import RetryConfig, TaskConfig
from novel_dev.llm.usage_tracker import LoggingUsageTracker, UsageTracker


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

    async def acomplete(self, messages, config: TaskConfig):
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


class LLMFactory:
    def __init__(self, settings: Settings, usage_tracker: UsageTracker | None = None):
        self.settings = settings
        self.usage_tracker = usage_tracker or LoggingUsageTracker()
        self._config = self._load_yaml(settings.llm_config_path)
        self._cache: dict[tuple, BaseDriver] = {}
        self._http_client: httpx.AsyncClient | None = None

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            headers = {}
            if self.settings.llm_user_agent:
                headers["X-Custom-User-Agent"] = self.settings.llm_user_agent
            self._http_client = httpx.AsyncClient(headers=headers)
        return self._http_client

    def _load_yaml(self, path: str) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            return {}

    def _resolve_config(self, agent_name: str, task: str | None) -> TaskConfig:
        defaults = self._config.get("defaults", {})
        agent_cfg = self._config.get("agents", {}).get(agent_name, {})
        task_cfg = agent_cfg.get("tasks", {}).get(task, {}) if task else {}

        merged = {**defaults, **agent_cfg, **task_cfg}
        # remove nested tasks dict if inherited
        merged.pop("tasks", None)

        if not merged.get("provider") or not merged.get("model"):
            raise LLMConfigError(f"Missing provider or model for agent={agent_name} task={task}")

        return TaskConfig(**merged)

    def _resolve_api_key(self, provider: str, base_url: str | None) -> str:
        if provider == "anthropic":
            key = self.settings.anthropic_api_key
            key_name = "anthropic_api_key"
        elif provider == "minimax":
            key = self.settings.minimax_api_key
            key_name = "minimax_api_key"
        elif provider == "openai_compatible":
            key, key_name = self._resolve_openai_compatible_key(base_url)
        else:
            raise LLMConfigError(f"Unknown provider: {provider}")

        if not key:
            raise LLMConfigError(f"Missing API key: {key_name}")
        return key

    def _resolve_openai_compatible_key(self, base_url: str | None) -> tuple[str | None, str]:
        if not base_url:
            return self.settings.openai_api_key, "openai_api_key"
        host = urlparse(base_url).hostname or ""
        if "moonshot" in host:
            return self.settings.moonshot_api_key, "moonshot_api_key"
        if "bigmodel" in host:
            return self.settings.zhipu_api_key, "zhipu_api_key"
        if "openai" in host:
            return self.settings.openai_api_key, "openai_api_key"
        return self.settings.openai_api_key, "openai_api_key"

    def _create_driver(self, config: TaskConfig) -> BaseDriver:
        key = self._resolve_api_key(config.provider, config.base_url)
        if config.provider == "anthropic":
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=key, http_client=self._get_http_client())
            return AnthropicDriver(client=client)
        if config.provider == "minimax":
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=key, base_url=config.base_url, http_client=self._get_http_client())
            return MinimaxDriver(client=client)
        if config.provider == "openai_compatible":
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=key, base_url=config.base_url, http_client=self._get_http_client())
            return OpenAICompatibleDriver(client=client)
        raise LLMConfigError(f"Unsupported provider: {config.provider}")

    def _get_cached_driver(self, config: TaskConfig) -> BaseDriver:
        key = self._resolve_api_key(config.provider, config.base_url)
        cache_key = (config.provider, config.model, config.base_url, key)
        if cache_key not in self._cache:
            self._cache[cache_key] = self._create_driver(config)
        return self._cache[cache_key]

    def get(self, agent_name: str, task: str | None = None) -> BaseDriver:
        task_cfg = self._resolve_config(agent_name, task)
        inner = self._get_cached_driver(task_cfg)
        retry_cfg = RetryConfig(retries=task_cfg.retries, timeout=task_cfg.timeout)
        return RetryableDriver(
            inner=inner,
            retry_config=retry_cfg,
            usage_tracker=self.usage_tracker,
            agent=agent_name,
            task=task,
        )
```

Update `src/novel_dev/llm/__init__.py` to append at the bottom:
```python
from novel_dev.config import settings
from novel_dev.llm.factory import LLMFactory

llm_factory = LLMFactory(settings=settings)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/llm/test_factory.py -v`
Expected: 4 tests pass

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/llm/factory.py src/novel_dev/llm/__init__.py llm_config.yaml tests/llm/test_factory.py
git commit -m "feat(llm): add LLMFactory, RetryableDriver, and config YAML"
```

---

### Task 7: RetryableDriver Unit Tests

**Files:**
- Test: `tests/llm/test_retryable_driver.py`

- [ ] **Step 1: Write retry tests**

Create `tests/llm/test_retryable_driver.py`:
```python
import pytest
from unittest.mock import AsyncMock

from novel_dev.llm.exceptions import LLMConfigError, LLMRateLimitError, LLMTimeoutError
from novel_dev.llm.factory import RetryableDriver
from novel_dev.llm.models import LLMResponse, RetryConfig, TaskConfig


@pytest.mark.asyncio
async def test_retryable_driver_retries_on_rate_limit():
    inner = AsyncMock()
    inner.acomplete.side_effect = [
        LLMRateLimitError("rate limit"),
        LLMResponse(text="ok"),
    ]
    driver = RetryableDriver(inner, RetryConfig(retries=2, timeout=30))
    config = TaskConfig(provider="anthropic", model="claude-opus-4-6")
    response = await driver.acomplete("hi", config)
    assert response.text == "ok"
    assert inner.acomplete.call_count == 2


@pytest.mark.asyncio
async def test_retryable_driver_no_retry_on_config_error():
    inner = AsyncMock()
    inner.acomplete.side_effect = LLMConfigError("bad config")
    driver = RetryableDriver(inner, RetryConfig(retries=3, timeout=30))
    config = TaskConfig(provider="anthropic", model="claude-opus-4-6")
    with pytest.raises(LLMConfigError):
        await driver.acomplete("hi", config)
    assert inner.acomplete.call_count == 1
```

- [ ] **Step 2: Run tests**

Run: `python3 -m pytest tests/llm/test_retryable_driver.py -v`
Expected: 2 tests pass

- [ ] **Step 3: Commit**

```bash
git add tests/llm/test_retryable_driver.py
git commit -m "test(llm): add RetryableDriver retry behavior tests"
```

---

### Task 8: Migrate LibrarianAgent

**Files:**
- Modify: `src/novel_dev/agents/librarian.py`
- Modify: `tests/test_agents/test_librarian.py`

- [ ] **Step 1: Write failing migration test**

Update `tests/test_agents/test_librarian.py` to add a new test that asserts the agent calls the factory:
```python
import pytest
from unittest.mock import AsyncMock, patch

from novel_dev.agents.librarian import LibrarianAgent
from novel_dev.llm.models import LLMResponse
from novel_dev.schemas.librarian import ExtractionResult


@pytest.mark.asyncio
async def test_librarian_calls_llm_factory(async_session):
    agent = LibrarianAgent(async_session)
    mock_response = ExtractionResult(
        timeline_events=[{"tick": 10, "narrative": "战斗结束"}],
        new_entities=[{"type": "character", "name": "Lin Feng", "state": {"level": 2}}],
    )
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text=mock_response.model_dump_json())

    with patch("novel_dev.agents.librarian.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await agent.extract("n1", "c1", "Lin Feng leveled up after the battle.")

    assert len(result.timeline_events) == 1
    assert result.timeline_events[0].tick == 10
    mock_factory.get.assert_called_once_with("LibrarianAgent", task="extract")
    mock_client.acomplete.assert_called_once()
```

Add this test to the existing `tests/test_agents/test_librarian.py` file (keep the old tests too).

- [ ] **Step 2: Run tests to verify the new test fails**

Run: `python3 -m pytest tests/test_agents/test_librarian.py::test_librarian_calls_llm_factory -v`
Expected: AssertionError because `librarian.py` doesn't use `llm_factory`

- [ ] **Step 3: Migrate LibrarianAgent**

Modify `src/novel_dev/agents/librarian.py`:

Replace the `_call_llm` method:
```python
    async def _call_llm(self, prompt: str) -> str:
        from novel_dev.llm import llm_factory
        client = llm_factory.get("LibrarianAgent", task="extract")
        response = await client.acomplete(prompt)
        return response.text
```

Leave `extract` and `fallback_extract` unchanged.

- [ ] **Step 4: Run all librarian tests**

Run: `python3 -m pytest tests/test_agents/test_librarian.py -v`
Expected: all tests pass (including new and existing ones)

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/librarian.py tests/test_agents/test_librarian.py
git commit -m "feat(agent): migrate LibrarianAgent to LLM factory"
```

---

### Task 9: Migrate BrainstormAgent

**Files:**
- Modify: `src/novel_dev/agents/brainstorm_agent.py`
- Modify: `tests/test_agents/test_brainstorm_agent.py`

- [ ] **Step 1: Write failing migration test**

Append to `tests/test_agents/test_brainstorm_agent.py`:
```python
import json
from unittest.mock import AsyncMock, patch

from novel_dev.llm.models import ChatMessage, LLMResponse
from novel_dev.schemas.outline import SynopsisData


@pytest.mark.asyncio
async def test_brainstorm_uses_llm_factory(async_session):
    await DocumentRepository(async_session).create(
        "doc_wv2", "n_brain2", "worldview", "Worldview", "天玄大陆。"
    )

    synopsis_json = SynopsisData(
        title="天玄纪元",
        logline="主角崛起",
        core_conflict="复仇",
        themes=["成长"],
        character_arcs=[],
        milestones=[],
        estimated_volumes=3,
        estimated_total_chapters=90,
        estimated_total_words=270000,
    ).model_dump_json()

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text=synopsis_json)

    with patch("novel_dev.agents.brainstorm_agent.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = BrainstormAgent(async_session)
        result = await agent.brainstorm("n_brain2")

    assert result.title == "天玄纪元"
    mock_factory.get.assert_called_once_with("BrainstormAgent", task="generate_synopsis")
    call_args = mock_client.acomplete.call_args[0][0]
    assert any(isinstance(m, ChatMessage) and m.role == "system" for m in call_args)
```

- [ ] **Step 2: Run the new test to verify it fails**

Run: `python3 -m pytest tests/test_agents/test_brainstorm_agent.py::test_brainstorm_uses_llm_factory -v`
Expected: Fails because `brainstorm_agent.py` doesn't import `llm_factory`

- [ ] **Step 3: Migrate BrainstormAgent**

Modify `src/novel_dev/agents/brainstorm_agent.py`:

Add import at the top:
```python
from novel_dev.llm.models import ChatMessage
```

Change `brainstorm` method to await `_generate_synopsis`:
```python
        synopsis_data = await self._generate_synopsis(combined)
```

Replace `_generate_synopsis`:
```python
    async def _generate_synopsis(self, combined_text: str) -> SynopsisData:
        from novel_dev.llm import llm_factory
        client = llm_factory.get("BrainstormAgent", task="generate_synopsis")
        messages = [
            ChatMessage(
                role="system",
                content=(
                    "你是一位小说大纲生成专家。根据用户提供的设定文档，"
                    "生成一份包含标题、一句话梗概、核心冲突、主题、人物弧光和剧情里程碑的大纲。"
                    "返回严格符合指定 JSON Schema 的数据。"
                ),
            ),
            ChatMessage(role="user", content=combined_text),
        ]
        response = await client.acomplete(messages)
        return SynopsisData.model_validate_json(response.text)
```

- [ ] **Step 4: Run all brainstorm tests**

Run: `python3 -m pytest tests/test_agents/test_brainstorm_agent.py -v`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/brainstorm_agent.py tests/test_agents/test_brainstorm_agent.py
git commit -m "feat(agent): migrate BrainstormAgent to LLM factory"
```

---

### Task 10: Full Regression Test Run

**Files:**
- Run: full test suite

- [ ] **Step 1: Run all tests**

Run: `python3 -m pytest tests/ -q --ignore=tests/test_integration_end_to_end.py`
Expected: all tests pass (existing + new LLM tests)

- [ ] **Step 2: Commit if any uncommitted changes remain**

```bash
git diff --quiet || git commit -am "test: full regression after LLM integration"
```

---

## Self-Review Checklist

### 1. Spec coverage
- [ ] `ChatMessage`, `LLMResponse`, `TaskConfig` models implemented (Task 2)
- [ ] `LLMError` hierarchy implemented (Task 2)
- [ ] `BaseDriver` interface with `acomplete(messages, config)` (Task 3)
- [ ] `OpenAICompatibleDriver` covers OpenAI-compatible endpoints (Task 3)
- [ ] `AnthropicDriver` native integration with system message support (Task 4)
- [ ] `MinimaxDriver` placeholder created (Task 4)
- [ ] `UsageTracker` protocol + `LoggingUsageTracker` (Task 5)
- [ ] `LLMFactory` with YAML config loading, fallback logic, caching, retry wrapper (Task 6)
- [ ] Custom user-agent injected via shared `httpx.AsyncClient` (Task 6)
- [ ] `RetryableDriver` retries `LLMRateLimitError` and `LLMTimeoutError` only (Task 6/7)
- [ ] `LibrarianAgent` migrated to factory (Task 8)
- [ ] `BrainstormAgent` migrated to factory (Task 9)

### 2. Placeholder scan
- [ ] No "TBD", "TODO", "implement later", "fill in details"
- [ ] No vague requirements like "add appropriate error handling"
- [ ] Every code step shows actual code
- [ ] Every test step shows actual test code

### 3. Type consistency
- [ ] `acomplete` signature uses `str | list[ChatMessage]` consistently across all drivers
- [ ] `TaskConfig` field names match in factory, drivers, and tests
- [ ] `LLMResponse` has `reasoning_content` reserved field
- [ ] Agent migration uses `llm_factory.get(agent_name, task=task_name)` consistently

### 4. Dependency check
- [ ] `pyproject.toml` includes `anthropic`, `openai`, `tenacity`, `pyyaml`
- [ ] `pip install -e ".[dev]"` step included before any import of new packages
