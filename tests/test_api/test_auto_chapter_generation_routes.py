import asyncio
import pytest
from copy import deepcopy
from datetime import datetime, timedelta
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from novel_dev.agents.context_agent import ContextAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.api.routes import get_session, router
from novel_dev.db.models import Timeline
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.schemas.context import BeatPlan, ChapterContext, ChapterPlan, LocationContext
from novel_dev.schemas.outline import SynopsisData, VolumeBeat, VolumePlan
from novel_dev.services.flow_control_service import FlowControlService
from novel_dev.repositories.generation_job_repo import GenerationJobRepository
from novel_dev.services.chapter_generation_service import ChapterGenerationService
from novel_dev.services.chapter_generation_service import AutoRunChaptersResult, AutoRunFailedError
from novel_dev.services.generation_job_service import CHAPTER_REWRITE_JOB


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
        review_status={"status": "accepted", "reason": "test accepted"},
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
            review_status={"status": "accepted", "reason": "test accepted"},
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
async def test_rewrite_route_creates_independent_generation_job(async_session, monkeypatch):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    monkeypatch.setattr("novel_dev.api.routes.schedule_generation_job", lambda job_id: None)
    transport = ASGITransport(app=app)
    try:
        plan = build_test_volume("vol_rewrite_route", "ch_rewrite_route")
        director = NovelDirector(session=async_session)
        await director.save_checkpoint(
            "n_rewrite_route",
            phase=Phase.CONTEXT_PREPARATION,
            checkpoint_data={
                "current_volume_plan": plan.model_dump(),
                "current_chapter_plan": plan.chapters[1].model_dump(),
            },
            volume_id="vol_rewrite_route",
            chapter_id="ch_rewrite_route_2",
        )
        repo = ChapterRepository(async_session)
        await repo.ensure_from_plan("n_rewrite_route", "vol_rewrite_route", plan.chapters[0])
        await repo.update_text("ch_rewrite_route_1", polished_text="旧正文")
        await repo.update_status("ch_rewrite_route_1", "archived")

        async with AsyncClient(transport=transport, base_url="http://test", timeout=120) as client:
            response = await client.post("/api/novels/n_rewrite_route/chapters/ch_rewrite_route_1/rewrite")

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "queued"
        assert data["job_type"] == CHAPTER_REWRITE_JOB
        assert data["request_payload"] == {"chapter_id": "ch_rewrite_route_1"}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_rewrite_route_accepts_drafted_chapter_for_retry(async_session, monkeypatch):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    monkeypatch.setattr("novel_dev.api.routes.schedule_generation_job", lambda job_id: None)
    transport = ASGITransport(app=app)
    try:
        plan = build_test_volume("vol_rewrite_draft_route", "ch_rewrite_draft_route")
        director = NovelDirector(session=async_session)
        await director.save_checkpoint(
            "n_rewrite_draft_route",
            phase=Phase.CONTEXT_PREPARATION,
            checkpoint_data={
                "current_volume_plan": plan.model_dump(),
                "current_chapter_plan": plan.chapters[1].model_dump(),
            },
            volume_id="vol_rewrite_draft_route",
            chapter_id="ch_rewrite_draft_route_2",
        )
        repo = ChapterRepository(async_session)
        await repo.ensure_from_plan("n_rewrite_draft_route", "vol_rewrite_draft_route", plan.chapters[0])
        await repo.update_text("ch_rewrite_draft_route_1", raw_draft="失败前已生成的草稿")
        await repo.update_status("ch_rewrite_draft_route_1", "drafted")

        async with AsyncClient(transport=transport, base_url="http://test", timeout=120) as client:
            response = await client.post(
                "/api/novels/n_rewrite_draft_route/chapters/ch_rewrite_draft_route_1/rewrite"
            )

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "queued"
        assert data["job_type"] == CHAPTER_REWRITE_JOB
        assert data["request_payload"] == {"chapter_id": "ch_rewrite_draft_route_1"}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_rewrite_route_clears_stale_flow_stop_before_queueing(async_session, monkeypatch):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    monkeypatch.setattr("novel_dev.api.routes.schedule_generation_job", lambda job_id: None)
    transport = ASGITransport(app=app)
    try:
        plan = build_test_volume("vol_rewrite_stop", "ch_rewrite_stop")
        director = NovelDirector(session=async_session)
        await director.save_checkpoint(
            "n_rewrite_stop",
            phase=Phase.CONTEXT_PREPARATION,
            checkpoint_data={
                "current_volume_plan": plan.model_dump(),
                "current_chapter_plan": plan.chapters[1].model_dump(),
            },
            volume_id="vol_rewrite_stop",
            chapter_id="ch_rewrite_stop_2",
        )
        await FlowControlService(async_session).request_stop("n_rewrite_stop")
        repo = ChapterRepository(async_session)
        await repo.ensure_from_plan("n_rewrite_stop", "vol_rewrite_stop", plan.chapters[0])
        await repo.update_text("ch_rewrite_stop_1", polished_text="旧正文")
        await repo.update_status("ch_rewrite_stop_1", "archived")

        async with AsyncClient(transport=transport, base_url="http://test", timeout=120) as client:
            response = await client.post("/api/novels/n_rewrite_stop/chapters/ch_rewrite_stop_1/rewrite")

        assert response.status_code == 202
        state = await director.resume("n_rewrite_stop")
        assert "flow_control" not in state.checkpoint_data
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_rewrite_background_job_archives_without_touching_current_state(async_session):
    plan = build_test_volume("vol_rewrite_bg", "ch_rewrite_bg")
    director = NovelDirector(session=async_session)
    checkpoint = {
        "current_volume_plan": plan.model_dump(),
        "current_chapter_plan": plan.chapters[1].model_dump(),
        "custom_marker": {"keep": True},
    }
    await director.save_checkpoint(
        "n_rewrite_bg",
        phase=Phase.DRAFTING,
        checkpoint_data=deepcopy(checkpoint),
        volume_id="vol_rewrite_bg",
        chapter_id="ch_rewrite_bg_2",
    )
    repo = ChapterRepository(async_session)
    await repo.ensure_from_plan("n_rewrite_bg", "vol_rewrite_bg", plan.chapters[0])
    await repo.update_text(
        "ch_rewrite_bg_1",
        raw_draft="旧草稿",
        polished_text="旧正文",
    )
    await repo.update_status("ch_rewrite_bg_1", "archived")
    job = await GenerationJobRepository(async_session).create(
        "n_rewrite_bg",
        CHAPTER_REWRITE_JOB,
        {"chapter_id": "ch_rewrite_bg_1"},
    )
    await async_session.commit()

    from novel_dev.services.generation_job_service import run_generation_job

    await run_generation_job(job.id)

    refreshed = await GenerationJobRepository(async_session).get_by_id(job.id)
    assert refreshed.status == "succeeded"
    assert refreshed.result_payload["chapter_id"] == "ch_rewrite_bg_1"

    rewritten = await ChapterRepository(async_session).get_by_id("ch_rewrite_bg_1")
    assert rewritten.status == "archived"
    assert rewritten.raw_draft and rewritten.raw_draft != "旧草稿"
    assert rewritten.polished_text and rewritten.polished_text != "旧正文"
    assert rewritten.score_overall == 88
    assert rewritten.fast_review_feedback

    state = await director.resume("n_rewrite_bg")
    assert state.current_phase == Phase.DRAFTING.value
    assert state.current_volume_id == "vol_rewrite_bg"
    assert state.current_chapter_id == "ch_rewrite_bg_2"
    assert state.checkpoint_data == checkpoint


