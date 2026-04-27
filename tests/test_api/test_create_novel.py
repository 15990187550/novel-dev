import re
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from sqlalchemy import select

from novel_dev.api import routes
from novel_dev.api.routes import router, get_session
from novel_dev.db.models import (
    AgentLog,
    BrainstormWorkspace,
    Chapter,
    Entity,
    EntityGroup,
    EntityRelationship,
    EntityVersion,
    Foreshadowing,
    NovelDocument,
    NovelState,
    OutlineMessage,
    OutlineSession,
    PendingExtraction,
    Spaceline,
    Timeline,
)

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_create_novel(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/novels", json={"title": "测试小说"})
            assert resp.status_code == 201
            data = resp.json()
            assert data["novel_id"].startswith("novel-")
            assert data["title"] == "测试小说"
            assert data["current_phase"] == "brainstorming"
            assert data["checkpoint_data"]["novel_title"] == "测试小说"
            assert data["checkpoint_data"]["synopsis_data"]["title"] == "测试小说"
            assert data["checkpoint_data"]["synopsis_data"]["estimated_volumes"] == 1
            assert data["current_volume_id"] is None
            assert data["current_chapter_id"] is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_novel_empty_title(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/novels", json={"title": "  "})
            assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_novel_title_is_separate_from_synopsis_title(async_session):
    novel_id = "n_title_update"

    async def override():
        yield async_session

    async_session.add(
        NovelState(
            novel_id=novel_id,
            current_phase="volume_planning",
            checkpoint_data={
                "novel_title": "旧项目名",
                "synopsis_data": {"title": "总纲标题"},
            },
        )
    )
    await async_session.commit()

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(f"/api/novels/{novel_id}", json={"title": "新项目名"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["title"] == "新项目名"
            assert data["checkpoint_data"]["novel_title"] == "新项目名"
            assert data["checkpoint_data"]["synopsis_data"]["title"] == "总纲标题"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_novel_removes_all_scoped_data(async_session, tmp_path):
    novel_id = "n_delete"
    other_novel_id = "n_keep"

    async def override():
        yield async_session

    async_session.add_all([
        NovelState(novel_id=novel_id, current_phase="brainstorming", checkpoint_data={}),
        NovelState(novel_id=other_novel_id, current_phase="drafting", checkpoint_data={}),
        Entity(
            id="e1",
            type="character",
            name="主角",
            novel_id=novel_id,
            manual_group_id="g1",
            system_group_id="g1",
        ),
        Entity(id="e2", type="character", name="旁观者", novel_id=other_novel_id),
        EntityGroup(id="g1", novel_id=novel_id, category="人物", group_name="主角团", group_slug="protagonists"),
        EntityRelationship(id=1, source_id="e1", target_id="e1", relation_type="关联", novel_id=novel_id),
        Timeline(id=1, tick=1, narrative="事件", novel_id=novel_id),
        Spaceline(id="s1", name="宗门", novel_id=novel_id),
        Foreshadowing(id="f1", content="伏笔", novel_id=novel_id),
        Chapter(id="ch1", volume_id="vol1", chapter_number=1, novel_id=novel_id, status="pending"),
        NovelDocument(id="d1", novel_id=novel_id, doc_type="setting", title="设定", content="内容"),
        OutlineSession(id="os1", novel_id=novel_id, outline_type="volume", outline_ref="vol1", status="pending"),
        OutlineMessage(id="om1", session_id="os1", role="assistant", message_type="reply", content="ok"),
        BrainstormWorkspace(id="bw1", novel_id=novel_id, status="active", outline_drafts={}, setting_docs_draft=[]),
        PendingExtraction(
            id="pe1",
            novel_id=novel_id,
            extraction_type="setting",
            status="pending",
            raw_result={},
        ),
        AgentLog(novel_id=novel_id, agent="TestAgent", message="待删除日志", level="info"),
    ])
    await async_session.flush()
    async_session.add(EntityVersion(entity_id="e1", version=1, state={}))
    await async_session.commit()

    novel_output_dir = tmp_path / "novel_output" / novel_id / "vol1"
    novel_output_dir.mkdir(parents=True)
    (novel_output_dir / "ch1.md").write_text("chapter", encoding="utf-8")
    original_markdown_output_dir = routes.settings.markdown_output_dir
    routes.settings.markdown_output_dir = str(tmp_path / "novel_output")

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete(f"/api/novels/{novel_id}")
            assert resp.status_code == 204

        for model in (
            NovelState,
            Entity,
            EntityGroup,
            EntityRelationship,
            Timeline,
            Spaceline,
            Foreshadowing,
            Chapter,
            NovelDocument,
            OutlineSession,
            BrainstormWorkspace,
            PendingExtraction,
            AgentLog,
        ):
            result = await async_session.execute(
                select(model).where(model.novel_id == novel_id)
            )
            assert result.scalars().first() is None

        versions = await async_session.execute(select(EntityVersion))
        assert versions.scalars().first() is None

        messages = await async_session.execute(
            select(OutlineMessage).where(OutlineMessage.session_id == "os1")
        )
        assert messages.scalars().first() is None

        assert not (tmp_path / "novel_output" / novel_id).exists()

        remaining_state = await async_session.execute(
            select(NovelState).where(NovelState.novel_id == other_novel_id)
        )
        assert remaining_state.scalar_one_or_none() is not None
    finally:
        routes.settings.markdown_output_dir = original_markdown_output_dir
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_novel_not_found(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete("/api/novels/missing-novel")
            assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()
