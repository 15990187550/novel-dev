from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import Entity, EntityRelationship
from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository


@dataclass
class GlobalConsistencyAuditResult:
    status: str
    confirm_required_items: list[dict[str, Any]] = field(default_factory=list)
    warning_items: list[dict[str, Any]] = field(default_factory=list)
    safe_items: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""

    def model_dump(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "confirm_required_items": self.confirm_required_items,
            "warning_items": self.warning_items,
            "safe_items": self.safe_items,
            "summary": self.summary,
        }


class GlobalConsistencyAuditService:
    """Manual/periodic cross-state audit for long-running novels."""

    RELATION_GROUPS = (
        {"ally", "friend", "盟友", "朋友", "同伴"},
        {"enemy", "rival", "敌人", "仇敌", "宿敌", "对手"},
    )

    def __init__(self, session: AsyncSession):
        self.session = session

    async def run(self, novel_id: str) -> GlobalConsistencyAuditResult:
        confirm: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        confirm.extend(await self._relationship_conflicts(novel_id))
        warnings.extend(await self._foreshadowing_warnings(novel_id))

        if confirm:
            return GlobalConsistencyAuditResult(
                status="confirm_required",
                confirm_required_items=confirm,
                warning_items=warnings,
                summary="全局一致性体检发现需要人工确认的问题。",
            )
        if warnings:
            return GlobalConsistencyAuditResult(
                status="warn",
                warning_items=warnings,
                summary="全局一致性体检发现可处理告警。",
            )
        return GlobalConsistencyAuditResult(status="pass", summary="全局一致性体检通过。")

    async def _relationship_conflicts(self, novel_id: str) -> list[dict[str, Any]]:
        result = await self.session.execute(
            select(EntityRelationship)
            .where(
                EntityRelationship.novel_id == novel_id,
                EntityRelationship.is_active == True,
            )
            .order_by(EntityRelationship.source_id, EntityRelationship.target_id, EntityRelationship.id)
        )
        relationships = list(result.scalars().all())
        entity_names = await self._entity_names(novel_id)
        by_pair: dict[tuple[str, str], list[EntityRelationship]] = {}
        for rel in relationships:
            by_pair.setdefault((rel.source_id, rel.target_id), []).append(rel)

        conflicts = []
        for (source_id, target_id), pair_rels in by_pair.items():
            relation_types = {str(rel.relation_type) for rel in pair_rels if rel.relation_type}
            if self._has_exclusive_relation_types(relation_types):
                conflicts.append({
                    "code": "mutually_exclusive_relationships",
                    "source_id": source_id,
                    "source_name": entity_names.get(source_id, source_id),
                    "target_id": target_id,
                    "target_name": entity_names.get(target_id, target_id),
                    "relation_types": sorted(relation_types),
                    "message": "同一实体关系同时存在盟友/敌对等互斥关系，需要确认当前有效关系。",
                })
        return conflicts

    async def _entity_names(self, novel_id: str) -> dict[str, str]:
        result = await self.session.execute(select(Entity).where(Entity.novel_id == novel_id))
        return {entity.id: entity.name for entity in result.scalars().all()}

    @classmethod
    def _has_exclusive_relation_types(cls, relation_types: set[str]) -> bool:
        matched = 0
        for group in cls.RELATION_GROUPS:
            if relation_types & group:
                matched += 1
        return matched >= 2

    async def _foreshadowing_warnings(self, novel_id: str) -> list[dict[str, Any]]:
        warnings = []
        for item in await ForeshadowingRepository(self.session).list_by_novel(novel_id):
            if item.回收状态 == "recovered" and not item.埋下_chapter_id:
                warnings.append({
                    "code": "foreshadowing_recovered_without_setup",
                    "foreshadowing_id": item.id,
                    "content": item.content,
                    "recovered_chapter_id": item.recovered_chapter_id,
                    "message": "伏笔已回收但缺少埋下章节，可能是未埋先收或导入数据不完整。",
                })
        return warnings
