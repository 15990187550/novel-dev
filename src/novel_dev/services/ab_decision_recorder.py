from __future__ import annotations
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import ABDecision
from novel_dev.repositories.ab_decision_repo import ABDecisionRepository

logger = logging.getLogger(__name__)

CRITICAL_ACTIONS = {"accept", "early_stop", "timeout", "rolled_back", "rollback_no_target", "accept_failed"}


class ABDecisionRecorder:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ABDecisionRepository(session)

    async def record(
        self,
        experiment_id: str,
        action: str,
        prompt_version_id: Optional[str] = None,
        scores: Optional[dict] = None,
        p_value: Optional[float] = None,
        effect_size: Optional[float] = None,
        meta: Optional[dict] = None,
    ) -> ABDecision:
        decision = await self.repo.create(
            experiment_id=experiment_id,
            action=action,
            prompt_version_id=prompt_version_id,
            scores=scores or {},
            p_value=p_value,
            effect_size=effect_size,
            meta=meta or {},
        )
        log_level = logging.ERROR if action in CRITICAL_ACTIONS else logging.INFO
        logger.log(
            log_level,
            f"ab_decision_{action}",
            extra={
                "experiment_id": experiment_id,
                "prompt_version_id": prompt_version_id,
                "scores": scores,
                "p_value": p_value,
            },
        )
        return decision
