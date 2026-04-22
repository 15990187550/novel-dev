from typing import Any, Optional

from pydantic import BaseModel, Field


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


class BrainstormWorkspacePayload(BaseModel):
    workspace_id: str
    novel_id: str
    status: str
    workspace_summary: Optional[str] = None
    outline_drafts: dict[str, dict[str, Any]] = Field(default_factory=dict)
    setting_docs_draft: list[SettingDocDraftPayload] = Field(default_factory=list)


class BrainstormWorkspaceSubmitResponse(BaseModel):
    synopsis_title: str
    pending_setting_count: int
    volume_outline_count: int
