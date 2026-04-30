from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.agents.brainstorm_agent import BrainstormAgent
from novel_dev.agents.outline_clarification_agent import OutlineClarificationAgent, OutlineClarificationDecision
from novel_dev.agents.volume_planner import VolumePlannerAgent
from novel_dev.db.models import OutlineMessage, OutlineSession
from novel_dev.llm.models import LLMResponse
from novel_dev.schemas.brainstorm_workspace import SettingSuggestionCardMergePayload
from novel_dev.services.brainstorm_workspace_service import BrainstormWorkspaceService
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.outline_session_repo import OutlineSessionRepository
from novel_dev.repositories.outline_message_repo import OutlineMessageRepository
from novel_dev.schemas.outline import SynopsisData, VolumePlan, VolumeBeat
from novel_dev.schemas.context import BeatPlan
from novel_dev.schemas.outline_workbench import OutlineContextWindow
from novel_dev.services.outline_workbench_service import (
    OutlineWorkbenchService,
    SuggestionCardUpdateEnvelope,
    SuggestionUpdateSummary,
)


@pytest.mark.asyncio
async def test_build_workbench_returns_synopsis_and_missing_volume_items(async_session):
    director = NovelDirector(session=async_session)
    synopsis = SynopsisData(
        title="九霄行",
        logline="主角逆势而上",
        core_conflict="家仇与天命相撞",
        estimated_volumes=3,
        estimated_total_chapters=30,
        estimated_total_words=90000,
    )
    volume_plan = VolumePlan(
        volume_id="vol_1",
        volume_number=1,
        title="第一卷",
        summary="卷一摘要",
        total_chapters=10,
        estimated_total_words=30000,
        chapters=[
            VolumeBeat(
                chapter_id="ch_1",
                chapter_number=1,
                title="第一章",
                summary="开篇",
                target_word_count=3000,
                target_mood="tense",
                beats=[BeatPlan(summary="B1", target_mood="tense")],
            )
        ],
    )
    await director.save_checkpoint(
        "n_workbench",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={
            "synopsis_data": synopsis.model_dump(),
            "current_volume_plan": volume_plan.model_dump(),
        },
        volume_id=None,
        chapter_id=None,
    )

    service = OutlineWorkbenchService(async_session)

    payload = await service.build_workbench(
        novel_id="n_workbench",
        outline_type="volume",
        outline_ref="vol_2",
    )

    assert [item.outline_ref for item in payload.outline_items] == [
        "synopsis",
        "vol_1",
        "vol_2",
        "vol_3",
    ]
    assert [item.title for item in payload.outline_items] == [
        "总纲",
        "第一卷",
        "第2卷",
        "第3卷",
    ]
    assert payload.outline_items[0].outline_type == "synopsis"
    assert payload.outline_items[2].status == "missing"
    assert payload.outline_items[3].status == "missing"
    assert payload.context_window.last_result_snapshot is None
    assert payload.context_window.recent_messages == []


@pytest.mark.asyncio
async def test_clear_context_removes_outline_messages_summary_and_snapshot(async_session):
    director = NovelDirector(session=async_session)
    synopsis = SynopsisData(
        title="九霄行",
        logline="主角逆势而上",
        core_conflict="家仇与天命相撞",
        estimated_volumes=1,
        estimated_total_chapters=10,
        estimated_total_words=30000,
    )
    await director.save_checkpoint(
        "n_clear_context",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={"synopsis_data": synopsis.model_dump()},
        volume_id=None,
        chapter_id=None,
    )
    session_repo = OutlineSessionRepository(async_session)
    message_repo = OutlineMessageRepository(async_session)
    outline_session = await session_repo.get_or_create(
        novel_id="n_clear_context",
        outline_type="synopsis",
        outline_ref="synopsis",
        status="active",
    )
    outline_session.conversation_summary = "旧摘要"
    outline_session.last_result_snapshot = {"title": "旧快照"}
    await message_repo.create(outline_session.id, "user", "feedback", "旧意见")
    await message_repo.create(outline_session.id, "assistant", "result", "旧结果")
    await async_session.commit()

    service = OutlineWorkbenchService(async_session)
    result = await service.clear_context(
        novel_id="n_clear_context",
        outline_type="synopsis",
        outline_ref="synopsis",
    )

    assert result.deleted_messages == 2
    assert result.conversation_summary is None
    assert result.last_result_snapshot is None

    messages = await service.get_messages(
        novel_id="n_clear_context",
        outline_type="synopsis",
        outline_ref="synopsis",
    )
    assert messages.recent_messages == []
    assert messages.conversation_summary is None
    assert messages.last_result_snapshot is None


@pytest.mark.asyncio
async def test_build_workbench_does_not_create_session_when_only_viewing(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_workbench_readonly",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={
            "synopsis_data": {
                "title": "九霄行",
                "logline": "主角逆势而上",
                "core_conflict": "家仇与天命相撞",
                "themes": [],
                "character_arcs": [],
                "milestones": [],
                "estimated_volumes": 2,
                "estimated_total_chapters": 30,
                "estimated_total_words": 90000,
            }
        },
        volume_id=None,
        chapter_id=None,
    )

    payload = await OutlineWorkbenchService(async_session).build_workbench(
        novel_id="n_workbench_readonly",
        outline_type="volume",
        outline_ref="vol_1",
    )

    assert payload.session_id == ""
    session_count = await async_session.scalar(
        select(func.count())
        .select_from(OutlineSession)
        .where(
            OutlineSession.novel_id == "n_workbench_readonly",
            OutlineSession.outline_type == "volume",
            OutlineSession.outline_ref == "vol_1",
        )
    )
    assert session_count == 0


@pytest.mark.asyncio
async def test_build_workbench_marks_failed_volume_revision_and_exposes_review_snapshot(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_workbench_review_failed",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={
            "synopsis_data": {
                "title": "九霄行",
                "logline": "主角逆势而上",
                "core_conflict": "家仇与天命相撞",
                "themes": [],
                "character_arcs": [],
                "milestones": [],
                "estimated_volumes": 1,
                "estimated_total_chapters": 10,
                "estimated_total_words": 30000,
            },
            "current_volume_plan": {
                "volume_id": "vol_1",
                "volume_number": 1,
                "title": "第一卷",
                "summary": "卷纲初稿",
                "total_chapters": 1,
                "estimated_total_words": 3000,
                "chapters": [],
                "review_status": {
                    "status": "revise_failed",
                    "reason": "自动修订失败",
                    "score": {"overall": 50},
                },
            },
        },
        volume_id=None,
        chapter_id=None,
    )

    payload = await OutlineWorkbenchService(async_session).build_workbench(
        novel_id="n_workbench_review_failed",
        outline_type="volume",
        outline_ref="vol_1",
    )

    volume_item = next(item for item in payload.outline_items if item.outline_ref == "vol_1")
    assert volume_item.status == "needs_revision"
    assert payload.context_window.last_result_snapshot["review_status"]["score"]["overall"] == 50


