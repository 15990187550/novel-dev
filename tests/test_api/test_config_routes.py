import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from unittest.mock import AsyncMock, MagicMock

from novel_dev.api.config_routes import router as config_router
from novel_dev.llm.models import LLMResponse

app = FastAPI()
app.include_router(config_router)


@pytest.mark.asyncio
async def test_get_llm_config(tmp_path, monkeypatch):
    config_path = tmp_path / "llm_config.yaml"
    config_path.write_text("defaults:\n  timeout: 30\nmodels:\n  gpt-4:\n    provider: openai_compatible\n    model: gpt-4\n")

    from novel_dev.config import Settings
    settings = Settings(llm_config_path=str(config_path))
    monkeypatch.setattr("novel_dev.api.config_routes.settings", settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/config/llm")
        assert resp.status_code == 200
        assert resp.json()["defaults"]["timeout"] == 30


@pytest.mark.asyncio
async def test_save_llm_config(tmp_path, monkeypatch):
    config_path = tmp_path / "llm_config.yaml"
    from novel_dev.config import Settings
    settings = Settings(llm_config_path=str(config_path))
    monkeypatch.setattr("novel_dev.api.config_routes.settings", settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/config/llm", json={"config": {"defaults": {"timeout": 30}, "models": {"gpt-4": {"provider": "openai_compatible", "model": "gpt-4"}}}})
        assert resp.status_code == 200
        assert resp.json()["saved"] is True
        content = config_path.read_text()
        assert "openai_compatible" in content


@pytest.mark.asyncio
async def test_save_llm_config_reloads_runtime_factory(tmp_path, monkeypatch):
    config_path = tmp_path / "llm_config.yaml"
    from novel_dev.config import Settings
    settings = Settings(llm_config_path=str(config_path))
    reload_calls = []
    monkeypatch.setattr("novel_dev.api.config_routes.settings", settings)
    monkeypatch.setattr("novel_dev.api.config_routes.llm_factory", type("Factory", (), {"reload": lambda self: reload_calls.append(True)})())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/config/llm", json={"config": {"defaults": {"timeout": 45}}})
        assert resp.status_code == 200
        assert resp.json()["saved"] is True
        assert resp.json()["reloaded"] is True
        assert reload_calls == [True]


@pytest.mark.asyncio
async def test_test_llm_model_uses_submitted_profile(monkeypatch):
    driver = type(
        "Driver",
        (),
        {"acomplete": AsyncMock(return_value=LLMResponse(text="pong"))},
    )()
    create_driver = MagicMock(return_value=driver)

    def build_driver(self, config):
        return create_driver(config)

    monkeypatch.setattr("novel_dev.api.config_routes.llm_factory", type("Factory", (), {"_create_driver": build_driver})())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/config/llm/test_model",
            json={
                "name": "main",
                "profile": {
                    "provider": "openai_compatible",
                    "model": "gpt-test",
                    "base_url": "http://127.0.0.1:9997/v1",
                    "api_key": "sk-test",
                    "timeout": 12,
                },
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["status"] == "success"
        assert data["name"] == "main"
        assert data["provider"] == "openai_compatible"
        assert data["model"] == "gpt-test"
        call_config = create_driver.call_args.args[0]
        assert call_config.max_tokens == 8
        assert call_config.timeout == 12
        driver.acomplete.assert_awaited_once()


@pytest.mark.asyncio
async def test_test_llm_model_reports_connection_failure(monkeypatch):
    driver = type("Driver", (), {"acomplete": AsyncMock(side_effect=RuntimeError("network down"))})()

    monkeypatch.setattr("novel_dev.api.config_routes.llm_factory", type("Factory", (), {"_create_driver": lambda self, config: driver})())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/config/llm/test_model",
            json={"name": "bad", "profile": {"provider": "anthropic", "model": "claude-test"}},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert data["status"] == "failed"
        assert data["message"] == "network down"


@pytest.mark.asyncio
async def test_test_llm_model_reports_incomplete_profile():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/config/llm/test_model",
            json={"name": "bad", "profile": {"provider": "anthropic"}},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert data["status"] == "invalid"
        assert data["message"] == "provider 和 model 为必填项"


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
