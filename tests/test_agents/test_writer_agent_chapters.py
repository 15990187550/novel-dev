from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.writer_agent import WriterAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.context import ChapterContext, ChapterPlan, BeatPlan, LocationContext
from novel_dev.schemas.similar_document import SimilarDocument
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.llm.models import LLMResponse
from novel_dev.genres.defaults import default_genre
from novel_dev.genres.models import ResolvedGenreTemplate


@pytest.mark.asyncio
async def test_multi_message_prompt_structure(async_session):
    """Verify WriterAgent uses system + user messages (not single message dump)."""
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=1,
        title="Test",
        target_word_count=2000,
        beats=[BeatPlan(summary="开场", target_mood="压抑")],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={"style_guide": "简洁有力"},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[],
        similar_chapters=[],
    )
    await director.save_checkpoint(
        "novel_test_multi",
        phase=Phase.DRAFTING,
        checkpoint_data={"chapter_context": context.model_dump()},
        volume_id="vol_1",
        chapter_id="ch_multi",
    )
    await ChapterRepository(async_session).create("ch_multi", "vol_1", 1, "Test")

    captured_messages = []

    def capture_prompt(agent, task=None):
        mock = AsyncMock()

        async def acomplete(messages, config=None):
            captured_messages.append(messages)
            return LLMResponse(
                text="这是一个很长的节拍正文内容，字数足够多，情节跌宕起伏，引人入胜，令人难以忘怀。"
            )

        mock.acomplete.side_effect = acomplete
        return mock

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.side_effect = capture_prompt
        mock_factory._resolve_config.return_value = None
        agent = WriterAgent(async_session)
        await agent.write("novel_test_multi", context, "ch_multi")

    # generation call should have system + user messages
    beat_messages = captured_messages[0]
    assert len(beat_messages) >= 2
    assert beat_messages[0].role == "system"
    assert beat_messages[1].role == "user"

    # System prompt should contain rules, not worldview dump
    system = beat_messages[0].content
    assert "写作方向" in system
    assert "读者读感" in system
    assert "简洁有力" in system

    # User prompt should contain whole-chapter contract and beat info
    user = beat_messages[1].content
    assert "整章写作合同" in user
    assert "#### beat 0" in user
    assert "开场" in user
    assert "<!--BEAT" not in user


@pytest.mark.asyncio
async def test_prompt_does_not_contain_full_context_dump(async_session):
    """Verify the old context.model_dump_json() pattern is gone."""
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=1,
        title="Test",
        target_word_count=2000,
        beats=[BeatPlan(summary="开场", target_mood="压抑")],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="这段世界观不应该出现在用户消息中" * 50,
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[],
        similar_chapters=[],
    )
    await director.save_checkpoint(
        "novel_test_nodump",
        phase=Phase.DRAFTING,
        checkpoint_data={"chapter_context": context.model_dump()},
        volume_id="vol_1",
        chapter_id="ch_nodump",
    )
    await ChapterRepository(async_session).create("ch_nodump", "vol_1", 1, "Test")

    captured_messages = []

    def capture_prompt(agent, task=None):
        mock = AsyncMock()

        async def acomplete(messages, config=None):
            captured_messages.append(messages)
            return LLMResponse(
                text="这是一个很长的节拍正文内容，字数足够多，情节跌宕起伏，引人入胜，令人难以忘怀。"
            )

        mock.acomplete.side_effect = acomplete
        return mock

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.side_effect = capture_prompt
        mock_factory._resolve_config.return_value = None
        agent = WriterAgent(async_session)
        await agent.write("novel_test_nodump", context, "ch_nodump")

    # User message should NOT contain the full worldview dump
    beat_messages = captured_messages[0]
    user_content = beat_messages[1].content
    assert "这段世界观不应该出现在用户消息中" not in user_content


