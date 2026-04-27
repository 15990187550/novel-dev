import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from novel_dev.agents.context_agent import ContextAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.api.routes import get_session, router
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.schemas.context import BeatPlan, ChapterContext, ChapterPlan, LocationContext
from novel_dev.schemas.outline import SynopsisData, VolumeBeat, VolumePlan
from novel_dev.services.flow_control_service import FlowControlService
from novel_dev.repositories.generation_job_repo import GenerationJobRepository
from novel_dev.services.chapter_generation_service import ChapterGenerationService


app = FastAPI()
app.include_router(router)


def build_test_volume(volume_id: str, chapter_prefix: str, count: int = 2) -> VolumePlan:
    chapters = [
        VolumeBeat(
            chapter_id=f"{chapter_prefix}_{index}",
            chapter_number=index,
            title=f"Chapter {index}",
            summary=f"第{index}章",
            target_word_count=80,
            target_mood="tense",
            beats=[BeatPlan(summary=f"B{index}", target_mood="tense")],
        )
        for index in range(1, count + 1)
    ]
    return VolumePlan(
        volume_id=volume_id,
        volume_number=1,
        title="Test Volume",
        summary="卷纲",
        total_chapters=count,
        estimated_total_words=80 * count,
        chapters=chapters,
    )


@pytest.mark.asyncio
async def test_plan_volume_returns_review_status_without_undefined_state(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        director = NovelDirector(session=async_session)
        synopsis = SynopsisData(
            title="Route Plan",
            logline="Logline",
            core_conflict="Conflict",
            estimated_volumes=1,
            estimated_total_chapters=1,
            estimated_total_words=3000,
        )
        await director.save_checkpoint(
            "n_route_plan",
            phase=Phase.VOLUME_PLANNING,
            checkpoint_data={"synopsis_data": synopsis.model_dump()},
        )

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/novels/n_route_plan/volume_plan")

        assert response.status_code == 200
        data = response.json()
        assert data["volume_id"] == "vol_1"
        assert data["review_status"]["status"] == "accepted"
        assert data["chapters"][0]["chapter_id"] == "ch_1"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_auto_run_route_creates_queued_generation_job(async_session, monkeypatch):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    monkeypatch.setattr("novel_dev.api.routes.schedule_generation_job", lambda job_id: None)
    transport = ASGITransport(app=app)
    try:
        chapters = [
            VolumeBeat(
                chapter_id="ch_auto_1",
                chapter_number=1,
                title="Auto One",
                summary="第一章",
                target_word_count=80,
                target_mood="tense",
                beats=[BeatPlan(summary="B1", target_mood="tense")],
            ),
            VolumeBeat(
                chapter_id="ch_auto_2",
                chapter_number=2,
                title="Auto Two",
                summary="第二章",
                target_word_count=80,
                target_mood="tense",
                beats=[BeatPlan(summary="B2", target_mood="tense")],
            ),
        ]
        plan = VolumePlan(
            volume_id="vol_auto",
            volume_number=1,
            title="Auto Volume",
            summary="卷纲",
            total_chapters=2,
            estimated_total_words=160,
            chapters=chapters,
        )
        director = NovelDirector(session=async_session)
        await director.save_checkpoint(
            "n_auto",
            phase=Phase.CONTEXT_PREPARATION,
            checkpoint_data={
                "current_volume_plan": plan.model_dump(),
                "current_chapter_plan": chapters[0].model_dump(),
            },
            volume_id="vol_auto",
            chapter_id="ch_auto_1",
        )
        await ChapterRepository(async_session).ensure_from_plan("n_auto", "vol_auto", chapters[0])

        async with AsyncClient(transport=transport, base_url="http://test", timeout=120) as client:
            response = await client.post("/api/novels/n_auto/chapters/auto-run", json={"max_chapters": 1})

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "queued"
        assert data["job_type"] == "chapter_auto_run"
        job = await GenerationJobRepository(async_session).get_by_id(data["job_id"])
        assert job.novel_id == "n_auto"
        assert job.request_payload == {"max_chapters": 1, "stop_at_volume_end": True}

        async with AsyncClient(transport=transport, base_url="http://test", timeout=120) as client:
            status_response = await client.get(f"/api/novels/n_auto/generation_jobs/{data['job_id']}")
        assert status_response.status_code == 200
        assert status_response.json()["job_id"] == data["job_id"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_auto_run_background_job_archives_and_moves_to_next_context_preparation(async_session):
    plan = build_test_volume("vol_auto_bg", "ch_auto_bg")
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_auto_bg",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={
            "current_volume_plan": plan.model_dump(),
            "current_chapter_plan": plan.chapters[0].model_dump(),
        },
        volume_id="vol_auto_bg",
        chapter_id="ch_auto_bg_1",
    )
    await ChapterRepository(async_session).ensure_from_plan("n_auto_bg", "vol_auto_bg", plan.chapters[0])
    job = await GenerationJobRepository(async_session).create(
        "n_auto_bg",
        "chapter_auto_run",
        {"max_chapters": 1, "stop_at_volume_end": True},
    )
    await async_session.commit()

    from novel_dev.services.generation_job_service import run_generation_job

    await run_generation_job(job.id)

    refreshed = await GenerationJobRepository(async_session).get_by_id(job.id)
    assert refreshed.status == "succeeded"
    assert refreshed.result_payload["completed_chapters"] == ["ch_auto_bg_1"]
    assert refreshed.result_payload["stopped_reason"] == "max_chapters_reached"

    first = await ChapterRepository(async_session).get_by_id("ch_auto_bg_1")
    second = await ChapterRepository(async_session).get_by_id("ch_auto_bg_2")
    assert first.status == "archived"
    assert first.raw_draft
    assert first.polished_text
    assert first.score_overall is not None
    assert first.fast_review_feedback
    assert second is not None


