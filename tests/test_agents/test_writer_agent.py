import asyncio
import inspect
from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.writer_agent import WriterAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.context import ChapterContext, ChapterPlan, BeatPlan, EntityState, LocationContext
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.llm.models import LLMResponse
from novel_dev.services.chapter_structure_guard_service import ChapterStructureGuardResult


def test_write_does_not_fire_and_forget_chapter_indexing():
    source = inspect.getsource(WriterAgent.write)
    assert "create_task(self.embedding_service.index_chapter" not in source


def test_writing_rules_require_motivated_character_turns(async_session):
    rules = WriterAgent(async_session)._build_writing_rules_block(is_last=False)

    assert "写作方向" in rules
    assert "读者读感" in rules
    assert "动作、对话、物件" in rules
    assert "人物态度转折" in rules
    assert "触发点" in rules
    assert "犹豫/识别" in rules
    assert "选择代价" in rules
    assert "当场目标" in rules
    assert "可见阻力" in rules
    assert "策略/态度变化" in rules
    assert "具体停点" in rules
    assert "试探、保留、误判或代价" in rules
    assert "既有线索" in rules
    assert "当场后果" in rules
    assert "下一步疑问或风险余波" in rules
    assert "角色处境" in rules
    assert "禁用词表" not in rules
    assert "写作硬约束" not in rules


@pytest.mark.asyncio
async def test_write_draft_success(async_session):
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=1,
        title="Test",
        target_word_count=2000,
        beats=[
            BeatPlan(summary="开场", target_mood="压抑"),
            BeatPlan(summary="冲突", target_mood="紧张"),
        ],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[{"id": "fs_1", "content": "玉佩发光", "role_in_chapter": "embed"}],
    )
    await director.save_checkpoint(
        "novel_test",
        phase=Phase.DRAFTING,
        checkpoint_data={"chapter_context": context.model_dump()},
        volume_id="vol_1",
        chapter_id="ch_1",
    )
    await ChapterRepository(async_session).create("ch_1", "vol_1", 1, "Test")

    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text="开场节拍生成的正文内容，字数足够多，情节跌宕起伏，引人入胜，令人难以忘怀。这是第一段非常详细的描写，包含了丰富的场景和人物心理活动，忽然玉佩发光。"),
        LLMResponse(text="冲突节拍生成的正文内容，字数足够多，矛盾尖锐，冲突激烈，让读者欲罢不能。这是第二段非常详细的描写，包含了紧张的对话和激烈的动作场面。"),
    ]

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = WriterAgent(async_session)
        metadata = await agent.write("novel_test", context, "ch_1")

    assert metadata.total_words > 0
    assert len(metadata.beat_coverage) == 2
    assert "fs_1" in metadata.embedded_foreshadowings

    ch = await ChapterRepository(async_session).get_by_id("ch_1")
    assert ch.status == "drafted"
    assert ch.raw_draft is not None

    state = await director.resume("novel_test")
    assert state.current_phase == Phase.REVIEWING.value


@pytest.mark.asyncio
async def test_write_awaits_chapter_indexing(async_session):
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=1,
        title="Test",
        target_word_count=800,
        beats=[BeatPlan(summary="开场", target_mood="压抑")],
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
        "novel_index_wait",
        phase=Phase.DRAFTING,
        checkpoint_data={"chapter_context": context.model_dump()},
        volume_id="vol_1",
        chapter_id="ch_index_wait",
    )
    await ChapterRepository(async_session).create("ch_index_wait", "vol_1", 1, "Test")

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="这是一个足够长的节拍正文内容，人物行动明确，场景推进稳定，读起来完整自然。")
    started = asyncio.Event()
    release = asyncio.Event()
    embedding_service = AsyncMock()

    async def index_chapter(chapter_id):
        assert chapter_id == "ch_index_wait"
        started.set()
        await release.wait()

    embedding_service.index_chapter.side_effect = index_chapter

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        mock_factory._resolve_config.return_value = None
        agent = WriterAgent(async_session, embedding_service=embedding_service)
        write_task = asyncio.create_task(agent.write("novel_index_wait", context, "ch_index_wait"))
        await started.wait()
        for _ in range(20):
            await asyncio.sleep(0)
        assert write_task.done() is False
        release.set()
        await write_task

    embedding_service.index_chapter.assert_awaited_once_with("ch_index_wait")


