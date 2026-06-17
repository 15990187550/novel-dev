import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from novel_dev.services.rolling_chapter_synopsis_service import RollingChapterSynopsisService


@pytest.mark.asyncio
async def test_should_update_on_quality_block(async_session):
    svc = RollingChapterSynopsisService(async_session)
    assert await svc.should_update("n_1", "ch_5", "quality_block", {"gate_status": "block"}) is True


@pytest.mark.asyncio
async def test_should_update_on_entity_state_dramatic(async_session):
    svc = RollingChapterSynopsisService(async_session)
    assert await svc.should_update("n_1", "ch_5", "entity_state_change", {"is_important": True}) is True


@pytest.mark.asyncio
async def test_should_update_false_for_minor_change(async_session):
    svc = RollingChapterSynopsisService(async_session)
    assert await svc.should_update("n_1", "ch_5", "entity_state_change", {"is_important": False}) is False


@pytest.mark.asyncio
async def test_update_writes_new_snapshot_and_caches(async_session):
    from novel_dev.repositories.chapter_synopsis_repo import ChapterSynopsisRepository
    from novel_dev.db.models import NovelState
    from novel_dev.services.prompt_registry import PromptRegistry

    # Bootstrap the rolling_synopsis prompt so get_active succeeds
    reg = PromptRegistry(async_session)
    await reg.bootstrap_defaults()

    ns = NovelState(novel_id="n_1", current_phase="drafting", checkpoint_data={})
    async_session.add(ns)
    await async_session.flush()

    fake_response = MagicMock()
    fake_response.text = '{"narrative_prose": "陆照进入灵谷...", "structured_json": {"plot_points": []}}'
    fake_response.usage = None
    fake_client = AsyncMock()
    fake_client.acomplete = AsyncMock(return_value=fake_response)
    with patch("novel_dev.services.rolling_chapter_synopsis_service.llm_factory") as mf:
        mf.get.return_value = fake_client
        svc = RollingChapterSynopsisService(async_session)
        syn = await svc.update("n_1", "ch_5", trigger_event={"type": "block"})

    assert syn.narrative_prose.startswith("陆照")
    assert syn.novel_id == "n_1"
    await async_session.refresh(ns)
    assert "rolling_synopsis_cache" in ns.checkpoint_data


@pytest.mark.asyncio
async def test_get_latest_returns_most_recent(async_session):
    from novel_dev.repositories.chapter_synopsis_repo import ChapterSynopsisRepository
    svc = RollingChapterSynopsisService(async_session)
    repo = ChapterSynopsisRepository(async_session)
    await repo.create("n_1", 1, 5, "first", {}, {})
    await repo.create("n_1", 6, 10, "second", {}, {})
    latest = await svc.get_latest("n_1")
    assert latest.chapter_range_end == 10
