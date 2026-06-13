"""Tests for /api/novels/{id}/quality/trends endpoint."""
from datetime import datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from novel_dev.api.routes import get_session, router
from novel_dev.db.models import Chapter, ChapterQualityMetric, NovelState


app = FastAPI()
app.include_router(router)


def _override_session(async_session):
    async def override():
        yield async_session
    return override


@pytest.mark.asyncio
async def test_quality_trends_returns_metric_point(async_session):
    """Happy path: novel + chapter + ChapterQualityMetric row -> endpoint reflects metric data."""
    novel_id = "test-novel-trends-metric"
    chapter_id = "ch-trends-1"
    volume_id = "vol-trends-1"

    async_session.add_all([
        NovelState(novel_id=novel_id, current_phase="completed", checkpoint_data={}),
        Chapter(
            id=chapter_id,
            volume_id=volume_id,
            chapter_number=1,
            title="第一章 试炼",
            novel_id=novel_id,
            score_overall=80,
        ),
    ])
    await async_session.flush()

    metric = ChapterQualityMetric(
        novel_id=novel_id,
        chapter_id=chapter_id,
        phase="final",
        attempt_index=0,
        overall_score=92,
        dimension_scores={"plot_tension": 88, "humanity": 90},
        gate_status="pass",
        issue_codes=["CONTINUITY_DRIFT", "STALE_TONE"],
    )
    async_session.add(metric)
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/novels/{novel_id}/quality/trends")
            assert resp.status_code == 200
            body = resp.json()
            assert body["novel_id"] == novel_id
            assert body["dimension"] == "overall"
            assert body["phase"] == "final"
            assert isinstance(body["points"], list)
            assert len(body["points"]) == 1
            point = body["points"][0]
            assert point["chapter_id"] == chapter_id
            assert point["chapter_number"] == 1
            assert point["title"] == "第一章 试炼"
            assert point["value"] == 92
            assert point["gate_status"] == "pass"
            assert point["issue_codes"] == ["CONTINUITY_DRIFT", "STALE_TONE"]
            assert point["source"] == "metrics"
            assert point["created_at"] is not None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_quality_trends_falls_back_to_chapter_score(async_session):
    """Fallback path: chapter with score_overall but no metric row -> source == chapter_fallback."""
    novel_id = "test-novel-trends-fallback"
    chapter_id = "ch-fallback-1"
    volume_id = "vol-fallback-1"

    async_session.add_all([
        NovelState(novel_id=novel_id, current_phase="completed", checkpoint_data={}),
        Chapter(
            id=chapter_id,
            volume_id=volume_id,
            chapter_number=1,
            title="第一章 跌落",
            novel_id=novel_id,
            score_overall=75,
            quality_status="warn",
            quality_reasons={"warning_items": ["STALE_TONE"]},
            quality_checked_at=datetime(2026, 5, 1, 10, 0, 0),
        ),
    ])
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/novels/{novel_id}/quality/trends")
            assert resp.status_code == 200
            body = resp.json()
            assert len(body["points"]) == 1
            point = body["points"][0]
            assert point["source"] == "chapter_fallback"
            assert point["value"] == 75
            assert point["gate_status"] == "warn"
            assert point["issue_codes"] == ["STALE_TONE"]
            assert point["chapter_id"] == chapter_id
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_quality_trends_query_params_echoed_and_filtered(async_session):
    """Query params (dimension/phase/from_chapter/to_chapter) echo in response and reach the service."""
    novel_id = "test-novel-trends-qparams"
    volume_id = "vol-qparams-1"

    # 6 chapters: 1..6. Ch 3 and 5 have a metric for `plot_tension` phase=final.
    # Ch 1, 2, 4, 6 have no metric; if dimension=overall, ch 1,2,4,6 fall back
    # (chapter 6 has no score_overall so it should NOT appear in overall trend).
    chapters = []
    for n in range(1, 7):
        chapters.append(Chapter(
            id=f"ch-qp-{n}",
            volume_id=volume_id,
            chapter_number=n,
            title=f"第{n}章",
            novel_id=novel_id,
            score_overall=70 + n,
        ))
    async_session.add(NovelState(novel_id=novel_id, current_phase="completed", checkpoint_data={}))
    async_session.add_all(chapters)
    await async_session.flush()

    # Only insert metric rows for chapters 3 and 5 with dimension_scores.
    async_session.add_all([
        ChapterQualityMetric(
            novel_id=novel_id,
            chapter_id="ch-qp-3",
            phase="final",
            overall_score=85,
            dimension_scores={"plot_tension": 91, "humanity": 80},
            gate_status="pass",
        ),
        ChapterQualityMetric(
            novel_id=novel_id,
            chapter_id="ch-qp-5",
            phase="final",
            overall_score=80,
            dimension_scores={"plot_tension": 78, "humanity": 82},
            gate_status="warn",
        ),
    ])
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # dimension=plot_tension, from_chapter=2, to_chapter=5
            resp = await client.get(
                f"/api/novels/{novel_id}/quality/trends",
                params={
                    "dimension": "plot_tension",
                    "phase": "final",
                    "from_chapter": 2,
                    "to_chapter": 5,
                },
            )
            assert resp.status_code == 200
            body = resp.json()
            # Echoed values
            assert body["novel_id"] == novel_id
            assert body["dimension"] == "plot_tension"
            assert body["phase"] == "final"

            # Filtered: chapters 2..5 range. Ch 3 and 5 have metric rows
            # with plot_tension dimension_score. Ch 2 and 4 have no metric
            # row and no score_breakdown[plot_tension], so they're excluded.
            chapter_numbers = [p["chapter_number"] for p in body["points"]]
            assert chapter_numbers == [3, 5]

            by_chapter = {p["chapter_number"]: p for p in body["points"]}
            assert by_chapter[3]["value"] == 91
            assert by_chapter[3]["source"] == "metrics"
            assert by_chapter[5]["value"] == 78
            assert by_chapter[5]["source"] == "metrics"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_quality_trends_empty_novel_returns_empty_points(async_session):
    """A novel with no chapters -> 200 with points: []."""
    novel_id = "test-novel-trends-empty"
    async_session.add(NovelState(novel_id=novel_id, current_phase="brainstorming", checkpoint_data={}))
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/novels/{novel_id}/quality/trends")
            assert resp.status_code == 200
            body = resp.json()
            assert body["novel_id"] == novel_id
            assert body["dimension"] == "overall"
            assert body["phase"] == "final"
            assert body["points"] == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_quality_trends_novel_without_state_returns_404(async_session):
    """A novel_id that has no NovelState row -> 404, matching the /state endpoint pattern."""
    novel_id = "test-novel-trends-missing"

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/novels/{novel_id}/quality/trends")
            # The /state endpoint returns 404 for unknown novel_id. To stay consistent,
            # the trends endpoint should also return 404 rather than 200 + empty list.
            assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()
