import pytest

from novel_dev.agents.librarian import LibrarianAgent
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
from novel_dev.repositories.relationship_repo import RelationshipRepository
from novel_dev.repositories.version_repo import EntityVersionRepository
from novel_dev.schemas.librarian import ExtractionResult
from novel_dev.services.world_state_diff_guard_service import WorldStateDiffGuardService


@pytest.mark.asyncio
async def test_world_state_diff_guard_requires_confirmation_before_reviving_dead_entity(async_session):
    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    await entity_repo.create("e_lz", "character", "林照", novel_id="n_guard")
    await version_repo.create(
        "e_lz",
        1,
        {
            "canonical_profile": {"name": "林照", "identity_role": "青云宗外门弟子"},
            "current_state": {"condition": "已死亡，尸身留在黑水城"},
            "observations": {},
            "canonical_meta": {"identity_role": {"source": "setting"}},
        },
        chapter_id="setting",
    )
    await entity_repo.update_version("e_lz", 1)
    await async_session.commit()

    extraction = ExtractionResult(
        character_updates=[{
            "entity_id": "林照",
            "state": {"状态": "醒来并开口"},
            "diff_summary": {"source": "chapter"},
        }],
    )

    result = await WorldStateDiffGuardService(async_session).analyze(extraction, "n_guard")

    assert result.status == "confirm_required"
    assert result.confirm_required_items[0]["code"] == "dead_entity_revived"


@pytest.mark.asyncio
async def test_librarian_persist_blocks_confirm_required_world_state_diff(async_session):
    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    await entity_repo.create("e_lz", "character", "林照", novel_id="n_guard")
    await version_repo.create(
        "e_lz",
        1,
        {
            "canonical_profile": {"name": "林照"},
            "current_state": {"condition": "已死亡，尸身留在黑水城"},
            "observations": {},
            "canonical_meta": {},
        },
        chapter_id="setting",
    )
    await entity_repo.update_version("e_lz", 1)
    await async_session.commit()

    extraction = ExtractionResult(
        character_updates=[{
            "entity_id": "林照",
            "state": {"状态": "醒来并开口"},
            "diff_summary": {"source": "chapter"},
        }],
    )

    with pytest.raises(RuntimeError, match="World state diff requires confirmation"):
        await LibrarianAgent(async_session).persist(extraction, "vol_1_ch_1", "n_guard")

    latest = await version_repo.get_latest("e_lz")
    assert latest.version == 1
    assert latest.state["current_state"]["condition"] == "已死亡，尸身留在黑水城"


@pytest.mark.asyncio
async def test_world_state_diff_guard_requires_confirmation_for_canonical_profile_overwrite(async_session):
    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    await entity_repo.create("e_lz", "character", "林照", novel_id="n_guard")
    await version_repo.create(
        "e_lz",
        1,
        {
            "canonical_profile": {"name": "林照", "identity_role": "青云宗外门弟子"},
            "current_state": {},
            "observations": {},
            "canonical_meta": {"identity_role": {"source": "setting"}},
        },
        chapter_id="setting",
    )
    await entity_repo.update_version("e_lz", 1)
    await async_session.commit()

    extraction = ExtractionResult(
        character_updates=[{
            "entity_id": "林照",
            "state": {"canonical_profile": {"identity_role": "魔门圣子"}},
            "diff_summary": {"source": "chapter"},
        }],
    )

    result = await WorldStateDiffGuardService(async_session).analyze(extraction, "n_guard")

    assert result.status == "confirm_required"
    assert result.confirm_required_items[0]["code"] == "canonical_profile_overwrite"
    assert result.confirm_required_items[0]["conflicts"][0] == {
        "field": "identity_role",
        "from": "青云宗外门弟子",
        "to": "魔门圣子",
    }


@pytest.mark.asyncio
async def test_world_state_diff_guard_requires_confirmation_for_relationship_polarity_flip(async_session):
    entity_repo = EntityRepository(async_session)
    rel_repo = RelationshipRepository(async_session)
    await entity_repo.create("e_lz", "character", "林照", novel_id="n_guard_rel")
    await entity_repo.create("e_sqh", "character", "苏清寒", novel_id="n_guard_rel")
    await rel_repo.create("e_lz", "e_sqh", "ally", novel_id="n_guard_rel")
    await async_session.commit()

    extraction = ExtractionResult(
        new_relationships=[{
            "source_entity_id": "林照",
            "target_entity_id": "苏清寒",
            "relation_type": "enemy",
        }],
    )

    result = await WorldStateDiffGuardService(async_session).analyze(extraction, "n_guard_rel")

    assert result.status == "confirm_required"
    assert result.confirm_required_items[0]["code"] == "relationship_polarity_flip"


@pytest.mark.asyncio
async def test_world_state_diff_guard_requires_confirmation_for_unique_item_owner_conflict(async_session):
    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    await entity_repo.create("item_sword", "item", "青霜剑", novel_id="n_guard_item")
    await version_repo.create(
        "item_sword",
        1,
        {
            "canonical_profile": {"name": "青霜剑"},
            "current_state": {"owner": "林照"},
            "observations": {},
            "canonical_meta": {},
        },
        chapter_id="setting",
    )
    await entity_repo.update_version("item_sword", 1)
    await async_session.commit()

    extraction = ExtractionResult(
        concept_updates=[{
            "entity_id": "青霜剑",
            "state": {"持有者": "苏清寒"},
            "diff_summary": {"source": "chapter"},
        }],
    )

    result = await WorldStateDiffGuardService(async_session).analyze(extraction, "n_guard_item")

    assert result.status == "confirm_required"
    assert result.confirm_required_items[0]["code"] == "unique_item_owner_conflict"


@pytest.mark.asyncio
async def test_world_state_diff_guard_warns_duplicate_foreshadowing_recovery(async_session):
    repo = ForeshadowingRepository(async_session)
    fs = await repo.create("fs_dup", "旧伏笔", 埋下_chapter_id="ch_1", novel_id="n_guard_fs")
    fs.回收状态 = "recovered"
    fs.recovered_chapter_id = "ch_4"
    await async_session.commit()

    extraction = ExtractionResult(foreshadowings_recovered=["fs_dup"])

    result = await WorldStateDiffGuardService(async_session).analyze(extraction, "n_guard_fs")

    assert result.status == "warn"
    assert result.warning_items[0]["code"] == "foreshadowing_duplicate_recovery"
