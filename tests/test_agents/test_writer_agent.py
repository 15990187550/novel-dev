import asyncio
import inspect
from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.writer_agent import WriterAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.context import ChapterContext, ChapterPlan, BeatPlan, EntityState, LocationContext
from novel_dev.schemas.quality import BeatBoundaryCard
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.llm.models import LLMResponse
from novel_dev.services.chapter_structure_guard_service import ChapterStructureGuardResult
from novel_dev.services.story_quality_service import StoryQualityService


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
        checkpoint_data={"chapter_context": context.model_dump(), "drafting_mode": "whole_chapter"},
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
    assert len(metadata.beat_coverage) == 1
    assert metadata.beat_coverage[0]["beat_index"] is None
    assert "fs_1" in metadata.embedded_foreshadowings

    ch = await ChapterRepository(async_session).get_by_id("ch_1")
    assert ch.status == "drafted"
    assert ch.raw_draft is not None

    state = await director.resume("novel_test")
    assert state.current_phase == Phase.REVIEWING.value


@pytest.mark.asyncio
async def test_longform_write_generates_whole_chapter_once(async_session):
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=3,
        title="同门试探",
        target_word_count=1200,
        beats=[
            BeatPlan(summary="王顺率先出破云式试探陆照", target_mood="tense", key_entities=["陆照", "王顺"]),
            BeatPlan(summary="陆照体内温热气流自行引导真气，拍偏王顺手腕", target_mood="strained", key_entities=["陆照", "王顺"]),
            BeatPlan(summary="王顺察觉异样但陆照暂时避开追问", target_mood="suspicious", key_entities=["陆照", "王顺"]),
        ],
        beat_boundary_cards=[
            BeatBoundaryCard(
                beat_index=0,
                must_cover=["王顺率先出手，一记破云式"],
                allowed_materials=["陆照", "王顺", "破云式"],
                forbidden_materials=["你变了", "认输离开"],
                ending_policy="停在陆照被迫应对第一招",
            ),
            BeatBoundaryCard(
                beat_index=1,
                must_cover=["陆照侧身避开", "体内温热气流自行引导真气", "拍偏王顺手腕"],
                allowed_materials=["陆照", "王顺", "体内温热气流"],
                forbidden_materials=["第二变", "第三式", "残页"],
                ending_policy="停在王顺踉跄两步和周围弟子诧异",
            ),
            BeatBoundaryCard(
                beat_index=2,
                must_cover=["王顺察觉陆照异样", "陆照选择暂时避开追问"],
                allowed_materials=["陆照", "王顺", "外门演武场"],
                forbidden_materials=["下一章", "夜探赵元"],
                ending_policy="以同门试探余波收束本章",
            ),
        ],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="外门演武场", narrative="晨雾、青石地面、槐树、兵器架、廊柱"),
        timeline_events=[],
        pending_foreshadowings=[],
    )
    await director.save_checkpoint(
        "novel_longform_chapter",
        phase=Phase.DRAFTING,
        checkpoint_data={
            "chapter_context": context.model_dump(),
            "acceptance_scope": "real-longform-volume1",
            "drafting_mode": "whole_chapter",
        },
        volume_id="vol_1",
        chapter_id="vol_1_ch_3",
    )
    await ChapterRepository(async_session).create("vol_1_ch_3", "vol_1", 3, "同门试探")

    chapter_text = (
        "王顺踏上青石地面，破云式先压向陆照肩头，逼得他在晨雾里侧身。\n\n"
        "陆照体内温热气流自行引导真气，他顺势拍偏王顺手腕，王顺踉跄两步才站稳。\n\n"
        "周围弟子一静，王顺看出异样却没有立刻点破，陆照把追问压回去，先选择避开。"
    )
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text=chapter_text)

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        mock_factory._resolve_config.return_value = None
        agent = WriterAgent(async_session)
        agent._generate_beat = AsyncMock(side_effect=AssertionError("longform should not generate beat-by-beat"))
        metadata = await agent.write("novel_longform_chapter", context, "vol_1_ch_3")

    mock_client.acomplete.assert_awaited_once()
    user_prompt = mock_client.acomplete.await_args.args[0][1].content
    assert "### 整章写作合同" in user_prompt
    assert "一次性写完整章" in user_prompt
    assert "<!--BEAT" not in user_prompt
    assert "禁止越界: 第二变；第三式；残页" in user_prompt
    assert "外门演武场" in user_prompt
    assert metadata.beat_coverage == [
        {"beat_index": None, "word_count": 101},
    ]

    ch = await ChapterRepository(async_session).get_by_id("vol_1_ch_3")
    assert "<!--BEAT" not in ch.raw_draft
    assert "窗边" not in ch.raw_draft
    assert ch.status == "drafted"


