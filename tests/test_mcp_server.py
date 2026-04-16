import uuid
import pytest

from novel_dev.mcp_server.server import mcp


def test_mcp_server_has_tools():
    expected = {
        "query_entity",
        "get_active_foreshadowings",
        "get_timeline",
        "get_spaceline_chain",
        "get_novel_state",
        "get_novel_documents",
        "upload_document",
        "get_pending_documents",
        "approve_pending_documents",
        "list_style_profile_versions",
        "rollback_style_profile",
        "analyze_style_from_text",
        "prepare_chapter_context",
        "generate_chapter_draft",
        "get_chapter_draft_status",
    }
    assert set(mcp.tools.keys()) == expected


@pytest.mark.asyncio
async def test_mcp_upload_document():
    result = await mcp.tools["upload_document"]("n1", "setting.txt", "世界观：天玄大陆。")
    assert result["extraction_type"] == "setting"
    assert "id" in result


@pytest.mark.asyncio
async def test_mcp_get_pending_documents():
    upload = await mcp.tools["upload_document"]("n2", "style.txt", "a" * 5000)
    result = await mcp.tools["get_pending_documents"]("n2")
    assert any(i["id"] == upload["id"] for i in result)


@pytest.mark.asyncio
async def test_mcp_list_style_profile_versions():
    novel_id = f"n3_{uuid.uuid4().hex[:8]}"
    upload = await mcp.tools["upload_document"](novel_id, "style.txt", "x" * 10000)
    await mcp.tools["approve_pending_documents"](upload["id"])
    result = await mcp.tools["list_style_profile_versions"](novel_id)
    assert len(result) == 1
    assert result[0]["version"] == 1


@pytest.mark.asyncio
async def test_mcp_rollback_style_profile():
    novel_id = f"n4_{uuid.uuid4().hex[:8]}"
    upload = await mcp.tools["upload_document"](novel_id, "style.txt", "y" * 10000)
    await mcp.tools["approve_pending_documents"](upload["id"])
    result = await mcp.tools["rollback_style_profile"](novel_id, 1)
    assert result["rolled_back_to_version"] == 1


@pytest.mark.asyncio
async def test_mcp_analyze_style_from_text():
    result = await mcp.tools["analyze_style_from_text"]("剑光一闪。敌人倒下。")
    assert "style_guide" in result
    assert "style_config" in result


@pytest.mark.asyncio
async def test_mcp_prepare_chapter_context():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.agents.director import NovelDirector, Phase
    from novel_dev.schemas.context import ChapterPlan, BeatPlan
    from novel_dev.repositories.chapter_repo import ChapterRepository

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_mcp_ctx_{suffix}"
    chapter_id = f"c_{suffix}"
    volume_id = f"v_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        director = NovelDirector(session=session)
        chapter_plan = ChapterPlan(
            chapter_number=1,
            title="MCP Test",
            target_word_count=3000,
            beats=[BeatPlan(summary="B1", target_mood="tense")],
        )
        await director.save_checkpoint(
            novel_id,
            phase=Phase.CONTEXT_PREPARATION,
            checkpoint_data={"current_chapter_plan": chapter_plan.model_dump()},
            volume_id=volume_id,
            chapter_id=chapter_id,
        )
        await ChapterRepository(session).create(chapter_id, volume_id, 1, "MCP Test")
        await session.commit()

    result = await mcp.tools["prepare_chapter_context"](novel_id, chapter_id)
    assert result["success"] is True
    assert result["chapter_plan_title"] == "MCP Test"


@pytest.mark.asyncio
async def test_mcp_generate_chapter_draft():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.agents.director import NovelDirector, Phase
    from novel_dev.schemas.context import ChapterPlan, BeatPlan, ChapterContext, LocationContext
    from novel_dev.repositories.chapter_repo import ChapterRepository
    import uuid

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_mcp_draft_{suffix}"
    chapter_id = f"c_{suffix}"
    volume_id = f"v_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        director = NovelDirector(session=session)
        chapter_plan = ChapterPlan(
            chapter_number=1,
            title="Draft Test",
            target_word_count=3000,
            beats=[BeatPlan(summary="B1", target_mood="tense")],
        )
        context = ChapterContext(
            chapter_plan=chapter_plan,
            style_profile={},
            worldview_summary="",
            active_entities=[],
            location_context=LocationContext(current=""),
            timeline_events=[],
            pending_foreshadowings=[],
        )
        await director.save_checkpoint(
            novel_id,
            phase=Phase.DRAFTING,
            checkpoint_data={"chapter_context": context.model_dump()},
            volume_id=volume_id,
            chapter_id=chapter_id,
        )
        await ChapterRepository(session).create(chapter_id, volume_id, 1, "Draft Test")
        await session.commit()

    result = await mcp.tools["generate_chapter_draft"](novel_id, chapter_id)
    assert "total_words" in result
    assert result["total_words"] > 0
    assert len(result["beat_coverage"]) == 1


@pytest.mark.asyncio
async def test_mcp_get_chapter_draft_status():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.agents.director import NovelDirector, Phase
    from novel_dev.repositories.chapter_repo import ChapterRepository
    import uuid

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_mcp_status_{suffix}"
    chapter_id = f"c_{suffix}"
    volume_id = f"v_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        director = NovelDirector(session=session)
        await director.save_checkpoint(
            novel_id,
            phase=Phase.DRAFTING,
            checkpoint_data={
                "drafting_progress": {"beat_index": 1, "total_beats": 3},
                "draft_metadata": {"total_words": 100},
            },
            volume_id=volume_id,
            chapter_id=chapter_id,
        )
        await ChapterRepository(session).create(chapter_id, volume_id, 1, "Status Test")
        await session.commit()

    result = await mcp.tools["get_chapter_draft_status"](novel_id, chapter_id)
    assert result["chapter_id"] == chapter_id
    assert result["status"] is not None
    assert result["drafting_progress"]["beat_index"] == 1
    assert result["draft_metadata"]["total_words"] == 100
