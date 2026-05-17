from __future__ import annotations

from typing import Any

from novel_dev.schemas.quality import BeatBoundaryCard


class BeatBoundaryService:
    """Build deterministic beat-scoped constraints from a chapter plan."""

    _MATERIAL_KEYS = (
        "characters",
        "entities",
        "key_entities",
        "locations",
        "props",
        "foreshadowings",
        "foreshadowings_to_embed",
    )
    _FORBIDDEN_MATERIALS = [
        "不得执行后续 beat 的核心事件。",
        "不得添加章节计划外的重大角色、关键物件、关键证据、独立威胁实体或背景因果。",
        "桥接时不得新增命名实体、新能力规则、新证据链、新阵营身份或新的长期因果解释。",
        "不得改变信息释放顺序。",
    ]
    _REVEAL_BOUNDARY = (
        "只释放当前 beat 已规划的信息；允许用无名动作、短台词、环境声响、灯火、脚步、视线和已有实体反应"
        "补足当前目标所需的最小桥接细节；不得提前泄露后续核心信息。"
    )
    _BRIDGE_DETAILS = [
        "可用已有实体的短动作、视线、停顿、沉默或身体反应承接当前冲突。",
        "可用当前场景中的声音、灯火、门窗、脚步、风声等环境细节制造轻微危险信号。",
        "桥接细节必须服务当前 beat 的目标、阻力、选择或停点，不能变成新线索主线。",
    ]
    _DEFAULT_ENDING_POLICY = "在当前 beat 目标/冲突完成最小推进后停止，不延伸到后续 beat。"

    @classmethod
    def build_cards(cls, chapter_plan: dict[str, Any]) -> list[BeatBoundaryCard]:
        if not isinstance(chapter_plan, dict):
            return []

        beats = chapter_plan.get("beats")
        if not isinstance(beats, list):
            return []

        return [
            BeatBoundaryCard(
                beat_index=index,
                must_cover=cls._must_cover(beat),
                allowed_materials=cls._allowed_materials(chapter_plan, beat),
                allowed_bridge_details=list(cls._BRIDGE_DETAILS),
                forbidden_materials=list(cls._FORBIDDEN_MATERIALS),
                reveal_boundary=cls._REVEAL_BOUNDARY,
                ending_policy=cls._ending_policy(beat),
            )
            for index, beat in enumerate(beats)
        ]

    @classmethod
    def _must_cover(cls, beat: Any) -> list[str]:
        if not isinstance(beat, dict):
            text = cls._coerce_text(beat)
            return [text] if text else []

        items: list[str] = []
        for key in ("summary", "content", "goal", "conflict"):
            text = cls._coerce_text(beat.get(key))
            if text:
                items.append(text)
        return items

    @classmethod
    def _allowed_materials(cls, chapter_plan: dict[str, Any], beat: Any) -> list[str]:
        materials: list[str] = []
        for source in (chapter_plan, beat if isinstance(beat, dict) else {}):
            for key in cls._MATERIAL_KEYS:
                materials.extend(cls._coerce_materials(source.get(key)))
        return cls._dedupe(materials)

    @classmethod
    def _coerce_materials(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [text for item in value if (text := cls._coerce_text(item))]

    @staticmethod
    def _coerce_text(value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            for key in ("name", "title", "summary", "content"):
                text = value.get(key)
                if isinstance(text, str) and text.strip():
                    return text.strip()
        return ""

    @classmethod
    def _ending_policy(cls, beat: Any) -> str:
        if isinstance(beat, dict):
            for key in ("hook", "ending_hook"):
                text = cls._coerce_text(beat.get(key))
                if text:
                    return text
        return cls._DEFAULT_ENDING_POLICY

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped
