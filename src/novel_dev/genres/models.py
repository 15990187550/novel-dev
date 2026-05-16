from __future__ import annotations

import re
from typing import Any, Literal, get_args

from pydantic import BaseModel, Field, field_validator, model_validator


def _validate_slug(value: str) -> str:
    normalized = value.strip()
    if not re.fullmatch(r"[a-z][a-z0-9_]*", normalized):
        raise ValueError("slug must be lowercase snake_case")
    return normalized


PromptBlockName = Literal[
    "role_rules",
    "source_rules",
    "setting_rules",
    "structure_rules",
    "prose_rules",
    "forbidden_rules",
    "quality_rules",
    "output_rules",
]
PROMPT_BLOCK_NAMES = set(get_args(PromptBlockName))


class GenreCategory(BaseModel):
    slug: str
    name: str
    level: Literal[1, 2]
    parent_slug: str | None = None
    description: str = ""
    sort_order: int = 0
    enabled: bool = True
    source: Literal["builtin", "db"] = "builtin"

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        return _validate_slug(value)

    @field_validator("parent_slug")
    @classmethod
    def validate_parent_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_slug(value)


class NovelGenre(BaseModel):
    primary_slug: str
    primary_name: str
    secondary_slug: str
    secondary_name: str

    @field_validator("primary_slug", "secondary_slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        return _validate_slug(value)


class GenreTemplate(BaseModel):
    scope: Literal["global", "primary", "secondary"]
    category_slug: str | None = None
    parent_slug: str | None = None
    agent_name: str = "*"
    task_name: str = "*"
    prompt_blocks: dict[str, list[str]] = Field(default_factory=dict)
    quality_config: dict[str, Any] = Field(default_factory=dict)
    merge_policy: dict[str, Literal["append", "replace"]] = Field(default_factory=dict)
    enabled: bool = True
    version: int = 1
    source: Literal["builtin", "db"] = "builtin"

    @field_validator("category_slug", "parent_slug")
    @classmethod
    def validate_optional_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_slug(value)

    @field_validator("prompt_blocks")
    @classmethod
    def validate_prompt_block_names(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        unknown = sorted(key for key in value if key not in PROMPT_BLOCK_NAMES)
        if unknown:
            raise ValueError(f"unknown prompt block names: {unknown}")
        return value

    @model_validator(mode="after")
    def validate_scope_structure(self) -> GenreTemplate:
        if self.scope == "global":
            if self.category_slug is not None or self.parent_slug is not None:
                raise ValueError("global templates must not define category_slug or parent_slug")
        elif self.scope == "primary":
            if self.category_slug is None:
                raise ValueError("primary templates must define category_slug")
            if self.parent_slug is not None:
                raise ValueError("primary templates must not define parent_slug")
        elif self.scope == "secondary":
            if self.category_slug is None or self.parent_slug is None:
                raise ValueError("secondary templates must define category_slug and parent_slug")
        return self


class ResolvedGenreTemplate(BaseModel):
    genre: NovelGenre
    prompt_blocks: dict[str, list[str]] = Field(default_factory=dict)
    quality_config: dict[str, Any] = Field(default_factory=dict)
    matched_templates: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def render_prompt_block(self, *names: str) -> str:
        lines: list[str] = []
        for name in names:
            values = self.prompt_blocks.get(name, [])
            if values:
                title = name.replace("_", " ")
                lines.append(f"### Genre {title}")
                lines.extend(f"- {item}" for item in values if item.strip())
        return "\n".join(lines).strip()


_DIALOGUE_OR_QUOTED_LINE_PATTERN = re.compile(r"([：:][\"“「『])|([说问道][：:][\"“「『])")
_SERIAL_CONTENT_MARKER_PATTERN = re.compile(r"第[一二三四五六七八九十百千万0-9]+[章节卷幕]")
_EXTERNAL_IP_TITLE_PATTERN = re.compile(r"《[^》]{2,}》")
_CONCRETE_ENTITY_CONTEXT_PATTERN = re.compile(
    r"(?:默认|固定|指定|预设|示例|样例|名为|叫做|设为|地点是|道具是|组织是|势力是)"
    r"[^。；;，,\n]{0,20}?"
    r"([一-龥]{2,10}(?:宗|盟|殿|阁|宫|城|国|朝|府|堂|会|帮|派|院|司|队|团|"
    r"草|丹|剑|刀|珠|印|符|鼎|炉|诀|经|功)(?![一-龥]))"
)


def _template_text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        values: list[str] = []
        for item in value.values():
            values.extend(_template_text_values(item))
        return values
    if isinstance(value, list | tuple | set):
        values = []
        for item in value:
            values.extend(_template_text_values(item))
        return values
    return []


def _template_payload_for_generic_validation(template: GenreTemplate) -> dict[str, Any]:
    return {
        "prompt_blocks": template.prompt_blocks,
        "quality_config": template.quality_config,
        "merge_policy": template.merge_policy,
    }


def validate_template_is_generic(template: GenreTemplate) -> None:
    violations: list[str] = []
    for value in _template_text_values(_template_payload_for_generic_validation(template)):
        if _DIALOGUE_OR_QUOTED_LINE_PATTERN.search(value):
            violations.append("dialogue_or_scene_line")
        if _SERIAL_CONTENT_MARKER_PATTERN.search(value):
            violations.append("chapter_or_volume_marker")
        if _EXTERNAL_IP_TITLE_PATTERN.search(value):
            violations.append("external_ip_title")
        concrete_entity_match = _CONCRETE_ENTITY_CONTEXT_PATTERN.search(value)
        if concrete_entity_match is not None:
            violations.append(f"concrete_named_entity:{concrete_entity_match.group(1)}")

    if violations:
        unique_violations = sorted(set(violations))
        raise ValueError(f"genre template must stay generic: {unique_violations}")
