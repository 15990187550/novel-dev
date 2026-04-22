from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.db.models import OutlineMessage
from novel_dev.llm.models import LLMResponse
from novel_dev.services.brainstorm_workspace_service import BrainstormWorkspaceService
from novel_dev.repositories.outline_session_repo import OutlineSessionRepository
from novel_dev.schemas.outline import SynopsisData, VolumePlan, VolumeBeat
from novel_dev.schemas.context import BeatPlan
from novel_dev.services.outline_workbench_service import OutlineWorkbenchService


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
    assert "character_arcs: 数组,每项只包含 name / arc_summary / key_turning_points 三个字段" in prompt
    assert "milestones: 数组,每项只包含 act / summary / climax_event 三个字段" in prompt
    assert "禁止使用旧字段" in prompt
    assert "character / arc / turning_points" in prompt
    assert "name / description / chapter_range" in prompt


@pytest.mark.asyncio
async def test_submit_feedback_requests_confirmation_before_generating_missing_brainstorm_synopsis(async_session, monkeypatch):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_brainstorm_confirm",
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
        raise AssertionError("should not optimize before confirmation")

    monkeypatch.setattr(service, "_optimize_outline", fail_optimize_outline)

    response = await service.submit_feedback(
        novel_id="n_brainstorm_confirm",
        outline_type="synopsis",
        outline_ref="synopsis",
        feedback="请基于当前设定生成完整总纲草稿，补齐一句话梗概、核心冲突、卷数规模、人物弧光和关键里程碑。",
    )

    assert response.assistant_message.role == "assistant"
    assert response.assistant_message.message_type == "question"
    assert response.last_result_snapshot is None
    assert "在我开始生成总纲草稿前" in response.assistant_message.content

    session = await OutlineSessionRepository(async_session).get_or_create(
        novel_id="n_brainstorm_confirm",
        outline_type="synopsis",
        outline_ref="synopsis",
    )
    assert session.status == "awaiting_confirmation"
    assert session.last_result_snapshot is None

    workspace = await BrainstormWorkspaceService(async_session).get_workspace_payload("n_brainstorm_confirm")
    assert workspace.outline_drafts == {}


@pytest.mark.asyncio
async def test_submit_feedback_generates_after_confirmation_for_missing_brainstorm_synopsis(async_session, monkeypatch):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_brainstorm_generate",
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
    first_response = await service.submit_feedback(
        novel_id="n_brainstorm_generate",
        outline_type="synopsis",
        outline_ref="synopsis",
        feedback="请基于当前设定生成完整总纲草稿，补齐一句话梗概、核心冲突、卷数规模、人物弧光和关键里程碑。",
    )
    assert first_response.assistant_message.message_type == "question"

    optimize_calls = []

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
            "conversation_summary": "用户确认先生成完整总纲草稿。",
        }

    monkeypatch.setattr(service, "_optimize_outline", fake_optimize_outline)

    response = await service.submit_feedback(
        novel_id="n_brainstorm_generate",
        outline_type="synopsis",
        outline_ref="synopsis",
        feedback="走仙侠升级流，预计两卷，感情线弱一些，确认按这个方向生成。",
    )

    assert optimize_calls and optimize_calls[0]["outline_type"] == "synopsis"
    assert "确认按这个方向生成" in optimize_calls[0]["feedback"]
    assert response.assistant_message.message_type == "result"
    assert response.last_result_snapshot["title"] == "新总纲"

    session = await OutlineSessionRepository(async_session).get_or_create(
        novel_id="n_brainstorm_generate",
        outline_type="synopsis",
        outline_ref="synopsis",
    )
    assert session.status == "active"
    assert session.last_result_snapshot["title"] == "新总纲"

    workspace = await BrainstormWorkspaceService(async_session).get_workspace_payload("n_brainstorm_generate")
    assert workspace.outline_drafts["synopsis:synopsis"]["title"] == "新总纲"


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
