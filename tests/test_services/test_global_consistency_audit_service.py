import pytest

from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
from novel_dev.repositories.relationship_repo import RelationshipRepository
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.services.chapter_generation_service import ChapterGenerationService
from novel_dev.services.global_consistency_audit_service import GlobalConsistencyAuditService


@pytest.mark.asyncio
async def test_global_consistency_audit_flags_mutually_exclusive_relationships(async_session):
    entity_repo = EntityRepository(async_session)
    rel_repo = RelationshipRepository(async_session)
    await entity_repo.create("e_lz", "character", "林照", novel_id="n_audit")
    await entity_repo.create("e_sqh", "character", "苏清寒", novel_id="n_audit")
    await rel_repo.create("e_lz", "e_sqh", "ally", novel_id="n_audit")
    await rel_repo.create("e_lz", "e_sqh", "enemy", novel_id="n_audit")
    await async_session.commit()

    result = await GlobalConsistencyAuditService(async_session).run("n_audit")

    assert result.status == "confirm_required"
    assert result.confirm_required_items[0]["code"] == "mutually_exclusive_relationships"
    assert set(result.confirm_required_items[0]["relation_types"]) == {"ally", "enemy"}


@pytest.mark.asyncio
async def test_global_consistency_audit_warns_recovered_foreshadowing_without_setup(async_session):
    repo = ForeshadowingRepository(async_session)
    fs = await repo.create("fs_1", "无来源的旧伏笔", novel_id="n_audit_fs")
    fs.回收状态 = "recovered"
    fs.recovered_chapter_id = "ch_5"
    await async_session.commit()

    result = await GlobalConsistencyAuditService(async_session).run("n_audit_fs")

    assert result.status == "warn"
    assert result.warning_items[0]["code"] == "foreshadowing_recovered_without_setup"


@pytest.mark.asyncio
async def test_auto_run_records_periodic_global_consistency_audit(async_session, monkeypatch):
    await NovelDirector(async_session).save_checkpoint(
        "n_periodic_audit",
        Phase.COMPLETED,
        {
            "global_audit_interval_chapters": 1,
            "current_volume_plan": {
                "review_status": {"status": "accepted"},
                "chapters": [{"chapter_id": "ch_periodic"}],
            },
        },
        volume_id="v1",
        chapter_id="ch_periodic",
    )

    async def fake_run_current_chapter(self, novel_id):
        return "ch_periodic"

    monkeypatch.setattr(ChapterGenerationService, "_run_current_chapter", fake_run_current_chapter)

    result = await ChapterGenerationService(async_session).auto_run("n_periodic_audit", max_chapters=1)

    state = await NovelDirector(async_session).resume("n_periodic_audit")
    assert result.completed_chapters == ["ch_periodic"]
    assert state.checkpoint_data["global_consistency_audit"]["status"] == "pass"
