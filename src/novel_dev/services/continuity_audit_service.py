from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContinuityAuditResult:
    status: str
    blocking_items: list[dict[str, Any]] = field(default_factory=list)
    warning_items: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""

    def model_dump(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "blocking_items": self.blocking_items,
            "warning_items": self.warning_items,
            "summary": self.summary,
        }


class ContinuityAuditService:
    """Deterministic continuity checks before world-state ingestion."""

    DEAD_MARKERS = ("已死亡", "死亡", "身亡", "阵亡", "尸身", "尸体")
    LIVING_ACTION_MARKERS = ("醒来", "开口", "说出", "走来", "站起", "活着", "出手")
    IDENTITY_DRIFT_MARKERS = ("魔门圣子", "魔教圣子", "血煞盟少主", "妖族少主")

    @classmethod
    def audit_chapter(cls, polished_text: str, chapter_context: dict[str, Any]) -> ContinuityAuditResult:
        blocking: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        text = polished_text or ""

        for entity in cls._active_entities(chapter_context):
            name = str(entity.get("name") or "").strip()
            state = str(entity.get("current_state") or "")
            if not name or name not in text:
                continue
            if cls._looks_dead(state) and cls._has_living_action_near_name(text, name):
                blocking.append({
                    "code": "dead_entity_acted",
                    "message": f"{name} 当前状态为死亡/尸身，但成稿写成了可行动角色。",
                    "detail": {"entity": name, "current_state": state[:240]},
                })
            identity_role = cls._canonical_identity_role(entity)
            drift_marker = cls._identity_drift_marker(text, name, identity_role)
            if drift_marker:
                blocking.append({
                    "code": "canonical_identity_drift",
                    "message": f"{name} 的固定身份是「{identity_role}」，但成稿写成「{drift_marker}」。",
                    "detail": {"entity": name, "canonical_identity_role": identity_role, "matched_text": drift_marker},
                })

        story_contract = chapter_context.get("story_contract") or {}
        carry_terms = story_contract.get("must_carry_forward") or story_contract.get("key_clues") or []
        missing_terms = [
            str(term)
            for term in carry_terms[:8]
            if str(term).strip() and str(term).strip() not in text
        ]
        if missing_terms:
            warnings.append({
                "code": "story_contract_terms_missing",
                "message": "成稿没有承接部分故事契约关键词。",
                "detail": {"missing_terms": missing_terms},
            })

        if blocking:
            return ContinuityAuditResult(
                status="block",
                blocking_items=blocking,
                warning_items=warnings,
                summary="连续性审计发现硬冲突，停止归档和世界状态入库。",
            )
        if warnings:
            return ContinuityAuditResult(
                status="warn",
                warning_items=warnings,
                summary="连续性审计发现可接受告警，允许继续但需要展示诊断。",
            )
        return ContinuityAuditResult(status="pass", summary="连续性审计通过。")

    @staticmethod
    def _active_entities(chapter_context: dict[str, Any]) -> list[dict[str, Any]]:
        entities = chapter_context.get("active_entities") or []
        return [item for item in entities if isinstance(item, dict)]

    @classmethod
    def _looks_dead(cls, state: str) -> bool:
        return any(marker in state for marker in cls.DEAD_MARKERS)

    @staticmethod
    def _canonical_identity_role(entity: dict[str, Any]) -> str:
        memory = entity.get("memory_snapshot") if isinstance(entity.get("memory_snapshot"), dict) else {}
        canonical = memory.get("canonical_profile") if isinstance(memory.get("canonical_profile"), dict) else {}
        return str(canonical.get("identity_role") or "").strip()

    @classmethod
    def _identity_drift_marker(cls, text: str, name: str, identity_role: str) -> str:
        if not identity_role:
            return ""
        if any(marker in identity_role for marker in cls.IDENTITY_DRIFT_MARKERS):
            return ""
        start = 0
        while True:
            index = text.find(name, start)
            if index < 0:
                return ""
            window = text[index:index + 80]
            for marker in cls.IDENTITY_DRIFT_MARKERS:
                if marker in window and marker not in identity_role:
                    return marker
            start = index + len(name)

    @classmethod
    def _has_living_action_near_name(cls, text: str, name: str) -> bool:
        start = 0
        while True:
            index = text.find(name, start)
            if index < 0:
                return False
            window = text[index:index + 80]
            if any(marker in window for marker in cls.LIVING_ACTION_MARKERS):
                return True
            start = index + len(name)
