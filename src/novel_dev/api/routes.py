import asyncio
import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field

from novel_dev.db.engine import async_session_maker
from novel_dev.db.models import EntityGroup, NovelState, Entity, EntityRelationship, Timeline, Spaceline, Foreshadowing, Chapter
from novel_dev.services.entity_service import EntityService
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.storage.markdown_sync import MarkdownSync
from novel_dev.config import Settings
from novel_dev.services.extraction_service import ExtractionService
from novel_dev.repositories.pending_extraction_repo import PendingExtractionRepository
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.agents.context_agent import ContextAgent
from novel_dev.agents.writer_agent import WriterAgent
from novel_dev.services.embedding_service import EmbeddingService
from novel_dev.llm import llm_factory
from novel_dev.llm.exceptions import LLMTimeoutError
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.context import ChapterContext
from novel_dev.schemas.outline import VolumePlan
from novel_dev.agents.brainstorm_agent import BrainstormAgent
from novel_dev.agents.volume_planner import VolumePlannerAgent
import re
import secrets

router = APIRouter()


class CreateNovelRequest(BaseModel):
    title: str


class EntityClassificationUpdateRequest(BaseModel):
    manual_category: str
    manual_group_slug: str


settings = Settings()


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


def _build_inferred_relationships(entity_rows: list[dict]) -> list[dict]:
    inferred = []
    seen = set()
    sorted_rows = sorted(entity_rows, key=lambda item: len(item["name"]), reverse=True)
    for source in sorted_rows:
        latest_state = source.get("latest_state") or {}
        relation_text = _stringify_relationship_value(
            latest_state.get("relationships") or latest_state.get("relationship")
        )
        if not relation_text:
            continue
        for target in sorted_rows:
            if source["entity_id"] == target["entity_id"]:
                continue
            if target["name"] not in relation_text:
                continue
            relation_type = _infer_relationship_type(relation_text)
            dedup_key = (source["entity_id"], target["entity_id"], relation_type)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            inferred.append({
                "id": f"inferred:{source['entity_id']}:{target['entity_id']}:{relation_type}",
                "source_id": source["entity_id"],
                "target_id": target["entity_id"],
                "relation_type": relation_type,
                "meta": {"source": "latest_state.relationships"},
                "created_at_chapter_id": None,
                "is_active": True,
                "is_inferred": True,
            })
    return inferred


def _classification_status(entity: Entity) -> str:
    if entity.manual_category or entity.manual_group_id:
        return "manual_override"
    if entity.system_needs_review:
        return "needs_review"
    return "auto"


async def _serialize_entity_payload(session: AsyncSession, entity: Entity) -> dict:
    group_ids = [group_id for group_id in (entity.system_group_id, entity.manual_group_id) if group_id]
    groups: dict[str, EntityGroup] = {}
    if group_ids:
        group_result = await session.execute(select(EntityGroup).where(EntityGroup.id.in_(group_ids)))
        groups = {group.id: group for group in group_result.scalars().all()}

    system_group = groups.get(entity.system_group_id) if entity.system_group_id else None
    manual_group = groups.get(entity.manual_group_id) if entity.manual_group_id else None

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
        "manual_category": entity.manual_category,
        "manual_group_id": entity.manual_group_id,
        "manual_group_slug": manual_group.group_slug if manual_group else None,
        "classification_reason": entity.classification_reason,
        "classification_confidence": entity.classification_confidence,
        "system_needs_review": entity.system_needs_review,
        "classification_status": _classification_status(entity),
        "search_document": entity.search_document,
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
                "title": (r.checkpoint_data or {}).get("synopsis_data", {}).get("title") or r.novel_id,
                "current_phase": r.current_phase,
                "last_updated": r.last_updated.isoformat() if r.last_updated else None,
            }
            for r in rows
        ]
    }


def _generate_novel_id(title: str) -> str:
    # Strip non-ASCII first so CJK titles get a clean slug
    slug = re.sub(r'[^\x00-\x7F]', '', title.lower())
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[-\s]+', '-', slug).strip('-')
    if not slug:
        slug = 'novel'
    suffix = secrets.token_hex(2)
    return f"{slug}-{suffix}"


@router.post("/api/novels", status_code=201)
async def create_novel(req: CreateNovelRequest, session: AsyncSession = Depends(get_session)):
    title = req.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="标题不能为空")

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

    return {
        "novel_id": state.novel_id,
        "current_phase": state.current_phase,
        "current_volume_id": state.current_volume_id,
        "current_chapter_id": state.current_chapter_id,
        "checkpoint_data": state.checkpoint_data,
        "last_updated": state.last_updated.isoformat() if state.last_updated else None,
    }


