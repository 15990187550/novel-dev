"""Bridge RecommendationService decisions to rewrite dispatch."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.exc import IntegrityError

from novel_dev.config.quality_config import ConfigError, get_quality_config
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.generation_job_repo import GenerationJobRepository
from novel_dev.services.chapter_rewrite_service import ChapterRewriteService
from novel_dev.services.recommendation_service import Recommendation, RecommendationService, RecommendationType

logger = logging.getLogger(__name__)


@dataclass
class WireResult:
    action: Literal["accept", "auto_rewrite_queued", "manual_review"]
    recommendation: Recommendation | None
    rewrite_job_id: str | None


class RecommendationWirer:
    def __init__(self, session, max_auto_rewrites: int | None = None):
        self.session = session
        if max_auto_rewrites is None:
            cfg = get_quality_config()
            try:
                max_auto_rewrites = cfg["recommendation"]["max_auto_rewrites"]
            except KeyError as exc:
                raise ConfigError(
                    "Missing required key quality_thresholds.recommendation.max_auto_rewrites"
                ) from exc
        self.max_auto_rewrites = max_auto_rewrites
        self.chapter_repo = ChapterRepository(session)
        self.job_repo = GenerationJobRepository(session)

    async def evaluate_and_dispatch(self, novel_id: str, chapter_id: str) -> WireResult:
        chapter = await self.chapter_repo.get_by_id(chapter_id)
        if chapter is None:
            logger.error("RecommendationWirer chapter not found", extra={"chapter_id": chapter_id})
            return WireResult(action="manual_review", recommendation=None, rewrite_job_id=None)

        if chapter.attempt_index > self.max_auto_rewrites + 3:
            logger.error("attempt_index drift detected", extra={"chapter_id": chapter_id, "attempt_index": chapter.attempt_index})
            return WireResult(action="manual_review", recommendation=None, rewrite_job_id=None)

        chapter_dict = {
            "id": chapter.id,
            "final_review_score": chapter.final_review_score,
            "quality_status": chapter.quality_status or "unchecked",
            "score_breakdown": chapter.score_breakdown or {},
        }
        try:
            recommendation = RecommendationService(
                chapter=chapter_dict,
                recent_issue_counts=[],
                current_attempt=chapter.attempt_index,
            ).recommend(accept_with_warn=False)
        except Exception as exc:
            logger.error("RecommendationWirer failed", extra={"chapter_id": chapter_id, "error": repr(exc)})
            return WireResult(action="manual_review", recommendation=None, rewrite_job_id=None)

        rec_type = recommendation.recommendation
        if rec_type == RecommendationType.ACCEPT:
            return WireResult(action="accept", recommendation=recommendation, rewrite_job_id=None)
        if rec_type == RecommendationType.STOP_AND_INSPECT:
            logger.warning("Quality gate hit stop_and_inspect", extra={"chapter_id": chapter_id, "attempt": chapter.attempt_index})
            return WireResult(action="manual_review", recommendation=recommendation, rewrite_job_id=None)

        if chapter.attempt_index < self.max_auto_rewrites:
            return await self._queue_rewrite(novel_id, chapter_id, recommendation)
        return WireResult(action="manual_review", recommendation=recommendation, rewrite_job_id=None)

    async def _queue_rewrite(
        self,
        novel_id: str,
        chapter_id: str,
        recommendation: Recommendation,
    ) -> WireResult:
        chapter = await self.chapter_repo.get_by_id(chapter_id)
        chapter.attempt_index += 1
        chapter.quality_status = "rewriting"
        await self.session.flush()
        try:
            rewrite_service = ChapterRewriteService(self.session)
            await rewrite_service.rewrite(novel_id, chapter_id)
        except IntegrityError as exc:
            logger.warning("rewrite queue IntegrityError, checking active job", extra={"chapter_id": chapter_id, "error": repr(exc)})
            active = await self.job_repo.get_active(novel_id, "chapter_rewrite")
            if active:
                return WireResult(action="auto_rewrite_queued", recommendation=recommendation, rewrite_job_id=active.id)
            logger.error("rewrite queue failed", extra={"chapter_id": chapter_id, "error": repr(exc)})
            return WireResult(action="manual_review", recommendation=recommendation, rewrite_job_id=None)
        except Exception as exc:
            logger.error("rewrite queue failed", extra={"chapter_id": chapter_id, "error": repr(exc)})
            return WireResult(action="manual_review", recommendation=recommendation, rewrite_job_id=None)
        return WireResult(action="auto_rewrite_queued", recommendation=recommendation, rewrite_job_id=None)
