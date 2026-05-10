from typing import Optional

from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

from novel_dev.db.models import EntityRelationship
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
from novel_dev.services.embedding_service import EmbeddingService
from novel_dev.llm import llm_factory
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.agents.brainstorm_agent import BrainstormAgent
from novel_dev.agents.volume_planner import VolumePlannerAgent
from novel_dev.schemas.context import ChapterContext
from novel_dev.schemas.outline import VolumePlan, SynopsisData
from novel_dev.services.export_service import ExportService
import uuid as uuid_mod
from novel_dev.config import settings
from novel_dev.mcp_server.registry import MCPToolRegistry
from novel_dev.services.entity_context_sanitizer import sanitize_entity_state_for_context

mcp = FastMCP("novel-dev")


@mcp.tool()
async def query_entity(entity_id: str, novel_id: str = "") -> dict:
    async with async_session_maker() as session:
        svc = EntityService(session)
        entity = await svc.entity_repo.get_by_id(entity_id)
        if not entity:
            return {"error": "Entity not found", "entity_id": entity_id}
        if novel_id and entity.novel_id != novel_id:
            return {"error": "Entity not found in novel", "entity_id": entity_id, "novel_id": novel_id}
        state = sanitize_entity_state_for_context(await svc.get_latest_state(entity_id) or {})
        relationship_result = await session.execute(
            select(EntityRelationship)
            .where(
                EntityRelationship.novel_id == entity.novel_id,
                EntityRelationship.is_active == True,
                (
                    (EntityRelationship.source_id == entity_id)
                    | (EntityRelationship.target_id == entity_id)
                ),
            )
            .order_by(EntityRelationship.id.desc())
            .limit(30)
        )
        relationships = [
            {
                "id": relationship.id,
                "source_id": relationship.source_id,
                "target_id": relationship.target_id,
                "relation_type": relationship.relation_type,
                "meta": relationship.meta or {},
            }
            for relationship in relationship_result.scalars().all()
        ]
        return {
            "entity_id": entity_id,
            "novel_id": entity.novel_id,
            "type": entity.type,
            "name": entity.name,
            "current_version": entity.current_version,
            "state": state,
            "relationships": relationships,
        }


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
async def search_domain_documents(
    novel_id: str,
    query: str,
    domain_name: str = "",
    doc_type: str = "",
    limit: int = 5,
) -> dict:
    async with async_session_maker() as session:
        repo = DocumentRepository(session)
        doc_types = [doc_type] if doc_type else [
            "domain_setting",
            "domain_worldview",
            "domain_synopsis",
            "domain_concept",
            "setting",
            "worldview",
            "synopsis",
            "concept",
        ]
        docs = []
        for current_type in doc_types:
            docs.extend(await repo.get_current_by_type(novel_id, current_type))

        terms = _expand_domain_search_terms(query)
        domain_names = _split_domain_names(domain_name)
        scored = []
        for doc in docs:
            title = doc.title or ""
            content = doc.content or ""
            haystack = f"{title}\n{content}"
            if domain_names and not any(
                _document_matches_domain_name(doc.doc_type, title, content, name)
                for name in domain_names
            ):
                continue
            if terms and not any(term in haystack for term in terms):
                continue
            score = 0
            for name in domain_names:
                if name in title:
                    score += 20
                elif name in content:
                    score += 10
            for term in terms:
                if term in title:
                    score += 6
                if term in content:
                    score += 2
            scored.append((score, doc))

        scored.sort(
            key=lambda item: (
                item[0],
                item[1].updated_at.timestamp() if item[1].updated_at else 0,
            ),
            reverse=True,
        )
        max_limit = min(max(int(limit or 5), 1), 10)
        return {
            "documents": [
                {
                    "id": doc.id,
                    "doc_type": doc.doc_type,
                    "title": doc.title,
                    "version": doc.version,
                    "content_preview": doc.content[:1200],
                    "score": score,
                }
                for score, doc in scored[:max_limit]
            ]
        }


def _split_domain_names(domain_name: str) -> list[str]:
    normalized = (
        domain_name.replace("，", ",")
        .replace("、", ",")
        .replace("；", ",")
        .replace(";", ",")
        .replace("/", ",")
    )
    return [item.strip() for item in normalized.split(",") if item.strip()]


def _expand_domain_search_terms(query: str) -> list[str]:
    normalized = query.replace("，", " ").replace(",", " ").replace("、", " ")
    terms = [term.strip() for term in normalized.split() if term.strip()]
    if any(marker in query for marker in ("境界", "修炼", "对标", "映射")):
        terms.extend(["境界", "修炼", "体系"])
    if any(marker in query for marker in ("剧情", "梗概", "事件", "节点")):
        terms.extend(["剧情", "梗概", "事件"])
    if any(marker in query for marker in ("人物", "主角", "角色")):
        terms.extend(["人物", "主角"])
    return list(dict.fromkeys(terms))


