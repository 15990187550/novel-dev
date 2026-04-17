from typing import List, Optional
from pydantic import BaseModel, Field

from novel_dev.schemas.similar_document import SimilarDocument


class BeatPlan(BaseModel):
    summary: str
    target_mood: str
    key_entities: List[str] = Field(default_factory=list)
    foreshadowings_to_embed: List[str] = Field(default_factory=list)


class ChapterPlan(BaseModel):
    chapter_number: int
    title: Optional[str] = None
    target_word_count: int
    beats: List[BeatPlan]


class EntityState(BaseModel):
    entity_id: str
    name: str
    type: str
    current_state: str


class LocationContext(BaseModel):
    current: str
    parent: Optional[str] = None
    narrative: Optional[str] = None


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


class DraftMetadata(BaseModel):
    total_words: int
    beat_coverage: List[dict]
    style_violations: List[str]
    embedded_foreshadowings: List[str]
