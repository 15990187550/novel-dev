import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router, get_session
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.context import ChapterPlan, BeatPlan, ChapterContext, LocationContext
from novel_dev.repositories.chapter_repo import ChapterRepository

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_advance_and_get_review(async_session, mock_llm_factory):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        director = NovelDirector(session=async_session)
        plan = ChapterPlan(chapter_number=1, title="API Review", target_word_count=100, beats=[BeatPlan(summary="B1", target_mood="tense")])
        context = ChapterContext(
            chapter_plan=plan,
            style_profile={},
            worldview_summary="",
            active_entities=[],
            location_context=LocationContext(current=""),
            timeline_events=[],
            pending_foreshadowings=[],
        )
        await director.save_checkpoint(
            "n_rev",
            phase=Phase.REVIEWING,
            checkpoint_data={"chapter_context": context.model_dump()},
            volume_id="v1",
            chapter_id="c1",
        )
        await ChapterRepository(async_session).create("c1", "v1", 1, "API Review")
        await ChapterRepository(async_session).update_text("c1", raw_draft="a" * 100, polished_text="a" * 100)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/novels/n_rev/advance")
            assert resp.status_code == 200
            assert resp.json()["current_phase"] == Phase.EDITING.value

            resp2 = await client.get("/api/novels/n_rev/review")
            assert resp2.status_code == 200
            assert resp2.json()["score_overall"] is not None

            # advance to FAST_REVIEWING, then to LIBRARIAN, and call /fast_review
            resp3 = await client.post("/api/novels/n_rev/advance")
            assert resp3.status_code == 200
            assert resp3.json()["current_phase"] == Phase.FAST_REVIEWING.value

            resp4 = await client.post("/api/novels/n_rev/advance")
            assert resp4.status_code == 200
            assert resp4.json()["current_phase"] == Phase.LIBRARIAN.value

            resp5 = await client.get("/api/novels/n_rev/fast_review")
            assert resp5.status_code == 200
            assert resp5.json()["fast_review_score"] is not None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_review_no_chapter(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        director = NovelDirector(session=async_session)
        await director.save_checkpoint(
            "n_no_ch",
            phase=Phase.REVIEWING,
            checkpoint_data={},
            volume_id="v1",
            chapter_id=None,
        )

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/n_no_ch/review")
            assert resp.status_code == 404
            assert "Current chapter not set" in resp.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_fast_review_no_chapter(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        director = NovelDirector(session=async_session)
        await director.save_checkpoint(
            "n_no_ch2",
            phase=Phase.FAST_REVIEWING,
            checkpoint_data={},
            volume_id="v1",
            chapter_id=None,
        )

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/n_no_ch2/fast_review")
            assert resp.status_code == 404
            assert "Current chapter not set" in resp.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_review_chapter_not_found(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        director = NovelDirector(session=async_session)
        await director.save_checkpoint(
            "n_missing_ch",
            phase=Phase.REVIEWING,
            checkpoint_data={},
            volume_id="v1",
            chapter_id="nonexistent_chapter",
        )

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/n_missing_ch/review")
            assert resp.status_code == 404
            assert "Chapter not found" in resp.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_fast_review_chapter_not_found(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        director = NovelDirector(session=async_session)
        await director.save_checkpoint(
            "n_missing_ch2",
            phase=Phase.FAST_REVIEWING,
            checkpoint_data={},
            volume_id="v1",
            chapter_id="nonexistent_chapter",
        )

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/n_missing_ch2/fast_review")
            assert resp.status_code == 404
            assert "Chapter not found" in resp.text
    finally:
        app.dependency_overrides.clear()