@pytest.mark.asyncio
async def test_write_generates_whole_chapter_by_default(async_session):
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=4,
        title="默认整章",
        target_word_count=1000,
        beats=[
            BeatPlan(summary="第一段推进当前目标", target_mood="tense"),
            BeatPlan(summary="第二段完成当章停点", target_mood="suspicious"),
        ],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="测试地点"),
        timeline_events=[],
        pending_foreshadowings=[],
    )
    await director.save_checkpoint(
        "novel_default_whole_chapter",
        phase=Phase.DRAFTING,
        checkpoint_data={"chapter_context": context.model_dump(), "drafting_mode": "whole_chapter"},
        volume_id="vol_1",
        chapter_id="ch_default_whole",
    )
    await ChapterRepository(async_session).create("ch_default_whole", "vol_1", 4, "默认整章")

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(
        text="第一段推进当前目标，人物在测试地点里完成选择。\n\n第二段承接阻力，并把当章停点自然落下。"
    )

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        mock_factory._resolve_config.return_value = None
        agent = WriterAgent(async_session)
        agent._generate_beat = AsyncMock(side_effect=AssertionError("write should not use single-beat generation"))
        agent._rewrite_angle = AsyncMock(side_effect=AssertionError("write should not use beat rewrite"))
        metadata = await agent.write("novel_default_whole_chapter", context, "ch_default_whole")

    mock_client.acomplete.assert_awaited_once()
    assert metadata.beat_coverage == [{"beat_index": None, "word_count": 42}]
    state = await director.resume("novel_default_whole_chapter")
    assert state.checkpoint_data["drafting_mode"] == "whole_chapter"


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
        checkpoint_data={"chapter_context": context.model_dump(), "drafting_mode": "beat_legacy"},
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
        checkpoint_data={"chapter_context": context.model_dump(), "drafting_mode": "beat_legacy"},
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


def test_conservative_fallback_keeps_multi_actor_body_flow_scene_in_current_location(async_session):
    chapter_plan = ChapterPlan(
        chapter_number=3,
        title="同门试探",
        target_word_count=1200,
        beats=[
            BeatPlan(
                summary="王顺出破云式，陆照体内温热气流自行引导真气后拍偏王顺手腕。",
                target_mood="紧张",
                key_entities=["陆照", "王顺"],
            )
        ],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="外门演武场", narrative="晨雾、青石地面、槐树、兵器架、廊柱"),
        timeline_events=[],
        pending_foreshadowings=[],
    )

    text = WriterAgent(async_session)._build_conservative_guard_fallback(
        chapter_plan.beats[0],
        context=context,
        beat_idx=0,
        is_last=False,
        guard_evidence={
            "issues": ["提前写到第二变和第三式"],
            "suggested_rewrite_focus": "只写破云式、体内气流、拍偏手腕、王顺踉跄。",
        },
    )

    assert "窗边" not in text
    assert "体内温热气流" in text
    assert "王顺" in text


