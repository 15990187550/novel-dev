from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    database_url: str = "postgresql+asyncpg://localhost/novel_dev"
    markdown_output_dir: str = "./novel_output"
