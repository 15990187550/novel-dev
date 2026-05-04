import pytest
from sqlalchemy import select

from novel_dev.db.models import Entity, EntityRelationship, EntityVersion
from novel_dev.scripts.merge_duplicate_domain_entities import (
    DuplicateEntityMergeService,
    entity_name_variants,
    find_duplicate_groups,
)


def test_entity_name_variants_include_bracket_and_alias_parts():
    assert entity_name_variants("荒（石昊）") >= {"荒", "石昊"}
    assert entity_name_variants("小白/九尾天狐") >= {"小白", "九尾天狐"}


def test_find_duplicate_groups_connects_bracket_aliases_and_skips_ambiguous_aggregate():
    rows = [
        {
            "id": "e_shihao",
            "name": "石昊",
            "type": "character",
            "novel_id": "novel-1",
            "domain_key": "_knowledge_domain_id:domain-1",
            "state": {},
            "relationship_count": 1,
        },
        {
            "id": "e_huang",
            "name": "荒",
            "type": "character",
            "novel_id": "novel-1",
            "domain_key": "_knowledge_domain_id:domain-1",
            "state": {},
            "relationship_count": 0,
        },
        {
            "id": "e_alias",
            "name": "荒（石昊）",
            "type": "character",
            "novel_id": "novel-1",
            "domain_key": "_knowledge_domain_id:domain-1",
            "state": {},
            "relationship_count": 0,
        },
        {
            "id": "e_yue_ting",
            "name": "瑶月婷",
            "type": "character",
            "novel_id": "novel-1",
            "domain_key": "_knowledge_domain_id:domain-1",
            "state": {},
            "relationship_count": 0,
        },
        {
            "id": "e_yue_ru",
            "name": "瑶月如",
            "type": "character",
            "novel_id": "novel-1",
            "domain_key": "_knowledge_domain_id:domain-1",
            "state": {},
            "relationship_count": 0,
        },
        {
            "id": "e_aggregate",
            "name": "瑶月婷/瑶月如",
            "type": "character",
            "novel_id": "novel-1",
            "domain_key": "_knowledge_domain_id:domain-1",
            "state": {},
            "relationship_count": 0,
        },
    ]

    groups, skipped = find_duplicate_groups(rows)

    group_by_keep = {group["keep_id"]: group for group in groups}
    assert group_by_keep["e_shihao"]["drop_ids"] == ["e_huang", "e_alias"]
    assert not any("e_aggregate" in group["drop_ids"] for group in groups)
    assert any(item["entity_id"] == "e_aggregate" for item in skipped)


def test_find_duplicate_groups_skips_shared_descriptors_and_non_character_slash_branches():
    rows = [
        {
            "id": "e_wu",
            "name": "吴国（起源大陆）",
            "type": "faction",
            "novel_id": "novel-1",
            "domain_key": "_knowledge_domain_id:domain-1",
            "state": {},
            "relationship_count": 0,
        },
        {
            "id": "e_tianmu",
            "name": "天木国（起源大陆）",
            "type": "faction",
            "novel_id": "novel-1",
            "domain_key": "_knowledge_domain_id:domain-1",
            "state": {},
            "relationship_count": 0,
        },
        {
            "id": "e_world",
            "name": "晋之世界",
            "type": "faction",
            "novel_id": "novel-1",
            "domain_key": "_knowledge_domain_id:domain-1",
            "state": {},
            "relationship_count": 0,
        },
        {
            "id": "e_east_army",
            "name": "晋之世界/东军",
            "type": "faction",
            "novel_id": "novel-1",
            "domain_key": "_knowledge_domain_id:domain-1",
            "state": {},
            "relationship_count": 0,
        },
        {
            "id": "e_xiaofan",
            "name": "张小凡",
            "type": "character",
            "novel_id": "novel-1",
            "domain_key": "_knowledge_domain_id:domain-1",
            "state": {},
            "relationship_count": 0,
        },
        {
            "id": "e_alias",
            "name": "张小凡/鬼厉",
            "type": "character",
            "novel_id": "novel-1",
            "domain_key": "_knowledge_domain_id:domain-1",
            "state": {},
            "relationship_count": 0,
        },
    ]

    groups, skipped = find_duplicate_groups(rows)

    assert [group["keep_id"] for group in groups] == ["e_xiaofan"]
    assert groups[0]["drop_ids"] == ["e_alias"]
    skipped_ids = {item["entity_id"] for item in skipped}
    assert {"e_wu", "e_tianmu", "e_east_army"} <= skipped_ids


