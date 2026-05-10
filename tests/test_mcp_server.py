import uuid
import pytest

from novel_dev.mcp_server.server import internal_mcp_registry, mcp


def test_mcp_server_has_tools():
    expected = {
        "query_entity",
        "get_active_foreshadowings",
        "get_timeline",
        "get_spaceline_chain",
        "get_novel_state",
        "get_novel_documents",
        "search_domain_documents",
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
        "get_novel_document_full",
        "save_brainstorm_draft",
        "confirm_brainstorm",
    }
    assert set(mcp._tool_manager._tools.keys()) == expected


def test_mcp_internal_registry_reuses_external_tool_functions():
    entry = internal_mcp_registry.get("get_novel_state")
    assert entry is not None
    assert entry.fn is mcp._tool_manager._tools["get_novel_state"].fn
    assert entry.read_only is True

    write_entry = internal_mcp_registry.get("upload_document")
    assert write_entry is not None
    assert write_entry.fn is mcp._tool_manager._tools["upload_document"].fn
    assert write_entry.read_only is False


@pytest.mark.asyncio
async def test_mcp_query_entity_returns_entity_details_and_relationships():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.repositories.relationship_repo import RelationshipRepository
    from novel_dev.services.entity_service import EntityService

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_entity_query_{suffix}"
    source_id = f"ent_source_{suffix}"
    target_id = f"ent_target_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        svc = EntityService(session)
        await svc.create_entity(
            source_id,
            "character",
            "陆照",
            novel_id=novel_id,
            initial_state={
                "境界": "蕴气",
                "_merged_duplicate_entities": [{"entity_id": f"ent_old_{suffix}", "name": "旧陆照"}],
            },
            use_llm_for_classification=False,
        )
        await svc.create_entity(
            target_id,
            "item",
            "道种",
            novel_id=novel_id,
            initial_state={"状态": "未觉醒"},
            use_llm_for_classification=False,
        )
        await RelationshipRepository(session).create(
            source_id,
            target_id,
            "持有",
            novel_id=novel_id,
        )
        await session.commit()

    result = await mcp._tool_manager._tools["query_entity"].fn(entity_id=source_id, novel_id=novel_id)

    assert result["entity_id"] == source_id
    assert result["name"] == "陆照"
    assert result["type"] == "character"
    assert result["state"]["境界"] == "蕴气"
    assert "_merged_duplicate_entities" not in result["state"]
    assert f"ent_old_{suffix}" not in str(result)
    assert result["relationships"][0]["target_id"] == target_id
    assert result["relationships"][0]["relation_type"] == "持有"

    mismatch = await mcp._tool_manager._tools["query_entity"].fn(entity_id=source_id, novel_id="other")
    assert mismatch["error"] == "Entity not found in novel"


@pytest.mark.asyncio
async def test_mcp_get_novel_document_full():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.repositories.document_repo import DocumentRepository

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_doc_full_{suffix}"
    content = "a" * 2000

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        doc = await DocumentRepository(session).create(
            f"d_{suffix}", novel_id, "worldview", "WV", content
        )
        await session.commit()

    result = await mcp._tool_manager._tools["get_novel_document_full"].fn(novel_id=novel_id, doc_id=doc.id)
    assert result["content"] == content
    assert result["doc_type"] == "worldview"


@pytest.mark.asyncio
async def test_mcp_search_domain_documents_filters_by_domain_and_query():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.repositories.document_repo import DocumentRepository

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_doc_search_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        repo = DocumentRepository(session)
        zhetian_doc = await repo.create(
            f"d_zhetian_{suffix}",
            novel_id,
            "domain_setting",
            "遮天 / 修炼体系",
            "四极、化龙、仙台、圣人、大圣、准帝、大帝、红尘仙。",
        )
        await repo.create(
            f"d_xian ni_{suffix}",
            novel_id,
            "domain_setting",
            "仙逆 / 修炼体系",
            "元婴、化神、婴变、问鼎、阴虚、阳实、踏天。",
        )
        await repo.create(
            f"d_perfect_{suffix}",
            novel_id,
            "domain_setting",
            "完美世界 / 修炼体系",
            "完美世界体系，正文提及遮天和红尘仙作为后续关联。",
        )
        await session.commit()

    result = await mcp._tool_manager._tools["search_domain_documents"].fn(
        novel_id=novel_id,
        domain_name="遮天",
        query="红尘仙 境界",
        doc_type="domain_setting",
    )

    assert result["documents"][0]["id"] == zhetian_doc.id
    assert result["documents"][0]["title"] == "遮天 / 修炼体系"
    assert "红尘仙" in result["documents"][0]["content_preview"]
    assert len(result["documents"]) == 1


