import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.api.routes import get_session, router
from novel_dev.repositories.chapter_repo import ChapterRepository


app = FastAPI()
app.include_router(router)


async def _seed_manual_review_chapter(async_session, *, novel_id="n_manual_quality", chapter_id="c_manual_quality"):
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
    await repo.create(chapter_id, "v1", 1, "Manual Quality", novel_id=novel_id)
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
    await async_session.commit()
    return director, repo


@pytest.mark.asyncio
async def test_manual_review_approve_marks_warn_and_moves_to_librarian(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        director, repo = await _seed_manual_review_chapter(async_session)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/novels/n_manual_quality/chapters/c_manual_quality/quality/manual_review",
                json={"action": "approve", "note": "确认可带告警归档"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["quality_status"] == "warn"
        assert data["current_phase"] == Phase.LIBRARIAN.value
        assert data["quality_reasons"]["manual_review"]["action"] == "approve"
        assert data["quality_reasons"]["manual_review"]["note"] == "确认可带告警归档"

        chapter = await repo.get_by_id("c_manual_quality")
        assert chapter.quality_status == "warn"
        assert chapter.quality_reasons["manual_review"]["action"] == "approve"
        state = await director.resume("n_manual_quality")
        assert state.current_phase == Phase.LIBRARIAN.value
        assert state.checkpoint_data["quality_gate"]["status"] == "warn"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_manual_review_return_to_editing_resets_quality_and_records_audit(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        director, repo = await _seed_manual_review_chapter(
            async_session,
            novel_id="n_manual_return",
            chapter_id="c_manual_return",
        )

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/novels/n_manual_return/chapters/c_manual_return/quality/manual_review",
                json={"action": "return_to_editing", "note": "补写缺失线索"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["quality_status"] == "unchecked"
        assert data["current_phase"] == Phase.EDITING.value
        assert data["quality_reasons"]["manual_review"]["action"] == "return_to_editing"

        chapter = await repo.get_by_id("c_manual_return")
        assert chapter.quality_status == "unchecked"
        state = await director.resume("n_manual_return")
        assert state.current_phase == Phase.EDITING.value
        assert state.checkpoint_data["manual_review_decision"]["note"] == "补写缺失线索"
        assert "quality_gate" not in state.checkpoint_data
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_manual_review_action_rejects_non_manual_status(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        director = NovelDirector(async_session)
        await director.save_checkpoint("n_not_manual", phase=Phase.LIBRARIAN, checkpoint_data={}, volume_id="v1", chapter_id="c1")
        repo = ChapterRepository(async_session)
        await repo.create("c1", "v1", 1, "Not Manual", novel_id="n_not_manual")
        await repo.update_text("c1", polished_text="polished")
        await repo.update_quality_gate("c1", quality_status="warn", quality_reasons={"status": "warn"})
        await async_session.commit()

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/novels/n_not_manual/chapters/c1/quality/manual_review",
                json={"action": "approve"},
            )

        assert response.status_code == 409
        assert "manual_review_required" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()
