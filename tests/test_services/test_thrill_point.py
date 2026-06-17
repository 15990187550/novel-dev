"""Tests for ThrillPointRepository — Task 18 Phase 4.

Covers:
- create() persists thrill point with all fields
- list_unverified() filters by chapter_id and excludes verified items
- mark_verified() flips fast_review_verified and stores evidence
- chapter_id isolation: list_unverified for one chapter does not leak
  predictions from another chapter of the same novel
"""

import pytest

from novel_dev.repositories.thrill_point_repo import ThrillPointRepository


@pytest.mark.asyncio
async def test_create_and_query_unverified_predicted_thrills(async_session):
    repo = ThrillPointRepository(async_session)
    await repo.create(novel_id="n_1", chapter_id="ch_1", beat_idx=2,
                      thrill_type="face_slap", intensity="high",
                      planner_predicted=True)
    # Simulate a second predicted thrill that has already been verified via
    # mark_verified, so list_unverified should ignore it.
    verified_tp = await repo.create(novel_id="n_1", chapter_id="ch_1", beat_idx=3,
                                    thrill_type="level_up", intensity="peak",
                                    planner_predicted=True)
    await repo.mark_verified(verified_tp.id, evidence_quote="突破瓶颈，气息暴涨")
    unverified = await repo.list_unverified("n_1", chapter_id="ch_1")
    assert len(unverified) == 1
    assert unverified[0].thrill_type == "face_slap"
    assert unverified[0].planner_predicted is True
    assert unverified[0].fast_review_verified is False


@pytest.mark.asyncio
async def test_list_unverified_isolated_by_chapter(async_session):
    repo = ThrillPointRepository(async_session)
    await repo.create(novel_id="n_1", chapter_id="ch_a", beat_idx=0,
                      thrill_type="revelation", intensity="medium",
                      planner_predicted=True)
    await repo.create(novel_id="n_1", chapter_id="ch_b", beat_idx=0,
                      thrill_type="recognition", intensity="high",
                      planner_predicted=True)
    only_ch_a = await repo.list_unverified("n_1", chapter_id="ch_a")
    assert {tp.thrill_type for tp in only_ch_a} == {"revelation"}
    only_ch_b = await repo.list_unverified("n_1", chapter_id="ch_b")
    assert {tp.thrill_type for tp in only_ch_b} == {"recognition"}


@pytest.mark.asyncio
async def test_mark_verified_flips_flag_and_stores_evidence(async_session):
    repo = ThrillPointRepository(async_session)
    tp = await repo.create(novel_id="n_2", chapter_id="ch_2", beat_idx=1,
                           thrill_type="show_off", intensity="medium",
                           planner_predicted=True)
    await repo.mark_verified(tp.id, evidence_quote="他轻轻一推，众弟子皆已倒地")
    remaining = await repo.list_unverified("n_2", chapter_id="ch_2")
    assert remaining == []
    # Re-fetch to confirm evidence was stored
    from sqlalchemy import select
    from novel_dev.db.models import ThrillPoint
    result = await async_session.execute(select(ThrillPoint).where(ThrillPoint.id == tp.id))
    refreshed = result.scalar_one()
    assert refreshed.fast_review_verified is True
    assert refreshed.evidence_quote == "他轻轻一推，众弟子皆已倒地"
