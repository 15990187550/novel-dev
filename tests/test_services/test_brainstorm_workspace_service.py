import pytest
from unittest.mock import AsyncMock

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.agents.file_classifier import FileClassificationResult
from novel_dev.repositories.brainstorm_workspace_repo import BrainstormWorkspaceRepository
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.pending_extraction_repo import PendingExtractionRepository
from novel_dev.repositories.relationship_repo import RelationshipRepository
from novel_dev.services.brainstorm_workspace_service import BrainstormWorkspaceService
from novel_dev.services.entity_service import EntityService


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
async def test_merge_suggestion_cards_upserts_by_merge_key(async_session):
    service = BrainstormWorkspaceService(async_session)

    await service.merge_suggestion_cards(
        "novel_merge_cards",
        [
            {
                "operation": "upsert",
                "card_id": "card_old",
                "card_type": "character",
                "merge_key": "character:lu-zhao",
                "title": "陆照",
                "summary": "主角初版建议",
                "status": "active",
                "source_outline_refs": ["synopsis"],
                "payload": {"canonical_name": "陆照", "goal": "改命"},
                "display_order": 10,
            }
        ],
    )

    cards = await service.merge_suggestion_cards(
        "novel_merge_cards",
        [
            {
                "operation": "upsert",
                "card_id": "card_new",
                "card_type": "character",
                "merge_key": "character:lu-zhao",
                "title": "陆照",
                "summary": "补充主角资源",
                "status": "active",
                "source_outline_refs": ["vol_1"],
                "payload": {
                    "canonical_name": "陆照",
                    "goal": "改命",
                    "resources": "祖传黑刀",
                },
                "display_order": 10,
            }
        ],
    )

    assert len(cards) == 1
    assert cards[0].summary == "补充主角资源"
    assert cards[0].source_outline_refs == ["synopsis", "vol_1"]
    assert cards[0].payload["resources"] == "祖传黑刀"


@pytest.mark.asyncio
async def test_merge_suggestion_cards_marks_superseded_cards(async_session):
    service = BrainstormWorkspaceService(async_session)

    await service.merge_suggestion_cards(
        "novel_supersede_cards",
        [
            {
                "operation": "upsert",
                "card_id": "card_faction",
                "card_type": "faction",
                "merge_key": "faction:tian-xing-zong",
                "title": "天刑宗",
                "summary": "旧版设定",
                "status": "active",
                "source_outline_refs": ["synopsis"],
                "payload": {"canonical_name": "天刑宗", "position": "铁板一块"},
                "display_order": 20,
            },
            {
                "operation": "supersede",
                "merge_key": "faction:tian-xing-zong",
            },
        ],
    )

    payload = await service.get_workspace_payload("novel_supersede_cards")
    assert payload.setting_suggestion_cards[0].status == "superseded"


@pytest.mark.asyncio
async def test_merge_suggestion_cards_preserves_existing_payload_keys(async_session):
    service = BrainstormWorkspaceService(async_session)

    await service.merge_suggestion_cards(
        "novel_payload_merge_cards",
        [
            {
                "operation": "upsert",
                "card_id": "card_seed",
                "card_type": "character",
                "merge_key": "character:lu-zhao",
                "title": "陆照",
                "summary": "主角初版建议",
                "status": "active",
                "source_outline_refs": ["synopsis"],
                "payload": {"canonical_name": "陆照", "goal": "改命", "trait": "谨慎"},
                "display_order": 10,
            }
        ],
    )

    cards = await service.merge_suggestion_cards(
        "novel_payload_merge_cards",
        [
            {
                "operation": "upsert",
                "card_id": "card_delta",
                "card_type": "character",
                "merge_key": "character:lu-zhao",
                "title": "陆照",
                "summary": "补充主角资源",
                "status": "active",
                "source_outline_refs": ["vol_1"],
                "payload": {"resources": "祖传黑刀"},
                "display_order": 10,
            }
        ],
    )

    assert cards[0].payload == {
        "canonical_name": "陆照",
        "goal": "改命",
        "trait": "谨慎",
        "resources": "祖传黑刀",
    }