@pytest.mark.asyncio
async def test_writer_prompt_carries_story_contract_goal(async_session):
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=1,
        title="Test",
        target_word_count=2000,
        beats=[BeatPlan(summary="林照发现祠堂里的玉佩", target_mood="压抑")],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="祠堂"),
        timeline_events=[],
        pending_foreshadowings=[],
        story_contract={
            "protagonist_goal": "追查家族覆灭真相",
            "current_stage_goal": "找到父亲玉佩里的第一条线索",
            "first_chapter_goal": "让林照确认玉佩与覆灭真相有关",
            "must_carry_forward": ["父亲玉佩"],
        },
    )
    await director.save_checkpoint(
        "novel_test_contract",
        phase=Phase.DRAFTING,
        checkpoint_data={"chapter_context": context.model_dump()},
        volume_id="vol_1",
        chapter_id="ch_contract",
    )
    await ChapterRepository(async_session).create("ch_contract", "vol_1", 1, "Test")

    captured_messages = []

    def capture_prompt(agent, task=None):
        mock = AsyncMock()

        async def acomplete(messages, config=None):
            captured_messages.append(messages)
            return LLMResponse(text="林照在祠堂里握住玉佩，寒意顺着掌心蔓延，他终于确认父亲留下的线索仍在。")

        mock.acomplete.side_effect = acomplete
        return mock

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.side_effect = capture_prompt
        mock_factory._resolve_config.return_value = None
        agent = WriterAgent(async_session)
        await agent.write("novel_test_contract", context, "ch_contract")

    user = captured_messages[0][1].content
    assert "故事契约" in user
    assert "追查家族覆灭真相" in user
    assert "整章推进要服务长期目标" in user


@pytest.mark.asyncio
async def test_writer_prompt_includes_resolved_genre_rules(async_session):
    from novel_dev.db.models import NovelState
    from novel_dev.agents.writer_agent import WriterAgent
    from novel_dev.schemas.context import BeatPlan, ChapterContext, ChapterPlan, LocationContext

    async_session.add(
        NovelState(
            novel_id="n_writer_genre",
            current_phase="drafting",
            checkpoint_data={
                "genre": {
                    "primary_slug": "xuanhuan",
                    "primary_name": "玄幻",
                    "secondary_slug": "zhutian",
                    "secondary_name": "诸天文",
                }
            },
        )
    )
    await async_session.commit()

    captured = {}

    async def fake_generate(*args, **kwargs):
        captured["system"] = args[0][0].content
        return type("Resp", (), {"text": "他按住呼吸，沿着既定规则推进。"})

    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = fake_generate

    agent = WriterAgent(async_session)
    beat = BeatPlan(summary="主角在规则压力下做出选择。", target_mood="紧张", target_word_count=300)
    context = ChapterContext(
        chapter_plan=ChapterPlan(chapter_number=1, title="第一章", target_word_count=800, beats=[beat]),
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="测试场景"),
        timeline_events=[],
        pending_foreshadowings=[],
        story_contract={},
    )
    with patch("novel_dev.llm.llm_factory.get", return_value=mock_client), patch(
        "novel_dev.llm.llm_factory._resolve_config",
        return_value={},
    ):
        await agent._generate_beat(beat, context, [], "", 0, 1, True, novel_id="n_writer_genre")

    assert "互联网黑话" in captured["system"]
    assert "跨世界" in captured["system"]


@pytest.mark.asyncio
async def test_writer_prompt_without_novel_id_skips_genre_resolution(async_session):
    from novel_dev.agents.writer_agent import WriterAgent
    from novel_dev.schemas.context import BeatPlan, ChapterContext, ChapterPlan, LocationContext

    captured = {}

    async def fake_generate(*args, **kwargs):
        captured["system"] = args[0][0].content
        return type("Resp", (), {"text": "他按住呼吸，沿着既定规则推进。"})

    async def fail_resolve(*args, **kwargs):
        raise AssertionError("GenreTemplateService.resolve should not be called without novel_id")

    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = fake_generate

    agent = WriterAgent(async_session)
    beat = BeatPlan(summary="主角在压力下做出选择。", target_mood="紧张", target_word_count=300)
    context = ChapterContext(
        chapter_plan=ChapterPlan(chapter_number=1, title="第一章", target_word_count=800, beats=[beat]),
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="测试场景"),
        timeline_events=[],
        pending_foreshadowings=[],
        story_contract={},
    )

    with patch("novel_dev.llm.llm_factory.get", return_value=mock_client), patch(
        "novel_dev.llm.llm_factory._resolve_config",
        return_value={},
    ), patch(
        "novel_dev.agents.writer_agent.GenreTemplateService.resolve",
        side_effect=fail_resolve,
    ):
        await agent._generate_beat(beat, context, [], "", 0, 1, True, novel_id="")

    assert "Genre setting rules" not in captured["system"]
    assert "跨世界" not in captured["system"]