@router.get("/api/novels/{novel_id}/state")
async def get_novel_state(novel_id: str, session: AsyncSession = Depends(get_session)):
    repo = NovelStateRepository(session)
    state = await repo.get_state(novel_id)
    if not state:
        raise HTTPException(status_code=404, detail="Novel state not found")
    return {
        "novel_id": state.novel_id,
        "current_phase": state.current_phase,
        "current_volume_id": state.current_volume_id,
        "current_chapter_id": state.current_chapter_id,
        "checkpoint_data": state.checkpoint_data,
        "last_updated": state.last_updated.isoformat(),
    }


@router.get("/api/novels/{novel_id}/entities")
async def list_entities(novel_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Entity).where(Entity.novel_id == novel_id).order_by(Entity.name)
    )
    entities = list(result.scalars().all())
    svc = EntityService(session)
    states = await svc.get_latest_states([ent.id for ent in entities])
    grouped: dict[tuple[str, str], list[dict]] = {}
    for ent in entities:
        row = {
            "entity_id": ent.id,
            "type": ent.type,
            "name": ent.name,
            "current_version": ent.current_version,
            "created_at_chapter_id": ent.created_at_chapter_id,
            "latest_state": states.get(ent.id),
        }
        key = (ent.type, EntityRepository.normalize_name(ent.name) or ent.name)
        grouped.setdefault(key, []).append(row)

    items = []
    for rows in grouped.values():
        rows.sort(key=lambda item: (len(item["name"]), item["name"]))
        primary = dict(rows[0])
        merged_state = dict(primary.get("latest_state") or {})
        aliases = [row["name"] for row in rows[1:] if row["name"] != primary["name"]]
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
    session: AsyncSession = Depends(get_session),
):
    embedder = llm_factory.get_embedder()
    embedding_service = EmbeddingService(session, embedder)
    query_vector = await embedding_service.generate_embedding(q)
    entity_repo = EntityRepository(session)
    hits = await entity_repo.search_entities(
        novel_id,
        query=q,
        query_vector=query_vector,
        limit=20,
    )
    group_ids = []
    for hit in hits:
        group_id = hit.get("manual_group_id") or hit.get("system_group_id")
        if group_id and group_id not in group_ids:
            group_ids.append(group_id)

    groups_by_id: dict[str, EntityGroup] = {}
    if group_ids:
        group_result = await session.execute(
            select(EntityGroup).where(EntityGroup.id.in_(group_ids))
        )
        groups_by_id = {group.id: group for group in group_result.scalars().all()}

    grouped_items: list[dict] = []
    group_index_by_key: dict[tuple[str, str], int] = {}
    for hit in hits:
        effective_category = hit.get("manual_category") or hit.get("system_category") or "其他"
        effective_group_id = hit.get("manual_group_id") or hit.get("system_group_id")
        group = groups_by_id.get(effective_group_id) if effective_group_id else None
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
        grouped_items[group_index_by_key[group_key]]["entities"].append(hit)

    return {"items": grouped_items}


@router.get("/api/novels/{novel_id}/entities/{entity_id}")
async def get_entity(novel_id: str, entity_id: str, session: AsyncSession = Depends(get_session)):
    svc = EntityService(session)
    state = await svc.get_latest_state(entity_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return {"entity_id": entity_id, "latest_state": state}


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

    group_result = await session.execute(
        select(EntityGroup).where(
            EntityGroup.novel_id == novel_id,
            EntityGroup.category == req.manual_category,
            EntityGroup.group_slug == req.manual_group_slug,
        )
    )
    manual_group = group_result.scalar_one_or_none()
    if manual_group is None:
        raise HTTPException(status_code=404, detail="Entity group not found")

    await entity_repo.update_classification(
        entity_id,
        manual_category=req.manual_category,
        manual_group_id=manual_group.id,
    )
    await session.commit()

    updated = await entity_repo.get_by_id(entity_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return await _serialize_entity_payload(session, updated)


@router.get("/api/novels/{novel_id}/entity_relationships")
async def list_entity_relationships(novel_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(EntityRelationship)
        .where(EntityRelationship.novel_id == novel_id, EntityRelationship.is_active.is_(True))
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
        }
        for rel in result.scalars().all()
    ]
    if items:
        return {"items": items}

    entities_result = await session.execute(
        select(Entity).where(Entity.novel_id == novel_id).order_by(Entity.name)
    )
    entities = list(entities_result.scalars().all())
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
    items = _build_inferred_relationships(entity_rows)
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
        })
    return {"items": items}


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
    if not ch or not ch.polished_text:
        raise HTTPException(status_code=404, detail="Chapter content not found")
    sync = MarkdownSync(settings.markdown_output_dir)
    path = await sync.write_chapter(novel_id, ch.volume_id, chapter_id, ch.polished_text)
    return {"exported_path": path, "content": ch.polished_text}