@pytest.mark.asyncio
async def test_auto_run_background_job_updates_heartbeat(async_session):
    plan = build_test_volume("vol_heartbeat_bg", "ch_heartbeat_bg")
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_auto_heartbeat_bg",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={
            "current_volume_plan": plan.model_dump(),
            "current_chapter_plan": plan.chapters[0].model_dump(),
        },
        volume_id="vol_heartbeat_bg",
        chapter_id="ch_heartbeat_bg_1",
    )
    repo = GenerationJobRepository(async_session)
    job = await repo.create(
        "n_auto_heartbeat_bg",
        "chapter_auto_run",
        {"max_chapters": 1, "stop_at_volume_end": True},
    )
    await async_session.commit()

    from novel_dev.services.generation_job_service import run_generation_job

    await run_generation_job(job.id)

    refreshed = await repo.get_by_id(job.id)
    assert refreshed.heartbeat_at is not None
    assert refreshed.finished_at is not None
    assert refreshed.heartbeat_at <= refreshed.finished_at


@pytest.mark.asyncio
async def test_auto_run_stops_at_volume_end(async_session):
    plan = build_test_volume("vol_end", "ch_end")
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_auto_end",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={
            "current_volume_plan": plan.model_dump(),
            "current_chapter_plan": plan.chapters[0].model_dump(),
        },
        volume_id="vol_end",
        chapter_id="ch_end_1",
    )
    job = await GenerationJobRepository(async_session).create(
        "n_auto_end",
        "chapter_auto_run",
        {"max_chapters": 2, "stop_at_volume_end": True},
    )
    await async_session.commit()

    from novel_dev.services.generation_job_service import run_generation_job

    await run_generation_job(job.id)

    refreshed = await GenerationJobRepository(async_session).get_by_id(job.id)
    assert refreshed.status == "succeeded"
    assert refreshed.result_payload["completed_chapters"] == ["ch_end_1", "ch_end_2"]
    assert refreshed.result_payload["stopped_reason"] == "volume_completed"
    assert refreshed.result_payload["current_phase"] == Phase.VOLUME_PLANNING.value

    first = await ChapterRepository(async_session).get_by_id("ch_end_1")
    second = await ChapterRepository(async_session).get_by_id("ch_end_2")
    assert first.status == "archived"
    assert second.status == "archived"


