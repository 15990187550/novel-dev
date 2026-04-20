import asyncio
import hashlib
import logging
import re
from typing import Optional, Tuple
from urllib.parse import urlparse

import tenacity
import yaml
import httpx

logger = logging.getLogger(__name__)

from novel_dev.config import Settings
from novel_dev.llm.drivers.anthropic import AnthropicDriver
from novel_dev.llm.drivers.base import BaseDriver
from novel_dev.llm.drivers.minimax import MinimaxDriver
from novel_dev.llm.drivers.openai_compatible import OpenAICompatibleDriver
from novel_dev.llm.embedder import BaseEmbedder
from novel_dev.llm.exceptions import LLMConfigError, LLMRateLimitError, LLMTimeoutError
from novel_dev.llm.fallback_driver import FallbackDriver
from novel_dev.llm.models import EmbeddingConfig, RetryConfig, TaskConfig
from novel_dev.llm.usage_tracker import LoggingUsageTracker, UsageTracker


class RetryableDriver(BaseDriver):
    def __init__(
        self,
        inner: BaseDriver,
        retry_config: RetryConfig,
        usage_tracker: Optional[UsageTracker] = None,
        agent: Optional[str] = None,
        task: Optional[str] = None,
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
        try:
            response = await asyncio.wait_for(
                retryer(self.inner.acomplete, messages, config),
                timeout=self.retry_config.timeout,
            )
        except asyncio.TimeoutError as exc:
            raise LLMTimeoutError("Request timed out") from exc
        if self.usage_tracker and response.usage:
            async def _log():
                try:
                    await self.usage_tracker.log(agent=self.agent, task=self.task, usage=response.usage)
                except Exception as exc:
                    logger.warning("llm_usage_tracking_failed", extra={"error": str(exc)})
            asyncio.create_task(_log())
        return response


class LLMFactory:
    def __init__(self, settings: Settings, usage_tracker: Optional[UsageTracker] = None):
        self.settings = settings
        self.usage_tracker = usage_tracker or LoggingUsageTracker()
        self._config = self._load_yaml(settings.llm_config_path)
        self._cache: dict[Tuple, BaseDriver] = {}
        self._http_client: Optional[httpx.AsyncClient] = None

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

    def _build_task_config(self, raw: dict) -> TaskConfig:
        if isinstance(raw, TaskConfig):
            return raw
        raw = raw.copy()
        fallback_raw = raw.pop("fallback", None)
        fallback = None
        if fallback_raw:
            if isinstance(fallback_raw, TaskConfig):
                fallback = fallback_raw
            else:
                fallback = self._build_task_config(fallback_raw)
        return TaskConfig(fallback=fallback, **raw)

    def _normalize_agent_name(self, name: str) -> str:
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

    def _resolve_config(self, agent_name: str, task: Optional[str]) -> TaskConfig:
        defaults = self._config.get("defaults", {})
        normalized_name = self._normalize_agent_name(agent_name)
        agent_cfg = self._config.get("agents", {}).get(normalized_name, {})
        task_cfg = agent_cfg.get("tasks", {}).get(task, {}) if task else {}

        # agent base config (without tasks/fallback) — inherited by fallback
        agent_base = {k: v for k, v in agent_cfg.items() if k not in ("tasks", "fallback")}

        # Merge main config: defaults → agent → task
        merged = {**defaults, **agent_cfg, **task_cfg}
        merged.pop("tasks", None)

        # Resolve fallback: inherit agent_base, then fallback self overrides
        fallback = None
        fallback_raw = merged.pop("fallback", None)
        if fallback_raw:
            fallback_merged = {**defaults, **agent_base, **fallback_raw}
            fallback = self._resolve_model_profile(fallback_merged)

        return self._resolve_model_profile(merged, fallback=fallback)

    def _resolve_model_profile(
        self, raw: dict, fallback: Optional[TaskConfig] = None
    ) -> TaskConfig:
        raw = raw.copy()
        model_ref = raw.pop("model", None)
        if model_ref:
            profile = self._config.get("models", {}).get(model_ref, {})
            if not profile:
                raise LLMConfigError(f"Unknown model profile: {model_ref}")
            raw = {**profile, **raw}
        else:
            raise LLMConfigError("Missing model reference")

        if not raw.get("provider") or not raw.get("model"):
            raise LLMConfigError("Missing provider or model after resolving profile")

        return self._build_task_config({**raw, "fallback": fallback})

    def _resolve_api_key(self, provider: str, base_url: Optional[str]) -> str:
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

    def _resolve_openai_compatible_key(self, base_url: Optional[str]) -> Tuple[Optional[str], str]:
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
            kwargs = {"api_key": key, "http_client": self._get_http_client()}
            if config.base_url:
                kwargs["base_url"] = config.base_url
            client = AsyncAnthropic(**kwargs)
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
        key_hash = hashlib.sha256(key.encode()).hexdigest()[:16]
        cache_key = (config.provider, config.model, config.base_url, key_hash)
        if cache_key not in self._cache:
            self._cache[cache_key] = self._create_driver(config)
        return self._cache[cache_key]

    def _build_retryable_driver(self, config: TaskConfig, agent_name: str, task: Optional[str]) -> BaseDriver:
        inner = self._get_cached_driver(config)
        retry_cfg = RetryConfig(retries=config.retries, timeout=config.timeout)
        return RetryableDriver(
            inner=inner,
            retry_config=retry_cfg,
            usage_tracker=self.usage_tracker,
            agent=agent_name,
            task=task,
        )

    def get(self, agent_name: str, task: Optional[str] = None) -> BaseDriver:
        task_cfg = self._resolve_config(agent_name, task)
        primary = self._build_retryable_driver(task_cfg, agent_name, task)

        fallback_driver = None
        if task_cfg.fallback:
            fallback_driver = self._build_retryable_driver(task_cfg.fallback, agent_name, task)

        if fallback_driver:
            return FallbackDriver(
                primary=primary,
                fallback=fallback_driver,
                fallback_config=task_cfg.fallback,
                usage_tracker=self.usage_tracker,
                agent=agent_name,
                task=task,
            )
        return primary

    def get_embedder(self) -> BaseEmbedder:
        from novel_dev.llm.embedder import OpenAIEmbedder
        from openai import AsyncOpenAI

        raw = self._config.get("embedding", {})
        if not raw:
            raise LLMConfigError("Missing 'embedding' configuration in llm_config.yaml")

        config = EmbeddingConfig(**raw)
        key = self._resolve_api_key(config.provider, config.base_url)
        client = AsyncOpenAI(
            api_key=key,
            base_url=config.base_url,
            http_client=self._get_http_client(),
        )
        return OpenAIEmbedder(client=client, model=config.model, dimensions=config.dimensions)
