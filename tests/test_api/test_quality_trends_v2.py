"""Tests for /api/novels/{id}/quality-trends-v2 endpoint."""
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from novel_dev.api.routes import get_session, router
from novel_dev.db.models import (
    Chapter,
    ChapterQualityMetric,
    ImageryInventory,
    NovelState,
    ThrillPoint,
)
from novel_dev.services.quality_metrics_service import QualityMetricsService


app = FastAPI()
app.include_router(router)


def _override_session(async_session):
    async def override():
        yield async_session
    return override


async def _seed_novel(async_session, novel_id: str = "test-novel-qtv2") -> None:
    """Insert the NovelState row the v2 endpoint requires for 200 OK."""
    async_session.add(
        NovelState(
            novel_id=novel_id,
            current_phase="completed",
            checkpoint_data={},
        )
    )
    chapters = [
        Chapter(
            id=f"{novel_id}-ch-1",
            novel_id=novel_id,
            volume_id=f"{novel_id}-v1",
            chapter_number=1,
            title="道经初现",
            status="polished",
        ),
        Chapter(
            id=f"{novel_id}-ch-2",
            novel_id=novel_id,
            volume_id=f"{novel_id}-v1",
            chapter_number=2,
            title="风波再起",
            status="polished",
        ),
    ]
    async_session.add_all(chapters)
    await async_session.flush()


@pytest.mark.asyncio
async def test_quality_trends_v2_returns_thrills_imagery_hook_aggregate(async_session):
    """Happy path: seeded thrills/imagery/hook rows -> endpoint returns aggregated data."""
    novel_id = "test-novel-qtv2-happy"
    await _seed_novel(async_session, novel_id)

    # Seed thrills: 3 planned, 2 verified -> achievement_rate = 2/3.
    thrills = [
        ThrillPoint(
            novel_id=novel_id,
            chapter_id=f"{novel_id}-ch-1",
            beat_idx=0,
            thrill_type="breakthrough",
            intensity="high",
            planner_predicted=True,
            fast_review_verified=True,
        ),
        ThrillPoint(
            novel_id=novel_id,
            chapter_id=f"{novel_id}-ch-1",
            beat_idx=1,
            thrill_type="face_slap",
            intensity="mid",
            planner_predicted=True,
            fast_review_verified=True,
        ),
        ThrillPoint(
            novel_id=novel_id,
            chapter_id=f"{novel_id}-ch-2",
            beat_idx=0,
            thrill_type="reveal",
            intensity="high",
            planner_predicted=True,
            fast_review_verified=False,
        ),
        # An unplanned (extracted-only) thrill should NOT count toward achievement.
        ThrillPoint(
            novel_id=novel_id,
            chapter_id=f"{novel_id}-ch-2",
            beat_idx=1,
            thrill_type="climax",
            intensity="high",
            planner_predicted=False,
            fast_review_verified=False,
        ),
    ]
    async_session.add_all(thrills)

    # Seed imagery across two chapters. "寒月" appears in both -> top by chapter_count*freq_sum.
    imagery = [
        ImageryInventory(
            novel_id=novel_id,
            chapter_id=f"{novel_id}-ch-1",
            item="寒月",
            item_type="自然",
            frequency_in_chapter=3,
        ),
        ImageryInventory(
            novel_id=novel_id,
            chapter_id=f"{novel_id}-ch-2",
            item="寒月",
            item_type="自然",
            frequency_in_chapter=5,
        ),
        ImageryInventory(
            novel_id=novel_id,
            chapter_id=f"{novel_id}-ch-2",
            item="长剑出鞘",
            item_type="动作",
            frequency_in_chapter=1,
        ),
    ]
    async_session.add_all(imagery)

    # Seed a metric row with a hook_strength dimension score so the hook trend has data.
    metric = ChapterQualityMetric(
        chapter_id=f"{novel_id}-ch-1",
        novel_id=novel_id,
        phase="final",
        attempt_index=0,
        overall_score=88,
        dimension_scores={"hook_strength": 90, "overall": 88},
        gate_status="pass",
    )
    async_session.add(metric)
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/novels/{novel_id}/quality-trends-v2",
                params={"window": 5},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()

            assert data["novel_id"] == novel_id
            assert data["window"] == 5
            assert isinstance(data["trends"], list)

            # Thrill aggregation: 3 planned, 2 verified -> 2/3.
            assert data["thrills_planned"] == 3
            assert data["thrills_verified"] == 2
            assert data["thrills_achievement_rate"] == pytest.approx(2 / 3)

            # Imagery top 5: 寒月 first (2 chapters * 8 freq), then 长剑出鞘 (1 * 1).
            top5 = data["imagery_repeat_top5"]
            assert len(top5) == 2
            assert top5[0]["item"] == "寒月"
            assert top5[0]["type"] == "自然"
            assert top5[0]["chapter_count"] == 2
            assert top5[0]["freq_sum"] == 8
            assert top5[1]["item"] == "长剑出鞘"
            assert top5[1]["chapter_count"] == 1

            # Hook achievement trend should have one entry (ch-1 has hook_strength=90).
            assert isinstance(data["hook_achievement_trend"], list)
            assert len(data["hook_achievement_trend"]) == 1
            assert data["hook_achievement_trend"][0]["chapter_number"] == 1
            assert data["hook_achievement_trend"][0]["value"] == 90
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_quality_trends_v2_empty_novel_returns_zero_rates_and_null_hook(async_session):
    """Empty case: novel exists but no thrills/imagery/metrics -> rates are zero, hook=None."""
    novel_id = "test-novel-qtv2-empty"
    await _seed_novel(async_session, novel_id)
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/novels/{novel_id}/quality-trends-v2",
                params={"window": 5},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["thrills_planned"] == 0
            assert data["thrills_verified"] == 0
            assert data["thrills_achievement_rate"] == 0.0
            assert data["imagery_repeat_top5"] == []
            # No hook_strength metric rows => None stub per design.
            assert data["hook_achievement_trend"] is None
            assert data["trends"] == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_quality_trends_v2_404_when_novel_missing(async_session):
    """Missing novel state -> 404."""
    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/does-not-exist/quality-trends-v2")
            assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_quality_trends_v2_imagery_top5_capped_at_five(async_session):
    """Top 5 must be capped at 5 even when more imagery items exist."""
    novel_id = "test-novel-qtv2-cap"
    await _seed_novel(async_session, novel_id)

    imagery = [
        ImageryInventory(
            novel_id=novel_id,
            chapter_id=f"{novel_id}-ch-1",
            item=f"意象-{i}",
            item_type="misc",
            frequency_in_chapter=i + 1,
        )
        for i in range(8)
    ]
    async_session.add_all(imagery)
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/novels/{novel_id}/quality-trends-v2",
                params={"window": 5},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert len(data["imagery_repeat_top5"]) == 5
            # Sort key is chapter_count * freq_sum; with chapter_count=1 for all,
            # items should be ordered by freq_sum desc.
            freq_sums = [item["freq_sum"] for item in data["imagery_repeat_top5"]]
            assert freq_sums == sorted(freq_sums, reverse=True)
    finally:
        app.dependency_overrides.clear()