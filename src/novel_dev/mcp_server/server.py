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
from novel_dev.schemas.context import ChapterContext


class NovelDevMCPServer:
    """Lightweight MCP-compatible server without requiring the official mcp SDK."""

    def __init__(self):
        self.tools = {
            "query_entity": self.query_entity,
            "get_active_foreshadowings": self.get_active_foreshadowings,
            "get_timeline": self.get_timeline,
            "get_spaceline_chain": self.get_spaceline_chain,
            "get_novel_state": self.get_novel_state,
            "get_novel_documents": self.get_novel_documents,
            "upload_document": self.upload_document,
            "get_pending_documents": self.get_pending_documents,
            "approve_pending_documents": self.approve_pending_documents,
            "list_style_profile_versions": self.list_style_profile_versions,
            "rollback_style_profile": self.rollback_style_profile,
            "analyze_style_from_text": self.analyze_style_from_text,
            "prepare_chapter_context": self.prepare_chapter_context,
            "generate_chapter_draft": self.generate_chapter_draft,
            "get_chapter_draft_status": self.get_chapter_draft_status,
        }

    async def query_entity(self, entity_id: str) -> dict:
        async with async_session_maker() as session:
            svc = EntityService(session)
            state = await svc.get_latest_state(entity_id)
            return {"entity_id": entity_id, "state": state}

    async def get_active_foreshadowings(self) -> list:
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

    async def get_timeline(self) -> dict:
        async with async_session_maker() as session:
            repo = TimelineRepository(session)
            tick = await repo.get_current_tick()
            return {"current_tick": tick}

    async def get_spaceline_chain(self, location_id: str) -> list:
        async with async_session_maker() as session:
            repo = SpacelineRepository(session)
            chain = await repo.get_chain(location_id)
            return [{"id": node.id, "name": node.name} for node in chain]

    async def get_novel_state(self, novel_id: str) -> dict:
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

    async def get_novel_documents(self, novel_id: str, doc_type: str) -> list:
        async with async_session_maker() as session:
            repo = DocumentRepository(session)
            docs = await repo.get_by_type(novel_id, doc_type)
            return [{"id": d.id, "title": d.title, "content": d.content[:500]} for d in docs]

    async def upload_document(self, novel_id: str, filename: str, content: str) -> dict:
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

    async def get_pending_documents(self, novel_id: str) -> list:
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

    async def approve_pending_documents(self, pending_id: str) -> dict:
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

    async def list_style_profile_versions(self, novel_id: str) -> list:
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

    async def rollback_style_profile(self, novel_id: str, version: int) -> dict:
        try:
            async with async_session_maker() as session:
                svc = ExtractionService(session)
                await svc.rollback_style_profile(novel_id, version)
                await session.commit()
                return {"rolled_back_to_version": version}
        except Exception as e:
            return {"error": str(e)}

    async def analyze_style_from_text(self, text: str) -> dict:
        try:
            agent = StyleProfilerAgent()
            profile = await agent.profile(text)
            return profile.model_dump()
        except Exception as e:
            return {"error": str(e)}

    async def prepare_chapter_context(self, novel_id: str, chapter_id: str) -> dict:
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

    async def generate_chapter_draft(self, novel_id: str, chapter_id: str) -> dict:
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

    async def get_chapter_draft_status(self, novel_id: str, chapter_id: str) -> dict:
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


mcp = NovelDevMCPServer()
