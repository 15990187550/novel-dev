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
