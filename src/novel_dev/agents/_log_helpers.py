from __future__ import annotations

import re
from typing import Any

from novel_dev.services.log_service import log_service


def preview_text(value: Any, limit: int = 120) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def log_agent_detail(
    novel_id: str,
    agent: str,
    message: str,
    *,
    node: str,
    task: str,
    metadata: dict[str, Any] | None = None,
    status: str = "succeeded",
    level: str = "info",
) -> None:
    log_service.add_log(
        novel_id,
        agent,
        message,
        level=level,
        event="agent.progress",
        status=status,
        node=node,
        task=task,
        metadata=metadata or {},
    )


def named_items(items: list[Any], *, limit: int = 8) -> list[dict[str, Any]]:
    result = []
    for item in items[:limit]:
        if isinstance(item, dict):
            result.append({
                "id": item.get("id") or item.get("entity_id") or item.get("chapter_id"),
                "name": item.get("name") or item.get("title") or item.get("content"),
                "preview": preview_text(item.get("preview") or item.get("summary") or item.get("content") or item.get("current_state")),
            })
            continue
        result.append({
            "id": getattr(item, "id", None) or getattr(item, "entity_id", None) or getattr(item, "chapter_id", None),
            "name": getattr(item, "name", None) or getattr(item, "title", None) or getattr(item, "content", None),
            "preview": preview_text(
                getattr(item, "summary", None)
                or getattr(item, "content", None)
                or getattr(item, "current_state", None)
            ),
        })
    return result
