import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from novel_dev.api.routes import get_session, router
from novel_dev.db.models import NovelState
from novel_dev.repositories.setting_workbench_repo import SettingWorkbenchRepository

pytestmark = pytest.mark.asyncio

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


async def test_setting_workbench_create_session_and_reply(async_session, test_client, monkeypatch):
    async_session.add(NovelState(novel_id="novel-api", current_phase="brainstorming", checkpoint_data={}))
    await async_session.commit()

    async def fake_reply(self, *, novel_id, session_id, content):
        session = await self.repo.get_session(session_id)
        return {
            "session": session,
            "assistant_message": "请补充核心势力。",
            "questions": ["主角敌对势力是谁？"],
        }

    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.SettingWorkbenchService.reply_to_session",
        fake_reply,
    )

    async with test_client as client:
        created = await client.post(
            "/api/novels/novel-api/settings/sessions",
            json={"title": "主角阵营设定", "initial_idea": "废脉少年", "target_categories": ["人物", "势力"]},
        )
        assert created.status_code == 200
        session_id = created.json()["id"]

        reply = await client.post(
            f"/api/novels/novel-api/settings/sessions/{session_id}/reply",
            json={"content": "主角来自没落宗门"},
        )

    assert reply.status_code == 200
    assert reply.json()["assistant_message"] == "请补充核心势力。"
    assert reply.json()["questions"] == ["主角敌对势力是谁？"]


async def test_setting_workbench_get_session_includes_messages_and_batches(async_session, test_client):
    async_session.add(NovelState(novel_id="novel-api-detail", current_phase="brainstorming", checkpoint_data={}))
    repo = SettingWorkbenchRepository(async_session)
    setting_session = await repo.create_session(
        novel_id="novel-api-detail",
        title="宗门设定",
        target_categories=["势力"],
    )
    await repo.add_message(session_id=setting_session.id, role="user", content="补充宗门")
    batch = await repo.create_review_batch(
        novel_id="novel-api-detail",
        source_type="ai_session",
        source_session_id=setting_session.id,
        summary="新增宗门设定",
    )
    await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        after_snapshot={"doc_type": "setting", "title": "宗门", "content": "没落宗门。"},
        source_session_id=setting_session.id,
    )
    await async_session.commit()

    async with test_client as client:
        resp = await client.get(f"/api/novels/novel-api-detail/settings/sessions/{setting_session.id}")
        missing = await client.get("/api/novels/novel-api-detail/settings/sessions/missing")

    assert resp.status_code == 200
    data = resp.json()
    assert data["session"]["id"] == setting_session.id
    assert data["messages"][0]["content"] == "补充宗门"
    assert data["review_batches"][0]["source_session_title"] == "宗门设定"
    assert data["review_batches"][0]["counts"]["setting_card"] == 1
    assert data["review_batches"][0]["changes"][0]["after_snapshot"]["title"] == "宗门"
    assert missing.status_code == 404


async def test_setting_workbench_overview_list_and_review_detail(async_session, test_client):
    async_session.add(NovelState(novel_id="novel-api-overview", current_phase="brainstorming", checkpoint_data={}))
    repo = SettingWorkbenchRepository(async_session)
    setting_session = await repo.create_session(
        novel_id="novel-api-overview",
        title="设定工作台会话",
        target_categories=["体系"],
    )
    batch = await repo.create_review_batch(
        novel_id="novel-api-overview",
        source_type="ai_session",
        source_session_id=setting_session.id,
        summary="新增体系设定",
    )
    await repo.add_review_change(
        batch_id=batch.id,
        target_type="entity",
        operation="create",
        after_snapshot={"type": "item", "name": "道种", "state": {}},
        source_session_id=setting_session.id,
    )
    await async_session.commit()

    async with test_client as client:
        workbench = await client.get("/api/novels/novel-api-overview/settings/workbench")
        sessions = await client.get("/api/novels/novel-api-overview/settings/sessions")
        detail = await client.get(f"/api/novels/novel-api-overview/settings/review_batches/{batch.id}")

    assert workbench.status_code == 200
    assert workbench.json()["sessions"][0]["title"] == "设定工作台会话"
    assert workbench.json()["review_batches"][0]["source_session_title"] == "设定工作台会话"
    assert sessions.status_code == 200
    assert sessions.json()["items"][0]["id"] == setting_session.id
    assert detail.status_code == 200
    assert detail.json()["counts"] == {"setting_card": 0, "entity": 1, "relationship": 0}
    assert detail.json()["source_session_title"] == "设定工作台会话"


