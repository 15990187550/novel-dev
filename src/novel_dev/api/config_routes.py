import os
import time
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel
from novel_dev.config import settings
from novel_dev.llm.models import ChatMessage, TaskConfig
from dotenv import set_key, find_dotenv
from novel_dev.llm import llm_factory

router = APIRouter()


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


@router.get("/api/config/llm")
async def get_llm_config():
    import yaml
    import os
    if not os.path.exists(settings.llm_config_path):
        return {}
    with open(settings.llm_config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


@router.post("/api/config/llm")
async def save_llm_config(payload: LLMConfigPayload):
    import yaml
    config_dir = os.path.dirname(settings.llm_config_path)
    if config_dir:
        os.makedirs(config_dir, exist_ok=True)
    with open(settings.llm_config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload.config, f, allow_unicode=True, sort_keys=False)
    llm_factory.reload()
    return {"saved": True, "reloaded": True}


def _clean_error_message(exc: Exception, profile: dict) -> str:
    message = str(exc) or exc.__class__.__name__
    api_key = profile.get("api_key")
    if api_key:
        message = message.replace(str(api_key), "***")
    return message


@router.post("/api/config/llm/test_model")
async def test_llm_model(payload: LLMModelTestPayload):
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
        "anthropic_api_key": settings.anthropic_api_key or "",
        "openai_api_key": settings.openai_api_key or "",
        "moonshot_api_key": settings.moonshot_api_key or "",
        "minimax_api_key": settings.minimax_api_key or "",
        "zhipu_api_key": settings.zhipu_api_key or "",
    }


@router.post("/api/config/env")
async def save_env_config(payload: EnvConfigPayload):
    env_path = find_dotenv() or ".env"
    for key, value in payload.model_dump().items():
        if value is not None:
            set_key(env_path, key.upper(), value)
            setattr(settings, key, value)
    return {"saved": True}