def test_writer_prompt_uses_non_formulaic_reader_pull():
    from novel_dev.agents.writer_agent import WriterAgent
    from novel_dev.schemas.context import BeatPlan, ChapterContext, ChapterPlan, LocationContext

    agent = WriterAgent.__new__(WriterAgent)
    beat = BeatPlan(summary="主角在压力下做出选择。", target_mood="紧张", target_word_count=300)
    context = ChapterContext(
        chapter_plan=ChapterPlan(chapter_number=1, title="第一章", target_word_count=800, beats=[beat]),
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="测试场景"),
        timeline_events=[],
        pending_foreshadowings=[],
        story_contract={},
    )

    prompt = agent._build_system_prompt(context, True)

    assert "不要为了满足形式要求机械添加对话、动作、感官或悬念" in prompt
    assert "优先判断当前场景最自然的表达方式" in prompt
    assert "更具体的阅读期待" in prompt
    assert "信息差、关系变化、行动压力、情绪余波、环境异常或人物选择" in prompt
    assert "对话占比" not in prompt
    assert "30%-50%" not in prompt


def test_writer_prompt_uses_compiled_style_contract_instead_of_raw_json():
    from novel_dev.agents.writer_agent import WriterAgent
    from novel_dev.schemas.context import BeatPlan, ChapterContext, ChapterPlan, LocationContext

    agent = WriterAgent.__new__(WriterAgent)
    beat = BeatPlan(summary="主角在压力下做出选择。", target_mood="紧张", target_word_count=300)
    context = ChapterContext(
        chapter_plan=ChapterPlan(chapter_number=1, title="第一章", target_word_count=800, beats=[beat]),
        style_profile={
            "style_guide": "克制、具体。",
            "narrative_rules": ["先写动作，再显出信息差。"],
            "character_rules": ["用停顿和避让呈现关系压力。"],
            "anti_ai_rules": ["不要段尾升华。"],
        },
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="测试场景"),
        timeline_events=[],
        pending_foreshadowings=[],
        story_contract={},
    )

    prompt = agent._build_system_prompt(context, True)

    assert "### 写法合同" in prompt
    assert "#### 叙事规则" in prompt
    assert "先写动作" in prompt
    assert "#### 角色表达" in prompt
    assert "停顿和避让" in prompt
    assert "#### 反AI风险" in prompt
    assert '"style_guide"' not in prompt
    assert '"narrative_rules"' not in prompt


def test_whole_chapter_prompt_uses_narrative_variables_and_scene_fuel():
    from novel_dev.agents.writer_agent import WriterAgent
    from novel_dev.schemas.context import BeatPlan, BeatWritingCard, ChapterContext, ChapterPlan, LocationContext

    agent = WriterAgent.__new__(WriterAgent)
    beat = BeatPlan(
        summary="陆照夺到密函后被执事堵住，必须决定是否暴露玉佩残光。",
        target_mood="紧张",
        key_entities=["陆照", "密函"],
    )
    card = BeatWritingCard(
        beat_index=0,
        source_summary=beat.summary,
        objective="陆照夺到密函",
        conflict="执事堵住药库门",
        turning_point="陆照决定是否暴露玉佩残光",
        stake="迟疑就会被搜身并失去密函",
        required_entities=["陆照", "密函"],
        chapter_role="冲突推进",
        chapter_purpose="让密函从目标变成新的追踪风险",
        suspense_mode="行动压力",
        foreshadowing_operation="强化密函血色符痕",
        reveal_delta="密函不是普通证物，符痕会触发追踪",
        emotional_shift="紧张 -> 压迫",
        next_chapter_pressure="追踪术已经启动",
        scene_pressure_lenses=["可选: 让压力落在门口距离、搜身风险和密函藏处。"],
        relationship_subtext_lenses=["可选: 用执事的停顿、视线和陆照的避让承载试探。"],
        prose_texture_lenses=["优先把抽象压力落到手心、门缝冷光和药灰味。"],
        freshness_lenses=["避免复用上一章的昏迷式收束，改用关系压力停点。"],
    )
    context = ChapterContext(
        chapter_plan=ChapterPlan(chapter_number=7, title="密函余波", target_word_count=1200, beats=[beat]),
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="药库", narrative="门缝里有冷光。"),
        timeline_events=[],
        pending_foreshadowings=[],
        writing_cards=[card],
        scene_fuel={
            "plot_fuel": ["密函边角的血色符痕开始发亮"],
            "character_pressure": ["陆照必须判断执事是否看见玉佩残光"],
            "world_fragment": ["追踪术会沿血符回响定位"],
            "technique_hint": ["用物件变化和站位压迫替代作者总结"],
            "continuity_momentum": ["前情余压: 陆照刚从药柜暗格取出密函"],
            "freshness_guard": ["上一章用过追兵逼近时，本章优先换成关系试探或物件变化。"],
        },
    )

    prompt = agent._build_whole_chapter_context_message(context)

    assert "当前章信息变化" in prompt
    assert "下一章压力" in prompt
    assert "可写作燃料" in prompt
    assert "密函边角的血色符痕开始发亮" in prompt
    assert "追踪术已经启动" in prompt
    assert "可选叙事策略池" in prompt
    assert "这些策略不是逐项硬性完成" in prompt
    assert "连续性动能: 前情余压" in prompt
    assert "新鲜度提醒: 上一章用过追兵逼近" in prompt
    assert "必须短对话" not in prompt
    assert "必须出现新风险" not in prompt
    assert "对话占比" not in prompt