async def test_setting_workbench_generate_route_creates_review_batch(async_session, test_client, monkeypatch):
    async_session.add(NovelState(novel_id="novel-api-generate", current_phase="brainstorming", checkpoint_data={}))
    repo = SettingWorkbenchRepository(async_session)
    setting_session = await repo.create_session(
        novel_id="novel-api-generate",
        title="AI 生成设定",
        target_categories=["势力"],
        status="ready_to_generate",
    )
    await async_session.commit()

    async def fake_generate(self, *, novel_id, session_id):
        batch = await self.repo.create_review_batch(
            novel_id=novel_id,
            source_type="ai_session",
            source_session_id=session_id,
            summary="新增 1 张势力设定",
        )
        await self.repo.add_review_change(
            batch_id=batch.id,
            target_type="setting_card",
            operation="create",
            after_snapshot={"doc_type": "setting", "title": "势力格局", "content": "青云门与魔宗对立。"},
            source_session_id=session_id,
        )
        return batch

    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.SettingWorkbenchService.generate_review_batch",
        fake_generate,
    )

    async with test_client as client:
        resp = await client.post(
            f"/api/novels/novel-api-generate/settings/sessions/{setting_session.id}/generate",
            json={},
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["summary"] == "新增 1 张势力设定"
    assert payload["source_session_title"] == "AI 生成设定"
    assert payload["counts"] == {"setting_card": 1, "entity": 0, "relationship": 0}


async def test_setting_workbench_generate_route_maps_errors(async_session, test_client, monkeypatch):
    async_session.add(NovelState(novel_id="novel-api-generate-errors", current_phase="brainstorming", checkpoint_data={}))
    await async_session.commit()

    async def fake_generate_failure(self, *, novel_id, session_id):
        if session_id == "missing":
            raise ValueError("Setting generation session not found")
        raise RuntimeError("模型返回的设定为空")

    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.SettingWorkbenchService.generate_review_batch",
        fake_generate_failure,
    )

    async with test_client as client:
        missing = await client.post(
            "/api/novels/novel-api-generate-errors/settings/sessions/missing/generate",
            json={},
        )
        failed = await client.post(
            "/api/novels/novel-api-generate-errors/settings/sessions/sgs-failed/generate",
            json={},
        )

    assert missing.status_code == 404
    assert failed.status_code == 422
    assert failed.json()["detail"] == "模型返回的设定为空"


async def test_setting_workbench_generate_batch_and_apply_review(async_session, test_client):
    async_session.add(NovelState(novel_id="novel-api-review", current_phase="brainstorming", checkpoint_data={}))
    repo = SettingWorkbenchRepository(async_session)
    setting_session = await repo.create_session(
        novel_id="novel-api-review",
        title="修炼体系",
        target_categories=["功法"],
    )
    batch = await repo.create_review_batch(
        novel_id="novel-api-review",
        source_type="ai_session",
        source_session_id=setting_session.id,
        summary="新增 1 张设定卡片",
    )
    change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        after_snapshot={"doc_type": "setting", "title": "修炼体系", "content": "九境。"},
        source_session_id=setting_session.id,
    )
    await async_session.commit()

    async with test_client as client:
        list_resp = await client.get("/api/novels/novel-api-review/settings/review_batches")
        apply_resp = await client.post(
            f"/api/novels/novel-api-review/settings/review_batches/{batch.id}/apply",
            json={"decisions": [{"change_id": change.id, "decision": "approve"}]},
        )

    assert list_resp.status_code == 200
    listed = list_resp.json()["items"][0]
    assert listed["summary"] == "新增 1 张设定卡片"
    assert listed["source_session_title"] == "修炼体系"
    assert listed["counts"] == {"setting_card": 1, "entity": 0, "relationship": 0}
    assert listed["changes"][0]["source_session_id"] == setting_session.id
    assert apply_resp.status_code == 200
    assert apply_resp.json()["status"] == "approved"


async def test_setting_workbench_apply_missing_batch_returns_404(async_session, test_client):
    async_session.add(NovelState(novel_id="novel-api-review-missing", current_phase="brainstorming", checkpoint_data={}))
    await async_session.commit()

    async with test_client as client:
        resp = await client.post(
            "/api/novels/novel-api-review-missing/settings/review_batches/missing/apply",
            json={"decisions": []},
        )

    assert resp.status_code == 404