@pytest.mark.asyncio
async def test_rewrite_background_job_retries_drafted_chapter_after_failure(async_session):
    plan = build_test_volume("vol_rewrite_retry_bg", "ch_rewrite_retry_bg")
    director = NovelDirector(session=async_session)
    checkpoint = {
        "current_volume_plan": plan.model_dump(),
        "current_chapter_plan": plan.chapters[1].model_dump(),
    }
    await director.save_checkpoint(
        "n_rewrite_retry_bg",
        phase=Phase.DRAFTING,
        checkpoint_data=deepcopy(checkpoint),
        volume_id="vol_rewrite_retry_bg",
        chapter_id="ch_rewrite_retry_bg_2",
    )
    repo = ChapterRepository(async_session)
    await repo.ensure_from_plan("n_rewrite_retry_bg", "vol_rewrite_retry_bg", plan.chapters[0])
    await repo.update_text("ch_rewrite_retry_bg_1", raw_draft="失败前残留草稿")
    await repo.update_status("ch_rewrite_retry_bg_1", "drafted")
    job = await GenerationJobRepository(async_session).create(
        "n_rewrite_retry_bg",
        CHAPTER_REWRITE_JOB,
        {"chapter_id": "ch_rewrite_retry_bg_1"},
    )
    await async_session.commit()

    from novel_dev.services.generation_job_service import run_generation_job

    await run_generation_job(job.id)

    refreshed = await GenerationJobRepository(async_session).get_by_id(job.id)
    assert refreshed.status == "succeeded"
    rewritten = await ChapterRepository(async_session).get_by_id("ch_rewrite_retry_bg_1")
    assert rewritten.status == "archived"
    assert rewritten.raw_draft and rewritten.raw_draft != "失败前残留草稿"
    assert rewritten.polished_text


@pytest.mark.asyncio
async def test_rewrite_background_job_resumes_context_failure_without_existing_chapter(async_session):
    plan = build_test_volume("vol_rewrite_context_retry_bg", "ch_rewrite_context_retry_bg")
    director = NovelDirector(session=async_session)
    checkpoint = {
        "current_volume_plan": plan.model_dump(),
        "current_chapter_plan": plan.chapters[1].model_dump(),
    }
    await director.save_checkpoint(
        "n_rewrite_context_retry_bg",
        phase=Phase.DRAFTING,
        checkpoint_data=deepcopy(checkpoint),
        volume_id="vol_rewrite_context_retry_bg",
        chapter_id="ch_rewrite_context_retry_bg_2",
    )
    job = await GenerationJobRepository(async_session).create(
        "n_rewrite_context_retry_bg",
        CHAPTER_REWRITE_JOB,
        {
            "chapter_id": "ch_rewrite_context_retry_bg_1",
            "resume": True,
            "resume_from_stage": "context",
        },
    )
    await async_session.commit()

    from novel_dev.services.generation_job_service import run_generation_job

    await run_generation_job(job.id)

    refreshed = await GenerationJobRepository(async_session).get_by_id(job.id)
    assert refreshed.status == "succeeded"
    rewritten = await ChapterRepository(async_session).get_by_id("ch_rewrite_context_retry_bg_1")
    assert rewritten is not None
    assert rewritten.status == "archived"
    assert rewritten.raw_draft
    assert rewritten.polished_text


