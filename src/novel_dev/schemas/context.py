from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator

from novel_dev.agents._llm_helpers import coerce_to_str_list, coerce_to_text
from novel_dev.schemas.similar_document import SimilarDocument


class BeatPlan(BaseModel):
    summary: str
    target_mood: str
    key_entities: List[str] = Field(default_factory=list)
    foreshadowings_to_embed: List[str] = Field(default_factory=list)

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


class ChapterContext(BaseModel):
    chapter_plan: ChapterPlan
    style_profile: dict
    worldview_summary: str
    active_entities: List[EntityState]
    location_context: LocationContext
    timeline_events: List[dict]
    pending_foreshadowings: List[dict]
    previous_chapter_summary: Optional[str] = None
    relevant_documents: list[SimilarDocument] = Field(default_factory=list)
    related_entities: list[EntityState] = Field(default_factory=list)
    similar_chapters: list[SimilarDocument] = Field(default_factory=list)

    @field_validator("worldview_summary", "previous_chapter_summary", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)


class DraftMetadata(BaseModel):
    total_words: int
    beat_coverage: List[dict]
    style_violations: List[str]
    embedded_foreshadowings: List[str]

    @field_validator("style_violations", "embedded_foreshadowings", mode="before")
    @classmethod
    def _coerce_string_list_fields(cls, value: Any) -> List[str]:
        return coerce_to_str_list(value)