@pytest.mark.asyncio
async def test_mcp_search_domain_documents_handles_multi_domain_abstract_realm_query():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.repositories.document_repo import DocumentRepository

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_doc_search_multi_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        repo = DocumentRepository(session)
        yangshen_doc = await repo.create(
            f"d_yangshen_{suffix}",
            novel_id,
            "domain_setting",
            "阳神 / 修炼体系",
            "武道修命体系与仙道修性体系，终极境界为彼岸。",
        )
        perfect_doc = await repo.create(
            f"d_perfect_{suffix}",
            novel_id,
            "domain_setting",
            "完美世界 / 修炼体系",
            "搬血、洞天、铭纹、尊者、真仙、仙王等境界。",
        )
        await repo.create(
            f"d_zhetian_{suffix}",
            novel_id,
            "domain_setting",
            "遮天 / 修炼体系",
            "轮海、道宫、四极、化龙、仙台。",
        )
        await session.commit()

    result = await mcp._tool_manager._tools["search_domain_documents"].fn(
        novel_id=novel_id,
        domain_name="阳神、完美世界、吞噬星空",
        query="境界映射",
        doc_type="domain_setting",
    )

    ids = [item["id"] for item in result["documents"]]
    assert yangshen_doc.id in ids
    assert perfect_doc.id in ids
    assert all("遮天" not in item["title"] for item in result["documents"])


@pytest.mark.asyncio
async def test_mcp_save_brainstorm_draft():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.agents.director import NovelDirector, Phase
    from novel_dev.schemas.outline import SynopsisData

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_draft_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        director = NovelDirector(session=session)
        await director.save_checkpoint(
            novel_id,
            phase=Phase.BRAINSTORMING,
            checkpoint_data={},
            volume_id=None,
            chapter_id=None,
        )
        await session.commit()

    synopsis = SynopsisData(
        title="T",
        logline="L",
        core_conflict="C",
        estimated_volumes=1,
        estimated_total_chapters=1,
        estimated_total_words=3000,
    )
    result = await mcp._tool_manager._tools["save_brainstorm_draft"].fn(
        novel_id=novel_id, synopsis_data=synopsis.model_dump()
    )
    assert result["saved"] is True

    async with async_session_local() as session:
        director = NovelDirector(session=session)
        state = await director.resume(novel_id)
        assert state.checkpoint_data["pending_synopsis"]["title"] == "T"


@pytest.mark.asyncio
async def test_mcp_confirm_brainstorm():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.agents.director import NovelDirector, Phase
    from novel_dev.schemas.outline import SynopsisData
    from novel_dev.repositories.document_repo import DocumentRepository

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_confirm_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        director = NovelDirector(session=session)
        await director.save_checkpoint(
            novel_id,
            phase=Phase.BRAINSTORMING,
            checkpoint_data={},
            volume_id=None,
            chapter_id=None,
        )
        await session.commit()

    synopsis = SynopsisData(
        title="T2",
        logline="L2",
        core_conflict="C2",
        estimated_volumes=1,
        estimated_total_chapters=1,
        estimated_total_words=3000,
    )
    await mcp._tool_manager._tools["save_brainstorm_draft"].fn(
        novel_id=novel_id, synopsis_data=synopsis.model_dump()
    )

    result = await mcp._tool_manager._tools["confirm_brainstorm"].fn(novel_id=novel_id)
    assert result["confirmed"] is True

    async with async_session_local() as session:
        director = NovelDirector(session=session)
        state = await director.resume(novel_id)
        assert state.current_phase == Phase.VOLUME_PLANNING.value
        assert "pending_synopsis" not in state.checkpoint_data
        docs = await DocumentRepository(session).get_by_type(novel_id, "synopsis")
        assert any(d.title == "T2" for d in docs)


@pytest.mark.asyncio
async def test_mcp_upload_document():
    result = await mcp._tool_manager._tools["upload_document"].fn("n1", "setting.txt", "世界观：天玄大陆。")
    assert result["extraction_type"] == "setting"
    assert "id" in result


@pytest.mark.asyncio
async def test_mcp_get_pending_documents():
    upload = await mcp._tool_manager._tools["upload_document"].fn("n2", "style.txt", "a" * 5000)
    result = await mcp._tool_manager._tools["get_pending_documents"].fn("n2")
    assert any(i["id"] == upload["id"] for i in result)


@pytest.mark.asyncio
async def test_mcp_list_style_profile_versions():
    novel_id = f"n3_{uuid.uuid4().hex[:8]}"
    upload = await mcp._tool_manager._tools["upload_document"].fn(novel_id, "style.txt", "x" * 10000)
    await mcp._tool_manager._tools["approve_pending_documents"].fn(upload["id"])
    result = await mcp._tool_manager._tools["list_style_profile_versions"].fn(novel_id)
    assert len(result) == 1
    assert result[0]["version"] == 1