@pytest.mark.asyncio
async def test_rewrite_job_records_librarian_stage_failure_for_resume(async_session, monkeypatch):
    plan = build_test_volume("vol_rewrite_librarian_fail", "ch_rewrite_librarian_fail")
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_rewrite_librarian_fail",
        phase=Phase.DRAFTING,
        checkpoint_data={
            "current_volume_plan": plan.model_dump(),
            "current_chapter_plan": plan.chapters[1].model_dump(),
        },
        volume_id="vol_rewrite_librarian_fail",
        chapter_id="ch_rewrite_librarian_fail_2",
    )
    repo = ChapterRepository(async_session)
    await repo.ensure_from_plan("n_rewrite_librarian_fail", "vol_rewrite_librarian_fail", plan.chapters[0])
    await repo.update_text("ch_rewrite_librarian_fail_1", polished_text="旧正文")
    await repo.update_status("ch_rewrite_librarian_fail_1", "archived")

    async def fail_extract(self, novel_id, chapter_id, polished_text):
        raise RuntimeError("librarian exploded")

    monkeypatch.setattr("novel_dev.services.chapter_rewrite_service.LibrarianAgent.extract", fail_extract)
    job = await GenerationJobRepository(async_session).create(
        "n_rewrite_librarian_fail",
        CHAPTER_REWRITE_JOB,
        {"chapter_id": "ch_rewrite_librarian_fail_1"},
    )
    await async_session.commit()

    from novel_dev.services.generation_job_service import run_generation_job

    await run_generation_job(job.id)

    refreshed = await GenerationJobRepository(async_session).get_by_id(job.id)
    assert refreshed.status == "failed"
    assert refreshed.error_message == "librarian exploded"
    assert refreshed.result_payload["chapter_id"] == "ch_rewrite_librarian_fail_1"
    assert refreshed.result_payload["failed_stage"] == "librarian_archive"
    assert refreshed.result_payload["resume_from_stage"] == "librarian_archive"
    assert refreshed.result_payload["can_resume"] is True


@pytest.mark.asyncio
async def test_rewrite_job_records_failed_after_librarian_flush_error(async_session, monkeypatch):
    plan = build_test_volume("vol_rewrite_flush_fail", "ch_rewrite_flush_fail")
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_rewrite_flush_fail",
        phase=Phase.DRAFTING,
        checkpoint_data={
            "current_volume_plan": plan.model_dump(),
            "current_chapter_plan": plan.chapters[1].model_dump(),
        },
        volume_id="vol_rewrite_flush_fail",
        chapter_id="ch_rewrite_flush_fail_2",
    )
    repo = ChapterRepository(async_session)
    await repo.ensure_from_plan("n_rewrite_flush_fail", "vol_rewrite_flush_fail", plan.chapters[0])
    await repo.update_text("ch_rewrite_flush_fail_1", polished_text="旧正文")
    await repo.update_status("ch_rewrite_flush_fail_1", "archived")
    async_session.add(Timeline(
        novel_id="n_rewrite_flush_fail",
        tick=0,
        narrative="已有时间线",
        anchor_chapter_id="ch_rewrite_flush_fail_1",
    ))
    await async_session.flush()

    async def fail_persist(self, extraction, chapter_id, novel_id):
        self.session.add(Timeline(
            novel_id=novel_id,
            tick=0,
            narrative="重复时间线",
            anchor_chapter_id=chapter_id,
        ))
        await self.session.flush()

    monkeypatch.setattr("novel_dev.services.chapter_rewrite_service.LibrarianAgent.persist", fail_persist)
    job = await GenerationJobRepository(async_session).create(
        "n_rewrite_flush_fail",
        CHAPTER_REWRITE_JOB,
        {"chapter_id": "ch_rewrite_flush_fail_1"},
    )
    await async_session.commit()

    from novel_dev.services.generation_job_service import run_generation_job

    await run_generation_job(job.id)

    refreshed = await GenerationJobRepository(async_session).get_by_id(job.id)
    assert refreshed.status == "failed"
    assert "UNIQUE constraint failed" in refreshed.error_message
    assert refreshed.result_payload["failed_stage"] == "librarian_archive"
    assert refreshed.result_payload["can_resume"] is True


