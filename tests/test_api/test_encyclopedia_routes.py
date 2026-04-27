import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router, get_session
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.entity_group_repo import EntityGroupRepository
from novel_dev.repositories.timeline_repo import TimelineRepository
from novel_dev.repositories.spaceline_repo import SpacelineRepository
from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
from novel_dev.repositories.version_repo import EntityVersionRepository
from novel_dev.repositories.relationship_repo import RelationshipRepository

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_list_entities(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    group_repo = EntityGroupRepository(async_session)
    await repo.create("e1", "character", "Lin Feng", novel_id="n1")
    group = await group_repo.upsert("n1", "人物", "主角阵营", "hero-camp", source="system")
    await repo.update_classification("e1", system_category="人物", system_group_id=group.id)
    await version_repo.create(
        "e1",
        1,
        {"name": "Lin Feng", "identity": "弟子", "personality": "坚韧", "goal": "报仇"},
    )
    await repo.update_version("e1", 1)
    await async_session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/n1/entities")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["items"]) == 1
            assert data["items"][0]["name"] == "Lin Feng"
            assert data["items"][0]["latest_state"]["identity"] == "弟子"
            assert data["items"][0]["latest_state"]["personality"] == "坚韧"
            assert data["items"][0]["latest_state"]["goal"] == "报仇"
            assert data["items"][0]["effective_category"] == "人物"
            assert data["items"][0]["effective_group_name"] == "主角阵营"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_entities_collapses_normalized_aliases(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    await repo.create("e1", "character", "陆照（主角）", novel_id="n_alias_view")
    await repo.create("e2", "character", "陆照", novel_id="n_alias_view")
    await version_repo.create("e1", 1, {"name": "陆照（主角）", "identity": "主角"})
    await version_repo.create("e2", 1, {"name": "陆照", "goal": "超脱"})
    await repo.update_version("e1", 1)
    await repo.update_version("e2", 1)
    await async_session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/n_alias_view/entities")
            assert resp.status_code == 200
            items = resp.json()["items"]
            assert len(items) == 1
            assert items[0]["name"] == "陆照"
            assert items[0]["aliases"] == ["陆照（主角）"]
            assert items[0]["latest_state"]["identity"] == "主角"
            assert items[0]["latest_state"]["goal"] == "超脱"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_entities_keeps_global_and_domain_entities_separate(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    await repo.create("e_global", "character", "张小凡", novel_id="n_scope")
    await repo.create("e_domain_zhuxian", "character", "张小凡", novel_id="n_scope")
    await repo.create("e_domain_zhetian", "character", "张小凡", novel_id="n_scope")
    await version_repo.create("e_global", 1, {"name": "张小凡", "identity": "全局占位"})
    await version_repo.create("e_domain_zhuxian", 1, {
        "name": "张小凡",
        "identity": "草庙村少年",
        "_knowledge_usage": "domain",
        "_knowledge_domain_id": "domain_zhuxian",
        "_knowledge_domain_name": "诛仙",
    })
    await version_repo.create("e_domain_zhetian", 1, {
        "name": "张小凡",
        "identity": "遮天同名角色",
        "_knowledge_usage": "domain",
        "_knowledge_domain_id": "domain_zhetian",
        "_knowledge_domain_name": "遮天",
    })
    for entity_id in ("e_global", "e_domain_zhuxian", "e_domain_zhetian"):
        await repo.update_version(entity_id, 1)
    await async_session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/n_scope/entities")
            assert resp.status_code == 200
            items = resp.json()["items"]
            assert len(items) == 3
            by_id = {item["entity_id"]: item for item in items}
            assert by_id["e_global"]["knowledge_usage"] == "global"
            assert by_id["e_domain_zhuxian"]["knowledge_usage"] == "domain"
            assert by_id["e_domain_zhuxian"]["knowledge_domain_name"] == "诛仙"
            assert by_id["e_domain_zhetian"]["knowledge_domain_name"] == "遮天"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_entity(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    group_repo = EntityGroupRepository(async_session)
    await repo.create("e1", "character", "Lin Feng", novel_id="n1")
    group = await group_repo.upsert("n1", "人物", "主角阵营", "hero-camp", source="system")
    await repo.update_classification("e1", system_category="人物", system_group_id=group.id)
    await version_repo.create(
        "e1",
        1,
        {"name": "Lin Feng", "identity": "弟子", "personality": "坚韧", "goal": "报仇"},
    )
    await repo.update_version("e1", 1)
    await async_session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/n1/entities/e1")
            assert resp.status_code == 200
            data = resp.json()
            assert data["entity_id"] == "e1"
            assert data["latest_state"]["identity"] == "弟子"
            assert data["effective_category"] == "人物"
            assert data["effective_group_name"] == "主角阵营"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_entity_fields(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    await repo.create("e1", "character", "Lin Feng", novel_id="n_edit")
    await version_repo.create(
        "e1",
        1,
        {"name": "Lin Feng", "identity": "弟子", "personality": "坚韧"},
    )
    await repo.update_version("e1", 1)
    await async_session.commit()

    try:
      async with AsyncClient(transport=transport, base_url="http://test") as client:
          resp = await client.patch(
              "/api/novels/n_edit/entities/e1",
              json={
                  "name": "林风",
                  "type": "character",
                  "aliases": ["Lin Feng", "阿风"],
                  "state_fields": {
                      "identity": "青云宗内门弟子",
                      "goal": "查明灭门真相",
                  },
              },
          )
          assert resp.status_code == 200
          data = resp.json()
          assert data["name"] == "林风"
          assert data["current_version"] == 2
          assert data["latest_state"]["name"] == "林风"
          assert data["latest_state"]["identity"] == "青云宗内门弟子"
          assert data["latest_state"]["goal"] == "查明灭门真相"
          assert data["aliases"] == ["Lin Feng", "阿风"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_entity_hard_deletes_versions_and_relationships(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    relationship_repo = RelationshipRepository(async_session)
    await repo.create("e1", "character", "Lin Feng", novel_id="n_delete")
    await repo.create("e2", "character", "苏瑶", novel_id="n_delete")
    await version_repo.create("e1", 1, {"name": "Lin Feng"})
    await version_repo.create("e2", 1, {"name": "苏瑶"})
    await repo.update_version("e1", 1)
    await repo.update_version("e2", 1)
    await relationship_repo.create("e1", "e2", "盟友", novel_id="n_delete")
    await relationship_repo.create("e2", "e1", "盟友", novel_id="n_delete")
    await async_session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete("/api/novels/n_delete/entities/e1")
            assert resp.status_code == 200
            assert resp.json() == {"deleted": True, "entity_id": "e1"}

            detail_resp = await client.get("/api/novels/n_delete/entities/e1")
            assert detail_resp.status_code == 404

            list_resp = await client.get("/api/novels/n_delete/entities")
            assert list_resp.status_code == 200
            items = list_resp.json()["items"]
            assert [item["entity_id"] for item in items] == ["e2"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_entity_classification(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    repo = EntityRepository(async_session)
    group_repo = EntityGroupRepository(async_session)
    await repo.create("e1", "character", "Lin Feng", novel_id="n1")
    await group_repo.upsert("n1", "人物", "主角阵营", "hero-camp", source="custom")
    await async_session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/novels/n1/entities/e1/classification",
                json={"manual_category": "人物", "manual_group_slug": "hero-camp"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["classification_status"] == "manual_override"
            assert data["manual_category"] == "人物"
            updated = await repo.get_by_id("e1")
            assert updated.search_vector_embedding is not None
            assert "一级分类：人物" in (updated.search_document or "")
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_entity_classification_can_clear_manual_override(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    repo = EntityRepository(async_session)
    group_repo = EntityGroupRepository(async_session)
    await repo.create("e1", "character", "Lin Feng", novel_id="n_clear")
    group = await group_repo.upsert("n_clear", "人物", "主角阵营", "hero-camp", source="custom")
    await repo.update_classification("e1", manual_category="人物", manual_group_id=group.id)
    await async_session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/novels/n_clear/entities/e1/classification",
                json={"clear_manual_override": True},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["manual_category"] is None
            assert data["manual_group_id"] is None
            assert data["classification_status"] == "auto"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_entity_classification_allows_group_only_override(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    repo = EntityRepository(async_session)
    group_repo = EntityGroupRepository(async_session)
    await repo.create("e1", "character", "Lin Feng", novel_id="n_group_only")
    system_group = await group_repo.upsert("n_group_only", "人物", "主角阵营", "hero-camp", source="system")
    await repo.update_classification("e1", system_category="人物", system_group_id=system_group.id)
    await async_session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/novels/n_group_only/entities/e1/classification",
                json={"manual_group_slug": "shi-men", "manual_group_name": "师门"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["manual_category"] == "人物"
            assert data["manual_group_slug"] == "shi-men"
            assert data["effective_group_name"] == "师门"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_reclassify_entities_for_novel(async_session, monkeypatch):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    await repo.create("e1", "character", "陆照", novel_id="n_reclassify")
    await repo.create("e2", "item", "昆仑镜", novel_id="n_reclassify")
    await version_repo.create("e1", 1, {"name": "陆照", "identity": "主角"})
    await version_repo.create("e2", 1, {"name": "昆仑镜", "description": "上古镜类至宝"})
    await repo.update_version("e1", 1)
    await repo.update_version("e2", 1)
    await async_session.commit()

    try:
        from novel_dev.agents.entity_classifier import (
            EntityClassificationBatchItem,
            EntityClassificationBatchResult,
            EntityClassifierAgent,
        )

        async def fail_single_classify(*args, **kwargs):
            raise AssertionError("full reclassify should use batch classifier")

        batch_calls = []

        async def classify_batch(self, *, entities, novel_id=""):
            batch_calls.append([entity["entity_name"] for entity in entities])
            return EntityClassificationBatchResult(
                items=[
                    EntityClassificationBatchItem(
                        index=0,
                        category="人物",
                        group_name="主角阵营",
                        confidence=0.94,
                        reason="batch test",
                    ),
                    EntityClassificationBatchItem(
                        index=1,
                        category="法宝神兵",
                        group_name="特殊法宝",
                        confidence=0.93,
                        reason="batch test",
                    ),
                ]
            )

        monkeypatch.setattr(EntityClassifierAgent, "classify", fail_single_classify)
        monkeypatch.setattr(EntityClassifierAgent, "classify_batch", classify_batch)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/novels/n_reclassify/entities/reclassify")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 2
            assert data["updated"] == 2
            assert data["batch_size"] == 25
            assert batch_calls == [["陆照", "昆仑镜"]]

            list_resp = await client.get("/api/novels/n_reclassify/entities")
            assert list_resp.status_code == 200
            items = {item["name"]: item for item in list_resp.json()["items"]}
            assert items["陆照"]["effective_category"] == "人物"
            assert items["陆照"]["effective_group_name"] == "主角阵营"
            assert items["昆仑镜"]["effective_category"] == "法宝神兵"
            assert items["昆仑镜"]["effective_group_name"] == "特殊法宝"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_search_entities_returns_grouped_results(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    repo = EntityRepository(async_session)
    group_repo = EntityGroupRepository(async_session)
    await repo.create("e1", "character", "主角阵营", novel_id="n_search")
    entity = await repo.get_by_id("e1")
    group = await group_repo.upsert("n_search", "人物", "主角阵营", "hero-camp", source="system")
    await repo.update_classification("e1", system_category="人物", system_group_id=group.id)
    await repo.update_classification("e1", manual_category="势力")
    entity.search_document = "名称：主角阵营\n一级分类：人物"
    entity.search_vector_embedding = [1.0, 0.0, 0.0]
    await async_session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/n_search/entities/search", params={"q": "主角阵营"})
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["items"]) == 1
            group_item = data["items"][0]
            assert group_item["category"] == "势力"
            assert group_item["group_slug"] is None
            assert group_item["group_name"] is None
            assert len(group_item["entities"]) == 1
            assert group_item["entities"][0]["entity_id"] == "e1"
            assert group_item["entities"][0]["match_reason"] in {"名称命中", "语义相关", "关系命中"}
            assert group_item["entities"][0]["effective_category"] == "势力"
            assert group_item["entities"][0]["classification_status"] == "manual_override"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_search_entities_blank_query_returns_empty_grouped_results(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    repo = EntityRepository(async_session)
    await repo.create("e1", "character", "主角阵营", novel_id="n_search_blank")
    await async_session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/n_search_blank/entities/search", params={"q": "   "})
            assert resp.status_code == 200
            assert resp.json()["items"] == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_entity_relationships_falls_back_to_latest_state(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    await repo.create("e1", "character", "陆照", novel_id="n_rel")
    await repo.create("e2", "character", "苏清寒", novel_id="n_rel")
    await version_repo.create(
        "e1",
        1,
        {"name": "陆照", "relationships": "与苏清寒亦敌亦友，后来结成同盟"},
    )
    await version_repo.create(
        "e2",
        1,
        {"name": "苏清寒"},
    )
    await repo.update_version("e1", 1)
    await repo.update_version("e2", 1)
    await async_session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/n_rel/entity_relationships")
            assert resp.status_code == 200
            items = resp.json()["items"]
            assert len(items) == 1
            assert items[0]["source_id"] == "e1"
            assert items[0]["target_id"] == "e2"
            assert items[0]["relation_type"] == "同盟"
            assert items[0]["is_inferred"] is True
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_entity_relationships_infers_relationships_for_non_character_entities(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    await repo.create("hero", "character", "孟奇", novel_id="n_item_rel")
    await repo.create("jade", "item", "护身玉佩", novel_id="n_item_rel")
    await repo.create("mirror", "item", "照道镜", novel_id="n_item_rel")
    await repo.create("kunlun", "item", "昆仑镜", novel_id="n_item_rel")
    await version_repo.create("hero", 1, {"name": "孟奇"})
    await version_repo.create(
        "jade",
        1,
        {
            "name": "护身玉佩",
            "description": "孟奇所赠，可抵挡致命一击",
            "significance": "前期保命之物，暗示主角与孟奇的关联",
        },
    )
    await version_repo.create("mirror", 1, {"name": "照道镜"})
    await version_repo.create(
        "kunlun",
        1,
        {
            "name": "昆仑镜",
            "description": "昆仑山神兵，可观过去未来，映照诸天",
            "significance": "与照道镜功能相似，可能形成对照或竞争关系",
        },
    )
    await repo.update_version("hero", 1)
    await repo.update_version("jade", 1)
    await repo.update_version("mirror", 1)
    await repo.update_version("kunlun", 1)
    await async_session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/n_item_rel/entity_relationships")
            assert resp.status_code == 200
            items = resp.json()["items"]
            edges = {
                (item["source_id"], item["target_id"], item["relation_type"]): item
                for item in items
            }
            assert ("jade", "hero", "关联") in edges
            assert edges[("jade", "hero", "关联")]["meta"]["source"] == "latest_state.description"
            assert ("kunlun", "mirror", "关联") in edges
            assert edges[("kunlun", "mirror", "关联")]["meta"]["source"] == "latest_state.significance"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_entity_relationships_downgrades_non_character_mentor_inference(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    await repo.create("hero", "character", "陆照", novel_id="n_cross_rel")
    await repo.create("manual", "item", "道经", novel_id="n_cross_rel")
    await version_repo.create(
        "hero",
        1,
        {"name": "陆照", "identity": "道经传人"},
    )
    await version_repo.create(
        "manual",
        1,
        {"name": "道经"},
    )
    await repo.update_version("hero", 1)
    await repo.update_version("manual", 1)
    await async_session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/n_cross_rel/entity_relationships")
            assert resp.status_code == 200
            items = resp.json()["items"]
            assert len(items) == 1
            assert items[0]["source_id"] == "hero"
            assert items[0]["target_id"] == "manual"
            assert items[0]["relation_type"] == "关联"
            assert items[0]["meta"]["source"] == "latest_state.identity"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_timelines(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    repo = TimelineRepository(async_session)
    await repo.create(tick=1, narrative="Start", novel_id="n1")
    await async_session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/n1/timelines")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["items"]) == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_spacelines(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    repo = SpacelineRepository(async_session)
    await repo.create("loc_1", "Qingyun", novel_id="n1")
    await async_session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/n1/spacelines")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["items"]) == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_foreshadowings(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    repo = ForeshadowingRepository(async_session)
    await repo.create(fs_id="fs_1", content="Hint", novel_id="n1")
    await async_session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/n1/foreshadowings")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["items"]) == 1
    finally:
        app.dependency_overrides.clear()