@pytest.mark.asyncio
async def test_write_missing_context(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_no_ctx",
        phase=Phase.DRAFTING,
        checkpoint_data={},
        volume_id="vol_1",
        chapter_id="ch_1",
    )
    context = ChapterContext(
        chapter_plan=ChapterPlan(chapter_number=1, title="T", target_word_count=100, beats=[]),
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[],
    )
    agent = WriterAgent(async_session)
    with pytest.raises(ValueError, match="chapter_context missing"):
        await agent.write("novel_no_ctx", context, "ch_1")


@pytest.mark.asyncio
async def test_write_rewrites_once_when_structure_guard_fails(async_session):
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=1,
        title="Test",
        target_word_count=800,
        beats=[
            BeatPlan(summary="林照发现玉佩", target_mood="tense"),
            BeatPlan(summary="追兵赶到", target_mood="danger"),
        ],
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
        "novel_guard_rewrite",
        phase=Phase.DRAFTING,
        checkpoint_data={"chapter_context": context.model_dump()},
        volume_id="vol_guard",
        chapter_id="ch_guard",
    )
    await ChapterRepository(async_session).create("ch_guard", "vol_guard", 1, "Test")

    class FakeGuard:
        def __init__(self):
            self.calls = 0

        async def check_writer_beat(self, **kwargs):
            self.calls += 1
            if kwargs["beat_index"] == 0 and self.calls == 1:
                return ChapterStructureGuardResult(
                    passed=False,
                    completed_current_beat=True,
                    premature_future_beat=True,
                    introduced_plan_external_fact=False,
                    changed_event_order=False,
                    issues=["提前写到后续节拍"],
                    suggested_rewrite_focus="停在玉佩发现，不要写追兵赶到",
                )
            return ChapterStructureGuardResult(passed=True)

    guard = FakeGuard()
    agent = WriterAgent(async_session, structure_guard=guard)
    agent._generate_beat = AsyncMock(side_effect=[
        "<!--BEAT:0-->\n林照在尘封供桌下发现玉佩，冷意沿着掌心钻入袖口，他屏住呼吸，只听见门外风声渐紧，仍没有任何人闯入屋内。\n<!--/BEAT:0-->",
        "<!--BEAT:1-->\n追兵赶到，靴底踏碎门槛前的积雪，林照被迫后退半步，指节扣紧袖中的玉佩，视线扫过侧窗、倒塌香案和未灭的油灯，寻找从混乱里脱身的空隙。\n<!--/BEAT:1-->",
    ])
    agent._rewrite_angle = AsyncMock(return_value="林照发现玉佩，将它藏入袖中，指腹压住玉面上细小的裂痕。屋外风雪拍门，他没有急着起身，只把呼吸放得更轻。")
    agent._generate_relay = AsyncMock(return_value=type(
        "Relay",
        (),
        {
            "scene_state": "state",
            "emotional_tone": "tense",
            "new_info_revealed": "",
            "open_threads": "",
            "next_beat_hook": "",
            "model_dump": lambda self: {
            "scene_state": self.scene_state,
                "emotional_tone": self.emotional_tone,
                "new_info_revealed": self.new_info_revealed,
                "open_threads": self.open_threads,
                "next_beat_hook": self.next_beat_hook,
            },
        },
    )())

    await agent.write("novel_guard_rewrite", context, "ch_guard")

    agent._rewrite_angle.assert_awaited_once()
    state = await director.resume("novel_guard_rewrite")
    assert state.checkpoint_data["writer_guard_failures"][0]["beat_index"] == 0
    ch = await ChapterRepository(async_session).get_by_id("ch_guard")
    assert "林照发现玉佩，将它藏入袖中" in ch.raw_draft


