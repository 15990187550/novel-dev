import asyncio
import json
from datetime import datetime
from typing import Any, Optional
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, func, select, text
from pydantic import BaseModel, Field

from novel_dev.db.engine import async_session_maker
from novel_dev.db.models import AgentLog, EntityGroup, NovelState, Entity, EntityRelationship, Timeline, Spaceline, Foreshadowing, Chapter
from novel_dev.services.entity_service import EntityService
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.genre_repo import GenreRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.storage.markdown_sync import MarkdownSync
from novel_dev.storage.paths import StoragePaths
from novel_dev.config import Settings
from novel_dev.services.extraction_service import ExtractionService
from novel_dev.repositories.pending_extraction_repo import PendingExtractionRepository
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.export.brainstorm import render_brainstorm_prompt
from novel_dev.agents.context_agent import ContextAgent
from novel_dev.agents.writer_agent import WriterAgent
from novel_dev.services.embedding_service import EmbeddingService
from novel_dev.llm import llm_factory
from novel_dev.llm.exceptions import LLMConfigError, LLMTimeoutError
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.context import ChapterContext
from novel_dev.schemas.outline import VolumePlan
from novel_dev.schemas.outline_workbench import OutlineClearContextResponse, OutlineMessagesResponse
from novel_dev.schemas.brainstorm_workspace import (
    BrainstormSuggestionCardUpdateRequest,
    BrainstormSuggestionCardUpdateResponse,
    BrainstormWorkspacePayload,
    BrainstormWorkspaceSubmitResponse,
)
from novel_dev.services.brainstorm_workspace_service import BrainstormWorkspaceService
from novel_dev.services.flow_control_service import FlowCancelledError, FlowControlService
from novel_dev.services.chapter_generation_service import AutoRunChaptersRequest
from novel_dev.repositories.generation_job_repo import GenerationJobRepository
from novel_dev.services.generation_job_service import (
    CHAPTER_AUTO_RUN_JOB,
    CHAPTER_REWRITE_JOB,
    SETTING_CONSOLIDATION_JOB,
    schedule_generation_job,
)
from novel_dev.services.recovery_cleanup_service import RecoveryCleanupOptions, RecoveryCleanupService
from novel_dev.services.log_service import log_service
from novel_dev.services.novel_deletion_service import NovelDeletionService
from novel_dev.services.outline_workbench_service import OutlineWorkbenchService
from novel_dev.services.knowledge_domain_service import KnowledgeDomainService
from novel_dev.schemas.knowledge_domain import (
    ConfirmDomainScopeRequest,
    KnowledgeDomainCreate,
    KnowledgeDomainUpdate,
    serialize_knowledge_domain,
)
from novel_dev.schemas.setting_workbench import (
    SettingConsolidationStartRequest,
    SettingConsolidationStartResponse,
    SettingConflictResolutionRequest,
    SettingGenerationSessionCreateRequest,
    SettingGenerationSessionDetailResponse,
    SettingGenerationSessionGenerateRequest,
    SettingGenerationSessionListResponse,
    SettingGenerationSessionReplyRequest,
    SettingGenerationSessionReplyResponse,
    SettingGenerationSessionResponse,
    SettingReviewApplyRequest,
    SettingReviewApplyResponse,
    SettingReviewApproveRequest,
    SettingReviewBatchDetailResponse,
    SettingReviewBatchListResponse,
    SettingReviewBatchResponse,
    SettingWorkbenchResponse,
)
from novel_dev.repositories.setting_workbench_repo import SettingWorkbenchRepository
from novel_dev.services.setting_consolidation_service import SettingConsolidationService
from novel_dev.services.setting_workbench_service import SettingWorkbenchService
from novel_dev.services.global_consistency_audit_service import GlobalConsistencyAuditService
from novel_dev.services.world_state_review_service import WorldStateReviewService
from novel_dev.agents.brainstorm_agent import BrainstormAgent
from novel_dev.agents.volume_planner import VolumePlannerAgent
from novel_dev.genres import default_genre
import re
import secrets

router = APIRouter()
document_upload_tasks: set[asyncio.Task] = set()


async def _raise_flow_cancelled(session: AsyncSession, novel_id: str):
    log_service.add_log(
        novel_id,
        "FlowControl",
        "流程已停止",
        level="warning",
        event="flow.stop",
        status="stopped",
        node="flow_control",
        task="stop",
    )
    await session.commit()
    raise HTTPException(status_code=409, detail="流程已停止")


def _llm_config_http_exception(exc: LLMConfigError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"AI 模型配置或认证失败：{exc}",
    )


class CreateNovelRequest(BaseModel):
    title: str
    primary_category_slug: str
    secondary_category_slug: str


class WorldStateReviewResolveRequest(BaseModel):
    action: str
    edited_extraction: dict | None = None


def _isoformat(value):
    return value.isoformat() if value else None


def _world_state_review_response(item) -> dict[str, Any]:
    return {
        "id": item.id,
        "novel_id": item.novel_id,
        "chapter_id": item.chapter_id,
        "status": item.status,
        "extraction_payload": item.extraction_payload or {},
        "diff_result": item.diff_result or {},
        "decision": item.decision,
        "error_message": item.error_message,
        "created_at": _isoformat(item.created_at),
        "updated_at": _isoformat(item.updated_at),
    }


def _serialize_setting_generation_session(item) -> dict[str, Any]:
    return {
        "id": item.id,
        "novel_id": item.novel_id,
        "title": item.title,
        "status": item.status,
        "target_categories": item.target_categories or [],
        "clarification_round": item.clarification_round or 0,
        "conversation_summary": item.conversation_summary,
        "created_at": _isoformat(item.created_at),
        "updated_at": _isoformat(item.updated_at),
    }


def _serialize_setting_generation_message(item) -> dict[str, Any]:
    return {
        "id": item.id,
        "session_id": item.session_id,
        "role": item.role,
        "content": item.content,
        "meta": item.meta or {},
        "created_at": _isoformat(item.created_at),
    }


def _serialize_setting_review_batch(item) -> dict[str, Any]:
    return {
        "id": item.id,
        "novel_id": item.novel_id,
        "source_type": item.source_type,
        "source_file": item.source_file,
        "source_session_id": item.source_session_id,
        "job_id": item.job_id,
        "status": item.status,
        "summary": item.summary or "",
        "input_snapshot": item.input_snapshot or {},
        "error_message": item.error_message,
        "created_at": _isoformat(item.created_at),
        "updated_at": _isoformat(item.updated_at),
    }


def _serialize_setting_review_change(item) -> dict[str, Any]:
    return {
        "id": item.id,
        "batch_id": item.batch_id,
        "target_type": item.target_type,
        "operation": item.operation,
        "target_id": item.target_id,
        "status": item.status,
        "before_snapshot": item.before_snapshot,
        "after_snapshot": item.after_snapshot,
        "conflict_hints": item.conflict_hints or [],
        "error_message": item.error_message,
        "created_at": _isoformat(item.created_at),
        "updated_at": _isoformat(item.updated_at),
    }


async def _lock_setting_consolidation_start(session: AsyncSession, novel_id: str) -> None:
    bind = session.get_bind()
    if getattr(bind.dialect, "name", "") != "postgresql":
        return
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"setting_consolidation:{novel_id}"},
    )


class UpdateNovelRequest(BaseModel):
    title: str


class ChapterRewriteRequest(BaseModel):
    resume: bool = False
    failed_job_id: Optional[str] = None


class EntityClassificationUpdateRequest(BaseModel):
    manual_category: Optional[str] = None
    manual_group_slug: Optional[str] = None
    manual_group_name: Optional[str] = None
    clear_manual_override: bool = False
    reclassify: bool = False


