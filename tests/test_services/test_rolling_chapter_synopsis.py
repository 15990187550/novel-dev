import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from novel_dev.services.rolling_chapter_synopsis_service import RollingChapterSynopsisService


@pytest.mark.asyncio
async def test_should_update_on_quality_block(async_session):
    svc = RollingChapterSynopsisService(async_session)
    assert await svc.should_update("n_1", "ch_5", "quality_block", {"gate_status": "block"}) is True


@pytest.mark.asyncio
async def test_should_update_on_quality_block_when_gate_status_not_block(async_session):
    """quality_block event with gate_status != 'block' must NOT trigger an update."""
    svc = RollingChapterSynopsisService(async_session)
    assert await svc.should_update(
        "n_1", "ch_5", "quality_block", {"gate_status": "warn"}
    ) is False
    assert await svc.should_update(
        "n_1", "ch_5", "quality_block", {"gate_status": "pass"}
    ) is False


@pytest.mark.asyncio
async def test_should_update_on_entity_state_dramatic(async_session):
    svc = RollingChapterSynopsisService(async_session)
    assert await svc.should_update("n_1", "ch_5", "entity_state_change", {"is_important": True}) is True


@pytest.mark.asyncio
async def test_should_update_false_for_minor_change(async_session):
    svc = RollingChapterSynopsisService(async_session)
    assert await svc.should_update("n_1", "ch_5", "entity_state_change", {"is_important": False}) is False


@pytest.mark.asyncio
async def test_should_update_on_entity_introduced_returns_true(async_session):
    """entity_introduced must always trigger an update regardless of payload."""
    svc = RollingChapterSynopsisService(async_session)
    assert await svc.should_update("n_1", "ch_5", "entity_introduced", {}) is True
    assert await svc.should_update(
        "n_1", "ch_5", "entity_introduced", {"name": "主角"}
    ) is True


@pytest.mark.asyncio
async def test_should_update_on_entity_removed_returns_true(async_session):
    """entity_removed must always trigger an update regardless of payload."""
    svc = RollingChapterSynopsisService(async_session)
    assert await svc.should_update("n_1", "ch_5", "entity_removed", {}) is True
    assert await svc.should_update(
        "n_1", "ch_5", "entity_removed", {"name": "配角"}
    ) is True


@pytest.mark.asyncio
async def test_should_update_returns_false_for_unknown_event_type(async_session):
    """Unknown event types must NOT trigger an update (default branch)."""
    svc = RollingChapterSynopsisService(async_session)
    assert await svc.should_update(
        "n_1", "ch_5", "chapter_finished", {"anything": 1}
    ) is False
    assert await svc.should_update(
        "n_1", "ch_5", "some_random_event", {}
    ) is False


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
async def test_update_falls_back_to_hardcoded_template_on_prompt_runtime_error(async_session):
    """When PromptRegistry.get_active raises RuntimeError, update must fall back
    to the hardcoded template and still produce a valid snapshot."""
    from novel_dev.db.models import NovelState, Chapter
    from novel_dev.services.prompt_registry import PromptRegistry

    # Create a chapter row so update can build the chapter summary line
    async_session.add(Chapter(
        id="ch_5", novel_id="n_1", volume_id="vol_1",
        chapter_number=5, title="第五章",
    ))
    async_session.add(NovelState(novel_id="n_1", current_phase="drafting", checkpoint_data={}))
    await async_session.flush()

    fake_response = MagicMock()
    fake_response.text = '{"narrative_prose": "fallback path", "structured_json": {"plot_points": []}}'
    fake_response.usage = None
    fake_client = AsyncMock()
    fake_client.acomplete = AsyncMock(return_value=fake_response)

    async def boom(*a, **kw):
        raise RuntimeError("prompt registry unavailable")

    with patch(
        "novel_dev.services.rolling_chapter_synopsis_service.llm_factory"
    ) as mf:
        mf.get.return_value = fake_client
        with patch.object(PromptRegistry, "get_active", new=boom):
            svc = RollingChapterSynopsisService(async_session)
            syn = await svc.update("n_1", "ch_5", trigger_event={"type": "block"})

    assert syn.narrative_prose == "fallback path"
    assert syn.novel_id == "n_1"
    assert syn.chapter_range_start == 1  # no prev synopsis → starts at 1
    assert syn.chapter_range_end == 5     # parsed from "ch_5"


@pytest.mark.asyncio
async def test_update_uses_existing_template_when_registry_returns_empty(async_session):
    """When PromptRegistry returns an empty template, update must keep using
    it as-is (not crash). The LLM still gets called with the empty template
    but the snapshot is still persisted."""
    from novel_dev.db.models import NovelState, Chapter
    from novel_dev.services.prompt_registry import PromptRegistry

    async_session.add(Chapter(
        id="ch_5", novel_id="n_1", volume_id="vol_1",
        chapter_number=5, title="第五章",
    ))
    async_session.add(NovelState(novel_id="n_1", current_phase="drafting", checkpoint_data={}))
    await async_session.flush()

    fake_response = MagicMock()
    fake_response.text = '{"narrative_prose": "empty tmpl path", "structured_json": {}}'
    fake_response.usage = None
    fake_client = AsyncMock()
    fake_client.acomplete = AsyncMock(return_value=fake_response)

    async def empty_template(*a, **kw):
        return ""

    with patch(
        "novel_dev.services.rolling_chapter_synopsis_service.llm_factory"
    ) as mf:
        mf.get.return_value = fake_client
        with patch.object(PromptRegistry, "get_active", new=empty_template):
            svc = RollingChapterSynopsisService(async_session)
            syn = await svc.update("n_1", "ch_5", trigger_event={"type": "block"})

    assert syn.narrative_prose == "empty tmpl path"
    # When the registry returns "" the service falls back to the hardcoded
    # template (line 43), so the LLM is called with a populated prompt, not
    # an empty body.
    call_args = fake_client.acomplete.call_args
    sent_messages = call_args.args[0]
    sent_prompt = sent_messages[0].content
    assert "(无前情摘要)" in sent_prompt  # prev_synopsis substitution
    assert "ch_5: 第五章" in sent_prompt    # new_chapter_summaries substitution
    assert '"type": "block"' in sent_prompt  # trigger_event substitution


@pytest.mark.asyncio
async def test_get_latest_returns_most_recent(async_session):
    from novel_dev.repositories.chapter_synopsis_repo import ChapterSynopsisRepository
    svc = RollingChapterSynopsisService(async_session)
    repo = ChapterSynopsisRepository(async_session)
    await repo.create("n_1", 1, 5, "first", {}, {})
    await repo.create("n_1", 6, 10, "second", {}, {})
    latest = await svc.get_latest("n_1")
    assert latest.chapter_range_end == 10


@pytest.mark.asyncio
async def test_cache_to_checkpoint_no_op_when_no_novel_state(async_session):
    """cache_to_checkpoint must silently no-op when NovelState row is missing
    (line 79: if not ns: return)."""
    from novel_dev.repositories.chapter_synopsis_repo import ChapterSynopsisRepository

    repo = ChapterSynopsisRepository(async_session)
    syn = await repo.create(
        "n_orphan", 1, 1, "no checkpoint", {}, {"type": "block"},
    )
    svc = RollingChapterSynopsisService(async_session)
    # Must not raise even though there's no NovelState for n_orphan
    await svc.cache_to_checkpoint("n_orphan", syn)