@pytest.mark.asyncio
async def test_write_skips_free_rewrite_and_uses_fast_fallback_on_severe_first_guard_failure(async_session):
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=1,
        title="Test",
        target_word_count=800,
        beats=[
            BeatPlan(summary="陆照初入外门，只写见闻与忐忑。", target_mood="压抑"),
        ],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="外门院落"),
        timeline_events=[],
        pending_foreshadowings=[],
    )
    await director.save_checkpoint(
        "novel_guard_fast_fallback",
        phase=Phase.DRAFTING,
        checkpoint_data={"chapter_context": context.model_dump(), "drafting_mode": "beat_legacy"},
        volume_id="vol_guard",
        chapter_id="ch_guard_fast_fallback",
    )
    await ChapterRepository(async_session).create("ch_guard_fast_fallback", "vol_guard", 1, "Test")

    class FakeGuard:
        def __init__(self):
            self.calls = 0

        async def check_writer_beat(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return ChapterStructureGuardResult(
                    passed=False,
                    completed_current_beat=False,
                    premature_future_beat=True,
                    introduced_plan_external_fact=True,
                    changed_event_order=True,
                    issues=["提前写到后续节拍", "新增计划外玉佩线索", "改变信息顺序"],
                    suggested_rewrite_focus="停在初入外门，不要写任务与额外线索。",
                )
            assert "玉佩" not in kwargs["generated_text"]
            assert "任务" not in kwargs["generated_text"]
            return ChapterStructureGuardResult(passed=True)

    guard = FakeGuard()
    agent = WriterAgent(async_session, structure_guard=guard)
    async def fake_generate_beat(*args, **kwargs):
        return "陆照刚入外门就看见玉佩，又听见刘管事说明日任务，还顺手记下院中铜铃和门外脚步，心里转过许多不该在此时出现的念头。"

    agent._generate_beat = AsyncMock(side_effect=fake_generate_beat)
    agent._rewrite_angle = AsyncMock(side_effect=AssertionError("should not rewrite before fast fallback"))
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

    await agent.write("novel_guard_fast_fallback", context, "ch_guard_fast_fallback")

    agent._rewrite_angle.assert_not_awaited()
    ch = await ChapterRepository(async_session).get_by_id("ch_guard_fast_fallback")
    assert "玉佩" not in ch.raw_draft
    assert "任务" not in ch.raw_draft
    state = await director.resume("novel_guard_fast_fallback")
    assert state.checkpoint_data["writer_guard_fallbacks"][0]["reason"] == "writer_initial_guard_failed_fast_fallback"


@pytest.mark.asyncio
async def test_write_stops_when_conservative_fallback_guard_still_fails(async_session):
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
        checkpoint_data={"chapter_context": context.model_dump(), "drafting_mode": "beat_legacy"},
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

    with pytest.raises(RuntimeError, match="Writer beat structure guard failed"):
        await agent.write("novel_guard_fallback_degrade", context, "ch_guard_fallback_degrade")

    ch = await ChapterRepository(async_session).get_by_id("ch_guard_fallback_degrade")
    assert not ch.raw_draft
    state = await director.resume("novel_guard_fallback_degrade")
    assert state.current_phase == Phase.DRAFTING.value
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
                "canonical_constraints": ["主角长期目标: 查清家族覆灭真相"],
                "continuity_requirements": ["优先承接故事契约关键词: 玉佩"],
                "causal_links": ["beat 1 -> beat 2: 围杀头狼 触发/压向 战后分配报酬"],
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
    assert "主角长期目标" not in fallback
    assert "故事契约关键词" not in fallback
    assert "beat 1 -> beat 2" not in fallback
    assert "这一拍" not in fallback
    assert "阻力不需要另起一条线" not in fallback
    assert "他的选择也只落在眼前" not in fallback
    assert "停点收在既有风险上" not in fallback
    assert "战后分配报酬" not in fallback
    assert "试探彼此信任" not in fallback


def test_conservative_guard_fallback_turns_contract_into_prose(async_session):
    agent = WriterAgent(async_session)
    chapter_plan = ChapterPlan(
        chapter_number=1,
        title="后山禁地",
        target_word_count=1667,
        beats=[
            BeatPlan(
                summary="陆照返回外门途中撞见赵元，捕捉到对方身上一闪而逝的黑芒，选择先回房检视体内异动。",
                target_mood="suspicious",
                key_entities=["陆照", "赵元"],
            )
        ],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="玄天宗外门"),
        timeline_events=[],
        pending_foreshadowings=[],
        writing_cards=[
            {
                "beat_index": 0,
                "source_summary": (
                    "陆照返回外门途中遇到同门赵元，赵元神色匆匆，与陆照擦肩而过时肩膀相撞，"
                    "赵元眼中闪过一丝不自然的黑芒，随即恢复正常并道歉离去；"
                    "陆照敏锐捕捉到那一瞬的异样，但此刻体内温热气流再次躁动，他无暇深究，快步回到住处关紧房门；"
                    "陆照必须决定是否把“后山禁地”线索带离现场，失败代价是后续追查中断；"
                    "结尾留下与“后山禁地”直接相关的未解变化，让陆照必须在下一章继续处理。"
                ),
                "objective": "陆照沿山路返回外门住处。",
                "conflict": "赵元迎面撞来，袖口有黑芒一闪即逝。",
                "turning_point": "陆照压住询问冲动，只记住赵元的异常反应。",
                "stake": "若当场追问，陆照可能暴露自己也有异样感知。",
                "reader_takeaway": "陆照捕捉到赵元异常，却选择先保住自己的秘密。",
                "ending_hook": "残页发烫，体内气流再次躁动。",
                "required_entities": ["陆照", "赵元"],
                "required_facts": ["陆照返回外门", "赵元身上黑芒一闪", "陆照先回房检视体内异动"],
                "required_payoffs": ["陆照捕捉到赵元异常", "残页发烫"],
                "allowed_bridge_details": ["可使用山路暮色、脚步、门板、呼吸等环境与身体反应。"],
                "forbidden_future_events": ["灯火朝禁地深处行去", "赵元与道经来自同一处深渊"],
            }
        ],
    )

    fallback = agent._build_conservative_guard_fallback(
        chapter_plan.beats[0],
        context=context,
        beat_idx=0,
        is_last=True,
        guard_evidence={"issues": ["正文以大纲语言替代小说正文"]},
    )

    assert len(fallback) >= 260
    assert "失败代价是" not in fallback
    assert "结尾留下" not in fallback
    assert "读者应" not in fallback
    assert "可使用" not in fallback
    assert "灯火朝禁地深处行去" not in fallback
    assert "深渊" not in fallback
    assert "陆照" in fallback
    assert "赵元" in fallback
    assert "黑芒" in fallback
    assert "温热气流" in fallback
    assert "残页" in fallback


