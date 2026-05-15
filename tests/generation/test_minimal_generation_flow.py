import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from novel_dev.api import routes as api_routes
from novel_dev.api.routes import get_session, router
from novel_dev.agents.director import Phase


@pytest.mark.asyncio
async def test_minimal_generation_flow_uses_fake_llm_gate(async_session, tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(router)

    async def override_session():
        yield async_session

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr(api_routes.settings, "data_dir", str(tmp_path))

    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            create_resp = await client.post(
                "/api/novels",
                json={
                    "title": "Fake Gate Novel",
                    "primary_category_slug": "xuanhuan",
                    "secondary_category_slug": "zhutian",
                },
            )
            assert create_resp.status_code == 201
            novel_id = create_resp.json()["novel_id"]
            assert create_resp.json()["current_phase"] == Phase.BRAINSTORMING.value

            session_resp = await client.post(
                f"/api/novels/{novel_id}/settings/sessions",
                json={
                    "title": "核心设定补全",
                    "initial_idea": "补全主角宗门和修炼体系。",
                    "target_categories": ["worldview", "characters"],
                },
            )
            assert session_resp.status_code == 200
            assert session_resp.json()["novel_id"] == novel_id

            upload_resp = await client.post(
                f"/api/novels/{novel_id}/documents/upload",
                json={
                    "filename": "setting.txt",
                    "content": (
                        "世界观：天玄大陆，宗门林立。\n"
                        "修炼体系：炼气、筑基、金丹。\n"
                        "势力：青云宗守护北境。\n"
                        "主角陆照，外门弟子，目标是查明家族旧案。\n"
                    ),
                },
            )
            assert upload_resp.status_code == 200
            pending_id = upload_resp.json()["id"]
            assert upload_resp.json()["extraction_type"] == "setting"

            approve_resp = await client.post(
                f"/api/novels/{novel_id}/documents/pending/approve",
                json={"pending_id": pending_id},
            )
            assert approve_resp.status_code == 200
            assert approve_resp.json()["documents"]

            brainstorm_resp = await client.post(f"/api/novels/{novel_id}/brainstorm")
            assert brainstorm_resp.status_code == 200
            assert brainstorm_resp.json()["title"] == "天玄纪元"

            state_resp = await client.get(f"/api/novels/{novel_id}/state")
            assert state_resp.status_code == 200
            assert state_resp.json()["current_phase"] == Phase.VOLUME_PLANNING.value

            volume_plan_resp = await client.post(f"/api/novels/{novel_id}/volume_plan")
            assert volume_plan_resp.status_code == 200
            volume_plan = volume_plan_resp.json()
            assert volume_plan["volume_id"] == "vol_1"
            assert volume_plan["chapters"][0]["chapter_id"] == "ch_1"
            assert volume_plan["chapters"][0]["title"] == "第一章"

            export_resp = await client.post(f"/api/novels/{novel_id}/export?format=md")
            assert export_resp.status_code == 200
            assert export_resp.json()["exported_path"]
    finally:
        app.dependency_overrides.clear()
