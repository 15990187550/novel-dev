from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


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


FORBIDDEN_TEMPLATE_FRAGMENTS = (
    "陆照",
    "李大牛",
    "王明月",
    "青云宗",
    "玄火盟",
    "血海殿",
    "瓦片",
    "凝气草",
    "职场霸凌还不用负法律责任",
    "搁前世",
    "藏书阁",
)


def validate_template_is_generic(template: GenreTemplate) -> None:
    payload = template.model_dump_json(ensure_ascii=False)
    found = [fragment for fragment in FORBIDDEN_TEMPLATE_FRAGMENTS if fragment in payload]
    if found:
        raise ValueError(f"genre template contains concrete story fragments: {found}")