@pytest.mark.asyncio
async def test_merge_suggestion_cards_preserves_display_order_when_omitted(async_session):
    service = BrainstormWorkspaceService(async_session)

    await service.merge_suggestion_cards(
        "novel_card_order_preserve",
        [
            {
                "operation": "upsert",
                "card_id": "card_alpha",
                "card_type": "character",
                "merge_key": "character:alpha",
                "title": "甲",
                "summary": "alpha seed",
                "status": "active",
                "source_outline_refs": ["synopsis"],
                "payload": {"canonical_name": "甲"},
                "display_order": 5,
            },
            {
                "operation": "upsert",
                "card_id": "card_beta",
                "card_type": "character",
                "merge_key": "character:beta",
                "title": "乙",
                "summary": "beta seed",
                "status": "active",
                "source_outline_refs": ["synopsis"],
                "payload": {"canonical_name": "乙"},
                "display_order": 20,
            },
        ],
    )

    cards = await service.merge_suggestion_cards(
        "novel_card_order_preserve",
        [
            {
                "operation": "upsert",
                "card_id": "card_beta_v2",
                "card_type": "character",
                "merge_key": "character:beta",
                "title": "乙",
                "summary": "beta updated",
                "status": "active",
                "source_outline_refs": ["vol_1"],
                "payload": {"resources": "新资源"},
                # display_order intentionally omitted: should not clobber existing order.
            }
        ],
    )

    assert [card.merge_key for card in cards] == ["character:alpha", "character:beta"]
    assert [card.display_order for card in cards] == [5, 20]
    assert cards[1].summary == "beta updated"
    assert cards[1].payload["resources"] == "新资源"


@pytest.mark.asyncio
async def test_merge_suggestion_cards_supersede_is_sticky_with_reordered_batch(async_session):
    service = BrainstormWorkspaceService(async_session)

    cards = await service.merge_suggestion_cards(
        "novel_reordered_supersede_cards",
        [
            {
                "operation": "supersede",
                "merge_key": "faction:tian-xing-zong",
            },
            {
                "operation": "upsert",
                "card_id": "card_faction",
                "card_type": "faction",
                "merge_key": "faction:tian-xing-zong",
                "title": "天刑宗",
                "summary": "旧版设定",
                "status": "active",
                "source_outline_refs": ["synopsis"],
                "payload": {"canonical_name": "天刑宗", "position": "铁板一块"},
                "display_order": 20,
            },
        ],
    )

    assert cards[0].status == "superseded"


@pytest.mark.asyncio
async def test_merge_suggestion_cards_supersede_is_sticky_across_calls(async_session):
    service = BrainstormWorkspaceService(async_session)

    first_cards = await service.merge_suggestion_cards(
        "novel_cross_call_supersede_cards",
        [
            {
                "operation": "supersede",
                "merge_key": "faction:tian-xing-zong",
            }
        ],
    )

    assert first_cards[0].status == "superseded"

    second_cards = await service.merge_suggestion_cards(
        "novel_cross_call_supersede_cards",
        [
            {
                "operation": "upsert",
                "card_id": "card_faction",
                "card_type": "faction",
                "merge_key": "faction:tian-xing-zong",
                "title": "天刑宗",
                "summary": "旧版设定",
                "status": "active",
                "source_outline_refs": ["synopsis"],
                "payload": {"canonical_name": "天刑宗", "position": "铁板一块"},
                "display_order": 20,
            }
        ],
    )

    assert second_cards[0].status == "superseded"


@pytest.mark.asyncio
async def test_merge_suggestion_cards_rejects_partial_upsert(async_session):
    service = BrainstormWorkspaceService(async_session)

    with pytest.raises(ValueError, match="Upsert suggestion cards require fields: summary"):
        await service.merge_suggestion_cards(
            "novel_invalid_partial_card",
            [
                {
                    "operation": "upsert",
                    "card_id": "card_invalid",
                    "card_type": "character",
                    "merge_key": "character:lu-zhao",
                    "title": "陆照",
                    "status": "active",
                    "source_outline_refs": ["synopsis"],
                    "payload": {"canonical_name": "陆照"},
                    "display_order": 10,
                }
            ],
        )