@pytest.mark.asyncio
async def test_write_uses_conservative_fallback_when_guard_retry_fails(async_session):
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=1,
        title="Test",
        target_word_count=800,
        beats=[
            BeatPlan(summary="林照被外门同门克扣口粮后隐忍，将注意力放回残卷运转异常。", target_mood="压抑"),
        ],
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
        "novel_guard_fallback",
        phase=Phase.DRAFTING,
        checkpoint_data={"chapter_context": context.model_dump()},
        volume_id="vol_guard",
        chapter_id="ch_guard_fallback",
    )
    await ChapterRepository(async_session).create("ch_guard_fallback", "vol_guard", 1, "Test")

    class FakeGuard:
        def __init__(self):
            self.calls = 0

        async def check_writer_beat(self, **kwargs):
            self.calls += 1
            if self.calls <= 2:
                return ChapterStructureGuardResult(
                    passed=False,
                    completed_current_beat=True,
                    introduced_plan_external_fact=True,
                    issues=["新增计划外人物张横"],
                    suggested_rewrite_focus="删除计划外人物，回到同门群体压力。",
                )
            assert "张横" not in kwargs["generated_text"]
            assert "外门同门" in kwargs["generated_text"]
            return ChapterStructureGuardResult(passed=True)

    guard = FakeGuard()
    agent = WriterAgent(async_session, structure_guard=guard)
    agent._generate_beat = AsyncMock(return_value="张横拦住林照，执法长老也站在门外。")
    agent._rewrite_angle = AsyncMock(return_value="张横继续挑衅林照，执法长老提起林家叛宗案。")
    agent._generate_relay = AsyncMock(return_value=type(
        "Relay",
        (),
        {
            "scene_state": "state",
            "emotional_tone": "tense",
            "new_info_revealed": "",
            "open_threads": "",
            "next_beat_hook": "",
            "model_dump": lambda self: {
                "scene_state": self.scene_state,
                "emotional_tone": self.emotional_tone,
                "new_info_revealed": self.new_info_revealed,
                "open_threads": self.open_threads,
                "next_beat_hook": self.next_beat_hook,
            },
        },
    )())

    await agent.write("novel_guard_fallback", context, "ch_guard_fallback")

    ch = await ChapterRepository(async_session).get_by_id("ch_guard_fallback")
    assert "外门同门" in ch.raw_draft
    assert "残卷运转异常" in ch.raw_draft
    assert "张横" not in ch.raw_draft
    state = await director.resume("novel_guard_fallback")
    assert state.checkpoint_data["writer_guard_failures"][-1]["mode"] == "writer_retry"
    assert state.checkpoint_data["writer_guard_fallbacks"][0]["beat_index"] == 0


