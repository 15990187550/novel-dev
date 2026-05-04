from typing import Any, Optional

from pydantic import BaseModel, Field


class SettingGenerationSessionCreateRequest(BaseModel):
    title: str
    initial_idea: str = ""
    target_categories: list[str] = Field(default_factory=list)


class SettingGenerationSessionResponse(BaseModel):
    id: str
    novel_id: str
    title: str
    status: str
    target_categories: list[str] = Field(default_factory=list)
    clarification_round: int = 0
    conversation_summary: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SettingGenerationMessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None


class SettingGenerationSessionListResponse(BaseModel):
    items: list[SettingGenerationSessionResponse] = Field(default_factory=list)


class SettingGenerationSessionDetailResponse(BaseModel):
    session: SettingGenerationSessionResponse
    messages: list[SettingGenerationMessageResponse] = Field(default_factory=list)


class SettingGenerationSessionReplyRequest(BaseModel):
    content: str


class SettingGenerationSessionReplyResponse(BaseModel):
    session: SettingGenerationSessionResponse
    assistant_message: str
    questions: list[str] = Field(default_factory=list)


class SettingGenerationSessionGenerateRequest(BaseModel):
    pass


class SettingConsolidationStartRequest(BaseModel):
    selected_pending_ids: list[str] = Field(default_factory=list)


class SettingConsolidationStartResponse(BaseModel):
    job_id: str
    status: str


class SettingReviewChangeResponse(BaseModel):
    id: str
    batch_id: str
    target_type: str
    operation: str
    target_id: Optional[str] = None
    status: str
    before_snapshot: Optional[dict[str, Any]] = None
    after_snapshot: Optional[dict[str, Any]] = None
    conflict_hints: list[dict[str, Any]] = Field(default_factory=list)
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SettingReviewBatchResponse(BaseModel):
    id: str
    novel_id: str
    source_type: str
    source_file: Optional[str] = None
    source_session_id: Optional[str] = None
    job_id: Optional[str] = None
    status: str
    summary: str = ""
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SettingReviewBatchListResponse(BaseModel):
    items: list[SettingReviewBatchResponse] = Field(default_factory=list)


class SettingWorkbenchResponse(BaseModel):
    sessions: list[SettingGenerationSessionResponse] = Field(default_factory=list)
    review_batches: list[SettingReviewBatchResponse] = Field(default_factory=list)


class SettingReviewBatchDetailResponse(BaseModel):
    batch: SettingReviewBatchResponse
    changes: list[SettingReviewChangeResponse] = Field(default_factory=list)


class SettingReviewApproveRequest(BaseModel):
    change_ids: list[str] = Field(default_factory=list)
    approve_all: bool = False


class SettingReviewDecisionRequest(BaseModel):
    change_id: str
    decision: str
    edited_after_snapshot: Optional[dict[str, Any]] = None


class SettingReviewApplyRequest(BaseModel):
    decisions: list[SettingReviewDecisionRequest] = Field(default_factory=list)


class SettingReviewApplyResponse(BaseModel):
    status: str
    applied: int = 0
    rejected: int = 0
    failed: int = 0


class SettingConflictResolutionRequest(BaseModel):
    change_id: str
    resolved_after_snapshot: dict[str, Any]
