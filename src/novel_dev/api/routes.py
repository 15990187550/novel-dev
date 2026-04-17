from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.engine import async_session_maker
from novel_dev.services.entity_service import EntityService
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.storage.markdown_sync import MarkdownSync
from novel_dev.config import Settings
from pydantic import BaseModel
from novel_dev.services.extraction_service import ExtractionService
from novel_dev.repositories.pending_extraction_repo import PendingExtractionRepository
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.agents.context_agent import ContextAgent
from novel_dev.agents.writer_agent import WriterAgent
from novel_dev.agents.director import NovelDirector
from novel_dev.schemas.context import ChapterContext
from novel_dev.agents.brainstorm_agent import BrainstormAgent
from novel_dev.agents.volume_planner import VolumePlannerAgent
from novel_dev.schemas.outline import VolumePlan

router = APIRouter()
settings = Settings()


async def get_session():
    async with async_session_maker() as session:
        yield session


from sqlalchemy import select
from novel_dev.db.models import NovelState


@router.get("/api/novels")
async def list_novels(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(NovelState.novel_id, NovelState.current_phase, NovelState.last_updated)
        .order_by(NovelState.last_updated.desc())
    )
    rows = result.all()
    return {
        "items": [
            {
                "novel_id": r.novel_id,
                "current_phase": r.current_phase,
                "last_updated": r.last_updated.isoformat() if r.last_updated else None,
            }
            for r in rows
        ]
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
    from sqlalchemy import select
    from novel_dev.db.models import Entity
    result = await session.execute(
        select(Entity).where(Entity.novel_id == novel_id).order_by(Entity.name)
    )
    svc = EntityService(session)
    items = []
    for ent in result.scalars().all():
        state = await svc.get_latest_state(ent.id)
        items.append({
            "entity_id": ent.id,
            "type": ent.type,
            "name": ent.name,
            "current_version": ent.current_version,
            "created_at_chapter_id": ent.created_at_chapter_id,
            "latest_state": state,
        })
    return {"items": items}


@router.get("/api/novels/{novel_id}/entities/{entity_id}")
async def get_entity(novel_id: str, entity_id: str, session: AsyncSession = Depends(get_session)):
    svc = EntityService(session)
    state = await svc.get_latest_state(entity_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return {"entity_id": entity_id, "latest_state": state}


@router.get("/api/novels/{novel_id}/timelines")
async def list_timelines(novel_id: str, session: AsyncSession = Depends(get_session)):
    from sqlalchemy import select
    from novel_dev.db.models import Timeline
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
    from sqlalchemy import select
    from novel_dev.db.models import Spaceline
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
    from sqlalchemy import select
    from novel_dev.db.models import Foreshadowing
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
        from sqlalchemy import select
        from novel_dev.db.models import Chapter
        result = await session.execute(select(Chapter).where(Chapter.id.in_(chapter_ids)))
        for ch in result.scalars().all():
            db_chapters[ch.id] = ch

    items = []
    for pc in plan_chapters:
        cid = pc.get("chapter_id")
        ch = db_chapters.get(cid)
        word_count = len(ch.polished_text or ch.raw_draft or "") if ch else 0
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
        "word_count": len(ch.polished_text or ch.raw_draft or ""),
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


class ApproveRequest(BaseModel):
    pending_id: str


class RollbackRequest(BaseModel):
    version: int


class ChapterContextRequest(BaseModel):
    pass


class ChapterDraftRequest(BaseModel):
    pass


@router.post("/api/novels/{novel_id}/documents/upload")
async def upload_document(novel_id: str, req: UploadRequest, session: AsyncSession = Depends(get_session)):
    svc = ExtractionService(session)
    pe = await svc.process_upload(novel_id, req.filename, req.content)
    return {
        "id": pe.id,
        "extraction_type": pe.extraction_type,
        "status": pe.status,
        "created_at": pe.created_at.isoformat(),
    }


@router.get("/api/novels/{novel_id}/documents/pending")
async def get_pending_documents(novel_id: str, session: AsyncSession = Depends(get_session)):
    repo = PendingExtractionRepository(session)
    items = await repo.list_by_novel(novel_id)
    return {
        "items": [
            {
                "id": i.id,
                "extraction_type": i.extraction_type,
                "status": i.status,
                "raw_result": i.raw_result,
                "proposed_entities": i.proposed_entities,
                "created_at": i.created_at.isoformat(),
            }
            for i in items
        ]
    }


@router.post("/api/novels/{novel_id}/documents/pending/approve")
async def approve_pending_document(novel_id: str, req: ApproveRequest, session: AsyncSession = Depends(get_session)):
    svc = ExtractionService(session)
    repo = PendingExtractionRepository(session)
    pe = await repo.get_by_id(req.pending_id)
    if not pe or pe.novel_id != novel_id:
        raise HTTPException(status_code=403, detail="Pending extraction does not belong to this novel")
    docs = await svc.approve_pending(req.pending_id)
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
    svc = ExtractionService(session)
    await svc.rollback_style_profile(novel_id, req.version)
    return {"rolled_back_to_version": req.version}


@router.post("/api/novels/{novel_id}/chapters/{chapter_id}/context")
async def prepare_chapter_context(
    novel_id: str,
    chapter_id: str,
    session: AsyncSession = Depends(get_session),
):
    agent = ContextAgent(session)
    try:
        context = await agent.assemble(novel_id, chapter_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
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
    agent = WriterAgent(session)
    try:
        metadata = await agent.write(novel_id, context, chapter_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

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
    return {
        "title": synopsis_data.title,
        "logline": synopsis_data.logline,
        "estimated_volumes": synopsis_data.estimated_volumes,
        "estimated_total_chapters": synopsis_data.estimated_total_chapters,
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
    return {
        "novel_id": state.novel_id,
        "current_phase": state.current_phase,
        "checkpoint_data": state.checkpoint_data,
    }


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