@pytest.mark.asyncio
async def test_write_degrades_to_conservative_fallback_when_fallback_guard_still_fails(async_session):
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=1,
        title="Test",
        target_word_count=800,
        beats=[
            BeatPlan(summary="陆照跟踪赵厉，确认身份后选择先撤离，不提前进入深夜返住处。", target_mood="tense"),
        ],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="外门集市"),
        timeline_events=[],
        pending_foreshadowings=[],
        writing_cards=[{
            "beat_index": 0,
            "objective": "确认赵厉身份后先撤离。",
            "required_facts": ["陆照跟踪赵厉", "确认身份", "先撤离"],
            "forbidden_future_events": ["深夜返回住处", "宗门暗流涌动"],
        }],
    )
    await director.save_checkpoint(
        "novel_guard_fallback_degrade",
        phase=Phase.DRAFTING,
        checkpoint_data={"chapter_context": context.model_dump()},
        volume_id="vol_guard",
        chapter_id="ch_guard_fallback_degrade",
    )
    await ChapterRepository(async_session).create("ch_guard_fallback_degrade", "vol_guard", 1, "Test")

    class FakeGuard:
        def __init__(self):
            self.calls = 0

        async def check_writer_beat(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return ChapterStructureGuardResult(
                    passed=False,
                    completed_current_beat=True,
                    premature_future_beat=True,
                    issues=["提前写到后续节拍"],
                    suggested_rewrite_focus="停在确认身份后撤离。",
                )
            if self.calls == 2:
                return ChapterStructureGuardResult(
                    passed=False,
                    completed_current_beat=False,
                    premature_future_beat=True,
                    introduced_plan_external_fact=True,
                    issues=["仍然混入深夜返住处", "新增计划外宗门暗流"],
                    suggested_rewrite_focus="删除后续节拍元素。",
                )
            return ChapterStructureGuardResult(
                passed=False,
                completed_current_beat=True,
                premature_future_beat=False,
                introduced_plan_external_fact=False,
                issues=["表述仍偏强，但已收束在当前节拍"],
                suggested_rewrite_focus="保持当前节拍收束。",
            )

    guard = FakeGuard()
    agent = WriterAgent(async_session, structure_guard=guard)
    agent._generate_beat = AsyncMock(return_value="陆照在集市认出赵厉，深夜回住处时察觉宗门暗流已至。")
    agent._rewrite_angle = AsyncMock(return_value="陆照跟着赵厉穿过廊道，回住处后才决定明日再查。")
    agent._generate_relay = AsyncMock(return_value=type(
        "Relay",
        (),
        {
            "scene_state": "state",
            "emotional_tone": "tense",
            "new_info_revealed": "",
            "open_threads": "",
            "next_beat_hook": "",
            "model_dump": lambda self: {
                "scene_state": self.scene_state,
                "emotional_tone": self.emotional_tone,
                "new_info_revealed": self.new_info_revealed,
                "open_threads": self.open_threads,
                "next_beat_hook": self.next_beat_hook,
            },
        },
    )())

    await agent.write("novel_guard_fallback_degrade", context, "ch_guard_fallback_degrade")

    ch = await ChapterRepository(async_session).get_by_id("ch_guard_fallback_degrade")
    assert "陆照" in ch.raw_draft
    assert "赵厉" in ch.raw_draft
    assert "撤" in ch.raw_draft or "先" in ch.raw_draft
    state = await director.resume("novel_guard_fallback_degrade")
    assert state.current_phase == Phase.REVIEWING.value
    assert state.checkpoint_data["writer_guard_fallbacks"][0]["reason"] == "writer_retry_and_fallback_guard_failed"


def test_conservative_guard_fallback_prefers_current_beat_contract(async_session):
    agent = WriterAgent(async_session)
    chapter_plan = ChapterPlan(
        chapter_number=5,
        title="山谷伏杀",
        target_word_count=2400,
        beats=[
            BeatPlan(summary="三人合力设伏围杀头狼，陆照刻意保留实力，暗中观察李大牛与王明月的战斗习惯。", target_mood="tense"),
            BeatPlan(summary="战后分配报酬，并试探彼此信任。", target_mood="suspicious"),
        ],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="山谷"),
        timeline_events=[],
        pending_foreshadowings=[],
        writing_cards=[
            {
                "beat_index": 0,
                "objective": "围住头狼，把它逼回陷坑边。",
                "conflict": "头狼扑击凶猛，阵型稍乱就会被撕开口子。",
                "turning_point": "陆照压住真实实力，只在关键一线补位。",
                "required_entities": ["陆照", "李大牛", "王明月"],
                "required_facts": ["三人合力设伏围杀头狼", "陆照刻意保留实力", "暗中观察李大牛与王明月的战斗习惯"],
                "forbidden_future_events": ["战后分配报酬", "试探彼此信任"],
                "reader_takeaway": "这一拍必须让读者看见战斗中的配合、保留与观察。",
            },
            {
                "beat_index": 1,
                "objective": "分报酬并互相试探。",
            },
        ],
        beat_contexts=[
            {
                "beat_index": 0,
                "beat": chapter_plan.beats[0].model_dump(),
                "guardrails": ["只写围杀头狼过程，不进入战后谈话。"],
            }
        ],
    )

    fallback = agent._build_conservative_guard_fallback(
        chapter_plan.beats[0],
        context=context,
        beat_idx=0,
        is_last=False,
        guard_evidence={
            "issues": [
                "当前beat的核心事件是战斗中刻意保留实力，暗中观察二人战斗习惯。",
                "正文提前写了战后分配报酬和试探信任。",
            ]
        },
    )

    assert "围" in fallback or "头狼" in fallback
    assert "保留实力" in fallback
    assert "观察" in fallback
    assert "战后分配报酬" not in fallback
    assert "试探彼此信任" not in fallback


def test_trim_repeated_prefix_from_previous_removes_cross_beat_duplicate(async_session):
    agent = WriterAgent(async_session)
    previous = (
        "陆照后背抵上门板，袖袋里蛇血硌着腕骨。\n\n"
        "不是同一个人。是同一脉。\n\n"
        "拇指指甲掐进食指，疼让。"
    )
    current = (
        "陆照后背抵上门板，袖袋里蛇血硌着腕骨。\n\n"
        "不是同一个人。是同一脉。\n\n"
        "拇指指甲掐进食指，疼让他回神。油灯没点，他从枕下摸出粗纸。"
    )

    trimmed = agent._trim_repeated_prefix_from_previous(previous, current)

    assert trimmed.startswith("拇指指甲掐进食指，疼让他回神。")
    assert "不是同一个人。是同一脉。" not in trimmed


