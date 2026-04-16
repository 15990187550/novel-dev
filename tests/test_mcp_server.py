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
        "advance_novel",
        "get_review_result",
        "get_fast_review_result",
        "brainstorm_novel",
        "plan_volume",
        "get_synopsis",
        "get_volume_plan",
        "run_librarian",
        "export_novel",
        "get_archive_stats",
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


@pytest.mark.asyncio
async def test_mcp_advance_novel():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.agents.director import NovelDirector, Phase
    from novel_dev.schemas.context import ChapterPlan, BeatPlan, ChapterContext, LocationContext
    from novel_dev.repositories.chapter_repo import ChapterRepository
    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_mcp_adv_{suffix}"
    chapter_id = f"c_{suffix}"
    volume_id = f"v_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        director = NovelDirector(session=session)
        plan = ChapterPlan(
            chapter_number=1,
            title="MCP Adv",
            target_word_count=3000,
            beats=[BeatPlan(summary="B1", target_mood="tense")],
        )
        context = ChapterContext(
            chapter_plan=plan,
            style_profile={},
            worldview_summary="",
            active_entities=[],
            location_context=LocationContext(current=""),
            timeline_events=[],
            pending_foreshadowings=[],
        )
        await director.save_checkpoint(
            novel_id,
            phase=Phase.REVIEWING,
            checkpoint_data={"chapter_context": context.model_dump()},
            volume_id=volume_id,
            chapter_id=chapter_id,
        )
        await ChapterRepository(session).create(chapter_id, volume_id, 1, "MCP Adv")
        await ChapterRepository(session).update_text(chapter_id, raw_draft="a" * 100)
        await session.commit()

    result = await mcp.tools["advance_novel"](novel_id)
    assert result["current_phase"] == Phase.EDITING.value


@pytest.mark.asyncio
async def test_mcp_get_review_result():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.agents.director import NovelDirector, Phase
    from novel_dev.schemas.context import ChapterPlan, BeatPlan, ChapterContext, LocationContext
    from novel_dev.repositories.chapter_repo import ChapterRepository

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_mcp_review_{suffix}"
    chapter_id = f"c_{suffix}"
    volume_id = f"v_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        director = NovelDirector(session=session)
        plan = ChapterPlan(
            chapter_number=1,
            title="MCP Review",
            target_word_count=3000,
            beats=[BeatPlan(summary="B1", target_mood="tense")],
        )
        context = ChapterContext(
            chapter_plan=plan,
            style_profile={},
            worldview_summary="",
            active_entities=[],
            location_context=LocationContext(current=""),
            timeline_events=[],
            pending_foreshadowings=[],
        )
        await director.save_checkpoint(
            novel_id,
            phase=Phase.REVIEWING,
            checkpoint_data={"chapter_context": context.model_dump()},
            volume_id=volume_id,
            chapter_id=chapter_id,
        )
        await ChapterRepository(session).create(chapter_id, volume_id, 1, "MCP Review")
        await ChapterRepository(session).update_scores(
            chapter_id,
            overall=85,
            breakdown={"plot": 90, "character": 80},
            feedback={"strengths": ["good pacing"], "weaknesses": []},
        )
        await session.commit()

    result = await mcp.tools["get_review_result"](novel_id)
    assert result["score_overall"] is not None


@pytest.mark.asyncio
async def test_mcp_get_fast_review_result():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.agents.director import NovelDirector, Phase
    from novel_dev.schemas.context import ChapterPlan, BeatPlan, ChapterContext, LocationContext
    from novel_dev.repositories.chapter_repo import ChapterRepository

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_mcp_fast_{suffix}"
    chapter_id = f"c_{suffix}"
    volume_id = f"v_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        director = NovelDirector(session=session)
        plan = ChapterPlan(
            chapter_number=1,
            title="MCP Fast Review",
            target_word_count=3000,
            beats=[BeatPlan(summary="B1", target_mood="tense")],
        )
        context = ChapterContext(
            chapter_plan=plan,
            style_profile={},
            worldview_summary="",
            active_entities=[],
            location_context=LocationContext(current=""),
            timeline_events=[],
            pending_foreshadowings=[],
        )
        await director.save_checkpoint(
            novel_id,
            phase=Phase.FAST_REVIEWING,
            checkpoint_data={"chapter_context": context.model_dump()},
            volume_id=volume_id,
            chapter_id=chapter_id,
        )
        await ChapterRepository(session).create(chapter_id, volume_id, 1, "MCP Fast Review")
        await ChapterRepository(session).update_fast_review(
            chapter_id,
            score=78,
            feedback={"summary": "decent", "issues": []},
        )
        await session.commit()

    result = await mcp.tools["get_fast_review_result"](novel_id)
    assert result["fast_review_score"] is not None


@pytest.mark.asyncio
async def test_mcp_brainstorm_novel():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.repositories.document_repo import DocumentRepository

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_mcp_brain_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        await DocumentRepository(session).create(
            f"d_{suffix}", novel_id, "worldview", "WV", "天玄大陆"
        )
        await session.commit()

    result = await mcp.tools["brainstorm_novel"](novel_id)
    assert result["title"] == "天玄纪元"
    assert result["estimated_volumes"] > 0


