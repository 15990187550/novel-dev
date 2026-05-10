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
async def test_get_llm_config_masks_profile_api_keys(tmp_path, monkeypatch):
    config_path = tmp_path / "llm_config.yaml"
    config_path.write_text(
        "models:\n"
        "  kimi:\n"
        "    provider: anthropic\n"
        "    model: kimi-test\n"
        "    api_key: sk-live-secret\n"
        "agents:\n"
        "  writer_agent:\n"
        "    model: kimi\n",
        encoding="utf-8",
    )

    from novel_dev.config import Settings

    settings = Settings(llm_config_path=str(config_path))
    monkeypatch.setattr("novel_dev.api.config_routes.settings", settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/config/llm")

    assert resp.status_code == 200
    data = resp.json()
    assert data["models"]["kimi"]["api_key"] == "********"
    assert "sk-live-secret" not in str(data)


@pytest.mark.asyncio
async def test_get_llm_config_surfaces_masked_env_backed_profile_api_key(tmp_path, monkeypatch):
    config_path = tmp_path / "llm_config.yaml"
    config_path.write_text(
        "models:\n"
        "  deepseek:\n"
        "    provider: anthropic\n"
        "    model: deepseek-v4-flash\n"
        "    api_key_env: DEEPSEEK_API_KEY\n",
        encoding="utf-8",
    )

    from novel_dev.config import Settings

    settings = Settings(llm_config_path=str(config_path))
    monkeypatch.setattr("novel_dev.api.config_routes.settings", settings)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-live")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/config/llm")

    assert resp.status_code == 200
    data = resp.json()
    assert data["models"]["deepseek"]["api_key_env"] == "DEEPSEEK_API_KEY"
    assert data["models"]["deepseek"]["api_key"] == "********"
    assert "sk-deepseek-live" not in str(data)


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
async def test_save_llm_config_requires_admin_token_when_configured(tmp_path, monkeypatch):
    config_path = tmp_path / "llm_config.yaml"

    from novel_dev.config import Settings

    settings = Settings(llm_config_path=str(config_path), config_admin_token="secret-token")
    monkeypatch.setattr("novel_dev.api.config_routes.settings", settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.post("/api/config/llm", json={"config": {"defaults": {"timeout": 30}}})
        wrong = await client.post(
            "/api/config/llm",
            json={"config": {"defaults": {"timeout": 30}}},
            headers={"X-Novel-Config-Token": "wrong"},
        )
        ok = await client.post(
            "/api/config/llm",
            json={"config": {"defaults": {"timeout": 30}}},
            headers={"X-Novel-Config-Token": "secret-token"},
        )

    assert missing.status_code == 403
    assert wrong.status_code == 403
    assert ok.status_code == 200
    assert ok.json()["saved"] is True


@pytest.mark.asyncio
async def test_save_llm_config_preserves_existing_secret_when_masked_value_round_trips(tmp_path, monkeypatch):
    import yaml

    config_path = tmp_path / "llm_config.yaml"
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    config_path.write_text(
        "models:\n"
        "  kimi:\n"
        "    provider: anthropic\n"
        "    model: kimi-test\n"
        "    api_key: sk-live-secret\n",
        encoding="utf-8",
    )

    from novel_dev.config import Settings

    settings = Settings(llm_config_path=str(config_path))
    monkeypatch.setattr("novel_dev.api.config_routes.settings", settings)
    monkeypatch.setattr("novel_dev.api.config_routes.find_dotenv", lambda: str(env_file))
    monkeypatch.delenv("KIMI_API_KEY", raising=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/config/llm",
            json={
                "config": {
                    "models": {
                        "kimi": {
                            "provider": "anthropic",
                            "model": "kimi-changed",
                            "api_key": "********",
                        }
                    }
                }
            },
        )

    assert resp.status_code == 200
    saved_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved_config["models"]["kimi"]["model"] == "kimi-changed"
    assert saved_config["models"]["kimi"]["api_key_env"] == "KIMI_API_KEY"
    assert "api_key" not in saved_config["models"]["kimi"]
    assert "KIMI_API_KEY='sk-live-secret'" in env_file.read_text(encoding="utf-8")
    assert __import__("os").environ["KIMI_API_KEY"] == "sk-live-secret"
    assert "********" not in config_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_save_llm_config_writes_profile_api_key_to_env_file(tmp_path, monkeypatch):
    import os
    import yaml

    config_path = tmp_path / "llm_config.yaml"
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")

    from novel_dev.config import Settings

    settings = Settings(llm_config_path=str(config_path))
    monkeypatch.setattr("novel_dev.api.config_routes.settings", settings)
    monkeypatch.setattr("novel_dev.api.config_routes.find_dotenv", lambda: str(env_file))
    monkeypatch.delenv("KIMI_API_KEY", raising=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/config/llm",
            json={
                "config": {
                    "models": {
                        "kimi-for-coding": {
                            "provider": "anthropic",
                            "model": "kimi-for-coding",
                            "api_key_env": "KIMI_API_KEY",
                            "api_key": "sk-new-secret",
                        }
                    }
                }
            },
        )

    assert resp.status_code == 200
    saved_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    saved_profile = saved_config["models"]["kimi-for-coding"]
    assert saved_profile["api_key_env"] == "KIMI_API_KEY"
    assert "api_key" not in saved_profile
    assert "sk-new-secret" not in config_path.read_text(encoding="utf-8")
    assert "KIMI_API_KEY='sk-new-secret'" in env_file.read_text(encoding="utf-8")
    assert os.environ["KIMI_API_KEY"] == "sk-new-secret"


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
async def test_test_llm_model_uses_submitted_profile(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setattr("novel_dev.api.config_routes.find_dotenv", lambda: str(env_file))
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
async def test_test_llm_model_preserves_api_key_env(monkeypatch):
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
                "name": "kimi",
                "profile": {
                    "provider": "anthropic",
                    "model": "kimi-k2-test",
                    "api_key_env": "KIMI_API_KEY",
                },
            },
        )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    call_config = create_driver.call_args.args[0]
    assert call_config.api_key_env == "KIMI_API_KEY"
    assert call_config.api_key is None


