"""Tests for Task 19 Phase 4 — Entity.cheat_ability fields.

Covers:
- 3 new Entity fields (cheat_ability, cheat_activation_rules,
  cheat_first_activation_chapter) persist via SQLAlchemy and round-trip
  through EntityRepository.get_by_id.
- Default values are backward-compatible (empty string / empty list / None).
"""

import pytest

from novel_dev.db.models import Entity
from novel_dev.repositories.entity_repo import EntityRepository


@pytest.mark.asyncio
async def test_entity_cheat_fields_persist(async_session):
    e = Entity(
        id="e_luzhao",
        type="character",
        name="陆照",
        cheat_ability="残玉空间 + 时间倒流",
        cheat_activation_rules=["每日子时触摸玉佩可回溯一刻钟"],
        cheat_first_activation_chapter="ch_3",
    )
    async_session.add(e)
    await async_session.flush()

    fetched = await EntityRepository(async_session).get_by_id("e_luzhao")
    assert fetched is not None
    assert fetched.cheat_ability == "残玉空间 + 时间倒流"
    assert fetched.cheat_activation_rules == ["每日子时触摸玉佩可回溯一刻钟"]
    assert "每日子时" in fetched.cheat_activation_rules[0]
    assert fetched.cheat_first_activation_chapter == "ch_3"


@pytest.mark.asyncio
async def test_entity_cheat_fields_default_to_empty(async_session):
    """Backward compat: existing entity rows must continue to work."""
    e = Entity(id="e_legacy", type="character", name="旧角色")
    async_session.add(e)
    await async_session.flush()

    fetched = await EntityRepository(async_session).get_by_id("e_legacy")
    assert fetched is not None
    assert fetched.cheat_ability == ""
    assert fetched.cheat_activation_rules == []
    assert fetched.cheat_first_activation_chapter is None
