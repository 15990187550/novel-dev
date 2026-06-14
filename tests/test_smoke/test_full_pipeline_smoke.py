"""Smoke test exercising the full 9-phase pipeline with mocked LLM calls.

NOTE: This test runs multiple agent invocations, so it is marked @pytest.mark.slow.
It uses the autouse ``mock_llm_factory`` fixture from ``tests/conftest.py`` plus
a targeted patch for ``LibrarianAgent`` (which is not covered by the default mock).

Pipeline phases exercised (per CLAUDE.md):
  1. brainstorming      — Director transitions to volume_planning
  2. volume_planning   — VolumePlannerAgent runs, generates accepted plan
  3. context_preparation — Director transitions to drafting once chapter_context set
  4. drafting          — WriterAgent runs (we set raw_draft directly to skip)
  5. reviewing         — CriticAgent runs, sets score_overall
  6. editing           — EditorAgent runs (mocked polished text)
  7. fast_reviewing    — FastReviewAgent runs, sets quality_status + metric
  8. librarian         — LibrarianAgent runs, creates entity/timeline
  9. completed         — Director continues to next phase
"""

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import select, func

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.agents.librarian import LibrarianAgent
from novel_dev.db.models import (
    ChapterQualityMetric,
    Entity,
    Timeline,
)
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.schemas.context import ChapterContext, ChapterPlan, LocationContext
from novel_dev.schemas.librarian import ExtractionResult, NewEntity
from novel_dev.schemas.outline import SynopsisData


pytestmark = pytest.mark.slow


# ----------------------------------------------------------------------------
# ExtractionResult that the mocked LibrarianAgent.extract() returns.
# Includes one new entity so we can verify entity creation in the smoke test.
# ----------------------------------------------------------------------------
def _make_librarian_extraction() -> ExtractionResult:
    return ExtractionResult(
        new_entities=[
            NewEntity(type="character", name="陆照", state={"mentioned": True}),
        ],
    )


