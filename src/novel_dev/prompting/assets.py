from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


RenderFn = Callable[[dict[str, Any]], str]


@dataclass(frozen=True)
class PromptContextPolicy:
    required: tuple[str, ...] = ()
    preferred: tuple[str, ...] = ()
    droppable: tuple[str, ...] = ()
    max_chars: int | None = None


@dataclass(frozen=True)
class PromptAsset:
    id: str
    version: str
    task: str
    mode: str
    context_policy: PromptContextPolicy = field(default_factory=PromptContextPolicy)
    render: RenderFn | None = None

    def render_text(self, payload: dict[str, Any] | None = None) -> str:
        if self.render is None:
            return ""
        return self.render(payload or {})


class PromptAssetRegistry:
    def __init__(self) -> None:
        self._assets: dict[str, PromptAsset] = {}

    def register(self, asset: PromptAsset) -> PromptAsset:
        if asset.id in self._assets:
            raise ValueError(f"Prompt asset already registered: {asset.id}")
        self._assets[asset.id] = asset
        return asset

    def get(self, asset_id: str) -> PromptAsset:
        try:
            return self._assets[asset_id]
        except KeyError as exc:
            raise KeyError(f"Prompt asset not registered: {asset_id}") from exc

    def all(self) -> list[PromptAsset]:
        return list(self._assets.values())


prompt_asset_registry = PromptAssetRegistry()

prompt_asset_registry.register(
    PromptAsset(
        id="writer.whole_chapter.context",
        version="v1",
        task="writer",
        mode="text",
        context_policy=PromptContextPolicy(
            required=("chapter_plan", "style_contract", "story_contract"),
            preferred=("scene_fuel", "writing_cards", "guardrails", "active_entities"),
            droppable=("similar_chapters", "relevant_documents", "narrative_source"),
            max_chars=18000,
        ),
    )
)

prompt_asset_registry.register(
    PromptAsset(
        id="editor.rewrite_beat",
        version="v1",
        task="editor",
        mode="text",
        context_policy=PromptContextPolicy(
            required=("source_text", "issues"),
            preferred=("style_contract", "chapter_plan", "writing_cards", "genre_prompt_block"),
            droppable=("whole_chapter_issues", "genre_quality_config"),
            max_chars=14000,
        ),
    )
)

prompt_asset_registry.register(
    PromptAsset(
        id="fast_review.chapter",
        version="v1",
        task="review",
        mode="structured",
        context_policy=PromptContextPolicy(
            required=("polished_text", "chapter_context"),
            preferred=("style_contract", "genre_quality_config", "required_payoffs"),
            droppable=("raw_draft", "similar_chapters"),
            max_chars=16000,
        ),
    )
)
