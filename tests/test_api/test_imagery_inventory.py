"""Tests for /api/novels/{id}/imagery-inventory endpoint."""
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from novel_dev.api.routes import get_session, router
from novel_dev.db.models import ImageryInventory


app = FastAPI()
app.include_router(router)


def _override_session(async_session):
    async def override():
        yield async_session
    return override


@pytest.mark.asyncio
async def test_imagery_inventory_returns_rows(async_session):
    """Happy path: rows from multiple chapters -> endpoint returns them."""
    novel_id = "test-novel-imagery"
    rows = [
        ImageryInventory(
            novel_id=novel_id,
            chapter_id="ch-1",
            item="寒月",
            item_type="自然",
            frequency_in_chapter=3,
        ),
        ImageryInventory(
            novel_id=novel_id,
            chapter_id="ch-2",
            item="寒月",
            item_type="自然",
            frequency_in_chapter=5,
        ),
        ImageryInventory(
            novel_id=novel_id,
            chapter_id="ch-2",
            item="长剑出鞘",
            item_type="动作",
            frequency_in_chapter=1,
        ),
    ]
    async_session.add_all(rows)
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/novels/{novel_id}/imagery-inventory",
                params={"window": 5},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["novel_id"] == novel_id
            assert data["window"] == 5
            assert len(data["items"]) == 3

            items = {i["item"]: i for i in data["items"]}
            assert items["寒月"]["item_type"] == "自然"
            assert items["寒月"]["chapter_id"] in {"ch-1", "ch-2"}
            assert items["寒月"]["frequency_in_chapter"] in {3, 5}
            assert items["长剑出鞘"]["item_type"] == "动作"
            assert items["长剑出鞘"]["chapter_id"] == "ch-2"
            assert items["长剑出鞘"]["frequency_in_chapter"] == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_imagery_inventory_returns_empty_when_none(async_session):
    """Empty case: no rows -> endpoint returns empty list."""
    novel_id = "test-novel-imagery-empty"

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/novels/{novel_id}/imagery-inventory",
                params={"window": 5},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["novel_id"] == novel_id
            assert data["window"] == 5
            assert data["items"] == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_imagery_inventory_scoped_to_novel(async_session):
    """Records for other novels must not leak into results."""
    novel_a = "test-novel-imagery-a"
    novel_b = "test-novel-imagery-b"
    async_session.add_all([
        ImageryInventory(
            novel_id=novel_a,
            chapter_id="ch-1",
            item="A 的意象",
            item_type="自然",
            frequency_in_chapter=1,
        ),
        ImageryInventory(
            novel_id=novel_b,
            chapter_id="ch-1",
            item="B 的意象",
            item_type="自然",
            frequency_in_chapter=1,
        ),
    ])
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/novels/{novel_a}/imagery-inventory",
                params={"window": 5},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["items"]) == 1
            assert data["items"][0]["item"] == "A 的意象"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_imagery_inventory_default_window(async_session):
    """Default window parameter (5) is honored when not supplied."""
    novel_id = "test-novel-imagery-default"
    async_session.add(
        ImageryInventory(
            novel_id=novel_id,
            chapter_id="ch-1",
            item="默认窗口",
            item_type="自然",
            frequency_in_chapter=1,
        )
    )
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/novels/{novel_id}/imagery-inventory")
            assert resp.status_code == 200
            data = resp.json()
            assert data["window"] == 5
            assert len(data["items"]) == 1
            assert data["items"][0]["item"] == "默认窗口"
    finally:
        app.dependency_overrides.clear()