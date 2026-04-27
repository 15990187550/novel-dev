import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router, get_session
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.schemas.outline import VolumePlan, VolumeBeat
from novel_dev.schemas.context import BeatPlan

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_list_chapters(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    repo = NovelStateRepository(async_session)
    await repo.save_checkpoint(
        "n1",
        current_phase="drafting",
        checkpoint_data={
            "current_volume_plan": {
                "volume_id": "v1",
                "volume_number": 1,
                "title": "Vol 1",
                "total_chapters": 2,
                "chapters": [
                    {"chapter_id": "c1", "chapter_number": 1, "title": "Ch1", "summary": "s1"},
                    {"chapter_id": "c2", "chapter_number": 2, "title": "Ch2", "summary": "s2"},
                ],
            }
        },
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1")
    await ChapterRepository(async_session).update_text("c1", polished_text="hello world")
    await ChapterRepository(async_session).update_scores(
        "c1",
        86,
        {"plot_tension": {"score": 88}, "readability": 82},
        {"summary_feedback": "节奏稳定，章末钩子清晰。"},
    )
    await async_session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/n1/chapters")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["items"]) == 2
            c1 = data["items"][0]
            assert c1["chapter_number"] == 1
            assert c1["status"] == "pending"
            assert c1["word_count"] == 10
            assert c1["score_overall"] == 86
            assert c1["score_breakdown"]["plot_tension"]["score"] == 88
            assert c1["review_feedback"]["summary_feedback"] == "节奏稳定，章末钩子清晰。"
            assert data["items"][1]["score_overall"] is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_chapter_text(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1")
    await ChapterRepository(async_session).update_text("c1", raw_draft="draft", polished_text="polished")
    await async_session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/n1/chapters/c1/text")
            assert resp.status_code == 200
            data = resp.json()
            assert data["raw_draft"] == "draft"
            assert data["polished_text"] == "polished"
            assert data["word_count"] == 8
    finally:
        app.dependency_overrides.clear()
