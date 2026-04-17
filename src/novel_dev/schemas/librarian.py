from typing import List, Optional
from pydantic import BaseModel, Field


class TimelineEvent(BaseModel):
    tick: int
    narrative: str
    anchor_event_id: Optional[str] = None


class SpacelineChange(BaseModel):
    location_id: str
    name: str
    parent_id: Optional[str] = None
    narrative: Optional[str] = None


class NewEntity(BaseModel):
    type: str
    name: str
    state: dict


class EntityUpdate(BaseModel):
    entity_id: str
    state: dict
    diff_summary: dict


class NewForeshadowing(BaseModel):
    content: str
    埋下_chapter_id: Optional[str] = None
    埋下_time_tick: Optional[int] = None
    埋下_location_id: Optional[str] = None
    回收条件: Optional[dict] = None


class NewRelationship(BaseModel):
    source_entity_id: str
    target_entity_id: str
    relation_type: str
    meta: Optional[dict] = None


class ExtractionResult(BaseModel):
    timeline_events: List[TimelineEvent] = Field(default_factory=list)
    spaceline_changes: List[SpacelineChange] = Field(default_factory=list)
    new_entities: List[NewEntity] = Field(default_factory=list)
    concept_updates: List[EntityUpdate] = Field(default_factory=list)
    character_updates: List[EntityUpdate] = Field(default_factory=list)
    foreshadowings_recovered: List[str] = Field(default_factory=list)
    new_foreshadowings: List[NewForeshadowing] = Field(default_factory=list)
    new_relationships: List[NewRelationship] = Field(default_factory=list)