class UploadRequest(BaseModel):
    filename: str
    content: str


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
            pe = await svc.process_upload(novel_id, req.filename, req.content)
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


@router.post("/api/novels/{novel_id}/documents/upload")
async def upload_document(novel_id: str, req: UploadRequest, session: AsyncSession = Depends(get_session)):
    embedder = llm_factory.get_embedder()
    embedding_service = EmbeddingService(session, embedder)
    svc = ExtractionService(session, embedding_service)
    try:
        pe = await svc.process_upload(novel_id, req.filename, req.content)
    except LLMTimeoutError as exc:
        raise HTTPException(status_code=504, detail="设定提取超时，请稍后重试或切换模型") from exc
    await session.commit()
    return {
        "id": pe.id,
        "source_filename": pe.source_filename,
        "extraction_type": pe.extraction_type,
        "status": pe.status,
        "created_at": pe.created_at.isoformat(),
    }


@router.post("/api/novels/{novel_id}/documents/upload/batch")
async def upload_documents_batch(
    novel_id: str,
    req: BatchUploadRequest,
):
    embedder = llm_factory.get_embedder()
    max_concurrency = min(req.max_concurrency or 3, 8)
    semaphore = asyncio.Semaphore(max_concurrency)

    async def run_one(item: UploadRequest) -> dict:
        async with semaphore:
            return await _process_upload_with_new_session(novel_id, item, embedder)

    results = await asyncio.gather(*(run_one(item) for item in req.items))
    succeeded = sum(1 for item in results if item["pending_id"])
    failed = len(results) - succeeded
    return {
        "total": len(results),
        "succeeded": succeeded,
        "failed": failed,
        "items": results,
    }


@router.get("/api/novels/{novel_id}/documents/pending")
async def get_pending_documents(novel_id: str, session: AsyncSession = Depends(get_session)):
    repo = PendingExtractionRepository(session)
    items = await repo.list_by_novel(novel_id)
    return {
        "items": [
            {
                "id": i.id,
                "source_filename": i.source_filename,
                "extraction_type": i.extraction_type,
                "status": i.status,
                "raw_result": i.raw_result,
                "proposed_entities": i.proposed_entities,
                "diff_result": i.diff_result,
                "resolution_result": i.resolution_result,
                "created_at": i.created_at.isoformat(),
            }
            for i in items
        ]
    }


@router.post("/api/novels/{novel_id}/documents/pending/approve")
async def approve_pending_document(novel_id: str, req: ApproveRequest, session: AsyncSession = Depends(get_session)):
    embedder = llm_factory.get_embedder()
    embedding_service = EmbeddingService(session, embedder)
    svc = ExtractionService(session, embedding_service)
    repo = PendingExtractionRepository(session)
    pe = await repo.get_by_id(req.pending_id)
    if not pe or pe.novel_id != novel_id:
        raise HTTPException(status_code=403, detail="Pending extraction does not belong to this novel")
    docs = await svc.approve_pending(req.pending_id, field_resolutions=[r.model_dump() for r in req.field_resolutions])
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