def test_whole_chapter_prompt_includes_chapter_obligation_contract():
    from novel_dev.agents.writer_agent import WriterAgent
    from novel_dev.schemas.context import BeatPlan, BeatWritingCard, ChapterContext, ChapterPlan, LocationContext

    agent = WriterAgent.__new__(WriterAgent)
    beat = BeatPlan(summary="主角带着旧钥匙进入封存房间。", key_entities=["主角", "旧钥匙"])
    context = ChapterContext(
        chapter_plan=ChapterPlan(chapter_number=2, title="压力转向", target_word_count=1200, beats=[beat]),
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="封存房间"),
        timeline_events=[],
        pending_foreshadowings=[],
        writing_cards=[
            BeatWritingCard(
                beat_index=0,
                objective="主角确认旧钥匙不是普通钥匙",
                required_facts=["旧钥匙仍在主角手里"],
                required_payoffs=["旧钥匙必须触发一次当场变化"],
                forbidden_future_events=["房间主人真实身份留到后续章节"],
            )
        ],
    )

    prompt = agent._build_whole_chapter_context_message(context)

    assert "### 章节义务合同" in prompt
    assert "主角确认旧钥匙不是普通钥匙" in prompt
    assert "旧钥匙必须触发一次当场变化" in prompt
    assert "旧钥匙仍在主角手里" in prompt
    assert "房间主人真实身份留到后续章节" in prompt
    assert "必须出现新风险" not in prompt
    assert "必须短对话" not in prompt


def test_whole_chapter_prompt_includes_compressed_narrative_source():
    from novel_dev.agents.writer_agent import WriterAgent
    from novel_dev.schemas.context import BeatPlan, ChapterContext, ChapterPlan, LocationContext

    agent = WriterAgent.__new__(WriterAgent)
    context = ChapterContext(
        chapter_plan=ChapterPlan(
            chapter_number=3,
            title="裂隙初开",
            target_word_count=1800,
            beats=[
                BeatPlan(
                    summary="陆照在药库发现密函异动，第一次看见诸天旧约的裂隙。",
                    key_entities=["陆照", "密函"],
                )
            ],
        ),
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="药库"),
        timeline_events=[],
        pending_foreshadowings=[],
        narrative_source="陆照从边城药库的密函开始，被卷入诸天旧约与王朝暗线的冲突，最终要在自保和改写旧约之间做选择。",
    )

    prompt = agent._build_whole_chapter_context_message(context)

    assert "全书压缩故事源头" in prompt
    assert "诸天旧约" in prompt
    assert "改写旧约" in prompt


