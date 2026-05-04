import os
import secrets
import time
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from novel_dev.config import settings
from novel_dev.llm.models import ChatMessage, TaskConfig
from dotenv import set_key, find_dotenv
from novel_dev.llm import llm_factory

router = APIRouter()

MASKED_SECRET = "********"
ENV_SECRET_FIELDS = {
    "anthropic_api_key",
    "openai_api_key",
    "moonshot_api_key",
    "minimax_api_key",
    "zhipu_api_key",
}


class LLMConfigPayload(BaseModel):
    config: dict


class LLMModelTestPayload(BaseModel):
    name: Optional[str] = None
    profile: dict


class EnvConfigPayload(BaseModel):
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    moonshot_api_key: Optional[str] = None
    minimax_api_key: Optional[str] = None
    zhipu_api_key: Optional[str] = None


def _mask_secret_value(value: Any) -> str:
    if value is None or value == "":
        return ""
    return MASKED_SECRET


def _is_secret_config_key(key: str) -> bool:
    normalized_key = key.lower()
    return (
        normalized_key == "api_key"
        or normalized_key.endswith("_api_key")
        or normalized_key in ENV_SECRET_FIELDS
    )


def _mask_config_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _mask_secret_value(item) if _is_secret_config_key(str(key)) else _mask_config_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_mask_config_secrets(item) for item in value]
    return value


def _preserve_masked_config_secrets(submitted: Any, existing: Any = None) -> Any:
    if isinstance(submitted, dict):
        existing_dict = existing if isinstance(existing, dict) else {}
        sanitized = {}
        for key, value in submitted.items():
            if _is_secret_config_key(str(key)) and value == MASKED_SECRET:
                existing_value = existing_dict.get(key)
                if existing_value not in (None, "", MASKED_SECRET):
                    sanitized[key] = existing_value
                continue

            sanitized_value = _preserve_masked_config_secrets(value, existing_dict.get(key))
            sanitized[key] = sanitized_value
        return sanitized

    if isinstance(submitted, list):
        existing_list = existing if isinstance(existing, list) else []
        return [
            _preserve_masked_config_secrets(
                item,
                existing_list[index] if index < len(existing_list) else None,
            )
            for index, item in enumerate(submitted)
        ]

    return submitted


def _require_config_admin_token(x_novel_config_token: Optional[str]) -> None:
    expected_token = settings.config_admin_token
    if not expected_token:
        return
    if not x_novel_config_token or not secrets.compare_digest(x_novel_config_token, expected_token):
        raise HTTPException(status_code=403, detail="Config admin token required")


@router.get("/api/config/llm")
async def get_llm_config():
    import yaml
    import os
    if not os.path.exists(settings.llm_config_path):
        return {}
    with open(settings.llm_config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return _mask_config_secrets(data)


@router.post("/api/config/llm")
async def save_llm_config(
    payload: LLMConfigPayload,
    x_novel_config_token: Optional[str] = Header(default=None),
):
    _require_config_admin_token(x_novel_config_token)
    import yaml
    existing_config = {}
    if os.path.exists(settings.llm_config_path):
        with open(settings.llm_config_path, "r", encoding="utf-8") as f:
            existing_config = yaml.safe_load(f) or {}
    config = _preserve_masked_config_secrets(payload.config, existing_config)
    config_dir = os.path.dirname(settings.llm_config_path)
    if config_dir:
        os.makedirs(config_dir, exist_ok=True)
    with open(settings.llm_config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)
    llm_factory.reload()
    return {"saved": True, "reloaded": True}


def _clean_error_message(exc: Exception, profile: dict) -> str:
    message = str(exc) or exc.__class__.__name__
    api_key = profile.get("api_key")
    if api_key:
        message = message.replace(str(api_key), "***")
    return message


@router.post("/api/config/llm/test_model")
async def test_llm_model(
    payload: LLMModelTestPayload,
    x_novel_config_token: Optional[str] = Header(default=None),
):
    _require_config_admin_token(x_novel_config_token)
    profile = payload.profile or {}
    provider = profile.get("provider")
    model = profile.get("model")
    if not provider or not model:
        return {
            "ok": False,
            "status": "invalid",
            "name": payload.name,
            "provider": provider,
            "model": model,
            "message": "provider 和 model 为必填项",
            "latency_ms": 0,
        }

    timeout = int(profile.get("timeout") or 15)
    config = TaskConfig(
        provider=provider,
        model=model,
        base_url=profile.get("base_url") or None,
        api_key=profile.get("api_key") or None,
        timeout=timeout,
        retries=0,
        temperature=0,
        max_tokens=8,
    )
    started = time.perf_counter()
    try:
        driver = llm_factory._create_driver(config)
        await driver.acomplete(
            [ChatMessage(role="user", content="Reply with ok.")],
            config,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": "failed",
            "name": payload.name,
            "provider": provider,
            "model": model,
            "message": _clean_error_message(exc, profile),
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
    return {
        "ok": True,
        "status": "success",
        "name": payload.name,
        "provider": provider,
        "model": model,
        "message": "连接成功",
        "latency_ms": round((time.perf_counter() - started) * 1000),
    }


@router.get("/api/config/env")
async def get_env_config():
    return {
        "anthropic_api_key": _mask_secret_value(settings.anthropic_api_key),
        "openai_api_key": _mask_secret_value(settings.openai_api_key),
        "moonshot_api_key": _mask_secret_value(settings.moonshot_api_key),
        "minimax_api_key": _mask_secret_value(settings.minimax_api_key),
        "zhipu_api_key": _mask_secret_value(settings.zhipu_api_key),
    }


@router.post("/api/config/env")
async def save_env_config(
    payload: EnvConfigPayload,
    x_novel_config_token: Optional[str] = Header(default=None),
):
    _require_config_admin_token(x_novel_config_token)
    env_path = find_dotenv() or ".env"
    for key, value in payload.model_dump().items():
        if value == MASKED_SECRET:
            continue
        if value is not None:
            set_key(env_path, key.upper(), value)
            setattr(settings, key, value)
    return {"saved": True}
