import pytest

from novel_dev.agents.librarian import LibrarianAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.version_repo import EntityVersionRepository
from novel_dev.schemas.librarian import ExtractionResult
from novel_dev.services.chapter_generation_service import ChapterGenerationService
from novel_dev.services.world_state_review_service import WorldStateReviewService
from novel_dev.services.world_state_review_service import WorldStateReviewRequiredError


@pytest.mark.asyncio
async def test_librarian_persist_creates_world_state_review_when_diff_requires_confirmation(async_session):
    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    await entity_repo.create("e_lz", "character", "林照", novel_id="n_review")
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
        await LibrarianAgent(async_session).persist(extraction, "ch_review", "n_review")

    reviews = await WorldStateReviewService(async_session).list_reviews("n_review")
    assert len(reviews) == 1
    assert reviews[0].status == "pending"
    assert reviews[0].chapter_id == "ch_review"
    assert reviews[0].diff_result["confirm_required_items"][0]["code"] == "dead_entity_revived"
    assert reviews[0].extraction_payload["character_updates"][0]["entity_id"] == "林照"


@pytest.mark.asyncio
async def test_world_state_review_approve_resumes_librarian_persistence(async_session):
    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    await entity_repo.create("e_lz", "character", "林照", novel_id="n_review_resume")
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
    service = WorldStateReviewService(async_session)
    review = await service.create_pending_review(
        "n_review_resume",
        "ch_review_resume",
        extraction,
        {
            "status": "confirm_required",
            "confirm_required_items": [{"code": "dead_entity_revived", "entity_name": "林照"}],
        },
    )
    await async_session.commit()

    result = await service.resolve_review(review.id, action="approve")
    await async_session.commit()

    assert result.status == "approved"
    latest = await version_repo.get_latest("e_lz")
    assert latest.version == 2
    assert latest.state["current_state"]["condition"] == "醒来并开口"


@pytest.mark.asyncio
async def test_world_state_review_reject_skips_blocking_update_and_marks_resolved(async_session):
    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    await entity_repo.create("e_lz", "character", "林照", novel_id="n_review_reject")
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
    extraction = ExtractionResult(
        character_updates=[{
            "entity_id": "林照",
            "state": {"状态": "醒来并开口"},
            "diff_summary": {"source": "chapter"},
        }],
    )
    service = WorldStateReviewService(async_session)
    review = await service.create_pending_review(
        "n_review_reject",
        "ch_review_reject",
        extraction,
        {
            "status": "confirm_required",
            "confirm_required_items": [{"code": "dead_entity_revived", "entity_name": "林照"}],
        },
    )
    await async_session.commit()

    result = await service.resolve_review(review.id, action="reject")
    await async_session.commit()

    assert result.status == "rejected"
    latest = await version_repo.get_latest("e_lz")
    assert latest.version == 1
    assert latest.state["current_state"]["condition"] == "已死亡，尸身留在黑水城"


@pytest.mark.asyncio
async def test_auto_run_stops_as_waiting_world_state_review(async_session, monkeypatch):
    await NovelDirector(async_session).save_checkpoint(
        "n_auto_review",
        Phase.LIBRARIAN,
        {
            "current_volume_plan": {
                "review_status": {"status": "accepted"},
                "chapters": [{"chapter_id": "ch_auto_review"}],
            }
        },
        volume_id="v1",
        chapter_id="ch_auto_review",
    )

    async def raise_review_required(self, novel_id):
        raise WorldStateReviewRequiredError("review_1", "ch_auto_review")

    monkeypatch.setattr(ChapterGenerationService, "_run_current_chapter", raise_review_required)

    result = await ChapterGenerationService(async_session).auto_run("n_auto_review", max_chapters=1)

    assert result.stopped_reason == "waiting_world_state_review"
    assert result.failed_chapter_id == "ch_auto_review"
    assert "World state diff requires confirmation" in result.error
