from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import QualityRootCause


class RootCauseRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def persist(
        self,
        chapter_id: str,
        analyzer_version: str,
        summary: str,
        suggested_actions: list[dict],
        confidence: float,
        input_snapshot: dict,
    ) -> QualityRootCause:
        rc = QualityRootCause(
            id=str(uuid.uuid4()),
            chapter_id=chapter_id,
            analyzer_version=analyzer_version,
            summary=summary,
            suggested_actions={"items": suggested_actions},
            confidence=confidence,
            input_snapshot=input_snapshot,
            created_at=datetime.utcnow(),
        )
        self.session.add(rc)
        await self.session.flush()
        return rc

    async def get_latest_for_chapter(self, chapter_id: str) -> Optional[QualityRootCause]:
        result = await self.session.execute(
            select(QualityRootCause)
            .where(QualityRootCause.chapter_id == chapter_id)
            .order_by(QualityRootCause.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
