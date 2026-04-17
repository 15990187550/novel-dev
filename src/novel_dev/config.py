from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    database_url: str = "postgresql+asyncpg://localhost/novel_dev"
    markdown_output_dir: str = "./novel_output"
    llm_config_path: str = "llm_config.yaml"
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    moonshot_api_key: Optional[str] = None
    minimax_api_key: Optional[str] = None
    zhipu_api_key: Optional[str] = None


settings = Settings()