def test_list_active_suggestion_cards_filters_terminal_statuses():
    service = BrainstormWorkspaceService(AsyncMock())
    payload = service.list_active_suggestion_cards(
        service._serialize_workspace(
            type(
                "WorkspaceStub",
                (),
                {
                    "id": "ws_1",
                    "novel_id": "novel_cards_helper",
                    "status": "active",
                    "workspace_summary": None,
                    "outline_drafts": {},
                    "setting_docs_draft": [],
                    "setting_suggestion_cards": [
                        {
                            "card_id": "card_active",
                            "card_type": "character",
                            "merge_key": "character:lu-zhao",
                            "title": "陆照",
                            "summary": "active",
                            "status": "active",
                            "source_outline_refs": [],
                            "payload": {},
                            "display_order": 10,
                        },
                        {
                            "card_id": "card_unresolved",
                            "card_type": "faction",
                            "merge_key": "faction:tian-xing-zong",
                            "title": "天刑宗",
                            "summary": "unresolved",
                            "status": "unresolved",
                            "source_outline_refs": [],
                            "payload": {},
                            "display_order": 20,
                        },
                        {
                            "card_id": "card_superseded",
                            "card_type": "relationship",
                            "merge_key": "relationship:lu-zhao:su-qinghan",
                            "title": "陆照 / 苏清寒",
                            "summary": "superseded",
                            "status": "superseded",
                            "source_outline_refs": [],
                            "payload": {},
                            "display_order": 30,
                        },
                    ],
                },
            )()
        )
    )

    assert [card.status for card in payload] == ["active", "unresolved"]


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


@pytest.mark.asyncio
async def test_submit_workspace_relationship_count_materializes_entity_and_relationship_cards(
    async_session,
):
    director = NovelDirector(async_session)
    await director.save_checkpoint(
        "novel_submit_cards",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )

    entity_service = EntityService(async_session)
    source_entity = await entity_service.create_entity(
        "ent_lin_feng",
        "character",
        "林风",
        novel_id="novel_submit_cards",
    )
    target_entity = await entity_service.create_entity(
        "ent_su_xue",
        "character",
        "苏雪",
        novel_id="novel_submit_cards",
    )

    service = BrainstormWorkspaceService(async_session)
    await service.save_outline_draft(
        novel_id="novel_submit_cards",
        outline_type="synopsis",
        outline_ref="synopsis",
        result_snapshot={
            "title": "九霄行",
            "logline": "林风逆势修行",
            "core_conflict": "林风 vs 长老会",
            "themes": ["成长"],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 2,
            "estimated_total_chapters": 200,
            "estimated_total_words": 600000,
        },
    )
    await service.merge_suggestion_cards(
        "novel_submit_cards",
        [
            {
                "operation": "upsert",
                "card_id": "card_char",
                "card_type": "character",
                "merge_key": "character:lin-feng",
                "title": "林风",
                "summary": "主角建议卡",
                "status": "active",
                "source_outline_refs": ["synopsis"],
                "payload": {
                    "canonical_name": "林风",
                    "identity": "外门弟子",
                    "goal": "改命",
                },
                "display_order": 10,
            },
            {
                "operation": "upsert",
                "card_id": "card_target_char",
                "card_type": "character",
                "merge_key": "character:su-xue",
                "title": "苏雪",
                "summary": "目标角色建议卡",
                "status": "active",
                "source_outline_refs": ["synopsis"],
                "payload": {
                    "canonical_name": "苏雪",
                    "identity": "内门弟子",
                    "goal": "查清真相",
                },
                "display_order": 15,
            },
            {
                "operation": "upsert",
                "card_id": "card_rel",
                "card_type": "relationship",
                "merge_key": "relationship:lin-feng:su-xue",
                "title": "林风 / 苏雪",
                "summary": "盟友关系",
                "status": "active",
                "source_outline_refs": ["vol_1"],
                "payload": {
                    "source_entity_ref": "林风",
                    "target_entity_ref": "苏雪",
                    "relation_type": "盟友",
                    "source_entity_card_key": "character:lin-feng",
                    "target_entity_card_key": "character:su-xue",
                },
                "display_order": 20,
            },
        ],
    )

    result = await service.submit_workspace("novel_submit_cards")

    pending = await PendingExtractionRepository(async_session).list_by_novel("novel_submit_cards")
    relationships = await RelationshipRepository(async_session).list_by_source(
        source_entity.id,
        novel_id="novel_submit_cards",
    )

    assert result.pending_setting_count == 2
    assert result.relationship_count == 1
    assert result.submit_warnings == []
    assert len(pending) == 2
    assert len(relationships) == 1
    assert relationships[0].source_id == source_entity.id
    assert relationships[0].target_id == target_entity.id
    assert relationships[0].relation_type == "盟友"


