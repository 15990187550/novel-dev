import uuid
import json
import logging
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.agents.file_classifier import FileClassifier
from novel_dev.agents.setting_extractor import SettingExtractorAgent
from novel_dev.agents.style_profiler import StyleProfilerAgent, StyleProfile, StyleConfig
from novel_dev.agents.profile_merger import ProfileMerger
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.pending_extraction_repo import PendingExtractionRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.services.entity_service import EntityService
from novel_dev.services.embedding_service import EmbeddingService
from novel_dev.db.models import NovelDocument, PendingExtraction

logger = logging.getLogger(__name__)


class ExtractionService:
    def __init__(self, session: AsyncSession, embedding_service: Optional[EmbeddingService] = None):
        self.session = session
        self.classifier = FileClassifier()
        self.setting_agent = SettingExtractorAgent()
        self.style_agent = StyleProfilerAgent()
        self.merger = ProfileMerger()
        self.doc_repo = DocumentRepository(session)
        self.pending_repo = PendingExtractionRepository(session)
        self.state_repo = NovelStateRepository(session)
        self.entity_svc = EntityService(session, embedding_service)

    async def process_upload(self, novel_id: str, filename: str, content: str) -> PendingExtraction:
        classification = await self.classifier.classify(filename, content)

        if classification.file_type == "setting":
            extracted = await self.setting_agent.extract(content)
            raw_result = extracted.model_dump()
            proposed_entities = []
            for c in extracted.character_profiles:
                proposed_entities.append({"type": "character", "name": c.name, "data": c.model_dump()})
            for i in extracted.important_items:
                proposed_entities.append({"type": "item", "name": i.name, "data": i.model_dump()})
            if extracted.factions:
                proposed_entities.append({"type": "faction", "name": "extracted_factions", "data": {"factions": extracted.factions}})

            return await self.pending_repo.create(
                pe_id=f"pe_{uuid.uuid4().hex[:8]}",
                novel_id=novel_id,
                extraction_type="setting",
                raw_result=raw_result,
                proposed_entities=proposed_entities,
            )
        else:
            profile = await self.style_agent.profile(content)
            raw_result = profile.model_dump()
            return await self.pending_repo.create(
                pe_id=f"pe_{uuid.uuid4().hex[:8]}",
                novel_id=novel_id,
                extraction_type="style_profile",
                raw_result=raw_result,
            )

    async def approve_pending(self, pe_id: str) -> List[NovelDocument]:
        pe = await self.pending_repo.get_by_id(pe_id)
        if not pe or pe.status != "pending":
            return []

        docs: List[NovelDocument] = []
        if pe.extraction_type == "setting":
            raw = pe.raw_result
            mappings = [
                ("worldview", "worldview", "世界观"),
                ("power_system", "setting", "修炼体系"),
                ("factions", "setting", "势力格局"),
                ("plot_synopsis", "synopsis", "剧情梗概"),
            ]
            for key, doc_type, title in mappings:
                val = raw.get(key)
                if val:
                    text_val = val if isinstance(val, str) else str(val)
                    doc = await self.doc_repo.create(
                        doc_id=f"doc_{uuid.uuid4().hex[:8]}",
                        novel_id=pe.novel_id,
                        doc_type=doc_type,
                        title=title,
                        content=text_val,
                    )
                    docs.append(doc)

            chars = raw.get("character_profiles", [])
            if chars:
                text = "\n".join(f"{c.get('name')}: {c.get('identity')} {c.get('personality')}" for c in chars)
                doc = await self.doc_repo.create(
                    doc_id=f"doc_{uuid.uuid4().hex[:8]}",
                    novel_id=pe.novel_id,
                    doc_type="concept",
                    title="人物设定",
                    content=text,
                )
                docs.append(doc)
                for c in chars:
                    await self.entity_svc.create_entity(
                        entity_id=f"ent_{uuid.uuid4().hex[:8]}",
                        entity_type="character",
                        name=c.get("name", "unknown"),
                    )

            items = raw.get("important_items", [])
            if items:
                text = "\n".join(f"{i.get('name')}: {i.get('description')}" for i in items)
                doc = await self.doc_repo.create(
                    doc_id=f"doc_{uuid.uuid4().hex[:8]}",
                    novel_id=pe.novel_id,
                    doc_type="concept",
                    title="物品设定",
                    content=text,
                )
                docs.append(doc)
                for i in items:
                    await self.entity_svc.create_entity(
                        entity_id=f"ent_{uuid.uuid4().hex[:8]}",
                        entity_type="item",
                        name=i.get("name", "unknown"),
                    )

        else:
            # style_profile
            latest = await self.doc_repo.get_latest_by_type(pe.novel_id, "style_profile")
            new_profile = StyleProfile(**pe.raw_result)
            if latest:
                old_config = StyleConfig()
                if latest.title:
                    try:
                        old_config = StyleConfig(**json.loads(latest.title))
                    except Exception:
                        pass
                old = StyleProfile(style_guide=latest.content, style_config=old_config)
                merged = self.merger.merge(old, new_profile)
                version = latest.version + 1
                doc = await self.doc_repo.create(
                    doc_id=f"doc_{uuid.uuid4().hex[:8]}",
                    novel_id=pe.novel_id,
                    doc_type="style_profile",
                    title=merged.merged_profile.style_config.model_dump_json(),
                    content=merged.merged_profile.style_guide,
                    version=version,
                )
            else:
                doc = await self.doc_repo.create(
                    doc_id=f"doc_{uuid.uuid4().hex[:8]}",
                    novel_id=pe.novel_id,
                    doc_type="style_profile",
                    title=new_profile.style_config.model_dump_json(),
                    content=new_profile.style_guide,
                    version=1,
                )
            docs.append(doc)

        await self.pending_repo.update_status(pe_id, "approved")
        return docs

    async def get_active_style_profile(self, novel_id: str) -> Optional[NovelDocument]:
        state = await self.state_repo.get_state(novel_id)
        active_version = None
        if state and state.checkpoint_data:
            active_version = state.checkpoint_data.get("active_style_profile_version")
        if active_version:
            return await self.doc_repo.get_by_type_and_version(novel_id, "style_profile", active_version)
        return await self.doc_repo.get_latest_by_type(novel_id, "style_profile")

    async def rollback_style_profile(self, novel_id: str, version: int) -> None:
        state = await self.state_repo.get_state(novel_id)
        if state is None:
            await self.state_repo.save_checkpoint(
                novel_id=novel_id,
                current_phase="context_preparation",
                checkpoint_data={"active_style_profile_version": version},
            )
        else:
            checkpoint = dict(state.checkpoint_data)
            checkpoint["active_style_profile_version"] = version
            await self.state_repo.save_checkpoint(
                novel_id=novel_id,
                current_phase=state.current_phase,
                checkpoint_data=checkpoint,
                current_volume_id=state.current_volume_id,
                current_chapter_id=state.current_chapter_id,
            )
