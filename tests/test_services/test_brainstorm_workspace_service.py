import pytest
from unittest.mock import AsyncMock

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.agents.file_classifier import FileClassificationResult
from novel_dev.repositories.brainstorm_workspace_repo import BrainstormWorkspaceRepository
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.pending_extraction_repo import PendingExtractionRepository
from novel_dev.services.brainstorm_workspace_service import BrainstormWorkspaceService


@pytest.mark.asyncio
async def test_brainstorm_workspace_save_outline_draft_persists_workspace_authority(async_session):
    service = BrainstormWorkspaceService(async_session)

    await service.save_outline_draft(
        novel_id="novel_ws",
        outline_type="synopsis",
        outline_ref="synopsis",
        result_snapshot={"title": "九霄行", "logline": "逆势而上"},
    )

    payload = await service.get_workspace_payload("novel_ws")

    assert payload.novel_id == "novel_ws"
    assert payload.outline_drafts["synopsis:synopsis"]["title"] == "九霄行"


@pytest.mark.asyncio
async def test_brainstorm_workspace_merge_setting_drafts_upserts_and_orders(async_session):
    service = BrainstormWorkspaceService(async_session)

    await service.merge_setting_drafts(
        "novel_ws_merge",
        [
            {
                "draft_id": "draft_b",
                "source_outline_ref": "synopsis",
                "source_kind": "power_system",
                "target_import_mode": "explicit_type",
                "target_doc_type": "setting",
                "title": "修炼体系",
                "content": "炼体、筑基、金丹三阶。",
                "order_index": 20,
            },
            {
                "draft_id": "draft_a",
                "source_outline_ref": "synopsis",
                "source_kind": "character",
                "target_import_mode": "explicit_type",
                "target_doc_type": "concept",
                "title": "林风",
                "content": "外门弟子。",
                "order_index": 10,
            },
        ],
    )

    drafts = await service.merge_setting_drafts(
        "novel_ws_merge",
        [
            {
                "draft_id": "draft_a",
                "source_outline_ref": "synopsis",
                "source_kind": "character",
                "target_import_mode": "explicit_type",
                "target_doc_type": "concept",
                "title": "林风",
                "content": "青云宗外门弟子。",
                "order_index": 1,
            }
        ],
    )

    assert [draft.draft_id for draft in drafts] == ["draft_a", "draft_b"]
    assert drafts[0].content == "青云宗外门弟子。"


@pytest.mark.asyncio
async def test_brainstorm_workspace_merge_setting_drafts_rejects_unsupported_explicit_combination(async_session):
    service = BrainstormWorkspaceService(async_session)

    with pytest.raises(ValueError, match="Explicit faction drafts are not supported"):
        await service.merge_setting_drafts(
            "novel_ws_invalid",
            [
                {
                    "draft_id": "draft_faction",
                    "source_outline_ref": "synopsis",
                    "source_kind": "faction",
                    "target_import_mode": "explicit_type",
                    "target_doc_type": "setting",
                    "title": "青云宗",
                    "content": "宗门势力覆盖北境。",
                    "order_index": 1,
                }
            ],
        )


@pytest.mark.asyncio
async def test_brainstorm_workspace_merge_setting_drafts_revalidates_existing_entries(async_session):
    service = BrainstormWorkspaceService(async_session)
    workspace_repo = BrainstormWorkspaceRepository(async_session)

    workspace = await workspace_repo.get_or_create("novel_ws_legacy")
    workspace.setting_docs_draft = [
        {
            "draft_id": "draft_legacy",
            "source_outline_ref": "synopsis",
            "source_kind": "faction",
            "target_import_mode": "explicit_type",
            "target_doc_type": "setting",
            "title": "青云宗",
            "content": "宗门势力覆盖北境。",
            "order_index": 5,
        }
    ]
    await async_session.flush()

    with pytest.raises(ValueError, match="Explicit faction drafts are not supported"):
        await service.merge_setting_drafts(
            "novel_ws_legacy",
            [
                {
                    "draft_id": "draft_new",
                    "source_outline_ref": "synopsis",
                    "source_kind": "character",
                    "target_import_mode": "explicit_type",
                    "target_doc_type": "concept",
                    "title": "林风",
                    "content": "青云宗外门弟子。",
                    "order_index": 1,
                }
            ],
        )


