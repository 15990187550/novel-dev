from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel
from novel_dev.config import settings
from dotenv import set_key, find_dotenv

router = APIRouter()


class LLMConfigPayload(BaseModel):
    config: dict


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
    # TODO: validate defaults with TaskConfig once novel_dev.llm.models is available
    import yaml
    with open(settings.llm_config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload.config, f, allow_unicode=True, sort_keys=False)
    return {"saved": True}


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