@pytest.mark.asyncio
async def test_write_standalone_without_novel_id_uses_whole_chapter_without_genre_template(async_session):
    from novel_dev.agents.writer_agent import WriterAgent
    from novel_dev.schemas.context import BeatPlan, ChapterContext, ChapterPlan, LocationContext

    captured = {}

    async def fake_generate_whole_chapter(*args, **kwargs):
        captured["genre_template"] = kwargs.get("genre_template")
        return "他按住呼吸，沿着既定规则推进，动作和选择都落在眼前压力里，直到这一场阻力有了清楚结果。"

    async def fail_resolve(*args, **kwargs):
        raise AssertionError("GenreTemplateService.resolve should not be called without novel_id")

    agent = WriterAgent(async_session)
    beat = BeatPlan(summary="主角在压力下做出选择。", target_mood="紧张", target_word_count=300)
    context = ChapterContext(
        chapter_plan=ChapterPlan(chapter_number=1, title="第一章", target_word_count=800, beats=[beat]),
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="测试场景"),
        timeline_events=[],
        pending_foreshadowings=[],
        story_contract={},
    )

    with patch.object(agent, "_generate_whole_chapter", side_effect=fake_generate_whole_chapter), patch.object(
        agent,
        "_generate_beat",
        side_effect=AssertionError("standalone writing should not use single-beat generation"),
    ), patch.object(
        agent,
        "_rewrite_angle",
        side_effect=AssertionError("standalone writing should not use beat rewrite"),
    ), patch.object(
        agent.chapter_repo,
        "update_text",
        new_callable=AsyncMock,
    ) as mock_update_text, patch.object(
        agent.chapter_repo,
        "update_status",
        new_callable=AsyncMock,
    ), patch(
        "novel_dev.agents.writer_agent.GenreTemplateService.resolve",
        side_effect=fail_resolve,
    ):
        await agent.write_standalone("", context, "ch_empty_genre")

    assert captured["genre_template"] is None
    mock_update_text.assert_awaited_once()
    saved_text = mock_update_text.await_args.kwargs["raw_draft"]
    assert "<!--BEAT" not in saved_text


@pytest.mark.asyncio
async def test_rewrite_angle_injects_genre_template_and_quality_config(async_session):
    captured = {}

    async def fake_rewrite(messages, config=None):
        captured["system"] = messages[0].content
        captured["user"] = messages[1].content
        return LLMResponse(text="重写后的正文保留当前目标，删除不合类型的表达。")

    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = fake_rewrite

    agent = WriterAgent(async_session)
    beat = BeatPlan(summary="主角在压力下做出选择。", target_mood="紧张", target_word_count=300)
    context = ChapterContext(
        chapter_plan=ChapterPlan(chapter_number=1, title="第一章", target_word_count=800, beats=[beat]),
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="测试场景"),
        timeline_events=[],
        pending_foreshadowings=[],
        story_contract={},
    )
    genre_template = ResolvedGenreTemplate(
        genre=default_genre(),
        prompt_blocks={
            "setting_rules": ["重写也必须遵守当前类型的来源边界。"],
            "forbidden_rules": ["不引入类型模板外的具体事实。"],
        },
        quality_config={
            "modern_terms_policy": "block",
            "modern_drift_patterns": ["KPI"],
        },
    )

    with patch("novel_dev.llm.llm_factory.get", return_value=mock_client), patch(
        "novel_dev.llm.llm_factory._resolve_config",
        return_value={},
    ):
        await agent._rewrite_angle(
            beat,
            "他把这次危机称作 KPI 复盘。",
            context,
            idx=0,
            total=1,
            is_last=True,
            novel_id="novel_writer_rewrite_genre",
            genre_template=genre_template,
        )

    assert "重写也必须遵守当前类型的来源边界" in captured["system"]
    assert "不引入类型模板外的具体事实" in captured["system"]
    assert "KPI" in captured["system"] or "KPI" in captured["user"]


def test_writer_self_check_uses_genre_quality_config_for_modern_terms(async_session):
    agent = WriterAgent(async_session)
    beat = BeatPlan(summary="主角在工作压力下做出选择。", target_mood="紧张")
    context = ChapterContext(
        chapter_plan=ChapterPlan(chapter_number=1, title="第一章", target_word_count=800, beats=[beat]),
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="办公室"),
        timeline_events=[],
        pending_foreshadowings=[],
    )
    genre_template = ResolvedGenreTemplate(
        genre=default_genre(),
        quality_config={"modern_terms_policy": "allow", "modern_drift_patterns": ["KPI"]},
    )

    check = agent._self_check_beat(
        "他打开项目面板，盯着 KPI 变化，终于决定把风险摊开说清楚。",
        beat,
        context,
        0,
        genre_template=genre_template,
    )

    assert not any("KPI" in issue for issue in check.contradictions)
