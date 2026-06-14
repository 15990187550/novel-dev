from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from novel_dev.schemas.quality import BeatBoundaryCard
from novel_dev.llm import llm_factory
from novel_dev.repositories.root_cause_repo import RootCauseRepository
from novel_dev.repositories.prompt_version_repo import PromptVersionRepository
from novel_dev.services.prompt_registry import PromptRegistry

logger = logging.getLogger(__name__)

MAX_INPUT_CHARS = 5000


@dataclass
class RootCauseResult:
    summary: str
    suggested_actions: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    analyzer_version: str = "v1.0"


class RootCauseAnalyzer:
    def __init__(
        self, session,
        prompt_registry: Optional[PromptRegistry] = None,
        llm_client=None,
    ):
        self.session = session
        self.prompt_registry = prompt_registry or PromptRegistry(session)
        self.llm_client = llm_client
        self.repo = RootCauseRepository(session)

    async def _get_llm_client(self):
        if self.llm_client:
            return self.llm_client
        return llm_factory.get("RootCauseAnalyzer")

    async def analyze(
        self,
        novel_id: str,
        chapter_id: str,
        chapter_text: str,
        score_breakdown: dict,
        issue_codes: list[str],
        beat_boundary_cards: list[BeatBoundaryCard],
    ) -> RootCauseResult:
        if len(chapter_text) > MAX_INPUT_CHARS:
            truncated = chapter_text[:MAX_INPUT_CHARS] + "...[截断]"
        else:
            truncated = chapter_text

        try:
            template = await self.prompt_registry.get_active("root_cause_analyzer")
        except Exception as exc:
            logger.warning("root_cause_prompt_load_failed", extra={"error": repr(exc)})
            return await self._fail_and_persist(novel_id, chapter_id, str(exc))

        active = await PromptVersionRepository(self.session).get_active("root_cause_analyzer")
        analyzer_version = active.version if active else "v1.0"

        prompt = template.format(
            chapter_text=truncated,
            score_breakdown=json.dumps(score_breakdown, ensure_ascii=False),
            issue_codes=", ".join(issue_codes) if issue_codes else "(none)",
            beat_cards=self._format_beat_cards(beat_boundary_cards),
        )

        try:
            client = await self._get_llm_client()
            from novel_dev.llm.models import ChatMessage
            response = await client.acomplete(
                [ChatMessage(role="user", content=prompt)],
            )
            result = self._parse_response(response.text, analyzer_version)
        except Exception as exc:
            logger.warning("root_cause_analysis_failed", extra={
                "chapter_id": chapter_id, "error": repr(exc),
            })
            return await self._fail_and_persist(novel_id, chapter_id, str(exc), analyzer_version)

        await self.repo.persist(
            chapter_id=chapter_id,
            analyzer_version=analyzer_version,
            summary=result.summary,
            suggested_actions=result.suggested_actions,
            confidence=result.confidence,
            input_snapshot={"chapter_preview": truncated[:500]},
        )
        return result

    async def _fail_and_persist(
        self, novel_id: str, chapter_id: str, error: str,
        analyzer_version: str = "v1.0",
    ) -> RootCauseResult:
        result = RootCauseResult(
            summary="[分析失败,请人工]",
            suggested_actions=[],
            confidence=0.0,
            analyzer_version=analyzer_version,
        )
        await self.repo.persist(
            chapter_id=chapter_id,
            analyzer_version=analyzer_version,
            summary=result.summary,
            suggested_actions=result.suggested_actions,
            confidence=result.confidence,
            input_snapshot={"error": error},
        )
        return result

    def _parse_response(self, text: str, analyzer_version: str) -> RootCauseResult:
        text = text.strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.MULTILINE)
        data = json.loads(text)
        return RootCauseResult(
            summary=data.get("summary", "[无 summary]"),
            suggested_actions=data.get("suggested_actions", []),
            confidence=float(data.get("confidence", 0.0)),
            analyzer_version=analyzer_version,
        )

    def _format_beat_cards(self, cards: list[BeatBoundaryCard]) -> str:
        if not cards:
            return "(none)"
        lines = []
        for c in cards:
            must = ", ".join(c.must_cover) if c.must_cover else "(no must_cover)"
            forbid = ", ".join(c.forbidden_materials) if c.forbidden_materials else "(no forbidden)"
            lines.append(f"  beat {c.beat_index}: must_cover=[{must}], forbidden=[{forbid}]")
        return "\n".join(lines)
