from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from novel_dev.agents._llm_helpers import coerce_to_str_list, coerce_to_text


@dataclass(frozen=True)
class StyleContract:
    general: list[str] = field(default_factory=list)
    narrative: list[str] = field(default_factory=list)
    character: list[str] = field(default_factory=list)
    language: list[str] = field(default_factory=list)
    rhythm: list[str] = field(default_factory=list)
    anti_ai: list[str] = field(default_factory=list)
    self_check: list[str] = field(default_factory=list)

    @property
    def has_content(self) -> bool:
        return any((
            self.general,
            self.narrative,
            self.character,
            self.language,
            self.rhythm,
            self.anti_ai,
            self.self_check,
        ))

    def render_prompt_block(self) -> str:
        if not self.has_content:
            return ""
        sections = [
            ("总体风格", self.general),
            ("叙事规则", self.narrative),
            ("角色表达", self.character),
            ("语言质感", self.language),
            ("节奏控制", self.rhythm),
            ("反AI风险", self.anti_ai),
            ("输出前自检", self.self_check),
        ]
        lines = ["### 写法合同", "这些规则是可执行写法约束；优先保持角色、剧情和连续性自然成立。"]
        for title, values in sections:
            cleaned = _dedupe(values)
            if not cleaned:
                continue
            lines.append(f"#### {title}")
            lines.extend(f"- {value}" for value in cleaned)
        return "\n".join(lines)


class StyleContractCompiler:
    """Compile stored style_profile data into prompt-ready writing constraints."""

    @classmethod
    def compile(cls, profile: Any) -> StyleContract:
        if not isinstance(profile, dict) or not profile:
            return StyleContract()
        style_guide = _value_list(profile, "style_guide", "guide", "summary", "description")
        style_config = profile.get("style_config") if isinstance(profile.get("style_config"), dict) else {}
        return StyleContract(
            general=_dedupe(
                style_guide
                + _prefixed_value_list(style_config, "整体气质", "tone")
                + _prefixed_value_list(style_config, "视角取向", "perspective")
                + _value_list(style_config, "evolution_notes")
            ),
            narrative=_dedupe(
                _value_list(profile, "narrative_rules", "narrative", "story_rules")
                + _value_list(style_config, "narration_voice", "information_reveal", "scene_preferences", "writing_rules")
            ),
            character=_dedupe(
                _value_list(profile, "character_rules", "character", "dialogue_rules", "dialogue")
                + _value_list(style_config, "dialogue_style")
            ),
            language=_dedupe(
                _value_list(profile, "language_rules", "language", "prose_rules", "style_rules")
                + _value_list(style_config, "sentence_patterns", "rhetoric_devices", "vocabulary_preferences")
            ),
            rhythm=_dedupe(
                _value_list(profile, "rhythm_rules", "rhythm", "pacing_rules", "pacing")
                + _prefixed_value_list(style_config, "节奏取向", "pacing")
            ),
            anti_ai=_dedupe(
                _value_list(profile, "anti_ai_rules", "anti_ai", "antiAi", "forbidden_rules")
                + _value_list(style_config, "style_boundary")
            ),
            self_check=_dedupe(_value_list(profile, "self_check", "self_check_rules", "checklist")),
        )


def _value_list(mapping: dict[str, Any], *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        raw = mapping.get(key)
        if raw is None:
            continue
        if isinstance(raw, dict):
            added = 0
            for nested_key in (
                "summary",
                "rules",
                "keep",
                "avoid",
                "lines",
                "items",
            ):
                nested_values = _coerce_lines(raw.get(nested_key))
                values.extend(nested_values)
                added += len(nested_values)
            if added == 0:
                for nested_value in raw.values():
                    values.extend(_coerce_lines(nested_value))
        else:
            values.extend(_coerce_lines(raw))
    return values


def _prefixed_value_list(mapping: dict[str, Any], prefix: str, *keys: str) -> list[str]:
    values = _value_list(mapping, *keys)
    return [f"{prefix}: {value}" for value in values]


def _coerce_lines(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [coerce_to_text(item).strip() for item in coerce_to_str_list(value) if coerce_to_text(item).strip()]
    text = coerce_to_text(value).strip()
    if not text:
        return []
    lines = [line.strip("- ；;") for line in text.splitlines() if line.strip()]
    return [line for line in lines if line]


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = coerce_to_text(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result
