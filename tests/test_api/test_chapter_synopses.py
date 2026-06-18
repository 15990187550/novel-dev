"""Tests for /api/novels/{id}/chapter-synopses endpoint."""
from datetime import datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from novel_dev.api.routes import get_session, router
from novel_dev.db.models import ChapterSynopsis


app = FastAPI()
app.include_router(router)


def _override_session(async_session):
    async def override():
        yield async_session
    return override


@pytest.mark.asyncio
async def test_list_chapter_synopses_returns_records(async_session):
    """Happy path: two ChapterSynopsis rows -> endpoint returns them in order."""
    novel_id = "test-novel-rcs"
    s1 = ChapterSynopsis(
        novel_id=novel_id,
        chapter_range_start=1,
        chapter_range_end=5,
        narrative_prose="卷一故事概要",
        structured_json={"themes": ["成长"], "conflicts": ["正邪冲突"]},
        trigger_event={"chapter": 5, "summary": "突破境界"},
        analyzer_version="v1.0",
        created_at=datetime(2026, 6, 17, 10, 0, 0),
    )
    s2 = ChapterSynopsis(
        novel_id=novel_id,
        chapter_range_start=6,
        chapter_range_end=10,
        narrative_prose="卷二故事概要",
        structured_json={"themes": ["复仇"], "conflicts": ["师门恩怨"]},
        trigger_event={"chapter": 10, "summary": "身份暴露"},
        prev_synopsis_id=s1.id,
        analyzer_version="v1.0",
        created_at=datetime(2026, 6, 17, 12, 0, 0),
    )
    async_session.add_all([s1, s2])
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/novels/{novel_id}/chapter-synopses")
            assert resp.status_code == 200
            data = resp.json()
            assert data["novel_id"] == novel_id
            assert len(data["synopses"]) == 2

            first = data["synopses"][0]
            assert first["chapter_range"] == [1, 5]
            assert first["narrative_prose"] == "卷一故事概要"
            assert first["structured_json"] == {"themes": ["成长"], "conflicts": ["正邪冲突"]}
            assert first["trigger_event"] == {"chapter": 5, "summary": "突破境界"}
            assert first["created_at"] == "2026-06-17T10:00:00"

            second = data["synopses"][1]
            assert second["chapter_range"] == [6, 10]
            assert second["created_at"] == "2026-06-17T12:00:00"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_chapter_synopses_returns_empty_when_none(async_session):
    """Empty case: no ChapterSynopsis rows -> endpoint returns empty list."""
    novel_id = "test-novel-rcs-empty"

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/novels/{novel_id}/chapter-synopses")
            assert resp.status_code == 200
            data = resp.json()
            assert data["novel_id"] == novel_id
            assert data["synopses"] == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_chapter_synopses_scoped_to_novel(async_session):
    """Records for other novels must not leak into results."""
    novel_a = "test-novel-rcs-a"
    novel_b = "test-novel-rcs-b"
    async_session.add_all([
        ChapterSynopsis(
            novel_id=novel_a,
            chapter_range_start=1,
            chapter_range_end=3,
            narrative_prose="A 的概要",
            structured_json={},
            trigger_event={},
        ),
        ChapterSynopsis(
            novel_id=novel_b,
            chapter_range_start=1,
            chapter_range_end=3,
            narrative_prose="B 的概要",
            structured_json={},
            trigger_event={},
        ),
    ])
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/novels/{novel_a}/chapter-synopses")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["synopses"]) == 1
            assert data["synopses"][0]["narrative_prose"] == "A 的概要"
    finally:
        app.dependency_overrides.clear()