import math
import re
from datetime import datetime
from typing import Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_, select, text

from novel_dev.db.models import Entity, EntityGroup, EntityRelationship
from novel_dev.schemas.similar_document import SimilarDocument

ROLE_PREFIXES = (
    "主角", "男主", "女主", "反派", "配角", "角色",
    "主要角色", "次要角色", "反派角色",
)
ALIAS_SEPARATORS_PATTERN = r"[/／|｜、;；]+"
BRACKET_CONTENT_PATTERN = r"（(.*?)）|\((.*?)\)|【(.*?)】|\[(.*?)\]"
TYPE_TO_CATEGORY = {
    "character": "人物",
    "faction": "势力",
    "location": "地点",
}
PERSON_RELATION_GROUPS = (
    (
        ("妻子", "妻", "丈夫", "夫君", "道侣", "配偶", "伴侣", "老婆", "夫人", "爱人", "恋人"),
        ("妻子", "丈夫", "夫君", "道侣", "配偶", "伴侣", "老婆", "夫人", "爱人", "恋人"),
    ),
    (
        ("红颜", "红颜知己", "蓝颜", "情人", "情感羁绊"),
        ("红颜", "红颜知己", "蓝颜", "情人", "情感羁绊"),
    ),
    (
        ("父母", "父亲", "母亲", "父", "母", "爹", "娘", "义父", "义母", "养父", "养母", "生父", "生母"),
        ("父亲", "母亲", "爹", "娘", "义父", "义母", "养父", "养母", "生父", "生母"),
    ),
    (
        ("儿子", "女儿", "子女", "儿女", "孩子", "后代", "子嗣"),
        ("儿子", "女儿", "子女", "儿女", "孩子", "后代", "子嗣", "长子", "次子", "幼子", "长女", "次女"),
    ),
    (
        ("兄弟", "姐妹", "兄妹", "姐弟", "哥哥", "弟弟", "姐姐", "妹妹", "结拜兄弟", "义兄", "义弟"),
        ("兄弟", "姐妹", "兄妹", "姐弟", "哥哥", "弟弟", "姐姐", "妹妹", "大哥", "二哥", "三弟", "二弟", "结拜", "义兄", "义弟"),
    ),
    (
        ("师父", "师傅", "师尊", "师门", "师承", "师徒", "老师", "恩师", "授业者", "传道人"),
        ("师父", "师傅", "师尊", "师门", "师承", "老师", "恩师", "授业", "传道人", "启蒙师父"),
    ),
    (
        ("徒弟", "弟子", "门人", "传人", "学生", "门徒", "继承人"),
        ("徒弟", "弟子", "门人", "传人", "学生", "门徒", "继承人"),
    ),
    (
        ("师兄", "师弟", "师姐", "师妹", "师兄弟", "师姐妹", "同门", "同宗", "同派"),
        ("师兄", "师弟", "师姐", "师妹", "师兄弟", "师姐妹", "同门", "同宗", "同派"),
    ),
    (
        ("朋友", "好友", "挚友", "盟友", "同伴", "伙伴", "战友", "队友"),
        ("朋友", "好友", "挚友", "盟友", "同伴", "伙伴", "战友", "队友"),
    ),
    (
        ("恩人", "救命恩人", "贵人", "支持者", "庇护者", "引路人"),
        ("恩人", "救命恩人", "贵人", "支持者", "庇护者", "引路人"),
    ),
    (
        ("敌人", "仇人", "宿敌", "对手", "死敌", "敌对者", "仇敌", "劲敌"),
        ("敌人", "仇人", "宿敌", "对手", "死敌", "敌对", "仇敌", "劲敌"),
    ),
    (
        ("手下", "下属", "部下", "属下", "麾下", "随从", "仆人", "侍从"),
        ("手下", "下属", "部下", "属下", "麾下", "随从", "仆人", "侍从"),
    ),
    (
        ("上级", "主人", "主上", "宗主", "掌门", "族长", "首领", "领袖"),
        ("上级", "主人", "主上", "宗主", "掌门", "族长", "首领", "领袖"),
    ),
    (
        ("岳父", "岳母", "女婿", "儿媳", "婆婆", "公公", "亲家"),
        ("岳父", "岳母", "女婿", "儿媳", "婆婆", "公公", "亲家"),
    ),
)
PERSON_RELATION_QUERY_KEYWORDS = tuple(
    keyword
    for query_keywords, _ in PERSON_RELATION_GROUPS
    for keyword in query_keywords
)
CATEGORY_QUERY_KEYWORDS = (
    ("功法", ("功法", "道术", "神通", "秘术", "所修", "修炼", "传承")),
    ("法宝神兵", ("法宝", "神兵", "兵器", "武器")),
    ("天材地宝", ("天材地宝", "灵物", "丹药", "宝药", "资源")),
    ("势力", ("势力", "组织", "宗门", "门派", "王朝", "阵营")),
    ("人物", ("人物", "角色", "道友", *PERSON_RELATION_QUERY_KEYWORDS)),
    ("地点", ("地点", "地方", "城市", "遗迹", "地域")),
)
STRICT_RELATION_QUERY_KEYWORDS = (
    "所修",
    "修的",
    "修炼的",
    *PERSON_RELATION_QUERY_KEYWORDS,
)
GRAPH_RELATION_QUERY_GROUPS = (
    (
        ("妻子", "妻", "丈夫", "夫君", "道侣", "配偶", "伴侣", "老婆", "夫人", "爱人", "恋人"),
        ("妻子", "妻", "丈夫", "夫君", "道侣", "配偶", "伴侣", "老婆", "夫人", "爱人", "恋人", "spouse", "partner"),
    ),
    (
        ("红颜", "红颜知己", "蓝颜", "情人", "情感羁绊"),
        ("红颜", "红颜知己", "蓝颜", "情人", "情感羁绊"),
    ),
    (
        ("父母", "父亲", "母亲", "父", "母", "爹", "娘", "义父", "义母", "养父", "养母", "生父", "生母"),
        ("父母", "父亲", "母亲", "父", "母", "爹", "娘", "义父", "义母", "养父", "养母", "生父", "生母", "parent", "father", "mother"),
    ),
    (
        ("儿子", "女儿", "子女", "儿女", "孩子", "后代", "子嗣"),
        ("儿子", "女儿", "子女", "儿女", "孩子", "后代", "子嗣", "长子", "次子", "幼子", "长女", "次女", "child", "son", "daughter"),
    ),
    (
        ("兄弟", "姐妹", "兄妹", "姐弟", "哥哥", "弟弟", "姐姐", "妹妹", "结拜兄弟", "义兄", "义弟"),
        ("兄弟", "姐妹", "兄妹", "姐弟", "哥哥", "弟弟", "姐姐", "妹妹", "大哥", "二哥", "三弟", "二弟", "结拜", "义兄", "义弟", "sibling", "brother", "sister"),
    ),
    (
        ("师父", "师傅", "师尊", "师门", "师承", "师徒", "老师", "恩师", "授业者", "传道人"),
        ("师父", "师傅", "师尊", "师门", "师承", "老师", "恩师", "授业", "传道人", "启蒙师父", "mentor", "master", "teacher"),
    ),
    (
        ("徒弟", "弟子", "门人", "传人", "学生", "门徒", "继承人"),
        ("徒弟", "弟子", "门人", "传人", "学生", "门徒", "继承人", "disciple", "student", "successor"),
    ),
    (
        ("师兄", "师弟", "师姐", "师妹", "师兄弟", "师姐妹", "同门", "同宗", "同派"),
        ("师兄", "师弟", "师姐", "师妹", "师兄弟", "师姐妹", "同门", "同宗", "同派"),
    ),
    (
        ("朋友", "好友", "挚友", "盟友", "同伴", "伙伴", "战友", "队友"),
        ("朋友", "好友", "挚友", "盟友", "同伴", "伙伴", "战友", "队友", "ally", "friend", "companion"),
    ),
    (
        ("恩人", "救命恩人", "贵人", "支持者", "庇护者", "引路人"),
        ("恩人", "救命恩人", "贵人", "支持者", "庇护者", "引路人"),
    ),
    (
        ("敌人", "仇人", "宿敌", "对手", "死敌", "敌对者", "仇敌", "劲敌"),
        ("敌人", "仇人", "宿敌", "对手", "死敌", "敌对", "仇敌", "劲敌", "enemy", "rival"),
    ),
    (
        ("手下", "下属", "部下", "属下", "麾下", "随从", "仆人", "侍从"),
        ("手下", "下属", "部下", "属下", "麾下", "随从", "仆人", "侍从", "subordinate", "follower"),
    ),
    (
        ("上级", "主人", "主上", "宗主", "掌门", "族长", "首领", "领袖"),
        ("上级", "主人", "主上", "宗主", "掌门", "族长", "首领", "领袖", "leader", "master"),
    ),
    (
        ("功法", "道术", "神通", "秘术", "所修", "修的", "修炼", "传承"),
        ("功法", "道术", "神通", "秘术", "所修", "修炼", "修行", "传承", "主修", "cultivation"),
    ),
    (
        ("法宝", "神兵", "兵器", "武器"),
        ("法宝", "神兵", "兵器", "武器", "持有", "拥有", "weapon", "artifact"),
    ),
)
_UNSET = object()


class EntityRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, entity_id: str, entity_type: str, name: str, created_at_chapter_id: Optional[str] = None, novel_id: Optional[str] = None) -> Entity:
        entity = Entity(
            id=entity_id,
            type=entity_type,
            name=name,
            created_at_chapter_id=created_at_chapter_id,
            novel_id=novel_id,
        )
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def get_by_id(self, entity_id: str) -> Optional[Entity]:
        result = await self.session.execute(select(Entity).where(Entity.id == entity_id))
        return result.scalar_one_or_none()

    async def archive_for_consolidation(
        self,
        entity_id: str,
        *,
        novel_id: str,
        batch_id: str,
        change_id: str,
        reason: str = "setting_consolidation",
    ) -> Optional[Entity]:
        result = await self.session.execute(
            select(Entity).where(
                Entity.id == entity_id,
                Entity.novel_id == novel_id,
            )
        )
        entity = result.scalar_one_or_none()
        if entity is None:
            return None
        entity.archived_at = datetime.utcnow()
        entity.archive_reason = reason
        entity.archived_by_consolidation_batch_id = batch_id
        entity.archived_by_consolidation_change_id = change_id
        await self.session.flush()
        return entity

    async def update_basic_fields(
        self,
        entity_id: str,
        *,
        name: object = _UNSET,
        entity_type: object = _UNSET,
    ) -> Entity:
        entity = await self.get_by_id(entity_id)
        if entity is None:
            raise ValueError("entity not found")

        if name is not _UNSET:
            entity.name = name
        if entity_type is not _UNSET:
            entity.type = entity_type
        await self.session.flush()
        return entity

    async def delete(self, entity_id: str) -> None:
        entity = await self.get_by_id(entity_id)
        if entity is None:
            return
        await self.session.delete(entity)
        await self.session.flush()

    async def update_classification(
        self,
        entity_id: str,
        *,
        system_category=_UNSET,
        system_group_id=_UNSET,
        manual_category=_UNSET,
        manual_group_id=_UNSET,
        classification_reason=_UNSET,
        classification_confidence=_UNSET,
        system_needs_review=_UNSET,
    ) -> Entity:
        entity = await self.get_by_id(entity_id)
        if entity is None:
            raise ValueError("entity not found")

        target_system_category = entity.system_category if system_category is _UNSET else system_category
        target_manual_category = entity.manual_category if manual_category is _UNSET else manual_category

        async def load_group(group_id: str) -> Optional[EntityGroup]:
            result = await self.session.execute(
                select(EntityGroup).where(EntityGroup.id == group_id)
            )
            return result.scalar_one_or_none()

        effective_system_group_id = entity.system_group_id if system_group_id is _UNSET else system_group_id
        if effective_system_group_id is not None:
            system_group = await load_group(effective_system_group_id)
            if (
                system_group is None
                or system_group.category != target_system_category
                or (
                    entity.novel_id is not None
                    and system_group.novel_id != entity.novel_id
                )
            ):
                if system_group_id is _UNSET:
                    effective_system_group_id = None
                else:
                    raise ValueError("system_group must belong to system_category")

        effective_manual_group_id = entity.manual_group_id if manual_group_id is _UNSET else manual_group_id
        if effective_manual_group_id is not None:
            manual_group = await load_group(effective_manual_group_id)
            if (
                manual_group is None
                or manual_group.category != target_manual_category
                or (
                    entity.novel_id is not None
                    and manual_group.novel_id != entity.novel_id
                )
            ):
                if manual_group_id is _UNSET:
                    effective_manual_group_id = None
                else:
                    raise ValueError("manual_group must belong to manual_category")

        if system_category is not _UNSET:
            entity.system_category = system_category
        entity.system_group_id = effective_system_group_id
        if manual_category is not _UNSET:
            entity.manual_category = manual_category
        entity.manual_group_id = effective_manual_group_id
        if classification_reason is not _UNSET:
            entity.classification_reason = classification_reason
        if classification_confidence is not _UNSET:
            entity.classification_confidence = classification_confidence
        if system_needs_review is not _UNSET:
            entity.system_needs_review = system_needs_review

        await self.session.flush()
        return entity

    @staticmethod
    def _normalize_name_text(name: str) -> str:
        normalized = (name or "").strip()
        normalized = re.sub(r"（.*?）|\(.*?\)|【.*?】|\[.*?\]", "", normalized)
        normalized = re.sub(r"[\s·•,，。:：/\\_\-—]+", "", normalized)
        for prefix in ROLE_PREFIXES:
            if normalized.startswith(prefix) and len(normalized) - len(prefix) >= 2:
                normalized = normalized[len(prefix):]
                break
        return normalized

    @classmethod
    def normalize_name(cls, name: str) -> str:
        return cls._normalize_name_text(name)

    @classmethod
    def name_variants(cls, name: str) -> set[str]:
        raw = (name or "").strip()
        if not raw:
            return set()

        candidates = {raw}
        for match in re.finditer(BRACKET_CONTENT_PATTERN, raw):
            candidates.update(part for part in match.groups() if part)
        candidates.update(part for part in re.split(ALIAS_SEPARATORS_PATTERN, raw) if part)

        variants = {
            cls._normalize_name_text(candidate)
            for candidate in candidates
            if cls._normalize_name_text(candidate)
        }
        return variants

    @classmethod
    def _is_close_name_match(cls, candidate: str, target: str) -> bool:
        if not candidate or not target:
            return False
        if candidate == target:
            return True
        shorter, longer = sorted((candidate, target), key=len)
        return len(shorter) >= 2 and shorter in longer and len(longer) - len(shorter) <= 2

    async def find_by_name(self, name: str, entity_type: Optional[str] = None, novel_id: Optional[str] = None) -> Optional[Entity]:
        stmt = select(Entity).where(Entity.name == name)
        if entity_type is not None:
            stmt = stmt.where(Entity.type == entity_type)
        if novel_id is not None:
            stmt = stmt.where(Entity.novel_id == novel_id)
        result = await self.session.execute(stmt)
        exact_matches = list(result.scalars().all())
        if len(exact_matches) == 1:
            return exact_matches[0]
        if len(exact_matches) > 1:
            return None

        target_variants = self.name_variants(name)
        if not target_variants:
            return None

        stmt = select(Entity)
        if entity_type is not None:
            stmt = stmt.where(Entity.type == entity_type)
        if novel_id is not None:
            stmt = stmt.where(Entity.novel_id == novel_id)
        result = await self.session.execute(stmt)
        candidates = result.scalars().all()

        normalized_matches = [
            entity for entity in candidates
            if self.name_variants(entity.name) & target_variants
        ]
        if len(normalized_matches) == 1:
            return normalized_matches[0]

        close_matches = [
            entity for entity in candidates
            if any(
                self._is_close_name_match(candidate_variant, target_variant)
                for candidate_variant in self.name_variants(entity.name)
                for target_variant in target_variants
            )
        ]
        if len(close_matches) == 1:
            return close_matches[0]
        return None

    async def update_version(self, entity_id: str, new_version: int) -> None:
        entity = await self.get_by_id(entity_id)
        if entity:
            entity.current_version = new_version
            await self.session.flush()

    async def find_by_names(self, names: List[str], novel_id: Optional[str] = None) -> List[Entity]:
        if not names:
            return []
        stmt = select(Entity).where(Entity.name.in_(names))
        if novel_id is not None:
            stmt = stmt.where(Entity.novel_id == novel_id)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_by_novel(self, novel_id: str) -> List[Entity]:
        result = await self.session.execute(
            select(Entity).where(Entity.novel_id == novel_id)
        )
        return result.scalars().all()

    async def search_entities(
        self,
        novel_id: str,
        *,
        query: str,
        query_vector: Optional[List[float]],
        limit: int = 20,
        include_archived: bool = False,
    ) -> list[dict]:
        query = (query or "").strip()
        if not query:
            return []

        normalized_query = self.normalize_name(query)
        query_lower = query.lower()

        filters = [Entity.novel_id == novel_id]
        if not include_archived:
            filters.append(Entity.archived_at.is_(None))
        result = await self.session.execute(select(Entity).where(*filters))
        entities = result.scalars().all()

        graph_hits = await self._relationship_graph_query_hits(
            novel_id,
            entities,
            query,
            include_archived=include_archived,
        )
        if graph_hits:
            return graph_hits[:limit]

        relationship_hits = self._relationship_query_hits(entities, query)
        if relationship_hits:
            return relationship_hits[:limit]
        if self._is_strict_relationship_query(query):
            return []

        scored: list[tuple[float, dict]] = []
        for entity in entities:
            name = entity.name or ""
            search_document = entity.search_document or ""
            lexical_hit = False
            relationship_hit = False
            semantic_score = 0.0

            if query:
                normalized_name = self.normalize_name(name)
                lexical_hit = (
                    query_lower in name.lower()
                    or (normalized_query and normalized_query == normalized_name)
                    or (normalized_query and normalized_query in normalized_name)
                )
                relationship_hit = not lexical_hit and query_lower in search_document.lower()

            if self._has_vector(query_vector) and self._has_vector(entity.search_vector_embedding):
                semantic_score = self._cosine_similarity(query_vector, entity.search_vector_embedding)

            score = semantic_score
            match_reason = "语义相关"
            if relationship_hit:
                score += 0.4
                match_reason = "关系命中"
            if lexical_hit:
                score += 1.0
                match_reason = "名称命中"
            elif semantic_score <= 0 and relationship_hit:
                match_reason = "关系命中"

            if score <= 0 and not lexical_hit and not relationship_hit:
                continue

            scored.append((
                score,
                {
                    "entity_id": entity.id,
                    "type": entity.type,
                    "name": entity.name,
                    "system_category": entity.system_category,
                    "manual_category": entity.manual_category,
                    "system_group_id": entity.system_group_id,
                    "manual_group_id": entity.manual_group_id,
                    "search_document": entity.search_document,
                    "score": float(score),
                    "match_reason": match_reason,
                },
            ))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def _relationship_query_hits(self, entities: list[Entity], query: str) -> list[dict]:
        target_categories = self._target_categories_from_query(query)
        if not target_categories:
            return []
        person_relation_terms = self._person_relation_document_terms_from_query(query)

        subjects = [
            entity
            for entity in entities
            if entity.name and len(entity.name.strip()) >= 2 and entity.name in query
        ]
        if not subjects:
            return []

        hits: list[tuple[float, dict]] = []
        seen: set[str] = set()
        subjects.sort(key=lambda entity: len(entity.name or ""), reverse=True)
        for source in subjects:
            source_document = source.search_document or ""
            if not source_document:
                continue
            source_domain = self._search_document_domain_key(source_document)
            for target in entities:
                if target.id == source.id or target.id in seen:
                    continue
                if self._effective_category(target) not in target_categories:
                    continue
                target_name = target.name or ""
                if not target_name or target_name not in source_document:
                    continue
                if (
                    self._effective_category(target) == "人物"
                    and person_relation_terms
                    and not self._target_linked_by_relation(source_document, target_name, person_relation_terms)
                ):
                    continue
                if self._search_document_domain_key(target.search_document or "") != source_domain:
                    continue
                seen.add(target.id)
                hits.append((
                    2.0 + min(len(target_name), 20) / 100,
                    {
                        "entity_id": target.id,
                        "type": target.type,
                        "name": target.name,
                        "system_category": target.system_category,
                        "manual_category": target.manual_category,
                        "system_group_id": target.system_group_id,
                        "manual_group_id": target.manual_group_id,
                        "search_document": target.search_document,
                        "score": float(2.0 + min(len(target_name), 20) / 100),
                        "match_reason": "关系查询",
                    },
                ))

        hits.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in hits]

    async def _relationship_graph_query_hits(
        self,
        novel_id: str,
        entities: list[Entity],
        query: str,
        *,
        include_archived: bool = False,
    ) -> list[dict]:
        relation_aliases = self._graph_relation_aliases_from_query(query)
        target_categories = self._target_categories_from_query(query)
        if not relation_aliases and not target_categories:
            return []

        subjects = [
            entity
            for entity in entities
            if entity.name and len(entity.name.strip()) >= 2 and entity.name in query
        ]
        if not subjects:
            return []

        entity_by_id = {entity.id: entity for entity in entities}
        subject_ids = [entity.id for entity in subjects]
        filters = [
            EntityRelationship.novel_id == novel_id,
            EntityRelationship.is_active.is_(True),
            or_(
                EntityRelationship.source_id.in_(subject_ids),
                EntityRelationship.target_id.in_(subject_ids),
            ),
        ]
        if not include_archived:
            filters.append(EntityRelationship.archived_at.is_(None))
        result = await self.session.execute(
            select(EntityRelationship)
            .where(*filters)
            .order_by(EntityRelationship.id)
        )
        relationships = [
            relationship
            for relationship in result.scalars().all()
            if hasattr(relationship, "source_id") and hasattr(relationship, "target_id")
        ]
        if not relationships:
            return []

        hits: list[tuple[float, dict]] = []
        seen: set[str] = set()
        subjects.sort(key=lambda entity: len(entity.name or ""), reverse=True)
        for source in subjects:
            for relationship in relationships:
                if relationship.source_id == source.id:
                    target_id = relationship.target_id
                elif relationship.target_id == source.id:
                    target_id = relationship.source_id
                else:
                    continue

                target = entity_by_id.get(target_id)
                if target is None or target.id == source.id or target.id in seen:
                    continue
                if relation_aliases and not self._relation_type_matches(relationship.relation_type, relation_aliases):
                    continue
                if target_categories and self._effective_category(target) not in target_categories:
                    continue

                seen.add(target.id)
                score = 3.0 + min(len(target.name or ""), 20) / 100
                hits.append((
                    score,
                    {
                        "entity_id": target.id,
                        "type": target.type,
                        "name": target.name,
                        "system_category": target.system_category,
                        "manual_category": target.manual_category,
                        "system_group_id": target.system_group_id,
                        "manual_group_id": target.manual_group_id,
                        "search_document": target.search_document,
                        "score": float(score),
                        "match_reason": "关系图谱",
                    },
                ))

        hits.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in hits]

    @staticmethod
    def _graph_relation_aliases_from_query(query: str) -> set[str]:
        aliases: set[str] = set()
        for query_keywords, relation_aliases in GRAPH_RELATION_QUERY_GROUPS:
            if any(keyword in query for keyword in query_keywords):
                aliases.update(relation_aliases)
        return aliases

    @staticmethod
    def _relation_type_matches(relation_type: str, aliases: set[str]) -> bool:
        normalized_relation = re.sub(r"[\s·•,，。:：/\\_\-—]+", "", (relation_type or "").lower())
        if not normalized_relation:
            return False
        return any(
            normalized_alias in normalized_relation or normalized_relation in normalized_alias
            for alias in aliases
            for normalized_alias in [re.sub(r"[\s·•,，。:：/\\_\-—]+", "", alias.lower())]
            if normalized_alias
        )

    @staticmethod
    def _target_categories_from_query(query: str) -> set[str]:
        return {
            category
            for category, keywords in CATEGORY_QUERY_KEYWORDS
            if any(keyword in query for keyword in keywords)
        }

    @staticmethod
    def _is_strict_relationship_query(query: str) -> bool:
        return any(keyword in query for keyword in STRICT_RELATION_QUERY_KEYWORDS)

    @staticmethod
    def _person_relation_document_terms_from_query(query: str) -> set[str]:
        terms: set[str] = set()
        for query_keywords, document_terms in PERSON_RELATION_GROUPS:
            if any(keyword in query for keyword in query_keywords):
                terms.update(document_terms)
        return terms

    @staticmethod
    def _target_linked_by_relation(search_document: str, target_name: str, relation_terms: set[str]) -> bool:
        segments = re.split(r"[；;。，,\n]+", search_document or "")
        for segment in segments:
            if target_name in segment and any(term in segment for term in relation_terms):
                return True
        return False

    @staticmethod
    def _effective_category(entity: Entity) -> str:
        return entity.manual_category or entity.system_category or TYPE_TO_CATEGORY.get(entity.type, "其他")

    @staticmethod
    def _search_document_domain_key(search_document: str) -> str | None:
        for field in ("_knowledge_domain_id", "_knowledge_domain_name"):
            match = re.search(rf"{field}\s*[：:]\s*([^\n]+)", search_document or "")
            if match and match.group(1).strip():
                return f"{field}:{match.group(1).strip()}"
        return None

    @staticmethod
    def _has_vector(value: Any) -> bool:
        if value is None:
            return False
        try:
            return len(value) > 0
        except TypeError:
            return False

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))

    async def similarity_search(
        self,
        novel_id: str,
        query_vector: List[float],
        limit: int = 5,
        type_filter: Optional[str] = None,
    ) -> List[SimilarDocument]:
        dialect_name = self.session.bind.dialect.name if self.session.bind else "sqlite"

        if dialect_name == "postgresql":
            return await self._similarity_search_postgres(novel_id, query_vector, limit, type_filter)
        return await self._similarity_search_sqlite(novel_id, query_vector, limit, type_filter)

    async def _similarity_search_postgres(
        self,
        novel_id: str,
        query_vector: List[float],
        limit: int,
        type_filter: Optional[str],
    ) -> List[SimilarDocument]:
        vector_str = "[" + ",".join(str(v) for v in query_vector) + "]"
        sql = """
            SELECT id, type, name,
                   1 - (vector_embedding <=> :query_vector) AS similarity
            FROM entities
            WHERE novel_id = :novel_id
              AND vector_embedding IS NOT NULL
        """
        params = {"novel_id": novel_id, "query_vector": vector_str}
        if type_filter:
            sql += " AND type = :type_filter"
            params["type_filter"] = type_filter
        sql += " ORDER BY similarity DESC LIMIT :limit"
        params["limit"] = limit

        result = await self.session.execute(text(sql), params)
        rows = result.all()
        return [
            SimilarDocument(
                doc_id=row.id,
                doc_type=row.type,
                title=row.name,
                content_preview=f"{row.name} ({row.type})",
                similarity_score=float(row.similarity),
            )
            for row in rows
        ]

    async def _similarity_search_sqlite(
        self,
        novel_id: str,
        query_vector: List[float],
        limit: int,
        type_filter: Optional[str],
    ) -> List[SimilarDocument]:
        stmt = select(Entity).where(
            Entity.novel_id == novel_id,
            Entity.vector_embedding.is_not(None),
        )
        if type_filter:
            stmt = stmt.where(Entity.type == type_filter)

        result = await self.session.execute(stmt)
        entities = result.scalars().all()

        scored = []
        for entity in entities:
            emb = entity.vector_embedding
            if not emb:
                continue
            score = self._cosine_similarity(query_vector, emb)
            scored.append((score, entity))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            SimilarDocument(
                doc_id=entity.id,
                doc_type=entity.type,
                title=entity.name,
                content_preview=f"{entity.name} ({entity.type})",
                similarity_score=score,
            )
            for score, entity in scored[:limit]
        ]
