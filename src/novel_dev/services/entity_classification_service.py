from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(slots=True)
class EntityClassificationResult:
    system_category: str
    system_group_slug: Optional[str]
    classification_reason: dict[str, Any]
    classification_confidence: float
    system_needs_review: bool
    classification_status: str


class EntityClassificationService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def classify(
        self,
        novel_id: Optional[str],
        entity_name: str,
        latest_state: dict,
        relationships: list,
    ) -> EntityClassificationResult:
        text_parts = [entity_name, str(latest_state or {})]
        for rel in relationships or []:
            if isinstance(rel, dict):
                text_parts.append(str(rel.get("relation_type", "")))
                meta = rel.get("meta")
            else:
                text_parts.append(str(getattr(rel, "relation_type", "")))
                meta = getattr(rel, "meta", None)
            if meta:
                text_parts.append(str(meta))
        text = "".join(text_parts)

        system_category = "其他"
        system_group_slug = "other"
        classification_reason: dict[str, Any] = {"reason": "fallback"}
        confidence = 0.2
        needs_review = True

        if any(keyword in text for keyword in ("宗门", "门派", "圣地", "世家")):
            system_category = "势力"
            system_group_slug = "factions"
            classification_reason = {"reason": "keyword_match", "keywords": ["宗门", "门派", "圣地", "世家"]}
            confidence = 0.9
            needs_review = False
        elif any(keyword in text for keyword in ("功法", "心法", "神通")):
            system_category = "功法"
            system_group_slug = "skills"
            classification_reason = {"reason": "keyword_match", "keywords": ["功法", "心法", "神通"]}
            confidence = 0.9
            needs_review = False

        status = "needs_review" if needs_review else "auto"

        return EntityClassificationResult(
            system_category=system_category,
            system_group_slug=system_group_slug,
            classification_reason=classification_reason,
            classification_confidence=confidence,
            system_needs_review=needs_review,
            classification_status=status,
        )