def _document_matches_domain_name(doc_type: str, title: str, content: str, domain_name: str) -> bool:
    if str(doc_type or "").startswith("domain_"):
        return domain_name in title
    return domain_name in f"{title}\n{content}"


@mcp.tool()
async def upload_document(novel_id: str, filename: str, content: str) -> dict:
    async with async_session_maker() as session:
        embedder = llm_factory.get_embedder()
        embedding_service = EmbeddingService(session, embedder)
        svc = ExtractionService(session, embedding_service)
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
        embedder = llm_factory.get_embedder()
        embedding_service = EmbeddingService(session, embedder)
        svc = ExtractionService(session, embedding_service)
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
            embedder = llm_factory.get_embedder()
            embedding_service = EmbeddingService(session, embedder)
            svc = ExtractionService(session, embedding_service)
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
        embedder = llm_factory.get_embedder()
        embedding_service = EmbeddingService(session, embedder)
        agent = ContextAgent(session, embedding_service)
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
        embedder = llm_factory.get_embedder()
        embedding_service = EmbeddingService(session, embedder)
        agent = WriterAgent(session, embedding_service)
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
    async with async_session_maker() as session:
        svc = ExportService(session, settings.data_dir)
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


@mcp.tool()
async def get_novel_document_full(novel_id: str, doc_id: str) -> dict:
    async with async_session_maker() as session:
        repo = DocumentRepository(session)
        doc = await repo.get_by_id(doc_id)
        if not doc or doc.novel_id != novel_id:
            return {"error": "Document not found"}
        return {
            "id": doc.id,
            "title": doc.title,
            "content": doc.content,
            "doc_type": doc.doc_type,
        }


@mcp.tool()
async def save_brainstorm_draft(novel_id: str, synopsis_data: dict) -> dict:
    async with async_session_maker() as session:
        state_repo = NovelStateRepository(session)
        state = await state_repo.get_state(novel_id)
        if not state or state.current_phase != Phase.BRAINSTORMING.value:
            return {"error": "Novel is not in brainstorming phase"}
        synopsis = SynopsisData.model_validate(synopsis_data)
        checkpoint = dict(state.checkpoint_data or {})
        checkpoint["pending_synopsis"] = synopsis.model_dump()
        director = NovelDirector(session)
        await director.save_checkpoint(
            novel_id,
            phase=Phase.BRAINSTORMING,
            checkpoint_data=checkpoint,
            volume_id=state.current_volume_id,
            chapter_id=state.current_chapter_id,
        )
        await session.commit()
        return {"saved": True}


@mcp.tool()
async def confirm_brainstorm(novel_id: str) -> dict:
    async with async_session_maker() as session:
        state_repo = NovelStateRepository(session)
        state = await state_repo.get_state(novel_id)
        if not state or state.current_phase != Phase.BRAINSTORMING.value:
            return {"error": "Novel is not in brainstorming phase"}
        checkpoint = dict(state.checkpoint_data or {})
        pending = checkpoint.get("pending_synopsis")
        if not pending:
            return {"error": "No pending synopsis found"}
        synopsis = SynopsisData.model_validate(pending)
        agent = BrainstormAgent(session)
        synopsis_text = agent.format_synopsis_text(synopsis, "")
        doc_repo = DocumentRepository(session)
        await doc_repo.create(
            doc_id=f"doc_{uuid_mod.uuid4().hex[:8]}",
            novel_id=novel_id,
            doc_type="synopsis",
            title=synopsis.title,
            content=synopsis_text,
        )
        checkpoint["synopsis_data"] = synopsis.model_dump()
        checkpoint.pop("pending_synopsis", None)
        director = NovelDirector(session)
        await director.save_checkpoint(
            novel_id,
            phase=Phase.VOLUME_PLANNING,
            checkpoint_data=checkpoint,
            volume_id=state.current_volume_id,
            chapter_id=state.current_chapter_id,
        )
        await session.commit()
        return {"confirmed": True}


_WRITE_TOOL_NAMES = {
    "upload_document",
    "approve_pending_documents",
    "rollback_style_profile",
    "prepare_chapter_context",
    "generate_chapter_draft",
    "advance_novel",
    "brainstorm_novel",
    "plan_volume",
    "run_librarian",
    "save_brainstorm_draft",
    "confirm_brainstorm",
}

internal_mcp_registry = MCPToolRegistry.from_fastmcp(
    mcp,
    write_tool_names=_WRITE_TOOL_NAMES,
)