@pytest.mark.asyncio
async def test_write_volume_snapshot_persists_chapters_and_volume_document(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_write_volume_snapshot",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={
            "synopsis_data": {
                "title": "九霄行",
                "logline": "主角逆势而上",
                "core_conflict": "家仇与天命相撞",
                "themes": [],
                "character_arcs": [],
                "milestones": [],
                "estimated_volumes": 1,
                "estimated_total_chapters": 2,
                "estimated_total_words": 6000,
            }
        },
        volume_id=None,
        chapter_id=None,
    )
    volume_plan = VolumePlan(
        volume_id="vol_1",
        volume_number=1,
        title="第一卷",
        summary="卷一摘要",
        total_chapters=2,
        estimated_total_words=6000,
        chapters=[
            VolumeBeat(
                chapter_id="ch_1",
                chapter_number=1,
                title="照见旧碑",
                summary="陆照发现古碑异动。",
                target_word_count=3000,
                target_mood="mysterious",
                beats=[BeatPlan(summary="旧碑裂开。", target_mood="mysterious")],
            ),
            VolumeBeat(
                chapter_id="ch_2",
                chapter_number=2,
                title="山门问罪",
                summary="长老会借机发难。",
                target_word_count=3000,
                target_mood="tense",
                beats=[BeatPlan(summary="长老发难。", target_mood="tense")],
            ),
        ],
    )

    await OutlineWorkbenchService(async_session)._write_result_snapshot(
        novel_id="n_write_volume_snapshot",
        outline_type="volume",
        outline_ref="vol_1",
        result_snapshot=volume_plan.model_dump(),
    )

    state = await director.resume("n_write_volume_snapshot")
    assert state.checkpoint_data["current_volume_plan"]["title"] == "第一卷"
    assert state.current_volume_id == "vol_1"
    assert state.current_chapter_id == "ch_1"
    chapters = await ChapterRepository(async_session).list_by_volume("vol_1")
    assert [chapter.id for chapter in chapters] == ["ch_1", "ch_2"]
    docs = await DocumentRepository(async_session).get_by_type("n_write_volume_snapshot", "volume_plan")
    assert len(docs) == 1
    assert docs[0].title == "第一卷"


@pytest.mark.asyncio
async def test_submit_feedback_routes_volume_outline_and_returns_assistant_message(async_session, monkeypatch):
    director = NovelDirector(session=async_session)
    synopsis = SynopsisData(
        title="九霄行",
        logline="主角逆势而上",
        core_conflict="家仇与天命相撞",
        estimated_volumes=2,
        estimated_total_chapters=20,
        estimated_total_words=60000,
    )
    await director.save_checkpoint(
        "n_submit",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={"synopsis_data": synopsis.model_dump()},
        volume_id=None,
        chapter_id=None,
    )

    service = OutlineWorkbenchService(async_session)
    optimize_calls = []
    snapshot_calls = []

    async def fake_optimize_outline(*, novel_id, outline_type, outline_ref, feedback, context_window):
        optimize_calls.append(
            {
                "novel_id": novel_id,
                "outline_type": outline_type,
                "outline_ref": outline_ref,
                "feedback": feedback,
                "context_window": context_window,
            }
        )
        return {
            "content": "已根据反馈补强第二卷冲突升级。",
            "result_snapshot": {"outline_ref": outline_ref, "title": "第二卷", "summary": "强化冲突升级"},
            "conversation_summary": "用户要求强化第二卷中段冲突，已完成调整。",
        }

    async def fake_write_result_snapshot(*, novel_id, outline_type, outline_ref, result_snapshot):
        snapshot_calls.append(
            {
                "novel_id": novel_id,
                "outline_type": outline_type,
                "outline_ref": outline_ref,
                "result_snapshot": result_snapshot,
            }
        )

    monkeypatch.setattr(service, "_optimize_outline", fake_optimize_outline)
    monkeypatch.setattr(service, "_write_result_snapshot", fake_write_result_snapshot)

    response = await service.submit_feedback(
        novel_id="n_submit",
        outline_type="volume",
        outline_ref="vol_2",
        feedback="第二卷冲突升级不够猛，再推高主角代价。",
    )

    assert optimize_calls and optimize_calls[0]["outline_type"] == "volume"
    assert optimize_calls[0]["novel_id"] == "n_submit"
    assert optimize_calls[0]["outline_ref"] == "vol_2"
    assert optimize_calls[0]["feedback"] == "第二卷冲突升级不够猛，再推高主角代价。"
    assert response.assistant_message.content == "已根据反馈补强第二卷冲突升级。"
    assert response.assistant_message.role == "assistant"
    assert response.last_result_snapshot == {
        "outline_ref": "vol_2",
        "title": "第二卷",
        "summary": "强化冲突升级",
    }
    assert response.conversation_summary == "用户要求强化第二卷中段冲突，已完成调整。"
    assert snapshot_calls == [
        {
            "novel_id": "n_submit",
            "outline_type": "volume",
            "outline_ref": "vol_2",
            "result_snapshot": {"outline_ref": "vol_2", "title": "第二卷", "summary": "强化冲突升级"},
        }
    ]

    session = await OutlineSessionRepository(async_session).get_or_create(
        novel_id="n_submit",
        outline_type="volume",
        outline_ref="vol_2",
    )
    messages = (
        await async_session.execute(
            OutlineMessage.__table__.select().where(OutlineMessage.session_id == session.id).order_by(OutlineMessage.created_at.asc())
        )
    ).all()

    assert [row.role for row in messages] == ["user", "assistant"]
    assert messages[0].content == "第二卷冲突升级不够猛，再推高主角代价。"
    assert messages[1].content == "已根据反馈补强第二卷冲突升级。"
    assert session.last_result_snapshot == {"outline_ref": "vol_2", "title": "第二卷", "summary": "强化冲突升级"}
    assert session.conversation_summary == "用户要求强化第二卷中段冲突，已完成调整。"


@pytest.mark.asyncio
async def test_submit_feedback_omits_setting_update_summary_outside_brainstorming(async_session, monkeypatch):
    director = NovelDirector(session=async_session)
    synopsis = SynopsisData(
        title="九霄行",
        logline="主角逆势而上",
        core_conflict="家仇与天命相撞",
        estimated_volumes=2,
        estimated_total_chapters=20,
        estimated_total_words=60000,
    )
    await director.save_checkpoint(
        "n_submit_no_summary",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={"synopsis_data": synopsis.model_dump()},
        volume_id=None,
        chapter_id=None,
    )

    service = OutlineWorkbenchService(async_session)

    async def fake_optimize_volume(**kwargs):
        return {
            "content": "已根据反馈补强第二卷冲突升级。",
            "result_snapshot": {
                "volume_id": "vol_2",
                "volume_number": 2,
                "title": "第二卷",
                "summary": "强化冲突升级",
                "total_chapters": 10,
                "estimated_total_words": 30000,
                "chapters": [],
            },
            "setting_draft_updates": [],
        }

    async def fake_write_result_snapshot(**kwargs):
        return None

    monkeypatch.setattr(service, "_optimize_volume", fake_optimize_volume)
    monkeypatch.setattr(service, "_write_result_snapshot", fake_write_result_snapshot)

    response = await service.submit_feedback(
        novel_id="n_submit_no_summary",
        outline_type="volume",
        outline_ref="vol_2",
        feedback="第二卷冲突升级不够猛，再推高主角代价。",
    )

    assert response.setting_update_summary is None


