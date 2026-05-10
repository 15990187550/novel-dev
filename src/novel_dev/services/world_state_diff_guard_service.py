from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.relationship_repo import RelationshipRepository
from novel_dev.repositories.version_repo import EntityVersionRepository
from novel_dev.schemas.librarian import EntityUpdate, ExtractionResult


@dataclass
class WorldStateDiffResult:
    status: str
    safe_items: list[dict[str, Any]] = field(default_factory=list)
    warning_items: list[dict[str, Any]] = field(default_factory=list)
    confirm_required_items: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""

    def model_dump(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "safe_items": self.safe_items,
            "warning_items": self.warning_items,
            "confirm_required_items": self.confirm_required_items,
            "summary": self.summary,
        }


class WorldStateDiffGuardService:
    """Analyze librarian extraction before mutating long-term world state."""

    DEAD_MARKERS = ("已死亡", "死亡", "身亡", "阵亡", "尸身", "尸体")
    REVIVE_MARKERS = ("醒来", "开口", "复活", "活着", "站起", "行动", "出手")
    OWNER_KEYS = ("owner", "持有者", "归属", "主人")
    ALLY_RELATIONS = {"ally", "friend", "盟友", "朋友", "同伴"}
    ENEMY_RELATIONS = {"enemy", "敌人", "仇敌", "宿敌"}

    def __init__(self, session: AsyncSession):
        self.session = session
        self.entity_repo = EntityRepository(session)
        self.version_repo = EntityVersionRepository(session)
        self.relationship_repo = RelationshipRepository(session)
        self.foreshadowing_repo = ForeshadowingRepository(session)

    async def analyze(self, extraction: ExtractionResult, novel_id: str) -> WorldStateDiffResult:
        safe: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        confirm: list[dict[str, Any]] = []

        for update in extraction.concept_updates + extraction.character_updates:
            item = await self._analyze_entity_update(update, novel_id)
            if item is None:
                continue
            if item["severity"] == "confirm_required":
                confirm.append(item)
            elif item["severity"] == "warn":
                warnings.append(item)
            else:
                safe.append(item)
        for item in await self._analyze_relationships(extraction, novel_id):
            if item["severity"] == "confirm_required":
                confirm.append(item)
            else:
                warnings.append(item)
        warnings.extend(await self._analyze_foreshadowing_recovery(extraction, novel_id))

        if confirm:
            return WorldStateDiffResult(
                status="confirm_required",
                safe_items=safe,
                warning_items=warnings,
                confirm_required_items=confirm,
                summary="世界状态 diff 发现需要人工确认的长期记忆变更。",
            )
        if warnings:
            return WorldStateDiffResult(
                status="warn",
                safe_items=safe,
                warning_items=warnings,
                summary="世界状态 diff 发现可入库告警。",
            )
        return WorldStateDiffResult(
            status="safe",
            safe_items=safe,
            summary="世界状态 diff 未发现阻断项。",
        )

    async def _analyze_entity_update(self, update: EntityUpdate, novel_id: str) -> dict[str, Any] | None:
        entity = await self.entity_repo.get_by_id(update.entity_id)
        if entity is None:
            entity = await self.entity_repo.find_by_name(update.entity_id, novel_id=novel_id)
        if entity is None:
            return None

        latest = await self.version_repo.get_latest(entity.id)
        latest_state = latest.state if latest and isinstance(latest.state, dict) else {}
        extracted_state = update.state if isinstance(update.state, dict) else {}
        canonical_conflict = self._canonical_profile_conflict(entity.name, latest_state, extracted_state)
        if canonical_conflict:
            return canonical_conflict
        revive_conflict = self._dead_entity_revived(entity.name, latest_state, extracted_state)
        if revive_conflict:
            return revive_conflict
        owner_conflict = self._unique_item_owner_conflict(entity.name, latest_state, extracted_state)
        if owner_conflict:
            return owner_conflict

        return {
            "severity": "safe",
            "target_type": "entity",
            "entity_id": entity.id,
            "entity_name": entity.name,
            "operation": "update",
            "fields": sorted(str(key) for key in extracted_state.keys()),
        }

    @classmethod
    def _canonical_profile_conflict(
        cls,
        entity_name: str,
        latest_state: dict[str, Any],
        extracted_state: dict[str, Any],
    ) -> dict[str, Any] | None:
        proposed = extracted_state.get("canonical_profile")
        if not isinstance(proposed, dict):
            return None
        current = latest_state.get("canonical_profile") if isinstance(latest_state.get("canonical_profile"), dict) else {}
        conflicts = []
        for key, value in proposed.items():
            existing = current.get(key)
            if existing not in (None, "", value) and value not in (None, ""):
                conflicts.append({"field": key, "from": existing, "to": value})
        if not conflicts:
            return None
        return {
            "severity": "confirm_required",
            "code": "canonical_profile_overwrite",
            "target_type": "entity",
            "entity_name": entity_name,
            "message": f"{entity_name} 的固定档案将被覆盖，需要人工确认。",
            "conflicts": conflicts,
        }

    @classmethod
    def _dead_entity_revived(
        cls,
        entity_name: str,
        latest_state: dict[str, Any],
        extracted_state: dict[str, Any],
    ) -> dict[str, Any] | None:
        current_state = latest_state.get("current_state") if isinstance(latest_state.get("current_state"), dict) else {}
        old_condition = str(current_state.get("condition") or current_state.get("状态") or "")
        nested_current = extracted_state.get("current_state")
        nested_condition = (
            nested_current.get("condition") or nested_current.get("状态")
            if isinstance(nested_current, dict)
            else ""
        )
        new_condition = str(extracted_state.get("condition") or extracted_state.get("状态") or nested_condition or "")
        if not old_condition or not new_condition:
            return None
        if not any(marker in old_condition for marker in cls.DEAD_MARKERS):
            return None
        if not any(marker in new_condition for marker in cls.REVIVE_MARKERS):
            return None
        return {
            "severity": "confirm_required",
            "code": "dead_entity_revived",
            "target_type": "entity",
            "entity_name": entity_name,
            "message": f"{entity_name} 当前为死亡/尸身状态，但本章抽取结果试图改为可行动状态。",
            "field": "current_state.condition",
            "from": old_condition,
            "to": new_condition,
        }

    @classmethod
    def _unique_item_owner_conflict(
        cls,
        entity_name: str,
        latest_state: dict[str, Any],
        extracted_state: dict[str, Any],
    ) -> dict[str, Any] | None:
        current_state = latest_state.get("current_state") if isinstance(latest_state.get("current_state"), dict) else {}
        old_owner = cls._first_value(current_state, cls.OWNER_KEYS)
        new_owner = cls._first_value(extracted_state, cls.OWNER_KEYS)
        nested_current = extracted_state.get("current_state")
        if not new_owner and isinstance(nested_current, dict):
            new_owner = cls._first_value(nested_current, cls.OWNER_KEYS)
        if not old_owner or not new_owner or old_owner == new_owner:
            return None
        return {
            "severity": "confirm_required",
            "code": "unique_item_owner_conflict",
            "target_type": "entity",
            "entity_name": entity_name,
            "message": f"{entity_name} 的持有者将从 {old_owner} 改为 {new_owner}，需要确认是否发生转移。",
            "field": "current_state.owner",
            "from": old_owner,
            "to": new_owner,
        }

    @staticmethod
    def _first_value(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
        for key in keys:
            value = payload.get(key)
            if value not in (None, ""):
                return str(value)
        return ""

    async def _analyze_relationships(self, extraction: ExtractionResult, novel_id: str) -> list[dict[str, Any]]:
        items = []
        for rel in extraction.new_relationships:
            source = await self._resolve_entity(rel.source_entity_id, novel_id)
            target = await self._resolve_entity(rel.target_entity_id, novel_id)
            if not source or not target:
                continue
            existing = await self.relationship_repo.get_active(source.id, target.id, novel_id=novel_id)
            if not existing:
                continue
            if self._relation_polarity(existing.relation_type) and self._relation_polarity(rel.relation_type):
                if self._relation_polarity(existing.relation_type) != self._relation_polarity(rel.relation_type):
                    items.append({
                        "severity": "confirm_required",
                        "code": "relationship_polarity_flip",
                        "target_type": "relationship",
                        "source_id": source.id,
                        "source_name": source.name,
                        "target_id": target.id,
                        "target_name": target.name,
                        "from": existing.relation_type,
                        "to": rel.relation_type,
                        "message": "本章关系抽取将盟友/敌对关系反转，需要确认是否为真实剧情变化。",
                    })
        return items

    async def _resolve_entity(self, raw_ref: str, novel_id: str):
        entity = await self.entity_repo.get_by_id(raw_ref)
        if entity and entity.novel_id == novel_id:
            return entity
        return await self.entity_repo.find_by_name(raw_ref, novel_id=novel_id)

    @classmethod
    def _relation_polarity(cls, relation_type: str) -> str:
        relation = str(relation_type or "")
        if relation in cls.ALLY_RELATIONS:
            return "ally"
        if relation in cls.ENEMY_RELATIONS:
            return "enemy"
        return ""

    async def _analyze_foreshadowing_recovery(self, extraction: ExtractionResult, novel_id: str) -> list[dict[str, Any]]:
        warnings = []
        for fs_id in extraction.foreshadowings_recovered:
            fs = await self.foreshadowing_repo.get_by_id(fs_id)
            if not fs or fs.novel_id != novel_id:
                continue
            if fs.回收状态 == "recovered":
                warnings.append({
                    "severity": "warn",
                    "code": "foreshadowing_duplicate_recovery",
                    "target_type": "foreshadowing",
                    "foreshadowing_id": fs.id,
                    "content": fs.content,
                    "recovered_chapter_id": fs.recovered_chapter_id,
                    "message": "本章试图再次回收已回收伏笔，需检查是否重复回收。",
                })
        return warnings
