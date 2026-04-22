import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.agents.entity_classifier import EntityClassifierAgent

logger = logging.getLogger(__name__)

AUTO_CONFIDENCE_THRESHOLD = 0.72

SKILL_KEYWORDS = (
    "功法", "心法", "神通", "秘术", "法门", "口诀", "法诀", "剑诀", "经", "诀", "术", "篇", "录", "典",
)
TREASURE_KEYWORDS = (
    "剑", "刀", "枪", "戟", "斧", "塔", "钟", "鼎", "印", "镜", "珠", "佩", "图", "旗", "棺", "轮",
    "炉", "令", "幡", "伞", "甲", "冠", "盾", "碑", "盘", "梭", "舟", "宫", "殿", "宫灯", "舍利",
)
MATERIAL_KEYWORDS = (
    "丹", "药", "液", "髓", "果", "草", "花", "叶", "血", "骨", "晶", "石", "玉髓", "灵乳", "矿", "砂",
)
FACTION_KEYWORDS = ("宗门", "门派", "圣地", "世家", "皇朝", "王朝", "教", "阁", "殿", "盟", "会")


@dataclass(slots=True)
class EntityClassificationResult:
    system_category: str
    system_group_slug: Optional[str]
    system_group_name: Optional[str]
    classification_reason: dict[str, Any]
    classification_confidence: float
    system_needs_review: bool
    classification_status: str


class EntityClassificationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.classifier_agent = EntityClassifierAgent()

    async def classify(
        self,
        novel_id: Optional[str],
        entity_type: str,
        entity_name: str,
        latest_state: dict,
        relationships: list,
    ) -> EntityClassificationResult:
        rule_result = self._classify_by_rules(
            entity_type=entity_type,
            entity_name=entity_name,
            latest_state=latest_state,
            relationships=relationships,
        )
        llm_result = await self._classify_with_model(
            novel_id=novel_id,
            entity_type=entity_type,
            entity_name=entity_name,
            latest_state=latest_state,
            relationships=relationships,
        )
        if llm_result is None:
            return rule_result

        confidence = max(0.0, min(float(llm_result.confidence), 1.0))
        needs_review = confidence < AUTO_CONFIDENCE_THRESHOLD or llm_result.category == "其他"
        group_name = self._normalize_group_name(llm_result.group_name, llm_result.category)
        return EntityClassificationResult(
            system_category=llm_result.category,
            system_group_slug=self._slugify(group_name) if group_name and not needs_review else ("other" if llm_result.category == "其他" else None),
            system_group_name=group_name,
            classification_reason={
                "reason": "llm_classification",
                "llm_reason": llm_result.reason,
                "fallback_category": rule_result.system_category,
                "fallback_group_name": rule_result.system_group_name,
            },
            classification_confidence=confidence,
            system_needs_review=needs_review,
            classification_status="needs_review" if needs_review else "auto",
        )

    async def _classify_with_model(
        self,
        *,
        novel_id: Optional[str],
        entity_type: str,
        entity_name: str,
        latest_state: dict,
        relationships: list,
    ):
        try:
            return await self.classifier_agent.classify(
                entity_type=entity_type,
                entity_name=entity_name,
                latest_state=latest_state,
                relationships=relationships,
                novel_id=novel_id or "",
            )
        except Exception as exc:
            logger.warning(
                "entity_classification_llm_failed",
                extra={"entity_name": entity_name, "entity_type": entity_type, "error": str(exc)},
            )
            return None

    def _classify_by_rules(
        self,
        *,
        entity_type: str,
        entity_name: str,
        latest_state: dict,
        relationships: list,
    ) -> EntityClassificationResult:
        text = self._build_text(entity_name, latest_state, relationships)
        normalized_type = (entity_type or "other").strip().lower()

        if normalized_type == "character":
            group_name = self._infer_character_group(entity_name, text)
            return self._result(
                category="人物",
                group_name=group_name,
                confidence=0.9,
                reason={"reason": "entity_type_match", "entity_type": normalized_type},
                needs_review=False,
            )

        if normalized_type == "faction":
            group_name = "宗门势力" if any(keyword in text for keyword in FACTION_KEYWORDS) else "势力格局"
            return self._result(
                category="势力",
                group_name=group_name,
                confidence=0.9,
                reason={"reason": "entity_type_match", "entity_type": normalized_type},
                needs_review=False,
            )

        if any(keyword in text for keyword in FACTION_KEYWORDS):
            return self._result(
                category="势力",
                group_name="宗门势力",
                confidence=0.88,
                reason={"reason": "keyword_match", "keywords": list(FACTION_KEYWORDS)},
                needs_review=False,
            )

        if self._contains_any(text, SKILL_KEYWORDS):
            return self._result(
                category="功法",
                group_name=self._infer_skill_group(entity_name, text),
                confidence=0.86,
                reason={"reason": "keyword_match", "keywords": self._matched_keywords(text, SKILL_KEYWORDS)},
                needs_review=False,
            )

        if self._contains_any(text, TREASURE_KEYWORDS):
            return self._result(
                category="法宝神兵",
                group_name=self._infer_treasure_group(entity_name, text),
                confidence=0.84,
                reason={"reason": "keyword_match", "keywords": self._matched_keywords(text, TREASURE_KEYWORDS)},
                needs_review=False,
            )

        if self._contains_any(text, MATERIAL_KEYWORDS):
            return self._result(
                category="天材地宝",
                group_name="稀有材料",
                confidence=0.8,
                reason={"reason": "keyword_match", "keywords": self._matched_keywords(text, MATERIAL_KEYWORDS)},
                needs_review=False,
            )

        return self._result(
            category="其他",
            group_name="",
            confidence=0.2,
            reason={"reason": "fallback"},
            needs_review=True,
        )

    @staticmethod
    def _build_text(entity_name: str, latest_state: dict, relationships: list) -> str:
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
        return "".join(text_parts)

    @staticmethod
    def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _matched_keywords(text: str, keywords: tuple[str, ...]) -> list[str]:
        return [keyword for keyword in keywords if keyword in text][:6]

    @staticmethod
    def _normalize_group_name(group_name: str, category: str) -> Optional[str]:
        normalized = (group_name or "").strip()
        if not normalized:
            return None
        if normalized in {"未分组", "其他", "默认分组", "通用", category}:
            return None
        return normalized[:40]

    @staticmethod
    def _slugify(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        normalized = re.sub(r"\s+", "-", value.strip().lower())
        normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff-]", "", normalized)
        normalized = normalized.strip("-")
        return normalized or None

    @classmethod
    def _result(
        cls,
        *,
        category: str,
        group_name: str,
        confidence: float,
        reason: dict[str, Any],
        needs_review: bool,
    ) -> EntityClassificationResult:
        normalized_group = cls._normalize_group_name(group_name, category)
        return EntityClassificationResult(
            system_category=category,
            system_group_slug=cls._slugify(normalized_group) if normalized_group and not needs_review else ("other" if category == "其他" else None),
            system_group_name=normalized_group,
            classification_reason=reason,
            classification_confidence=confidence,
            system_needs_review=needs_review,
            classification_status="needs_review" if needs_review else "auto",
        )

    @staticmethod
    def _infer_character_group(entity_name: str, text: str) -> str:
        if any(keyword in text for keyword in ("主角", "男主", "女主", "天命之子")):
            return "主角阵营"
        if any(keyword in text for keyword in ("反派", "宿敌", "魔头", "敌对")):
            return "反派阵营"
        if any(keyword in text for keyword in ("佛祖", "至尊", "大帝", "真仙", "古皇", "天尊")):
            return "上古强者"
        return "核心人物"

    @staticmethod
    def _infer_skill_group(entity_name: str, text: str) -> str:
        if any(keyword in text for keyword in ("剑诀", "剑道", "剑经")):
            return "剑道传承"
        if any(keyword in text for keyword in ("炼体", "肉身")):
            return "炼体"
        if any(keyword in text for keyword in ("经", "传承", "古经")):
            return "传承"
        return "核心功法"

    @staticmethod
    def _infer_treasure_group(entity_name: str, text: str) -> str:
        if "镜" in entity_name or "镜" in text:
            return "镜类法宝"
        if any(keyword in entity_name for keyword in ("剑", "刀", "枪", "戟", "斧")):
            return "攻伐兵刃"
        if any(keyword in text for keyword in ("护身", "防御", "护体")):
            return "护身法宝"
        if any(keyword in text for keyword in ("轮回", "传送", "空间")):
            return "空间法宝"
        return "特殊法宝"