@pytest.mark.asyncio
async def test_submit_feedback_updates_synopsis_checkpoint(async_session, monkeypatch):
    director = NovelDirector(session=async_session)
    synopsis = SynopsisData(
        title="九霄行",
        logline="主角逆势而上",
        core_conflict="家仇与天命相撞",
        estimated_volumes=5,
        estimated_total_chapters=800,
        estimated_total_words=2400000,
    )
    await director.save_checkpoint(
        "n_synopsis_submit",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={"synopsis_data": synopsis.model_dump()},
        volume_id=None,
        chapter_id=None,
    )

    service = OutlineWorkbenchService(async_session)

    async def fake_optimize_outline(*, novel_id, outline_type, outline_ref, feedback, context_window):
        assert novel_id == "n_synopsis_submit"
        assert outline_type == "synopsis"
        assert outline_ref == "synopsis"
        assert feedback == "总章数我想要达到 1300 章左右"
        return {
            "content": "已将总纲预计总章数调整为约 1300 章，并同步提高总字数预估。",
            "result_snapshot": {
                **synopsis.model_dump(),
                "estimated_total_chapters": 1300,
                "estimated_total_words": 3900000,
            },
            "conversation_summary": "用户希望把整书体量提升到约 1300 章，已更新总纲规模预估。",
        }

    monkeypatch.setattr(service, "_optimize_outline", fake_optimize_outline)

    response = await service.submit_feedback(
        novel_id="n_synopsis_submit",
        outline_type="synopsis",
        outline_ref="synopsis",
        feedback="总章数我想要达到 1300 章左右",
    )

    state = await service.novel_state_repo.get_state("n_synopsis_submit")
    assert state is not None
    assert state.checkpoint_data["synopsis_data"]["estimated_total_chapters"] == 1300
    assert state.checkpoint_data["synopsis_data"]["estimated_total_words"] == 3900000
    assert response.last_result_snapshot["estimated_total_chapters"] == 1300
    assert response.assistant_message.content == "已将总纲预计总章数调整为约 1300 章，并同步提高总字数预估。"


@pytest.mark.asyncio
async def test_submit_feedback_regenerates_synopsis_when_rewrite_intent(async_session, monkeypatch):
    director = NovelDirector(session=async_session)
    old_synopsis = SynopsisData(
        title="旧总纲",
        logline="旧主线",
        core_conflict="旧冲突",
        estimated_volumes=2,
        estimated_total_chapters=80,
        estimated_total_words=240000,
    )
    await director.save_checkpoint(
        "n_synopsis_regenerate",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={"synopsis_data": old_synopsis.model_dump()},
        volume_id=None,
        chapter_id=None,
    )

    service = OutlineWorkbenchService(async_session)
    monkeypatch.setattr(
        service,
        "_optimize_synopsis",
        AsyncMock(side_effect=AssertionError("rewrite intent should not use revise")),
    )
    monkeypatch.setattr(service, "_load_brainstorm_source_text", AsyncMock(return_value="世界设定"))

    captured = {}

    async def fake_generate_synopsis(self, combined_text, novel_id):
        captured["combined_text"] = combined_text
        captured["novel_id"] = novel_id
        return SynopsisData(
            title="新总纲",
            logline="新主线",
            core_conflict="新冲突",
            estimated_volumes=4,
            estimated_total_chapters=1300,
            estimated_total_words=3900000,
        )

    monkeypatch.setattr(BrainstormAgent, "_generate_synopsis", fake_generate_synopsis)

    response = await service.submit_feedback(
        novel_id="n_synopsis_regenerate",
        outline_type="synopsis",
        outline_ref="synopsis",
        feedback="重写生成 1300 左右的大纲，替换掉旧版",
    )

    state = await service.novel_state_repo.get_state("n_synopsis_regenerate")
    assert state is not None
    assert state.checkpoint_data["synopsis_data"]["title"] == "新总纲"
    assert state.checkpoint_data["synopsis_data"]["estimated_total_chapters"] == 1300
    assert response.last_result_snapshot["title"] == "新总纲"
    assert "重写生成 1300 左右的大纲" in captured["combined_text"]
    assert "旧版规模参考" in captured["combined_text"]
    assert "旧预估总章数: 80" in captured["combined_text"]
    assert "旧主线" not in captured["combined_text"]


@pytest.mark.asyncio
async def test_optimize_synopsis_prompt_explicitly_constrains_schema(async_session):
    service = OutlineWorkbenchService(async_session)
    checkpoint = {
        "synopsis_data": {
            "title": "道照诸天",
            "logline": "陆照欲证彼岸，却被末劫与旧敌逼上绝路。",
            "core_conflict": "陆照 vs 玄天道庭，争夺末劫前最后的彼岸道统",
            "themes": ["求道"],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 10,
            "estimated_total_chapters": 1300,
            "estimated_total_words": 3900000,
        }
    }
    outline_session = await service.outline_session_repo.get_or_create(
        novel_id="n_prompt_constraints",
        outline_type="synopsis",
        outline_ref="synopsis",
    )
    context_window = await service._build_context_window(
        outline_session.id,
        outline_type="synopsis",
        outline_ref="synopsis",
    )
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(
        text=SynopsisData(
            title="道照诸天",
            logline="陆照欲证彼岸，却被末劫与旧敌逼上绝路。",
            core_conflict="陆照 vs 玄天道庭，争夺末劫前最后的彼岸道统",
            themes=["求道"],
            character_arcs=[],
            milestones=[],
            estimated_volumes=10,
            estimated_total_chapters=1300,
            estimated_total_words=3900000,
        ).model_dump_json()
    )

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        with patch.object(service, "_load_brainstorm_source_text", AsyncMock(return_value="世界设定")):
            await service._optimize_synopsis(
                novel_id="n_prompt_constraints",
                checkpoint=checkpoint,
                feedback="强化末劫压迫感，但不要改主线方向。",
                context_window=context_window,
            )

    prompt = mock_client.acomplete.call_args.args[0][0].content
    assert "只允许以下顶层字段" in prompt
    assert '"title"' in prompt
    assert '"logline"' in prompt
    assert '"core_conflict"' in prompt
    assert '"themes"' in prompt
    assert '"character_arcs"' in prompt
    assert '"milestones"' in prompt
    assert '"estimated_volumes"' in prompt
    assert '"estimated_total_chapters"' in prompt
    assert '"estimated_total_words"' in prompt
    assert '"entity_highlights"' in prompt
    assert '"relationship_highlights"' in prompt
    assert "character_arcs: 数组,每项只包含 name / arc_summary / key_turning_points 三个字段" in prompt
    assert "milestones: 数组,每项只包含 act / summary / climax_event 三个字段" in prompt
    assert "entity_highlights: 对象" in prompt
    assert "relationship_highlights: 字符串数组" in prompt
    assert "禁止使用旧字段" in prompt
    assert "character / arc / turning_points" in prompt
    assert "name / description / chapter_range" in prompt


