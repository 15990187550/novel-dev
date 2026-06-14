import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.api.routes import get_session, router
from novel_dev.repositories.chapter_repo import ChapterRepository


app = FastAPI()
app.include_router(router)


async def _seed_manual_review_chapter_with_attempt(async_session, *, novel_id="n_manual_retry", chapter_id="c_manual_retry", attempt_index=5):
    director = NovelDirector(async_session)
    await director.save_checkpoint(
        novel_id,
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={
            "quality_gate": {
                "status": "manual_review_required",
                "warning_items": [{"code": "required_payoff", "message": "缺少章节承诺兑现"}],
                "summary": "存在需要人工确认的质量问题，停止自动归档。",
            },
            "quality_issues": [{"code": "required_payoff"}],
        },
        volume_id="v1",
        chapter_id=chapter_id,
    )
    repo = ChapterRepository(async_session)
    await repo.create(chapter_id, "v1", 1, "Manual Retry", novel_id=novel_id)
    await repo.update_text(chapter_id, raw_draft="raw", polished_text="polished")
    await repo.update_quality_gate(
        chapter_id,
        quality_status="manual_review_required",
        quality_reasons={
            "status": "manual_review_required",
            "warning_items": [{"code": "required_payoff", "message": "缺少章节承诺兑现"}],
        },
        world_state_ingested=False,
    )
    # Set attempt_index
    ch = await repo.get_by_id(chapter_id)
    ch.attempt_index = attempt_index
    await async_session.commit()
    return director, repo


@pytest.mark.asyncio
async def test_manual_review_continue_retry(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        director, repo = await _seed_manual_review_chapter_with_attempt(
            async_session,
            novel_id="n_manual_retry",
            chapter_id="c_manual_retry",
            attempt_index=5,
        )

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/novels/n_manual_retry/chapters/c_manual_retry/quality/manual_review",
                json={"action": "continue_retry"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["quality_status"] == "unchecked"

        # Verify attempt_index was reset in DB
        chapter = await repo.get_by_id("c_manual_retry")
        assert chapter.attempt_index == 0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_manual_review_accept_version(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        director, repo = await _seed_manual_review_chapter_with_attempt(
            async_session,
            novel_id="n_manual_accept",
            chapter_id="c_manual_accept",
            attempt_index=3,
        )

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/novels/n_manual_accept/chapters/c_manual_accept/quality/manual_review",
                json={"action": "accept_version", "note": "接受当前版本"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["quality_status"] == "warn"
        assert data["current_phase"] == Phase.LIBRARIAN.value
        assert data["quality_reasons"]["manual_review"]["action"] == "accept_version"

        # Verify attempt_index was NOT reset
        chapter = await repo.get_by_id("c_manual_accept")
        assert chapter.attempt_index == 3
    finally:
        app.dependency_overrides.clear()
