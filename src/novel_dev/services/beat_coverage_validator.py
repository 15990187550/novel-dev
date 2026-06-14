"""Post-write beat coverage validator with LLM-as-judge and deterministic fallback."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from novel_dev.schemas.quality import BeatBoundaryCard

logger = logging.getLogger(__name__)


@dataclass
class BeatCoverageResult:
    beat_index: int
    covered: bool
    deviation: str | None
    severity: Literal["ok", "warn", "block"]

    def to_issue_code(self) -> str | None:
        if self.severity == "ok":
            return None
        if self.severity == "block":
            return "BEAT_BOUNDARY_VIOLATION"
        return "EVENT_ORDER_DRIFT"


class BeatCoverageValidator:
    def __init__(self, session, llm_client=None, use_llm: bool = True):
        self.session = session
        self.llm = llm_client
        self.use_llm = use_llm

    async def validate(
        self,
        beat_cards: list[BeatBoundaryCard],
        draft_text: str,
    ) -> list[BeatCoverageResult]:
        if not beat_cards and not self.use_llm:
            return [
                BeatCoverageResult(
                    beat_index=-1,
                    covered=True,
                    deviation="no_cards_no_llm",
                    severity="ok",
                )
            ]
        if self.use_llm:
            try:
                return await self._llm_judge(beat_cards, draft_text)
            except Exception as exc:
                logger.warning(
                    "Beat coverage LLM judge failed, falling back",
                    extra={"fallback": "deterministic", "reason": repr(exc)},
                )
        return self._deterministic_check(beat_cards, draft_text)

    async def _llm_judge(
        self,
        beat_cards: list[BeatBoundaryCard],
        draft_text: str,
    ) -> list[BeatCoverageResult]:
        # Implemented in Task 4
        raise NotImplementedError

    def _deterministic_check(
        self,
        beat_cards: list[BeatBoundaryCard],
        draft_text: str,
    ) -> list[BeatCoverageResult]:
        # Implemented in Task 4
        raise NotImplementedError