def test_conservative_guard_fallback_does_not_invent_scene_mechanics(async_session):
    agent = WriterAgent(async_session)
    chapter_plan = ChapterPlan(
        chapter_number=1,
        title="董事会听证",
        target_word_count=1200,
        beats=[
            BeatPlan(
                summary="林岚在董事会听证中说明系统审计差异，陈越质疑她隐瞒关键日志，她决定先提交只读快照。",
                target_mood="tense",
                key_entities=["林岚", "陈越"],
            )
        ],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="会议室"),
        timeline_events=[],
        pending_foreshadowings=[],
        writing_cards=[
            {
                "beat_index": 0,
                "source_summary": "林岚说明系统审计差异；陈越质疑关键日志；林岚提交只读快照保留复核余地。",
                "objective": "林岚说明系统审计差异。",
                "conflict": "陈越质疑她隐瞒关键日志。",
                "turning_point": "林岚决定先提交只读快照。",
                "stake": "若直接开放后台权限，复核链路会失去控制。",
                "reader_takeaway": "林岚没有逃避质疑，但保留了可验证边界。",
                "ending_hook": "只读快照里仍有一段时间戳无法解释。",
                "required_entities": ["林岚", "陈越"],
                "required_facts": ["审计差异被摆上台面", "陈越提出质疑", "林岚提交只读快照"],
                "required_payoffs": ["复核边界被保留", "异常时间戳留下疑问"],
            }
        ],
    )

    fallback = agent._build_conservative_guard_fallback(
        chapter_plan.beats[0],
        context=context,
        beat_idx=0,
        is_last=True,
        guard_evidence={"issues": ["正文以大纲语言替代小说正文"]},
    )

    assert "系统审计差异" in fallback
    assert "只读快照" in fallback
    for invented in ("袖中", "衣袂", "脚步声", "门板", "禁地", "屋外风声", "山路"):
        assert invented not in fallback


def test_conservative_guard_fallback_for_solo_inner_vision_avoids_external_intrusion(async_session):
    agent = WriterAgent(async_session)
    chapter_plan = ChapterPlan(
        chapter_number=2,
        title="异样感知",
        target_word_count=1667,
        beats=[
            BeatPlan(
                summary="陆照盘膝坐在床榻上闭目内视，发现识海中悬着几枚金色经文碎片；他以意念触碰碎片，陌生文字开始缓缓运转；陆照只能先权衡是否继续靠近异样感知。",
                target_mood="mysterious",
                key_entities=["陆照"],
            )
        ],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="外门住处"),
        timeline_events=[],
        pending_foreshadowings=[],
        writing_cards=[
            {
                "beat_index": 0,
                "objective": "陆照盘膝坐在床榻上闭目内视，发现识海中悬着几枚金色经文碎片。",
                "conflict": "经文碎片释放陌生文字，陆照看不懂却能感到其运转规律。",
                "turning_point": "陆照以意念触碰碎片，文字开始缓缓流动。",
                "stake": "继续靠近可能让识海失控，退开又会失去主动权。",
                "reader_takeaway": "陆照第一次确认识海中的经文碎片正在主动运转。",
                "ending_hook": "金色文字在识海深处留下未解的运转痕迹。",
                "required_entities": ["陆照"],
                "required_facts": ["闭目内视", "金色经文碎片", "意念触碰", "陌生文字运转"],
                "required_payoffs": ["确认经文碎片正在主动运转"],
                "allowed_bridge_details": ["可使用心跳、呼吸、冷汗、灯火摇曳等细节。"],
            }
        ],
    )

    fallback = agent._build_conservative_guard_fallback(
        chapter_plan.beats[0],
        context=context,
        beat_idx=0,
        is_last=False,
        guard_evidence={"issues": ["不得引入外部人物、脚步声、门板动作或袖中物件"]},
    )

    assert "金色经文碎片" in fallback
    assert "意念触碰" in fallback
    assert "陌生文字" in fallback
    assert "赵元" not in fallback
    assert "衣袂" not in fallback
    assert "脚步声" not in fallback
    assert "门板" not in fallback
    assert "袖中" not in fallback


