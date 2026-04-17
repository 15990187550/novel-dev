import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.config_routes import router as config_router

app = FastAPI()
app.include_router(config_router)


@pytest.mark.asyncio
async def test_get_llm_config(tmp_path, monkeypatch):
    config_path = tmp_path / "llm_config.yaml"
    config_path.write_text("defaults:\n  provider: openai_compatible\n  model: gpt-4\n")

    from novel_dev.config import Settings
    settings = Settings(llm_config_path=str(config_path))
    monkeypatch.setattr("novel_dev.api.config_routes.settings", settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/config/llm")
        assert resp.status_code == 200
        assert resp.json()["defaults"]["model"] == "gpt-4"


@pytest.mark.asyncio
async def test_save_llm_config(tmp_path, monkeypatch):
    config_path = tmp_path / "llm_config.yaml"
    from novel_dev.config import Settings
    settings = Settings(llm_config_path=str(config_path))
    monkeypatch.setattr("novel_dev.api.config_routes.settings", settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/config/llm", json={"config": {"defaults": {"provider": "anthropic", "model": "claude-3"}}})
        assert resp.status_code == 200
        assert resp.json()["saved"] is True
        content = config_path.read_text()
        assert "anthropic" in content


@pytest.mark.asyncio
async def test_get_env_config(monkeypatch):
    from novel_dev.config import Settings
    settings = Settings()
    monkeypatch.setattr("novel_dev.api.config_routes.settings", settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/config/env")
        assert resp.status_code == 200
        data = resp.json()
        assert "anthropic_api_key" in data


@pytest.mark.asyncio
async def test_save_env_config(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("")

    from novel_dev.config import Settings
    settings = Settings()
    monkeypatch.setattr("novel_dev.api.config_routes.settings", settings)
    monkeypatch.setattr("novel_dev.api.config_routes.find_dotenv", lambda: str(env_file))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/config/env", json={"anthropic_api_key": "sk-test"})
        assert resp.status_code == 200
        assert resp.json()["saved"] is True
        content = env_file.read_text()
        assert "sk-test" in content
