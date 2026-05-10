import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from pathlib import Path

from novel_dev.api.routes import router, get_session
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.version_repo import EntityVersionRepository
from novel_dev.schemas.context import ChapterPlan, BeatPlan
from novel_dev.schemas.librarian import ExtractionResult
from novel_dev.services.world_state_review_service import WorldStateReviewService

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_post_librarian_success(async_session, tmp_path, monkeypatch):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        director = NovelDirector(session=async_session)
        plan = ChapterPlan(chapter_number=1, title="Ch1", target_word_count=3000, beats=[BeatPlan(summary="B1", target_mood="tense")]).model_dump()
        plan["chapter_id"] = "c1"
        await director.save_checkpoint(
            "n_api_lib",
            phase=Phase.LIBRARIAN,
            checkpoint_data={"current_volume_plan": {"chapters": [plan]}},
            volume_id="v1",
            chapter_id="c1",
        )
        await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1", novel_id="n_api_lib")
        await ChapterRepository(async_session).update_text("c1", polished_text="abc")
        await async_session.commit()

        monkeypatch.setattr("novel_dev.agents.director.settings.data_dir", str(tmp_path))
        with (
            patch("novel_dev.agents.librarian.LibrarianAgent._call_llm", new_callable=AsyncMock, return_value='{}'),
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/api/novels/n_api_lib/librarian")
        assert response.status_code == 200
        assert response.json()["current_phase"] == Phase.VOLUME_PLANNING.value
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_world_state_review_routes_list_and_approve(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        entity_repo = EntityRepository(async_session)
        version_repo = EntityVersionRepository(async_session)
        await entity_repo.create("e_lz", "character", "林照", novel_id="n_api_review")
        await version_repo.create(
            "e_lz",
            1,
            {
                "canonical_profile": {"name": "林照"},
                "current_state": {"condition": "已死亡，尸身留在黑水城"},
                "observations": {},
                "canonical_meta": {},
            },
            chapter_id="setting",
        )
        await entity_repo.update_version("e_lz", 1)
        extraction = ExtractionResult(
            character_updates=[{
                "entity_id": "林照",
                "state": {"状态": "醒来并开口"},
                "diff_summary": {"source": "chapter"},
            }],
        )
        review = await WorldStateReviewService(async_session).create_pending_review(
            "n_api_review",
            "ch_api_review",
            extraction,
            {
                "status": "confirm_required",
                "confirm_required_items": [{"code": "dead_entity_revived", "entity_name": "林照"}],
            },
        )
        await async_session.commit()

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            list_response = await client.get("/api/novels/n_api_review/world_state_reviews")
            approve_response = await client.post(
                f"/api/novels/n_api_review/world_state_reviews/{review.id}/resolve",
                json={"action": "approve"},
            )

        assert list_response.status_code == 200
        assert list_response.json()["items"][0]["id"] == review.id
        assert approve_response.status_code == 200
        assert approve_response.json()["status"] == "approved"
        latest = await version_repo.get_latest("e_lz")
        assert latest.version == 2
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_world_state_review_resolve_rejects_wrong_novel_before_persist(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        entity_repo = EntityRepository(async_session)
        version_repo = EntityVersionRepository(async_session)
        await entity_repo.create("e_wrong_novel", "character", "林照", novel_id="n_api_review_owner")
        await version_repo.create(
            "e_wrong_novel",
            1,
            {
                "canonical_profile": {"name": "林照"},
                "current_state": {"condition": "已死亡"},
                "observations": {},
                "canonical_meta": {},
            },
            chapter_id="setting",
        )
        await entity_repo.update_version("e_wrong_novel", 1)
        extraction = ExtractionResult(
            character_updates=[{
                "entity_id": "林照",
                "state": {"状态": "复活"},
                "diff_summary": {"source": "chapter"},
            }],
        )
        review = await WorldStateReviewService(async_session).create_pending_review(
            "n_api_review_owner",
            "ch_api_review_owner",
            extraction,
            {"status": "confirm_required", "confirm_required_items": []},
        )
        await async_session.commit()

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/novels/n_api_other/world_state_reviews/{review.id}/resolve",
                json={"action": "approve"},
            )

        assert response.status_code == 404
        latest = await version_repo.get_latest("e_wrong_novel")
        assert latest.version == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_global_consistency_audit_route_reports_relationship_conflict(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        from novel_dev.repositories.relationship_repo import RelationshipRepository

        entity_repo = EntityRepository(async_session)
        rel_repo = RelationshipRepository(async_session)
        await entity_repo.create("e_lz", "character", "林照", novel_id="n_api_audit")
        await entity_repo.create("e_sqh", "character", "苏清寒", novel_id="n_api_audit")
        await rel_repo.create("e_lz", "e_sqh", "ally", novel_id="n_api_audit")
        await rel_repo.create("e_lz", "e_sqh", "enemy", novel_id="n_api_audit")
        await async_session.commit()

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/novels/n_api_audit/global_consistency_audit")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "confirm_required"
        assert payload["confirm_required_items"][0]["code"] == "mutually_exclusive_relationships"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_post_export_success(async_session):
    from novel_dev.services.archive_service import ArchiveService
    import tempfile

    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        director = NovelDirector(session=async_session)
        await director.save_checkpoint("n_api_exp", phase=Phase.COMPLETED, checkpoint_data={})
        await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1", novel_id="n_api_exp")
        await ChapterRepository(async_session).update_text("c1", polished_text="abc")
        await async_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            svc = ArchiveService(async_session, tmpdir)
            await svc.archive("n_api_exp", "c1")
            await async_session.commit()

            mock_settings = type("MockSettings", (), {"data_dir": tmpdir})()
            with patch("novel_dev.api.routes.settings", mock_settings):
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post("/api/novels/n_api_exp/export?format=md")
            assert response.status_code == 200
            assert response.json()["format"] == "md"
            assert "exported_path" in response.json()
            assert Path(response.json()["exported_path"]).is_relative_to(
                Path(tmpdir).resolve() / "novels" / "n_api_exp" / "exports"
            )
            assert "abc" in Path(response.json()["exported_path"]).read_text(encoding="utf-8")
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_archive_stats_success(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        director = NovelDirector(session=async_session)
        await director.save_checkpoint("n_api_stats", phase=Phase.COMPLETED, checkpoint_data={"archive_stats": {"total_word_count": 100, "archived_chapter_count": 1}})
        await async_session.commit()

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/novels/n_api_stats/archive_stats")
        assert response.status_code == 200
        assert response.json()["total_word_count"] == 100
        assert response.json()["archived_chapter_count"] == 1
        assert response.json()["avg_word_count"] == 0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_post_librarian_novel_not_found(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/novels/nonexistent/librarian")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_post_librarian_value_error(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        director = NovelDirector(session=async_session)
        await director.save_checkpoint(
            "n_api_lib_err",
            phase=Phase.LIBRARIAN,
            checkpoint_data={},
            volume_id="v1",
            chapter_id="c_err",
        )
        await async_session.commit()

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/novels/n_api_lib_err/librarian")
        assert response.status_code == 400
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_post_export_bad_format(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/novels/n_api_exp/export?format=pdf")
        assert response.status_code == 400
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_archive_stats_not_found(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/novels/nonexistent/archive_stats")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
