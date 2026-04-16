from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://localhost/novel_dev"
    markdown_output_dir: str = "./novel_output"

    class Config:
        env_prefix = ""
