import pytest

from novel_dev.agents.librarian import LibrarianAgent
from novel_dev.repositories.entity_repo import EntityRepository
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
