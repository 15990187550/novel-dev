from novel_dev.agents.writer_agent import WriterAgent
from novel_dev.schemas.context import BeatPlan, BeatWritingCard, ChapterContext, ChapterPlan, LocationContext


def test_writer_context_message_prefers_writing_card_details():
    beat = BeatPlan(summary="陆照潜入药库", target_mood="紧张", key_entities=["陆照"])
    context = ChapterContext(
        chapter_plan=ChapterPlan(chapter_number=1, title="第一章", target_word_count=1000, beats=[beat]),
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="药库"),
        timeline_events=[],
        pending_foreshadowings=[],
        writing_cards=[
            BeatWritingCard(
                beat_index=0,
                objective="陆照要偷到寒露丹救妹妹。",
                conflict="守库执事发现药架异响，逼他交出身份牌。",
                turning_point="陆照选择暴露玉佩残光换取逃生机会。",
                required_entities=["陆照", "守库执事"],
                required_facts=["寒露丹只能从内库取得"],
                forbidden_future_events=["宗门试炼开始"],
                ending_hook="门外响起追兵脚步。",
                target_word_count=1000,
            )
        ],
    )

    message = WriterAgent(None)._build_context_message(
        beat,
        context,
        relay_history=[],
        last_beat_text="",
        idx=0,
        total=1,
        is_last=True,
    )

    assert "### 当前节拍写作卡" in message
    assert "陆照要偷到寒露丹救妹妹" in message
    assert "守库执事发现药架异响" in message
    assert "宗门试炼开始" in message
    assert "门外响起追兵脚步" in message
