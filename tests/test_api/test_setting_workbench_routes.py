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
    assert data["review_batches"][0]["counts"]["setting_card"] == 1
    assert data["review_batches"][0]["changes"][0]["after_snapshot"]["title"] == "宗门"
    assert missing.status_code == 404


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
    assert listed["counts"] == {"setting_card": 1, "entity": 0, "relationship": 0}
    assert listed["changes"][0]["source_session_id"] == setting_session.id
    assert apply_resp.status_code == 200
    assert apply_resp.json()["status"] == "approved"