def test_conservative_guard_fallback_expands_solo_multi_step_plan(async_session):
    agent = WriterAgent(async_session)
    chapter_plan = ChapterPlan(
        chapter_number=2,
        title="异样感知",
        target_word_count=1667,
        beats=[
            BeatPlan(
                summary=(
                    "陆照反复试验三次，确认感知确实大幅提升，但每次使用后丹田处的温热气流便会减弱一分；"
                    "窗外天色渐暗，他起身点燃油灯，取出袖中残页对照识海中的经文碎片，残页上的字迹与碎片运转的文字风格一致，但内容完全不同；"
                    "他将残页藏入枕下，决定明早再去后山查看。"
                ),
                target_mood="冷静分析",
                key_entities=["陆照"],
            )
        ],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="外门住处"),
        timeline_events=[],
        pending_foreshadowings=[],
        writing_cards=[
            {
                "beat_index": 0,
                "source_summary": chapter_plan.beats[0].summary,
                "objective": "陆照反复试验三次，确认感知确实大幅提升。",
                "conflict": "每次使用后丹田处的温热气流都会减弱一分。",
                "turning_point": "陆照取出袖中残页，对照识海中的经文碎片。",
                "stake": "残页与碎片风格一致但内容不同，后山线索无法收束。",
                "reader_takeaway": "陆照确认感知能力有消耗，并决定明早再去后山查看。",
                "ending_hook": "温热气流减弱，残页与经文碎片的关系仍未解开。",
                "required_entities": ["陆照"],
                "required_facts": ["试验三次", "温热气流减弱", "点燃油灯", "取出残页对照", "藏入枕下"],
                "required_payoffs": ["决定明早再去后山查看"],
                "allowed_bridge_details": ["可使用心跳、呼吸、冷汗、灯火摇曳等细节。"],
            }
        ],
    )

    fallback = agent._build_conservative_guard_fallback(
        chapter_plan.beats[0],
        context=context,
        beat_idx=0,
        is_last=True,
        guard_evidence={"issues": ["避免直接粘贴计划文本"]},
    )

    assert "第一次" in fallback
    assert "第二次" in fallback
    assert "第三次" in fallback
    assert "油灯" in fallback
    assert "残页" in fallback
    assert "枕下" in fallback
    assert "明早" in fallback
    assert "陆照反复试验三次，确认感知确实大幅提升" not in fallback
    assert "可使用" not in fallback
    assert "已有人物" not in fallback


