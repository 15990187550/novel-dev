import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.agents.entity_classifier import EntityClassifierAgent

logger = logging.getLogger(__name__)

AUTO_CONFIDENCE_THRESHOLD = 0.72

SKILL_KEYWORDS = (
    "功法", "心法", "神通", "秘术", "法门", "口诀", "法诀", "剑诀", "剑经", "经", "诀", "术", "篇", "录", "典",
    "天书", "真诀", "道法", "遁法", "身法", "剑法", "刀法", "拳法", "掌法", "指法", "炼体", "吐纳",
)
TREASURE_KEYWORDS = (
    "剑", "刀", "枪", "戟", "斧", "塔", "钟", "鼎", "印", "镜", "珠", "佩", "图", "旗", "棺", "轮",
    "炉", "令", "幡", "伞", "甲", "冠", "盾", "碑", "盘", "梭", "舟", "宫", "殿", "宫灯", "舍利",
    "铃", "环", "镯", "钗", "瓶", "葫芦", "棒", "杖", "法宝", "神兵", "灵宝", "至宝", "仙器", "魔器",
)
MATERIAL_KEYWORDS = (
    "丹", "药", "液", "髓", "果", "草", "花", "叶", "血", "骨", "晶", "石", "玉髓", "灵乳", "矿", "砂",
    "芝", "参", "莲", "根", "露", "泉", "精", "铁", "金", "铜", "木", "火种", "灵材", "仙材",
)
FACTION_KEYWORDS = (
    "宗门", "门派", "圣地", "世家", "皇朝", "王朝", "帝国", "国", "教", "寺", "观", "宫", "阁", "殿",
    "盟", "会", "帮", "派", "门", "宗", "族", "家", "府", "寨", "谷",
)
LOCATION_KEYWORDS = (
    "地点", "地域", "区域", "山", "峰", "谷", "洞", "城", "镇", "村", "河", "江", "海", "湖", "林", "原",
    "荒", "境", "界", "天", "地", "禁地", "洞府", "仙府", "山门", "秘境", "遗迹", "战场", "陵", "墓",
)
EVENT_KEYWORDS = ("事件", "大战", "战役", "变故", "劫难", "动乱", "试炼", "仪式", "约定", "计划")
CONCEPT_KEYWORDS = ("规则", "体系", "设定", "概念", "境界", "因果", "轮回", "气运", "命格", "法则", "权柄")


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
        *,
        use_llm: bool = True,
    ) -> EntityClassificationResult:
        rule_result = self._classify_by_rules(
            entity_type=entity_type,
            entity_name=entity_name,
            latest_state=latest_state,
            relationships=relationships,
        )
        if not use_llm:
            return rule_result
        llm_result = await self._classify_with_model(
            novel_id=novel_id,
            entity_type=entity_type,
            entity_name=entity_name,
            latest_state=latest_state,
            relationships=relationships,
        )
        if llm_result is None:
            return rule_result

        return self._result_from_llm(llm_result, rule_result, reason="llm_classification")

    async def classify_batch(
        self,
        novel_id: Optional[str],
        entities: list[dict[str, Any]],
    ) -> list[EntityClassificationResult]:
        rule_results = [
            self._classify_by_rules(
                entity_type=str(entity.get("entity_type") or "other"),
                entity_name=str(entity.get("entity_name") or ""),
                latest_state=entity.get("latest_state") or {},
                relationships=entity.get("relationships") or [],
            )
            for entity in entities
        ]
        if not entities:
            return []

        try:
            llm_result = await self.classifier_agent.classify_batch(
                entities=[
                    {
                        **entity,
                        "local_category": rule_results[index].system_category,
                        "local_group_name": rule_results[index].system_group_name,
                    }
                    for index, entity in enumerate(entities)
                ],
                novel_id=novel_id or "",
            )
        except Exception as exc:
            logger.warning(
                "entity_classification_batch_llm_failed",
                extra={"novel_id": novel_id, "entity_count": len(entities), "error": str(exc)},
            )
            return rule_results

        by_index = {item.index: item for item in llm_result.items}
        results: list[EntityClassificationResult] = []
        for index, rule_result in enumerate(rule_results):
            item = by_index.get(index)
            if item is None:
                results.append(rule_result)
                continue
            results.append(
                self._result_from_llm(
                    item,
                    rule_result,
                    reason="llm_batch_classification",
                )
            )
        return results

    def _result_from_llm(
        self,
        llm_result,
        rule_result: EntityClassificationResult,
        *,
        reason: str,
    ) -> EntityClassificationResult:
        confidence = max(0.0, min(float(llm_result.confidence), 1.0))
        needs_review = confidence < AUTO_CONFIDENCE_THRESHOLD or llm_result.category == "其他"
        group_name = self._normalize_group_name(llm_result.group_name, llm_result.category)
        return EntityClassificationResult(
            system_category=llm_result.category,
            system_group_slug=self._slugify(group_name) if group_name and not needs_review else ("other" if llm_result.category == "其他" else None),
            system_group_name=group_name,
            classification_reason={
                "reason": reason,
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
            group_name = self._infer_faction_group(entity_name, text)
            return self._result(
                category="势力",
                group_name=group_name,
                confidence=0.9,
                reason={"reason": "entity_type_match", "entity_type": normalized_type},
                needs_review=False,
            )

        if normalized_type == "location":
            return self._result(
                category="其他",
                group_name=self._infer_other_group(entity_name, text),
                confidence=0.9,
                reason={"reason": "entity_type_match", "entity_type": normalized_type},
                needs_review=False,
            )

        if normalized_type == "item":
            if self._contains_any(text, SKILL_KEYWORDS):
                return self._result(
                    category="功法",
                    group_name=self._infer_skill_group(entity_name, text),
                    confidence=0.88,
                    reason={"reason": "entity_type_item_keyword_match", "keywords": self._matched_keywords(text, SKILL_KEYWORDS)},
                    needs_review=False,
                )
            if self._contains_any(text, MATERIAL_KEYWORDS):
                return self._result(
                    category="天材地宝",
                    group_name=self._infer_material_group(entity_name, text),
                    confidence=0.84,
                    reason={"reason": "entity_type_item_keyword_match", "keywords": self._matched_keywords(text, MATERIAL_KEYWORDS)},
                    needs_review=False,
                )
            if self._contains_any(text, TREASURE_KEYWORDS):
                return self._result(
                    category="法宝神兵",
                    group_name=self._infer_treasure_group(entity_name, text),
                    confidence=0.84,
                    reason={"reason": "entity_type_item_keyword_match", "keywords": self._matched_keywords(text, TREASURE_KEYWORDS)},
                    needs_review=False,
                )

        if any(keyword in text for keyword in FACTION_KEYWORDS):
            return self._result(
                category="势力",
                group_name=self._infer_faction_group(entity_name, text),
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
                group_name=self._infer_material_group(entity_name, text),
                confidence=0.8,
                reason={"reason": "keyword_match", "keywords": self._matched_keywords(text, MATERIAL_KEYWORDS)},
                needs_review=False,
            )

        if self._contains_any(text, LOCATION_KEYWORDS + EVENT_KEYWORDS + CONCEPT_KEYWORDS):
            return self._result(
                category="其他",
                group_name=self._infer_other_group(entity_name, text),
                confidence=0.76,
                reason={
                    "reason": "keyword_match",
                    "keywords": self._matched_keywords(text, LOCATION_KEYWORDS + EVENT_KEYWORDS + CONCEPT_KEYWORDS),
                },
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
        if any(keyword in text for keyword in ("反派", "宿敌", "魔头", "敌对", "仇敌", "追杀")):
            return "反派"
        if any(keyword in text for keyword in ("师父", "师尊", "师兄", "师姐", "师弟", "师妹", "同门", "门下", "弟子")):
            return "师门"
        if any(keyword in text for keyword in ("父亲", "母亲", "兄长", "妹妹", "姐姐", "家族", "血亲", "族人")):
            return "家族"
        if any(keyword in text for keyword in ("盟友", "伙伴", "朋友", "同伴", "相助", "同行")):
            return "盟友"
        if any(keyword in text for keyword in ("佛祖", "至尊", "大帝", "真仙", "古皇", "天尊")):
            return "上古强者"
        return "核心人物"

    @staticmethod
    def _infer_skill_group(entity_name: str, text: str) -> str:
        if any(keyword in text for keyword in ("禁术", "禁法", "邪术", "血祭", "献祭", "燃烧寿元", "燃血")):
            return "禁术"
        if any(keyword in text for keyword in ("主修", "根本", "本命功法", "核心功法")):
            return "主修"
        if any(keyword in text for keyword in ("辅修", "辅助", "身法", "遁法", "御剑", "步法")):
            return "辅修"
        if any(keyword in text for keyword in ("剑诀", "剑道", "剑经")):
            return "剑道传承"
        if any(keyword in text for keyword in ("炼体", "肉身")):
            return "炼体"
        if any(keyword in text for keyword in ("经", "传承", "古经")):
            return "传承"
        return "核心功法"

    @staticmethod
    def _infer_treasure_group(entity_name: str, text: str) -> str:
        if any(keyword in text for keyword in ("本命", "性命交修", "伴生")):
            return "本命"
        if any(keyword in text for keyword in ("传承", "镇派", "镇宗", "祖传")):
            return "传承"
        if any(keyword in text for keyword in ("敌对", "反派", "魔道", "敌人")):
            return "敌对"
        if any(keyword in text for keyword in ("随身", "常用", "佩戴", "日常")):
            return "常用"
        if "镜" in entity_name or "镜" in text:
            return "镜类法宝"
        if any(keyword in entity_name for keyword in ("剑", "刀", "枪", "戟", "斧")):
            return "攻伐兵刃"
        if any(keyword in text for keyword in ("护身", "防御", "护体")):
            return "护身法宝"
        if any(keyword in text for keyword in ("轮回", "传送", "空间")):
            return "空间法宝"
        return "特殊法宝"

    @staticmethod
    def _infer_faction_group(entity_name: str, text: str) -> str:
        if any(keyword in text for keyword in ("敌对", "反派", "仇敌", "追杀", "魔教", "邪教", "魔道")):
            return "敌对势力"
        if any(keyword in text for keyword in ("皇朝", "王朝", "帝国", "朝廷", "官府", "王府")):
            return "朝廷"
        if any(keyword in text for keyword in ("世家", "家族", "氏族", "族", "家")):
            return "世家"
        if any(keyword in text for keyword in ("妖族", "魔族", "鬼族", "异族", "兽族")):
            return "异族"
        if any(keyword in text for keyword in ("盟", "会", "帮", "商会", "组织", "楼", "阁")):
            return "组织"
        if any(keyword in text for keyword in ("宗", "门", "派", "圣地", "教", "寺", "观", "宫", "殿", "谷")):
            return "宗门"
        return "组织"

    @staticmethod
    def _infer_material_group(entity_name: str, text: str) -> str:
        if any(keyword in text for keyword in ("疗伤", "续命", "解毒", "回春", "复元")):
            return "疗伤"
        if any(keyword in text for keyword in ("突破", "筑基", "结丹", "元婴", "破境", "晋升")):
            return "突破"
        if any(keyword in text for keyword in ("炼器", "矿", "砂", "铁", "金", "铜", "晶", "石")):
            return "炼器"
        if any(keyword in text for keyword in ("炼丹", "丹", "药", "草", "花", "叶", "根", "芝", "参")):
            return "炼丹"
        return "修炼"

    @staticmethod
    def _infer_other_group(entity_name: str, text: str) -> str:
        if any(keyword in text for keyword in LOCATION_KEYWORDS):
            return "地点"
        if any(keyword in text for keyword in EVENT_KEYWORDS):
            return "事件"
        if any(keyword in text for keyword in CONCEPT_KEYWORDS):
            return "世界规则"
        return "概念"