class EntityUpdateRequest(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    aliases: Optional[list[str]] = None
    state_fields: dict[str, Any] = Field(default_factory=dict)


class OutlineWorkbenchSubmitRequest(BaseModel):
    outline_type: str
    outline_ref: str
    content: str = Field(min_length=1)


class OutlineWorkbenchSelectionRequest(BaseModel):
    outline_type: str
    outline_ref: str


class RejectPendingRequest(BaseModel):
    pending_id: str


class UpdatePendingDraftFieldRequest(BaseModel):
    entity_type: str
    entity_name: str
    field: str
    value: str = ""


class UpdateLibraryDocumentRequest(BaseModel):
    content: str = Field(min_length=1)


settings = Settings()


def _parse_style_config_title(title: Optional[str]) -> dict[str, Any]:
    if not title:
        return {}
    try:
        parsed = json.loads(title)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _serialize_library_document(doc, *, is_active: bool = True) -> dict[str, Any]:
    payload = {
        "id": doc.id,
        "doc_type": doc.doc_type,
        "title": doc.title,
        "content": doc.content,
        "version": doc.version,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
        "is_active": is_active,
    }
    if doc.doc_type == "style_profile":
        payload["style_config"] = _parse_style_config_title(doc.title)
    return payload


def _serialize_pending_document(item) -> dict[str, Any]:
    return {
        "id": item.id,
        "source_filename": item.source_filename,
        "extraction_type": item.extraction_type,
        "status": item.status,
        "raw_result": item.raw_result,
        "proposed_entities": item.proposed_entities,
        "diff_result": item.diff_result,
        "resolution_result": item.resolution_result,
        "error_message": item.error_message,
        "created_at": item.created_at.isoformat(),
    }


def _latest_documents_by_title(docs: list) -> list:
    latest_by_key: dict[tuple[str, str], Any] = {}
    for doc in docs:
        key = (doc.doc_type, doc.title)
        current = latest_by_key.get(key)
        if current is None:
            latest_by_key[key] = doc
            continue
        current_version = getattr(current, "version", 0) or 0
        doc_version = getattr(doc, "version", 0) or 0
        current_updated = getattr(current, "updated_at", None)
        doc_updated = getattr(doc, "updated_at", None)
        if doc_version > current_version or (
            doc_version == current_version and doc_updated and current_updated and doc_updated > current_updated
        ):
            latest_by_key[key] = doc
    return sorted(
        latest_by_key.values(),
        key=lambda doc: (
            (getattr(doc, "updated_at", None).timestamp() if getattr(doc, "updated_at", None) else 0),
            getattr(doc, "title", ""),
        ),
        reverse=True,
    )


def _active_documents(docs: list) -> list:
    return [doc for doc in docs if getattr(doc, "archived_at", None) is None]


def _word_count(text: Optional[str]) -> int:
    if not text:
        return 0
    # For CJK novels, word count is approximately the character count excluding whitespace.
    return len(text.replace(" ", "").replace("\n", "").replace("\t", "").replace("\r", ""))


def _stringify_relationship_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _infer_relationship_type(text: str) -> str:
    if any(keyword in text for keyword in ("同盟", "盟友", "伙伴", "战友", "同伴")):
        return "同盟"
    if any(keyword in text for keyword in ("师父", "师徒", "弟子", "传人", "传承")):
        return "师承"
    if any(keyword in text for keyword in ("敌", "仇", "杀", "对立")):
        return "敌对"
    if any(keyword in text for keyword in ("爱", "情", "喜欢", "道侣", "暧昧")):
        return "情感"
    return "关联"


def _normalize_inferred_relationship_type(source_row: dict, target_row: dict, relation_text: str) -> str:
    relation_type = _infer_relationship_type(relation_text)
    source_type = (source_row.get("type") or "").strip().lower()
    target_type = (target_row.get("type") or "").strip().lower()

    if relation_type != "关联" and (source_type != "character" or target_type != "character"):
        return "关联"
    return relation_type


def _iter_inference_text_fragments(latest_state: dict) -> list[tuple[str, str]]:
    fragments: list[tuple[str, str]] = []
    for field, value in (latest_state or {}).items():
        if field in {"name", "aliases"}:
            continue
        text = _stringify_relationship_value(value).strip()
        if not text or text in {"{}", "[]", '""'}:
            continue
        fragments.append((field, text))
    return fragments


def _inference_domain_key(entity_row: dict) -> str | None:
    latest_state = entity_row.get("latest_state") or {}
    domain_id = latest_state.get("_knowledge_domain_id")
    if isinstance(domain_id, str) and domain_id.strip():
        return f"id:{domain_id.strip()}"
    domain_name = latest_state.get("_knowledge_domain_name")
    if isinstance(domain_name, str) and domain_name.strip():
        return f"name:{domain_name.strip()}"
    return None


def _same_inference_domain(source_row: dict, target_row: dict) -> bool:
    return _inference_domain_key(source_row) == _inference_domain_key(target_row)


def _build_inferred_relationships(entity_rows: list[dict]) -> list[dict]:
    inferred = []
    seen = set()
    sorted_rows = sorted(entity_rows, key=lambda item: len(item["name"]), reverse=True)
    for source in sorted_rows:
        latest_state = source.get("latest_state") or {}
        fragments = _iter_inference_text_fragments(latest_state)
        if not fragments:
            continue
        for field, relation_text in fragments:
            for target in sorted_rows:
                if source["entity_id"] == target["entity_id"]:
                    continue
                if target["name"] not in relation_text:
                    continue
                if not _same_inference_domain(source, target):
                    continue
                relation_type = _normalize_inferred_relationship_type(source, target, relation_text)
                dedup_key = (source["entity_id"], target["entity_id"], relation_type)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                inferred.append({
                    "id": f"inferred:{source['entity_id']}:{target['entity_id']}:{relation_type}",
                    "source_id": source["entity_id"],
                    "target_id": target["entity_id"],
                    "relation_type": relation_type,
                    "meta": {"source": f"latest_state.{field}"},
                    "created_at_chapter_id": None,
                    "is_active": True,
                    "is_inferred": True,
                    "archived_at": None,
                    "archive_reason": None,
                    "archived_by_consolidation_batch_id": None,
                    "archived_by_consolidation_change_id": None,
                })
    return inferred


def _classification_status(entity: Entity) -> str:
    if entity.manual_category or entity.manual_group_id:
        return "manual_override"
    if entity.system_needs_review:
        return "needs_review"
    return "auto"


def _effective_search_classification(
    hit: dict,
    groups_by_id: dict[str, EntityGroup],
) -> tuple[str, Optional[str], Optional[EntityGroup]]:
    manual_category = hit.get("manual_category")
    manual_group_id = hit.get("manual_group_id")
    system_category = hit.get("system_category")
    system_group_id = hit.get("system_group_id")

    manual_group = groups_by_id.get(manual_group_id) if manual_group_id else None
    system_group = groups_by_id.get(system_group_id) if system_group_id else None

    if (
        manual_category
        and manual_group_id
        and manual_group is not None
        and manual_group.category == manual_category
    ):
        return manual_category, manual_group_id, manual_group

    if manual_category:
        if (
            manual_group_id
            and manual_group is not None
            and manual_group.category == manual_category
        ):
            return manual_category, manual_group_id, manual_group
        return manual_category, None, None

    if (
        system_category
        and system_group_id
        and system_group is not None
        and system_group.category == system_category
    ):
        return system_category, system_group_id, system_group

    if system_category:
        return system_category, None, None

    return "其他", None, None


async def _serialize_entity_payload(session: AsyncSession, entity: Entity) -> dict:
    group_ids = [group_id for group_id in (entity.system_group_id, entity.manual_group_id) if group_id]
    groups: dict[str, EntityGroup] = {}
    if group_ids:
        group_result = await session.execute(select(EntityGroup).where(EntityGroup.id.in_(group_ids)))
        groups = {group.id: group for group in group_result.scalars().all()}

    system_group = groups.get(entity.system_group_id) if entity.system_group_id else None
    manual_group = groups.get(entity.manual_group_id) if entity.manual_group_id else None
    effective_category, effective_group_id, effective_group = _effective_search_classification(
        {
            "manual_category": entity.manual_category,
            "manual_group_id": entity.manual_group_id,
            "system_category": entity.system_category,
            "system_group_id": entity.system_group_id,
        },
        groups,
    )

    return {
        "entity_id": entity.id,
        "type": entity.type,
        "name": entity.name,
        "novel_id": entity.novel_id,
        "current_version": entity.current_version,
        "created_at_chapter_id": entity.created_at_chapter_id,
        "system_category": entity.system_category,
        "system_group_id": entity.system_group_id,
        "system_group_slug": system_group.group_slug if system_group else None,
        "system_group_name": system_group.group_name if system_group else None,
        "manual_category": entity.manual_category,
        "manual_group_id": entity.manual_group_id,
        "manual_group_slug": manual_group.group_slug if manual_group else None,
        "manual_group_name": manual_group.group_name if manual_group else None,
        "effective_category": effective_category,
        "effective_group_id": effective_group_id,
        "effective_group_slug": effective_group.group_slug if effective_group else None,
        "effective_group_name": effective_group.group_name if effective_group else None,
        "classification_reason": entity.classification_reason,
        "classification_confidence": entity.classification_confidence,
        "system_needs_review": entity.system_needs_review,
        "classification_status": _classification_status(entity),
        "search_document": entity.search_document,
        "archived_at": _isoformat(entity.archived_at),
        "archive_reason": entity.archive_reason,
        "archived_by_consolidation_batch_id": entity.archived_by_consolidation_batch_id,
        "archived_by_consolidation_change_id": entity.archived_by_consolidation_change_id,
    }


def _normalize_aliases(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _entity_scope_from_state(state: Optional[dict]) -> dict[str, Any]:
    state = state or {}
    if state.get("_knowledge_usage") != "domain":
        return {
            "knowledge_usage": "global",
            "knowledge_domain_id": None,
            "knowledge_domain_name": None,
        }
    return {
        "knowledge_usage": "domain",
        "knowledge_domain_id": state.get("_knowledge_domain_id"),
        "knowledge_domain_name": state.get("_knowledge_domain_name"),
    }


async def get_session():
    async with async_session_maker() as session:
        yield session


@router.get("/api/novels")
async def list_novels(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(NovelState.novel_id, NovelState.current_phase, NovelState.last_updated, NovelState.checkpoint_data)
        .order_by(NovelState.last_updated.desc())
    )
    rows = result.all()
    return {
        "items": [
            {
                "novel_id": r.novel_id,
                "title": _get_novel_display_title(r.novel_id, r.checkpoint_data or {}),
                "current_phase": r.current_phase,
                "genre": _get_checkpoint_genre(r.checkpoint_data),
                "last_updated": r.last_updated.isoformat() if r.last_updated else None,
            }
            for r in rows
        ]
    }


def _get_novel_display_title(novel_id: str, checkpoint_data: dict[str, Any]) -> str:
    return (
        checkpoint_data.get("novel_title")
        or checkpoint_data.get("title")
        or novel_id
    )


def _serialize_genre(genre) -> dict[str, str]:
    return {
        "primary_slug": genre.primary_slug,
        "primary_name": genre.primary_name,
        "secondary_slug": genre.secondary_slug,
        "secondary_name": genre.secondary_name,
    }


def _get_checkpoint_genre(checkpoint_data) -> dict[str, str]:
    raw_genre = (checkpoint_data or {}).get("genre") if isinstance(checkpoint_data, dict) else None
    if not isinstance(raw_genre, dict):
        return _serialize_genre(default_genre())

    fallback = _serialize_genre(default_genre())
    return {
        "primary_slug": raw_genre.get("primary_slug") or fallback["primary_slug"],
        "primary_name": raw_genre.get("primary_name") or fallback["primary_name"],
        "secondary_slug": raw_genre.get("secondary_slug") or fallback["secondary_slug"],
        "secondary_name": raw_genre.get("secondary_name") or fallback["secondary_name"],
    }


def _checkpoint_with_genre(checkpoint_data: dict[str, Any] | None) -> dict[str, Any]:
    checkpoint = dict(checkpoint_data or {})
    checkpoint["genre"] = _get_checkpoint_genre(checkpoint)
    return checkpoint


async def _resolve_create_genre(session: AsyncSession, primary_slug: str, secondary_slug: str):
    categories = await GenreRepository(session).list_categories(include_disabled=False)
    by_slug = {category.slug: category for category in categories}

    primary = by_slug.get(primary_slug)
    if primary is None or primary.level != 1:
        raise HTTPException(status_code=422, detail="一级分类不存在或不可用")

    secondary = by_slug.get(secondary_slug)
    if secondary is None or secondary.level != 2 or secondary.parent_slug != primary.slug:
        raise HTTPException(status_code=422, detail="二级分类不存在或不属于所选一级分类")

    return default_genre().model_copy(
        update={
            "primary_slug": primary.slug,
            "primary_name": primary.name,
            "secondary_slug": secondary.slug,
            "secondary_name": secondary.name,
        }
    )


def _generate_novel_id(title: str) -> str:
    # Strip non-ASCII first so CJK titles get a clean slug
    slug = re.sub(r'[^\x00-\x7F]', '', title.lower())
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[-\s]+', '-', slug).strip('-')
    if not slug:
        slug = 'novel'
    suffix = secrets.token_hex(2)
    return f"{slug}-{suffix}"


@router.get("/api/novel-categories")
async def list_novel_categories(session: AsyncSession = Depends(get_session)):
    categories = await GenreRepository(session).list_categories(include_disabled=False)
    children_by_parent: dict[str, list[dict[str, Any]]] = {}
    for category in categories:
        if category.level != 2 or not category.parent_slug:
            continue
        children_by_parent.setdefault(category.parent_slug, []).append(
            {
                "slug": category.slug,
                "name": category.name,
                "description": category.description,
                "sort_order": category.sort_order,
            }
        )

    return [
        {
            "slug": category.slug,
            "name": category.name,
            "description": category.description,
            "sort_order": category.sort_order,
            "children": children_by_parent.get(category.slug, []),
        }
        for category in categories
        if category.level == 1
    ]


@router.post("/api/novels", status_code=201)
async def create_novel(req: CreateNovelRequest, session: AsyncSession = Depends(get_session)):
    title = req.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="标题不能为空")
    genre = await _resolve_create_genre(session, req.primary_category_slug, req.secondary_category_slug)
    genre_data = _serialize_genre(genre)

    novel_id = None
    for _ in range(5):
        candidate = _generate_novel_id(title)
        existing = await session.execute(select(NovelState.novel_id).where(NovelState.novel_id == candidate))
        if existing.scalar_one_or_none() is None:
            novel_id = candidate
            break

    if novel_id is None:
        raise HTTPException(status_code=500, detail="无法生成唯一的小说 ID，请重试")

    checkpoint_data = {
        "novel_title": title,
        "genre": genre_data,
        "synopsis_data": {
            "title": title,
            "logline": "",
            "core_conflict": "",
            "themes": [],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 1,
            "estimated_total_chapters": 10,
            "estimated_total_words": 30000,
        },
        "synopsis_doc_id": None,
    }

    state = NovelState(
        novel_id=novel_id,
        current_phase="brainstorming",
        current_volume_id=None,
        current_chapter_id=None,
        checkpoint_data=checkpoint_data,
    )
    session.add(state)
    await session.commit()
    checkpoint = _checkpoint_with_genre(state.checkpoint_data)

    return {
        "novel_id": state.novel_id,
        "title": _get_novel_display_title(state.novel_id, checkpoint),
        "current_phase": state.current_phase,
        "current_volume_id": state.current_volume_id,
        "current_chapter_id": state.current_chapter_id,
        "genre": checkpoint["genre"],
        "checkpoint_data": checkpoint,
        "last_updated": state.last_updated.isoformat() if state.last_updated else None,
    }


@router.get("/api/novels/{novel_id}/state")
async def get_novel_state(novel_id: str, session: AsyncSession = Depends(get_session)):
    repo = NovelStateRepository(session)
    state = await repo.get_state(novel_id)
    if not state:
        raise HTTPException(status_code=404, detail="Novel state not found")
    checkpoint = _checkpoint_with_genre(state.checkpoint_data)
    return {
        "novel_id": state.novel_id,
        "title": _get_novel_display_title(state.novel_id, checkpoint),
        "current_phase": state.current_phase,
        "current_volume_id": state.current_volume_id,
        "current_chapter_id": state.current_chapter_id,
        "genre": checkpoint["genre"],
        "checkpoint_data": checkpoint,
        "last_updated": state.last_updated.isoformat(),
    }


@router.patch("/api/novels/{novel_id}")
async def update_novel(novel_id: str, req: UpdateNovelRequest, session: AsyncSession = Depends(get_session)):
    title = req.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="标题不能为空")

    repo = NovelStateRepository(session)
    state = await repo.get_state(novel_id)
    if not state:
        raise HTTPException(status_code=404, detail="Novel state not found")

    checkpoint_data = dict(state.checkpoint_data or {})
    checkpoint_data["novel_title"] = title
    state.checkpoint_data = checkpoint_data
    await session.commit()
    await session.refresh(state)
    checkpoint = _checkpoint_with_genre(state.checkpoint_data)

    return {
        "novel_id": state.novel_id,
        "title": _get_novel_display_title(state.novel_id, checkpoint),
        "current_phase": state.current_phase,
        "current_volume_id": state.current_volume_id,
        "current_chapter_id": state.current_chapter_id,
        "genre": checkpoint["genre"],
        "checkpoint_data": checkpoint,
        "last_updated": state.last_updated.isoformat(),
    }