@pytest.mark.asyncio
async def test_optimize_synopsis_preserves_highlight_fields_in_result_snapshot(async_session):
    service = OutlineWorkbenchService(async_session)
    checkpoint = {
        "synopsis_data": {
            "title": "道照诸天",
            "logline": "旧梗概",
            "core_conflict": "旧冲突",
            "themes": ["求道"],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 10,
            "estimated_total_chapters": 1300,
            "estimated_total_words": 3900000,
        }
    }
    context_window = OutlineContextWindow()

    with patch(
        "novel_dev.services.outline_workbench_service.call_and_parse_model",
        new=AsyncMock(
            return_value=SynopsisData.model_validate(
                {
                    **checkpoint["synopsis_data"],
                    "logline": "新梗概",
                    "entity_highlights": {"characters": ["陆照：主角"]},
                    "relationship_highlights": ["陆照 / 苏清寒：互疑转合作"],
                }
            )
        ),
    ):
        with patch.object(service, "_load_brainstorm_source_text", AsyncMock(return_value="世界设定")):
            result = await service._optimize_synopsis(
                novel_id="n_synopsis_highlights",
                checkpoint=checkpoint,
                feedback="补强人物亮点",
                context_window=context_window,
            )

    assert result["result_snapshot"]["entity_highlights"] == {"characters": ["陆照：主角"]}
    assert result["result_snapshot"]["relationship_highlights"] == ["陆照 / 苏清寒：互疑转合作"]


@pytest.mark.asyncio
async def test_optimize_volume_preserves_highlight_fields_in_result_snapshot(async_session, monkeypatch):
    checkpoint = {
        "synopsis_data": {
            "title": "道照诸天",
            "logline": "陆照求道",
            "core_conflict": "陆照 vs 玄天道庭",
            "themes": ["求道"],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 2,
            "estimated_total_chapters": 100,
            "estimated_total_words": 300000,
        }
    }
    service = OutlineWorkbenchService(async_session)

    async def fake_generate_volume_plan(*args, **kwargs):
        return VolumePlan.model_validate(
            {
                "volume_id": "vol_1",
                "volume_number": 1,
                "title": "第一卷",
                "summary": "卷一摘要",
                "total_chapters": 10,
                "estimated_total_words": 100000,
                "chapters": [],
            }
        )

    async def fake_revise_volume_plan(*args, **kwargs):
        return VolumePlan.model_validate(
            {
                "volume_id": "vol_1",
                "volume_number": 1,
                "title": "第一卷",
                "summary": "卷一摘要",
                "total_chapters": 10,
                "estimated_total_words": 100000,
                "chapters": [],
                "entity_highlights": {"characters": ["陆照：主角"]},
                "relationship_highlights": ["陆照 / 苏清寒：互疑转合作"],
            }
        )

    monkeypatch.setattr(VolumePlannerAgent, "_generate_volume_plan", fake_generate_volume_plan)
    monkeypatch.setattr(VolumePlannerAgent, "_revise_volume_plan", fake_revise_volume_plan)
    async def fake_build_plan_context(*args, **kwargs):
        return "plan context"

    monkeypatch.setattr(VolumePlannerAgent, "_build_plan_context", fake_build_plan_context)

    result = await service._optimize_volume(
        novel_id="n_volume_highlights",
        outline_ref="vol_1",
        checkpoint=checkpoint,
        feedback="补强人物关系亮点",
        context_window=OutlineContextWindow(),
    )

    assert result["result_snapshot"]["entity_highlights"] == {"characters": ["陆照：主角"]}
    assert result["result_snapshot"]["relationship_highlights"] == ["陆照 / 苏清寒：互疑转合作"]


@pytest.mark.asyncio
async def test_optimize_volume_regenerates_instead_of_revising_for_rewrite_intent(async_session, monkeypatch):
    checkpoint = {
        "synopsis_data": {
            "title": "道照诸天",
            "logline": "陆照求道",
            "core_conflict": "陆照 vs 玄天道庭",
            "themes": ["求道"],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 2,
            "estimated_total_chapters": 100,
            "estimated_total_words": 300000,
        }
    }
    existing_plan = VolumePlan(
        volume_id="vol_1",
        volume_number=1,
        title="旧第一卷",
        summary="旧摘要",
        total_chapters=10,
        estimated_total_words=100000,
        chapters=[],
    )
    service = OutlineWorkbenchService(async_session)
    captured = {}

    async def fake_generate_volume_plan(
        self,
        synopsis,
        volume_number,
        world_snapshot=None,
        novel_id="",
        generation_instruction="",
        target_chapters=None,
    ):
        captured["generation_instruction"] = generation_instruction
        captured["target_chapters"] = target_chapters
        return VolumePlan(
            volume_id="vol_1",
            volume_number=volume_number,
            title="新第一卷",
            summary="新摘要",
            total_chapters=12,
            estimated_total_words=120000,
            chapters=[],
        )

    async def fake_revise_volume_plan(*args, **kwargs):
        raise AssertionError("rewrite intent should not use revise")

    monkeypatch.setattr(VolumePlannerAgent, "_generate_volume_plan", fake_generate_volume_plan)
    monkeypatch.setattr(VolumePlannerAgent, "_revise_volume_plan", fake_revise_volume_plan)
    async def fake_build_plan_context(*args, **kwargs):
        return "plan context"

    monkeypatch.setattr(VolumePlannerAgent, "_build_plan_context", fake_build_plan_context)

    result = await service._optimize_volume(
        novel_id="n_volume_regenerate",
        outline_ref="vol_1",
        checkpoint=checkpoint,
        feedback="重新生成第一卷卷纲，替换旧版",
        context_window=OutlineContextWindow(last_result_snapshot=existing_plan.model_dump()),
        regenerate=True,
    )

    assert result["result_snapshot"]["title"] == "新第一卷"
    assert result["result_snapshot"]["total_chapters"] == 12
    assert captured["generation_instruction"] == "重新生成第一卷卷纲，替换旧版"
    assert captured["target_chapters"] is None