@pytest.mark.asyncio
async def test_rewrite_route_creates_resume_job_from_failed_stage(async_session, monkeypatch):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    monkeypatch.setattr("novel_dev.api.routes.schedule_generation_job", lambda job_id: None)
    transport = ASGITransport(app=app)
    try:
        plan = build_test_volume("vol_rewrite_resume_route", "ch_rewrite_resume_route")
        director = NovelDirector(session=async_session)
        await director.save_checkpoint(
            "n_rewrite_resume_route",
            phase=Phase.CONTEXT_PREPARATION,
            checkpoint_data={
                "current_volume_plan": plan.model_dump(),
                "current_chapter_plan": plan.chapters[1].model_dump(),
            },
            volume_id="vol_rewrite_resume_route",
            chapter_id="ch_rewrite_resume_route_2",
        )
        repo = ChapterRepository(async_session)
        await repo.ensure_from_plan("n_rewrite_resume_route", "vol_rewrite_resume_route", plan.chapters[0])
        await repo.update_text(
            "ch_rewrite_resume_route_1",
            raw_draft="已有草稿",
            polished_text="已有精修正文",
        )
        await repo.update_scores("ch_rewrite_resume_route_1", 88, {"readability": {"score": 88}}, {"summary": "ok"})
        await repo.update_fast_review("ch_rewrite_resume_route_1", 92, {"notes": []})
        await repo.update_status("ch_rewrite_resume_route_1", "edited")
        failed_job = await GenerationJobRepository(async_session).create(
            "n_rewrite_resume_route",
            CHAPTER_REWRITE_JOB,
            {"chapter_id": "ch_rewrite_resume_route_1"},
        )
        await GenerationJobRepository(async_session).mark_failed(
            failed_job.id,
            {
                "chapter_id": "ch_rewrite_resume_route_1",
                "failed_stage": "librarian_archive",
                "resume_from_stage": "librarian_archive",
                "can_resume": True,
                "rewrite_checkpoint": {"chapter_context": plan.chapters[0].model_dump()},
            },
            "librarian exploded",
        )

        async with AsyncClient(transport=transport, base_url="http://test", timeout=120) as client:
            response = await client.post(
                "/api/novels/n_rewrite_resume_route/chapters/ch_rewrite_resume_route_1/rewrite",
                json={"resume": True, "failed_job_id": failed_job.id},
            )

        assert response.status_code == 202
        data = response.json()
        assert data["request_payload"]["chapter_id"] == "ch_rewrite_resume_route_1"
        assert data["request_payload"]["resume"] is True
        assert data["request_payload"]["failed_job_id"] == failed_job.id
        assert data["request_payload"]["resume_from_stage"] == "librarian_archive"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_rewrite_route_resumes_first_step_failure_without_existing_chapter(async_session, monkeypatch):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    monkeypatch.setattr("novel_dev.api.routes.schedule_generation_job", lambda job_id: None)
    transport = ASGITransport(app=app)
    try:
        plan = build_test_volume("vol_rewrite_context_resume", "ch_rewrite_context_resume")
        director = NovelDirector(session=async_session)
        await director.save_checkpoint(
            "n_rewrite_context_resume",
            phase=Phase.CONTEXT_PREPARATION,
            checkpoint_data={
                "current_volume_plan": plan.model_dump(),
                "current_chapter_plan": plan.chapters[0].model_dump(),
            },
            volume_id="vol_rewrite_context_resume",
            chapter_id="ch_rewrite_context_resume_1",
        )
        failed_job = await GenerationJobRepository(async_session).create(
            "n_rewrite_context_resume",
            CHAPTER_REWRITE_JOB,
            {"chapter_id": "ch_rewrite_context_resume_1"},
        )
        await GenerationJobRepository(async_session).mark_failed(
            failed_job.id,
            {
                "chapter_id": "ch_rewrite_context_resume_1",
                "failed_stage": "context",
                "resume_from_stage": "context",
                "can_resume": True,
                "rewrite_checkpoint": {},
            },
            "context exploded",
        )
        await async_session.commit()

        async with AsyncClient(transport=transport, base_url="http://test", timeout=120) as client:
            response = await client.post(
                "/api/novels/n_rewrite_context_resume/chapters/ch_rewrite_context_resume_1/rewrite",
                json={"resume": True, "failed_job_id": failed_job.id},
            )

        assert response.status_code == 202
        data = response.json()
        assert data["request_payload"]["chapter_id"] == "ch_rewrite_context_resume_1"
        assert data["request_payload"]["resume"] is True
        assert data["request_payload"]["failed_job_id"] == failed_job.id
        assert data["request_payload"]["resume_from_stage"] == "context"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_rewrite_route_inferrs_librarian_resume_for_legacy_failed_job(async_session, monkeypatch):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    monkeypatch.setattr("novel_dev.api.routes.schedule_generation_job", lambda job_id: None)
    transport = ASGITransport(app=app)
    try:
        plan = build_test_volume("vol_rewrite_legacy_resume", "ch_rewrite_legacy_resume")
        director = NovelDirector(session=async_session)
        await director.save_checkpoint(
            "n_rewrite_legacy_resume",
            phase=Phase.CONTEXT_PREPARATION,
            checkpoint_data={
                "current_volume_plan": plan.model_dump(),
                "current_chapter_plan": plan.chapters[1].model_dump(),
            },
            volume_id="vol_rewrite_legacy_resume",
            chapter_id="ch_rewrite_legacy_resume_2",
        )
        repo = ChapterRepository(async_session)
        await repo.ensure_from_plan("n_rewrite_legacy_resume", "vol_rewrite_legacy_resume", plan.chapters[0])
        await repo.update_text(
            "ch_rewrite_legacy_resume_1",
            raw_draft="已有草稿",
            polished_text="已有精修正文",
        )
        await repo.update_scores("ch_rewrite_legacy_resume_1", 88, {"readability": {"score": 88}}, {"summary": "ok"})
        await repo.update_fast_review("ch_rewrite_legacy_resume_1", 92, {"notes": []})
        await repo.update_status("ch_rewrite_legacy_resume_1", "edited")
        failed_job = await GenerationJobRepository(async_session).create(
            "n_rewrite_legacy_resume",
            CHAPTER_REWRITE_JOB,
            {"chapter_id": "ch_rewrite_legacy_resume_1"},
        )
        await GenerationJobRepository(async_session).mark_failed(failed_job.id, {}, "legacy failure")

        async with AsyncClient(transport=transport, base_url="http://test", timeout=120) as client:
            response = await client.post(
                "/api/novels/n_rewrite_legacy_resume/chapters/ch_rewrite_legacy_resume_1/rewrite",
                json={"resume": True, "failed_job_id": failed_job.id},
            )

        assert response.status_code == 202
        data = response.json()
        assert data["request_payload"]["resume"] is True
        assert data["request_payload"]["resume_from_stage"] == "librarian_archive"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_chapter_rewrite_jobs_returns_latest_job_per_chapter(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        director = NovelDirector(session=async_session)
        plan = build_test_volume("vol_rewrite_jobs", "ch_rewrite_jobs")
        await director.save_checkpoint(
            "n_rewrite_jobs",
            phase=Phase.CONTEXT_PREPARATION,
            checkpoint_data={
                "current_volume_plan": plan.model_dump(),
                "current_chapter_plan": plan.chapters[0].model_dump(),
            },
            volume_id="vol_rewrite_jobs",
            chapter_id="ch_rewrite_jobs_1",
        )
        repo = GenerationJobRepository(async_session)
        older_job = await repo.create(
            "n_rewrite_jobs",
            CHAPTER_REWRITE_JOB,
            {"chapter_id": "ch_rewrite_jobs_1"},
            job_id="job_rewrite_older",
        )
        await repo.mark_failed(older_job.id, {"chapter_id": "ch_rewrite_jobs_1"}, "old failure")
        latest_job = await repo.create(
            "n_rewrite_jobs",
            CHAPTER_REWRITE_JOB,
            {"chapter_id": "ch_rewrite_jobs_1"},
            job_id="job_rewrite_latest",
        )
        await repo.mark_failed(
            latest_job.id,
            {
                "chapter_id": "ch_rewrite_jobs_1",
                "resume_from_stage": "librarian_archive",
                "can_resume": True,
            },
            "new failure",
        )
        other_chapter_job = await repo.create(
            "n_rewrite_jobs",
            CHAPTER_REWRITE_JOB,
            {"chapter_id": "ch_rewrite_jobs_2"},
            job_id="job_rewrite_other_chapter",
        )
        await repo.mark_succeeded(other_chapter_job.id, {"chapter_id": "ch_rewrite_jobs_2"})
        other_novel_job = await repo.create(
            "n_other_rewrite_jobs",
            CHAPTER_REWRITE_JOB,
            {"chapter_id": "ch_rewrite_jobs_1"},
            job_id="job_rewrite_other_novel",
        )
        await repo.mark_failed(other_novel_job.id, {"chapter_id": "ch_rewrite_jobs_1"}, "wrong novel")
        await async_session.commit()

        async with AsyncClient(transport=transport, base_url="http://test", timeout=120) as client:
            response = await client.get("/api/novels/n_rewrite_jobs/chapters/rewrite_jobs")

        assert response.status_code == 200
        data = response.json()
        jobs_by_chapter = {item["chapter_id"]: item["job"] for item in data["items"]}
        assert set(jobs_by_chapter) == {"ch_rewrite_jobs_1", "ch_rewrite_jobs_2"}
        assert jobs_by_chapter["ch_rewrite_jobs_1"]["job_id"] == "job_rewrite_latest"
        assert jobs_by_chapter["ch_rewrite_jobs_1"]["status"] == "failed"
        assert jobs_by_chapter["ch_rewrite_jobs_1"]["result_payload"]["resume_from_stage"] == "librarian_archive"
        assert jobs_by_chapter["ch_rewrite_jobs_2"]["job_id"] == "job_rewrite_other_chapter"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_rewrite_resume_from_librarian_skips_completed_generation_stages(async_session, monkeypatch):
    plan = build_test_volume("vol_rewrite_resume_bg", "ch_rewrite_resume_bg")
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_rewrite_resume_bg",
        phase=Phase.DRAFTING,
        checkpoint_data={
            "current_volume_plan": plan.model_dump(),
            "current_chapter_plan": plan.chapters[1].model_dump(),
        },
        volume_id="vol_rewrite_resume_bg",
        chapter_id="ch_rewrite_resume_bg_2",
    )
    repo = ChapterRepository(async_session)
    await repo.ensure_from_plan("n_rewrite_resume_bg", "vol_rewrite_resume_bg", plan.chapters[0])
    await repo.update_text("ch_rewrite_resume_bg_1", raw_draft="保留草稿", polished_text="保留精修正文")
    await repo.update_scores("ch_rewrite_resume_bg_1", 87, {"readability": {"score": 87}}, {"summary": "ok"})
    await repo.update_fast_review("ch_rewrite_resume_bg_1", 91, {"notes": []})
    await repo.update_status("ch_rewrite_resume_bg_1", "edited")

    async def unexpected_call(*args, **kwargs):
        raise AssertionError("completed rewrite stage should be skipped")

    monkeypatch.setattr("novel_dev.services.chapter_rewrite_service.ContextAgent.assemble_for_chapter", unexpected_call)
    monkeypatch.setattr("novel_dev.services.chapter_rewrite_service.WriterAgent.write_standalone", unexpected_call)
    monkeypatch.setattr("novel_dev.services.chapter_rewrite_service.CriticAgent.review_standalone", unexpected_call)
    monkeypatch.setattr("novel_dev.services.chapter_rewrite_service.EditorAgent.polish_standalone", unexpected_call)
    monkeypatch.setattr("novel_dev.services.chapter_rewrite_service.FastReviewAgent.review_standalone", unexpected_call)

    job = await GenerationJobRepository(async_session).create(
        "n_rewrite_resume_bg",
        CHAPTER_REWRITE_JOB,
        {
            "chapter_id": "ch_rewrite_resume_bg_1",
            "resume": True,
            "resume_from_stage": "librarian_archive",
        },
    )
    await async_session.commit()

    from novel_dev.services.generation_job_service import run_generation_job

    await run_generation_job(job.id)

    refreshed = await GenerationJobRepository(async_session).get_by_id(job.id)
    assert refreshed.status == "succeeded"
    rewritten = await ChapterRepository(async_session).get_by_id("ch_rewrite_resume_bg_1")
    assert rewritten.raw_draft == "保留草稿"
    assert rewritten.polished_text == "保留精修正文"
    assert rewritten.status == "archived"