@pytest.mark.asyncio
async def test_apply_group_merges_entities_and_preserves_relationships(async_session):
    keep = Entity(
        id="e_keep",
        type="character",
        name="石昊",
        current_version=1,
        novel_id="novel-1",
        search_document="_knowledge_domain_id：domain-1\n主角",
    )
    drop = Entity(
        id="e_drop",
        type="character",
        name="荒（石昊）",
        current_version=1,
        novel_id="novel-1",
        search_document="_knowledge_domain_id：domain-1\n别名",
    )
    target = Entity(
        id="e_target",
        type="faction",
        name="石村",
        current_version=1,
        novel_id="novel-1",
        search_document="_knowledge_domain_id：domain-1\n村落",
    )
    async_session.add_all([keep, drop, target])
    async_session.add_all(
        [
            EntityVersion(entity_id="e_keep", version=1, state={"aliases": ["小石"]}),
            EntityVersion(entity_id="e_drop", version=1, state={"note": "曾名荒"}),
            EntityVersion(entity_id="e_target", version=1, state={}),
            EntityRelationship(
                source_id="e_keep",
                target_id="e_target",
                relation_type="出身",
                meta={"source": "manual"},
                novel_id="novel-1",
                is_active=True,
            ),
            EntityRelationship(
                source_id="e_drop",
                target_id="e_target",
                relation_type="出身",
                meta={"source": "backfill"},
                novel_id="novel-1",
                is_active=True,
            ),
            EntityRelationship(
                source_id="e_drop",
                target_id="e_keep",
                relation_type="关联",
                meta={"source": "old"},
                novel_id="novel-1",
                is_active=True,
            ),
        ]
    )
    await async_session.flush()

    service = DuplicateEntityMergeService(async_session, create_backups=False)
    result = await service.apply_groups(
        [
            {
                "keep_id": "e_keep",
                "drop_ids": ["e_drop"],
                "shared_variants": ["石昊"],
                "reason": "test",
            }
        ]
    )

    assert result["merged_entities"] == 1
    entities = (await async_session.execute(select(Entity))).scalars().all()
    assert {entity.id for entity in entities} == {"e_keep", "e_target"}

    latest = (
        await async_session.execute(
            select(EntityVersion)
            .where(EntityVersion.entity_id == "e_keep")
            .order_by(EntityVersion.version.desc())
        )
    ).scalars().first()
    assert latest is not None
    assert set(latest.state["aliases"]) >= {"小石", "荒", "荒（石昊）"}
    assert latest.state["_merged_duplicate_entities"][0]["entity_id"] == "e_drop"

    relationships = (await async_session.execute(select(EntityRelationship))).scalars().all()
    assert not any(rel.source_id == "e_drop" or rel.target_id == "e_drop" for rel in relationships)
    active = [rel for rel in relationships if rel.is_active]
    assert len(active) == 1
    assert active[0].source_id == "e_keep"
    assert active[0].target_id == "e_target"
    assert active[0].meta["merged_duplicate_relationships"][0]["source_id"] == "e_keep"

    inactive = [rel for rel in relationships if not rel.is_active]
    assert len(inactive) == 2
    assert any(rel.meta.get("merge_reason") == "self_relationship_after_entity_merge" for rel in inactive)