@pytest.mark.asyncio
async def test_optimize_volume_regenerates_with_requested_chapter_count(async_session, monkeypatch):
    checkpoint = {
        "synopsis_data": {
            "title": "道照诸天",
            "logline": "陆照求道",
            "core_conflict": "陆照 vs 玄天道庭",
            "themes": ["求道"],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 2,
            "estimated_total_chapters": 100,
            "estimated_total_words": 300000,
        }
    }
    existing_plan = VolumePlan(
        volume_id="vol_1",
        volume_number=1,
        title="旧第一卷",
        summary="旧摘要",
        total_chapters=24,
        estimated_total_words=100000,
        chapters=[],
    )
    service = OutlineWorkbenchService(async_session)
    captured = {}

    async def fake_generate_volume_plan(
        self,
        synopsis,
        volume_number,
        world_snapshot=None,
        novel_id="",
        generation_instruction="",
        target_chapters=None,
    ):
        captured["generation_instruction"] = generation_instruction
        captured["target_chapters"] = target_chapters
        return VolumePlan(
            volume_id="vol_1",
            volume_number=volume_number,
            title="新第一卷",
            summary="新摘要",
            total_chapters=target_chapters or 24,
            estimated_total_words=180000,
            chapters=[],
        )

    async def fake_revise_volume_plan(*args, **kwargs):
        raise AssertionError("chapter count changes must regenerate instead of revise")

    monkeypatch.setattr(VolumePlannerAgent, "_generate_volume_plan", fake_generate_volume_plan)
    monkeypatch.setattr(VolumePlannerAgent, "_revise_volume_plan", fake_revise_volume_plan)

    async def fake_build_plan_context(*args, **kwargs):
        return "plan context"

    monkeypatch.setattr(VolumePlannerAgent, "_build_plan_context", fake_build_plan_context)

    result = await service._optimize_volume(
        novel_id="n_volume_scale",
        outline_ref="vol_1",
        checkpoint=checkpoint,
        feedback="24章不够，要60章",
        context_window=OutlineContextWindow(last_result_snapshot=existing_plan.model_dump()),
        regenerate=True,
    )

    assert result["result_snapshot"]["total_chapters"] == 60
    assert captured["generation_instruction"] == "24章不够，要60章"
    assert captured["target_chapters"] == 60


def test_classify_feedback_intent_detects_regenerate_and_negation(async_session):
    service = OutlineWorkbenchService(async_session)

    assert service._classify_feedback_intent("重写生成 1300 左右的大纲") == service._REGENERATE_INTENT
    assert service._classify_feedback_intent("重写 1300 左右的大纲") == service._REGENERATE_INTENT
    assert service._classify_feedback_intent("重新规划总纲，每一卷边界要更清晰") == service._REGENERATE_INTENT
    assert service._classify_feedback_intent("重新做一版第一卷卷纲") == service._REGENERATE_INTENT
    assert service._classify_feedback_intent("推倒重来，另起一版") == service._REGENERATE_INTENT
    assert service._classify_feedback_intent("第一卷要求60章左右") == service._REGENERATE_INTENT
    assert service._extract_requested_chapter_count("24章不够，要60章") == 60
    assert service._classify_feedback_intent("不要重写，只补强第二卷冲突") == service._REVISE_INTENT
    assert service._classify_feedback_intent("细化每一卷的境界提升") == service._REVISE_INTENT


@pytest.mark.asyncio
async def test_submit_feedback_requests_dynamic_clarification_before_generating_missing_brainstorm_synopsis(async_session, monkeypatch):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_brainstorm_clarify",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={
            "synopsis_data": {
                "title": "旧总纲",
                "logline": "",
                "core_conflict": "",
                "themes": [],
                "character_arcs": [],
                "milestones": [],
                "estimated_volumes": 2,
                "estimated_total_chapters": 10,
                "estimated_total_words": 30000,
            }
        },
        volume_id=None,
        chapter_id=None,
    )

    service = OutlineWorkbenchService(async_session)

    async def fail_optimize_outline(**kwargs):
        raise AssertionError("should not optimize while clarification is needed")

    async def fake_clarify(self, request):
        assert request.outline_type == "synopsis"
        assert request.outline_ref == "synopsis"
        assert request.round_number == 1
        return OutlineClarificationDecision(
            status="clarifying",
            confidence=0.4,
            missing_points=["题材卖点不明确"],
            questions=["题材、基调和核心卖点更偏哪一类？"],
            clarification_summary="用户想生成总纲，但题材卖点不明确。",
            assumptions=[],
            reason="缺少题材方向。",
        )

    monkeypatch.setattr(service, "_optimize_outline", fail_optimize_outline)
    monkeypatch.setattr(OutlineClarificationAgent, "clarify", fake_clarify)

    response = await service.submit_feedback(
        novel_id="n_brainstorm_clarify",
        outline_type="synopsis",
        outline_ref="synopsis",
        feedback="请基于当前设定生成完整总纲草稿，补齐一句话梗概、核心冲突、卷数规模、人物弧光和关键里程碑。",
    )

    assert response.assistant_message.role == "assistant"
    assert response.assistant_message.message_type == "question"
    assert response.last_result_snapshot is None
    assert "题材、基调和核心卖点" in response.assistant_message.content
    assert response.assistant_message.meta["interaction_stage"] == "generation_clarification"
    assert response.assistant_message.meta["clarification_round"] == 1
    assert response.assistant_message.meta["max_rounds"] == 5
    assert response.assistant_message.meta["clarification_status"] == "clarifying"
    assert response.assistant_message.meta["missing_points"] == ["题材卖点不明确"]

    session = await OutlineSessionRepository(async_session).get_or_create(
        novel_id="n_brainstorm_clarify",
        outline_type="synopsis",
        outline_ref="synopsis",
    )
    assert session.status == "awaiting_confirmation"
    assert session.last_result_snapshot is None


