from __future__ import annotations
import json
import logging
import re
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.llm import llm_factory
from novel_dev.repositories.imagery_inventory_repo import ImageryInventoryRepository

logger = logging.getLogger(__name__)


class ImageryInventoryService:
    """Extract imagery inventory from chapters and build avoidance lists.

    The service:
      * Calls an LLM to extract imagery items from a chapter and writes them
        to the ``ImageryInventory`` table.
      * Surfaces recent imagery (raw rows) via :meth:`get_recent`.
      * Aggregates recent imagery across chapters and returns a deterministic
        avoidance list that callers (e.g. ContextAgent) can inject into the
        writer prompt.
    """

    def __init__(
        self,
        session: AsyncSession,
        avoidance_top_n: int = 20,
        rows_per_chapter: int = 20,
    ) -> None:
        self.session = session
        self.repo = ImageryInventoryRepository(session)
        self.avoidance_top_n = avoidance_top_n
        # Heuristic: when fetching "the last N chapters" we pull N * rows_per_chapter
        # rows so aggregation has enough samples even for imagery-heavy chapters.
        self.rows_per_chapter = rows_per_chapter

    async def extract_and_store(
        self, novel_id: str, chapter_id: str, chapter_text: str,
    ) -> int:
        """Extract imagery from ``chapter_text`` via LLM and persist rows.

        Returns the number of rows written. On any LLM/parse failure it logs
        and returns 0 (graceful degradation; the pipeline should not fail
        because imagery extraction could not run).
        """
        # Lazy imports keep this module import-safe even if the LLM stack
        # is not fully configured (e.g. CLI tools, one-off scripts).
        from novel_dev.llm.models import ChatMessage
        from novel_dev.services.prompt_registry import PromptRegistry

        try:
            reg = PromptRegistry(self.session)
            template = await reg.get_active("imagery_extraction")
        except Exception as exc:
            logger.warning(
                "imagery_extraction_prompt_lookup_failed",
                extra={"novel_id": novel_id, "chapter_id": chapter_id, "error": str(exc)},
            )
            return 0

        if not template:
            logger.warning(
                "imagery_extraction_prompt_empty",
                extra={"novel_id": novel_id, "chapter_id": chapter_id},
            )
            return 0

        # Use string replace rather than ``str.format`` so the prompt can
        # contain literal ``{...}`` braces without escaping.
        snippet = chapter_text[:5000]
        prompt = template.replace("{chapter_text}", snippet)

        try:
            client = llm_factory.get("RootCauseAnalyzer")
            response = await client.acomplete(
                [ChatMessage(role="user", content=prompt)]
            )
        except Exception as exc:
            logger.warning(
                "imagery_extraction_llm_failed",
                extra={
                    "novel_id": novel_id, "chapter_id": chapter_id,
                    "error": str(exc),
                },
            )
            return 0

        try:
            text = _strip_code_fence(response.text)
            items = json.loads(text)
        except Exception as exc:
            logger.warning(
                "imagery_extraction_parse_failed",
                extra={
                    "novel_id": novel_id, "chapter_id": chapter_id,
                    "error": str(exc),
                    "raw_preview": (response.text or "")[:200],
                },
            )
            return 0

        if not isinstance(items, list):
            logger.warning(
                "imagery_extraction_not_a_list",
                extra={"novel_id": novel_id, "chapter_id": chapter_id},
            )
            return 0

        written = 0
        for raw in items:
            if not isinstance(raw, dict):
                continue
            item = raw.get("item")
            item_type = raw.get("item_type")
            if not item or not item_type:
                continue
            try:
                freq = int(raw.get("frequency_in_chapter") or 1)
            except (TypeError, ValueError):
                freq = 1
            try:
                await self.repo.create(
                    novel_id=novel_id,
                    chapter_id=chapter_id,
                    item=str(item),
                    item_type=str(item_type),
                    frequency_in_chapter=freq,
                )
                written += 1
            except Exception as exc:
                logger.warning(
                    "imagery_extraction_row_insert_failed",
                    extra={
                        "novel_id": novel_id, "chapter_id": chapter_id,
                        "item": item, "error": str(exc),
                    },
                )
                continue

        logger.info(
            "imagery_extraction_done",
            extra={
                "novel_id": novel_id, "chapter_id": chapter_id,
                "rows_written": written,
            },
        )
        return written

    async def get_recent(
        self, novel_id: str, window: int = 5,
    ) -> List:
        """Return the recent imagery rows covering roughly the last ``window`` chapters."""
        limit = max(1, int(window) * self.rows_per_chapter)
        return await self.repo.get_recent(novel_id, limit=limit)

    async def build_avoidance_list(
        self, novel_id: str, current_chapter_id: str, window: int = 5,
    ) -> str:
        """Aggregate recent imagery and format a top-N avoidance list.

        The output is deterministic (no LLM) and suitable for injection into
        a Writer prompt as ``avoid_imagery``.
        """
        items = await self.get_recent(novel_id, window=window)
        # Drop rows that belong to the chapter we're currently writing so
        # the writer is told to avoid imagery that was just used.
        items = [i for i in items if i.chapter_id != current_chapter_id]
        if not items:
            return ""

        agg: dict = {}
        for it in items:
            key = (it.item, it.item_type)
            entry = agg.get(key)
            if entry is None:
                entry = {"item": it.item, "type": it.item_type, "count": 0, "freq_sum": 0}
                agg[key] = entry
            entry["count"] += 1
            entry["freq_sum"] += int(it.frequency_in_chapter or 0)

        ranked = sorted(
            agg.values(),
            key=lambda x: (x["count"] * x["freq_sum"], x["freq_sum"], x["count"]),
            reverse=True,
        )
        top = ranked[: self.avoidance_top_n]

        lines = [f"### 本章应避免意象(最近 {window} 章已多次使用)"]
        for it in top:
            lines.append(
                f"- {it['item']}({it['type']},{it['count']} 章 × {it['freq_sum']} 次)"
            )
        return "\n".join(lines)


def _strip_code_fence(text: str) -> str:
    """Strip a leading/trailing ```json ... ``` fence if present."""
    if not text:
        return ""
    cleaned = text.strip()
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$", "", cleaned,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    return cleaned.strip()