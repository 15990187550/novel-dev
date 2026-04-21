import pytest

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.db.models import OutlineMessage
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

    async def fake_optimize_outline(*, outline_type, outline_ref, feedback, context_window):
        optimize_calls.append(
            {
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
