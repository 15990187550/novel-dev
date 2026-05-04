import pytest
import numpy as np
from types import SimpleNamespace

from novel_dev.db.models import EntityRelationship
from novel_dev.repositories.entity_group_repo import EntityGroupRepository
from novel_dev.repositories.entity_repo import EntityRepository


class AmbiguousVector:
    def __init__(self, values):
        self.values = values

    def __iter__(self):
        return iter(self.values)

    def __len__(self):
        return len(self.values)

    def __bool__(self):
        raise ValueError("ambiguous truth value")


class _FakeScalars:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return _FakeScalars(self.rows)


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _stmt):
        return _FakeResult(self.rows)


def _search_row(
    entity_id,
    name,
    *,
    category="人物",
    entity_type="character",
    document=None,
    vector=None,
):
    return SimpleNamespace(
        id=entity_id,
        type=entity_type,
        name=name,
        novel_id="n1",
        system_category=category,
        manual_category=None,
        system_group_id=None,
        manual_group_id=None,
        search_document=document or f"名称：{name}\n一级分类：{category}",
        search_vector_embedding=vector or [0.1, 0.0, 0.0],
    )


@pytest.mark.asyncio
async def test_create_entity(async_session):
    repo = EntityRepository(async_session)
    entity = await repo.create("char_001", "character", "Lin Feng")
    assert entity.id == "char_001"
    assert entity.name == "Lin Feng"


@pytest.mark.asyncio
async def test_search_entities_accepts_array_like_vectors_without_truth_value_check():
    entity = SimpleNamespace(
        id="e1",
        type="character",
        name="陆照",
        novel_id="n1",
        system_category=None,
        manual_category=None,
        system_group_id=None,
        manual_group_id=None,
        search_document="名称：陆照",
        search_vector_embedding=AmbiguousVector([np.float32(1.0), np.float32(0.0), np.float32(0.0)]),
    )
    repo = EntityRepository(_FakeSession([entity]))

    results = await repo.search_entities(
        "n1",
        query="陆照",
        query_vector=[1.0, 0.0, 0.0],
    )

    assert results[0]["entity_id"] == "e1"
    assert results[0]["score"] > 1
    assert type(results[0]["score"]) is float


@pytest.mark.asyncio
async def test_search_entities_answers_subject_category_relationship_query():
    rows = [
        SimpleNamespace(
            id="hero",
            type="character",
            name="陆照",
            novel_id="n1",
            system_category="人物",
            manual_category=None,
            system_group_id=None,
            manual_group_id=None,
            search_document="名称：陆照\n一级分类：人物\nrelationships：从孟奇处获得道经传承\nresources：拥有三清遗留的道经",
            search_vector_embedding=[0.9, 0.1, 0.0],
        ),
        SimpleNamespace(
            id="dao-local",
            type="item",
            name="道经",
            novel_id="n1",
            system_category="功法",
            manual_category=None,
            system_group_id=None,
            manual_group_id=None,
            search_document="名称：道经\n一级分类：功法\nsignificance：主角核心修炼典籍",
            search_vector_embedding=[0.1, 0.9, 0.0],
        ),
        SimpleNamespace(
            id="dao-yangshen",
            type="item",
            name="道经",
            novel_id="n1",
            system_category="功法",
            manual_category=None,
            system_group_id=None,
            manual_group_id=None,
            search_document="名称：道经\n一级分类：功法\n_knowledge_domain_id：domain_yangshen\n_knowledge_domain_name：阳神",
            search_vector_embedding=[0.1, 0.8, 0.0],
        ),
        SimpleNamespace(
            id="unrelated",
            type="item",
            name="虎魔炼骨拳",
            novel_id="n1",
            system_category="功法",
            manual_category=None,
            system_group_id=None,
            manual_group_id=None,
            search_document="名称：虎魔炼骨拳\n一级分类：功法",
            search_vector_embedding=[0.95, 0.0, 0.0],
        ),
    ]
    repo = EntityRepository(_FakeSession(rows))

    results = await repo.search_entities(
        "n1",
        query="陆照所修的功法",
        query_vector=[1.0, 0.0, 0.0],
    )

    assert [item["entity_id"] for item in results] == ["dao-local"]
    assert results[0]["match_reason"] == "关系查询"


