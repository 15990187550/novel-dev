from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./novel_dev.db"
    markdown_output_dir: str = "./novel_output"

    class Config:
        env_prefix = ""
