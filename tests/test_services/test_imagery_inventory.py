from __future__ import annotations
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_extract_and_store_writes_rows(async_session):
    fake_response = MagicMock()
    fake_response.text = json.dumps([
        {"item": "碎石硌掌心", "item_type": "physical_imagery", "frequency_in_chapter": 3},
        {"item": "像石子投入枯井", "item_type": "metaphor", "frequency_in_chapter": 1},
    ])
    fake_response.usage = None
    fake_client = AsyncMock()
    fake_client.acomplete = AsyncMock(return_value=fake_response)

    with patch("novel_dev.services.imagery_inventory_service.llm_factory") as mf:
        mf.get.return_value = fake_client
        from novel_dev.services.imagery_inventory_service import ImageryInventoryService
        svc = ImageryInventoryService(async_session)
        count = await svc.extract_and_store(
            "n_1", "ch_1", "陆照听见碎石硌掌心。"
        )

    assert count == 2
    from novel_dev.repositories.imagery_inventory_repo import ImageryInventoryRepository
    repo = ImageryInventoryRepository(async_session)
    items = await repo.get_recent("n_1", limit=10)
    assert any(i.item == "碎石硌掌心" for i in items)
    assert any(i.item == "像石子投入枯井" for i in items)


@pytest.mark.asyncio
async def test_extract_and_store_returns_zero_on_llm_error(async_session):
    fake_client = AsyncMock()
    fake_client.acomplete = AsyncMock(side_effect=RuntimeError("boom"))

    with patch("novel_dev.services.imagery_inventory_service.llm_factory") as mf:
        mf.get.return_value = fake_client
        from novel_dev.services.imagery_inventory_service import ImageryInventoryService
        svc = ImageryInventoryService(async_session)
        count = await svc.extract_and_store(
            "n_1", "ch_1", "陆照听见碎石硌掌心。"
        )
    assert count == 0


@pytest.mark.asyncio
async def test_extract_and_store_returns_zero_on_invalid_json(async_session):
    fake_response = MagicMock()
    fake_response.text = "this is not JSON"
    fake_response.usage = None
    fake_client = AsyncMock()
    fake_client.acomplete = AsyncMock(return_value=fake_response)

    with patch("novel_dev.services.imagery_inventory_service.llm_factory") as mf:
        mf.get.return_value = fake_client
        from novel_dev.services.imagery_inventory_service import ImageryInventoryService
        svc = ImageryInventoryService(async_session)
        count = await svc.extract_and_store(
            "n_1", "ch_1", "陆照听见碎石硌掌心。"
        )
    assert count == 0


@pytest.mark.asyncio
async def test_extract_and_store_strips_markdown_fence(async_session):
    fake_response = MagicMock()
    fake_response.text = "```json\n" + json.dumps([
        {"item": "碎石硌掌心", "item_type": "physical_imagery", "frequency_in_chapter": 2},
    ]) + "\n```"
    fake_response.usage = None
    fake_client = AsyncMock()
    fake_client.acomplete = AsyncMock(return_value=fake_response)

    with patch("novel_dev.services.imagery_inventory_service.llm_factory") as mf:
        mf.get.return_value = fake_client
        from novel_dev.services.imagery_inventory_service import ImageryInventoryService
        svc = ImageryInventoryService(async_session)
        count = await svc.extract_and_store(
            "n_1", "ch_1", "陆照听见碎石硌掌心。"
        )
    assert count == 1


@pytest.mark.asyncio
async def test_get_recent_delegates_to_repo(async_session):
    from novel_dev.repositories.imagery_inventory_repo import ImageryInventoryRepository
    repo = ImageryInventoryRepository(async_session)
    await repo.create("n_1", "ch_1", "碎石硌掌心", "physical_imagery", 1)
    await repo.create("n_1", "ch_2", "碎石硌掌心", "physical_imagery", 1)

    from novel_dev.services.imagery_inventory_service import ImageryInventoryService
    svc = ImageryInventoryService(async_session)
    items = await svc.get_recent("n_1", window=10)
    assert len(items) == 2
    assert all(i.item == "碎石硌掌心" for i in items)


@pytest.mark.asyncio
async def test_build_avoidance_list_returns_formatted_text(async_session):
    from novel_dev.services.imagery_inventory_service import ImageryInventoryService
    from novel_dev.repositories.imagery_inventory_repo import ImageryInventoryRepository
    repo = ImageryInventoryRepository(async_session)
    for ch in range(1, 6):
        for _ in range(ch):
            await repo.create("n_1", f"ch_{ch}", "碎石硌掌心", "physical_imagery", 1)
    svc = ImageryInventoryService(async_session)
    text = await svc.build_avoidance_list("n_1", "ch_6", window=5)
    assert "碎石硌掌心" in text
    assert "本章应避免" in text or "避免意象" in text


@pytest.mark.asyncio
async def test_build_avoidance_list_excludes_current_chapter(async_session):
    from novel_dev.services.imagery_inventory_service import ImageryInventoryService
    from novel_dev.repositories.imagery_inventory_repo import ImageryInventoryRepository
    repo = ImageryInventoryRepository(async_session)
    await repo.create("n_1", "ch_now", "本章专用意象", "metaphor", 5)
    await repo.create("n_1", "ch_prev", "过往意象", "physical_imagery", 3)
    svc = ImageryInventoryService(async_session)
    text = await svc.build_avoidance_list("n_1", "ch_now", window=5)
    assert "本章专用意象" not in text
    assert "过往意象" in text


@pytest.mark.asyncio
async def test_build_avoidance_list_empty_when_no_recent(async_session):
    from novel_dev.services.imagery_inventory_service import ImageryInventoryService
    svc = ImageryInventoryService(async_session)
    text = await svc.build_avoidance_list("n_empty", "ch_1", window=5)
    assert text == ""


@pytest.mark.asyncio
async def test_build_avoidance_list_aggregates_by_item_and_type(async_session):
    from novel_dev.services.imagery_inventory_service import ImageryInventoryService
    from novel_dev.repositories.imagery_inventory_repo import ImageryInventoryRepository
    repo = ImageryInventoryRepository(async_session)
    # ch_x is current → excluded
    await repo.create("n_1", "ch_x", "碎石硌掌心", "physical_imagery", 1)
    # ch_prev has 碎石硌掌心 (high count) and 像石子 (low count)
    await repo.create("n_1", "ch_prev", "碎石硌掌心", "physical_imagery", 5)
    await repo.create("n_1", "ch_prev2", "碎石硌掌心", "physical_imagery", 4)
    await repo.create("n_1", "ch_prev3", "像石子", "metaphor", 1)

    svc = ImageryInventoryService(async_session)
    text = await svc.build_avoidance_list("n_1", "ch_x", window=5)
    assert text != ""
    # higher-scoring item appears before lower-scoring
    idx_sui = text.find("碎石硌掌心")
    idx_shi = text.find("像石子")
    assert idx_sui != -1
    assert idx_shi != -1
    assert idx_sui < idx_shi