def test_conservative_guard_fallback_filters_meta_ending_hook(async_session):
    agent = WriterAgent(async_session)
    chapter_plan = ChapterPlan(
        chapter_number=2,
        title="异样感知",
        target_word_count=1667,
        beats=[
            BeatPlan(
                summary=(
                    "陆照反复试验三次确认感知提升但温热气流减弱；"
                    "点燃油灯取出残页对照经文碎片；"
                    "藏入枕下决定明早去后山。"
                ),
                target_mood="冷静分析",
                key_entities=["陆照"],
            )
        ],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="外门住处"),
        timeline_events=[],
        pending_foreshadowings=[],
        writing_cards=[
            {
                "beat_index": 0,
                "source_summary": chapter_plan.beats[0].summary,
                "objective": "陆照反复试验三次确认感知提升。",
                "conflict": "温热气流每次都会减弱一分。",
                "turning_point": "陆照点燃油灯取出残页对照经文碎片。",
                "stake": "残页与经文碎片的关系仍未解开。",
                "reader_takeaway": "陆照确认感知能力有消耗，并决定明早去后山查看。",
                "ending_hook": "留下与异样感知直接相关的未解变化，让陆照必须在下一章继续处理。",
                "required_entities": ["陆照"],
                "required_facts": ["试验三次", "温热气流减弱", "点燃油灯", "取出残页对照", "藏入枕下"],
                "required_payoffs": ["决定明早再去后山查看"],
            }
        ],
    )

    fallback = agent._build_conservative_guard_fallback(
        chapter_plan.beats[0],
        context=context,
        beat_idx=0,
        is_last=True,
        guard_evidence={"issues": ["删除计划外赵元关联，停在残页和经文碎片的关系未解。"]},
    )

    assert "与异样感知直接相关" not in fallback
    assert "下一章继续处理" not in fallback
    assert "必须在下一章" not in fallback
    assert "残页" in fallback
    assert "经文碎片" in fallback


def test_conservative_guard_fallback_expands_sensing_range_without_future_fragments(async_session):
    agent = WriterAgent(async_session)
    chapter_plan = ChapterPlan(
        chapter_number=2,
        title="异样感知",
        target_word_count=1667,
        beats=[
            BeatPlan(
                summary=(
                    "陆照试着按照识海中文运转的轨迹调动真气，真气刚一动，他的感知骤然向外扩散——"
                    "隔壁房间王顺翻身的声音、窗外二十丈外落叶触地的震动、山脚下溪流中鱼尾拍水的波纹，全部清晰传入脑海；"
                    "他惊得猛然收功，感知瞬间缩回正常范围，额头沁出冷汗；"
                    "这种感知范围远超他当前修为应有的水平，至少达到了内门弟子的层次。"
                ),
                target_mood="震惊克制",
                key_entities=["陆照", "王顺", "感知范围远超当前修为"],
            )
        ],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="外门住处"),
        timeline_events=[],
        pending_foreshadowings=[],
        writing_cards=[
            {
                "beat_index": 0,
                "source_summary": chapter_plan.beats[0].summary,
                "objective": "陆照按照识海文字轨迹调动真气，感知骤然扩散。",
                "conflict": "王顺翻身、落叶触地、鱼尾拍水都被清晰捕捉，范围远超当前修为。",
                "turning_point": "陆照惊得猛然收功，额头沁出冷汗。",
                "stake": "继续追查会暴露异常，暂时避险又可能错过线索。",
                "reader_takeaway": "感知范围远超当前修为。",
                "ending_hook": "陆照在继续追查与暂时避险之间选择。",
                "required_entities": ["陆照", "王顺", "感知范围远超当前修为"],
                "required_facts": ["王顺翻身", "落叶触地", "鱼尾拍水", "猛然收功", "额头冷汗"],
                "required_payoffs": ["感知范围远超当前修为"],
            }
        ],
    )

    fallback = agent._build_conservative_guard_fallback(
        chapter_plan.beats[0],
        context=context,
        beat_idx=0,
        is_last=False,
        guard_evidence={"issues": ["不得提前写残页、反复试验、多枚碎片或周厉对话。"]},
    )

    assert "王顺" in fallback
    assert "落叶" in fallback
    assert "鱼尾" in fallback
    assert "猛然收功" in fallback
    assert "远超" in fallback
    assert "残页" not in fallback
    assert "几枚碎片" not in fallback
    assert "碎片明灭" not in fallback
    assert "靠近那一点光" not in fallback
    assert "周厉" not in fallback


