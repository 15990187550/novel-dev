from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class SettingDocDraftPayload(BaseModel):
    draft_id: str
    source_outline_ref: str
    source_kind: str
    target_import_mode: str
    target_doc_type: Optional[str] = None
    title: str
    content: str
    order_index: int = 0


class PendingExtractionPayload(BaseModel):
    source_filename: str
    extraction_type: str
    raw_result: dict[str, Any] = Field(default_factory=dict)
    proposed_entities: Optional[list[dict[str, Any]]] = None
    diff_result: Optional[dict[str, Any]] = None


class SettingSuggestionCardPayload(BaseModel):
    card_id: str
    card_type: str
    merge_key: str
    title: str
    summary: str
    status: str
    source_outline_refs: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    display_order: int = 0


class SettingSuggestionCardMergePayload(BaseModel):
    operation: Literal["upsert", "supersede"] = "upsert"
    merge_key: str
    card_id: Optional[str] = None
    card_type: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    status: Optional[str] = None
    source_outline_refs: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    display_order: int = 0

    @model_validator(mode="after")
    def validate_upsert_fields(self) -> "SettingSuggestionCardMergePayload":
        if self.operation == "supersede":
            return self

        required_fields = {
            "card_id": self.card_id,
            "card_type": self.card_type,
            "title": self.title,
            "summary": self.summary,
            "status": self.status,
        }
        missing_fields = [field_name for field_name, value in required_fields.items() if value is None]
        if missing_fields:
            missing = ", ".join(sorted(missing_fields))
            raise ValueError(f"Upsert suggestion cards require fields: {missing}")
        return self


class BrainstormWorkspacePayload(BaseModel):
    workspace_id: str
    novel_id: str
    status: str
    workspace_summary: Optional[str] = None
    outline_drafts: dict[str, dict[str, Any]] = Field(default_factory=dict)
    setting_docs_draft: list[SettingDocDraftPayload] = Field(default_factory=list)
    setting_suggestion_cards: list[SettingSuggestionCardPayload] = Field(default_factory=list)


class BrainstormWorkspaceSubmitResponse(BaseModel):
    synopsis_title: str
    pending_setting_count: int
    volume_outline_count: int