@pytest.mark.asyncio
async def test_rewrite_resume_from_librarian_skips_persist_when_chapter_artifacts_exist(async_session, monkeypatch):
    plan = build_test_volume("vol_rewrite_resume_artifacts", "ch_rewrite_resume_artifacts")
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_rewrite_resume_artifacts",
        phase=Phase.DRAFTING,
        checkpoint_data={
            "current_volume_plan": plan.model_dump(),
            "current_chapter_plan": plan.chapters[1].model_dump(),
        },
        volume_id="vol_rewrite_resume_artifacts",
        chapter_id="ch_rewrite_resume_artifacts_2",
    )
    repo = ChapterRepository(async_session)
    await repo.ensure_from_plan("n_rewrite_resume_artifacts", "vol_rewrite_resume_artifacts", plan.chapters[0])
    await repo.update_text("ch_rewrite_resume_artifacts_1", raw_draft="保留草稿", polished_text="保留精修正文")
    await repo.update_scores("ch_rewrite_resume_artifacts_1", 87, {"readability": {"score": 87}}, {"summary": "ok"})
    await repo.update_fast_review("ch_rewrite_resume_artifacts_1", 91, {"notes": []})
    await repo.update_status("ch_rewrite_resume_artifacts_1", "edited")
    async_session.add(Timeline(
        novel_id="n_rewrite_resume_artifacts",
        tick=101,
        narrative="已经持久化的章节事件",
        anchor_chapter_id="ch_rewrite_resume_artifacts_1",
    ))
    await async_session.flush()

    async def unexpected_librarian_call(*args, **kwargs):
        raise AssertionError("existing chapter artifacts should prevent duplicate librarian persistence")

    monkeypatch.setattr("novel_dev.services.chapter_rewrite_service.LibrarianAgent.extract", unexpected_librarian_call)
    job = await GenerationJobRepository(async_session).create(
        "n_rewrite_resume_artifacts",
        CHAPTER_REWRITE_JOB,
        {
            "chapter_id": "ch_rewrite_resume_artifacts_1",
            "resume": True,
            "resume_from_stage": "librarian_archive",
        },
    )
    await async_session.commit()

    from novel_dev.services.generation_job_service import run_generation_job

    await run_generation_job(job.id)

    refreshed = await GenerationJobRepository(async_session).get_by_id(job.id)
    assert refreshed.status == "succeeded"
    rewritten = await ChapterRepository(async_session).get_by_id("ch_rewrite_resume_artifacts_1")
    assert rewritten.status == "archived"


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
async def test_auto_run_syncs_mismatched_current_chapter_plan(async_session):
    plan = build_test_volume("vol_sync_plan", "ch_sync_plan")
    director = NovelDirector(session=async_session)
    stale_context = ChapterContext(
        chapter_plan=ChapterPlan(
            chapter_number=1,
            title="Stale First Chapter",
            target_word_count=80,
            beats=[BeatPlan(summary="stale", target_mood="tense")],
        ),
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="旧地点"),
        timeline_events=[],
        pending_foreshadowings=[],
    )
    state = await director.save_checkpoint(
        "n_auto_sync_plan",
        phase=Phase.DRAFTING,
        checkpoint_data={
            "current_volume_plan": plan.model_dump(),
            "current_chapter_plan": plan.chapters[0].model_dump(),
            "chapter_context": stale_context.model_dump(),
            "drafting_progress": {"beat_index": 2},
            "relay_history": [{"scene_state": "旧接力"}],
            "draft_metadata": {"total_words": 1200},
        },
        volume_id="vol_sync_plan",
        chapter_id="ch_sync_plan_2",
    )

    service = ChapterGenerationService(async_session)
    synced = await service._sync_current_chapter_checkpoint(state)

    checkpoint = synced.checkpoint_data
    assert synced.current_phase == Phase.CONTEXT_PREPARATION.value
    assert synced.current_chapter_id == "ch_sync_plan_2"
    assert checkpoint["current_chapter_plan"]["chapter_id"] == "ch_sync_plan_2"
    assert checkpoint["current_chapter_plan"]["title"] == "Chapter 2"
    assert "chapter_context" not in checkpoint
    assert "drafting_progress" not in checkpoint
    assert "relay_history" not in checkpoint
    assert "draft_metadata" not in checkpoint


