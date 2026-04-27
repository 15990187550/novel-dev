from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from novel_dev.agents._llm_helpers import coerce_to_str_list, coerce_to_text


DEFAULT_DOMAIN_RULES = {
    "power_ladder": [],
    "scope_boundaries": [],
    "accessible_conflicts": [],
    "foreshadow_only": [],
    "forbidden_now": [],
    "continuity_rules": [],
    "knowledge_boundaries": [],
    "open_questions": [],
}


class KnowledgeDomainCreate(BaseModel):
    name: str
    domain_type: str = "source_work"
    activation_mode: str = "auto"
    activation_keywords: list[str] = Field(default_factory=list)
    rules: dict[str, Any] = Field(default_factory=dict)
    source_doc_ids: list[str] = Field(default_factory=list)
    confidence: str = "low"

    @field_validator("name", "domain_type", "activation_mode", "confidence", mode="before")
    @classmethod
    def _coerce_text(cls, value: Any) -> str:
        return coerce_to_text(value)

    @field_validator("activation_keywords", "source_doc_ids", mode="before")
    @classmethod
    def _coerce_str_list(cls, value: Any) -> list[str]:
        return coerce_to_str_list(value)


class KnowledgeDomainUpdate(BaseModel):
    name: Optional[str] = None
    domain_type: Optional[str] = None
    scope_status: Optional[str] = None
    activation_mode: Optional[str] = None
    activation_keywords: Optional[list[str]] = None
    rules: Optional[dict[str, Any]] = None
    suggested_scopes: Optional[list[dict[str, Any]]] = None
    confirmed_scopes: Optional[list[dict[str, Any]]] = None
    confidence: Optional[str] = None
    is_active: Optional[bool] = None


class ConfirmDomainScopeRequest(BaseModel):
    scope_type: str = "volume"
    scope_refs: list[str]

    @field_validator("scope_refs", mode="before")
    @classmethod
    def _coerce_scope_refs(cls, value: Any) -> list[str]:
        return coerce_to_str_list(value)


class KnowledgeDomainResponse(BaseModel):
    id: str
    novel_id: str
    name: str
    domain_type: str
    scope_status: str
    activation_mode: str
    activation_keywords: list[str]
    rules: dict[str, Any]
    source_doc_ids: list[str]
    suggested_scopes: list[dict[str, Any]]
    confirmed_scopes: list[dict[str, Any]]
    confidence: str
    is_active: bool


def serialize_knowledge_domain(domain) -> dict[str, Any]:
    return {
        "id": domain.id,
        "novel_id": domain.novel_id,
        "name": domain.name,
        "domain_type": domain.domain_type,
        "scope_status": domain.scope_status,
        "activation_mode": domain.activation_mode,
        "activation_keywords": domain.activation_keywords or [],
        "rules": domain.rules or {},
        "source_doc_ids": domain.source_doc_ids or [],
        "suggested_scopes": domain.suggested_scopes or [],
        "confirmed_scopes": domain.confirmed_scopes or [],
        "confidence": domain.confidence,
        "is_active": domain.is_active,
    }