@pytest.mark.asyncio
async def test_submit_workspace_includes_legacy_setting_drafts_when_active_cards_exist(async_session):
    director = NovelDirector(async_session)
    await director.save_checkpoint(
        "novel_submit_cards_with_legacy_drafts",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )

    service = BrainstormWorkspaceService(async_session)
    await service.save_outline_draft(
        novel_id="novel_submit_cards_with_legacy_drafts",
        outline_type="synopsis",
        outline_ref="synopsis",
        result_snapshot={
            "title": "九霄行",
            "logline": "林风逆势修行",
            "core_conflict": "林风 vs 长老会",
            "themes": ["成长"],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 2,
            "estimated_total_chapters": 200,
            "estimated_total_words": 600000,
        },
    )
    await service.merge_setting_drafts(
        "novel_submit_cards_with_legacy_drafts",
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
    await service.merge_suggestion_cards(
        "novel_submit_cards_with_legacy_drafts",
        [
            {
                "operation": "upsert",
                "card_id": "card_char",
                "card_type": "character",
                "merge_key": "character:lu-zhao",
                "title": "陆照",
                "summary": "主角建议卡",
                "status": "active",
                "source_outline_refs": ["synopsis"],
                "payload": {
                    "canonical_name": "陆照",
                    "identity": "外门弟子",
                    "goal": "改命",
                },
                "display_order": 10,
            }
        ],
    )

    result = await service.submit_workspace("novel_submit_cards_with_legacy_drafts")

    pending = await PendingExtractionRepository(async_session).list_by_novel(
        "novel_submit_cards_with_legacy_drafts"
    )

    assert result.pending_setting_count == 2
    assert result.relationship_count == 0
    assert len(pending) == 2
    assert {item.source_filename for item in pending} == {
        "brainstorm-synopsis-draft_1.md",
        "brainstorm-character:lu-zhao.md",
    }


@pytest.mark.asyncio
async def test_submit_workspace_relationship_count_collects_unresolved_card_warnings(
    async_session,
):
    director = NovelDirector(async_session)
    await director.save_checkpoint(
        "novel_submit_card_warning",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )

    entity_service = EntityService(async_session)
    await entity_service.create_entity(
        "ent_lin_feng",
        "character",
        "林风",
        novel_id="novel_submit_card_warning",
    )

    service = BrainstormWorkspaceService(async_session)
    await service.save_outline_draft(
        novel_id="novel_submit_card_warning",
        outline_type="synopsis",
        outline_ref="synopsis",
        result_snapshot={
            "title": "九霄行",
            "logline": "林风逆势修行",
            "core_conflict": "林风 vs 长老会",
            "themes": ["成长"],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 2,
            "estimated_total_chapters": 200,
            "estimated_total_words": 600000,
        },
    )
    await service.merge_suggestion_cards(
        "novel_submit_card_warning",
        [
            {
                "operation": "upsert",
                "card_id": "card_char",
                "card_type": "character",
                "merge_key": "character:lin-feng",
                "title": "林风",
                "summary": "主角建议卡",
                "status": "active",
                "source_outline_refs": ["synopsis"],
                "payload": {
                    "canonical_name": "林风",
                    "identity": "外门弟子",
                    "goal": "改命",
                },
                "display_order": 10,
            },
            {
                "operation": "upsert",
                "card_id": "card_rel",
                "card_type": "relationship",
                "merge_key": "relationship:lin-feng:su-xue",
                "title": "林风 / 苏雪",
                "summary": "盟友关系",
                "status": "active",
                "source_outline_refs": ["vol_1"],
                "payload": {
                    "source_entity_ref": "林风",
                    "target_entity_ref": "苏雪",
                    "relation_type": "盟友",
                    "source_entity_card_key": "character:lin-feng",
                },
                "display_order": 20,
            },
        ],
    )

    result = await service.submit_workspace("novel_submit_card_warning")

    assert result.pending_setting_count == 1
    assert result.relationship_count == 0
    assert result.submit_warnings == [
        "Skipped relationship card relationship:lin-feng:su-xue: target entity ref 苏雪 not found"
    ]


@pytest.mark.asyncio
async def test_submit_workspace_materializes_non_character_suggestion_cards(async_session):
    director = NovelDirector(async_session)
    await director.save_checkpoint(
        "novel_submit_faction_cards",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )

    service = BrainstormWorkspaceService(async_session)
    await service.save_outline_draft(
        novel_id="novel_submit_faction_cards",
        outline_type="synopsis",
        outline_ref="synopsis",
        result_snapshot={
            "title": "九霄行",
            "logline": "林风逆势修行",
            "core_conflict": "林风 vs 长老会",
            "themes": ["成长"],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 2,
            "estimated_total_chapters": 200,
            "estimated_total_words": 600000,
        },
    )
    await service.merge_suggestion_cards(
        "novel_submit_faction_cards",
        [
            {
                "operation": "upsert",
                "card_id": "card_faction",
                "card_type": "faction",
                "merge_key": "faction:qing-yun-zong",
                "title": "青云宗",
                "summary": "宗门势力建议卡",
                "status": "active",
                "source_outline_refs": ["synopsis"],
                "payload": {
                    "canonical_name": "青云宗",
                    "position": "北境七宗之一",
                    "description": "林风早期依附的修行宗门",
                },
                "display_order": 10,
            }
        ],
    )

    result = await service.submit_workspace("novel_submit_faction_cards")

    pending = await PendingExtractionRepository(async_session).list_by_novel(
        "novel_submit_faction_cards"
    )

    assert result.pending_setting_count == 1
    assert result.relationship_count == 0
    assert result.submit_warnings == []
    assert len(pending) == 1
    assert pending[0].source_filename == "brainstorm-faction:qing-yun-zong.md"


@pytest.mark.asyncio
async def test_submit_workspace_skips_ambiguous_name_resolution_with_warning(async_session):
    director = NovelDirector(async_session)
    await director.save_checkpoint(
        "novel_submit_ambiguous_rel",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )

    entity_service = EntityService(async_session)
    source_entity = await entity_service.create_entity(
        "ent_lin_feng_amb",
        "character",
        "林风",
        novel_id="novel_submit_ambiguous_rel",
    )
    await entity_service.create_entity(
        "ent_qingyun_faction",
        "faction",
        "青云",
        novel_id="novel_submit_ambiguous_rel",
    )
    await entity_service.create_entity(
        "ent_qingyun_location",
        "location",
        "青云",
        novel_id="novel_submit_ambiguous_rel",
    )

    service = BrainstormWorkspaceService(async_session)
    await service.save_outline_draft(
        novel_id="novel_submit_ambiguous_rel",
        outline_type="synopsis",
        outline_ref="synopsis",
        result_snapshot={
            "title": "九霄行",
            "logline": "林风逆势修行",
            "core_conflict": "林风 vs 长老会",
            "themes": ["成长"],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 2,
            "estimated_total_chapters": 200,
            "estimated_total_words": 600000,
        },
    )
    await service.merge_suggestion_cards(
        "novel_submit_ambiguous_rel",
        [
            {
                "operation": "upsert",
                "card_id": "card_rel_ambiguous",
                "card_type": "relationship",
                "merge_key": "relationship:lin-feng:qing-yun",
                "title": "林风 / 青云",
                "summary": "关系歧义",
                "status": "active",
                "source_outline_refs": ["vol_1"],
                "payload": {
                    "source_entity_ref": "林风",
                    "target_entity_ref": "青云",
                    "relation_type": "关联",
                },
                "display_order": 10,
            }
        ],
    )

    result = await service.submit_workspace("novel_submit_ambiguous_rel")

    relationships = await RelationshipRepository(async_session).list_by_source(
        source_entity.id,
        novel_id="novel_submit_ambiguous_rel",
    )

    assert result.relationship_count == 0
    assert relationships == []
    assert result.submit_warnings == [
        "Skipped relationship card relationship:lin-feng:qing-yun: target entity ref 青云 is ambiguous"
    ]


@pytest.mark.asyncio
async def test_submit_workspace_skips_empty_relation_type_with_warning(async_session):
    director = NovelDirector(async_session)
    await director.save_checkpoint(
        "novel_submit_empty_relation",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )

    entity_service = EntityService(async_session)
    source_entity = await entity_service.create_entity(
        "ent_lin_feng_empty",
        "character",
        "林风",
        novel_id="novel_submit_empty_relation",
    )
    await entity_service.create_entity(
        "ent_su_xue_empty",
        "character",
        "苏雪",
        novel_id="novel_submit_empty_relation",
    )

    service = BrainstormWorkspaceService(async_session)
    await service.save_outline_draft(
        novel_id="novel_submit_empty_relation",
        outline_type="synopsis",
        outline_ref="synopsis",
        result_snapshot={
            "title": "九霄行",
            "logline": "林风逆势修行",
            "core_conflict": "林风 vs 长老会",
            "themes": ["成长"],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 2,
            "estimated_total_chapters": 200,
            "estimated_total_words": 600000,
        },
    )
    await service.merge_suggestion_cards(
        "novel_submit_empty_relation",
        [
            {
                "operation": "upsert",
                "card_id": "card_source_char",
                "card_type": "character",
                "merge_key": "character:lin-feng",
                "title": "林风",
                "summary": "主角建议卡",
                "status": "active",
                "source_outline_refs": ["synopsis"],
                "payload": {
                    "canonical_name": "林风",
                    "identity": "外门弟子",
                    "goal": "改命",
                },
                "display_order": 10,
            },
            {
                "operation": "upsert",
                "card_id": "card_target_char",
                "card_type": "character",
                "merge_key": "character:su-xue",
                "title": "苏雪",
                "summary": "目标角色建议卡",
                "status": "active",
                "source_outline_refs": ["synopsis"],
                "payload": {
                    "canonical_name": "苏雪",
                    "identity": "内门弟子",
                    "goal": "查清真相",
                },
                "display_order": 15,
            },
            {
                "operation": "upsert",
                "card_id": "card_rel_empty_type",
                "card_type": "relationship",
                "merge_key": "relationship:lin-feng:su-xue",
                "title": "林风 / 苏雪",
                "summary": "缺少关系类型",
                "status": "active",
                "source_outline_refs": ["vol_1"],
                "payload": {
                    "source_entity_card_key": "character:lin-feng",
                    "target_entity_card_key": "character:su-xue",
                    "relation_type": "",
                },
                "display_order": 20,
            },
        ],
    )

    result = await service.submit_workspace("novel_submit_empty_relation")

    relationships = await RelationshipRepository(async_session).list_by_source(
        source_entity.id,
        novel_id="novel_submit_empty_relation",
    )

    assert result.relationship_count == 0
    assert relationships == []
    assert result.submit_warnings == [
        "Skipped relationship card relationship:lin-feng:su-xue: relation_type missing"
    ]


@pytest.mark.asyncio
async def test_submit_workspace_skips_close_match_relationship_resolution(async_session):
    director = NovelDirector(async_session)
    await director.save_checkpoint(
        "novel_submit_close_match_rel",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )

    entity_service = EntityService(async_session)
    source_entity = await entity_service.create_entity(
        "ent_lin_feng_close",
        "character",
        "林风",
        novel_id="novel_submit_close_match_rel",
    )
    await entity_service.create_entity(
        "ent_su_xue_close",
        "character",
        "苏雪儿",
        novel_id="novel_submit_close_match_rel",
    )

    service = BrainstormWorkspaceService(async_session)
    await service.save_outline_draft(
        novel_id="novel_submit_close_match_rel",
        outline_type="synopsis",
        outline_ref="synopsis",
        result_snapshot={
            "title": "九霄行",
            "logline": "林风逆势修行",
            "core_conflict": "林风 vs 长老会",
            "themes": ["成长"],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 2,
            "estimated_total_chapters": 200,
            "estimated_total_words": 600000,
        },
    )
    await service.merge_suggestion_cards(
        "novel_submit_close_match_rel",
        [
            {
                "operation": "upsert",
                "card_id": "card_rel_close",
                "card_type": "relationship",
                "merge_key": "relationship:lin-feng:su-xue",
                "title": "林风 / 苏雪",
                "summary": "仅近似名可命中",
                "status": "active",
                "source_outline_refs": ["vol_1"],
                "payload": {
                    "source_entity_ref": "林风",
                    "target_entity_ref": "苏雪",
                    "relation_type": "盟友",
                },
                "display_order": 10,
            }
        ],
    )

    result = await service.submit_workspace("novel_submit_close_match_rel")

    relationships = await RelationshipRepository(async_session).list_by_source(
        source_entity.id,
        novel_id="novel_submit_close_match_rel",
    )

    assert result.relationship_count == 0
    assert relationships == []
    assert result.submit_warnings == [
        "Skipped relationship card relationship:lin-feng:su-xue: target entity ref 苏雪 not found"
    ]


@pytest.mark.asyncio
async def test_submit_workspace_skips_ambiguous_entity_ref_card_match(async_session):
    director = NovelDirector(async_session)
    await director.save_checkpoint(
        "novel_submit_duplicate_card_match",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )

    entity_service = EntityService(async_session)
    source_entity = await entity_service.create_entity(
        "ent_lin_feng_dup",
        "character",
        "林风",
        novel_id="novel_submit_duplicate_card_match",
    )
    await entity_service.create_entity(
        "ent_qingyun_faction_dup",
        "faction",
        "青云宗",
        novel_id="novel_submit_duplicate_card_match",
    )

    service = BrainstormWorkspaceService(async_session)
    await service.save_outline_draft(
        novel_id="novel_submit_duplicate_card_match",
        outline_type="synopsis",
        outline_ref="synopsis",
        result_snapshot={
            "title": "九霄行",
            "logline": "林风逆势修行",
            "core_conflict": "林风 vs 长老会",
            "themes": ["成长"],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 2,
            "estimated_total_chapters": 200,
            "estimated_total_words": 600000,
        },
    )
    await service.merge_suggestion_cards(
        "novel_submit_duplicate_card_match",
        [
            {
                "operation": "upsert",
                "card_id": "card_faction_qingyun",
                "card_type": "faction",
                "merge_key": "faction:qing-yun-zong",
                "title": "青云宗",
                "summary": "宗门建议卡",
                "status": "active",
                "source_outline_refs": ["synopsis"],
                "payload": {"canonical_name": "青云宗"},
                "display_order": 10,
            },
            {
                "operation": "upsert",
                "card_id": "card_location_qingyun",
                "card_type": "location",
                "merge_key": "location:qing-yun-zong",
                "title": "青云 宗",
                "summary": "地名建议卡",
                "status": "active",
                "source_outline_refs": ["synopsis"],
                "payload": {"canonical_name": "青云 宗"},
                "display_order": 15,
            },
            {
                "operation": "upsert",
                "card_id": "card_rel_dup_match",
                "card_type": "relationship",
                "merge_key": "relationship:lin-feng:qing-yun-zong",
                "title": "林风 / 青云宗",
                "summary": "重名 suggestion card 歧义",
                "status": "active",
                "source_outline_refs": ["vol_1"],
                "payload": {
                    "source_entity_ref": "林风",
                    "target_entity_ref": "青 云宗",
                    "relation_type": "敌对",
                },
                "display_order": 20,
            },
        ],
    )

    result = await service.submit_workspace("novel_submit_duplicate_card_match")

    relationships = await RelationshipRepository(async_session).list_by_source(
        source_entity.id,
        novel_id="novel_submit_duplicate_card_match",
    )

    assert result.relationship_count == 0
    assert relationships == []
    assert result.submit_warnings == [
        "Skipped relationship card relationship:lin-feng:qing-yun-zong: target entity ref 青 云宗 is ambiguous"
    ]