@pytest.mark.asyncio
async def test_test_llm_model_writes_api_key_to_env_and_reloads(tmp_path, monkeypatch):
    import os

    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    reload_calls = []
    driver = type(
        "Driver",
        (),
        {"acomplete": AsyncMock(return_value=LLMResponse(text="pong"))},
    )()
    create_driver = MagicMock(return_value=driver)

    class Factory:
        def _create_driver(self, config):
            return create_driver(config)

        def reload(self):
            reload_calls.append(True)

    monkeypatch.setattr("novel_dev.api.config_routes.llm_factory", Factory())
    monkeypatch.setattr("novel_dev.api.config_routes.find_dotenv", lambda: str(env_file))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/config/llm/test_model",
            json={
                "name": "deepseek",
                "profile": {
                    "provider": "anthropic",
                    "model": "deepseek-v4-flash",
                    "api_key_env": "DEEPSEEK_API_KEY",
                    "api_key": "sk-deepseek-test",
                },
            },
        )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert reload_calls == [True]
    assert "DEEPSEEK_API_KEY='sk-deepseek-test'" in env_file.read_text(encoding="utf-8")
    assert os.environ["DEEPSEEK_API_KEY"] == "sk-deepseek-test"
    call_config = create_driver.call_args.args[0]
    assert call_config.api_key_env == "DEEPSEEK_API_KEY"
    assert call_config.api_key is None


@pytest.mark.asyncio
async def test_test_llm_model_does_not_persist_masked_api_key(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("DEEPSEEK_API_KEY='sk-existing'\n", encoding="utf-8")
    reload_calls = []
    driver = type(
        "Driver",
        (),
        {"acomplete": AsyncMock(return_value=LLMResponse(text="pong"))},
    )()

    class Factory:
        def _create_driver(self, config):
            return driver

        def reload(self):
            reload_calls.append(True)

    monkeypatch.setattr("novel_dev.api.config_routes.llm_factory", Factory())
    monkeypatch.setattr("novel_dev.api.config_routes.find_dotenv", lambda: str(env_file))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-existing")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/config/llm/test_model",
            json={
                "name": "deepseek",
                "profile": {
                    "provider": "anthropic",
                    "model": "deepseek-v4-flash",
                    "api_key_env": "DEEPSEEK_API_KEY",
                    "api_key": "********",
                },
            },
        )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert reload_calls == []
    assert env_file.read_text(encoding="utf-8") == "DEEPSEEK_API_KEY='sk-existing'\n"


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
async def test_get_env_config_masks_api_keys(monkeypatch):
    from novel_dev.config import Settings

    settings = Settings(
        anthropic_api_key="sk-anthropic-secret",
        openai_api_key="sk-openai-secret",
        moonshot_api_key="sk-moonshot-secret",
        minimax_api_key="sk-minimax-secret",
        zhipu_api_key="sk-zhipu-secret",
    )
    monkeypatch.setattr("novel_dev.api.config_routes.settings", settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/config/env")

    assert resp.status_code == 200
    data = resp.json()
    assert data == {
        "anthropic_api_key": "********",
        "openai_api_key": "********",
        "moonshot_api_key": "********",
        "minimax_api_key": "********",
        "zhipu_api_key": "********",
    }
    assert "sk-anthropic-secret" not in str(data)


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


@pytest.mark.asyncio
async def test_save_env_config_requires_admin_token_when_configured(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")

    from novel_dev.config import Settings

    settings = Settings(config_admin_token="secret-token")
    monkeypatch.setattr("novel_dev.api.config_routes.settings", settings)
    monkeypatch.setattr("novel_dev.api.config_routes.find_dotenv", lambda: str(env_file))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.post("/api/config/env", json={"anthropic_api_key": "sk-test"})
        ok = await client.post(
            "/api/config/env",
            json={"anthropic_api_key": "sk-test"},
            headers={"X-Novel-Config-Token": "secret-token"},
        )

    assert missing.status_code == 403
    assert ok.status_code == 200
    assert "sk-test" in env_file.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_save_env_config_ignores_masked_secret_placeholder(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=sk-live-secret\n", encoding="utf-8")

    from novel_dev.config import Settings

    settings = Settings(anthropic_api_key="sk-live-secret")
    monkeypatch.setattr("novel_dev.api.config_routes.settings", settings)
    monkeypatch.setattr("novel_dev.api.config_routes.find_dotenv", lambda: str(env_file))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/config/env", json={"anthropic_api_key": "********"})

    assert resp.status_code == 200
    content = env_file.read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY=sk-live-secret" in content
    assert "********" not in content