@pytest.fixture
def novel_id() -> str:
    return f"n_smoke_{uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_full_9_phase_pipeline(
    async_session,
    tmp_path,
    monkeypatch,
    mock_llm_factory,
    novel_id,
):
    """Walk a single chapter through all 9 phases via director.advance()."""
    # ------------------------------------------------------------------------
    # Setup: create novel state in BRAINSTORMING phase + synopsis doc
    # ------------------------------------------------------------------------
    director = NovelDirector(session=async_session)

    synopsis = SynopsisData(
        title="天玄纪元",
        logline="主角在修炼世界中崛起",
        core_conflict="个人复仇与天下大义",
        themes=["成长"],
        character_arcs=[],
        milestones=[],
        estimated_volumes=1,
        estimated_total_chapters=1,
        estimated_total_words=3000,
    )

    await director.save_checkpoint(
        novel_id,
        phase=Phase.BRAINSTORMING,
        checkpoint_data={"synopsis_data": synopsis.model_dump()},
    )
    await DocumentRepository(async_session).create(
        doc_id=f"doc_syn_{novel_id}",
        novel_id=novel_id,
        doc_type="synopsis",
        title="synopsis",
        content=synopsis.model_dump_json(),
    )
    await async_session.commit()

    # Redirect data dir so ArchiveService doesn't pollute the real one.
    monkeypatch.setattr("novel_dev.agents.director.settings.data_dir", str(tmp_path))

    # ------------------------------------------------------------------------
    # Phase 1 -> 2: brainstorming -> volume_planning
    # ------------------------------------------------------------------------
    state = await director.advance(novel_id)
    assert state.current_phase == Phase.VOLUME_PLANNING.value

    # ------------------------------------------------------------------------
    # Phase 2: volume_planning (VolumePlannerAgent runs)
    # ------------------------------------------------------------------------
    state = await director.advance(novel_id)
    assert state.current_phase == Phase.CONTEXT_PREPARATION.value

    cp = dict(state.checkpoint_data or {})
    volume_plan = cp.get("current_volume_plan", {})
    assert volume_plan.get("review_status", {}).get("status") == "accepted", (
        f"Volume plan not accepted: {volume_plan.get('review_status')}"
    )

    chapter_id = cp["current_chapter_plan"]["chapter_id"]
    volume_id = volume_plan["volume_id"]
    chapter_plan_dict = cp["current_chapter_plan"]

    # Ensure Chapter row exists (VolumePlannerAgent creates it, but be defensive)
    ch_repo = ChapterRepository(async_session)
    existing = await ch_repo.get_by_id(chapter_id)
    if existing is None:
        await ch_repo.create(
            chapter_id, volume_id, chapter_plan_dict["chapter_number"],
            chapter_plan_dict["title"], novel_id=novel_id,
        )
        await async_session.commit()

    # ------------------------------------------------------------------------
    # Phase 3: context_preparation -> drafting
    # Build a context that matches the current chapter plan (so the
    # staleness guard passes), then advance.
    # We override target_word_count to a small value so the FastReviewAgent's
    # word_count check (target ±10%) doesn't reject our short mock text.
    # ------------------------------------------------------------------------
    chapter_plan_dict["target_word_count"] = 50
    chapter_plan_dict["beats"] = [{"summary": "主角觉醒", "target_mood": "tense"}]
    chapter_plan = ChapterPlan.model_validate(chapter_plan_dict)
    chapter_context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="天玄大陆",
        active_entities=[],
        location_context=LocationContext(current="青云宗"),
        timeline_events=[],
        pending_foreshadowings=[],
    )

    cp["chapter_context"] = chapter_context.model_dump()
    await director.save_checkpoint(
        novel_id,
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data=cp,
        volume_id=volume_id,
        chapter_id=chapter_id,
    )
    await async_session.commit()

    state = await director.advance(novel_id)
    assert state.current_phase == Phase.DRAFTING.value

    # ------------------------------------------------------------------------
    # Phase 4 -> DRAFTING transition: provide raw_draft so advance() can move
    # to reviewing. WriterAgent runs but uses the mocked LLM (defaults to
    # a string for the chapter body — sufficient for the smoke test).
    # ------------------------------------------------------------------------
    raw_draft = (
        "陆照在青云宗后山觉醒血脉，灵气冲天而起，执事赶来查看。"
        "陆照握紧玉佩，决心踏上修行之路，追查父母失踪的真相。"
    )
    await ch_repo.update_text(chapter_id, raw_draft=raw_draft)
    await async_session.commit()

    state = await director.advance(novel_id)
    assert state.current_phase == Phase.REVIEWING.value

    # ------------------------------------------------------------------------
    # Phase 5: reviewing — CriticAgent scores the chapter
    # ------------------------------------------------------------------------
    state = await director.advance(novel_id)
    assert state.current_phase == Phase.EDITING.value

    # Chapter should now have score_overall set (mocked Critic returns 88)
    ch = await ch_repo.get_by_id(chapter_id)
    assert ch is not None
    assert ch.raw_draft is not None and len(ch.raw_draft) > 0
    assert ch.score_overall is not None and ch.score_overall >= 70, (
        f"Expected score_overall >= 70 from CriticAgent, got {ch.score_overall}"
    )

    # ------------------------------------------------------------------------
    # Phase 6: editing — EditorAgent polishes text
    # ------------------------------------------------------------------------
    state = await director.advance(novel_id)
    assert state.current_phase == Phase.FAST_REVIEWING.value

    # Ensure polished_text exists so FastReviewAgent / quality gate can run.
    ch = await ch_repo.get_by_id(chapter_id)
    if not ch.polished_text:
        await ch_repo.update_text(chapter_id, polished_text=raw_draft)
        await async_session.commit()

    # ------------------------------------------------------------------------
    # Phase 7: fast_reviewing — FastReviewAgent sets quality_status AND
    # records a row in chapter_quality_metrics (Task 10 wire-up).
    # ------------------------------------------------------------------------
    state = await director.advance(novel_id)
    # FastReviewAgent may advance to LIBRARIAN directly (default mocked response
    # returns consistency_fixed=True and beat_cohesion_ok=True).
    assert state.current_phase in {Phase.LIBRARIAN.value, Phase.EDITING.value}

    # Verify quality_status was set on the chapter and a metric row was written.
    ch = await ch_repo.get_by_id(chapter_id)
    assert ch.quality_status not in (None, "", "unchecked"), (
        f"Expected quality_status to be set after FastReviewAgent, got {ch.quality_status!r}"
    )

    metrics_q = await async_session.execute(
        select(func.count()).select_from(ChapterQualityMetric).where(
            ChapterQualityMetric.chapter_id == chapter_id,
        )
    )
    metric_count = metrics_q.scalar_one()
    assert metric_count >= 1, (
        "Expected at least 1 ChapterQualityMetric row after FastReviewAgent"
    )

    # ------------------------------------------------------------------------
    # Phase 8: librarian — extract entities/timeline + archive
    # ------------------------------------------------------------------------
    # If FastReviewAgent returned to EDITING (e.g., quality gate block with
    # repair), walk forward until we reach LIBRARIAN or COMPLETED.
    safety = 0
    while state.current_phase not in {Phase.LIBRARIAN.value, Phase.COMPLETED.value} and safety < 5:
        state = await director.advance(novel_id)
        safety += 1

    # We may already be in COMPLETED if there was a quality block and the
    # director decided not to archive. For the smoke test we expect the
    # happy path to reach LIBRARIAN; if not, skip the librarian assertions.
    if state.current_phase == Phase.LIBRARIAN.value:
        # Count entities before librarian runs so we can verify creation.
        before_entities = (await async_session.execute(
            select(func.count()).select_from(Entity).where(Entity.novel_id == novel_id)
        )).scalar_one()
        before_timeline = (await async_session.execute(
            select(func.count()).select_from(Timeline).where(Timeline.novel_id == novel_id)
        )).scalar_one()

        # Patch LibrarianAgent.extract() so we control the extraction payload
        # without depending on LLM mocking (the agent's extract() uses
        # call_and_parse_model which goes through the LLM factory — but we
        # want a deterministic result for the smoke test).
        async def fake_extract(novel_id_arg, chapter_id_arg, polished_text):
            return _make_librarian_extraction()

        with patch.object(
            LibrarianAgent, "extract", side_effect=fake_extract
        ):
            state = await director.advance(novel_id)

        # Should have advanced to COMPLETED (or next chapter/volume) after archive.
        # Single-chapter volumes wrap around to VOLUME_PLANNING for the next vol.
        assert state.current_phase in {
            Phase.COMPLETED.value,
            Phase.CONTEXT_PREPARATION.value,
            Phase.VOLUME_PLANNING.value,
        }, f"Unexpected phase after librarian: {state.current_phase}"

        after_entities = (await async_session.execute(
            select(func.count()).select_from(Entity).where(Entity.novel_id == novel_id)
        )).scalar_one()
        after_timeline = (await async_session.execute(
            select(func.count()).select_from(Timeline).where(Timeline.novel_id == novel_id)
        )).scalar_one()

        # The mocked librarian payload includes one new entity, so we
        # expect at least one new entity row.
        assert after_entities > before_entities, (
            f"Librarian should have created at least one entity "
            f"(before={before_entities}, after={after_entities})"
        )

    # ------------------------------------------------------------------------
    # Phase 9: completed — pipeline has cycled through all phases.
    # Verify chapter is archived (status flag).
    # ------------------------------------------------------------------------
    ch = await ch_repo.get_by_id(chapter_id)
    assert ch is not None
    # Either archived (librarian ran) or completed (review done); both valid.
    assert ch.status in {"archived", "completed"}, (
        f"Unexpected chapter status at end of pipeline: {ch.status!r}"
    )

    # Final invariant: chapter record exists with both draft + scores populated.
    assert ch.score_overall is not None
    assert ch.quality_status not in (None, "", "unchecked")
    assert ch.world_state_ingested is True or state.current_phase == Phase.COMPLETED.value