@router.post("/api/novels/{novel_id}/chapters/{chapter_id}/context")
async def prepare_chapter_context(
    novel_id: str,
    chapter_id: str,
    session: AsyncSession = Depends(get_session),
):
    embedder = llm_factory.get_embedder()
    embedding_service = EmbeddingService(session, embedder)
    agent = ContextAgent(session, embedding_service)
    try:
        context = await agent.assemble(novel_id, chapter_id)
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
    director = NovelDirector(session)
    try:
        state = await director.advance(novel_id)
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
    agent = BrainstormAgent(session)
    try:
        synopsis_data = await agent.brainstorm(novel_id)
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
        await doc_repo.get_by_type(novel_id, "worldview")
        + await doc_repo.get_by_type(novel_id, "setting")
        + await doc_repo.get_by_type(novel_id, "concept")
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
        await doc_repo.get_by_type(novel_id, "worldview")
        + await doc_repo.get_by_type(novel_id, "setting")
        + await doc_repo.get_by_type(novel_id, "concept")
    )
    if not docs:
        raise HTTPException(status_code=400, detail="请先上传世界观或设定文档")

    combined = "\n\n".join(f"[{d.doc_type}] {d.title}\n{d.content}" for d in docs)

    prompt = f'''---
name: Novel Brainstorm
description: 根据设定文档生成小说大纲 Synopsis
---

# 角色设定

你是 **资深商业小说大纲生成专家**，面向网文连载读者。

# 背景信息

```
{combined}
```

# 任务

根据背景信息，生成一份可供后续分卷、分章、分节拍继续展开的大纲。

## 结构要求(在里程碑与人物弧中体现)

1. 采用三幕式或更复杂结构，整部故事至少含 4 个能改变主角处境的转折点，
   每一幕至少 1 个，转折尽量由角色选择驱动（而非纯外力）。
2. 节奏：里程碑分布上，平均每 3 章左右有 1 个小高潮，每卷有 1 个卷级高潮。
3. 伏笔：character_arcs 与 milestones 合计给出 ≥4 个可回收的悬念点，
   每个悬念尽量在 1 卷内给出回收线索。
4. 钩子：整部故事结尾带开放性钩子，能引出下一卷或续作的核心悬念。
5. 人物弧光：主要角色 key_turning_points ≥3 个，且包含一次内在转变
   (信念/价值观/关系的重要变化)。

## 输出格式

请按以下 Markdown 格式输出（最后附上完整的 JSON）：

```markdown
# 《小说标题》

## 一句话梗概
[角色 + 欲望 + 阻力 + 赌注的一句话]

## 核心冲突
[具体对抗关系，如：主角 vs 反派，关于XXX的争夺]

## 主题
- 主题1
- 主题2

## 人物弧光

### 角色名1
弧光概述：[角色弧光简述]
转折点：
1. [转折点1]
2. [转折点2]
3. [转折点3]

### 角色名2
...

## 剧情里程碑

### 第一幕
概述：[本幕概述]
高潮事件：[具体高潮事件]

### 第二幕
...

### 第三幕
...

## 预估
- 卷数：X
- 总章节数：X
- 总字数：X

---

## 完整 JSON（供系统导入）

```json
{{
  "title": "小说标题",
  "logline": "...",
  "core_conflict": "...",
  "themes": [...],
  "character_arcs": [...],
  "milestones": [...],
  "estimated_volumes": 3,
  "estimated_total_chapters": 60,
  "estimated_total_words": 600000
}}
```
```

---

**提示**：
1. 先写 Markdown 部分，这是给人看的
2. 再补上 JSON 部分，这是给系统导入用的
3. 如果对输出满意，在最后加一行 `=== SYNOPSIS COMPLETE ===`
'''

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
    agent = VolumePlannerAgent(session)
    try:
        plan = await agent.plan(novel_id, volume_number=req.volume_number)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    await session.commit()
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


@router.get("/api/novels/{novel_id}/synopsis")
async def get_synopsis(novel_id: str, session: AsyncSession = Depends(get_session)):
    repo = DocumentRepository(session)
    state_repo = NovelStateRepository(session)
    docs = await repo.get_by_type(novel_id, "synopsis")
    if not docs:
        raise HTTPException(status_code=404, detail="Synopsis not found")
    state = await state_repo.get_state(novel_id)
    synopsis_data = {}
    if state and state.checkpoint_data:
        synopsis_data = state.checkpoint_data.get("synopsis_data", {})
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


@router.post("/api/novels/{novel_id}/librarian")
async def run_librarian(novel_id: str, session: AsyncSession = Depends(get_session)):
    director = NovelDirector(session)
    try:
        state = await director.run_librarian(novel_id)
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
    svc = ExportService(session, settings.markdown_output_dir)
    try:
        path = await svc.export_volume(novel_id, volume_id, format=format)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"exported_path": path, "format": format}


@router.post("/api/novels/{novel_id}/export")
async def export_novel(novel_id: str, format: str = "md", session: AsyncSession = Depends(get_session)):
    from novel_dev.services.export_service import ExportService
    svc = ExportService(session, settings.markdown_output_dir)
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


@router.get("/api/novels/{novel_id}/logs/stream")
async def stream_logs(novel_id: str):
    from novel_dev.services.log_service import log_service as _log_service

    q = _log_service.subscribe(novel_id)

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