def test_conservative_guard_fallback_filters_bridge_instruction_language(async_session):
    agent = WriterAgent(async_session)
    chapter_plan = ChapterPlan(
        chapter_number=2,
        title="异样感知",
        target_word_count=1200,
        beats=[
            BeatPlan(
                summary="主角发现感知范围异常扩大，必须先压下继续追查的冲动。",
                target_mood="震惊克制",
                key_entities=["主角"],
            )
        ],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="住处"),
        timeline_events=[],
        pending_foreshadowings=[],
        writing_cards=[
            {
                "beat_index": 0,
                "objective": "主角调动真气后发现感知范围骤然扩大。",
                "conflict": "远处细微声响同时涌入脑海，他意识到异常已经超出当前层次。",
                "turning_point": "主角猛然收功，先把真气压回丹田。",
                "stake": "继续追查会暴露异常，暂时避险又可能错过线索。",
                "required_entities": ["主角"],
                "required_facts": ["感知范围骤然扩大", "远处声响涌入脑海", "猛然收功", "真气压回丹田"],
                "required_payoffs": ["暂时按下继续追查"],
                "allowed_bridge_details": [
                    "已有人物的短动作、视线、停顿、沉默或身体反应承接当前冲突。",
                    "选择必须通过当前场景内可见动作表达，不要直接总结。",
                ],
            }
        ],
    )

    fallback = agent._build_conservative_guard_fallback(
        chapter_plan.beats[0],
        context=context,
        beat_idx=0,
        is_last=False,
        guard_evidence={"issues": ["正文混入写作卡指导语"]},
    )

    assert "感知范围" in fallback
    assert "猛然收功" in fallback
    for leaked in ("已有人物", "短动作", "承接当前冲突", "选择必须", "当前场景", "不要直接总结"):
        assert leaked not in fallback


def test_conservative_guard_fallback_avoids_plan_summary_phrasing(async_session):
    agent = WriterAgent(async_session)
    chapter_plan = ChapterPlan(
        chapter_number=2,
        title="消耗确认",
        target_word_count=1200,
        beats=[
            BeatPlan(
                summary="主角反复试验三次，发现每次动用能力都会消耗体内热流，决定暂时停手。",
                target_mood="冷静",
                key_entities=["主角"],
            )
        ],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="住处"),
        timeline_events=[],
        pending_foreshadowings=[],
        writing_cards=[
            {
                "beat_index": 0,
                "objective": "主角反复试验三次，确认能力变化并非偶然。",
                "conflict": "每次试验后体内热流都会减弱。",
                "turning_point": "第三次试验后，主角停下动作。",
                "stake": "继续试验会耗尽热流，停止又无法立刻查明缘由。",
                "required_entities": ["主角"],
                "required_facts": ["试验三次", "热流减弱", "第三次后停手"],
                "required_payoffs": ["决定暂时停手"],
            }
        ],
    )

    fallback = agent._build_conservative_guard_fallback(
        chapter_plan.beats[0],
        context=context,
        beat_idx=0,
        is_last=False,
        guard_evidence={"issues": ["避免直接粘贴计划文本"]},
    )

    assert "第一次" in fallback
    assert "第二次" in fallback
    assert "第三次" in fallback
    for meta_phrase in ("当前计划", "只能权衡", "只能守住", "不能把它直接变成新的结论", "不能替未知部分补结论"):
        assert meta_phrase not in fallback


def test_conservative_guard_fallback_ignores_reader_takeaway_and_guardrail_instructions(async_session):
    agent = WriterAgent(async_session)
    chapter_plan = ChapterPlan(
        chapter_number=3,
        title="暗室对质",
        target_word_count=1200,
        beats=[
            BeatPlan(
                summary="主角在暗室中交出账册副本，逼对方承认账目有误。",
                target_mood="tense",
                key_entities=["主角", "对方"],
            ),
            BeatPlan(
                summary="对方承认背后还有更高层授意。",
                target_mood="suspicious",
                key_entities=["主角", "对方"],
            ),
        ],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="暗室"),
        timeline_events=[],
        pending_foreshadowings=[],
        writing_cards=[
            {
                "beat_index": 0,
                "objective": "主角把账册副本放到桌上。",
                "conflict": "对方拒不承认账目有误。",
                "turning_point": "主角指出账册里被改过的日期。",
                "stake": "若证据被夺走，他会失去当场追问的主动权。",
                "reader_takeaway": "突出主角把证据摆上桌后带来的局势变化。",
                "required_entities": ["主角", "对方"],
                "required_facts": ["账册副本放到桌上", "对方拒不承认", "指出被改过的日期"],
            }
        ],
        beat_contexts=[
            {
                "beat_index": 0,
                "beat": chapter_plan.beats[0].model_dump(),
                "guardrails": [
                    "禁止描写后续承认幕后授意。",
                    "守卫要求不得提前写入第二个核心事件。",
                ],
            }
        ],
    )

    fallback = agent._build_conservative_guard_fallback(
        chapter_plan.beats[0],
        context=context,
        beat_idx=0,
        is_last=False,
        guard_evidence={"issues": ["正文混入守卫说明"]},
    )

    assert "账册" in fallback
    assert "日期" in fallback
    for leaked in ("突出主角", "局势变化", "禁止描写", "后续承认幕后授意", "守卫要求", "第二个核心事件"):
        assert leaked not in fallback


