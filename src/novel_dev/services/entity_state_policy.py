from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EntityStatePolicyResult:
    state: dict[str, Any]
    events: list[dict[str, Any]] = field(default_factory=list)


class EntityStatePolicy:
    CANONICAL_ALIASES = {
        "name": "name",
        "姓名": "name",
        "身份": "identity_role",
        "身份定位": "identity_role",
        "identity_role": "identity_role",
        "protagonist_role": "identity_role",
        "出身": "origin",
        "origin": "origin",
        "background_core": "origin",
        "核心性格": "core_traits",
        "core_traits": "core_traits",
        "长期目标": "long_term_goal",
        "long_term_goal": "long_term_goal",
        "核心能力": "core_ability",
        "core_ability": "core_ability",
        "金手指": "cheat",
        "cheat": "cheat",
        "artifact_core": "cheat",
        "阵营归属": "faction_affiliation",
        "faction_affiliation": "faction_affiliation",
        "师承": "lineage",
        "lineage": "lineage",
    }

    CURRENT_ALIASES = {
        "位置": "location",
        "location": "location",
        "状态": "condition",
        "condition": "condition",
        "伤势": "injury",
        "injury": "injury",
        "境界": "cultivation_level",
        "cultivation_level": "cultivation_level",
        "职业": "occupation",
        "occupation": "occupation",
        "当前身份": "current_identity",
        "current_identity": "current_identity",
        "社会位置": "social_position",
        "social_position": "social_position",
        "情绪": "emotional_state",
        "emotional_state": "emotional_state",
        "认知状态": "knowledge_state",
        "knowledge_state": "knowledge_state",
        "持有物": "possessions",
        "possessions": "possessions",
    }

    OBSERVATION_KEYS = {"变化", "描述", "summary", "description"}

    @classmethod
    def normalize_update(
        cls,
        *,
        entity_type: str,
        entity_name: str,
        latest_state: dict[str, Any] | None,
        extracted_state: dict[str, Any] | str | None,
        chapter_id: str,
        diff_summary: dict[str, Any] | None,
    ) -> EntityStatePolicyResult:
        state, events = cls._normalize_latest_state(latest_state, entity_name)

        if not isinstance(extracted_state, dict):
            text = cls._stringify(extracted_state)
            if text:
                cls._append_observation(state, chapter_id, text)
                events.append(
                    {
                        "type": "unclassified_observed",
                        "field": "__raw__",
                        "written_to": f"observations.{chapter_id}",
                    }
                )
            return EntityStatePolicyResult(state=state, events=events)

        for raw_key, value in extracted_state.items():
            if value is None or value == "":
                continue
            if isinstance(raw_key, str) and raw_key.startswith("attitude_to_"):
                state["current_state"][raw_key] = value
                continue
            if raw_key in cls.OBSERVATION_KEYS:
                cls._append_observation(
                    state, chapter_id, f"{raw_key}: {cls._stringify(value)}"
                )
                events.append(
                    {
                        "type": "unclassified_observed",
                        "field": raw_key,
                        "written_to": f"observations.{chapter_id}",
                    }
                )
                continue
            if raw_key in cls.CURRENT_ALIASES:
                state["current_state"][cls.CURRENT_ALIASES[raw_key]] = value
                continue
            if raw_key in cls.CANONICAL_ALIASES:
                cls._apply_canonical_value(state, events, raw_key, value, chapter_id)
                continue
            cls._append_observation(
                state, chapter_id, f"{raw_key}: {cls._stringify(value)}"
            )
            events.append(
                {
                    "type": "unclassified_observed",
                    "field": raw_key,
                    "written_to": f"observations.{chapter_id}",
                }
            )

        return EntityStatePolicyResult(state=state, events=events)

    @classmethod
    def _normalize_latest_state(
        cls,
        latest_state: dict[str, Any] | None,
        entity_name: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        events: list[dict[str, Any]] = []
        latest = latest_state if isinstance(latest_state, dict) else {}
        if any(
            key in latest
            for key in (
                "canonical_profile",
                "current_state",
                "observations",
                "canonical_meta",
            )
        ):
            state = dict(latest)
            state["canonical_profile"] = dict(latest.get("canonical_profile") or {})
            state["current_state"] = dict(latest.get("current_state") or {})
            state["observations"] = cls._copy_observations(
                latest.get("observations") or {}
            )
            state["canonical_meta"] = dict(latest.get("canonical_meta") or {})
            cls._fold_legacy_keys(state, latest)
            if entity_name and not state["canonical_profile"].get("name"):
                state["canonical_profile"]["name"] = entity_name
            return state, events

        state = {
            "canonical_profile": {"name": entity_name} if entity_name else {},
            "current_state": {},
            "observations": {},
            "canonical_meta": {},
        }
        for raw_key, value in latest.items():
            if value is None or value == "":
                continue
            if raw_key in cls.CANONICAL_ALIASES:
                state["canonical_profile"][cls.CANONICAL_ALIASES[raw_key]] = value
            elif raw_key in cls.CURRENT_ALIASES:
                state["current_state"][cls.CURRENT_ALIASES[raw_key]] = value
            else:
                state["current_state"][raw_key] = value
        if latest:
            events.append({"type": "flat_state_normalized"})
        return state, events

    @classmethod
    def _fold_legacy_keys(
        cls, state: dict[str, Any], latest: dict[str, Any]
    ) -> None:
        structured_keys = {
            "canonical_profile",
            "current_state",
            "observations",
            "canonical_meta",
        }
        for raw_key, value in latest.items():
            if raw_key in structured_keys or value is None or value == "":
                continue
            if raw_key in cls.CANONICAL_ALIASES:
                canonical_key = cls.CANONICAL_ALIASES[raw_key]
                state["canonical_profile"].setdefault(canonical_key, value)
            elif raw_key in cls.CURRENT_ALIASES:
                current_key = cls.CURRENT_ALIASES[raw_key]
                state["current_state"].setdefault(current_key, value)

    @staticmethod
    def _copy_observations(observations: dict[str, Any]) -> dict[str, Any]:
        copied = {}
        for chapter_id, items in observations.items():
            copied[chapter_id] = list(items) if isinstance(items, list) else items
        return copied

    @classmethod
    def _apply_canonical_value(
        cls,
        state: dict[str, Any],
        events: list[dict[str, Any]],
        raw_key: str,
        value: Any,
        chapter_id: str,
    ) -> None:
        canonical_key = cls.CANONICAL_ALIASES[raw_key]
        existing = state["canonical_profile"].get(canonical_key)
        if existing in (None, ""):
            state["canonical_profile"][canonical_key] = value
            state["canonical_meta"][canonical_key] = {
                "source": "chapter_inferred",
                "chapter_id": chapter_id,
            }
            events.append(
                {
                    "type": "canonical_field_inferred",
                    "field": raw_key,
                    "canonical_field": canonical_key,
                    "value": value,
                }
            )
            return
        if existing == value:
            return

        target = cls._demotion_target(canonical_key)
        if target:
            state["current_state"][target] = value
            written_to = f"current_state.{target}"
        else:
            cls._append_observation(state, chapter_id, f"{raw_key}: {cls._stringify(value)}")
            written_to = f"observations.{chapter_id}"
        events.append(
            {
                "type": "canonical_conflict_demoted",
                "field": raw_key,
                "canonical_field": canonical_key,
                "from": existing,
                "to": value,
                "written_to": written_to,
            }
        )

    @staticmethod
    def _demotion_target(canonical_key: str) -> str | None:
        if canonical_key == "identity_role":
            return "social_position"
        return None

    @classmethod
    def _append_observation(
        cls, state: dict[str, Any], chapter_id: str, text: str
    ) -> None:
        if not text:
            return
        observations = state.setdefault("observations", {})
        items = observations.setdefault(chapter_id, [])
        if text not in items:
            items.append(text)

    @classmethod
    def _stringify(cls, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return "; ".join(
                f"{key}: {cls._stringify(item)}" for key, item in value.items()
            )
        if isinstance(value, list):
            return ", ".join(cls._stringify(item) for item in value)
        return str(value)