@pytest.mark.asyncio
async def test_mcp_rollback_style_profile():
    novel_id = f"n4_{uuid.uuid4().hex[:8]}"
    upload = await mcp._tool_manager._tools["upload_document"].fn(novel_id, "style.txt", "y" * 10000)
    await mcp._tool_manager._tools["approve_pending_documents"].fn(upload["id"])
    result = await mcp._tool_manager._tools["rollback_style_profile"].fn(novel_id, 1)
    assert result["rolled_back_to_version"] == 1


@pytest.mark.asyncio
async def test_mcp_analyze_style_from_text():
    result = await mcp._tool_manager._tools["analyze_style_from_text"].fn("剑光一闪。敌人倒下。")
    assert "style_guide" in result
    assert "style_config" in result


@pytest.mark.asyncio
async def test_mcp_prepare_chapter_context(mock_llm_factory):
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

    result = await mcp._tool_manager._tools["prepare_chapter_context"].fn(novel_id, chapter_id)
    assert result["success"] is True
    assert result["chapter_plan_title"] == "MCP Test"


@pytest.mark.asyncio
async def test_mcp_generate_chapter_draft(mock_llm_factory):
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

    result = await mcp._tool_manager._tools["generate_chapter_draft"].fn(novel_id, chapter_id)
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

    result = await mcp._tool_manager._tools["get_chapter_draft_status"].fn(novel_id, chapter_id)
    assert result["chapter_id"] == chapter_id
    assert result["status"] is not None
    assert result["drafting_progress"]["beat_index"] == 1
    assert result["draft_metadata"]["total_words"] == 100


@pytest.mark.asyncio
async def test_mcp_advance_novel(mock_llm_factory):
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

    result = await mcp._tool_manager._tools["advance_novel"].fn(novel_id)
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

    result = await mcp._tool_manager._tools["get_review_result"].fn(novel_id)
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

    result = await mcp._tool_manager._tools["get_fast_review_result"].fn(novel_id)
    assert result["fast_review_score"] is not None


@pytest.mark.asyncio
async def test_mcp_brainstorm_novel(mock_llm_factory):
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

    result = await mcp._tool_manager._tools["brainstorm_novel"].fn(novel_id)
    assert result["title"] == "天玄纪元"
    assert result["estimated_volumes"] > 0


@pytest.mark.asyncio
async def test_mcp_plan_volume(mock_llm_factory):
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

    result = await mcp._tool_manager._tools["plan_volume"].fn(novel_id)
    assert result["volume_id"] == "vol_1"


@pytest.mark.asyncio
async def test_mcp_get_synopsis(mock_llm_factory):
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

    await mcp._tool_manager._tools["brainstorm_novel"].fn(novel_id)
    result = await mcp._tool_manager._tools["get_synopsis"].fn(novel_id)
    assert "content" in result
    assert "synopsis_data" in result


@pytest.mark.asyncio
async def test_mcp_get_volume_plan(mock_llm_factory):
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

    await mcp._tool_manager._tools["plan_volume"].fn(novel_id)
    result = await mcp._tool_manager._tools["get_volume_plan"].fn(novel_id)
    assert result["volume_id"] == "vol_1"


@pytest.mark.asyncio
async def test_mcp_run_librarian(tmp_path, monkeypatch):
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
    monkeypatch.setattr("novel_dev.agents.director.settings.data_dir", str(tmp_path))

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
        await ChapterRepository(session).create(chapter_id, volume_id, 1, "MCP Lib", novel_id=novel_id)
        await ChapterRepository(session).update_text(chapter_id, polished_text="abc")
        await session.commit()

    with patch("novel_dev.agents.librarian.LibrarianAgent._call_llm", new_callable=AsyncMock, return_value='{}'):
        result = await mcp._tool_manager._tools["run_librarian"].fn(novel_id)
    assert result["current_phase"] == Phase.VOLUME_PLANNING.value


@pytest.mark.asyncio
async def test_mcp_export_novel(tmp_path, monkeypatch):
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.repositories.chapter_repo import ChapterRepository

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_mcp_exp_{suffix}"
    chapter_id = f"c_{suffix}"
    volume_id = f"v_{suffix}"
    monkeypatch.setattr("novel_dev.mcp_server.server.settings.data_dir", str(tmp_path))

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        await ChapterRepository(session).create(chapter_id, volume_id, 1, "MCP Exp", novel_id=novel_id)
        await ChapterRepository(session).update_text(chapter_id, polished_text="export me")
        await ChapterRepository(session).update_status(chapter_id, "archived")
        await session.commit()

    result = await mcp._tool_manager._tools["export_novel"].fn(novel_id, "md")
    assert "exported_path" in result
    assert result["format"] == "md"
    assert "export me" in (tmp_path / "novels" / novel_id / "exports" / "novel.md").read_text(encoding="utf-8")


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

    result = await mcp._tool_manager._tools["get_archive_stats"].fn(novel_id)
    assert result["total_word_count"] == 42
    assert result["archived_chapter_count"] == 1
    assert result["avg_word_count"] == 0