@pytest.mark.asyncio
async def test_auto_run_rejects_when_generation_job_is_active(async_session, monkeypatch):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    monkeypatch.setattr("novel_dev.api.routes.schedule_generation_job", lambda job_id: None)
    transport = ASGITransport(app=app)
    try:
        plan = build_test_volume("vol_locked", "ch_locked")
        director = NovelDirector(session=async_session)
        await director.save_checkpoint(
            "n_auto_locked",
            phase=Phase.CONTEXT_PREPARATION,
            checkpoint_data={
                "current_volume_plan": plan.model_dump(),
                "current_chapter_plan": plan.chapters[0].model_dump(),
            },
            volume_id="vol_locked",
            chapter_id="ch_locked_1",
        )
        await GenerationJobRepository(async_session).create(
            "n_auto_locked",
            "chapter_auto_run",
            {"max_chapters": 1, "stop_at_volume_end": True},
        )
        await async_session.flush()

        async with AsyncClient(transport=transport, base_url="http://test", timeout=120) as client:
            response = await client.post("/api/novels/n_auto_locked/chapters/auto-run")

        assert response.status_code == 409
        assert "already running" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_auto_run_route_clears_stale_checkpoint_lock_when_no_active_job(async_session, monkeypatch):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    monkeypatch.setattr("novel_dev.api.routes.schedule_generation_job", lambda job_id: None)
    transport = ASGITransport(app=app)
    try:
        plan = build_test_volume("vol_stale_lock", "ch_stale_lock")
        director = NovelDirector(session=async_session)
        await director.save_checkpoint(
            "n_auto_stale_lock",
            phase=Phase.CONTEXT_PREPARATION,
            checkpoint_data={
                "current_volume_plan": plan.model_dump(),
                "current_chapter_plan": plan.chapters[0].model_dump(),
                "auto_run_lock": {
                    "active": True,
                    "token": "old-token",
                    "started_at": "2026-04-27T14:15:44Z",
                },
            },
            volume_id="vol_stale_lock",
            chapter_id="ch_stale_lock_1",
        )

        async with AsyncClient(transport=transport, base_url="http://test", timeout=120) as client:
            response = await client.post("/api/novels/n_auto_stale_lock/chapters/auto-run")

        assert response.status_code == 202
        state = await director.resume("n_auto_stale_lock")
        assert "auto_run_lock" not in state.checkpoint_data
        assert state.checkpoint_data["auto_run_last_result"] == {
            "stopped_reason": "failed",
            "recovered": True,
            "error": "Recovered stale auto_run_lock after process interruption",
        }
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_auto_run_job_stores_structured_failure_detail(async_session, monkeypatch):
    plan = build_test_volume("vol_fail", "ch_fail")
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_auto_fail",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={
            "current_volume_plan": plan.model_dump(),
            "current_chapter_plan": plan.chapters[0].model_dump(),
        },
        volume_id="vol_fail",
        chapter_id="ch_fail_1",
    )

    async def fail_assemble(self, novel_id, chapter_id):
        raise RuntimeError("context exploded")

    monkeypatch.setattr(ContextAgent, "assemble", fail_assemble)
    job = await GenerationJobRepository(async_session).create(
        "n_auto_fail",
        "chapter_auto_run",
        {"max_chapters": 1, "stop_at_volume_end": True},
    )
    await async_session.commit()

    from novel_dev.services.generation_job_service import run_generation_job

    await run_generation_job(job.id)

    refreshed = await GenerationJobRepository(async_session).get_by_id(job.id)
    assert refreshed.status == "failed"
    assert refreshed.result_payload["stopped_reason"] == "failed"
    assert refreshed.result_payload["failed_phase"] == Phase.CONTEXT_PREPARATION.value
    assert refreshed.result_payload["failed_chapter_id"] == "ch_fail_1"
    assert "context exploded" in refreshed.result_payload["error"]

    state = await director.resume("n_auto_fail")
    assert "auto_run_lock" not in state.checkpoint_data
    assert state.checkpoint_data["auto_run_last_result"]["stopped_reason"] == "failed"


