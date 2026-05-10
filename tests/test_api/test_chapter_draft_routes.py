import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from pathlib import Path
from unittest.mock import patch

from novel_dev.api.routes import router, get_session
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.context import ChapterPlan, BeatPlan
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.version_repo import EntityVersionRepository
from novel_dev.repositories.chapter_repo import ChapterRepository

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_prepare_context_and_generate_draft(async_session, mock_llm_factory):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        director = NovelDirector(session=async_session)
        chapter_plan = ChapterPlan(
            chapter_number=1,
            title="API Test",
            target_word_count=3000,
            beats=[BeatPlan(summary="Beat 1", target_mood="tense", key_entities=["林风"])],
        )
        await director.save_checkpoint(
            "n_api",
            phase=Phase.CONTEXT_PREPARATION,
            checkpoint_data={"current_chapter_plan": chapter_plan.model_dump()},
            volume_id="v1",
            chapter_id="c1",
        )
        await EntityRepository(async_session).create("e1", "character", "林风", novel_id="n_api")
        await EntityVersionRepository(async_session).create("e1", 1, {}, chapter_id="c1")
        await ChapterRepository(async_session).create("c1", "v1", 1, "API Test")

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/novels/n_api/chapters/c1/context")
            assert resp.status_code == 200
            data = resp.json()
            assert data["active_entities_count"] == 1

            resp2 = await client.post("/api/novels/n_api/chapters/c1/draft")
            assert resp2.status_code == 200
            assert resp2.json()["total_words"] > 0

            resp3 = await client.get("/api/novels/n_api/chapters/c1/draft")
            assert resp3.status_code == 200
            assert resp3.json()["status"] == "drafted"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_export_chapter_rejects_other_novel_chapter(async_session, tmp_path):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        await ChapterRepository(async_session).create(
            "c_other_export",
            "v_export",
            1,
            "Other Export",
            novel_id="n_owner",
        )
        await ChapterRepository(async_session).update_text("c_other_export", polished_text="polished")
        await async_session.commit()

        mock_settings = type("MockSettings", (), {"data_dir": str(tmp_path)})()
        with patch("novel_dev.api.routes.settings", mock_settings):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/novels/n_request/chapters/c_other_export/export.md")

        assert resp.status_code == 404
        assert not (tmp_path / "novels" / "n_request").exists()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_draft_without_context(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        director = NovelDirector(session=async_session)
        await director.save_checkpoint(
            "n_no_ctx",
            phase=Phase.DRAFTING,
            checkpoint_data={},
            volume_id="v1",
            chapter_id="c1",
        )
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/novels/n_no_ctx/chapters/c1/draft")
            assert resp.status_code == 400
            assert "Chapter context not prepared" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_export_chapter_writes_under_data_dir(async_session, tmp_path):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        await ChapterRepository(async_session).create("c_export", "v_export", 1, "Export Me", novel_id="n_export")
        await ChapterRepository(async_session).update_text("c_export", polished_text="polished chapter")
        await async_session.commit()

        mock_settings = type("MockSettings", (), {"data_dir": str(tmp_path)})()
        with patch("novel_dev.api.routes.settings", mock_settings):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/novels/n_export/chapters/c_export/export.md")

        assert resp.status_code == 200
        exported_path = Path(resp.json()["exported_path"])
        assert exported_path == (
            tmp_path.resolve()
            / "novels"
            / "n_export"
            / "archive"
            / "v_export"
            / "c_export.md"
        )
        assert exported_path.read_text(encoding="utf-8") == "polished chapter"
    finally:
        app.dependency_overrides.clear()