@pytest.mark.asyncio
async def test_generation_job_refreshes_heartbeat_while_work_is_running(async_session, monkeypatch):
    repo = GenerationJobRepository(async_session)
    job = await repo.create(
        "n_auto_periodic_heartbeat",
        "chapter_auto_run",
        {"max_chapters": 1, "stop_at_volume_end": True},
    )
    await async_session.commit()

    heartbeat_started = False
    heartbeat_cancelled = False

    async def tracked_heartbeat(job_id, novel_id):
        nonlocal heartbeat_started, heartbeat_cancelled
        heartbeat_started = True
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            heartbeat_cancelled = True
            raise

    async def slow_auto_run(self, novel_id, *, max_chapters=1, stop_at_volume_end=True):
        await asyncio.sleep(0.03)
        return AutoRunChaptersResult(
            novel_id=novel_id,
            current_phase=Phase.DRAFTING.value,
            completed_chapters=[],
            stopped_reason="max_chapters_reached",
        )

    monkeypatch.setattr("novel_dev.services.generation_job_service._heartbeat_active_job", tracked_heartbeat)
    monkeypatch.setattr("novel_dev.services.generation_job_service._supports_periodic_heartbeat", lambda session: True)
    monkeypatch.setattr(ChapterGenerationService, "auto_run", slow_auto_run)

    from novel_dev.services.generation_job_service import run_generation_job

    await run_generation_job(job.id)

    refreshed = await repo.get_by_id(job.id)
    assert refreshed.status == "succeeded"
    assert heartbeat_started is True
    assert heartbeat_cancelled is True


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
async def test_auto_run_stops_when_volume_plan_not_accepted(async_session):
    plan = build_test_volume("vol_not_ready", "ch_not_ready", count=1)
    plan_payload = plan.model_dump()
    plan_payload["review_status"] = {
        "status": "needs_manual_review",
        "reason": "卷纲存在未达标维度",
    }
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_auto_not_ready",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={
            "current_volume_plan": plan_payload,
            "current_chapter_plan": plan.chapters[0].model_dump(),
        },
        volume_id="vol_not_ready",
        chapter_id="ch_not_ready_1",
    )

    service = ChapterGenerationService(async_session)
    result = await service.auto_run("n_auto_not_ready", max_chapters=1)

    assert result.stopped_reason == "volume_plan_not_ready"
    assert result.error is not None
    assert "needs_manual_review" in result.error


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
async def test_auto_run_route_recovers_inactive_generation_job_before_start(async_session, monkeypatch):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    monkeypatch.setattr("novel_dev.api.routes.schedule_generation_job", lambda job_id: None)
    transport = ASGITransport(app=app)
    try:
        plan = build_test_volume("vol_inactive_job", "ch_inactive_job")
        director = NovelDirector(session=async_session)
        await director.save_checkpoint(
            "n_auto_inactive_job",
            phase=Phase.CONTEXT_PREPARATION,
            checkpoint_data={
                "current_volume_plan": plan.model_dump(),
                "current_chapter_plan": plan.chapters[0].model_dump(),
                "auto_run_lock": {
                    "active": True,
                    "token": "inactive-token",
                    "started_at": "2026-04-28T11:54:45Z",
                },
            },
            volume_id="vol_inactive_job",
            chapter_id="ch_inactive_job_1",
        )
        repo = GenerationJobRepository(async_session)
        stale_job = await repo.create(
            "n_auto_inactive_job",
            "chapter_auto_run",
            {"max_chapters": 1, "stop_at_volume_end": True},
        )
        await repo.mark_running(stale_job.id)
        old = datetime.utcnow() - timedelta(minutes=10)
        stale_job.heartbeat_at = old
        stale_job.updated_at = old
        await async_session.commit()

        async with AsyncClient(transport=transport, base_url="http://test", timeout=120) as client:
            response = await client.post("/api/novels/n_auto_inactive_job/chapters/auto-run")

        assert response.status_code == 202
        refreshed_stale_job = await repo.get_by_id(stale_job.id)
        assert refreshed_stale_job.status == "failed"

        state = await director.resume("n_auto_inactive_job")
        assert "auto_run_lock" not in state.checkpoint_data

        response_data = response.json()
        assert response_data["job_type"] == "chapter_auto_run"
        assert response_data["status"] == "queued"
        assert response_data["job_id"] != stale_job.id
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
async def test_auto_run_persists_writer_guard_failure_diagnostics(async_session, monkeypatch):
    plan = build_test_volume("vol_guard_fail", "ch_guard_fail")
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_auto_guard_fail",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={
            "current_volume_plan": plan.model_dump(),
            "current_chapter_plan": plan.chapters[0].model_dump(),
        },
        volume_id="vol_guard_fail",
        chapter_id="ch_guard_fail_1",
    )
    await async_session.commit()

    evidence = {
        "mode": "writer_retry",
        "beat_index": 2,
        "passed": False,
        "issues": ["提前写到后续节拍"],
    }

    async def fail_run(self, novel_id):
        error = RuntimeError("Writer beat structure guard failed")
        setattr(error, "chapter_structure_guard", evidence)
        setattr(error, "writer_guard_failures", [evidence])
        setattr(error, "failed_phase", Phase.DRAFTING.value)
        raise error

    monkeypatch.setattr(ChapterGenerationService, "_run_current_chapter", fail_run)

    service = ChapterGenerationService(async_session)
    with pytest.raises(AutoRunFailedError) as exc_info:
        await service.auto_run("n_auto_guard_fail", max_chapters=1)

    assert exc_info.value.result.failed_phase == Phase.DRAFTING.value
    state = await director.resume("n_auto_guard_fail")
    assert "auto_run_lock" not in state.checkpoint_data
    assert state.checkpoint_data["chapter_structure_guard"] == evidence
    assert state.checkpoint_data["writer_guard_failures"] == [evidence]
    assert state.checkpoint_data["auto_run_last_result"]["failed_phase"] == Phase.DRAFTING.value