@pytest.mark.asyncio
async def test_brainstorm_workspace_submit_workspace_materializes_synopsis_and_pending_settings(async_session):
    director = NovelDirector(async_session)
    await director.save_checkpoint(
        "novel_submit",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )

    service = BrainstormWorkspaceService(async_session)
    workspace = await service.get_workspace_payload("novel_submit")

    await service.save_outline_draft(
        novel_id="novel_submit",
        outline_type="synopsis",
        outline_ref="synopsis",
        result_snapshot={
            "title": "九霄行",
            "logline": "林风为改命踏上逆势而上的修行路。",
            "core_conflict": "林风 vs 掌控宗门命脉的长老会",
            "themes": ["成长"],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 2,
            "estimated_total_chapters": 200,
            "estimated_total_words": 600000,
        },
    )
    await service.save_outline_draft(
        novel_id="novel_submit",
        outline_type="volume",
        outline_ref="vol_1",
        result_snapshot={"title": "第一卷"},
    )
    await service.save_outline_draft(
        novel_id="novel_submit",
        outline_type="volume",
        outline_ref="vol_2",
        result_snapshot={"title": "第二卷"},
    )
    await service.merge_setting_drafts(
        "novel_submit",
        [
            {
                "draft_id": "draft_1",
                "source_outline_ref": "synopsis",
                "source_kind": "character",
                "target_import_mode": "explicit_type",
                "target_doc_type": "concept",
                "title": "林风",
                "content": "青云宗外门弟子，背负血仇。",
                "order_index": 1,
            }
        ],
    )

    result = await service.submit_workspace("novel_submit")

    docs = await DocumentRepository(async_session).get_by_type("novel_submit", "synopsis")
    state = await NovelStateRepository(async_session).get_state("novel_submit")
    pending = await PendingExtractionRepository(async_session).list_by_novel("novel_submit")
    workspace_repo = BrainstormWorkspaceRepository(async_session)
    submitted_workspace = await workspace_repo.get_by_id(workspace.workspace_id)

    assert result.synopsis_title == "九霄行"
    assert result.pending_setting_count == 1
    assert result.volume_outline_count == 2
    assert len(docs) == 1
    assert docs[0].title == "九霄行"
    assert state.current_phase == "volume_planning"
    assert state.checkpoint_data["synopsis_data"]["title"] == "九霄行"
    assert state.checkpoint_data["submitted_volume_outline_drafts"] == [
        {
            "outline_ref": "vol_1",
            "outline_key": "volume:vol_1",
            "snapshot": {"title": "第一卷"},
        },
        {
            "outline_ref": "vol_2",
            "outline_key": "volume:vol_2",
            "snapshot": {"title": "第二卷"},
        }
    ]
    assert len(pending) == 1
    assert pending[0].status == "pending"
    assert pending[0].source_filename == "brainstorm-synopsis-draft_1.md"
    assert await workspace_repo.get_active_by_novel("novel_submit") is None
    assert submitted_workspace is not None
    assert submitted_workspace.status == "submitted"


@pytest.mark.asyncio
async def test_brainstorm_workspace_submit_workspace_allows_submission_with_synopsis_only(
    async_session,
):
    director = NovelDirector(async_session)
    await director.save_checkpoint(
        "novel_submit_synopsis_only",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )

    service = BrainstormWorkspaceService(async_session)
    await service.save_outline_draft(
        novel_id="novel_submit_synopsis_only",
        outline_type="synopsis",
        outline_ref="synopsis",
        result_snapshot={
            "title": "九霄行",
            "logline": "林风为改命踏上逆势而上的修行路。",
            "core_conflict": "林风 vs 掌控宗门命脉的长老会",
            "themes": ["成长"],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 7,
            "estimated_total_chapters": 200,
            "estimated_total_words": 600000,
        },
    )

    result = await service.submit_workspace("novel_submit_synopsis_only")

    state = await NovelStateRepository(async_session).get_state("novel_submit_synopsis_only")

    assert result.synopsis_title == "九霄行"
    assert result.pending_setting_count == 0
    assert result.volume_outline_count == 0
    assert state.current_phase == "volume_planning"
    assert state.checkpoint_data["submitted_volume_outline_drafts"] == []


