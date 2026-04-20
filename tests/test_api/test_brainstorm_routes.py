import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router, get_session
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.agents.director import NovelDirector, Phase

app = FastAPI()
app.include_router(router)


@pytest.fixture
def test_client(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_brainstorm_start_success(async_session, test_client):
    await DocumentRepository(async_session).create(
        "d1", "n_brain", "worldview", "WV", "天玄大陆"
    )
    await async_session.commit()

    async with test_client as client:
        resp = await client.post("/api/novels/n_brain/brainstorm/start")
        assert resp.status_code == 200
        data = resp.json()
        assert "prompt" in data
        assert "n_brain" in data["prompt"]

        state = await NovelDirector(session=async_session).resume("n_brain")
        assert state.current_phase == Phase.BRAINSTORMING.value


@pytest.mark.asyncio
async def test_brainstorm_start_no_documents(async_session, test_client):
    async with test_client as client:
        resp = await client.post("/api/novels/n_empty/brainstorm/start")
        assert resp.status_code == 400
        assert "文档" in resp.json()["detail"] or "document" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_brainstorm_prompt_success(async_session, test_client):
    """端到端: 导出 prompt 供 Claude Code 使用"""
    await DocumentRepository(async_session).create(
        "d1", "n_prompt", "worldview", "WV", "天玄大陆"
    )
    await DocumentRepository(async_session).create(
        "d2", "n_prompt", "setting", "设定", "主角叫张三"
    )
    await async_session.commit()

    async with test_client as client:
        resp = await client.get("/api/novels/n_prompt/brainstorm/prompt")
        assert resp.status_code == 200
        data = resp.json()
        assert "prompt" in data
        assert data["doc_count"] == 2
        prompt = data["prompt"]
        assert "Markdown" in prompt
        assert "JSON" in prompt
        assert "天玄大陆" in prompt
        assert "张三" in prompt
        assert "=== SYNOPSIS COMPLETE ===" in prompt


@pytest.mark.asyncio
async def test_brainstorm_prompt_no_documents(async_session, test_client):
    async with test_client as client:
        resp = await client.get("/api/novels/n_empty/brainstorm/prompt")
        assert resp.status_code == 400
        assert "文档" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_brainstorm_import_success(async_session, test_client):
    """端到端: 导入 Claude Code 生成的 Synopsis JSON"""
    # 先创建小说状态
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_import",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )
    await async_session.commit()

    # 模拟 Claude Code 生成的 JSON (嵌在 Markdown 中的 JSON 块)
    synopsis_json = """\n```json\n{\n  "title": "测试小说",\n  "logline": "张三想要复仇",\n  "core_conflict": "张三 vs 李四",\n  "themes": ["复仇", "成长"],\n  "character_arcs": [\n    {\n      "name": "张三",\n      "arc_summary": "从废材到天才",\n      "key_turning_points": ["被退婚", "得奇遇", "报仇雪恨"]\n    }\n  ],\n  "milestones": [\n    {\n      "act": "第一幕",\n      "summary": "被退婚",\n      "climax_event": "当众被休"\n    },\n    {\n      "act": "第二幕",\n      "summary": "得奇遇",\n      "climax_event": "山洞得宝"\n    },\n    {\n      "act": "第三幕",\n      "summary": "报仇雪恨",\n      "climax_event": "击败李四"\n    }\n  ],\n  "estimated_volumes": 3,\n  "estimated_total_chapters": 60,\n  "estimated_total_words": 600000\n}\n```\n"""

    async with test_client as client:
        resp = await client.post(
            "/api/novels/n_import/brainstorm/import",
            json={"content": synopsis_json}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "测试小说"
        assert "doc_id" in data
        assert "导入" in data["message"]

        # 验证 checkpoint 已更新
        state = await director.resume("n_import")
        assert state.current_phase == Phase.VOLUME_PLANNING.value
        assert state.checkpoint_data["synopsis_data"]["title"] == "测试小说"


@pytest.mark.asyncio
async def test_brainstorm_import_invalid_json(async_session, test_client):
    """端到端: 导入无效的 JSON 应该报错"""
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_bad",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )
    await async_session.commit()

    async with test_client as client:
        resp = await client.post(
            "/api/novels/n_bad/brainstorm/import",
            json={"content": "这不是有效的 JSON"}
        )
        assert resp.status_code == 400
        assert "JSON" in resp.json()["detail"] or "解析" in resp.json()["detail"]
