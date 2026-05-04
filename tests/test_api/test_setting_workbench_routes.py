import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from novel_dev.api.routes import get_session, router


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
async def test_create_setting_generation_session_returns_session_and_initial_message(test_client):
    async with test_client as client:
        response = await client.post(
            "/api/novels/novel-api/settings/sessions",
            json={
                "title": "修炼体系补全",
                "initial_idea": "主角从废脉开始修炼",
                "target_categories": ["功法", "体系设定"],
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["title"] == "修炼体系补全"
        assert payload["status"] == "clarifying"
        assert payload["target_categories"] == ["功法", "体系设定"]

        detail = await client.get(f"/api/novels/novel-api/settings/sessions/{payload['id']}")
        assert detail.status_code == 200
        detail_payload = detail.json()
        assert detail_payload["session"]["id"] == payload["id"]
        assert detail_payload["messages"][0]["role"] == "user"
        assert detail_payload["messages"][0]["content"] == "主角从废脉开始修炼"


@pytest.mark.asyncio
async def test_list_setting_generation_sessions(test_client):
    async with test_client as client:
        created = await client.post(
            "/api/novels/novel-api/settings/sessions",
            json={
                "title": "主角阵营设定",
                "initial_idea": "",
                "target_categories": ["人物"],
            },
        )
        assert created.status_code == 200

        response = await client.get("/api/novels/novel-api/settings/sessions")
        assert response.status_code == 200
        payload = response.json()
        assert payload["items"][0]["title"] == "主角阵营设定"


@pytest.mark.asyncio
async def test_get_setting_workbench_returns_sessions_and_review_batches(test_client):
    async with test_client as client:
        created = await client.post(
            "/api/novels/novel-api/settings/sessions",
            json={
                "title": "北境宗门设定",
                "initial_idea": "北境宗门互相制衡",
                "target_categories": ["势力"],
            },
        )
        assert created.status_code == 200

        response = await client.get("/api/novels/novel-api/settings/workbench")

        assert response.status_code == 200
        payload = response.json()
        assert payload["sessions"][0]["title"] == "北境宗门设定"
        assert payload["review_batches"] == []


@pytest.mark.asyncio
async def test_apply_setting_review_batch_applies_pending_changes(test_client, async_session):
    from novel_dev.db.models import NovelDocument
    from novel_dev.repositories.setting_workbench_repo import SettingWorkbenchRepository

    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="novel-apply-api",
        source_type="ai_session",
        status="pending",
        summary="新增设定",
        input_snapshot={},
    )
    change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        after_snapshot={
            "title": "修炼体系",
            "doc_type": "setting",
            "content": "境界分为炼气、筑基、金丹。",
        },
    )
    await async_session.commit()

    async with test_client as client:
        response = await client.post(
            f"/api/novels/novel-apply-api/settings/review_batches/{batch.id}/apply",
            json={"decisions": [{"change_id": change.id, "decision": "approve"}]},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "approved"
    assert payload["applied"] == 1
    assert payload["rejected"] == 0
    assert payload["failed"] == 0

    result = await async_session.execute(
        select(NovelDocument).where(
            NovelDocument.novel_id == "novel-apply-api",
            NovelDocument.title == "修炼体系",
        )
    )
    doc = result.scalar_one()
    assert doc.content == "境界分为炼气、筑基、金丹。"
