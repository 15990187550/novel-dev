import json
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator

from novel_dev.agents._llm_helpers import coerce_to_str_list, coerce_to_text


def _parse_stringified_json_array(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped.startswith("["):
        return value
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return value
    return parsed if isinstance(parsed, list) else value


class TimelineEvent(BaseModel):
    tick: int
    narrative: str
    anchor_event_id: Optional[str] = None

    @field_validator("narrative", "anchor_event_id", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)


class SpacelineChange(BaseModel):
    location_id: str
    name: str
    parent_id: Optional[str] = None
    narrative: Optional[str] = None

    @field_validator("location_id", "name", "parent_id", "narrative", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)


class NewEntity(BaseModel):
    type: str
    name: str
    state: dict

    @field_validator("type", "name", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)


class EntityUpdate(BaseModel):
    entity_id: str
    state: dict
    diff_summary: dict

    @field_validator("entity_id", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)


class NewForeshadowing(BaseModel):
    content: str
    埋下_chapter_id: Optional[str] = None
    埋下_time_tick: Optional[int] = None
    埋下_location_id: Optional[str] = None
    回收条件: Optional[dict] = None

    @field_validator("content", "埋下_chapter_id", "埋下_location_id", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)


class NewRelationship(BaseModel):
    source_entity_id: str
    target_entity_id: str
    relation_type: str
    meta: Optional[dict] = None

    @field_validator("source_entity_id", "target_entity_id", "relation_type", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)


class ExtractionResult(BaseModel):
    timeline_events: List[TimelineEvent] = Field(default_factory=list)
    spaceline_changes: List[SpacelineChange] = Field(default_factory=list)
    new_entities: List[NewEntity] = Field(default_factory=list)
    concept_updates: List[EntityUpdate] = Field(default_factory=list)
    character_updates: List[EntityUpdate] = Field(default_factory=list)
    foreshadowings_recovered: List[str] = Field(default_factory=list)
    new_foreshadowings: List[NewForeshadowing] = Field(default_factory=list)
    new_relationships: List[NewRelationship] = Field(default_factory=list)

    @field_validator(
        "timeline_events",
        "spaceline_changes",
        "new_entities",
        "concept_updates",
        "character_updates",
        "new_foreshadowings",
        "new_relationships",
        mode="before",
    )
    @classmethod
    def _coerce_stringified_json_array_fields(cls, value: Any) -> Any:
        return _parse_stringified_json_array(value)

    @field_validator("foreshadowings_recovered", mode="before")
    @classmethod
    def _coerce_recovered_ids(cls, value: Any) -> List[str]:
        value = _parse_stringified_json_array(value)
        return coerce_to_str_list(value)