def test_conservative_guard_fallback_uses_concrete_scene_facts_for_action_beat(async_session):
    agent = WriterAgent(async_session)
    chapter_plan = ChapterPlan(
        chapter_number=3,
        title="同门试探",
        target_word_count=1600,
        beats=[
            BeatPlan(
                summary=(
                    "王顺率先出手，一记基础拳法直取陆照胸口；"
                    "陆照侧身避开，随手一掌拍在王顺手腕上，将攻势带偏；"
                    "王顺踉跄两步才站稳，周围弟子露出诧异之色；"
                    "陆照必须在继续追查“同门试探”与暂时避险之间选择，失败代价是线索被错过。"
                ),
                target_mood="紧张",
                key_entities=["陆照", "王顺"],
            ),
            BeatPlan(
                summary="王顺不服，连出七招，陆照以基础招式逐一化解。",
                target_mood="压迫",
                key_entities=["陆照", "王顺"],
            ),
        ],
    )
    writing_card = StoryQualityService.build_writing_cards(chapter_plan)[0]
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="外门演武场"),
        timeline_events=[],
        pending_foreshadowings=[],
        writing_cards=[writing_card],
    )

    fallback = agent._build_conservative_guard_fallback(
        chapter_plan.beats[0],
        context=context,
        beat_idx=0,
        is_last=False,
        guard_evidence={"issues": ["提前写入后续节拍"]},
    )

    assert "王顺率先出手" in fallback
    assert "一掌拍在王顺手腕" in fallback
    assert "周围弟子露出诧异" in fallback
    for leaked in ("必须", "失败代价", "先把眼前目标落到实处", "多余的猜测", "只看眼前已经发生的事"):
        assert leaked not in fallback


def test_conservative_guard_fallback_does_not_use_instruction_only_fields_as_material(async_session):
    agent = WriterAgent(async_session)
    chapter_plan = ChapterPlan(
        chapter_number=3,
        title="空卡兜底",
        target_word_count=1200,
        beats=[
            BeatPlan(
                summary="主角把账册放到桌上，等待对方回应。",
                target_mood="tense",
                key_entities=["主角", "对方"],
            )
        ],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="暗室"),
        timeline_events=[],
        pending_foreshadowings=[],
        writing_cards=[
            {
                "beat_index": 0,
                "reader_takeaway": "突出主角把证据摆上桌后带来的局势变化。",
                "required_entities": ["主角", "对方"],
            }
        ],
        beat_contexts=[
            {
                "beat_index": 0,
                "beat": chapter_plan.beats[0].model_dump(),
                "guardrails": ["禁止描写后续承认幕后授意。"],
            }
        ],
    )

    fallback = agent._build_conservative_guard_fallback(
        chapter_plan.beats[0],
        context=context,
        beat_idx=0,
        is_last=False,
        guard_evidence={"issues": ["正文混入指令字段"]},
    )

    assert "账册" in fallback
    assert "突出主角" not in fallback
    assert "禁止描写" not in fallback
    assert "后续承认幕后授意" not in fallback


def test_writer_self_check_blocks_meta_plan_language_and_modern_drift(async_session):
    agent = WriterAgent(async_session)
    chapter_plan = ChapterPlan(
        chapter_number=1,
        title="山门晨课",
        target_word_count=1200,
        beats=[BeatPlan(summary="陆照在晨课中忍住伤势，选择继续站稳。", target_mood="压抑")],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="山门"),
        timeline_events=[],
        pending_foreshadowings=[],
    )

    check = agent._self_check_beat(
        "他按当前计划只能权衡是否继续。他觉得这力道搁前世够把自己送进ICU。",
        chapter_plan.beats[0],
        context,
        0,
    )

    assert check.needs_rewrite is True
    assert any("规划/元叙述" in issue for issue in check.contradictions)
    assert any("ICU" in issue or "外文" in issue for issue in check.contradictions)


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
            "drafting_mode": "whole_chapter",
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
    assert metadata.beat_coverage == [{"beat_index": None, "word_count": 47}]
    chapter = await ChapterRepository(async_session).get_by_id("ch_resume_reset")
    assert chapter.raw_draft
    assert "<!--BEAT:" not in chapter.raw_draft