@pytest.mark.asyncio
async def test_search_entities_returns_empty_for_unresolved_relationship_query():
    rows = [
        SimpleNamespace(
            id="qinhao",
            type="character",
            name="齐昊",
            novel_id="n1",
            system_category="人物",
            manual_category=None,
            system_group_id=None,
            manual_group_id=None,
            search_document="名称：齐昊\n一级分类：人物\nrelationships：田灵儿妻子",
            search_vector_embedding=[1.0, 0.0, 0.0],
        ),
        SimpleNamespace(
            id="tianlinger",
            type="character",
            name="田灵儿",
            novel_id="n1",
            system_category="人物",
            manual_category=None,
            system_group_id=None,
            manual_group_id=None,
            search_document="名称：田灵儿\n一级分类：人物\nrelationships：齐昊妻子",
            search_vector_embedding=[0.9, 0.0, 0.0],
        ),
    ]
    repo = EntityRepository(_FakeSession(rows))

    results = await repo.search_entities(
        "n1",
        query="石昊的妻子",
        query_vector=[1.0, 0.0, 0.0],
    )

    assert results == []


@pytest.mark.asyncio
async def test_search_entities_uses_explicit_relationship_graph_before_semantic_noise(async_session):
    repo = EntityRepository(async_session)
    hero = await repo.create("shihao", "character", "石昊", novel_id="n_graph")
    wife = await repo.create("yunxi", "character", "云曦", novel_id="n_graph")
    unrelated = await repo.create("qingyun", "faction", "青云门", novel_id="n_graph")
    hero.system_category = "人物"
    hero.search_document = "名称：石昊\n一级分类：人物"
    hero.search_vector_embedding = [0.0, 0.0, 1.0]
    wife.system_category = "人物"
    wife.search_document = "名称：云曦\n一级分类：人物"
    wife.search_vector_embedding = [0.1, 0.0, 0.0]
    unrelated.system_category = "势力"
    unrelated.search_document = "名称：青云门\n一级分类：势力"
    unrelated.search_vector_embedding = [1.0, 0.0, 0.0]
    async_session.add(
        EntityRelationship(
            source_id=hero.id,
            target_id=wife.id,
            relation_type="妻子",
            novel_id="n_graph",
        )
    )
    await async_session.flush()

    results = await repo.search_entities(
        "n_graph",
        query="石昊的妻子",
        query_vector=[1.0, 0.0, 0.0],
    )

    assert [item["entity_id"] for item in results] == ["yunxi"]
    assert results[0]["match_reason"] == "关系图谱"


