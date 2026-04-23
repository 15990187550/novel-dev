from unittest.mock import AsyncMock

import pytest

from novel_dev.schemas.brainstorm_workspace import SettingSuggestionCardPayload
from novel_dev.services.extraction_service import ExtractionService


@pytest.mark.asyncio
async def test_build_pending_payload_from_setting_draft_previews_auto_classify_without_persisting(
    async_session,
):
    svc = ExtractionService(async_session)

    payload = await svc.build_pending_payload_from_setting_draft(
        "n_auto_preview",
        {
            "draft_id": "draft_auto",
            "source_outline_ref": "vol_1",
            "source_kind": "setting",
            "target_import_mode": "auto_classify",
            "title": "宗门制度",
            "content": "内外门泾渭分明。",
        },
    )

    pending = await svc.pending_repo.list_by_novel("n_auto_preview")

    assert payload.source_filename == "brainstorm-vol_1-draft_auto.md"
    assert payload.extraction_type == "setting"
    assert payload.raw_result["worldview"] == "mock worldview"
    assert payload.proposed_entities
    assert payload.diff_result is not None
    assert pending == []


@pytest.mark.asyncio
async def test_create_pending_from_setting_draft_uses_preview_builder(async_session):
    svc = ExtractionService(async_session)
    payload = AsyncMock()
    payload.source_filename = "brainstorm-vol_1-draft_auto.md"
    payload.extraction_type = "setting"
    payload.raw_result = {"worldview": "preview"}
    payload.proposed_entities = []
    payload.diff_result = {"summary": "preview"}
    svc.build_pending_payload_from_setting_draft = AsyncMock(return_value=payload)

    draft = {
        "draft_id": "draft_auto",
        "source_outline_ref": "vol_1",
        "source_kind": "setting",
        "target_import_mode": "auto_classify",
        "title": "宗门制度",
        "content": "内外门泾渭分明。",
    }

    result = await svc.create_pending_from_setting_draft("n_auto_draft", draft)

    assert result.source_filename == "brainstorm-vol_1-draft_auto.md"
    assert result.extraction_type == "setting"
    svc.build_pending_payload_from_setting_draft.assert_awaited_once_with(
        "n_auto_draft",
        draft,
    )


@pytest.mark.asyncio
async def test_create_pending_from_setting_draft_builds_explicit_character_pending(async_session):
    svc = ExtractionService(async_session)

    pe = await svc.create_pending_from_setting_draft(
        "n_explicit_draft",
        {
            "draft_id": "draft_char",
            "source_outline_ref": "synopsis",
            "source_kind": "character",
            "target_import_mode": "explicit_type",
            "target_doc_type": "concept",
            "title": "林风",
            "content": "青云宗外门弟子，背负血仇。",
        },
    )

    docs = await svc.approve_pending(pe.id)

    assert pe.extraction_type == "setting"
    assert pe.source_filename == "brainstorm-synopsis-draft_char.md"
    assert pe.raw_result["character_profiles"] == [
        {
            "name": "林风",
            "identity": "青云宗外门弟子，背负血仇。",
            "personality": "",
            "goal": "",
            "appearance": "",
            "background": "",
            "ability": "",
            "realm": "",
            "relationships": "",
            "resources": "",
            "secrets": "",
            "conflict": "",
            "arc": "",
            "notes": "",
        }
    ]
    assert pe.proposed_entities == [
        {
            "type": "character",
            "name": "林风",
            "data": pe.raw_result["character_profiles"][0],
        }
    ]
    assert [doc.title for doc in docs] == ["人物设定"]


@pytest.mark.asyncio
async def test_create_pending_from_setting_draft_builds_explicit_item_pending(async_session):
    svc = ExtractionService(async_session)

    pe = await svc.create_pending_from_setting_draft(
        "n_explicit_item",
        {
            "draft_id": "draft_item",
            "source_outline_ref": "synopsis",
            "source_kind": "item",
            "target_import_mode": "explicit_type",
            "target_doc_type": "concept",
            "title": "玄铁令",
            "content": "可开启祖地禁制的古令牌。",
        },
    )

    docs = await svc.approve_pending(pe.id)

    assert pe.extraction_type == "setting"
    assert pe.source_filename == "brainstorm-synopsis-draft_item.md"
    assert pe.raw_result["important_items"] == [
        {
            "name": "玄铁令",
            "description": "可开启祖地禁制的古令牌。",
            "significance": "",
        }
    ]
    assert pe.proposed_entities == [
        {
            "type": "item",
            "name": "玄铁令",
            "data": pe.raw_result["important_items"][0],
        }
    ]
    assert [doc.title for doc in docs] == ["物品设定"]


