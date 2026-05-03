from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


SessionStatus = Literal["clarifying", "ready_to_generate", "generating", "generated", "failed", "archived"]
BatchStatus = Literal["pending", "partially_approved", "approved", "rejected", "superseded", "failed"]
ChangeStatus = Literal["pending", "approved", "rejected", "edited_approved", "failed"]
TargetType = Literal["setting_card", "entity", "relationship"]
ChangeOperation = Literal["create", "update", "delete"]
ReviewDecision = Literal["approve", "reject", "edit_approve"]


class SettingGenerationSessionCreate(BaseModel):
    title: str
    initial_idea: str = ""
    target_categories: list[str] = Field(default_factory=list)
    focused_target: Optional[dict[str, Any]] = None


class SettingGenerationSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    title: str
    status: SessionStatus
    target_categories: list[str] = Field(default_factory=list)
    clarification_round: int = 0
    conversation_summary: Optional[str] = None
    focused_target: Optional[dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SettingGenerationMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    role: str
    content: str
    meta: Optional[dict[str, Any]] = None
    created_at: Optional[datetime] = None


class SettingSessionReplyRequest(BaseModel):
    content: str
    metadata: Optional[dict[str, Any]] = None


class SettingReviewChangeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    batch_id: str
    target_type: TargetType
    operation: ChangeOperation
    target_id: Optional[str] = None
    status: ChangeStatus
    before_snapshot: Optional[dict[str, Any]] = None
    after_snapshot: Optional[dict[str, Any]] = None
    conflict_hints: list[dict[str, Any]] = Field(default_factory=list)
    source_session_id: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SettingReviewBatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    source_type: str
    source_file: Optional[str] = None
    source_session_id: Optional[str] = None
    source_session_title: Optional[str] = None
    status: BatchStatus
    summary: str = ""
    error_message: Optional[str] = None
    counts: dict[str, int] = Field(default_factory=dict)
    changes: list[SettingReviewChangeResponse] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SettingWorkbenchPayload(BaseModel):
    novel_id: str
    sessions: list[SettingGenerationSessionResponse] = Field(default_factory=list)
    review_batches: list[SettingReviewBatchResponse] = Field(default_factory=list)


class SettingBatchGenerateRequest(BaseModel):
    force: bool = False


class SettingReviewDecision(BaseModel):
    change_id: str
    decision: ReviewDecision
    edited_after_snapshot: Optional[dict[str, Any]] = None


class SettingReviewApplyRequest(BaseModel):
    decisions: list[SettingReviewDecision] = Field(default_factory=list)