@pytest.mark.asyncio
async def test_submit_feedback_generates_when_clarification_reports_ready(async_session, monkeypatch):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_brainstorm_ready",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={
            "synopsis_data": {
                "title": "旧总纲",
                "logline": "",
                "core_conflict": "",
                "themes": [],
                "character_arcs": [],
                "milestones": [],
                "estimated_volumes": 2,
                "estimated_total_chapters": 10,
                "estimated_total_words": 30000,
            }
        },
        volume_id=None,
        chapter_id=None,
    )

    service = OutlineWorkbenchService(async_session)

    async def fake_clarify(self, request):
        return OutlineClarificationDecision(
            status="ready_to_generate",
            confidence=0.88,
            missing_points=[],
            questions=[],
            clarification_summary="用户已确认仙侠升级流、两卷、弱感情线。",
            assumptions=[],
            reason="信息足够。",
        )

    optimize_calls = []

    async def fake_optimize_outline(*, novel_id, outline_type, outline_ref, feedback, context_window):
        optimize_calls.append({"feedback": feedback, "context_window": context_window})
        return {
            "content": "已生成总纲草稿，请继续提出修改意见。",
            "result_snapshot": {
                "title": "新总纲",
                "logline": "新的故事主线",
                "core_conflict": "新的冲突",
                "themes": [],
                "character_arcs": [],
                "milestones": [],
                "estimated_volumes": 2,
                "estimated_total_chapters": 120,
                "estimated_total_words": 360000,
            },
            "conversation_summary": "用户已确认仙侠升级流、两卷、弱感情线。",
        }

    monkeypatch.setattr(OutlineClarificationAgent, "clarify", fake_clarify)
    monkeypatch.setattr(service, "_optimize_outline", fake_optimize_outline)

    response = await service.submit_feedback(
        novel_id="n_brainstorm_ready",
        outline_type="synopsis",
        outline_ref="synopsis",
        feedback="走仙侠升级流，预计两卷，感情线弱一些，按这个方向生成。",
    )

    assert optimize_calls
    assert "澄清摘要：用户已确认仙侠升级流、两卷、弱感情线。" in optimize_calls[0]["feedback"]
    assert response.assistant_message.message_type == "result"
    assert response.last_result_snapshot["title"] == "新总纲"

    session = await OutlineSessionRepository(async_session).get_or_create(
        novel_id="n_brainstorm_ready",
        outline_type="synopsis",
        outline_ref="synopsis",
    )
    assert session.status == "active"
    assert session.last_result_snapshot["title"] == "新总纲"

    workspace = await BrainstormWorkspaceService(async_session).get_workspace_payload("n_brainstorm_ready")
    assert workspace.outline_drafts["synopsis:synopsis"]["title"] == "新总纲"


@pytest.mark.asyncio
async def test_submit_feedback_releases_transaction_before_clarification_llm(async_session, monkeypatch):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_brainstorm_release",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={
            "synopsis_data": {
                "title": "旧总纲",
                "logline": "",
                "core_conflict": "",
                "themes": [],
                "character_arcs": [],
                "milestones": [],
                "estimated_volumes": 2,
                "estimated_total_chapters": 10,
                "estimated_total_words": 30000,
            }
        },
        volume_id=None,
        chapter_id=None,
    )

    service = OutlineWorkbenchService(async_session)
    transaction_states = []

    async def fake_clarify(self, request):
        transaction_states.append(service.session.in_transaction())
        return OutlineClarificationDecision(
            status="clarifying",
            confidence=0.5,
            missing_points=["题材方向不明确"],
            questions=["题材方向按哪类推进？"],
            clarification_summary="需要确认题材方向。",
            assumptions=[],
            reason="等待用户补充。",
        )

    monkeypatch.setattr(OutlineClarificationAgent, "clarify", fake_clarify)

    response = await service.submit_feedback(
        novel_id="n_brainstorm_release",
        outline_type="synopsis",
        outline_ref="synopsis",
        feedback="请生成完整总纲。",
    )

    assert response.assistant_message.message_type == "question"
    assert response.assistant_message.meta["interaction_stage"] == "generation_clarification"
    assert transaction_states == [False]


@pytest.mark.asyncio
async def test_submit_feedback_allows_fifth_visible_clarification_question(async_session, monkeypatch):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_brainstorm_round5",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={
            "synopsis_data": {
                "title": "旧总纲",
                "logline": "",
                "core_conflict": "",
                "themes": [],
                "character_arcs": [],
                "milestones": [],
                "estimated_volumes": 2,
                "estimated_total_chapters": 10,
                "estimated_total_words": 30000,
            }
        },
        volume_id=None,
        chapter_id=None,
    )

    service = OutlineWorkbenchService(async_session)
    outline_session = await OutlineSessionRepository(async_session).get_or_create(
        novel_id="n_brainstorm_round5",
        outline_type="synopsis",
        outline_ref="synopsis",
        status="awaiting_confirmation",
    )
    message_repo = OutlineMessageRepository(async_session)
    for round_number in range(1, 5):
        await message_repo.create(
            session_id=outline_session.id,
            role="assistant",
            message_type="question",
            content=f"第 {round_number} 轮问题",
            meta={
                "outline_type": "synopsis",
                "outline_ref": "synopsis",
                "interaction_stage": "generation_clarification",
                "clarification_round": round_number,
                "max_rounds": 5,
            },
        )
        await message_repo.create(
            session_id=outline_session.id,
            role="user",
            message_type="feedback",
            content=f"第 {round_number} 轮回答",
            meta={"outline_type": "synopsis", "outline_ref": "synopsis"},
        )
    await async_session.commit()

    async def fake_clarify(self, request):
        assert request.round_number == 5
        return OutlineClarificationDecision(
            status="clarifying",
            confidence=0.45,
            missing_points=["终局方向仍不明确"],
            questions=["终局方向更偏飞升、守护还是牺牲？"],
            clarification_summary="仍需确认终局方向。",
            assumptions=[],
            reason="第五轮仍允许追问。",
        )

    monkeypatch.setattr(OutlineClarificationAgent, "clarify", fake_clarify)

    response = await service.submit_feedback(
        novel_id="n_brainstorm_round5",
        outline_type="synopsis",
        outline_ref="synopsis",
        feedback="还需要再确认一下终局。",
    )

    assert response.assistant_message.message_type == "question"
    assert response.assistant_message.meta["clarification_round"] == 5
    assert response.assistant_message.meta["max_rounds"] == 5
    assert "终局方向" in response.assistant_message.content


@pytest.mark.asyncio
async def test_submit_feedback_passes_round_six_after_five_clarification_questions(async_session, monkeypatch):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_brainstorm_round6",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={
            "synopsis_data": {
                "title": "旧总纲",
                "logline": "",
                "core_conflict": "",
                "themes": [],
                "character_arcs": [],
                "milestones": [],
                "estimated_volumes": 2,
                "estimated_total_chapters": 10,
                "estimated_total_words": 30000,
            }
        },
        volume_id=None,
        chapter_id=None,
    )

    service = OutlineWorkbenchService(async_session)
    outline_session = await OutlineSessionRepository(async_session).get_or_create(
        novel_id="n_brainstorm_round6",
        outline_type="synopsis",
        outline_ref="synopsis",
        status="awaiting_confirmation",
    )
    message_repo = OutlineMessageRepository(async_session)
    for round_number in range(1, 6):
        await message_repo.create(
            session_id=outline_session.id,
            role="assistant",
            message_type="question",
            content=f"第 {round_number} 轮问题",
            meta={
                "outline_type": "synopsis",
                "outline_ref": "synopsis",
                "interaction_stage": "generation_clarification",
                "clarification_round": round_number,
                "max_rounds": 5,
            },
        )
        await message_repo.create(
            session_id=outline_session.id,
            role="user",
            message_type="feedback",
            content=f"第 {round_number} 轮回答",
            meta={"outline_type": "synopsis", "outline_ref": "synopsis"},
        )
    await async_session.commit()

    seen_rounds = []

    async def fake_clarify(self, request):
        seen_rounds.append(request.round_number)
        return OutlineClarificationDecision(
            status="force_generate",
            confidence=1.0,
            missing_points=[],
            questions=[],
            clarification_summary="达到澄清上限，按当前设定生成。",
            assumptions=["已完成 5 轮澄清，当前回复作为最终生成依据。"],
            reason="round 6 forces generation",
        )

    optimize_calls = []

    async def fake_optimize_outline(*, novel_id, outline_type, outline_ref, feedback, context_window):
        optimize_calls.append({"feedback": feedback, "context_window": context_window})
        return {
            "content": "已生成总纲草稿。",
            "result_snapshot": {
                "title": "第六轮强制生成总纲",
                "logline": "新的故事主线",
                "core_conflict": "新的冲突",
                "themes": [],
                "character_arcs": [],
                "milestones": [],
                "estimated_volumes": 2,
                "estimated_total_chapters": 120,
                "estimated_total_words": 360000,
            },
            "conversation_summary": "达到澄清上限，按当前设定生成。",
        }

    monkeypatch.setattr(OutlineClarificationAgent, "clarify", fake_clarify)
    monkeypatch.setattr(service, "_optimize_outline", fake_optimize_outline)

    response = await service.submit_feedback(
        novel_id="n_brainstorm_round6",
        outline_type="synopsis",
        outline_ref="synopsis",
        feedback="第五轮后按现在这些答案生成。",
    )

    assert seen_rounds == [6]
    assert optimize_calls
    assert "生成假设：" in optimize_calls[0]["feedback"]
    assert response.assistant_message.message_type == "result"


