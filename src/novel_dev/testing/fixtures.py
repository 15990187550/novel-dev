from __future__ import annotations

from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml


BUILTIN_FIXTURE = "fixtures/minimal_novel.yaml"


@dataclass(frozen=True)
class GenerationFixture:
    dataset: str
    title: str
    initial_setting_idea: str
    minimum_chapter_chars: int
    watched_terms: list[str] = field(default_factory=list)


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Fixture YAML must contain a mapping: {path}")
    return data


def _from_data(data: dict[str, Any]) -> GenerationFixture:
    watched_terms = data.get("watched_terms", [])
    if watched_terms is None:
        watched_terms = []
    if not isinstance(watched_terms, list):
        raise ValueError("Fixture watched_terms must be a list.")

    return GenerationFixture(
        dataset=str(data["dataset"]),
        title=str(data["title"]),
        initial_setting_idea=str(data["initial_setting_idea"]),
        minimum_chapter_chars=int(data["minimum_chapter_chars"]),
        watched_terms=[str(term) for term in watched_terms],
    )


def load_generation_fixture(source: str) -> GenerationFixture:
    if source == "minimal_builtin":
        resource = files("novel_dev.testing").joinpath(BUILTIN_FIXTURE)
        return _from_data(_read_yaml(resource))

    path = Path(source)
    if path.is_dir():
        return _from_data(_read_yaml(path / "fixture.yaml"))
    if path.is_file():
        return _from_data(_read_yaml(path))

    raise ValueError(f"Unknown generation fixture source: {source}")
