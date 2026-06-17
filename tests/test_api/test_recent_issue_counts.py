"""Tests for /api/novels/{id}/chapters/recent-issue-counts endpoint."""
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from novel_dev.api.routes import get_session, router
from novel_dev.db.models import NovelState
from novel_dev.services.quality_metrics_service import QualityMetricInput, QualityMetricsService


app = FastAPI()
app.include_router(router)


def _override_session(async_session):
    async def override():
        yield async_session
    return override


@pytest.mark.asyncio
async def test_recent_issue_counts_returns_recent_codes(async_session):
    """Happy path: records metrics then verifies endpoint returns aggregated counts."""
    novel_id = "test-novel-ric"
    async_session.add(NovelState(novel_id=novel_id, current_phase="drafting", checkpoint_data={}))
    await async_session.flush()

    svc = QualityMetricsService(async_session)
    for i, code in enumerate(["BEAT_BOUNDARY_VIOLATION", "BEAT_BOUNDARY_VIOLATION", "AI_FLAVOR_HIGH"]):
        await svc.record(QualityMetricInput(
            chapter_id=f"ch_{i}",
            novel_id=novel_id,
            phase="critic",
            attempt_index=1,
            overall_score=70,
            gate_status="warn",
            issue_codes=[code],
        ))
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/novels/{novel_id}/chapters/recent-issue-counts?window=5")
            assert resp.status_code == 200
            data = resp.json()
            assert data["novel_id"] == novel_id
            assert data["window"] == 5
            assert data["counts"]["BEAT_BOUNDARY_VIOLATION"] == 2
            assert data["counts"]["AI_FLAVOR_HIGH"] == 1
    finally:
        app.dependency_overrides.clear()
