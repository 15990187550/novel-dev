from typing import Optional

from mcp.server.fastmcp import FastMCP

from novel_dev.db.engine import async_session_maker
from novel_dev.services.entity_service import EntityService
from novel_dev.services.extraction_service import ExtractionService
from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
from novel_dev.repositories.timeline_repo import TimelineRepository
from novel_dev.repositories.spaceline_repo import SpacelineRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.pending_extraction_repo import PendingExtractionRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.agents.style_profiler import StyleProfilerAgent
from novel_dev.agents.context_agent import ContextAgent
from novel_dev.agents.writer_agent import WriterAgent
from novel_dev.agents.director import NovelDirector
from novel_dev.agents.brainstorm_agent import BrainstormAgent
from novel_dev.agents.volume_planner import VolumePlannerAgent
from novel_dev.schemas.context import ChapterContext
from novel_dev.schemas.outline import VolumePlan
from novel_dev.services.export_service import ExportService
from novel_dev.config import Settings

mcp = FastMCP("novel-dev")


@mcp.tool()
async def query_entity(entity_id: str) -> dict:
    async with async_session_maker() as session:
        svc = EntityService(session)
        state = await svc.get_latest_state(entity_id)
        return {"entity_id": entity_id, "state": state}


@mcp.tool()
async def get_active_foreshadowings() -> list:
    async with async_session_maker() as session:
        repo = ForeshadowingRepository(session)
        items = await repo.list_active()
        return [
            {
                "id": fs.id,
                "content": fs.content,
                "回收条件": fs.回收条件,
            }
            for fs in items
        ]


@mcp.tool()
async def get_timeline() -> dict:
    async with async_session_maker() as session:
        repo = TimelineRepository(session)
        tick = await repo.get_current_tick()
        return {"current_tick": tick}


@mcp.tool()
async def get_spaceline_chain(location_id: str) -> list:
    async with async_session_maker() as session:
        repo = SpacelineRepository(session)
        chain = await repo.get_chain(location_id)
        return [{"id": node.id, "name": node.name} for node in chain]


@mcp.tool()
async def get_novel_state(novel_id: str) -> dict:
    async with async_session_maker() as session:
        repo = NovelStateRepository(session)
        state = await repo.get_state(novel_id)
        if not state:
            return {"error": "not found"}
        return {
            "novel_id": state.novel_id,
            "current_phase": state.current_phase,
            "checkpoint_data": state.checkpoint_data,
        }


@mcp.tool()
async def get_novel_documents(novel_id: str, doc_type: str) -> list:
    async with async_session_maker() as session:
        repo = DocumentRepository(session)
        docs = await repo.get_by_type(novel_id, doc_type)
        return [{"id": d.id, "title": d.title, "content": d.content[:500]} for d in docs]


@mcp.tool()
async def upload_document(novel_id: str, filename: str, content: str) -> dict:
    async with async_session_maker() as session:
        svc = ExtractionService(session)
        pe = await svc.process_upload(novel_id, filename, content)
        await session.commit()
        return {
            "id": pe.id,
            "extraction_type": pe.extraction_type,
            "status": pe.status,
            "created_at": pe.created_at.isoformat(),
        }


