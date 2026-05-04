import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.agents._llm_helpers import call_and_parse_model, coerce_to_text
from novel_dev.db.models import Entity
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.relationship_repo import RelationshipRepository

logger = logging.getLogger(__name__)


class ExtractedRelationship(BaseModel):
    source_entity_name: str
    target_entity_name: str
    relation_type: str
    evidence: str = ""
    confidence: float = 0.0
    source_role: str = ""
    target_role: str = ""

    @field_validator(
        "source_entity_name",
        "target_entity_name",
        "relation_type",
        "evidence",
        "source_role",
        "target_role",
        mode="before",
    )
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0


class RelationshipExtractionResult(BaseModel):
    relationships: list[ExtractedRelationship] = Field(default_factory=list)


RelationshipExtractor = Callable[
    [str, str, str, list[dict[str, str]]],
    Awaitable[RelationshipExtractionResult | dict[str, Any]],
]


class RelationshipExtractionService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        extractor: RelationshipExtractor | None = None,
    ):
        self.session = session
        self.entity_repo = EntityRepository(session)
        self.relationship_repo = RelationshipRepository(session)
        self.extractor = extractor

    async def extract_and_persist_from_setting(
        self,
        *,
        novel_id: str,
        source_text: str,
        source_ref: str,
        domain_id: str | None = None,
        domain_name: str | None = None,
    ) -> dict[str, Any]:
        entities = await self.entity_repo.list_by_novel(novel_id)
        candidates = self._serialize_candidates(entities, domain_id=domain_id, domain_name=domain_name)
        if len(candidates) < 2 or not (source_text or "").strip():
            return {"created": 0, "skipped": [], "extracted": 0}

        try:
            extracted = await self._extract(novel_id, source_text, source_ref, candidates)
        except Exception as exc:
            logger.warning(
                "relationship_extraction_failed",
                extra={"novel_id": novel_id, "source_ref": source_ref, "error": str(exc)},
            )
            return {
                "created": 0,
                "skipped": [],
                "extracted": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }

        created = 0
        skipped: list[dict[str, str]] = []
        for relationship in extracted.relationships:
            source = self._resolve_entity(entities, relationship.source_entity_name, domain_id, domain_name)
            target = self._resolve_entity(entities, relationship.target_entity_name, domain_id, domain_name)
            if source is None or target is None or source.id == target.id:
                skipped.append(
                    {
                        "source_entity_name": relationship.source_entity_name,
                        "target_entity_name": relationship.target_entity_name,
                        "relation_type": relationship.relation_type,
                        "reason": "entity_not_found_or_ambiguous",
                    }
                )
                continue

            await self.relationship_repo.upsert(
                source_id=source.id,
                target_id=target.id,
                relation_type=relationship.relation_type,
                meta={
                    "source": "llm_relationship_extraction",
                    "source_ref": source_ref,
                    "evidence": relationship.evidence,
                    "confidence": relationship.confidence,
                    "source_role": relationship.source_role,
                    "target_role": relationship.target_role,
                    "domain_id": domain_id,
                    "domain_name": domain_name,
                    "raw_relation": relationship.model_dump(),
                },
                novel_id=novel_id,
            )
            created += 1

        return {"created": created, "skipped": skipped, "extracted": len(extracted.relationships)}

    async def _extract(
        self,
        novel_id: str,
        source_text: str,
        source_ref: str,
        candidates: list[dict[str, str]],
    ) -> RelationshipExtractionResult:
        if self.extractor is not None:
            result = await self.extractor(novel_id, source_text, source_ref, candidates)
            return RelationshipExtractionResult.model_validate(result)

        prompt = self._build_prompt(source_text, source_ref, candidates)
        return await call_and_parse_model(
            "RelationshipExtractionService",
            "extract_setting_relationships",
            prompt,
            RelationshipExtractionResult,
            max_retries=2,
            novel_id=novel_id,
            config_agent_name="SettingExtractorAgent",
            config_task="extract_setting",
        )

    def _build_prompt(
        self,
        source_text: str,
        source_ref: str,
        candidates: list[dict[str, str]],
    ) -> str:
        return (
            "你是小说设定关系抽取器。只从资料文本中抽取实体之间明确成立的关系，"
            "返回严格 JSON，格式为 {\"relationships\": [...]}。\n"
            "每条 relationship 必须包含 source_entity_name, target_entity_name, relation_type, "
            "evidence, confidence, source_role, target_role。\n"
            "规则：\n"
            "- source_entity_name 和 target_entity_name 必须来自候选实体 name。\n"
            "- relation_type 写文本中能支持的具体关系，例如 妻子、父亲、师父、师兄、盟友、宿敌、所修功法、所属势力。\n"
            "- evidence 必须摘录或概括能支持关系的原文依据。\n"
            "- 不确定或跨设定域的关系不要输出。\n"
            "- 不输出泛泛的“关联”，除非原文只说明弱关联且没有更具体关系。\n\n"
            f"资料来源：{source_ref}\n"
            f"候选实体：\n{json.dumps(candidates, ensure_ascii=False)}\n\n"
            f"资料文本：\n{source_text}\n"
        )

    def _serialize_candidates(
        self,
        entities: list[Entity],
        *,
        domain_id: str | None,
        domain_name: str | None,
    ) -> list[dict[str, str]]:
        rows = []
        for entity in entities:
            if not self._entity_in_domain(entity, domain_id, domain_name):
                continue
            rows.append(
                {
                    "id": entity.id,
                    "name": entity.name,
                    "type": entity.type,
                    "category": EntityRepository._effective_category(entity),
                }
            )
        return rows

    def _resolve_entity(
        self,
        entities: list[Entity],
        name: str,
        domain_id: str | None,
        domain_name: str | None,
    ) -> Entity | None:
        normalized = EntityRepository.normalize_name(name)
        if not normalized:
            return None
        matches = [
            entity
            for entity in entities
            if self._entity_in_domain(entity, domain_id, domain_name)
            and EntityRepository.normalize_name(entity.name) == normalized
        ]
        return matches[0] if len(matches) == 1 else None

    def _entity_in_domain(self, entity: Entity, domain_id: str | None, domain_name: str | None) -> bool:
        search_document = entity.search_document or ""
        if not domain_id and not domain_name:
            return EntityRepository._search_document_domain_key(search_document) is None
        if domain_id and f"_knowledge_domain_id：{domain_id}" in search_document:
            return True
        if domain_id and f"_knowledge_domain_id:{domain_id}" in search_document:
            return True
        if domain_name and f"_knowledge_domain_name：{domain_name}" in search_document:
            return True
        if domain_name and f"_knowledge_domain_name:{domain_name}" in search_document:
            return True
        return False
