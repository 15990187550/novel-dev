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
    await repo.create("e1", "character", "Lin Feng", novel_id="n1")
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
async def test_get_entity(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    await repo.create("e1", "character", "Lin Feng", novel_id="n1")
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
    await group_repo.upsert("n1", "人物", "主角阵营", "hero-camp", source="manual")
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
            assert group_item["category"] == "人物"
            assert group_item["group_slug"] == "hero-camp"
            assert group_item["group_name"] == "主角阵营"
            assert len(group_item["entities"]) == 1
            assert group_item["entities"][0]["entity_id"] == "e1"
            assert group_item["entities"][0]["match_reason"] in {"名称命中", "语义相关", "关系命中"}
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
