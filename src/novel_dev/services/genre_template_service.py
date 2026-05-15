from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import NovelState
from novel_dev.genres.defaults import BUILTIN_TEMPLATES, default_genre
from novel_dev.genres.models import GenreTemplate, NovelGenre, ResolvedGenreTemplate, validate_template_is_generic
from novel_dev.repositories.genre_repo import GenreRepository


class GenreTemplateService:
    def __init__(self, session: AsyncSession | None):
        self.session = session

    async def resolve(self, novel_id: str, agent_name: str, task_name: str = "*") -> ResolvedGenreTemplate:
        genre = await self.resolve_novel_genre(novel_id)
        templates, warnings = await self._select_templates(genre, agent_name, task_name)
        return self._merge_templates(genre, templates, warnings)

    async def resolve_novel_genre(self, novel_id: str) -> NovelGenre:
        if self.session is None:
            return default_genre()

        result = await self.session.execute(select(NovelState).where(NovelState.novel_id == novel_id))
        state = result.scalar_one_or_none()
        if state is None:
            return default_genre()

        raw_genre = (state.checkpoint_data or {}).get("genre")
        if not isinstance(raw_genre, dict):
            return default_genre()

        default = default_genre()
        try:
            return NovelGenre(
                primary_slug=raw_genre.get("primary_slug") or default.primary_slug,
                primary_name=raw_genre.get("primary_name") or default.primary_name,
                secondary_slug=raw_genre.get("secondary_slug") or default.secondary_slug,
                secondary_name=raw_genre.get("secondary_name") or default.secondary_name,
            )
        except ValueError:
            return default

    async def _select_templates(
        self,
        genre: NovelGenre,
        agent_name: str,
        task_name: str,
    ) -> tuple[list[GenreTemplate], list[str]]:
        templates: list[GenreTemplate] = list(BUILTIN_TEMPLATES)
        if self.session is not None:
            templates.extend(await GenreRepository(self.session).list_template_overrides())

        selected = [
            template
            for template in templates
            if template.enabled
            and self._matches_layer(template, genre)
            and self._matches_specificity(template, agent_name, task_name)
        ]
        selected.sort(
            key=lambda template: (
                self._layer_rank(template),
                self._specificity_rank(template),
                self._source_rank(template),
                template.version,
            )
        )

        warnings: list[str] = []
        if not self._is_default_compat_genre(genre):
            if not any(template.scope == "primary" for template in selected):
                warnings.append(f"genre_template_missing:primary:{genre.primary_slug}")
            if not any(template.scope == "secondary" for template in selected):
                warnings.append(f"genre_template_missing:secondary:{genre.secondary_slug}")

        return selected, warnings

    def _merge_templates(
        self,
        genre: NovelGenre,
        templates: list[GenreTemplate],
        warnings: list[str] | None = None,
    ) -> ResolvedGenreTemplate:
        prompt_blocks: dict[str, list[str]] = {}
        quality_config: dict[str, Any] = {}
        matched_templates: list[str] = []

        for template in templates:
            validate_template_is_generic(template)
            matched_templates.append(self._template_id(template))

            for name, values in template.prompt_blocks.items():
                if template.merge_policy.get(name) == "replace":
                    prompt_blocks[name] = self._dedupe_list(values)
                else:
                    prompt_blocks[name] = self._dedupe_list([*prompt_blocks.get(name, []), *values])

            quality_config = self._deep_merge(quality_config, template.quality_config)

        return ResolvedGenreTemplate(
            genre=genre,
            prompt_blocks=prompt_blocks,
            quality_config=quality_config,
            matched_templates=matched_templates,
            warnings=list(warnings or []),
        )

    def merge_templates_for_test(self, raw_templates: list[dict[str, Any]]) -> ResolvedGenreTemplate:
        templates = [
            GenreTemplate(
                scope=raw.get("scope", "global"),
                category_slug=raw.get("category_slug"),
                parent_slug=raw.get("parent_slug"),
                agent_name=raw.get("agent_name", "*"),
                task_name=raw.get("task_name", "*"),
                prompt_blocks=raw.get("prompt_blocks", {}),
                quality_config=raw.get("quality_config", {}),
                merge_policy=raw.get("merge_policy", {}),
                enabled=raw.get("enabled", True),
                version=raw.get("version", 1),
                source=raw.get("source", "builtin"),
            )
            for raw in raw_templates
        ]
        return self._merge_templates(default_genre(), templates, [])

    def _matches_layer(self, template: GenreTemplate, genre: NovelGenre) -> bool:
        if template.scope == "global":
            return True
        if template.scope == "primary":
            return template.category_slug == genre.primary_slug
        return template.category_slug == genre.secondary_slug and template.parent_slug == genre.primary_slug

    def _matches_specificity(self, template: GenreTemplate, agent_name: str, task_name: str) -> bool:
        return template.agent_name in {"*", agent_name} and template.task_name in {"*", task_name}

    def _layer_rank(self, template: GenreTemplate) -> int:
        return {"global": 0, "primary": 1, "secondary": 2}[template.scope]

    def _specificity_rank(self, template: GenreTemplate) -> int:
        if template.agent_name == "*" and template.task_name == "*":
            return 0
        if template.agent_name != "*" and template.task_name == "*":
            return 1
        if template.agent_name == "*" and template.task_name != "*":
            return 2
        return 3

    def _source_rank(self, template: GenreTemplate) -> int:
        return 0 if template.source == "builtin" else 1

    def _is_default_compat_genre(self, genre: NovelGenre) -> bool:
        default = default_genre()
        return genre.primary_slug == default.primary_slug and genre.secondary_slug == default.secondary_slug

    def _template_id(self, template: GenreTemplate) -> str:
        slug = template.category_slug if template.category_slug is not None else "*"
        return f"{template.source}:{template.scope}:{slug}:{template.agent_name}:{template.task_name}:v{template.version}"

    def _deep_merge(self, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(base)
        for key, value in override.items():
            if key in merged:
                merged[key] = self._merge_value(merged[key], value)
            else:
                merged[key] = deepcopy(value)
        return merged

    def _merge_value(self, base: Any, override: Any) -> Any:
        if isinstance(base, dict) and isinstance(override, dict):
            return self._deep_merge(base, override)
        if isinstance(base, list) and isinstance(override, list):
            return self._dedupe_list([*base, *override])
        return deepcopy(override)

    def _dedupe_list(self, values: list[Any]) -> list[Any]:
        deduped: list[Any] = []
        for value in values:
            if value not in deduped:
                deduped.append(deepcopy(value))
        return deduped