@pytest.mark.asyncio
async def test_auto_run_job_releases_lock_after_flush_error(async_session, monkeypatch):
    plan = build_test_volume("vol_flush_fail", "ch_flush_fail")
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_auto_flush_fail",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={
            "current_volume_plan": plan.model_dump(),
            "current_chapter_plan": plan.chapters[0].model_dump(),
        },
        volume_id="vol_flush_fail",
        chapter_id="ch_flush_fail_1",
    )
    async_session.add(Timeline(
        novel_id="n_auto_flush_fail",
        tick=0,
        narrative="已有时间线",
        anchor_chapter_id="ch_flush_fail_1",
    ))
    await async_session.flush()

    async def fail_assemble(self, novel_id, chapter_id):
        self.session.add(Timeline(
            novel_id=novel_id,
            tick=0,
            narrative="重复时间线",
            anchor_chapter_id=chapter_id,
        ))
        await self.session.flush()

    monkeypatch.setattr(ContextAgent, "assemble", fail_assemble)
    job = await GenerationJobRepository(async_session).create(
        "n_auto_flush_fail",
        "chapter_auto_run",
        {"max_chapters": 1, "stop_at_volume_end": True},
    )
    await async_session.commit()

    from novel_dev.services.generation_job_service import run_generation_job

    await run_generation_job(job.id)

    refreshed = await GenerationJobRepository(async_session).get_by_id(job.id)
    assert refreshed.status == "failed"
    assert refreshed.result_payload["stopped_reason"] == "failed"
    assert "UNIQUE constraint failed" in refreshed.result_payload["error"]

    state = await director.resume("n_auto_flush_fail")
    assert "auto_run_lock" not in state.checkpoint_data
    assert state.checkpoint_data["auto_run_last_result"]["stopped_reason"] == "failed"


