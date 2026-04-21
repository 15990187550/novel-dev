import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.api.routes import OutlineWorkbenchService, get_session, router
from novel_dev.schemas.outline import SynopsisData, VolumeBeat, VolumePlan
from novel_dev.schemas.context import BeatPlan
from novel_dev.schemas.outline_workbench import OutlineMessagesResponse

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
async def test_get_outline_workbench_returns_sidebar_items(async_session, test_client):
    director = NovelDirector(session=async_session)
    synopsis = SynopsisData(
        title="九霄行",
        logline="主角逆势而上",
        core_conflict="家仇与天命相撞",
        estimated_volumes=3,
        estimated_total_chapters=30,
        estimated_total_words=90000,
    )
    volume_plan = VolumePlan(
        volume_id="vol_1",
        volume_number=1,
        title="第一卷",
        summary="卷一摘要",
        total_chapters=10,
        estimated_total_words=30000,
        chapters=[
            VolumeBeat(
                chapter_id="ch_1",
                chapter_number=1,
                title="第一章",
                summary="开篇",
                target_word_count=3000,
                target_mood="tense",
                beats=[BeatPlan(summary="B1", target_mood="tense")],
            )
        ],
    )
    await director.save_checkpoint(
        "n_outline_workbench",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={
            "synopsis_data": synopsis.model_dump(),
            "current_volume_plan": volume_plan.model_dump(),
        },
        volume_id=None,
        chapter_id=None,
    )
    await async_session.commit()

    async with test_client as client:
        resp = await client.get(
            "/api/novels/n_outline_workbench/outline_workbench",
            params={"outline_type": "volume", "outline_ref": "vol_2"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert [item["outline_ref"] for item in data["outline_items"]] == [
        "synopsis",
        "vol_1",
        "vol_2",
        "vol_3",
    ]
    assert [item["title"] for item in data["outline_items"]] == [
        "总纲",
        "第一卷",
        "第2卷",
        "第3卷",
    ]


@pytest.mark.asyncio
async def test_submit_outline_workbench_feedback_returns_updated_assistant_message(async_session, test_client):
    director = NovelDirector(session=async_session)
    synopsis = SynopsisData(
        title="九霄行",
        logline="主角逆势而上",
        core_conflict="家仇与天命相撞",
        estimated_volumes=2,
        estimated_total_chapters=20,
        estimated_total_words=60000,
    )
    await director.save_checkpoint(
        "n_outline_submit",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={"synopsis_data": synopsis.model_dump()},
        volume_id=None,
        chapter_id=None,
    )
    await async_session.commit()

    async with test_client as client:
        resp = await client.post(
            "/api/novels/n_outline_submit/outline_workbench/submit",
            json={
                "outline_type": "volume",
                "outline_ref": "vol_2",
                "content": "第二卷中段冲突不够强，再提高主角代价。",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["assistant_message"]["role"] == "assistant"
    assert data["assistant_message"]["message_type"] == "result"
    assert data["assistant_message"]["content"] == (
        "[stub] 已记录对 volume:vol_2 的反馈：第二卷中段冲突不够强，再提高主角代价。"
    )


@pytest.mark.asyncio
async def test_get_outline_workbench_messages_returns_recent_messages(async_session, test_client):
    director = NovelDirector(session=async_session)
    synopsis = SynopsisData(
        title="九霄行",
        logline="主角逆势而上",
        core_conflict="家仇与天命相撞",
        estimated_volumes=2,
        estimated_total_chapters=20,
        estimated_total_words=60000,
    )
    await director.save_checkpoint(
        "n_outline_messages",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={"synopsis_data": synopsis.model_dump()},
        volume_id=None,
        chapter_id=None,
    )
    await async_session.commit()

    async with test_client as client:
        submit_resp = await client.post(
            "/api/novels/n_outline_messages/outline_workbench/submit",
            json={
                "outline_type": "volume",
                "outline_ref": "vol_1",
                "content": "把第二幕节奏再压紧。",
            },
        )
        assert submit_resp.status_code == 200

        resp = await client.get(
            "/api/novels/n_outline_messages/outline_workbench/messages",
            params={"outline_type": "volume", "outline_ref": "vol_1"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["recent_messages"][0]["role"] == "user"
    assert data["recent_messages"][0]["content"] == "把第二幕节奏再压紧。"
    assert data["recent_messages"][1]["role"] == "assistant"
    assert data["recent_messages"][1]["content"] == "[stub] 已记录对 volume:vol_1 的反馈：把第二幕节奏再压紧。"


@pytest.mark.asyncio
async def test_get_outline_workbench_messages_uses_service_public_method(test_client, monkeypatch):
    async def fake_get_messages(self, novel_id, outline_type, outline_ref):
        assert novel_id == "n_service_only"
        assert outline_type == "volume"
        assert outline_ref == "vol_9"
        return OutlineMessagesResponse(
            session_id="sess_123",
            outline_type=outline_type,
            outline_ref=outline_ref,
            last_result_snapshot={"title": "第九卷"},
            conversation_summary="摘要",
            recent_messages=[
                {
                    "id": "msg_1",
                    "role": "assistant",
                    "message_type": "result",
                    "content": "通过公共方法返回",
                    "meta": {"outline_ref": outline_ref},
                    "created_at": None,
                }
            ],
        )

    monkeypatch.setattr(OutlineWorkbenchService, "get_messages", fake_get_messages, raising=False)

    async with test_client as client:
        resp = await client.get(
            "/api/novels/n_service_only/outline_workbench/messages",
            params={"outline_type": "volume", "outline_ref": "vol_9"},
        )

    assert resp.status_code == 200
    assert resp.json() == {
        "session_id": "sess_123",
        "outline_type": "volume",
        "outline_ref": "vol_9",
        "last_result_snapshot": {"title": "第九卷"},
        "conversation_summary": "摘要",
        "recent_messages": [
            {
                "id": "msg_1",
                "role": "assistant",
                "message_type": "result",
                "content": "通过公共方法返回",
                "meta": {"outline_ref": "vol_9"},
                "created_at": None,
            }
        ],
    }


@pytest.mark.asyncio
async def test_get_outline_workbench_messages_returns_404_when_service_raises_value_error(test_client, monkeypatch):
    async def fake_get_messages(self, novel_id, outline_type, outline_ref):
        raise ValueError(f"Novel state not found: {novel_id}")

    monkeypatch.setattr(OutlineWorkbenchService, "get_messages", fake_get_messages, raising=False)

    async with test_client as client:
        resp = await client.get(
            "/api/novels/n_missing/outline_workbench/messages",
            params={"outline_type": "volume", "outline_ref": "vol_1"},
        )

    assert resp.status_code == 404
    assert resp.json() == {"detail": "Novel state not found: n_missing"}
