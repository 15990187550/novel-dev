from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from novel_dev.agents._llm_helpers import coerce_to_str_list, coerce_to_text
from novel_dev.schemas.similar_document import SimilarDocument


class BeatPlan(BaseModel):
    summary: str
    target_mood: str
    target_word_count: Optional[int] = None
    key_entities: List[str] = Field(default_factory=list)
    foreshadowings_to_embed: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        if "summary" not in normalized:
            for legacy_key in ("description", "content", "beat_summary"):
                if legacy_key in normalized:
                    normalized["summary"] = normalized[legacy_key]
                    break
        if "target_mood" not in normalized:
            for legacy_key in ("mood", "tone", "emotion"):
                if legacy_key in normalized:
                    normalized["target_mood"] = normalized[legacy_key]
                    break
        if "target_mood" not in normalized:
            normalized["target_mood"] = "tense"
        if "foreshadowings_to_embed" not in normalized:
            for legacy_key in ("planned_foreshadowings", "foreshadowings", "embed_foreshadowings"):
                if legacy_key in normalized:
                    normalized["foreshadowings_to_embed"] = normalized[legacy_key]
                    break
        return normalized

    @field_validator("summary", "target_mood", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)

    @field_validator("key_entities", "foreshadowings_to_embed", mode="before")
    @classmethod
    def _coerce_string_list_fields(cls, value: Any) -> List[str]:
        return coerce_to_str_list(value)


class ChapterPlan(BaseModel):
    chapter_number: int
    title: Optional[str] = None
    target_word_count: int
    beats: List[BeatPlan]

    @field_validator("title", mode="before")
    @classmethod
    def _coerce_title(cls, value: Any) -> str:
        return coerce_to_text(value)


class EntityState(BaseModel):
    entity_id: str
    name: str
    type: str
    current_state: str
    aliases: List[str] = Field(default_factory=list)
    memory_snapshot: dict = Field(default_factory=dict)

    @field_validator("aliases", mode="before")
    @classmethod
    def _coerce_aliases(cls, value: Any) -> List[str]:
        return coerce_to_str_list(value)


class NarrativeRelay(BaseModel):
    """Beat 写完后生成的叙事状态快照，传递给后续 beat。"""
    scene_state: str
    emotional_tone: str
    new_info_revealed: str
    open_threads: str
    next_beat_hook: str

    @field_validator("scene_state", "emotional_tone", "new_info_revealed", "open_threads", "next_beat_hook", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)


class LocationContext(BaseModel):
    current: str
    parent: Optional[str] = None
    narrative: Optional[str] = None

    @field_validator("current", "parent", "narrative", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)


class ForeshadowingContext(BaseModel):
    id: str
    content: str
    role_in_chapter: str = "embed"
    related_entity_names: List[str] = Field(default_factory=list)
    target_beat_index: Optional[int] = None
    surface_hint: Optional[str] = None
    payoff_requirement: Optional[str] = None

    @field_validator("content", "role_in_chapter", "surface_hint", "payoff_requirement", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)

    @field_validator("related_entity_names", mode="before")
    @classmethod
    def _coerce_related_entity_names(cls, value: Any) -> List[str]:
        return coerce_to_str_list(value)


class BeatContext(BaseModel):
    beat_index: int
    beat: BeatPlan
    entities: List[EntityState] = Field(default_factory=list)
    foreshadowings: List[ForeshadowingContext] = Field(default_factory=list)
    relevant_documents: list[SimilarDocument] = Field(default_factory=list)
    guardrails: List[str] = Field(default_factory=list)

    @field_validator("guardrails", mode="before")
    @classmethod
    def _coerce_guardrails(cls, value: Any) -> List[str]:
        return coerce_to_str_list(value)


class BeatWritingCard(BaseModel):
    """Executable beat contract used by WriterAgent before prose generation."""

    beat_index: int
    objective: str = ""
    conflict: str = ""
    turning_point: str = ""
    required_entities: List[str] = Field(default_factory=list)
    required_facts: List[str] = Field(default_factory=list)
    required_payoffs: List[str] = Field(default_factory=list)
    forbidden_future_events: List[str] = Field(default_factory=list)
    ending_hook: str = ""
    reader_takeaway: str = ""
    target_word_count: int = 800

    @field_validator("objective", "conflict", "turning_point", "ending_hook", "reader_takeaway", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)

    @field_validator("required_entities", "required_facts", "required_payoffs", "forbidden_future_events", mode="before")
    @classmethod
    def _coerce_string_list_fields(cls, value: Any) -> List[str]:
        return coerce_to_str_list(value)


class ChapterContext(BaseModel):
    chapter_plan: ChapterPlan
    style_profile: dict
    worldview_summary: str
    active_entities: List[EntityState]
    location_context: LocationContext
    timeline_events: List[dict]
    pending_foreshadowings: List[ForeshadowingContext]
    previous_chapter_summary: Optional[str] = None
    relevant_documents: list[SimilarDocument] = Field(default_factory=list)
    related_entities: list[EntityState] = Field(default_factory=list)
    similar_chapters: list[SimilarDocument] = Field(default_factory=list)
    guardrails: List[str] = Field(default_factory=list)
    beat_contexts: List[BeatContext] = Field(default_factory=list)
    writing_cards: List[BeatWritingCard] = Field(default_factory=list)
    story_contract: dict[str, Any] = Field(default_factory=dict)

    @field_validator("worldview_summary", "previous_chapter_summary", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)

    @field_validator("guardrails", mode="before")
    @classmethod
    def _coerce_guardrails(cls, value: Any) -> List[str]:
        return coerce_to_str_list(value)


class BeatSelfCheck(BaseModel):
    missing_entities: List[str] = Field(default_factory=list)
    missing_foreshadowings: List[str] = Field(default_factory=list)
    missing_payoffs: List[str] = Field(default_factory=list)
    contradictions: List[str] = Field(default_factory=list)
    needs_rewrite: bool = False

    @field_validator("missing_entities", "missing_foreshadowings", "missing_payoffs", "contradictions", mode="before")
    @classmethod
    def _coerce_string_list_fields(cls, value: Any) -> List[str]:
        return coerce_to_str_list(value)


class DraftMetadata(BaseModel):
    total_words: int
    beat_coverage: List[dict]
    style_violations: List[str]
    embedded_foreshadowings: List[str]

    @field_validator("style_violations", "embedded_foreshadowings", mode="before")
    @classmethod
    def _coerce_string_list_fields(cls, value: Any) -> List[str]:
        return coerce_to_str_list(value)
