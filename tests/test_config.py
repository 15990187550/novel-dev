def test_database_url_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
    from novel_dev.config import Settings


    settings = Settings()

    assert settings.database_url == "postgresql+asyncpg://test:test@localhost/test"


def test_data_dir_default(monkeypatch):
    monkeypatch.delenv("NOVEL_DEV_DATA_DIR", raising=False)
    from novel_dev.config import Settings

    settings = Settings()

    assert settings.data_dir == "~/NovelDevData"


def test_data_dir_from_env(monkeypatch):
    monkeypatch.setenv("NOVEL_DEV_DATA_DIR", "/tmp/novel-dev-data")
    from novel_dev.config import Settings

    settings = Settings()

    assert settings.data_dir == "/tmp/novel-dev-data"


def test_data_dir_can_be_overridden_by_field_name(monkeypatch):
    monkeypatch.delenv("NOVEL_DEV_DATA_DIR", raising=False)
    from novel_dev.config import Settings

    settings = Settings(data_dir="/tmp/explicit-novel-dev-data")

    assert settings.data_dir == "/tmp/explicit-novel-dev-data"
