"""Tests for /api/chapters/{chapter_id}/critic-breakdown endpoint.

The endpoint returns the latest attempt's per-dimension score breakdown from
ChapterQualityMetric rows, used by the QualityRecommendationWidget to expand a
"查看评分明细" panel.
"""
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
async def test_critic_breakdown_returns_latest_attempt_dimensions(async_session):
    """Multiple metric rows -> endpoint returns the latest attempt_index row's
    overall_score, dimensions, and dimension_feedback."""
    novel_id = "test-novel-critic-bd-latest"
    chapter_id = "ch-critic-bd-1"
    volume_id = "vol-critic-bd-1"

    async_session.add_all([
        NovelState(novel_id=novel_id, current_phase="completed", checkpoint_data={}),
        Chapter(
            id=chapter_id,
            volume_id=volume_id,
            chapter_number=1,
            title="第一章",
            novel_id=novel_id,
        ),
    ])
    await async_session.flush()

    async_session.add_all([
        ChapterQualityMetric(
            novel_id=novel_id,
            chapter_id=chapter_id,
            phase="final",
            attempt_index=0,
            overall_score=72,
            dimension_scores={"plot_tension": 70, "humanity": 75, "hook_strength": 71},
            dimension_feedback={"plot_tension": "张力不够"},
            gate_status="warn",
        ),
        ChapterQualityMetric(
            novel_id=novel_id,
            chapter_id=chapter_id,
            phase="final",
            attempt_index=1,
            overall_score=85,
            dimension_scores={"plot_tension": 88, "humanity": 82, "hook_strength": 84},
            dimension_feedback={
                "plot_tension": "张力提升",
                "humanity": "人物鲜活",
                "hook_strength": "钩子到位",
            },
            gate_status="pass",
        ),
    ])
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/chapters/{chapter_id}/critic-breakdown")
            assert resp.status_code == 200
            body = resp.json()
            assert body["chapter_id"] == chapter_id
            assert body["attempt_index"] == 1
            assert body["overall_score"] == 85
            assert body["dimensions"] == {
                "plot_tension": 88,
                "humanity": 82,
                "hook_strength": 84,
            }
            assert body["dimension_feedback"] == {
                "plot_tension": "张力提升",
                "humanity": "人物鲜活",
                "hook_strength": "钩子到位",
            }
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_critic_breakdown_unknown_chapter_returns_empty_dimensions(async_session):
    """A chapter_id with no metric rows -> 200 with empty dimensions dict and
    overall_score=None. Matches the plan's intent: callers can distinguish
    'no data yet' from 'has data' via attempt_index."""
    chapter_id = "ch-no-metrics-yet"

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/chapters/{chapter_id}/critic-breakdown")
            assert resp.status_code == 200
            body = resp.json()
            assert body["chapter_id"] == chapter_id
            assert body["overall_score"] is None
            assert body["dimensions"] == {}
            assert body["dimension_feedback"] == {}
            assert body["attempt_index"] is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_critic_breakdown_handles_null_dimension_scores(async_session):
    """Metric row with null dimension_scores / dimension_feedback -> empty dicts
    in the response (frontend relies on object iteration)."""
    novel_id = "test-novel-critic-bd-nulls"
    chapter_id = "ch-critic-bd-nulls"
    volume_id = "vol-critic-bd-nulls"

    async_session.add_all([
        NovelState(novel_id=novel_id, current_phase="completed", checkpoint_data={}),
        Chapter(
            id=chapter_id,
            volume_id=volume_id,
            chapter_number=1,
            title="第一章 null",
            novel_id=novel_id,
        ),
    ])
    await async_session.flush()

    async_session.add(ChapterQualityMetric(
        novel_id=novel_id,
        chapter_id=chapter_id,
        phase="final",
        attempt_index=0,
        overall_score=80,
        dimension_scores=None,
        dimension_feedback=None,
        gate_status="pass",
    ))
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/chapters/{chapter_id}/critic-breakdown")
            assert resp.status_code == 200
            body = resp.json()
            assert body["overall_score"] == 80
            assert body["attempt_index"] == 0
            assert body["dimensions"] == {}
            assert body["dimension_feedback"] == {}
    finally:
        app.dependency_overrides.clear()