@router.delete("/api/novels/{novel_id}", status_code=204)
async def delete_novel(novel_id: str, session: AsyncSession = Depends(get_session)):
    deleted = await NovelDeletionService(session, settings.data_dir).delete_novel(novel_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Novel state not found")
    return None


@router.get("/api/novels/{novel_id}/entities")
async def list_entities(
    novel_id: str,
    include_archived: bool = False,
    session: AsyncSession = Depends(get_session),
):
    filters = [Entity.novel_id == novel_id]
    if not include_archived:
        filters.append(Entity.archived_at.is_(None))
    result = await session.execute(
        select(Entity).where(*filters).order_by(Entity.name)
    )
    entities = list(result.scalars().all())
    svc = EntityService(session)
    states = await svc.get_latest_states([ent.id for ent in entities])
    grouped: dict[tuple[str, str], list[dict]] = {}
    for ent in entities:
        row = await _serialize_entity_payload(session, ent)
        row["latest_state"] = states.get(ent.id)
        row.update(_entity_scope_from_state(row["latest_state"]))
        row["aliases"] = _normalize_aliases(row["latest_state"].get("aliases") if row["latest_state"] else None)
        scope_key = row["knowledge_domain_id"] if row["knowledge_usage"] == "domain" else "global"
        key = (scope_key, ent.type, EntityRepository.normalize_name(ent.name) or ent.name)
        grouped.setdefault(key, []).append(row)

    items = []
    for rows in grouped.values():
        rows.sort(key=lambda item: (len(item["name"]), item["name"]))
        primary = dict(rows[0])
        merged_state = dict(primary.get("latest_state") or {})
        aliases = list(primary.get("aliases") or [])
        aliases.extend(row["name"] for row in rows[1:] if row["name"] != primary["name"])
        for row in rows[1:]:
            for key, value in (row.get("latest_state") or {}).items():
                if key == "name":
                    continue
                if key not in merged_state or merged_state[key] in (None, "", [], {}):
                    if value not in (None, "", [], {}):
                        merged_state[key] = value
        primary["current_version"] = max(row["current_version"] for row in rows)
        primary["latest_state"] = merged_state
        primary["aliases"] = aliases
        primary["merged_entity_ids"] = [row["entity_id"] for row in rows]
        items.append(primary)
    items.sort(key=lambda item: item["name"])
    return {"items": items}




@router.get("/api/novels/{novel_id}/entities/search")
async def search_entities(
    novel_id: str,
    q: str,
    include_archived: bool = False,
    session: AsyncSession = Depends(get_session),
):
    query = q.strip()
    if not query:
        return {"items": []}

    embedder = llm_factory.get_embedder()
    embedding_service = EmbeddingService(session, embedder)
    query_vector = await embedding_service.generate_embedding(query)
    entity_repo = EntityRepository(session)
    hits = await entity_repo.search_entities(
        novel_id,
        query=query,
        query_vector=query_vector,
        limit=20,
        include_archived=include_archived,
    )
    group_ids = []
    for hit in hits:
        for group_id in (hit.get("manual_group_id"), hit.get("system_group_id")):
            if group_id and group_id not in group_ids:
                group_ids.append(group_id)

    groups_by_id: dict[str, EntityGroup] = {}
    if group_ids:
        group_result = await session.execute(
            select(EntityGroup).where(EntityGroup.id.in_(group_ids))
        )
        groups_by_id = {group.id: group for group in group_result.scalars().all()}

    hit_entity_ids = [hit["entity_id"] for hit in hits if hit.get("entity_id")]
    entities_by_id: dict[str, Entity] = {}
    states_by_id: dict[str, dict] = {}
    serialized_by_id: dict[str, dict] = {}
    if hit_entity_ids:
        entity_result = await session.execute(
            select(Entity).where(Entity.id.in_(hit_entity_ids))
        )
        entity_rows = entity_result.scalars().all()
        entities_by_id = {entity.id: entity for entity in entity_rows}
        svc = EntityService(session)
        states_by_id = await svc.get_latest_states(hit_entity_ids)
        for entity_id, entity in entities_by_id.items():
            payload = await _serialize_entity_payload(session, entity)
            payload["latest_state"] = states_by_id.get(entity_id)
            serialized_by_id[entity_id] = payload

    grouped_items: list[dict] = []
    group_index_by_key: dict[tuple[str, str], int] = {}
    for hit in hits:
        effective_category, effective_group_id, group = _effective_search_classification(hit, groups_by_id)
        group_key = (effective_category, effective_group_id or "__ungrouped__")
        if group_key not in group_index_by_key:
            group_index_by_key[group_key] = len(grouped_items)
            grouped_items.append({
                "category": effective_category,
                "group_id": effective_group_id,
                "group_slug": group.group_slug if group else None,
                "group_name": group.group_name if group else None,
                "entities": [],
            })
        entity_payload = dict(serialized_by_id.get(hit.get("entity_id"), {}))
        entity_payload["score"] = hit.get("score")
        entity_payload["match_reason"] = hit.get("match_reason")
        grouped_items[group_index_by_key[group_key]]["entities"].append(entity_payload)

    return {"items": grouped_items}


@router.get("/api/novels/{novel_id}/entities/{entity_id}")
async def get_entity(novel_id: str, entity_id: str, session: AsyncSession = Depends(get_session)):
    entity_repo = EntityRepository(session)
    entity = await entity_repo.get_by_id(entity_id)
    if entity is None or entity.novel_id != novel_id:
        raise HTTPException(status_code=404, detail="Entity not found")
    svc = EntityService(session)
    state = await svc.get_latest_state(entity_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    payload = await _serialize_entity_payload(session, entity)
    payload["latest_state"] = state
    payload.update(_entity_scope_from_state(state))
    payload["aliases"] = _normalize_aliases(state.get("aliases") if state else None)
    return payload


@router.patch("/api/novels/{novel_id}/entities/{entity_id}")
async def update_entity(
    novel_id: str,
    entity_id: str,
    req: EntityUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    svc = EntityService(session)
    entity_repo = EntityRepository(session)
    entity = await entity_repo.get_by_id(entity_id)
    if entity is None or entity.novel_id != novel_id:
        raise HTTPException(status_code=404, detail="Entity not found")

    try:
        updated = await svc.update_entity_fields(
            entity_id,
            name=req.name,
            entity_type=req.type,
            aliases=req.aliases,
            state_fields=req.state_fields,
        )
        await session.commit()
    except ValueError as e:
        detail = str(e)
        status_code = 404 if "not found" in detail.lower() else 409
        raise HTTPException(status_code=status_code, detail=detail)

    state = await svc.get_latest_state(entity_id)
    payload = await _serialize_entity_payload(session, updated)
    payload["latest_state"] = state
    payload["aliases"] = _normalize_aliases(state.get("aliases") if state else None)
    return payload


@router.delete("/api/novels/{novel_id}/entities/{entity_id}")
async def delete_entity(
    novel_id: str,
    entity_id: str,
    session: AsyncSession = Depends(get_session),
):
    svc = EntityService(session)
    entity_repo = EntityRepository(session)
    entity = await entity_repo.get_by_id(entity_id)
    if entity is None or entity.novel_id != novel_id:
        raise HTTPException(status_code=404, detail="Entity not found")

    try:
        await svc.delete_entity(entity_id)
        await session.commit()
    except ValueError as e:
        detail = str(e)
        status_code = 404 if "not found" in detail.lower() else 409
        raise HTTPException(status_code=status_code, detail=detail)

    return {"deleted": True, "entity_id": entity_id}


@router.post("/api/novels/{novel_id}/entities/{entity_id}/classification")
async def update_entity_classification(
    novel_id: str,
    entity_id: str,
    req: EntityClassificationUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    entity_repo = EntityRepository(session)
    entity = await entity_repo.get_by_id(entity_id)
    if entity is None or entity.novel_id != novel_id:
        raise HTTPException(status_code=404, detail="Entity not found")

    if req.clear_manual_override:
        await entity_repo.update_classification(
            entity_id,
            manual_category=None,
            manual_group_id=None,
        )
    else:
        has_manual_update = (
            req.manual_category is not None
            or req.manual_group_slug is not None
            or req.manual_group_name is not None
        )
        if has_manual_update:
            current_effective_category, _, _ = _effective_search_classification(
                {
                    "manual_category": entity.manual_category,
                    "manual_group_id": entity.manual_group_id,
                    "system_category": entity.system_category,
                    "system_group_id": entity.system_group_id,
                },
                {},
            )
            target_manual_category = req.manual_category
            if target_manual_category is None and (req.manual_group_slug or req.manual_group_name):
                target_manual_category = current_effective_category

            manual_group = None
            if req.manual_group_slug:
                if not target_manual_category:
                    raise HTTPException(status_code=422, detail="manual_category is required when manual_group_slug is provided")
                group_result = await session.execute(
                    select(EntityGroup).where(
                        EntityGroup.novel_id == novel_id,
                        EntityGroup.category == target_manual_category,
                        EntityGroup.group_slug == req.manual_group_slug,
                    )
                )
                manual_group = group_result.scalar_one_or_none()
                if manual_group is None:
                    manual_group = await EntityService(session).group_repo.upsert(
                        novel_id=novel_id,
                        category=target_manual_category,
                        group_name=(req.manual_group_name or req.manual_group_slug).strip(),
                        group_slug=req.manual_group_slug,
                        source="custom",
                    )

            await entity_repo.update_classification(
                entity_id,
                manual_category=target_manual_category,
                manual_group_id=manual_group.id if manual_group else None,
            )

    if req.reclassify:
        embedding_service = EmbeddingService(session, llm_factory.get_embedder())
        await EntityService(session, embedding_service=embedding_service)._refresh_entity_artifacts(entity_id)
    else:
        embedding_service = EmbeddingService(session, llm_factory.get_embedder())
        await embedding_service.index_entity_search(entity_id)
    await session.commit()

    updated = await entity_repo.get_by_id(entity_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return await _serialize_entity_payload(session, updated)


@router.post("/api/novels/{novel_id}/entities/reclassify")
async def reclassify_entities_for_novel(novel_id: str, session: AsyncSession = Depends(get_session)):
    service = EntityService(session)
    result = await service.reclassify_entities_for_novel(novel_id)
    await session.commit()
    return result


@router.get("/api/novels/{novel_id}/entity_relationships")
async def list_entity_relationships(
    novel_id: str,
    include_archived: bool = False,
    session: AsyncSession = Depends(get_session),
):
    relationship_filters = [
        EntityRelationship.novel_id == novel_id,
        EntityRelationship.is_active.is_(True),
    ]
    if not include_archived:
        relationship_filters.append(EntityRelationship.archived_at.is_(None))
    result = await session.execute(
        select(EntityRelationship)
        .where(*relationship_filters)
        .order_by(EntityRelationship.id)
    )
    items = [
        {
            "id": rel.id,
            "source_id": rel.source_id,
            "target_id": rel.target_id,
            "relation_type": rel.relation_type,
            "meta": rel.meta,
            "created_at_chapter_id": rel.created_at_chapter_id,
            "is_active": rel.is_active,
            "is_inferred": False,
            "archived_at": _isoformat(rel.archived_at),
            "archive_reason": rel.archive_reason,
            "archived_by_consolidation_batch_id": rel.archived_by_consolidation_batch_id,
            "archived_by_consolidation_change_id": rel.archived_by_consolidation_change_id,
        }
        for rel in result.scalars().all()
    ]
    entity_filters = [Entity.novel_id == novel_id]
    if not include_archived:
        entity_filters.append(Entity.archived_at.is_(None))
    entities_result = await session.execute(
        select(Entity).where(*entity_filters).order_by(Entity.name)
    )
    entities = list(entities_result.scalars().all())
    if not include_archived:
        visible_entity_ids = {entity.id for entity in entities}
        items = [
            item for item in items
            if item["source_id"] in visible_entity_ids and item["target_id"] in visible_entity_ids
        ]
    svc = EntityService(session)
    states = await svc.get_latest_states([ent.id for ent in entities])
    entity_rows = [
        {
            "entity_id": ent.id,
            "type": ent.type,
            "name": ent.name,
            "latest_state": states.get(ent.id),
        }
        for ent in entities
    ]
    entity_scope_keys = {
        row["entity_id"]: _inference_domain_key(row)
        for row in entity_rows
    }
    scopes_with_explicit_relationships = set()
    for item in items:
        source_scope = entity_scope_keys.get(item["source_id"])
        target_scope = entity_scope_keys.get(item["target_id"])
        if source_scope == target_scope:
            scopes_with_explicit_relationships.add(source_scope)
        else:
            scopes_with_explicit_relationships.update(scope for scope in (source_scope, target_scope) if scope is not None)
    explicit_keys = {
        (item["source_id"], item["target_id"], item["relation_type"])
        for item in items
    }
    for inferred in _build_inferred_relationships(entity_rows):
        if entity_scope_keys.get(inferred["source_id"]) in scopes_with_explicit_relationships:
            continue
        dedup_key = (inferred["source_id"], inferred["target_id"], inferred["relation_type"])
        if dedup_key not in explicit_keys:
            items.append(inferred)
            explicit_keys.add(dedup_key)
    return {"items": items}


@router.get("/api/novels/{novel_id}/timelines")
async def list_timelines(novel_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Timeline).where(Timeline.novel_id == novel_id).order_by(Timeline.tick)
    )
    items = [
        {
            "id": t.id,
            "tick": t.tick,
            "narrative": t.narrative,
            "anchor_chapter_id": t.anchor_chapter_id,
            "anchor_event_id": t.anchor_event_id,
        }
        for t in result.scalars().all()
    ]
    return {"items": items}


@router.get("/api/novels/{novel_id}/spacelines")
async def list_spacelines(novel_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Spaceline).where(Spaceline.novel_id == novel_id).order_by(Spaceline.name)
    )
    items = [
        {
            "id": s.id,
            "name": s.name,
            "parent_id": s.parent_id,
            "narrative": s.narrative,
            "meta": s.meta,
        }
        for s in result.scalars().all()
    ]
    return {"items": items}


@router.get("/api/novels/{novel_id}/foreshadowings")
async def list_foreshadowings(novel_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Foreshadowing).where(Foreshadowing.novel_id == novel_id).order_by(Foreshadowing.id)
    )
    items = [
        {
            "id": f.id,
            "content": f.content,
            "埋下_chapter_id": f.埋下_chapter_id,
            "埋下_time_tick": f.埋下_time_tick,
            "回收状态": f.回收状态,
            "回收条件": f.回收条件,
            "recovered_chapter_id": f.recovered_chapter_id,
        }
        for f in result.scalars().all()
    ]
    return {"items": items}


@router.get("/api/novels/{novel_id}/chapters")
async def list_chapters(novel_id: str, session: AsyncSession = Depends(get_session)):
    state_repo = NovelStateRepository(session)
    state = await state_repo.get_state(novel_id)
    plan_chapters = []
    if state and state.checkpoint_data:
        volume_plan = state.checkpoint_data.get("current_volume_plan", {})
        plan_chapters = volume_plan.get("chapters", [])

    chapter_ids = [c.get("chapter_id") for c in plan_chapters if c.get("chapter_id")]
    db_chapters = {}
    if chapter_ids:
        result = await session.execute(select(Chapter).where(Chapter.id.in_(chapter_ids)))
        for ch in result.scalars().all():
            db_chapters[ch.id] = ch

    items = []
    for pc in plan_chapters:
        cid = pc.get("chapter_id")
        ch = db_chapters.get(cid)
        word_count = _word_count(ch.polished_text or ch.raw_draft) if ch else 0
        items.append({
            "chapter_id": cid,
            "volume_id": pc.get("volume_id") or (ch.volume_id if ch else None),
            "volume_number": pc.get("volume_number", 1),
            "chapter_number": pc.get("chapter_number"),
            "title": pc.get("title"),
            "summary": pc.get("summary"),
            "status": ch.status if ch else "pending",
            "word_count": word_count,
            "score_overall": ch.score_overall if ch else None,
            "display_score": (
                ch.final_review_score
                if ch and ch.final_review_score is not None
                else (ch.score_overall if ch else None)
            ),
            "score_breakdown": ch.score_breakdown if ch else {},
            "review_feedback": ch.review_feedback if ch else {},
            "fast_review_score": ch.fast_review_score if ch else None,
            "fast_review_feedback": ch.fast_review_feedback if ch else {},
            "draft_review_score": ch.draft_review_score if ch else None,
            "draft_review_feedback": ch.draft_review_feedback if ch else {},
            "final_review_score": ch.final_review_score if ch else None,
            "final_review_feedback": ch.final_review_feedback if ch else {},
            "quality_status": ch.quality_status if ch else "unchecked",
            "quality_reasons": ch.quality_reasons if ch else {},
            "quality_checked_at": ch.quality_checked_at.isoformat() if ch and ch.quality_checked_at else None,
            "world_state_ingested": bool(ch.world_state_ingested) if ch else False,
        })
    return {"items": items}


@router.get("/api/novels/{novel_id}/chapters/rewrite_jobs")
async def list_chapter_rewrite_jobs(novel_id: str, session: AsyncSession = Depends(get_session)):
    state = await NovelStateRepository(session).get_state(novel_id)
    if not state:
        raise HTTPException(status_code=404, detail="Novel state not found")
    jobs = await GenerationJobRepository(session).list_latest_by_chapter(novel_id, CHAPTER_REWRITE_JOB)
    return {
        "novel_id": novel_id,
        "items": [
            {
                "chapter_id": chapter_id,
                "job": _generation_job_response(job),
            }
            for chapter_id, job in jobs
        ],
    }


@router.get("/api/novels/{novel_id}/chapters/{chapter_id}")
async def get_chapter(novel_id: str, chapter_id: str, session: AsyncSession = Depends(get_session)):
    repo = ChapterRepository(session)
    ch = await repo.get_by_id(chapter_id)
    if not ch:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return {
        "id": ch.id,
        "volume_id": ch.volume_id,
        "chapter_number": ch.chapter_number,
        "title": ch.title,
        "status": ch.status,
        "score_overall": ch.score_overall,
        "display_score": ch.final_review_score if ch.final_review_score is not None else ch.score_overall,
        "draft_review_score": ch.draft_review_score,
        "draft_review_feedback": ch.draft_review_feedback,
        "final_review_score": ch.final_review_score,
        "final_review_feedback": ch.final_review_feedback,
        "quality_status": ch.quality_status,
        "quality_reasons": ch.quality_reasons,
        "quality_checked_at": ch.quality_checked_at.isoformat() if ch.quality_checked_at else None,
        "world_state_ingested": ch.world_state_ingested,
    }


@router.get("/api/novels/{novel_id}/chapters/{chapter_id}/quality")
async def get_chapter_quality(novel_id: str, chapter_id: str, session: AsyncSession = Depends(get_session)):
    repo = ChapterRepository(session)
    ch = await repo.get_by_id(chapter_id)
    if not ch or ch.novel_id not in {None, novel_id}:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return {
        "chapter_id": ch.id,
        "quality_status": ch.quality_status,
        "quality_reasons": ch.quality_reasons or {},
        "quality_checked_at": ch.quality_checked_at.isoformat() if ch.quality_checked_at else None,
        "draft_review_score": ch.draft_review_score,
        "draft_review_feedback": ch.draft_review_feedback or {},
        "final_review_score": ch.final_review_score,
        "final_review_feedback": ch.final_review_feedback or {},
        "fast_review_score": ch.fast_review_score,
        "fast_review_feedback": ch.fast_review_feedback or {},
        "world_state_ingested": ch.world_state_ingested,
    }


@router.get("/api/novels/{novel_id}/chapters/{chapter_id}/text")
async def get_chapter_text(novel_id: str, chapter_id: str, session: AsyncSession = Depends(get_session)):
    repo = ChapterRepository(session)
    ch = await repo.get_by_id(chapter_id)
    if not ch:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return {
        "chapter_id": ch.id,
        "title": ch.title,
        "status": ch.status,
        "raw_draft": ch.raw_draft,
        "polished_text": ch.polished_text,
        "word_count": _word_count(ch.polished_text or ch.raw_draft),
    }


@router.get("/api/novels/{novel_id}/chapters/{chapter_id}/export.md")
async def export_chapter(novel_id: str, chapter_id: str, session: AsyncSession = Depends(get_session)):
    repo = ChapterRepository(session)
    ch = await repo.get_by_id(chapter_id)
    if not ch or ch.novel_id != novel_id or not ch.polished_text:
        raise HTTPException(status_code=404, detail="Chapter content not found")
    sync = MarkdownSync(storage_paths=StoragePaths(settings.data_dir))
    path = await sync.write_chapter(novel_id, ch.volume_id, chapter_id, ch.polished_text)
    return {"exported_path": path, "content": ch.polished_text}


class UploadRequest(BaseModel):
    filename: str
    content: str
    knowledge_usage: str | None = None
    domain_name: str | None = None
    activation_mode: str | None = None


class BatchUploadRequest(BaseModel):
    items: list[UploadRequest] = Field(min_length=1)
    max_concurrency: int | None = Field(default=None, ge=1, le=8)


class FieldResolution(BaseModel):
    entity_type: str
    entity_name: str
    field: str
    action: str
    merged_value: str | None = None


class ApproveRequest(BaseModel):
    pending_id: str
    field_resolutions: list[FieldResolution] = Field(default_factory=list)


class RollbackRequest(BaseModel):
    version: int


async def _process_upload_with_new_session(
    novel_id: str,
    req: UploadRequest,
    embedder,
) -> dict:
    async with async_session_maker() as session:
        embedding_service = EmbeddingService(session, embedder)
        svc = ExtractionService(session, embedding_service)
        try:
            pe = await svc.process_upload(
                novel_id,
                req.filename,
                req.content,
                force_setting=(req.knowledge_usage or "").strip() == "domain",
            )
            await session.commit()
            return {
                "filename": req.filename,
                "pending_id": pe.id,
                "status": pe.status,
                "error": None,
            }
        except LLMTimeoutError:
            await session.rollback()
            return {
                "filename": req.filename,
                "pending_id": None,
                "status": "failed",
                "error": "设定提取超时，请稍后重试或切换模型",
            }
        except Exception as exc:
            await session.rollback()
            return {
                "filename": req.filename,
                "pending_id": None,
                "status": "failed",
                "error": str(exc) or "导入失败",
            }


async def _complete_processing_upload_with_new_session(
    pending_id: str,
    novel_id: str,
    req: UploadRequest,
    embedder,
) -> None:
    async with async_session_maker() as session:
        embedding_service = EmbeddingService(session, embedder)
        svc = ExtractionService(session, embedding_service)
        repo = PendingExtractionRepository(session)
        try:
            is_domain_import = (req.knowledge_usage or "").strip() == "domain"
            if is_domain_import:
                await svc.complete_processing_upload(
                    pending_id,
                    novel_id,
                    req.filename,
                    req.content,
                    force_setting=True,
                )
            else:
                await svc.complete_processing_upload(pending_id, novel_id, req.filename, req.content)
            pending_after_extract = await repo.get_by_id(pending_id)
            if pending_after_extract is None:
                await session.commit()
                return
            if is_domain_import:
                domain_service = KnowledgeDomainService(session)
                draft = domain_service.create_domain_draft_from_document(
                    name=req.domain_name or req.filename,
                    doc_id=pending_id,
                    content=req.content,
                    domain_type="source_work",
                    activation_mode=req.activation_mode or "auto",
                )
                await domain_service.create_domain(novel_id, draft)
            await session.commit()
        except LLMTimeoutError:
            await session.rollback()
            await repo.update_status(
                pending_id,
                "failed",
                error_message="设定提取超时，请稍后重试或切换模型",
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            await repo.update_status(
                pending_id,
                "failed",
                error_message=str(exc) or "导入失败",
            )
            await session.commit()


@router.post("/api/novels/{novel_id}/documents/upload")
async def upload_document(novel_id: str, req: UploadRequest, session: AsyncSession = Depends(get_session)):
    embedder = llm_factory.get_embedder()
    embedding_service = EmbeddingService(session, embedder)
    svc = ExtractionService(session, embedding_service)
    try:
        pe = await svc.process_upload(
            novel_id,
            req.filename,
            req.content,
            force_setting=(req.knowledge_usage or "").strip() == "domain",
        )
    except LLMTimeoutError as exc:
        raise HTTPException(status_code=504, detail="设定提取超时，请稍后重试或切换模型") from exc
    created_domain = None
    if (req.knowledge_usage or "").strip() == "domain":
        domain_service = KnowledgeDomainService(session)
        draft = domain_service.create_domain_draft_from_document(
            name=req.domain_name or req.filename,
            doc_id=pe.id,
            content=req.content,
            domain_type="source_work",
            activation_mode=req.activation_mode or "auto",
        )
        created_domain = await domain_service.create_domain(novel_id, draft)
    await session.commit()
    return {
        "id": pe.id,
        "source_filename": pe.source_filename,
        "extraction_type": pe.extraction_type,
        "status": pe.status,
        "created_at": pe.created_at.isoformat(),
        "knowledge_domain": serialize_knowledge_domain(created_domain) if created_domain else None,
    }


@router.post("/api/novels/{novel_id}/documents/upload/batch")
async def upload_documents_batch(
    novel_id: str,
    req: BatchUploadRequest,
):
    embedder = llm_factory.get_embedder()
    async with async_session_maker() as session:
        embedding_service = EmbeddingService(session, embedder)
        svc = ExtractionService(session, embedding_service)
        accepted_items = []
        for item in req.items:
            pe = await svc.create_processing_upload(novel_id, item.filename)
            accepted_items.append(
                {
                    "filename": item.filename,
                    "pending_id": pe.id,
                    "status": pe.status,
                    "error": None,
                }
            )
        await session.commit()

    max_concurrency = min(req.max_concurrency or 3, 8)
    semaphore = asyncio.Semaphore(max_concurrency)

    async def run_one(item: UploadRequest, pending_id: str) -> None:
        async with semaphore:
            await _complete_processing_upload_with_new_session(pending_id, novel_id, item, embedder)

    for item, accepted in zip(req.items, accepted_items):
        task = asyncio.create_task(run_one(item, accepted["pending_id"]))
        document_upload_tasks.add(task)
        task.add_done_callback(document_upload_tasks.discard)

    return {
        "total": len(accepted_items),
        "accepted": len(accepted_items),
        "failed": 0,
        "items": accepted_items,
    }


@router.get("/api/novels/{novel_id}/documents/pending")
async def get_pending_documents(novel_id: str, session: AsyncSession = Depends(get_session)):
    repo = PendingExtractionRepository(session)
    items = await repo.list_by_novel(novel_id)
    return {
        "items": [_serialize_pending_document(i) for i in items]
    }


@router.get("/api/novels/{novel_id}/documents/library")
async def get_document_library(novel_id: str, session: AsyncSession = Depends(get_session)):
    repo = DocumentRepository(session)
    extraction_service = ExtractionService(session)

    worldview_docs = _active_documents(await repo.get_by_type(novel_id, "worldview"))
    setting_docs = _active_documents(await repo.get_by_type(novel_id, "setting"))
    synopsis_docs = _active_documents(await repo.get_by_type(novel_id, "synopsis"))
    concept_docs = _active_documents(await repo.get_by_type(novel_id, "concept"))
    style_docs = _active_documents(await repo.get_by_type(novel_id, "style_profile"))
    active_style_doc = await extraction_service.get_active_style_profile(novel_id)
    if active_style_doc and active_style_doc.archived_at is not None:
        active_style_doc = None

    items = [
        *[_serialize_library_document(doc) for doc in _latest_documents_by_title(worldview_docs)],
        *[_serialize_library_document(doc) for doc in _latest_documents_by_title(setting_docs)],
        *[_serialize_library_document(doc) for doc in _latest_documents_by_title(synopsis_docs)],
        *[_serialize_library_document(doc) for doc in _latest_documents_by_title(concept_docs)],
        *[
            _serialize_library_document(doc, is_active=bool(active_style_doc and doc.id == active_style_doc.id))
            for doc in style_docs
        ],
    ]
    return {
        "items": items,
        "active_style_profile_version": active_style_doc.version if active_style_doc else None,
    }


@router.get("/api/novels/{novel_id}/knowledge_domains")
async def list_knowledge_domains(
    novel_id: str,
    include_disabled: bool = False,
    session: AsyncSession = Depends(get_session),
):
    svc = KnowledgeDomainService(session)
    domains = await svc.repo.list_by_novel(novel_id, include_disabled=include_disabled)
    return {"items": [serialize_knowledge_domain(domain) for domain in domains]}


@router.post("/api/novels/{novel_id}/knowledge_domains")
async def create_knowledge_domain(
    novel_id: str,
    req: KnowledgeDomainCreate,
    session: AsyncSession = Depends(get_session),
):
    svc = KnowledgeDomainService(session)
    domain = await svc.create_domain(novel_id, req)
    await session.commit()
    return {"item": serialize_knowledge_domain(domain)}


@router.patch("/api/novels/{novel_id}/knowledge_domains/{domain_id}")
async def update_knowledge_domain(
    novel_id: str,
    domain_id: str,
    req: KnowledgeDomainUpdate,
    session: AsyncSession = Depends(get_session),
):
    svc = KnowledgeDomainService(session)
    try:
        domain = await svc.update_domain(novel_id, domain_id, req)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return {"item": serialize_knowledge_domain(domain)}


@router.post("/api/novels/{novel_id}/knowledge_domains/{domain_id}/confirm_scope")
async def confirm_knowledge_domain_scope(
    novel_id: str,
    domain_id: str,
    req: ConfirmDomainScopeRequest,
    session: AsyncSession = Depends(get_session),
):
    svc = KnowledgeDomainService(session)
    try:
        domain = await svc.confirm_scope(novel_id, domain_id, req.scope_type, req.scope_refs)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return {"item": serialize_knowledge_domain(domain)}


@router.post("/api/novels/{novel_id}/knowledge_domains/{domain_id}/disable")
async def disable_knowledge_domain(
    novel_id: str,
    domain_id: str,
    session: AsyncSession = Depends(get_session),
):
    svc = KnowledgeDomainService(session)
    try:
        domain = await svc.update_domain(
            novel_id,
            domain_id,
            KnowledgeDomainUpdate(is_active=False, scope_status="disabled", activation_mode="disabled"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return {"item": serialize_knowledge_domain(domain)}


@router.delete("/api/novels/{novel_id}/knowledge_domains/{domain_id}")
async def delete_knowledge_domain(
    novel_id: str,
    domain_id: str,
    session: AsyncSession = Depends(get_session),
):
    svc = KnowledgeDomainService(session)
    try:
        result = await svc.delete_domain(novel_id, domain_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return result


@router.post("/api/novels/{novel_id}/documents/library/merge-duplicates")
async def merge_duplicate_library_documents(novel_id: str, session: AsyncSession = Depends(get_session)):
    embedder = llm_factory.get_embedder()
    embedding_service = EmbeddingService(session, embedder)
    svc = ExtractionService(session, embedding_service)
    merged_docs = await svc.merge_existing_library_duplicates(novel_id)
    await session.commit()
    return {
        "merged": [
            {
                "id": doc.id,
                "doc_type": doc.doc_type,
                "title": doc.title,
                "version": doc.version,
                "content": doc.content[:500],
            }
            for doc in merged_docs
        ]
    }


@router.post("/api/novels/{novel_id}/documents/pending/approve")
async def approve_pending_document(novel_id: str, req: ApproveRequest, session: AsyncSession = Depends(get_session)):
    embedder = llm_factory.get_embedder()
    embedding_service = EmbeddingService(session, embedder)
    svc = ExtractionService(session, embedding_service)
    repo = PendingExtractionRepository(session)
    pe = await repo.get_by_id(req.pending_id)
    if not pe:
        await session.commit()
        return
    if pe.novel_id != novel_id:
        raise HTTPException(status_code=403, detail="Pending extraction does not belong to this novel")
    try:
        docs = await svc.approve_pending(req.pending_id, field_resolutions=[r.model_dump() for r in req.field_resolutions])
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"自动合并失败: {exc}") from exc
    await session.commit()
    return {
        "documents": [
            {
                "id": d.id,
                "doc_type": d.doc_type,
                "title": d.title,
                "content": d.content[:500],
                "version": d.version,
            }
            for d in docs
        ]
    }


@router.patch("/api/novels/{novel_id}/documents/pending/{pending_id}/draft-field")
async def update_pending_draft_field(
    novel_id: str,
    pending_id: str,
    req: UpdatePendingDraftFieldRequest,
    session: AsyncSession = Depends(get_session),
):
    embedder = llm_factory.get_embedder()
    embedding_service = EmbeddingService(session, embedder)
    svc = ExtractionService(session, embedding_service)
    repo = PendingExtractionRepository(session)
    pe = await repo.get_by_id(pending_id)
    if not pe:
        await session.commit()
        return
    if pe.novel_id != novel_id:
        raise HTTPException(status_code=403, detail="Pending extraction does not belong to this novel")

    try:
        updated = await svc.update_pending_draft_field(
            pending_id=pending_id,
            entity_type=req.entity_type,
            entity_name=req.entity_name,
            field=req.field,
            value=req.value,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await session.commit()
    return {"item": _serialize_pending_document(updated)}


@router.patch("/api/novels/{novel_id}/documents/library/{doc_id}")
async def update_library_document(
    novel_id: str,
    doc_id: str,
    req: UpdateLibraryDocumentRequest,
    session: AsyncSession = Depends(get_session),
):
    embedder = llm_factory.get_embedder()
    embedding_service = EmbeddingService(session, embedder)
    svc = ExtractionService(session, embedding_service)
    try:
        updated = await svc.update_library_document(novel_id, doc_id=doc_id, content=req.content)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    active_style_doc = await svc.get_active_style_profile(novel_id) if updated.doc_type == "style_profile" else None
    await session.commit()
    return {
        "item": _serialize_library_document(
            updated,
            is_active=bool(updated.doc_type != "style_profile" or (active_style_doc and active_style_doc.id == updated.id)),
        )
    }


@router.post("/api/novels/{novel_id}/documents/pending/reject", status_code=204)
async def reject_pending_document(novel_id: str, req: RejectPendingRequest, session: AsyncSession = Depends(get_session)):
    embedder = llm_factory.get_embedder()
    embedding_service = EmbeddingService(session, embedder)
    svc = ExtractionService(session, embedding_service)
    repo = PendingExtractionRepository(session)
    pe = await repo.get_by_id(req.pending_id)
    if not pe or pe.novel_id != novel_id:
        raise HTTPException(status_code=403, detail="Pending extraction does not belong to this novel")
    deleted = await svc.reject_pending(req.pending_id)
    if not deleted:
        raise HTTPException(status_code=409, detail="待审核记录已不可拒绝")
    await session.commit()


@router.delete("/api/novels/{novel_id}/documents/pending/{pending_id}", status_code=204)
async def delete_failed_pending_document(novel_id: str, pending_id: str, session: AsyncSession = Depends(get_session)):
    embedder = llm_factory.get_embedder()
    embedding_service = EmbeddingService(session, embedder)
    svc = ExtractionService(session, embedding_service)
    repo = PendingExtractionRepository(session)
    pe = await repo.get_by_id(pending_id)
    if not pe:
        await session.commit()
        return
    if pe.novel_id != novel_id:
        raise HTTPException(status_code=403, detail="Pending extraction does not belong to this novel")
    deleted = await svc.delete_cancelable_pending(pending_id)
    if not deleted:
        raise HTTPException(status_code=409, detail="只有导入中或失败记录可以删除")
    await session.commit()


@router.get("/api/novels/{novel_id}/style_profile/versions")
async def list_style_profile_versions(novel_id: str, session: AsyncSession = Depends(get_session)):
    repo = DocumentRepository(session)
    docs = await repo.get_by_type(novel_id, "style_profile")
    return {
        "versions": [
            {
                "version": d.version,
                "updated_at": d.updated_at.isoformat(),
                "title": d.title,
            }
            for d in docs
        ]
    }


@router.post("/api/novels/{novel_id}/style_profile/rollback")
async def rollback_style_profile(novel_id: str, req: RollbackRequest, session: AsyncSession = Depends(get_session)):
    embedder = llm_factory.get_embedder()
    embedding_service = EmbeddingService(session, embedder)
    svc = ExtractionService(session, embedding_service)
    await svc.rollback_style_profile(novel_id, req.version)
    await session.commit()
    return {"rolled_back_to_version": req.version}


class SaveDocumentVersionRequest(BaseModel):
    title: str
    content: str


@router.get("/api/novels/{novel_id}/documents")
async def list_approved_documents(novel_id: str, doc_type: Optional[str] = None, session: AsyncSession = Depends(get_session)):
    repo = DocumentRepository(session)
    docs = await repo.list_by_novel(novel_id, doc_type=doc_type)
    return {
        "items": [
            {
                "id": d.id,
                "doc_type": d.doc_type,
                "title": d.title,
                "version": d.version,
                "updated_at": d.updated_at.isoformat() if d.updated_at else None,
                "content_preview": (d.content or "")[:200],
                "word_count": _word_count(d.content),
                "has_embedding": d.vector_embedding is not None,
            }
            for d in docs
        ]
    }


@router.get("/api/novels/{novel_id}/documents/{document_id}")
async def get_document_detail(novel_id: str, document_id: str, session: AsyncSession = Depends(get_session)):
    svc = ExtractionService(session)
    doc = await svc.get_approved_document(novel_id, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "id": doc.id,
        "doc_type": doc.doc_type,
        "title": doc.title,
        "content": doc.content,
        "version": doc.version,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
        "has_embedding": doc.vector_embedding is not None,
    }


@router.get("/api/novels/{novel_id}/documents/types/{doc_type}/versions")
async def list_document_versions(novel_id: str, doc_type: str, session: AsyncSession = Depends(get_session)):
    svc = ExtractionService(session)
    docs = await svc.list_document_versions(novel_id, doc_type)
    return {
        "items": [
            {
                "id": d.id,
                "title": d.title,
                "version": d.version,
                "updated_at": d.updated_at.isoformat() if d.updated_at else None,
            }
            for d in docs
        ]
    }


@router.get("/api/novels/{novel_id}/documents/{document_id}/versions")
async def list_document_versions_for_document(novel_id: str, document_id: str, session: AsyncSession = Depends(get_session)):
    svc = ExtractionService(session)
    doc = await svc.get_approved_document(novel_id, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    docs = await svc.list_document_versions_for_document(novel_id, document_id)
    return {
        "items": [
            {
                "id": d.id,
                "title": d.title,
                "version": d.version,
                "updated_at": d.updated_at.isoformat() if d.updated_at else None,
            }
            for d in docs
        ]
    }


@router.post("/api/novels/{novel_id}/documents/{document_id}/versions")
async def save_document_version(novel_id: str, document_id: str, req: SaveDocumentVersionRequest, session: AsyncSession = Depends(get_session)):
    if not req.title.strip() or not req.content.strip():
        raise HTTPException(status_code=422, detail="title and content are required")
    embedder = llm_factory.get_embedder()
    embedding_service = EmbeddingService(session, embedder)
    svc = ExtractionService(session, embedding_service)
    doc = await svc.save_document_version(novel_id, document_id, req.title, req.content)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    await session.commit()
    return {
        "id": doc.id,
        "doc_type": doc.doc_type,
        "title": doc.title,
        "version": doc.version,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }


@router.post("/api/novels/{novel_id}/documents/{document_id}/reindex")
async def reindex_document(novel_id: str, document_id: str, session: AsyncSession = Depends(get_session)):
    embedder = llm_factory.get_embedder()
    embedding_service = EmbeddingService(session, embedder)
    svc = ExtractionService(session, embedding_service)
    doc = await svc.reindex_document(novel_id, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    await session.commit()
    return {"id": doc.id, "reindexed": True}


@router.post("/api/novels/{novel_id}/chapters/{chapter_id}/context")
async def prepare_chapter_context(
    novel_id: str,
    chapter_id: str,
    session: AsyncSession = Depends(get_session),
):
    await FlowControlService(session).clear_stop(novel_id)
    embedder = llm_factory.get_embedder()
    embedding_service = EmbeddingService(session, embedder)
    agent = ContextAgent(session, embedding_service)
    try:
        context = await agent.assemble(novel_id, chapter_id)
    except FlowCancelledError:
        await _raise_flow_cancelled(session, novel_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await session.commit()
    return {
        "chapter_plan_title": context.chapter_plan.title,
        "active_entities_count": len(context.active_entities),
        "pending_foreshadowings_count": len(context.pending_foreshadowings),
        "timeline_events_count": len(context.timeline_events),
    }


@router.post("/api/novels/{novel_id}/chapters/{chapter_id}/draft")
async def generate_chapter_draft(
    novel_id: str,
    chapter_id: str,
    session: AsyncSession = Depends(get_session),
):
    await FlowControlService(session).clear_stop(novel_id)
    state_repo = NovelStateRepository(session)
    state = await state_repo.get_state(novel_id)
    if not state:
        raise HTTPException(status_code=404, detail="Novel state not found")

    checkpoint = state.checkpoint_data or {}
    context_data = checkpoint.get("chapter_context")
    if not context_data:
        raise HTTPException(status_code=400, detail="Chapter context not prepared. Call POST /context first.")

    context = ChapterContext.model_validate(context_data)
    embedder = llm_factory.get_embedder()
    embedding_service = EmbeddingService(session, embedder)
    agent = WriterAgent(session, embedding_service)
    try:
        metadata = await agent.write(novel_id, context, chapter_id)
    except FlowCancelledError:
        await _raise_flow_cancelled(session, novel_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await session.commit()
    return metadata.model_dump()


@router.get("/api/novels/{novel_id}/chapters/{chapter_id}/draft")
async def get_chapter_draft(
    novel_id: str,
    chapter_id: str,
    session: AsyncSession = Depends(get_session),
):
    repo = ChapterRepository(session)
    ch = await repo.get_by_id(chapter_id)
    if not ch:
        raise HTTPException(status_code=404, detail="Chapter not found")

    state_repo = NovelStateRepository(session)
    state = await state_repo.get_state(novel_id)
    checkpoint = state.checkpoint_data if state else {}

    return {
        "chapter_id": ch.id,
        "status": ch.status,
        "raw_draft": ch.raw_draft,
        "drafting_progress": checkpoint.get("drafting_progress"),
        "draft_metadata": checkpoint.get("draft_metadata"),
    }


@router.post("/api/novels/{novel_id}/advance")
async def advance_novel(novel_id: str, session: AsyncSession = Depends(get_session)):
    await FlowControlService(session).clear_stop(novel_id)
    director = NovelDirector(session)
    try:
        state = await director.advance(novel_id)
    except FlowCancelledError:
        await _raise_flow_cancelled(session, novel_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    await session.commit()
    return {
        "novel_id": state.novel_id,
        "current_phase": state.current_phase,
        "checkpoint_data": state.checkpoint_data,
    }


def _generation_job_response(job) -> dict:
    return {
        "job_id": job.id,
        "novel_id": job.novel_id,
        "job_type": job.job_type,
        "status": job.status,
        "request_payload": job.request_payload,
        "result_payload": job.result_payload,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


@router.post("/api/novels/{novel_id}/chapters/auto-run", status_code=status.HTTP_202_ACCEPTED)
async def auto_run_chapters(
    novel_id: str,
    req: AutoRunChaptersRequest = AutoRunChaptersRequest(),
    session: AsyncSession = Depends(get_session),
):
    state = await NovelStateRepository(session).get_state(novel_id)
    if not state:
        raise HTTPException(status_code=404, detail="Novel state not found")
    await FlowControlService(session).clear_stop(novel_id)
    await RecoveryCleanupService(session).run_cleanup(
        RecoveryCleanupOptions(stale_running_minutes=5, stale_queued_minutes=1)
    )
    repo = GenerationJobRepository(session)
    active = await repo.get_active(novel_id, CHAPTER_AUTO_RUN_JOB)
    if active:
        raise HTTPException(status_code=409, detail="Auto chapter generation is already running")
    payload = {
        "max_chapters": req.max_chapters,
        "stop_at_volume_end": req.stop_at_volume_end,
    }
    job = await repo.create(novel_id, CHAPTER_AUTO_RUN_JOB, payload)
    await session.commit()
    schedule_generation_job(job.id)
    return _generation_job_response(job)


@router.post("/api/novels/{novel_id}/chapters/{chapter_id}/rewrite", status_code=status.HTTP_202_ACCEPTED)
async def rewrite_chapter(
    novel_id: str,
    chapter_id: str,
    req: ChapterRewriteRequest | None = Body(default=None),
    session: AsyncSession = Depends(get_session),
):
    req = req or ChapterRewriteRequest()
    state = await NovelStateRepository(session).get_state(novel_id)
    if not state:
        raise HTTPException(status_code=404, detail="Novel state not found")

    chapter_repo = ChapterRepository(session)
    chapter = await chapter_repo.get_by_id(chapter_id)
    if chapter and chapter.novel_id != novel_id:
        raise HTTPException(status_code=404, detail="Chapter not found")
    if not req.resume and not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    if not req.resume and chapter.status not in {"drafted", "edited", "archived"}:
        raise HTTPException(status_code=409, detail="Only drafted, edited or archived chapters can be rewritten")

    checkpoint = dict(state.checkpoint_data or {})
    volume_plan = checkpoint.get("current_volume_plan") or {}
    plan_chapter_ids = {
        c.get("chapter_id")
        for c in volume_plan.get("chapters", [])
        if isinstance(c, dict) and c.get("chapter_id")
    }
    if chapter_id not in plan_chapter_ids:
        raise HTTPException(status_code=404, detail="Chapter plan not found")

    repo = GenerationJobRepository(session)
    active_rewrite = await repo.get_active(novel_id, CHAPTER_REWRITE_JOB)
    if active_rewrite:
        raise HTTPException(status_code=409, detail="Chapter rewrite is already running")
    active_auto_run = await repo.get_active(novel_id, CHAPTER_AUTO_RUN_JOB)
    if active_auto_run and state.current_chapter_id == chapter_id:
        raise HTTPException(status_code=409, detail="Current chapter is being generated")

    payload = {"chapter_id": chapter_id}
    if req.resume:
        resume_payload = await _build_chapter_rewrite_resume_payload(
            session,
            novel_id,
            chapter_id,
            chapter,
            failed_job_id=req.failed_job_id,
        )
        payload.update(resume_payload)
    elif chapter.status not in {"drafted", "edited", "archived"}:
        raise HTTPException(status_code=409, detail="Only drafted, edited or archived chapters can be rewritten")

    await FlowControlService(session).clear_stop(novel_id)
    job = await repo.create(novel_id, CHAPTER_REWRITE_JOB, payload)
    await session.commit()
    schedule_generation_job(job.id)
    return _generation_job_response(job)


@router.get("/api/novels/{novel_id}/world_state_reviews")
async def list_world_state_reviews(
    novel_id: str,
    status_filter: str | None = Query(default=None, alias="status"),
    session: AsyncSession = Depends(get_session),
):
    reviews = await WorldStateReviewService(session).list_reviews(novel_id, status=status_filter)
    return {"items": [_world_state_review_response(item) for item in reviews]}


@router.post("/api/novels/{novel_id}/world_state_reviews/{review_id}/resolve")
async def resolve_world_state_review(
    novel_id: str,
    review_id: str,
    req: WorldStateReviewResolveRequest,
    session: AsyncSession = Depends(get_session),
):
    service = WorldStateReviewService(session)
    existing = await service.get_review(review_id)
    if not existing or existing.novel_id != novel_id:
        raise HTTPException(status_code=404, detail="World state review not found")
    try:
        review = await service.resolve_review(
            review_id,
            action=req.action,
            edited_extraction=req.edited_extraction,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return _world_state_review_response(review)


@router.post("/api/novels/{novel_id}/global_consistency_audit")
async def run_global_consistency_audit(novel_id: str, session: AsyncSession = Depends(get_session)):
    result = await GlobalConsistencyAuditService(session).run(novel_id)
    return result.model_dump()


async def _build_chapter_rewrite_resume_payload(
    session: AsyncSession,
    novel_id: str,
    chapter_id: str,
    chapter: Chapter | None,
    *,
    failed_job_id: str | None,
) -> dict:
    payload: dict[str, Any] = {
        "resume": True,
    }
    failed_payload: dict[str, Any] = {}
    if failed_job_id:
        failed_job = await GenerationJobRepository(session).get_by_id(failed_job_id)
        if not failed_job or failed_job.novel_id != novel_id or failed_job.job_type != CHAPTER_REWRITE_JOB:
            raise HTTPException(status_code=404, detail="Failed rewrite job not found")
        if failed_job.status != "failed":
            raise HTTPException(status_code=409, detail="Only failed rewrite jobs can be resumed")
        request_chapter_id = (failed_job.request_payload or {}).get("chapter_id")
        result_chapter_id = (failed_job.result_payload or {}).get("chapter_id")
        if request_chapter_id != chapter_id and result_chapter_id != chapter_id:
            raise HTTPException(status_code=409, detail="Failed rewrite job belongs to another chapter")
        failed_payload = dict(failed_job.result_payload or {})
        payload["failed_job_id"] = failed_job_id

    resume_from_stage = failed_payload.get("resume_from_stage") or _infer_chapter_rewrite_resume_stage(chapter)
    if not chapter and resume_from_stage != "context":
        raise HTTPException(status_code=409, detail="Failed rewrite job cannot be resumed without chapter artifacts")
    if chapter and chapter.status == "pending" and resume_from_stage != "context":
        raise HTTPException(status_code=409, detail="Failed rewrite job cannot be resumed from this stage without chapter artifacts")
    if chapter and chapter.status not in {"pending", "drafted", "edited", "archived"}:
        raise HTTPException(status_code=409, detail="Only pending, drafted, edited or archived chapters can resume rewrite")
    payload["resume_from_stage"] = resume_from_stage
    checkpoint = failed_payload.get("rewrite_checkpoint")
    if isinstance(checkpoint, dict) and checkpoint:
        payload["resume_checkpoint"] = checkpoint
    return payload


def _infer_chapter_rewrite_resume_stage(chapter: Chapter | None) -> str:
    if not chapter:
        return "context"
    if getattr(chapter, "quality_status", "unchecked") == "block":
        return "edit_fast_review"
    if chapter.polished_text and chapter.score_overall is not None and chapter.fast_review_feedback is not None:
        return "librarian_archive"
    if chapter.raw_draft and chapter.score_overall is not None:
        return "edit_fast_review"
    if chapter.raw_draft:
        return "review"
    return "context"


@router.get("/api/novels/{novel_id}/generation_jobs/{job_id}")
async def get_generation_job(novel_id: str, job_id: str, session: AsyncSession = Depends(get_session)):
    job = await GenerationJobRepository(session).get_by_id(job_id)
    if not job or job.novel_id != novel_id:
        raise HTTPException(status_code=404, detail="Generation job not found")
    return _generation_job_response(job)


@router.post("/api/recovery/cleanup")
async def run_recovery_cleanup(
    req: RecoveryCleanupOptions = RecoveryCleanupOptions(),
    session: AsyncSession = Depends(get_session),
):
    result = await RecoveryCleanupService(session).run_cleanup(req)
    return result.model_dump()


@router.post("/api/novels/{novel_id}/flow/stop")
async def stop_current_flow(novel_id: str, session: AsyncSession = Depends(get_session)):
    try:
        result = await FlowControlService(session).request_stop(novel_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await session.commit()
    return result


@router.get("/api/novels/{novel_id}/review")
async def get_review_result(novel_id: str, session: AsyncSession = Depends(get_session)):
    repo = NovelStateRepository(session)
    state = await repo.get_state(novel_id)
    if not state:
        raise HTTPException(status_code=404, detail="Novel state not found")
    if not state.current_chapter_id:
        raise HTTPException(status_code=404, detail="Current chapter not set")
    ch_repo = ChapterRepository(session)
    ch = await ch_repo.get_by_id(state.current_chapter_id)
    if not ch:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return {
        "score_overall": ch.score_overall,
        "score_breakdown": ch.score_breakdown,
        "review_feedback": ch.review_feedback,
    }


@router.get("/api/novels/{novel_id}/fast_review")
async def get_fast_review_result(novel_id: str, session: AsyncSession = Depends(get_session)):
    repo = NovelStateRepository(session)
    state = await repo.get_state(novel_id)
    if not state:
        raise HTTPException(status_code=404, detail="Novel state not found")
    if not state.current_chapter_id:
        raise HTTPException(status_code=404, detail="Current chapter not set")
    ch_repo = ChapterRepository(session)
    ch = await ch_repo.get_by_id(state.current_chapter_id)
    if not ch:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return {
        "fast_review_score": ch.fast_review_score,
        "fast_review_feedback": ch.fast_review_feedback,
    }


class VolumePlanRequest(BaseModel):
    volume_number: Optional[int] = None


@router.post("/api/novels/{novel_id}/brainstorm")
async def brainstorm_novel(novel_id: str, session: AsyncSession = Depends(get_session)):
    await FlowControlService(session).clear_stop(novel_id)
    agent = BrainstormAgent(session)
    try:
        synopsis_data = await agent.brainstorm(novel_id)
    except FlowCancelledError:
        await _raise_flow_cancelled(session, novel_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await session.commit()
    return {
        "title": synopsis_data.title,
        "logline": synopsis_data.logline,
        "estimated_volumes": synopsis_data.estimated_volumes,
        "estimated_total_chapters": synopsis_data.estimated_total_chapters,
    }


@router.post("/api/novels/{novel_id}/brainstorm/start")
async def start_brainstorm(novel_id: str, session: AsyncSession = Depends(get_session)):
    doc_repo = DocumentRepository(session)
    docs = (
        await doc_repo.get_current_by_type(novel_id, "worldview")
        + await doc_repo.get_current_by_type(novel_id, "setting")
        + await doc_repo.get_current_by_type(novel_id, "concept")
    )
    if not docs:
        raise HTTPException(status_code=400, detail="请先上传世界观或设定文档")

    director = NovelDirector(session)
    state = await director.resume(novel_id)
    checkpoint = dict(state.checkpoint_data or {}) if state else {}
    await director.save_checkpoint(
        novel_id,
        phase=Phase.BRAINSTORMING,
        checkpoint_data=checkpoint,
        volume_id=state.current_volume_id if state else None,
        chapter_id=state.current_chapter_id if state else None,
    )
    await session.commit()

    doc_list = "\n".join(f"- [{d.doc_type}] {d.title} (doc_id={d.id})" for d in docs)
    prompt = (
        f'请为小说 "{novel_id}" 脑暴一份大纲。\n\n'
        f"已上传的设定文档列表如下，你可以调用 get_novel_document_full 获取完整内容：\n"
        f"{doc_list}\n\n"
        f"请基于这些文档生成大纲。每次修改后请调用 save_brainstorm_draft 保存。\n"
        f'当我确认满意后，调用 confirm_brainstorm 完成脑暴。'
    )
    return {"prompt": prompt}


@router.get("/api/novels/{novel_id}/brainstorm/prompt")
async def get_brainstorm_prompt(novel_id: str, session: AsyncSession = Depends(get_session)):
    """获取脑暴 prompt 内容（用于复制到 Claude Code）"""
    doc_repo = DocumentRepository(session)
    docs = (
        await doc_repo.get_current_by_type(novel_id, "worldview")
        + await doc_repo.get_current_by_type(novel_id, "setting")
        + await doc_repo.get_current_by_type(novel_id, "concept")
    )
    if not docs:
        raise HTTPException(status_code=400, detail="请先上传世界观或设定文档")

    combined = "\n\n".join(f"[{d.doc_type}] {d.title}\n{d.content}" for d in docs)

    prompt = render_brainstorm_prompt(combined)

    return {"prompt": prompt, "doc_count": len(docs)}


class ImportSynopsisRequest(BaseModel):
    content: str


@router.post("/api/novels/{novel_id}/brainstorm/import")
async def import_synopsis(novel_id: str, req: ImportSynopsisRequest, session: AsyncSession = Depends(get_session)):
    """导入 Claude Code 生成的 Synopsis JSON"""
    from novel_dev.schemas.outline import SynopsisData
    import re

    content = req.content.strip()

    # 尝试从 Markdown 代码块中提取 JSON
    json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
    if json_match:
        json_str = json_match.group(1).strip()
    else:
        json_str = content

    try:
        synopsis_data = SynopsisData.model_validate_json(json_str)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"JSON 解析失败: {e}")

    doc_repo = DocumentRepository(session)
    from novel_dev.agents.brainstorm_agent import BrainstormAgent

    # 格式化文本
    lines = [
        f"# {synopsis_data.title}",
        "",
        "## 一句话梗概",
        synopsis_data.logline,
        "",
        "## 核心冲突",
        synopsis_data.core_conflict,
        "",
        "## 人物弧光",
    ]
    for arc in synopsis_data.character_arcs:
        lines.append(f"### {arc.name}")
        lines.append(arc.arc_summary)
        for pt in arc.key_turning_points:
            lines.append(f"- {pt}")
    lines.append("")
    lines.append("## 剧情里程碑")
    for ms in synopsis_data.milestones:
        lines.append(f"### {ms.act}")
        lines.append(ms.summary)
        if ms.climax_event:
            lines.append(f"高潮：{ms.climax_event}")
    synopsis_text = "\n".join(lines)

    doc = await doc_repo.create(
        doc_id=f"doc_{secrets.token_hex(4)}",
        novel_id=novel_id,
        doc_type="synopsis",
        title=synopsis_data.title,
        content=synopsis_text,
    )

    # 更新 checkpoint
    director = NovelDirector(session)
    state = await director.resume(novel_id)
    checkpoint = dict(state.checkpoint_data or {}) if state else {}
    checkpoint["synopsis_data"] = synopsis_data.model_dump()
    checkpoint["synopsis_doc_id"] = doc.id

    await director.save_checkpoint(
        novel_id,
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data=checkpoint,
        volume_id=state.current_volume_id if state else None,
        chapter_id=state.current_chapter_id if state else None,
    )
    await session.commit()

    return {
        "doc_id": doc.id,
        "title": synopsis_data.title,
        "message": "Synopsis 已导入，流程进入 Volume Planning 阶段"
    }


@router.post("/api/novels/{novel_id}/volume_plan")
async def plan_volume(novel_id: str, req: VolumePlanRequest = VolumePlanRequest(), session: AsyncSession = Depends(get_session)):
    await FlowControlService(session).clear_stop(novel_id)
    agent = VolumePlannerAgent(session)
    try:
        plan = await agent.plan(novel_id, volume_number=req.volume_number)
    except FlowCancelledError:
        await _raise_flow_cancelled(session, novel_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    state = await NovelStateRepository(session).get_state(novel_id)
    current_volume_plan = (state.checkpoint_data or {}).get("current_volume_plan", {}) if state else {}
    await session.commit()
    return {
        "volume_id": plan.volume_id,
        "volume_number": plan.volume_number,
        "title": plan.title,
        "summary": plan.summary,
        "total_chapters": plan.total_chapters,
        "estimated_total_words": plan.estimated_total_words,
        "review_status": current_volume_plan.get("review_status"),
        "chapters": [
            {
                "chapter_id": ch.chapter_id,
                "chapter_number": ch.chapter_number,
                "title": ch.title,
                "summary": ch.summary,
            }
            for ch in plan.chapters
        ],
    }


@router.get("/api/novels/{novel_id}/synopsis")
async def get_synopsis(novel_id: str, session: AsyncSession = Depends(get_session)):
    repo = DocumentRepository(session)
    state_repo = NovelStateRepository(session)
    state = await state_repo.get_state(novel_id)
    if not state:
        raise HTTPException(status_code=404, detail="Novel state not found")

    docs = await repo.get_current_by_type(novel_id, "synopsis")
    synopsis_data = {}
    if state.checkpoint_data:
        synopsis_data = state.checkpoint_data.get("synopsis_data", {})

    if not docs:
        return {
            "content": "",
            "synopsis_data": synopsis_data,
        }

    return {
        "content": docs[0].content,
        "synopsis_data": synopsis_data,
    }


@router.get("/api/novels/{novel_id}/volume_plan")
async def get_volume_plan(novel_id: str, session: AsyncSession = Depends(get_session)):
    state_repo = NovelStateRepository(session)
    state = await state_repo.get_state(novel_id)
    if not state or not state.checkpoint_data.get("current_volume_plan"):
        raise HTTPException(status_code=404, detail="Volume plan not found")
    plan = VolumePlan.model_validate(state.checkpoint_data["current_volume_plan"])
    return {
        "volume_id": plan.volume_id,
        "volume_number": plan.volume_number,
        "title": plan.title,
        "total_chapters": plan.total_chapters,
        "chapters": [
            {
                "chapter_id": ch.chapter_id,
                "chapter_number": ch.chapter_number,
                "title": ch.title,
                "summary": ch.summary,
            }
            for ch in plan.chapters
        ],
    }


@router.get("/api/novels/{novel_id}/outline_workbench")
async def get_outline_workbench(
    novel_id: str,
    outline_type: str,
    outline_ref: str,
    session: AsyncSession = Depends(get_session),
):
    service = OutlineWorkbenchService(session)
    try:
        return await service.build_workbench(
            novel_id=novel_id,
            outline_type=outline_type,
            outline_ref=outline_ref,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/api/novels/{novel_id}/outline_workbench/messages", response_model=OutlineMessagesResponse)
async def get_outline_workbench_messages(
    novel_id: str,
    outline_type: str,
    outline_ref: str,
    session: AsyncSession = Depends(get_session),
):
    service = OutlineWorkbenchService(session)
    try:
        return await service.get_messages(
            novel_id=novel_id,
            outline_type=outline_type,
            outline_ref=outline_ref,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/novels/{novel_id}/outline_workbench/submit")
async def submit_outline_workbench(
    novel_id: str,
    req: OutlineWorkbenchSubmitRequest,
    session: AsyncSession = Depends(get_session),
):
    await FlowControlService(session).clear_stop(novel_id)
    service = OutlineWorkbenchService(session)
    try:
        return await service.submit_feedback(
            novel_id=novel_id,
            outline_type=req.outline_type,
            outline_ref=req.outline_ref,
            feedback=req.content,
        )
    except FlowCancelledError:
        await _raise_flow_cancelled(session, novel_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post(
    "/api/novels/{novel_id}/outline_workbench/clear_context",
    response_model=OutlineClearContextResponse,
)
async def clear_outline_workbench_context(
    novel_id: str,
    req: OutlineWorkbenchSelectionRequest,
    session: AsyncSession = Depends(get_session),
):
    service = OutlineWorkbenchService(session)
    try:
        return await service.clear_context(
            novel_id=novel_id,
            outline_type=req.outline_type,
            outline_ref=req.outline_ref,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/novels/{novel_id}/outline_workbench/review")
async def review_outline_workbench(
    novel_id: str,
    req: OutlineWorkbenchSelectionRequest,
    session: AsyncSession = Depends(get_session),
):
    service = OutlineWorkbenchService(session)
    try:
        return await service.review_outline(
            novel_id=novel_id,
            outline_type=req.outline_type,
            outline_ref=req.outline_ref,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post(
    "/api/novels/{novel_id}/settings/sessions",
    response_model=SettingGenerationSessionResponse,
)
async def create_setting_generation_session(
    novel_id: str,
    req: SettingGenerationSessionCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    title = req.title.strip() or "未命名设定会话"
    repo = SettingWorkbenchRepository(session)
    item = await repo.create_session(
        novel_id=novel_id,
        title=title,
        target_categories=req.target_categories,
    )
    initial_idea = req.initial_idea.strip()
    if initial_idea:
        await repo.add_message(
            session_id=item.id,
            role="user",
            content=initial_idea,
            metadata={"kind": "initial_idea"},
        )
    await session.commit()
    return _serialize_setting_generation_session(item)


@router.get(
    "/api/novels/{novel_id}/settings/workbench",
    response_model=SettingWorkbenchResponse,
)
async def get_setting_workbench(
    novel_id: str,
    session: AsyncSession = Depends(get_session),
):
    repo = SettingWorkbenchRepository(session)
    sessions = await repo.list_sessions(novel_id)
    review_batches = await repo.list_review_batches(novel_id)
    return {
        "sessions": [_serialize_setting_generation_session(item) for item in sessions],
        "review_batches": [_serialize_setting_review_batch(item) for item in review_batches],
    }


@router.get(
    "/api/novels/{novel_id}/settings/sessions",
    response_model=SettingGenerationSessionListResponse,
)
async def list_setting_generation_sessions(
    novel_id: str,
    session: AsyncSession = Depends(get_session),
):
    repo = SettingWorkbenchRepository(session)
    items = await repo.list_sessions(novel_id)
    return {"items": [_serialize_setting_generation_session(item) for item in items]}


@router.get(
    "/api/novels/{novel_id}/settings/sessions/{session_id}",
    response_model=SettingGenerationSessionDetailResponse,
)
async def get_setting_generation_session(
    novel_id: str,
    session_id: str,
    session: AsyncSession = Depends(get_session),
):
    repo = SettingWorkbenchRepository(session)
    item = await repo.get_session(session_id)
    if item is None or item.novel_id != novel_id:
        raise HTTPException(status_code=404, detail="Setting generation session not found")
    messages = await repo.list_messages(session_id)
    return {
        "session": _serialize_setting_generation_session(item),
        "messages": [_serialize_setting_generation_message(message) for message in messages],
    }


@router.post(
    "/api/novels/{novel_id}/settings/sessions/{session_id}/reply",
    response_model=SettingGenerationSessionReplyResponse,
)
async def reply_setting_generation_session(
    novel_id: str,
    session_id: str,
    req: SettingGenerationSessionReplyRequest,
    session: AsyncSession = Depends(get_session),
):
    service = SettingWorkbenchService(session)
    try:
        result = await service.reply_to_session(
            novel_id=novel_id,
            session_id=session_id,
            content=req.content,
        )
    except LLMConfigError as exc:
        await session.rollback()
        raise _llm_config_http_exception(exc) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return {
        "session": _serialize_setting_generation_session(result["session"]),
        "assistant_message": result["assistant_message"],
        "questions": result.get("questions") or [],
    }


@router.post(
    "/api/novels/{novel_id}/settings/sessions/{session_id}/generate",
    response_model=SettingReviewBatchResponse,
)
async def generate_setting_review_batch(
    novel_id: str,
    session_id: str,
    req: SettingGenerationSessionGenerateRequest,
    session: AsyncSession = Depends(get_session),
):
    _ = req
    service = SettingWorkbenchService(session)
    try:
        batch = await service.generate_review_batch(novel_id=novel_id, session_id=session_id)
    except LLMConfigError as exc:
        await session.rollback()
        raise _llm_config_http_exception(exc) from exc
    except LLMTimeoutError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="AI 生成设定审核记录超时，请稍后重试",
        ) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return _serialize_setting_review_batch(batch)


@router.post(
    "/api/novels/{novel_id}/settings/consolidations",
    response_model=SettingConsolidationStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_setting_consolidation(
    novel_id: str,
    req: SettingConsolidationStartRequest,
    session: AsyncSession = Depends(get_session),
):
    repo = GenerationJobRepository(session)
    await _lock_setting_consolidation_start(session, novel_id)
    active = await repo.get_active(novel_id, SETTING_CONSOLIDATION_JOB)
    if active:
        return {"job_id": active.id, "status": active.status}

    job = await repo.create(
        novel_id,
        SETTING_CONSOLIDATION_JOB,
        {"selected_pending_ids": req.selected_pending_ids},
    )
    await session.commit()
    try:
        schedule_generation_job(job.id)
    except Exception as exc:
        error_message = f"Failed to schedule setting consolidation job: {exc}"
        await repo.mark_failed(job.id, {}, error_message)
        await session.commit()
        raise HTTPException(status_code=500, detail=error_message)
    return {"job_id": job.id, "status": job.status}


@router.get(
    "/api/novels/{novel_id}/settings/review_batches",
    response_model=SettingReviewBatchListResponse,
)
async def list_setting_review_batches(
    novel_id: str,
    session: AsyncSession = Depends(get_session),
):
    repo = SettingWorkbenchRepository(session)
    items = await repo.list_review_batches(novel_id)
    return {"items": [_serialize_setting_review_batch(item) for item in items]}


@router.get(
    "/api/novels/{novel_id}/settings/review_batches/{batch_id}",
    response_model=SettingReviewBatchDetailResponse,
)
async def get_setting_review_batch(
    novel_id: str,
    batch_id: str,
    session: AsyncSession = Depends(get_session),
):
    repo = SettingWorkbenchRepository(session)
    batch = await repo.get_review_batch(batch_id)
    if batch is None or batch.novel_id != novel_id:
        raise HTTPException(status_code=404, detail="Setting review batch not found")
    changes = await repo.list_review_changes(batch_id)
    return {
        "batch": _serialize_setting_review_batch(batch),
        "changes": [_serialize_setting_review_change(change) for change in changes],
    }


@router.post(
    "/api/novels/{novel_id}/settings/review_batches/{batch_id}/apply",
    response_model=SettingReviewApplyResponse,
)
async def apply_setting_review_batch(
    novel_id: str,
    batch_id: str,
    req: SettingReviewApplyRequest,
    session: AsyncSession = Depends(get_session),
):
    service = SettingWorkbenchService(session)
    try:
        result = await service.apply_review_decisions(
            novel_id,
            batch_id,
            [decision.model_dump() for decision in req.decisions],
        )
    except ValueError as exc:
        await session.rollback()
        detail = str(exc)
        status_code = 404 if "not found" in detail.lower() else 409
        raise HTTPException(status_code=status_code, detail=detail) from exc
    await session.commit()
    return result


@router.post(
    "/api/novels/{novel_id}/settings/review_batches/{batch_id}/approve",
    response_model=SettingReviewBatchDetailResponse,
)
async def approve_setting_review_batch(
    novel_id: str,
    batch_id: str,
    req: SettingReviewApproveRequest,
    session: AsyncSession = Depends(get_session),
):
    service = SettingConsolidationService(session)
    batch = await service.setting_repo.get_review_batch(batch_id)
    if batch is None or batch.novel_id != novel_id:
        raise HTTPException(status_code=404, detail="Setting review batch not found")
    try:
        await service.approve_review_batch(
            batch_id,
            change_ids=req.change_ids,
            approve_all=req.approve_all,
        )
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()

    updated = await service.setting_repo.get_review_batch(batch_id)
    changes = await service.setting_repo.list_review_changes(batch_id)
    return {
        "batch": _serialize_setting_review_batch(updated),
        "changes": [_serialize_setting_review_change(change) for change in changes],
    }


@router.post(
    "/api/novels/{novel_id}/settings/review_batches/{batch_id}/apply",
    response_model=SettingReviewApplyResponse,
)
async def apply_setting_review_batch(
    novel_id: str,
    batch_id: str,
    req: SettingReviewApplyRequest,
    session: AsyncSession = Depends(get_session),
):
    service = SettingWorkbenchService(session)
    batch = await service.repo.get_review_batch(batch_id)
    if batch is None or batch.novel_id != novel_id:
        raise HTTPException(status_code=404, detail="Setting review batch not found")
    try:
        result = await service.apply_review_decisions(
            novel_id,
            batch_id,
            [decision.model_dump(exclude_none=True) for decision in req.decisions],
        )
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return result


@router.post(
    "/api/novels/{novel_id}/settings/review_batches/{batch_id}/conflicts/resolve",
    response_model=SettingReviewBatchDetailResponse,
)
async def resolve_setting_review_conflict(
    novel_id: str,
    batch_id: str,
    req: SettingConflictResolutionRequest,
    session: AsyncSession = Depends(get_session),
):
    service = SettingConsolidationService(session)
    batch = await service.setting_repo.get_review_batch(batch_id)
    if batch is None or batch.novel_id != novel_id:
        raise HTTPException(status_code=404, detail="Setting review batch not found")
    try:
        await service.resolve_conflict_change(
            batch_id,
            change_id=req.change_id,
            resolved_after_snapshot=req.resolved_after_snapshot,
        )
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()

    updated = await service.setting_repo.get_review_batch(batch_id)
    changes = await service.setting_repo.list_review_changes(batch_id)
    return {
        "batch": _serialize_setting_review_batch(updated),
        "changes": [_serialize_setting_review_change(change) for change in changes],
    }


@router.post(
    "/api/novels/{novel_id}/brainstorm/workspace/start",
    response_model=BrainstormWorkspacePayload,
)
async def start_brainstorm_workspace(
    novel_id: str,
    session: AsyncSession = Depends(get_session),
):
    service = BrainstormWorkspaceService(session)
    try:
        return await service.get_workspace_payload(novel_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/api/novels/{novel_id}/brainstorm/workspace",
    response_model=BrainstormWorkspacePayload,
)
async def get_brainstorm_workspace(
    novel_id: str,
    session: AsyncSession = Depends(get_session),
):
    service = BrainstormWorkspaceService(session)
    try:
        return await service.get_workspace_payload(novel_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/api/novels/{novel_id}/brainstorm/workspace/submit",
    response_model=BrainstormWorkspaceSubmitResponse,
)
async def submit_brainstorm_workspace(
    novel_id: str,
    session: AsyncSession = Depends(get_session),
):
    service = BrainstormWorkspaceService(session)
    try:
        return await service.submit_workspace(novel_id)
    except ValueError as e:
        detail = str(e)
        status_code = 404 if "not found" in detail.lower() else 409
        raise HTTPException(status_code=status_code, detail=detail)


@router.patch(
    "/api/novels/{novel_id}/brainstorm/suggestion_cards/{card_id}",
    response_model=BrainstormSuggestionCardUpdateResponse,
)
async def update_brainstorm_suggestion_card(
    novel_id: str,
    card_id: str,
    payload: BrainstormSuggestionCardUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    service = BrainstormWorkspaceService(session)
    try:
        result = await service.update_suggestion_card(novel_id, card_id, payload.action)
        await session.commit()
        return result
    except ValueError as e:
        detail = str(e)
        lowered = detail.lower()
        if "not found" in lowered:
            raise HTTPException(status_code=404, detail=detail)
        if "unsupported suggestion card action" in lowered:
            raise HTTPException(status_code=400, detail=detail)
        raise HTTPException(status_code=409, detail=detail)


@router.post("/api/novels/{novel_id}/librarian")
async def run_librarian(novel_id: str, session: AsyncSession = Depends(get_session)):
    await FlowControlService(session).clear_stop(novel_id)
    director = NovelDirector(session)
    try:
        state = await director.run_librarian(novel_id)
    except FlowCancelledError:
        await _raise_flow_cancelled(session, novel_id)
    except ValueError as e:
        if "Novel state not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    await session.commit()
    return {
        "novel_id": state.novel_id,
        "current_phase": state.current_phase,
        "checkpoint_data": state.checkpoint_data,
    }


@router.get("/api/novels/{novel_id}/volumes/{volume_id}/export")
async def export_volume(novel_id: str, volume_id: str, format: str = "md", session: AsyncSession = Depends(get_session)):
    from novel_dev.services.export_service import ExportService
    svc = ExportService(session, settings.data_dir)
    try:
        path = await svc.export_volume(novel_id, volume_id, format=format)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"exported_path": path, "format": format}


@router.post("/api/novels/{novel_id}/export")
async def export_novel(novel_id: str, format: str = "md", session: AsyncSession = Depends(get_session)):
    from novel_dev.services.export_service import ExportService
    svc = ExportService(session, settings.data_dir)
    try:
        path = await svc.export_novel(novel_id, format=format)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"exported_path": path, "format": format}


@router.get("/api/novels/{novel_id}/archive_stats")
async def get_archive_stats(novel_id: str, session: AsyncSession = Depends(get_session)):
    repo = NovelStateRepository(session)
    state = await repo.get_state(novel_id)
    if not state:
        raise HTTPException(status_code=404, detail="Novel state not found")
    stats = state.checkpoint_data.get("archive_stats", {})
    return {
        "novel_id": novel_id,
        "total_word_count": stats.get("total_word_count", 0),
        "archived_chapter_count": stats.get("archived_chapter_count", 0),
        "avg_word_count": stats.get("avg_word_count", 0),
    }


def _agent_log_to_entry(row: AgentLog) -> dict[str, Any]:
    entry = {
        "timestamp": row.timestamp.isoformat() + "Z",
        "agent": row.agent,
        "message": row.message,
        "level": row.level,
    }
    if row.event is not None:
        entry["event"] = row.event
    if row.status is not None:
        entry["status"] = row.status
    if row.node is not None:
        entry["node"] = row.node
    if row.task is not None:
        entry["task"] = row.task
    if row.meta is not None:
        entry["metadata"] = row.meta
    if row.duration_ms is not None:
        entry["duration_ms"] = row.duration_ms
    return entry


@router.get("/api/novels/{novel_id}/logs")
async def get_logs(novel_id: str, limit: int = 500, session: AsyncSession = Depends(get_session)):
    state = await session.get(NovelState, novel_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Novel state not found")

    bounded_limit = max(1, min(limit, 500))
    result = await session.execute(
        select(AgentLog)
        .where(AgentLog.novel_id == novel_id)
        .order_by(AgentLog.timestamp.desc(), AgentLog.id.desc())
        .limit(bounded_limit)
    )
    rows = list(result.scalars())[::-1]
    return {"novel_id": novel_id, "logs": [_agent_log_to_entry(row) for row in rows]}


@router.get("/api/novels/{novel_id}/logs/stream")
async def stream_logs(novel_id: str):
    from novel_dev.services.log_service import log_service as _log_service

    q = await _log_service.subscribe_with_history(novel_id)

    async def event_generator():
        try:
            while True:
                entry = await q.get()
                yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            _log_service.unsubscribe(novel_id, q)
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.delete("/api/novels/{novel_id}/logs")
async def clear_logs(novel_id: str, session: AsyncSession = Depends(get_session)):
    state = await session.get(NovelState, novel_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Novel state not found")

    count_result = await session.execute(
        select(func.count()).select_from(AgentLog).where(AgentLog.novel_id == novel_id)
    )
    deleted_count = int(count_result.scalar_one() or 0)
    await session.execute(delete(AgentLog).where(AgentLog.novel_id == novel_id))
    audit_timestamp = datetime.utcnow()
    audit_entry = {
        "timestamp": audit_timestamp.isoformat() + "Z",
        "agent": "LogService",
        "message": f"日志已清空，删除 {deleted_count} 条历史记录",
        "level": "warning",
        "event": "logs.clear",
        "status": "succeeded",
        "metadata": {"deleted_count": deleted_count},
    }
    session.add(AgentLog(
        novel_id=novel_id,
        timestamp=audit_timestamp,
        agent=audit_entry["agent"],
        message=audit_entry["message"],
        level=audit_entry["level"],
        event=audit_entry["event"],
        status=audit_entry["status"],
        meta=audit_entry["metadata"],
    ))
    await session.commit()
    log_service.clear_memory(novel_id)
    return {"novel_id": novel_id, "deleted_count": deleted_count, "audit_log": audit_entry}
