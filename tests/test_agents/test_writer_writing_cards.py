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
                required_payoffs=["陆照拿到寒露丹", "追兵确认他还在药库"],
                forbidden_future_events=["宗门试炼开始"],
                ending_hook="门外响起追兵脚步。",
                reader_takeaway="陆照暂时得手，但下一刻会被堵在门内。",
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
    assert "陆照拿到寒露丹" in message
    assert "正文完成效果: 陆照暂时得手" in message
    assert "读者读完应获得" not in message
    assert "宗门试炼开始" in message
    assert "门外响起追兵脚步" in message


def test_writer_context_message_sanitizes_meta_plan_language():
    beat = BeatPlan(
        summary=(
            "陆照发现识海异动；"
            "陆照推进“识海异动”时发现原计划受阻，对手或环境压力逼他立刻调整行动；"
            "若局面继续拖延，陆照会失去处理“识海异动”的主动权。"
        ),
        target_mood="紧张",
        key_entities=["陆照"],
    )
    context = ChapterContext(
        chapter_plan=ChapterPlan(chapter_number=2, title="识海异动", target_word_count=1000, beats=[beat]),
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="杂务房"),
        timeline_events=[],
        pending_foreshadowings=[],
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

    assert "陆照发现识海异动" in message
    assert "原计划受阻" not in message
    assert "对手或环境压力逼" not in message
    assert "失去处理" not in message
    assert "主动权" not in message


def test_writer_context_message_renders_ending_driver_candidates_as_soft_strategy_pool():
    beat = BeatPlan(
        summary="陆照揣着残页离开功法阁，必须避开周家弟子的视线，否则残页会被夺走。",
        target_mood="压迫",
        key_entities=["陆照", "残页", "周家弟子"],
    )
    context = ChapterContext(
        chapter_plan=ChapterPlan(chapter_number=3, title="外门困境", target_word_count=1000, beats=[beat]),
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="功法阁"),
        timeline_events=[],
        pending_foreshadowings=[],
        writing_cards=[
            BeatWritingCard(
                beat_index=0,
                objective="陆照带着残页离开功法阁",
                ending_hook="与“外门困境”直接相关的未解变化压到章末，逼得陆照下一步继续处理",
                required_payoffs=["与“外门困境”直接相关的未解变化压到章末，逼得陆照下一步继续处理"],
                ending_driver_candidates=["残页在陆照手里出现可感知变化", "周家弟子的视线让陆照下一步受限"],
                summary_risk_flags=["原章末钩子偏抽象，不可直接写成正文。"],
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

    assert "章末牵引候选" in message
    assert "残页在陆照手里出现可感知变化" in message
    assert "周家弟子的视线" in message
    assert "这些策略不是逐项硬性完成" in message
    assert "外门困境”直接相关的未解变化" not in message