@pytest.mark.asyncio
async def test_search_entities_resolves_inverse_relationship_graph_edges(async_session):
    repo = EntityRepository(async_session)
    child = await repo.create("qinyu", "character", "秦羽", novel_id="n_graph_inverse")
    father = await repo.create("qinde", "character", "秦德", novel_id="n_graph_inverse")
    child.system_category = "人物"
    child.search_document = "名称：秦羽\n一级分类：人物"
    father.system_category = "人物"
    father.search_document = "名称：秦德\n一级分类：人物"
    async_session.add(
        EntityRelationship(
            source_id=father.id,
            target_id=child.id,
            relation_type="父亲",
            novel_id="n_graph_inverse",
        )
    )
    await async_session.flush()

    results = await repo.search_entities(
        "n_graph_inverse",
        query="秦羽的父亲",
        query_vector=[1.0, 0.0, 0.0],
    )

    assert [item["entity_id"] for item in results] == ["qinde"]
    assert results[0]["match_reason"] == "关系图谱"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected_ids"),
    [
        ("秦羽的父母", ["father", "mother"]),
        ("秦羽的结拜兄弟", ["houfei", "heiyu"]),
        ("张小凡的师兄弟", ["songdaren", "linjingyu"]),
        ("韩立的红颜知己", ["ziling", "yinyue"]),
        ("叶凡的宿敌", ["budie"]),
        ("林雷的恩人", ["beirut"]),
        ("洪易的手下", ["tuyuan"]),
    ],
)
async def test_search_entities_supports_broader_person_relationship_queries(query, expected_ids):
    rows = [
        _search_row(
            "qinyu",
            "秦羽",
            document=(
                "名称：秦羽\n一级分类：人物\nrelationships："
                "父亲秦德，母亲静怡；妻子姜立；结拜二弟侯费、三弟黑羽。"
            ),
        ),
        _search_row(
            "zhangxiaofan",
            "张小凡",
            document="名称：张小凡\n一级分类：人物\nrelationships：宋大仁为师兄，林惊羽为同门好友，田不易为师父。",
        ),
        _search_row(
            "hanli",
            "韩立",
            document="名称：韩立\n一级分类：人物\nrelationships：南宫婉为道侣；紫灵、银月为红颜知己；厉飞雨为好友。",
        ),
        _search_row(
            "yefan",
            "叶凡",
            document="名称：叶凡\n一级分类：人物\nrelationships：姬紫月为妻子；不死天皇为宿敌；庞博为挚友。",
        ),
        _search_row(
            "linlei",
            "林雷",
            document="名称：林雷\n一级分类：人物\nrelationships：贝鲁特为恩人和支持者；迪莉娅为妻子。",
        ),
        _search_row(
            "hongyi",
            "洪易",
            document="名称：洪易\n一级分类：人物\nrelationships：图元为手下；禅银纱为道侣；洪玄机为父亲兼敌人。",
        ),
        _search_row("father", "秦德"),
        _search_row("mother", "静怡"),
        _search_row("wife", "姜立"),
        _search_row("houfei", "侯费"),
        _search_row("heiyu", "黑羽"),
        _search_row("songdaren", "宋大仁"),
        _search_row("linjingyu", "林惊羽"),
        _search_row("master", "田不易"),
        _search_row("nangongwan", "南宫婉"),
        _search_row("ziling", "紫灵"),
        _search_row("yinyue", "银月"),
        _search_row("lifeyu", "厉飞雨"),
        _search_row("jiziyue", "姬紫月"),
        _search_row("budie", "不死天皇"),
        _search_row("pangbo", "庞博"),
        _search_row("beirut", "贝鲁特"),
        _search_row("delia", "迪莉娅"),
        _search_row("tuyuan", "图元"),
        _search_row("chanyinsha", "禅银纱"),
        _search_row("hongxuanji", "洪玄机"),
    ]
    repo = EntityRepository(_FakeSession(rows))

    results = await repo.search_entities(
        "n1",
        query=query,
        query_vector=[1.0, 0.0, 0.0],
    )

    assert [item["entity_id"] for item in results] == expected_ids
    assert {item["match_reason"] for item in results} == {"关系查询"}


@pytest.mark.asyncio
async def test_find_by_names(async_session):
    repo = EntityRepository(async_session)
    await repo.create("e1", "character", "林风")
    await repo.create("e2", "character", "苏雪")
    results = await repo.find_by_names(["林风", "苏雪"])
    assert len(results) == 2
    assert {r.name for r in results} == {"林风", "苏雪"}


@pytest.mark.asyncio
async def test_find_by_name_matches_compound_alias_variants(async_session):
    repo = EntityRepository(async_session)
    entity = await repo.create("zhangxiaofan", "character", "张小凡/鬼厉", novel_id="n_alias_variant")

    by_primary = await repo.find_by_name("张小凡", entity_type="character", novel_id="n_alias_variant")
    by_alias = await repo.find_by_name("鬼厉", entity_type="character", novel_id="n_alias_variant")

    assert by_primary == entity
    assert by_alias == entity