@pytest.mark.asyncio
async def test_auto_run_commits_completed_chapter_before_later_failure(async_session, monkeypatch):
    plan = build_test_volume("vol_commit_done", "ch_commit_done")
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_auto_commit_done",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={
            "current_volume_plan": plan.model_dump(),
            "current_chapter_plan": plan.chapters[0].model_dump(),
        },
        volume_id="vol_commit_done",
        chapter_id="ch_commit_done_1",
    )
    await async_session.commit()

    calls = 0

    async def fake_run_current_chapter(self, novel_id):
        nonlocal calls
        calls += 1
        if calls == 1:
            self.session.add(Timeline(
                novel_id=novel_id,
                tick=1,
                narrative="第一章已归档的时间线",
                anchor_chapter_id="ch_commit_done_1",
            ))
            await self.session.flush()
            return "ch_commit_done_1"
        raise RuntimeError("second chapter failed")

    monkeypatch.setattr(ChapterGenerationService, "_run_current_chapter", fake_run_current_chapter)
    service = ChapterGenerationService(async_session)

    with pytest.raises(AutoRunFailedError):
        await service.auto_run("n_auto_commit_done", max_chapters=2)

    result = await async_session.execute(
        select(Timeline).where(Timeline.novel_id == "n_auto_commit_done")
    )
    timelines = result.scalars().all()
    assert [timeline.narrative for timeline in timelines] == ["第一章已归档的时间线"]


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