@pytest.mark.asyncio
async def test_brainstorm_workspace_submit_workspace_requires_novel_state(async_session):
    service = BrainstormWorkspaceService(async_session)
    workspace_repo = BrainstormWorkspaceRepository(async_session)

    workspace = await service.get_workspace_payload("novel_submit_missing_state")
    await service.save_outline_draft(
        novel_id="novel_submit_missing_state",
        outline_type="synopsis",
        outline_ref="synopsis",
        result_snapshot={
            "title": "九霄行",
            "logline": "林风为改命踏上逆势而上的修行路。",
            "core_conflict": "林风 vs 掌控宗门命脉的长老会",
            "themes": ["成长"],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 2,
            "estimated_total_chapters": 200,
            "estimated_total_words": 600000,
        },
    )
    await service.save_outline_draft(
        novel_id="novel_submit_missing_state",
        outline_type="volume",
        outline_ref="vol_1",
        result_snapshot={"title": "第一卷"},
    )
    await service.merge_setting_drafts(
        "novel_submit_missing_state",
        [
            {
                "draft_id": "draft_1",
                "source_outline_ref": "synopsis",
                "source_kind": "character",
                "target_import_mode": "explicit_type",
                "target_doc_type": "concept",
                "title": "林风",
                "content": "青云宗外门弟子，背负血仇。",
                "order_index": 1,
            }
        ],
    )

    with pytest.raises(ValueError, match="Novel state not found for brainstorm submission"):
        await service.submit_workspace("novel_submit_missing_state")

    docs = await DocumentRepository(async_session).get_by_type(
        "novel_submit_missing_state",
        "synopsis",
    )
    state = await NovelStateRepository(async_session).get_state("novel_submit_missing_state")
    pending = await PendingExtractionRepository(async_session).list_by_novel(
        "novel_submit_missing_state"
    )
    active_workspace = await workspace_repo.get_active_by_novel("novel_submit_missing_state")
    submitted_workspace = await workspace_repo.get_by_id(workspace.workspace_id)

    assert docs == []
    assert state is None
    assert pending == []
    assert active_workspace is not None
    assert active_workspace.status == "active"
    assert submitted_workspace is not None
    assert submitted_workspace.status == "active"


@pytest.mark.asyncio
async def test_brainstorm_workspace_submit_workspace_requires_brainstorming_phase(async_session):
    director = NovelDirector(async_session)
    await director.save_checkpoint(
        "novel_submit_wrong_phase",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={"existing": "checkpoint"},
        volume_id="vol_existing",
        chapter_id=None,
    )

    service = BrainstormWorkspaceService(async_session)
    workspace = await service.get_workspace_payload("novel_submit_wrong_phase")
    await service.save_outline_draft(
        novel_id="novel_submit_wrong_phase",
        outline_type="synopsis",
        outline_ref="synopsis",
        result_snapshot={
            "title": "九霄行",
            "logline": "林风为改命踏上逆势而上的修行路。",
            "core_conflict": "林风 vs 掌控宗门命脉的长老会",
            "themes": ["成长"],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 2,
            "estimated_total_chapters": 200,
            "estimated_total_words": 600000,
        },
    )
    await service.save_outline_draft(
        novel_id="novel_submit_wrong_phase",
        outline_type="volume",
        outline_ref="vol_1",
        result_snapshot={"title": "第一卷"},
    )
    await service.merge_setting_drafts(
        "novel_submit_wrong_phase",
        [
            {
                "draft_id": "draft_1",
                "source_outline_ref": "synopsis",
                "source_kind": "character",
                "target_import_mode": "explicit_type",
                "target_doc_type": "concept",
                "title": "林风",
                "content": "青云宗外门弟子，背负血仇。",
                "order_index": 1,
            }
        ],
    )

    with pytest.raises(
        ValueError,
        match="Brainstorm workspace can only be submitted during the brainstorming phase",
    ):
        await service.submit_workspace("novel_submit_wrong_phase")

    docs = await DocumentRepository(async_session).get_by_type(
        "novel_submit_wrong_phase",
        "synopsis",
    )
    state = await NovelStateRepository(async_session).get_state("novel_submit_wrong_phase")
    pending = await PendingExtractionRepository(async_session).list_by_novel(
        "novel_submit_wrong_phase"
    )
    workspace_repo = BrainstormWorkspaceRepository(async_session)
    active_workspace = await workspace_repo.get_active_by_novel("novel_submit_wrong_phase")
    submitted_workspace = await workspace_repo.get_by_id(workspace.workspace_id)

    assert docs == []
    assert state.current_phase == "volume_planning"
    assert state.checkpoint_data == {"existing": "checkpoint"}
    assert pending == []
    assert active_workspace is not None
    assert active_workspace.status == "active"
    assert submitted_workspace is not None
    assert submitted_workspace.status == "active"


