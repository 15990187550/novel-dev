from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.repositories.world_state_review_repo import WorldStateReviewRepository
from novel_dev.schemas.librarian import ExtractionResult


class WorldStateReviewRequiredError(RuntimeError):
    def __init__(self, review_id: str, chapter_id: str):
        self.review_id = review_id
        self.chapter_id = chapter_id
        super().__init__("World state diff requires confirmation before librarian persistence")


class WorldStateReviewService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = WorldStateReviewRepository(session)

    async def create_pending_review(
        self,
        novel_id: str,
        chapter_id: str,
        extraction: ExtractionResult,
        diff_result: dict,
    ):
        existing = await self.repo.find_pending_for_chapter(novel_id, chapter_id)
        payload = extraction.model_dump()
        if existing:
            existing.extraction_payload = payload
            existing.diff_result = dict(diff_result or {})
            await self.session.flush()
            return existing
        return await self.repo.create(novel_id, chapter_id, payload, diff_result)

    async def list_reviews(self, novel_id: str, status: str | None = None):
        return await self.repo.list_by_novel(novel_id, status=status)

    async def get_review(self, review_id: str):
        return await self.repo.get_by_id(review_id)

    async def resolve_review(self, review_id: str, *, action: str, edited_extraction: dict | None = None):
        review = await self.repo.get_by_id(review_id)
        if not review:
            raise ValueError("World state review not found")
        if review.status != "pending":
            raise ValueError("Only pending world state reviews can be resolved")
        if action not in {"approve", "reject", "edit"}:
            raise ValueError(f"Unsupported world state review action: {action}")

        extraction_payload = dict(review.extraction_payload or {})
        if action == "reject":
            await self.repo.mark_resolved(review_id, status="rejected", decision={"action": action})
            return review
        if action == "edit":
            if not isinstance(edited_extraction, dict):
                raise ValueError("edited_extraction is required for edit action")
            extraction_payload = edited_extraction

        extraction = ExtractionResult.model_validate(extraction_payload)
        from novel_dev.agents.librarian import LibrarianAgent

        await LibrarianAgent(self.session).persist(
            extraction,
            review.chapter_id,
            review.novel_id,
            skip_world_state_review=True,
        )
        status = "approved" if action == "approve" else "edited"
        await self.repo.mark_resolved(
            review_id,
            status=status,
            decision={"action": action, "edited_extraction": edited_extraction or None},
        )
        return review