@pytest.mark.asyncio
async def test_submit_feedback_generates_on_second_reply_after_clarification_question(async_session, monkeypatch):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_brainstorm_second_reply",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={
            "synopsis_data": {
                "title": "旧总纲",
                "logline": "",
                "core_conflict": "",
                "themes": [],
                "character_arcs": [],
                "milestones": [],
                "estimated_volumes": 2,
                "estimated_total_chapters": 10,
                "estimated_total_words": 30000,
            }
        },
        volume_id=None,
        chapter_id=None,
    )

    service = OutlineWorkbenchService(async_session)
    outline_session = await OutlineSessionRepository(async_session).get_or_create(
        novel_id="n_brainstorm_second_reply",
        outline_type="synopsis",
        outline_ref="synopsis",
        status="awaiting_confirmation",
    )
    await OutlineMessageRepository(async_session).create(
        session_id=outline_session.id,
        role="assistant",
        message_type="question",
        content="题材方向按哪类推进？",
        meta={
            "outline_type": "synopsis",
            "outline_ref": "synopsis",
            "interaction_stage": "generation_clarification",
            "clarification_round": 1,
            "max_rounds": 5,
        },
    )
    await async_session.commit()

    async def fake_clarify(self, request):
        assert request.round_number == 2
        return OutlineClarificationDecision(
            status="ready_to_generate",
            confidence=0.9,
            missing_points=[],
            questions=[],
            clarification_summary="用户补充了仙侠升级流和弱感情线。",
            assumptions=[],
            reason="信息足够。",
        )

    optimize_calls = []

    async def fake_optimize_outline(*, novel_id, outline_type, outline_ref, feedback, context_window):
        optimize_calls.append({"feedback": feedback, "context_window": context_window})
        return {
            "content": "已生成总纲草稿。",
            "result_snapshot": {
                "title": "二次回复生成总纲",
                "logline": "新的故事主线",
                "core_conflict": "新的冲突",
                "themes": [],
                "character_arcs": [],
                "milestones": [],
                "estimated_volumes": 2,
                "estimated_total_chapters": 120,
                "estimated_total_words": 360000,
            },
            "conversation_summary": "用户补充了仙侠升级流和弱感情线。",
        }

    monkeypatch.setattr(OutlineClarificationAgent, "clarify", fake_clarify)
    monkeypatch.setattr(service, "_optimize_outline", fake_optimize_outline)

    response = await service.submit_feedback(
        novel_id="n_brainstorm_second_reply",
        outline_type="synopsis",
        outline_ref="synopsis",
        feedback="仙侠升级流，两卷，感情线弱一些。",
    )

    assert optimize_calls
    assert response.assistant_message.message_type == "result"
    assert response.last_result_snapshot["title"] == "二次回复生成总纲"


@pytest.mark.asyncio
async def test_build_workbench_uses_workspace_drafts_during_brainstorming(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_brainstorm_workbench",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={
            "synopsis_data": {
                "title": "旧总纲",
                "logline": "",
                "core_conflict": "",
                "themes": [],
                "character_arcs": [],
                "milestones": [],
                "estimated_volumes": 2,
                "estimated_total_chapters": 10,
                "estimated_total_words": 30000,
            }
        },
        volume_id=None,
        chapter_id=None,
    )
    workspace_service = BrainstormWorkspaceService(async_session)
    await workspace_service.save_outline_draft(
        novel_id="n_brainstorm_workbench",
        outline_type="synopsis",
        outline_ref="synopsis",
        result_snapshot={
            "title": "新总纲",
            "logline": "新的故事主线",
            "core_conflict": "新的核心冲突",
            "themes": [],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 2,
            "estimated_total_chapters": 120,
            "estimated_total_words": 360000,
        },
    )
    await workspace_service.save_outline_draft(
        novel_id="n_brainstorm_workbench",
        outline_type="volume",
        outline_ref="vol_1",
        result_snapshot={
            "volume_id": "vol_1",
            "volume_number": 1,
            "title": "工作区第一卷",
            "summary": "来自工作区",
            "total_chapters": 12,
            "estimated_total_words": 120000,
            "chapters": [],
        },
    )

    service = OutlineWorkbenchService(async_session)
    payload = await service.build_workbench(
        novel_id="n_brainstorm_workbench",
        outline_type="volume",
        outline_ref="vol_1",
    )

    assert [item.outline_ref for item in payload.outline_items] == ["synopsis", "vol_1", "vol_2"]
    assert payload.outline_items[0].summary == "新的故事主线"
    assert payload.outline_items[1].title == "工作区第一卷"
    assert payload.context_window.last_result_snapshot == {
        "volume_id": "vol_1",
        "volume_number": 1,
        "title": "工作区第一卷",
        "summary": "来自工作区",
        "total_chapters": 12,
        "estimated_total_words": 120000,
        "chapters": [],
    }