@pytest.mark.asyncio
async def test_create_pending_from_setting_draft_builds_explicit_worldview_pending(async_session):
    svc = ExtractionService(async_session)

    pe = await svc.create_pending_from_setting_draft(
        "n_explicit_worldview",
        {
            "draft_id": "draft_worldview",
            "source_outline_ref": "synopsis",
            "source_kind": "worldview",
            "target_import_mode": "explicit_type",
            "target_doc_type": "worldview",
            "title": "世界观总览",
            "content": "九州分裂为三大皇朝与八大宗门。",
        },
    )

    docs = await svc.approve_pending(pe.id)

    assert pe.raw_result["worldview"] == "九州分裂为三大皇朝与八大宗门。"
    assert pe.proposed_entities == []
    assert [(doc.doc_type, doc.title) for doc in docs] == [("worldview", "世界观")]


@pytest.mark.asyncio
async def test_create_pending_from_setting_draft_builds_explicit_power_system_pending(async_session):
    svc = ExtractionService(async_session)

    pe = await svc.create_pending_from_setting_draft(
        "n_explicit_power",
        {
            "draft_id": "draft_power",
            "source_outline_ref": "synopsis",
            "source_kind": "power_system",
            "target_import_mode": "explicit_type",
            "target_doc_type": "setting",
            "title": "修炼体系",
            "content": "炼体、筑基、金丹、元婴四境。",
        },
    )

    docs = await svc.approve_pending(pe.id)

    assert pe.raw_result["power_system"] == "炼体、筑基、金丹、元婴四境。"
    assert pe.proposed_entities == []
    assert [(doc.doc_type, doc.title) for doc in docs] == [("setting", "修炼体系")]


@pytest.mark.asyncio
async def test_create_pending_from_setting_draft_builds_explicit_synopsis_pending(async_session):
    svc = ExtractionService(async_session)

    pe = await svc.create_pending_from_setting_draft(
        "n_explicit_synopsis",
        {
            "draft_id": "draft_synopsis",
            "source_outline_ref": "synopsis",
            "source_kind": "synopsis",
            "target_import_mode": "explicit_type",
            "target_doc_type": "synopsis",
            "title": "剧情梗概",
            "content": "林风自边城入宗，逐步揭开灭门真相。",
        },
    )

    docs = await svc.approve_pending(pe.id)

    assert pe.raw_result["plot_synopsis"] == "林风自边城入宗，逐步揭开灭门真相。"
    assert pe.proposed_entities == []
    assert [(doc.doc_type, doc.title) for doc in docs] == [("synopsis", "剧情梗概")]


@pytest.mark.asyncio
async def test_create_pending_from_setting_draft_rejects_explicit_faction(async_session):
    svc = ExtractionService(async_session)

    with pytest.raises(ValueError, match="Explicit faction drafts are not supported"):
        await svc.create_pending_from_setting_draft(
            "n_faction_draft",
            {
                "draft_id": "draft_faction",
                "source_outline_ref": "synopsis",
                "source_kind": "faction",
                "target_import_mode": "explicit_type",
                "target_doc_type": "setting",
                "title": "青云宗",
                "content": "宗门势力覆盖北境。",
            },
        )


@pytest.mark.asyncio
async def test_create_pending_from_setting_draft_rejects_invalid_explicit_setting_combination(
    async_session,
):
    svc = ExtractionService(async_session)

    with pytest.raises(ValueError, match="Unsupported explicit draft combination"):
        await svc.create_pending_from_setting_draft(
            "n_invalid_draft",
            {
                "draft_id": "draft_setting",
                "source_outline_ref": "vol_2",
                "source_kind": "institution",
                "target_import_mode": "explicit_type",
                "target_doc_type": "setting",
                "title": "监天司",
                "content": "直属皇权的监察机构。",
            },
        )