@pytest.mark.asyncio
async def test_write_wrong_phase(async_session):
    director = NovelDirector(session=async_session)
    plan = ChapterPlan(chapter_number=1, title="T", target_word_count=100, beats=[])
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
        "novel_wrong",
        phase=Phase.REVIEWING,
        checkpoint_data={"chapter_context": context.model_dump()},
        volume_id="vol_1",
        chapter_id="ch_1",
    )
    agent = WriterAgent(async_session)
    with pytest.raises(ValueError, match="Cannot write draft"):
        await agent.write("novel_wrong", context, "ch_1")


@pytest.mark.asyncio
async def test_write_resets_stale_resume_progress_when_chapter_has_no_draft(async_session):
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=11,
        title="Resume Reset",
        target_word_count=1200,
        beats=[
            BeatPlan(summary="开场试探", target_mood="tense"),
            BeatPlan(summary="确认线索", target_mood="suspicious"),
            BeatPlan(summary="夜里记档", target_mood="cold"),
        ],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="后山"),
        timeline_events=[],
        pending_foreshadowings=[],
    )
    await director.save_checkpoint(
        "novel_resume_reset",
        phase=Phase.DRAFTING,
        checkpoint_data={
            "chapter_context": context.model_dump(),
            "drafting_progress": {"beat_index": 3, "total_beats": 3, "current_word_count": 9999},
            "relay_history": [{"scene_state": "stale"}],
        },
        volume_id="vol_1",
        chapter_id="ch_resume_reset",
    )
    await ChapterRepository(async_session).create("ch_resume_reset", "vol_1", 11, "Resume Reset")

    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text="第一拍正文足够长，人物进入后山，故意把话只说半句，气氛紧绷，读者能看见他在观察同伴与地形变化。"),
        LLMResponse(text="第二拍正文足够长，线索逐渐被确认，人物动作、对话和怀疑同步推进，没有跳到结尾。"),
        LLMResponse(text="第三拍正文足够长，回到夜里整理线索，留下新的危险信号，形成完整停点。"),
    ]

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        mock_factory._resolve_config.return_value = None
        agent = WriterAgent(async_session)
        agent._self_check_beat = lambda *args, **kwargs: type(
            "BeatCheck",
            (),
            {
                "needs_rewrite": False,
                "missing_entities": [],
                "missing_foreshadowings": [],
                "contradictions": [],
            },
        )()
        agent._rewrite_angle = AsyncMock(return_value="重写后的正文足够长，人物动作、判断和局势变化都落在当前节拍里，没有越界，也不会触发新的结构问题。")
        agent._guard_writer_beat = AsyncMock(side_effect=lambda **kwargs: (kwargs["inner"], f"<!--BEAT:{kwargs['idx']}-->\n{kwargs['inner']}\n<!--/BEAT:{kwargs['idx']}-->"))
        agent._enforce_beat_word_budget = AsyncMock(side_effect=lambda **kwargs: (kwargs["inner"], f"<!--BEAT:{kwargs['idx']}-->\n{kwargs['inner']}\n<!--/BEAT:{kwargs['idx']}-->"))
        agent._generate_relay = AsyncMock(return_value=type(
            "Relay",
            (),
            {
                "scene_state": "state",
                "emotional_tone": "tone",
                "new_info_revealed": "",
                "open_threads": "",
                "next_beat_hook": "",
                "model_dump": lambda self: {
                    "scene_state": self.scene_state,
                    "emotional_tone": self.emotional_tone,
                    "new_info_revealed": self.new_info_revealed,
                    "open_threads": self.open_threads,
                    "next_beat_hook": self.next_beat_hook,
                },
            },
        )())
        metadata = await agent.write("novel_resume_reset", context, "ch_resume_reset")

    assert metadata.total_words > 0
    assert len(metadata.beat_coverage) == 3
    chapter = await ChapterRepository(async_session).get_by_id("ch_resume_reset")
    assert chapter.raw_draft
    assert "<!--BEAT:0-->" in chapter.raw_draft
    assert "<!--BEAT:2-->" in chapter.raw_draft
