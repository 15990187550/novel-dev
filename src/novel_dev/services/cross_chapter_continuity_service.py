from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import Chapter, Entity, EntityVersion
from novel_dev.llm import llm_factory
from novel_dev.services.prompt_registry import PromptRegistry

logger = logging.getLogger(__name__)


@dataclass
class DriftIssue:
    """A single continuity drift issue detected between the current polished
    text and the prior chapters / entity history for a given entity.

    drift_type: one of name_drift / identity_drift / state_jump.
    severity: one of warn / block.
    """

    entity_name: str
    drift_type: str  # name_drift / identity_drift / state_jump
    severity: str  # warn / block
    evidence_quote: str
    suggested_fix: str


class CrossChapterContinuityService:
    """Build pre-write continuity constraints and detect cross-chapter drift.

    `build_pre_write_constraints` is deterministic and reads from
    `EntityVersion` only. `detect_drift` is LLM-based and compares the
    polished text of the current chapter against the most recent
    `post_write_window` chapters plus entity history.
    """

    def __init__(
        self,
        session: AsyncSession,
        pre_write_window: int = 3,
        post_write_window: int = 5,
    ):
        self.session = session
        self.pre_write_window = pre_write_window
        self.post_write_window = post_write_window

    async def build_pre_write_constraints(
        self,
        novel_id: str,
        entity_ids: list[str],
    ) -> str:
        """确定性:拉每个 entity 最新 EntityVersion,生成约束提示文本"""
        if not entity_ids:
            return ""
        result = await self.session.execute(
            select(Entity, EntityVersion)
            .join(EntityVersion, EntityVersion.entity_id == Entity.id)
            .where(Entity.id.in_(entity_ids))
            .order_by(EntityVersion.version.desc())
        )
        rows = result.all()
        # 去重,每个 entity 取最新 version
        latest: dict[str, tuple[Entity, EntityVersion]] = {}
        for ent, ver in rows:
            if ent.id not in latest:
                latest[ent.id] = (ent, ver)
        if not latest:
            return ""
        lines = ["### 实体连续性约束(本章不得违背)"]
        for ent, ver in latest.values():
            state = ver.state or {}
            pl = state.get("power_level", "?")
            ir = state.get("identity_role", "?")
            lines.append(f"- {ent.name}: 实力 = {pl}, 身份 = {ir}")
        return "\n".join(lines)

    async def detect_drift(
        self,
        novel_id: str,
        chapter_id: str,
        polished_text: str,
        entity_ids: list[str],
    ) -> list[DriftIssue]:
        """LLM 检测 3 类漂移: 名字漂移 / 身份漂移 / 状态阶跃.

        Returns an empty list on any failure (empty entity_ids, missing
        prompt, LLM error, invalid JSON). Errors are logged, never raised.
        """
        if not entity_ids:
            return []

        # 拉最近 N 章文本(排除当前章节)
        result = await self.session.execute(
            select(Chapter)
            .where(Chapter.novel_id == novel_id)
            .order_by(Chapter.chapter_number.desc())
            .limit(self.post_write_window)
        )
        recent = list(result.scalars().all())
        prior_texts = "\n\n".join([
            f"--- {c.id} ---\n{(c.polished_text or c.draft_text or '')[:1500]}"
            for c in recent
            if c.id != chapter_id
        ])

        # 拉实体最新版本信息
        ent_result = await self.session.execute(
            select(Entity, EntityVersion)
            .join(EntityVersion, EntityVersion.entity_id == Entity.id)
            .where(Entity.id.in_(entity_ids))
            .order_by(EntityVersion.version.desc())
        )
        entities_info: list[dict] = []
        seen: set[str] = set()
        for ent, ver in ent_result.all():
            if ent.id in seen:
                continue
            seen.add(ent.id)
            entities_info.append({
                "name": ent.name,
                "history_state": ver.state,
                "identity_role": (ver.state or {}).get("identity_role"),
            })

        # 取 prompt 模板
        try:
            reg = PromptRegistry(self.session)
            template = await reg.get_active("cross_chapter_drift")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "cross_chapter_drift_prompt_unavailable",
                extra={"error": str(exc)},
            )
            return []
        if not template:
            logger.warning("cross_chapter_drift_prompt_empty")
            return []

        # 用 str.replace 避免 JSON 模板中的花括号与 str.format 冲突
        prompt = template
        prompt = prompt.replace("{current_text}", (polished_text or "")[:5000])
        prompt = prompt.replace("{prior_texts}", (prior_texts or "")[:5000])
        prompt = prompt.replace(
            "{entities}",
            json.dumps(entities_info, ensure_ascii=False),
        )

        # 调 LLM
        try:
            client = llm_factory.get("RootCauseAnalyzer")
            from novel_dev.llm.models import ChatMessage

            response = await client.acomplete(
                [ChatMessage(role="user", content=prompt)]
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "cross_chapter_drift_llm_call_failed",
                extra={"error": str(exc)},
            )
            return []

        # 解析响应
        text = (response.text or "").strip()
        text = re.sub(
            r"^```(?:json)?\s*|\s*```$",
            "",
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError) as exc:
            logger.warning(
                "cross_chapter_drift_invalid_json",
                extra={"error": str(exc), "raw_text_prefix": text[:120]},
            )
            return []

        if not isinstance(parsed, list):
            logger.warning(
                "cross_chapter_drift_unexpected_payload_type",
                extra={"type": type(parsed).__name__},
            )
            return []

        issues: list[DriftIssue] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            issues.append(
                DriftIssue(
                    entity_name=str(item.get("entity_name", "")),
                    drift_type=str(item.get("drift_type", "")),
                    severity=str(item.get("severity", "warn")),
                    evidence_quote=str(item.get("evidence_quote", "")),
                    suggested_fix=str(item.get("suggested_fix", "")),
                )
            )
        return issues