@pytest.mark.asyncio
async def test_get_messages_uses_workspace_snapshot_during_brainstorming(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_brainstorm_messages",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={
            "synopsis_data": {
                "title": "旧总纲",
                "logline": "",
                "core_conflict": "",
                "themes": [],
                "character_arcs": [],
                "milestones": [],
                "estimated_volumes": 1,
                "estimated_total_chapters": 10,
                "estimated_total_words": 30000,
            }
        },
        volume_id=None,
        chapter_id=None,
    )
    workspace_service = BrainstormWorkspaceService(async_session)
    await workspace_service.save_outline_draft(
        novel_id="n_brainstorm_messages",
        outline_type="synopsis",
        outline_ref="synopsis",
        result_snapshot={
            "title": "工作区总纲",
            "logline": "工作区梗概",
            "core_conflict": "工作区冲突",
            "themes": [],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 1,
            "estimated_total_chapters": 99,
            "estimated_total_words": 300000,
        },
    )

    response = await OutlineWorkbenchService(async_session).get_messages(
        novel_id="n_brainstorm_messages",
        outline_type="synopsis",
        outline_ref="synopsis",
    )

    assert response.last_result_snapshot == {
        "title": "工作区总纲",
        "logline": "工作区梗概",
        "core_conflict": "工作区冲突",
        "themes": [],
        "character_arcs": [],
        "milestones": [],
        "estimated_volumes": 1,
        "estimated_total_chapters": 99,
        "estimated_total_words": 300000,
    }
    assert response.recent_messages == []


@pytest.mark.asyncio
async def test_get_messages_does_not_create_session_when_only_viewing(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_messages_readonly",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={
            "synopsis_data": {
                "title": "九霄行",
                "logline": "主角逆势而上",
                "core_conflict": "家仇与天命相撞",
                "themes": [],
                "character_arcs": [],
                "milestones": [],
                "estimated_volumes": 1,
                "estimated_total_chapters": 10,
                "estimated_total_words": 30000,
            }
        },
        volume_id=None,
        chapter_id=None,
    )

    response = await OutlineWorkbenchService(async_session).get_messages(
        novel_id="n_messages_readonly",
        outline_type="volume",
        outline_ref="vol_1",
    )

    assert response.session_id == ""
    assert response.recent_messages == []
    session_count = await async_session.scalar(
        select(func.count())
        .select_from(OutlineSession)
        .where(
            OutlineSession.novel_id == "n_messages_readonly",
            OutlineSession.outline_type == "volume",
            OutlineSession.outline_ref == "vol_1",
        )
    )
    assert session_count == 0


@pytest.mark.asyncio
async def test_submit_feedback_updates_workspace_without_mutating_checkpoint_during_brainstorming(async_session, monkeypatch):
    director = NovelDirector(session=async_session)
    initial_synopsis = SynopsisData(
        title="初始总纲",
        logline="旧梗概",
        core_conflict="旧冲突",
        estimated_volumes=1,
        estimated_total_chapters=10,
        estimated_total_words=30000,
    )
    await director.save_checkpoint(
        "n_brainstorm_submit",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={"synopsis_data": initial_synopsis.model_dump()},
        volume_id=None,
        chapter_id=None,
    )
    workspace_service = BrainstormWorkspaceService(async_session)
    await workspace_service.save_outline_draft(
        novel_id="n_brainstorm_submit",
        outline_type="synopsis",
        outline_ref="synopsis",
        result_snapshot=initial_synopsis.model_dump(),
    )

    service = OutlineWorkbenchService(async_session)

    async def fake_optimize_outline(*, novel_id, outline_type, outline_ref, feedback, context_window):
        return {
            "content": "已改成工作区版本。",
            "result_snapshot": {
                **initial_synopsis.model_dump(),
                "title": "工作区总纲",
                "estimated_total_chapters": 120,
                "estimated_total_words": 360000,
            },
            "setting_draft_updates": [],
            "conversation_summary": "已进入工作区草稿。",
        }

    async def fail_write_result_snapshot(**kwargs):
        raise AssertionError("brainstorming submit should not write formal checkpoint snapshots")

    monkeypatch.setattr(service, "_optimize_outline", fake_optimize_outline)
    monkeypatch.setattr(service, "_write_result_snapshot", fail_write_result_snapshot)

    response = await service.submit_feedback(
        novel_id="n_brainstorm_submit",
        outline_type="synopsis",
        outline_ref="synopsis",
        feedback="把体量拉大到 120 章。",
    )

    state = await service.novel_state_repo.get_state("n_brainstorm_submit")
    workspace = await workspace_service.get_workspace_payload("n_brainstorm_submit")

    assert state is not None
    assert state.checkpoint_data["synopsis_data"]["title"] == "初始总纲"
    assert state.checkpoint_data["synopsis_data"]["estimated_total_chapters"] == 10
    assert workspace.outline_drafts["synopsis:synopsis"]["title"] == "工作区总纲"
    assert workspace.outline_drafts["synopsis:synopsis"]["estimated_total_chapters"] == 120
    assert response.last_result_snapshot["title"] == "工作区总纲"


@pytest.mark.asyncio
async def test_submit_feedback_merges_suggestion_cards_in_brainstorm_mode(async_session, monkeypatch):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_outline_cards",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )

    service = OutlineWorkbenchService(async_session)

    async def fake_optimize_volume(**kwargs):
        return {
            "content": "已更新第一卷卷纲，并细化主要人物与关系。",
            "result_snapshot": {
                "volume_id": "vol_1",
                "volume_number": 1,
                "title": "第一卷",
                "summary": "卷一摘要",
                "total_chapters": 10,
                "estimated_total_words": 100000,
                "chapters": [],
                "entity_highlights": {"characters": ["陆照：主角"]},
                "relationship_highlights": ["陆照 / 苏清寒：互疑转合作"],
            },
            "setting_draft_updates": [],
        }

    async def fake_call_and_parse_model(*args, **kwargs):
        return SuggestionCardUpdateEnvelope(
            cards=[
                SettingSuggestionCardMergePayload(
                    operation="upsert",
                    card_id="card_rel",
                    card_type="relationship",
                    merge_key="relationship:lu-zhao:su-qinghan",
                    title="陆照 / 苏清寒",
                    summary="互疑转合作",
                    status="active",
                    source_outline_refs=["vol_1"],
                    payload={
                        "source_entity_ref": "陆照",
                        "target_entity_ref": "苏清寒",
                        "relation_type": "亦敌亦友",
                    },
                    display_order=30,
                )
            ],
            summary=SuggestionUpdateSummary(
                created=1,
                updated=0,
                superseded=0,
                unresolved=0,
            ),
        )

    monkeypatch.setattr(service, "_optimize_volume", fake_optimize_volume)
    monkeypatch.setattr(
        "novel_dev.services.outline_workbench_service.call_and_parse_model",
        fake_call_and_parse_model,
    )

    response = await service.submit_feedback(
        novel_id="novel_outline_cards",
        outline_type="volume",
        outline_ref="vol_1",
        feedback="强化第一卷主角与女主关系推进",
    )

    assert "细化主要人物与关系" in response.assistant_message.content
    assert response.setting_update_summary == {
        "created": 1,
        "updated": 0,
        "superseded": 0,
        "unresolved": 0,
    }
    workspace = await service.workspace_service.get_workspace_payload("novel_outline_cards")
    assert workspace.setting_suggestion_cards[0].merge_key == "relationship:lu-zhao:su-qinghan"
    assert response.last_result_snapshot["relationship_highlights"] == ["陆照 / 苏清寒：互疑转合作"]
