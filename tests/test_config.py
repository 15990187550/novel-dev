import os


def test_database_url_from_env():
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost/test"
    from novel_dev.config import Settings
    settings = Settings()
    assert settings.database_url == "postgresql+asyncpg://test:test@localhost/test"