@pytest.mark.asyncio
async def test_brainstorm_workspace_submit_workspace_prevalidates_drafts_before_writes(async_session):
    director = NovelDirector(async_session)
    await director.save_checkpoint(
        "novel_submit_invalid",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )

    service = BrainstormWorkspaceService(async_session)
    await service.save_outline_draft(
        novel_id="novel_submit_invalid",
        outline_type="synopsis",
        outline_ref="synopsis",
        result_snapshot={
            "title": "九霄行",
            "logline": "林风为改命踏上逆势而上的修行路。",
            "core_conflict": "林风 vs 掌控宗门命脉的长老会",
            "themes": ["成长"],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 2,
            "estimated_total_chapters": 200,
            "estimated_total_words": 600000,
        },
    )
    await service.save_outline_draft(
        novel_id="novel_submit_invalid",
        outline_type="volume",
        outline_ref="vol_1",
        result_snapshot={"title": "第一卷"},
    )
    await service.save_outline_draft(
        novel_id="novel_submit_invalid",
        outline_type="volume",
        outline_ref="vol_2",
        result_snapshot={"title": "第二卷"},
    )

    workspace_repo = BrainstormWorkspaceRepository(async_session)
    workspace = await workspace_repo.get_active_by_novel("novel_submit_invalid")
    workspace.setting_docs_draft = [
        {
            "draft_id": "draft_bad",
            "source_outline_ref": "synopsis",
            "source_kind": "faction",
            "target_import_mode": "explicit_type",
            "target_doc_type": "setting",
            "title": "青云宗",
            "content": "宗门势力覆盖北境。",
            "order_index": 1,
        }
    ]
    await async_session.flush()

    with pytest.raises(ValueError, match="Explicit faction drafts are not supported"):
        await service.submit_workspace("novel_submit_invalid")

    docs = await DocumentRepository(async_session).get_by_type("novel_submit_invalid", "synopsis")
    state = await NovelStateRepository(async_session).get_state("novel_submit_invalid")
    pending = await PendingExtractionRepository(async_session).list_by_novel("novel_submit_invalid")
    active_workspace = await workspace_repo.get_active_by_novel("novel_submit_invalid")

    assert docs == []
    assert state.current_phase == "brainstorming"
    assert state.checkpoint_data == {}
    assert pending == []
    assert active_workspace is not None
    assert active_workspace.status == "active"


@pytest.mark.asyncio
async def test_brainstorm_workspace_submit_workspace_auto_classify_failure_aborts_before_writes(
    async_session,
):
    director = NovelDirector(async_session)
    await director.save_checkpoint(
        "novel_submit_auto_invalid",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )

    service = BrainstormWorkspaceService(async_session)
    await service.save_outline_draft(
        novel_id="novel_submit_auto_invalid",
        outline_type="synopsis",
        outline_ref="synopsis",
        result_snapshot={
            "title": "九霄行",
            "logline": "林风为改命踏上逆势而上的修行路。",
            "core_conflict": "林风 vs 掌控宗门命脉的长老会",
            "themes": ["成长"],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 2,
            "estimated_total_chapters": 200,
            "estimated_total_words": 600000,
        },
    )
    await service.save_outline_draft(
        novel_id="novel_submit_auto_invalid",
        outline_type="volume",
        outline_ref="vol_1",
        result_snapshot={"title": "第一卷"},
    )
    await service.save_outline_draft(
        novel_id="novel_submit_auto_invalid",
        outline_type="volume",
        outline_ref="vol_2",
        result_snapshot={"title": "第二卷"},
    )
    await service.merge_setting_drafts(
        "novel_submit_auto_invalid",
        [
            {
                "draft_id": "draft_auto_bad",
                "source_outline_ref": "synopsis",
                "source_kind": "setting",
                "target_import_mode": "auto_classify",
                "title": "宗门制度",
                "content": "内外门泾渭分明。",
                "order_index": 1,
            }
        ],
    )

    service.extraction_service.classifier.classify = AsyncMock(
        return_value=FileClassificationResult(
            file_type="setting",
            confidence=0.95,
            reason="mock",
        )
    )
    service.extraction_service.setting_agent.extract = AsyncMock(
        side_effect=ValueError("auto classify failed")
    )

    workspace_repo = BrainstormWorkspaceRepository(async_session)

    with pytest.raises(ValueError, match="auto classify failed"):
        await service.submit_workspace("novel_submit_auto_invalid")

    docs = await DocumentRepository(async_session).get_by_type(
        "novel_submit_auto_invalid",
        "synopsis",
    )
    state = await NovelStateRepository(async_session).get_state("novel_submit_auto_invalid")
    pending = await PendingExtractionRepository(async_session).list_by_novel(
        "novel_submit_auto_invalid"
    )
    active_workspace = await workspace_repo.get_active_by_novel("novel_submit_auto_invalid")

    assert docs == []
    assert state.current_phase == "brainstorming"
    assert state.checkpoint_data == {}
    assert pending == []
    assert active_workspace is not None
    assert active_workspace.status == "active"
