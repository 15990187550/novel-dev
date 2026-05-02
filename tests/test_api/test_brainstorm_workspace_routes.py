import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.api.routes import get_session, router
from novel_dev.services.brainstorm_workspace_service import BrainstormWorkspaceService

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


async def _seed_route_suggestion_card(async_session, novel_id: str, status: str = "active"):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        novel_id,
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )
    service = BrainstormWorkspaceService(async_session)
    await service.merge_suggestion_cards(
        novel_id,
        [
            {
                "operation": "upsert",
                "card_id": "card_route_1",
                "card_type": "character",
                "merge_key": "character:route",
                "title": "林风",
                "summary": "主角建议卡",
                "status": status,
                "source_outline_refs": ["synopsis"],
                "payload": {"canonical_name": "林风"},
                "display_order": 1,
            }
        ],
    )
    await async_session.commit()


@pytest.mark.asyncio
async def test_patch_suggestion_card_resolves_card(async_session, test_client):
    await _seed_route_suggestion_card(async_session, "n_workspace_card_patch")

    async with test_client as client:
        resp = await client.patch(
            "/api/novels/n_workspace_card_patch/brainstorm/suggestion_cards/card_route_1",
            json={"action": "resolve"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["workspace"]["setting_suggestion_cards"][0]["status"] == "resolved"
    assert data["pending_extraction"] is None


@pytest.mark.asyncio
async def test_patch_suggestion_card_returns_404_for_missing_card(
    async_session,
    test_client,
):
    await _seed_route_suggestion_card(async_session, "n_workspace_card_missing")

    async with test_client as client:
        resp = await client.patch(
            "/api/novels/n_workspace_card_missing/brainstorm/suggestion_cards/nope",
            json={"action": "resolve"},
        )

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_patch_suggestion_card_returns_409_for_illegal_status(
    async_session,
    test_client,
):
    await _seed_route_suggestion_card(
        async_session,
        "n_workspace_card_illegal_status",
        status="submitted",
    )

    async with test_client as client:
        resp = await client.patch(
            "/api/novels/n_workspace_card_illegal_status/brainstorm/suggestion_cards/card_route_1",
            json={"action": "reactivate"},
        )

    assert resp.status_code == 409
    assert "cannot be reactivated" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_start_brainstorm_workspace_returns_active_workspace(async_session, test_client):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_workspace_start",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )
    await async_session.commit()

    async with test_client as client:
        resp = await client.post("/api/novels/n_workspace_start/brainstorm/workspace/start")

    assert resp.status_code == 200
    data = resp.json()
    assert data["novel_id"] == "n_workspace_start"
    assert data["status"] == "active"
    assert data["outline_drafts"] == {}
    assert data["setting_docs_draft"] == []


@pytest.mark.asyncio
async def test_get_brainstorm_workspace_returns_saved_drafts(async_session, test_client):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_workspace_get",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )
    workspace_service = BrainstormWorkspaceService(async_session)
    await workspace_service.save_outline_draft(
        novel_id="n_workspace_get",
        outline_type="synopsis",
        outline_ref="synopsis",
        result_snapshot={"title": "工作区总纲"},
    )
    await async_session.commit()

    async with test_client as client:
        resp = await client.get("/api/novels/n_workspace_get/brainstorm/workspace")

    assert resp.status_code == 200
    assert resp.json()["outline_drafts"]["synopsis:synopsis"] == {"title": "工作区总纲"}


@pytest.mark.asyncio
async def test_submit_brainstorm_workspace_materializes_formal_data(async_session, test_client):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_workspace_submit",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )
    workspace_service = BrainstormWorkspaceService(async_session)
    await workspace_service.save_outline_draft(
        novel_id="n_workspace_submit",
        outline_type="synopsis",
        outline_ref="synopsis",
        result_snapshot={
            "title": "九霄行",
            "logline": "林风逆势而上。",
            "core_conflict": "林风对抗长老会。",
            "themes": [],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 1,
            "estimated_total_chapters": 80,
            "estimated_total_words": 240000,
        },
    )
    await workspace_service.save_outline_draft(
        novel_id="n_workspace_submit",
        outline_type="volume",
        outline_ref="vol_1",
        result_snapshot={"title": "第一卷"},
    )
    await workspace_service.merge_setting_drafts(
        "n_workspace_submit",
        [
            {
                "draft_id": "draft_1",
                "source_outline_ref": "synopsis",
                "source_kind": "character",
                "target_import_mode": "explicit_type",
                "target_doc_type": "concept",
                "title": "林风",
                "content": "青云宗外门弟子。",
                "order_index": 1,
            }
        ],
    )
    await async_session.commit()

    async with test_client as client:
        resp = await client.post("/api/novels/n_workspace_submit/brainstorm/workspace/submit")

    assert resp.status_code == 200
    data = resp.json()
    assert data["synopsis_title"] == "九霄行"
    assert data["pending_setting_count"] == 1
    assert data["volume_outline_count"] == 1


@pytest.mark.asyncio
async def test_submit_brainstorm_workspace_allows_synopsis_without_all_volume_drafts(
    async_session,
    test_client,
):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_workspace_submit_synopsis_only",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )
    workspace_service = BrainstormWorkspaceService(async_session)
    await workspace_service.save_outline_draft(
        novel_id="n_workspace_submit_synopsis_only",
        outline_type="synopsis",
        outline_ref="synopsis",
        result_snapshot={
            "title": "九霄行",
            "logline": "林风逆势而上。",
            "core_conflict": "林风对抗长老会。",
            "themes": [],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 7,
            "estimated_total_chapters": 80,
            "estimated_total_words": 240000,
        },
    )
    await async_session.commit()

    async with test_client as client:
        resp = await client.post(
            "/api/novels/n_workspace_submit_synopsis_only/brainstorm/workspace/submit"
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["synopsis_title"] == "九霄行"
    assert data["pending_setting_count"] == 0
    assert data["volume_outline_count"] == 0