@pytest.mark.asyncio
async def test_mcp_plan_volume():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.agents.director import NovelDirector, Phase
    from novel_dev.schemas.outline import SynopsisData
    from novel_dev.repositories.document_repo import DocumentRepository

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_mcp_plan_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        await DocumentRepository(session).create(
            f"d_{suffix}", novel_id, "worldview", "WV", "大陆"
        )
        director = NovelDirector(session=session)
        synopsis = SynopsisData(
            title="T", logline="L", core_conflict="C",
            estimated_volumes=1, estimated_total_chapters=1, estimated_total_words=3000,
        )
        await director.save_checkpoint(
            novel_id,
            phase=Phase.VOLUME_PLANNING,
            checkpoint_data={"synopsis_data": synopsis.model_dump()},
            volume_id=None,
            chapter_id=None,
        )
        await session.commit()

    result = await mcp.tools["plan_volume"](novel_id)
    assert result["volume_id"] == "vol_1"


@pytest.mark.asyncio
async def test_mcp_get_synopsis():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.repositories.document_repo import DocumentRepository

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_mcp_syn_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        await DocumentRepository(session).create(
            f"d_{suffix}", novel_id, "worldview", "WV", "大陆"
        )
        await session.commit()

    await mcp.tools["brainstorm_novel"](novel_id)
    result = await mcp.tools["get_synopsis"](novel_id)
    assert "content" in result
    assert "synopsis_data" in result


@pytest.mark.asyncio
async def test_mcp_get_volume_plan():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.agents.director import NovelDirector, Phase
    from novel_dev.schemas.outline import SynopsisData
    from novel_dev.repositories.document_repo import DocumentRepository

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_mcp_vp_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        await DocumentRepository(session).create(
            f"d_{suffix}", novel_id, "worldview", "WV", "大陆"
        )
        director = NovelDirector(session=session)
        synopsis = SynopsisData(
            title="T", logline="L", core_conflict="C",
            estimated_volumes=1, estimated_total_chapters=1, estimated_total_words=3000,
        )
        await director.save_checkpoint(
            novel_id,
            phase=Phase.VOLUME_PLANNING,
            checkpoint_data={"synopsis_data": synopsis.model_dump()},
            volume_id=None,
            chapter_id=None,
        )
        await session.commit()

    await mcp.tools["plan_volume"](novel_id)
    result = await mcp.tools["get_volume_plan"](novel_id)
    assert result["volume_id"] == "vol_1"


@pytest.mark.asyncio
async def test_mcp_run_librarian():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.agents.director import NovelDirector, Phase
    from novel_dev.repositories.chapter_repo import ChapterRepository
    from novel_dev.schemas.context import ChapterPlan, BeatPlan
    from unittest.mock import patch, AsyncMock

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_mcp_lib_{suffix}"
    chapter_id = f"c_{suffix}"
    volume_id = f"v_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        director = NovelDirector(session=session)
        plan = ChapterPlan(chapter_number=1, title="MCP Lib", target_word_count=3000, beats=[BeatPlan(summary="B1", target_mood="tense")]).model_dump()
        plan["chapter_id"] = chapter_id
        await director.save_checkpoint(
            novel_id,
            phase=Phase.LIBRARIAN,
            checkpoint_data={"current_volume_plan": {"chapters": [plan]}},
            volume_id=volume_id,
            chapter_id=chapter_id,
        )
        await ChapterRepository(session).create(chapter_id, volume_id, 1, "MCP Lib")
        await ChapterRepository(session).update_text(chapter_id, polished_text="abc")
        await session.commit()

    with patch("novel_dev.agents.librarian.LibrarianAgent._call_llm", new_callable=AsyncMock, return_value='{}'):
        result = await mcp.tools["run_librarian"](novel_id)
    assert result["current_phase"] == Phase.VOLUME_PLANNING.value


@pytest.mark.asyncio
async def test_mcp_export_novel():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.repositories.chapter_repo import ChapterRepository

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_mcp_exp_{suffix}"
    chapter_id = f"c_{suffix}"
    volume_id = f"v_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        await ChapterRepository(session).create(chapter_id, volume_id, 1, "MCP Exp")
        await ChapterRepository(session).update_text(chapter_id, polished_text="export me")
        await ChapterRepository(session).update_status(chapter_id, "archived")
        await session.commit()

    result = await mcp.tools["export_novel"](novel_id, "md")
    assert "exported_path" in result
    assert result["format"] == "md"


@pytest.mark.asyncio
async def test_mcp_get_archive_stats():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.agents.director import NovelDirector, Phase

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_mcp_stats_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        director = NovelDirector(session=session)
        await director.save_checkpoint(
            novel_id,
            phase=Phase.COMPLETED,
            checkpoint_data={"archive_stats": {"total_word_count": 42, "archived_chapter_count": 1}},
        )
        await session.commit()

    result = await mcp.tools["get_archive_stats"](novel_id)
    assert result["total_word_count"] == 42
    assert result["archived_chapter_count"] == 1
    assert result["avg_word_count"] == 0