@pytest.mark.asyncio
async def test_auto_run_returns_flow_cancelled_when_stopped_during_run(async_session, monkeypatch):
    original_assemble = ContextAgent.assemble
    plan = build_test_volume("vol_stop", "ch_stop")
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_auto_stop",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={
            "current_volume_plan": plan.model_dump(),
            "current_chapter_plan": plan.chapters[0].model_dump(),
        },
        volume_id="vol_stop",
        chapter_id="ch_stop_1",
    )

    async def stop_after_context(self, novel_id, chapter_id):
        context = await original_assemble(self, novel_id, chapter_id)
        await FlowControlService(self.session).request_stop(novel_id)
        return context

    monkeypatch.setattr(ContextAgent, "assemble", stop_after_context)
    job = await GenerationJobRepository(async_session).create(
        "n_auto_stop",
        "chapter_auto_run",
        {"max_chapters": 1, "stop_at_volume_end": True},
    )
    await async_session.commit()

    from novel_dev.services.generation_job_service import run_generation_job

    await run_generation_job(job.id)

    refreshed = await GenerationJobRepository(async_session).get_by_id(job.id)
    assert refreshed.status == "cancelled"
    assert refreshed.result_payload["stopped_reason"] == "flow_cancelled"
    assert refreshed.result_payload["completed_chapters"] == []
    assert refreshed.result_payload["current_phase"] == Phase.DRAFTING.value

    state = await director.resume("n_auto_stop")
    assert "auto_run_lock" not in state.checkpoint_data


@pytest.mark.asyncio
async def test_auto_run_continues_from_drafting_phase(async_session):
    plan = build_test_volume("vol_mid", "ch_mid")
    chapter_plan = ChapterPlan(
        chapter_number=1,
        title="Mid Draft",
        target_word_count=80,
        beats=[BeatPlan(summary="B1", target_mood="tense")],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="默认地点"),
        timeline_events=[],
        pending_foreshadowings=[],
    )
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_auto_mid",
        phase=Phase.DRAFTING,
        checkpoint_data={
            "current_volume_plan": plan.model_dump(),
            "current_chapter_plan": plan.chapters[0].model_dump(),
            "chapter_context": context.model_dump(),
            "drafting_progress": {"beat_index": 0, "total_beats": 1, "current_word_count": 0},
        },
        volume_id="vol_mid",
        chapter_id="ch_mid_1",
    )
    await ChapterRepository(async_session).ensure_from_plan("n_auto_mid", "vol_mid", plan.chapters[0])
    job = await GenerationJobRepository(async_session).create(
        "n_auto_mid",
        "chapter_auto_run",
        {"max_chapters": 1, "stop_at_volume_end": True},
    )
    await async_session.commit()

    from novel_dev.services.generation_job_service import run_generation_job

    await run_generation_job(job.id)

    refreshed = await GenerationJobRepository(async_session).get_by_id(job.id)
    assert refreshed.status == "succeeded"
    assert refreshed.result_payload["completed_chapters"] == ["ch_mid_1"]
    assert refreshed.result_payload["stopped_reason"] == "max_chapters_reached"
    assert refreshed.result_payload["current_phase"] == Phase.CONTEXT_PREPARATION.value
    assert refreshed.result_payload["current_chapter_id"] == "ch_mid_2"

    chapter = await ChapterRepository(async_session).get_by_id("ch_mid_1")
    assert chapter.status == "archived"
    assert chapter.raw_draft
    assert chapter.polished_text


def test_auto_run_uses_embedding_service_like_manual_routes(async_session, monkeypatch):
    class DummyEmbedder:
        pass

    monkeypatch.setattr("novel_dev.services.chapter_generation_service.llm_factory.get_embedder", lambda: DummyEmbedder())

    service = ChapterGenerationService(async_session)
    embedding_service = service._embedding_service()

    assert embedding_service is not None
    assert embedding_service.session is async_session
