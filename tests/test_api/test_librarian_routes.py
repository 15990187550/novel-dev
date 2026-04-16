import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router, get_session
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.schemas.context import ChapterPlan, BeatPlan

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_post_librarian_success(async_session):
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
        await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1")
        await ChapterRepository(async_session).update_text("c1", polished_text="abc")
        await async_session.commit()

        with patch("novel_dev.agents.librarian.LibrarianAgent._call_llm", new_callable=AsyncMock, return_value='{}'):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/api/novels/n_api_lib/librarian")
        assert response.status_code == 200
        assert response.json()["current_phase"] == Phase.VOLUME_PLANNING.value
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
        await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1")
        await ChapterRepository(async_session).update_text("c1", polished_text="abc")
        await async_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            svc = ArchiveService(async_session, tmpdir)
            await svc.archive("n_api_exp", "c1")
            await async_session.commit()

            mock_settings = type("MockSettings", (), {"markdown_output_dir": tmpdir})()
            with patch("novel_dev.api.routes.settings", mock_settings):
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post("/api/novels/n_api_exp/export?format=md")
            assert response.status_code == 200
            assert response.json()["format"] == "md"
            assert "exported_path" in response.json()
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
    finally:
        app.dependency_overrides.clear()
