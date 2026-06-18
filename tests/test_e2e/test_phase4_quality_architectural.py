"""Phase 4 E2E: quality architectural full flow.

Exercises the full Phase 4 pipeline:
  1. Bootstrap defaults + register Phase 4 prompts
  2. LibrarianAgent.on_chapter_finalized (block gate) -> RCS update
  3. rolling_synopsis_cache written to NovelState.checkpoint_data
  4. ContextAgent._narrative_source_from_checkpoint prefers the cache
  5. ImageryInventoryService.extract_and_store + build_avoidance_list
  6. A/B routing: stable per chapter + distributed across chapters

Notes:
  * Uses neutral names ("主角A", "碎石硌掌心" etc.) to avoid colliding
    with the template-safety test fixtures (which forbid "陆照" exact
    fragments inside generated text).
  * Patches the per-service `llm_factory` symbols directly because
    each service reads `llm_factory` from its own module scope at
    call time.
  * Uses ``async_session.commit()`` between major steps so subsequent
    reads via the same session see persisted rows. The ``async_session``
    fixture rolls back at teardown, so commit is safe here.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_phase4_full_pipeline_e2e(async_session):
    """E2E: quality block -> RCS update -> cross-chapter continuity ->
    imagery extraction -> avoidance list."""
    from novel_dev.db.models import Chapter, Entity, EntityVersion, NovelState
    from novel_dev.services.rolling_chapter_synopsis_service import (
        RollingChapterSynopsisService,
    )
    from novel_dev.services.imagery_inventory_service import ImageryInventoryService
    from novel_dev.services.cross_chapter_continuity_service import (
        CrossChapterContinuityService,
    )
    from novel_dev.agents.librarian import LibrarianAgent
    from novel_dev.agents.context_agent import ContextAgent
    from novel_dev.services.prompt_registry import PromptRegistry

    # 1. bootstrap novel_state + 实体 + chapter
    ns = NovelState(novel_id="n_1", current_phase="drafting", checkpoint_data={})
    async_session.add(ns)
    e = Entity(id="e_zhujue_a", type="character", name="主角A")
    async_session.add(e)
    ev = EntityVersion(
        entity_id="e_zhujue_a",
        version=1,
        state={"power_level": 0, "identity_role": "师兄"},
    )
    async_session.add(ev)
    for i in range(1, 6):
        ch = Chapter(
            id=f"ch_{i}",
            novel_id="n_1",
            chapter_number=i,
            title=f"ch {i}",
            volume_id="v1",
            raw_draft="主角A听见追兵。",
            polished_text="主角A听见追兵。",
        )
        async_session.add(ch)
    await async_session.commit()

    # 2. bootstrap prompts
    reg = PromptRegistry(async_session)
    await reg.bootstrap_defaults()
    # The Phase 4 prompts are in DEFAULT_PROMPTS already (see _default_prompts.py);
    # bootstrap_defaults creates them as v1.0 and active. Override with our
    # own content to make prompt-substring matching in the mock trivial.
    for name, content in [
        ("rolling_synopsis", "ROLLING TEMPLATE: {prev_synopsis} | {new_chapter_summaries} | {trigger_event}"),
        ("imagery_extraction", "TEMPLATE: {chapter_text}"),
        ("cross_chapter_drift", "DRIFT TEMPLATE: {current_text} {prior_texts} {entities}"),
    ]:
        await reg.create_version(name, "v2.0", content, is_active=True)

    # 3. Mock LLM that pattern-matches prompt substrings.
    async def mock_acomplete(messages, config=None):
        m = MagicMock()
        prompt_text = ""
        try:
            first = messages[0]
            prompt_text = first.content if hasattr(first, "content") else str(first)
        except Exception:
            prompt_text = ""
        if "ROLLING TEMPLATE" in prompt_text:
            m.text = '{"narrative_prose": "主角A 遭遇追兵,离开灵谷,身份从师兄变为独行。", "structured_json": {"plot_points": []}}'
        elif "DRIFT TEMPLATE" in prompt_text:
            m.text = "[]"
        elif "TEMPLATE:" in prompt_text or "意象" in prompt_text:
            m.text = '[{"item": "碎石硌掌心", "item_type": "physical_imagery", "frequency_in_chapter": 1}]'
        else:
            m.text = "{}"
        m.usage = None
        return m

    fake_client = MagicMock()
    fake_client.acomplete = AsyncMock(side_effect=mock_acomplete)

    with patch("novel_dev.services.rolling_chapter_synopsis_service.llm_factory") as m1, \
         patch("novel_dev.services.imagery_inventory_service.llm_factory") as m2, \
         patch("novel_dev.llm.llm_factory") as m3, \
         patch("novel_dev.services.cross_chapter_continuity_service.llm_factory") as m4:
        m1.get.return_value = fake_client
        m2.get.return_value = fake_client
        m3.get.return_value = fake_client
        m4.get.return_value = fake_client

        # 4. trigger RCS via librarian (quality block path). We omit
        # entity_state_changes here because the existing entity-change
        # evaluation path in librarian.on_chapter_finalized has a separate
        # LLM call we don't need to exercise for the RCS cache flow.
        lib = LibrarianAgent(async_session)
        await lib.on_chapter_finalized(
            novel_id="n_1",
            chapter_id="ch_5",
            gate_status="block",
        )
        await async_session.commit()

        # 5. verify RCS row written
        rcs = RollingChapterSynopsisService(async_session)
        latest = await rcs.get_latest("n_1")
        assert latest is not None, "RCS row should have been written"
        assert "主角A" in latest.narrative_prose, (
            f"Expected '主角A' in narrative_prose, got: {latest.narrative_prose!r}"
        )

        # 6. verify cache_to_checkpoint populated NovelState.checkpoint_data
        await async_session.refresh(ns)
        text = ContextAgent._narrative_source_from_checkpoint(ns.checkpoint_data)
        assert "主角A" in text, (
            f"Expected '主角A' in narrative_source, got: {text!r}"
        )

        # 7. cross-chapter pre-write constraints (no LLM involved here)
        continuity_svc = CrossChapterContinuityService(async_session)
        constraints = await continuity_svc.build_pre_write_constraints(
            "n_1", ["e_zhujue_a"]
        )
        assert "主角A" in constraints
        assert "师兄" in constraints

        # 8. imagery extraction (LLM-driven; mock returns one item)
        imagery_svc = ImageryInventoryService(async_session)
        count = await imagery_svc.extract_and_store(
            "n_1", "ch_5", "主角A听见碎石硌掌心。"
        )
        assert count == 1
        await async_session.commit()

        # 9. avoidance list — ch_5 imagery should NOT be in the list for ch_5,
        # so we ask the list for the *next* chapter (ch_6) with a window that
        # includes ch_5.
        avoidance = await imagery_svc.build_avoidance_list("n_1", "ch_6", window=5)
        assert "碎石硌掌心" in avoidance, (
            f"Expected '碎石硌掌心' in avoidance list, got: {avoidance!r}"
        )


@pytest.mark.asyncio
async def test_phase4_ab_routing_routes_via_chapter_id(async_session):
    """A/B 路由: same chapter routes stably, different chapters split
    between baseline and challenger."""
    from novel_dev.services.prompt_registry import PromptRegistry
    from novel_dev.services.ab_test_runner import ABTestRunner

    reg = PromptRegistry(async_session)
    # Register baseline v1.0 (active) and challenger v2.0 (inactive)
    await reg.create_version("writer", "v1.0", "v1", is_active=True)
    await reg.create_version("writer", "v2.0", "v2")
    runner = ABTestRunner(async_session)
    await runner.start("writer", "v1.0", "v2.0", max_samples=10, min_samples=3)

    # Same chapter -> stable routing (same content string)
    c1 = await reg.get_active_for_chapter("writer", "ch_test")
    c1_again = await reg.get_active_for_chapter("writer", "ch_test")
    assert c1 == c1_again, (
        f"A/B routing should be stable per chapter, got {c1!r} vs {c1_again!r}"
    )
    # And content must be one of the two registered contents
    assert c1 in {"v1", "v2"}

    # 100 chapters -> distribution must hit both
    picked = set()
    for i in range(100):
        picked.add(await reg.get_active_for_chapter("writer", f"ch_{i}"))
    assert picked == {"v1", "v2"}, (
        f"Expected both versions to be sampled across 100 chapters, got {picked!r}"
    )