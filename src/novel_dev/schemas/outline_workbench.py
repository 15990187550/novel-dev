from typing import Any, List, Optional

from pydantic import BaseModel, Field


class OutlineItemSummary(BaseModel):
    outline_type: str
    outline_ref: str
    title: str
    status: str = "ready"
    summary: Optional[str] = None


class OutlineMessagePayload(BaseModel):
    id: str
    role: str
    message_type: str
    content: str
    meta: Optional[dict[str, Any]] = None
    created_at: Optional[str] = None


class OutlineContextWindow(BaseModel):
    last_result_snapshot: Optional[dict[str, Any]] = None
    conversation_summary: Optional[str] = None
    recent_messages: List[OutlineMessagePayload] = Field(default_factory=list)


class OutlineWorkbenchPayload(BaseModel):
    novel_id: str
    outline_type: str
    outline_ref: str
    session_id: str
    outline_items: List[OutlineItemSummary] = Field(default_factory=list)
    context_window: OutlineContextWindow = Field(default_factory=OutlineContextWindow)


class OutlineMessagesResponse(BaseModel):
    session_id: str
    outline_type: str
    outline_ref: str
    last_result_snapshot: Optional[dict[str, Any]] = None
    conversation_summary: Optional[str] = None
    recent_messages: List[OutlineMessagePayload] = Field(default_factory=list)


class OutlineSubmitResponse(BaseModel):
    session_id: str
    assistant_message: OutlineMessagePayload
    last_result_snapshot: Optional[dict[str, Any]] = None
    conversation_summary: Optional[str] = None
    setting_update_summary: Optional[dict[str, int]] = None


class OutlineClearContextResponse(BaseModel):
    session_id: str
    outline_type: str
    outline_ref: str
    deleted_messages: int = 0
    conversation_summary: Optional[str] = None
    last_result_snapshot: Optional[dict[str, Any]] = None
