from novel_dev.db.engine import async_session_maker
from novel_dev.services.entity_service import EntityService
from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
from novel_dev.repositories.timeline_repo import TimelineRepository
from novel_dev.repositories.spaceline_repo import SpacelineRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.document_repo import DocumentRepository


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


mcp = NovelDevMCPServer()