@pytest.mark.asyncio
async def test_create_entity_with_novel_id(async_session):
    repo = EntityRepository(async_session)
    entity = await repo.create("char_002", "character", "Zhang San", novel_id="novel_a")
    assert entity.id == "char_002"
    assert entity.novel_id == "novel_a"


@pytest.mark.asyncio
async def test_create_entity_initializes_classification_fields(async_session):
    repo = EntityRepository(async_session)
    entity = await repo.create("char_100", "character", "陆照", novel_id="novel_x")

    assert entity.system_category is None
    assert entity.system_group_id is None
    assert entity.manual_category is None
    assert entity.manual_group_id is None
    assert entity.classification_reason is None
    assert entity.classification_confidence is None
    assert entity.search_document is None
    assert entity.search_vector_embedding is None
    assert entity.system_needs_review is False


@pytest.mark.asyncio
async def test_list_entities_by_novel(async_session):
    repo = EntityRepository(async_session)
    await repo.create("e1", "character", "A", novel_id="n1")
    await repo.create("e2", "character", "B", novel_id="n1")
    await repo.create("e3", "character", "C", novel_id="n2")
    results = await repo.list_by_novel("n1")
    assert len(results) == 2
    assert {r.name for r in results} == {"A", "B"}


@pytest.mark.asyncio
async def test_entity_repo_rejects_manual_group_outside_manual_category(async_session):
    group_repo = EntityGroupRepository(async_session)
    entity_repo = EntityRepository(async_session)

    group = await group_repo.upsert(
        novel_id="novel_x",
        category="人物",
        group_name="人物",
        group_slug="people",
    )
    entity = await entity_repo.create("char_200", "character", "陆照", novel_id="novel_x")

    with pytest.raises(ValueError, match="manual_group must belong to manual_category"):
        await entity_repo.update_classification(
            entity.id,
            manual_category="势力",
            manual_group_id=group.id,
        )


@pytest.mark.asyncio
async def test_update_classification_clears_manual_group_when_category_changes(async_session):
    group_repo = EntityGroupRepository(async_session)
    entity_repo = EntityRepository(async_session)

    people_group = await group_repo.upsert(
        novel_id="novel_x",
        category="人物",
        group_name="人物",
        group_slug="people",
    )
    entity = await entity_repo.create("char_201", "character", "陆照", novel_id="novel_x")

    await entity_repo.update_classification(
        entity.id,
        manual_category="人物",
        manual_group_id=people_group.id,
    )

    updated = await entity_repo.update_classification(
        entity.id,
        manual_category="势力",
    )
    assert updated.manual_category == "势力"
    assert updated.manual_group_id is None

    await entity_repo.update_classification(
        entity.id,
        manual_category="人物",
        manual_group_id=people_group.id,
    )
    cleared = await entity_repo.update_classification(
        entity.id,
        manual_category=None,
    )
    assert cleared.manual_category is None
    assert cleared.manual_group_id is None


@pytest.mark.asyncio
async def test_update_classification_clears_system_group_when_category_changes(async_session):
    group_repo = EntityGroupRepository(async_session)
    entity_repo = EntityRepository(async_session)

    people_group = await group_repo.upsert(
        novel_id="novel_x",
        category="人物",
        group_name="人物",
        group_slug="people",
    )
    faction_group = await group_repo.upsert(
        novel_id="novel_x",
        category="势力",
        group_name="势力",
        group_slug="factions",
    )
    entity = await entity_repo.create("char_202", "character", "陆照", novel_id="novel_x")

    await entity_repo.update_classification(
        entity.id,
        system_category="人物",
        system_group_id=people_group.id,
    )

    updated = await entity_repo.update_classification(
        entity.id,
        system_category="势力",
    )
    assert updated.system_category == "势力"
    assert updated.system_group_id is None

    with pytest.raises(ValueError, match="system_group must belong to system_category"):
        await entity_repo.update_classification(
            entity.id,
            system_category="人物",
            system_group_id=faction_group.id,
        )
