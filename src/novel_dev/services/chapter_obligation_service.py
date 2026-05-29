from __future__ import annotations

from typing import Any

from novel_dev.services.story_quality_service import StoryQualityService


class ChapterObligationService:
    """Build a reusable chapter obligation contract from existing planning assets."""

    CONTRACT_KEYS = ("must_hit_now", "must_preserve", "can_defer", "forbidden_crossings")

    @classmethod
    def build_from_context(cls, context: Any) -> dict[str, list[str]]:
        contract = {key: [] for key in cls.CONTRACT_KEYS}
        story_contract = cls._get(context, "story_contract", {}) or {}
        if isinstance(story_contract, dict):
            contract["must_preserve"].extend(cls._string_list(
                story_contract.get("must_carry_forward") or story_contract.get("key_clues") or []
            ))

        for card in cls._get(context, "writing_cards", []) or []:
            contract["must_hit_now"].extend(cls._card_values(
                card,
                "objective",
                "conflict",
                "turning_point",
                "stake",
                "required_payoffs",
                "ending_hook",
                "ending_driver_candidates",
            ))
            contract["must_preserve"].extend(cls._card_values(
                card,
                "required_entities",
                "required_facts",
                "canonical_constraints",
                "continuity_requirements",
            ))
            contract["can_defer"].extend(cls._card_values(card, "next_chapter_pressure"))
            contract["forbidden_crossings"].extend(cls._card_values(card, "forbidden_future_events"))

        chapter_plan = cls._get(context, "chapter_plan", None)
        for card in cls._get(chapter_plan, "beat_boundary_cards", []) or []:
            contract["must_hit_now"].extend(cls._string_list(cls._get(card, "must_cover", [])))
            contract["must_preserve"].extend(cls._string_list(cls._get(card, "allowed_materials", [])))
            contract["can_defer"].extend(cls._string_list(cls._get(card, "allowed_bridge_details", [])))
            contract["forbidden_crossings"].extend(cls._string_list(cls._get(card, "forbidden_materials", [])))
            reveal_boundary = str(cls._get(card, "reveal_boundary", "") or "").strip()
            if reveal_boundary:
                contract["forbidden_crossings"].append(reveal_boundary)

        return {key: cls._dedupe(cls._sanitize_values(values)) for key, values in contract.items()}

    @classmethod
    def render_prompt_block(cls, contract: dict[str, Any] | None) -> str:
        if not isinstance(contract, dict):
            return ""
        sections = [
            ("must_hit_now", "本章必须让读者看见"),
            ("must_preserve", "本章必须保持不变"),
            ("can_defer", "可以延后处理"),
            ("forbidden_crossings", "不得越界确认"),
        ]
        lines: list[str] = ["### 章节义务合同"]
        for key, label in sections:
            values = cls._string_list(contract.get(key, []))
            if values:
                lines.append(f"- {label}: " + "；".join(values[:8]))
        if len(lines) == 1:
            return ""
        lines.append(
            "- 使用方式: 这些是章节职责边界，不是固定桥段模板；优先用当前场景里最自然的行动、结果、关系变化或信息变化完成。"
        )
        return "\n".join(lines)

    @staticmethod
    def _get(source: Any, key: str, default: Any = None) -> Any:
        if isinstance(source, dict):
            return source.get(key, default)
        return getattr(source, key, default)

    @classmethod
    def _card_values(cls, card: Any, *keys: str) -> list[str]:
        values: list[str] = []
        for key in keys:
            value = cls._get(card, key, None)
            values.extend(cls._string_list(value))
        return values

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            items = [value]
        elif isinstance(value, (list, tuple, set)):
            items = list(value)
        else:
            items = [value]
        return [str(item).strip() for item in items if str(item or "").strip()]

    @classmethod
    def _sanitize_values(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            text = StoryQualityService.sanitize_prompt_text(value)
            if not text or StoryQualityService._looks_like_abstract_ending_driver(text):
                continue
            cleaned.append(text)
        return cleaned

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result
