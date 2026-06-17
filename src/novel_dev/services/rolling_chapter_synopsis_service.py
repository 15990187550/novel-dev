from __future__ import annotations
import json
import logging
import re
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.llm import llm_factory
from novel_dev.db.models import NovelState, Chapter, ChapterSynopsis
from novel_dev.repositories.chapter_synopsis_repo import ChapterSynopsisRepository
from novel_dev.services.prompt_registry import PromptRegistry

logger = logging.getLogger(__name__)


class RollingChapterSynopsisService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ChapterSynopsisRepository(session)

    async def should_update(
        self, novel_id: str, chapter_id: str, event_type: str, event_payload: dict,
    ) -> bool:
        if event_type == "quality_block":
            return event_payload.get("gate_status") == "block"
        if event_type == "entity_state_change":
            return bool(event_payload.get("is_important"))
        if event_type in ("entity_introduced", "entity_removed"):
            return True
        return False

    async def update(
        self, novel_id: str, chapter_id: str, trigger_event: dict,
    ) -> ChapterSynopsis:
        prev = await self.repo.get_latest(novel_id)
        prev_synopsis = prev.narrative_prose if prev else ""

        reg = PromptRegistry(self.session)
        try:
            template = await reg.get_active("rolling_synopsis")
            if not template:
                template = "{prev_synopsis} | {new_chapter_summaries} | {trigger_event}"
        except RuntimeError:
            template = "{prev_synopsis} | {new_chapter_summaries} | {trigger_event}"

        ch_result = await self.session.execute(
            select(Chapter).where(Chapter.id == chapter_id)
        )
        ch = ch_result.scalar_one_or_none()
        new_chapter_summary = ch.title if ch else chapter_id
        prompt = template.replace("{prev_synopsis}", prev_synopsis or "(无前情摘要)")
        prompt = prompt.replace("{new_chapter_summaries}", f"- {chapter_id}: {new_chapter_summary}")
        prompt = prompt.replace("{trigger_event}", json.dumps(trigger_event, ensure_ascii=False))

        client = llm_factory.get("RootCauseAnalyzer")
        from novel_dev.llm.models import ChatMessage
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        parsed = self._parse_response(response.text)

        syn = await self.repo.create(
            novel_id=novel_id,
            chapter_range_start=(prev.chapter_range_end + 1) if prev else 1,
            chapter_range_end=int(chapter_id.split("_")[-1]) if "_" in chapter_id else 1,
            narrative_prose=parsed["narrative_prose"],
            structured_json=parsed["structured_json"],
            trigger_event=trigger_event,
            prev_synopsis_id=prev.id if prev else None,
        )
        await self.cache_to_checkpoint(novel_id, syn)
        return syn

    async def cache_to_checkpoint(self, novel_id: str, syn: ChapterSynopsis) -> None:
        result = await self.session.execute(
            select(NovelState).where(NovelState.novel_id == novel_id)
        )
        ns = result.scalar_one_or_none()
        if not ns:
            return
        cp = dict(ns.checkpoint_data or {})
        cp["rolling_synopsis_cache"] = {
            "id": syn.id,
            "chapter_range": [syn.chapter_range_start, syn.chapter_range_end],
            "narrative_prose": syn.narrative_prose,
            "structured_json": syn.structured_json,
        }
        ns.checkpoint_data = cp
        await self.session.flush()

    async def get_latest(self, novel_id: str) -> Optional[ChapterSynopsis]:
        return await self.repo.get_latest(novel_id)

    @staticmethod
    def _parse_response(text: str) -> dict:
        text = text.strip()
        text = re.sub(
            r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.MULTILINE
        )
        return json.loads(text)
