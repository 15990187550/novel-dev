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
from novel_dev.services.recommendation_service import Recommendation, RecommendationService

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
        raise NotImplementedError