@pytest.mark.asyncio
async def test_build_pending_payload_from_suggestion_card_builds_character_pending(async_session):
    svc = ExtractionService(async_session)
    card = SettingSuggestionCardPayload.model_validate(
        {
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
        }
    )

    payload = await svc.build_pending_payload_from_suggestion_card(
        "novel_card_mapper",
        card,
    )

    assert payload.source_filename == "brainstorm-character:lin-feng.md"
    assert payload.extraction_type == "setting"
    assert payload.raw_result["character_profiles"] == [
        {
            "canonical_name": "林风",
            "identity": "外门弟子",
            "goal": "改命",
            "name": "林风",
        }
    ]
    assert payload.proposed_entities == [
        {
            "type": "character",
            "name": "林风",
            "data": {
                "identity": "外门弟子",
                "goal": "改命",
                "resources": "",
            },
        }
    ]


@pytest.mark.asyncio
async def test_build_pending_payload_from_suggestion_card_builds_faction_pending(async_session):
    svc = ExtractionService(async_session)
    card = SettingSuggestionCardPayload.model_validate(
        {
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
            "display_order": 20,
        }
    )

    payload = await svc.build_pending_payload_from_suggestion_card(
        "novel_card_mapper",
        card,
    )

    assert payload.source_filename == "brainstorm-faction:qing-yun-zong.md"
    assert payload.extraction_type == "setting"
    assert payload.proposed_entities == [
        {
            "type": "faction",
            "name": "青云宗",
            "data": {
                "name": "青云宗",
                "position": "北境七宗之一",
                "description": "林风早期依附的修行宗门",
            },
        }
    ]


@pytest.mark.asyncio
async def test_build_pending_payload_from_suggestion_card_builds_location_pending(async_session):
    svc = ExtractionService(async_session)
    card = SettingSuggestionCardPayload.model_validate(
        {
            "card_id": "card_location",
            "card_type": "location",
            "merge_key": "location:qing-yun-feng",
            "title": "青云峰",
            "summary": "地点建议卡",
            "status": "active",
            "source_outline_refs": ["vol_1"],
            "payload": {
                "canonical_name": "青云峰",
                "description": "青云宗外门所在主峰",
                "position": "北境",
            },
            "display_order": 30,
        }
    )

    payload = await svc.build_pending_payload_from_suggestion_card(
        "novel_card_mapper",
        card,
    )

    assert payload.source_filename == "brainstorm-location:qing-yun-feng.md"
    assert payload.extraction_type == "setting"
    assert payload.proposed_entities == [
        {
            "type": "location",
            "name": "青云峰",
            "data": {
                "name": "青云峰",
                "description": "青云宗外门所在主峰",
                "position": "北境",
            },
        }
    ]


@pytest.mark.asyncio
async def test_build_pending_payload_from_suggestion_card_builds_item_pending(async_session):
    svc = ExtractionService(async_session)
    card = SettingSuggestionCardPayload.model_validate(
        {
            "card_id": "card_item",
            "card_type": "item",
            "merge_key": "item:xuan-tie-ling",
            "title": "玄铁令",
            "summary": "法宝建议卡",
            "status": "active",
            "source_outline_refs": ["synopsis"],
            "payload": {
                "canonical_name": "玄铁令",
                "description": "可开启祖地禁制的古令牌",
                "significance": "牵出主线秘辛",
            },
            "display_order": 40,
        }
    )

    payload = await svc.build_pending_payload_from_suggestion_card(
        "novel_card_mapper",
        card,
    )

    assert payload.source_filename == "brainstorm-item:xuan-tie-ling.md"
    assert payload.extraction_type == "setting"
    assert payload.raw_result["important_items"] == [
        {
            "name": "玄铁令",
            "description": "可开启祖地禁制的古令牌",
            "significance": "牵出主线秘辛",
        }
    ]
    assert payload.proposed_entities == [
        {
            "type": "item",
            "name": "玄铁令",
            "data": {
                "name": "玄铁令",
                "description": "可开启祖地禁制的古令牌",
                "significance": "牵出主线秘辛",
            },
        }
    ]