@mcp.tool()
async def get_pending_documents(novel_id: str) -> list:
    async with async_session_maker() as session:
        repo = PendingExtractionRepository(session)
        items = await repo.list_by_novel(novel_id)
        return [
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


@mcp.tool()
async def approve_pending_documents(pending_id: str) -> dict:
    async with async_session_maker() as session:
        svc = ExtractionService(session)
        docs = await svc.approve_pending(pending_id)
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


@mcp.tool()
async def list_style_profile_versions(novel_id: str) -> list:
    async with async_session_maker() as session:
        repo = DocumentRepository(session)
        docs = await repo.get_by_type(novel_id, "style_profile")
        return [
            {
                "version": d.version,
                "updated_at": d.updated_at.isoformat() if d.updated_at else None,
                "title": d.title,
            }
            for d in docs
        ]


@mcp.tool()
async def rollback_style_profile(novel_id: str, version: int) -> dict:
    try:
        async with async_session_maker() as session:
            svc = ExtractionService(session)
            await svc.rollback_style_profile(novel_id, version)
            await session.commit()
            return {"rolled_back_to_version": version}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def analyze_style_from_text(text: str) -> dict:
    try:
        agent = StyleProfilerAgent()
        profile = await agent.profile(text)
        return profile.model_dump()
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def prepare_chapter_context(novel_id: str, chapter_id: str) -> dict:
    async with async_session_maker() as session:
        agent = ContextAgent(session)
        try:
            context = await agent.assemble(novel_id, chapter_id)
            await session.commit()
            return {
                "success": True,
                "chapter_plan_title": context.chapter_plan.title,
                "active_entities_count": len(context.active_entities),
                "pending_foreshadowings_count": len(context.pending_foreshadowings),
            }
        except ValueError as e:
            return {"success": False, "error": str(e)}


@mcp.tool()
async def generate_chapter_draft(novel_id: str, chapter_id: str) -> dict:
    async with async_session_maker() as session:
        state_repo = NovelStateRepository(session)
        state = await state_repo.get_state(novel_id)
        if not state:
            return {"error": "Novel state not found"}
        checkpoint = state.checkpoint_data or {}
        context_data = checkpoint.get("chapter_context")
        if not context_data:
            return {"error": "Chapter context not prepared"}
        context = ChapterContext.model_validate(context_data)
        agent = WriterAgent(session)
        try:
            metadata = await agent.write(novel_id, context, chapter_id)
            await session.commit()
            return metadata.model_dump()
        except Exception as e:
            return {"error": str(e)}


@mcp.tool()
async def get_chapter_draft_status(novel_id: str, chapter_id: str) -> dict:
    async with async_session_maker() as session:
        repo = ChapterRepository(session)
        ch = await repo.get_by_id(chapter_id)
        state_repo = NovelStateRepository(session)
        state = await state_repo.get_state(novel_id)
        if not state:
            return {"error": "Novel state not found"}
        checkpoint = state.checkpoint_data if state else {}
        return {
            "chapter_id": chapter_id,
            "status": ch.status if ch else None,
            "raw_draft": ch.raw_draft if ch else None,
            "drafting_progress": checkpoint.get("drafting_progress"),
            "draft_metadata": checkpoint.get("draft_metadata"),
        }


@mcp.tool()
async def advance_novel(novel_id: str) -> dict:
    async with async_session_maker() as session:
        director = NovelDirector(session)
        try:
            state = await director.advance(novel_id)
            await session.commit()
            return {
                "novel_id": state.novel_id,
                "current_phase": state.current_phase,
                "checkpoint_data": state.checkpoint_data,
            }
        except ValueError as e:
            return {"error": str(e)}
        except RuntimeError as e:
            return {"error": str(e)}


@mcp.tool()
async def get_review_result(novel_id: str) -> dict:
    async with async_session_maker() as session:
        state_repo = NovelStateRepository(session)
        state = await state_repo.get_state(novel_id)
        if not state:
            return {"error": "Novel state not found"}
        if not state.current_chapter_id:
            return {"error": "Current chapter not set"}
        repo = ChapterRepository(session)
        ch = await repo.get_by_id(state.current_chapter_id)
        if not ch:
            return {"error": "Chapter not found"}
        return {
            "score_overall": ch.score_overall,
            "score_breakdown": ch.score_breakdown,
            "review_feedback": ch.review_feedback,
        }


@mcp.tool()
async def get_fast_review_result(novel_id: str) -> dict:
    async with async_session_maker() as session:
        state_repo = NovelStateRepository(session)
        state = await state_repo.get_state(novel_id)
        if not state:
            return {"error": "Novel state not found"}
        if not state.current_chapter_id:
            return {"error": "Current chapter not set"}
        repo = ChapterRepository(session)
        ch = await repo.get_by_id(state.current_chapter_id)
        if not ch:
            return {"error": "Chapter not found"}
        return {
            "fast_review_score": ch.fast_review_score,
            "fast_review_feedback": ch.fast_review_feedback,
        }


@mcp.tool()
async def brainstorm_novel(novel_id: str) -> dict:
    async with async_session_maker() as session:
        agent = BrainstormAgent(session)
        try:
            synopsis_data = await agent.brainstorm(novel_id)
            await session.commit()
            return {
                "title": synopsis_data.title,
                "logline": synopsis_data.logline,
                "estimated_volumes": synopsis_data.estimated_volumes,
                "estimated_total_chapters": synopsis_data.estimated_total_chapters,
            }
        except ValueError as e:
            return {"error": str(e)}


@mcp.tool()
async def plan_volume(novel_id: str, volume_number: Optional[int] = None) -> dict:
    async with async_session_maker() as session:
        agent = VolumePlannerAgent(session)
        try:
            plan = await agent.plan(novel_id, volume_number)
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
        except ValueError as e:
            return {"error": str(e)}


@mcp.tool()
async def get_synopsis(novel_id: str) -> dict:
    try:
        async with async_session_maker() as session:
            repo = DocumentRepository(session)
            state_repo = NovelStateRepository(session)
            docs = await repo.get_by_type(novel_id, "synopsis")
            if not docs:
                return {"error": "Synopsis not found"}
            state = await state_repo.get_state(novel_id)
            synopsis_data = {}
            if state and state.checkpoint_data:
                synopsis_data = state.checkpoint_data.get("synopsis_data", {})
            return {
                "content": docs[0].content,
                "synopsis_data": synopsis_data,
            }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def get_volume_plan(novel_id: str) -> dict:
    try:
        async with async_session_maker() as session:
            state_repo = NovelStateRepository(session)
            state = await state_repo.get_state(novel_id)
            if not state or not state.checkpoint_data.get("current_volume_plan"):
                return {"error": "Volume plan not found"}
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
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def run_librarian(novel_id: str) -> dict:
    async with async_session_maker() as session:
        director = NovelDirector(session)
        try:
            state = await director.run_librarian(novel_id)
            await session.commit()
            return {
                "novel_id": state.novel_id,
                "current_phase": state.current_phase,
                "checkpoint_data": state.checkpoint_data,
            }
        except ValueError as e:
            return {"error": str(e)}
        except RuntimeError as e:
            return {"error": str(e)}


@mcp.tool()
async def export_novel(novel_id: str, format: str = "md") -> dict:
    settings = Settings()
    async with async_session_maker() as session:
        svc = ExportService(session, settings.markdown_output_dir)
        try:
            path = await svc.export_novel(novel_id, format=format)
            return {"exported_path": path, "format": format}
        except ValueError as e:
            return {"error": str(e)}


@mcp.tool()
async def get_archive_stats(novel_id: str) -> dict:
    async with async_session_maker() as session:
        repo = NovelStateRepository(session)
        state = await repo.get_state(novel_id)
        if not state:
            return {"error": "Novel state not found"}
        stats = state.checkpoint_data.get("archive_stats", {})
        return {
            "total_word_count": stats.get("total_word_count", 0),
            "archived_chapter_count": stats.get("archived_chapter_count", 0),
            "avg_word_count": stats.get("avg_word_count", 0),
        }
