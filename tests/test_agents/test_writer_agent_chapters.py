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

    # generate_beat call should have system + user messages
    beat_messages = captured_messages[0]
    assert len(beat_messages) >= 2
    assert beat_messages[0].role == "system"
    assert beat_messages[1].role == "user"

    # System prompt should contain rules, not worldview dump
    system = beat_messages[0].content
    assert "写作方向" in system
    assert "读者读感" in system
    assert "简洁有力" in system

    # User prompt should contain chapter plan and beat info
    user = beat_messages[1].content
    assert "当前节拍" in user
    assert "开场" in user


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
    assert "当前节拍动作要服务这个长期目标" in user


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


@pytest.mark.asyncio
async def test_write_standalone_without_novel_id_passes_no_genre_template(async_session):
    from novel_dev.agents.writer_agent import WriterAgent
    from novel_dev.schemas.context import BeatPlan, ChapterContext, ChapterPlan, LocationContext

    captured = {}

    async def fake_generate_beat(*args, **kwargs):
        captured["genre_template"] = kwargs.get("genre_template")
        text = "他按住呼吸，沿着既定规则推进，动作和选择都落在眼前压力里，直到这一场阻力有了清楚结果。"
        return f"<!--BEAT:0-->\n{text}\n<!--/BEAT:0-->"

    async def pass_guard(*args, **kwargs):
        inner = kwargs["inner"]
        idx = kwargs["idx"]
        return inner, f"<!--BEAT:{idx}-->\n{inner}\n<!--/BEAT:{idx}-->"

    async def pass_budget(*args, **kwargs):
        inner = kwargs["inner"]
        idx = kwargs["idx"]
        return inner, f"<!--BEAT:{idx}-->\n{inner}\n<!--/BEAT:{idx}-->"

    async def pass_hygiene(*args, **kwargs):
        inner = kwargs["inner"]
        idx = kwargs["idx"]
        return inner, f"<!--BEAT:{idx}-->\n{inner}\n<!--/BEAT:{idx}-->"

    async def no_relay(*args, **kwargs):
        raise RuntimeError("skip relay")

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

    with patch.object(agent, "_generate_beat", side_effect=fake_generate_beat), patch.object(
        agent,
        "_guard_writer_beat",
        side_effect=pass_guard,
    ), patch.object(
        agent,
        "_enforce_beat_word_budget",
        side_effect=pass_budget,
    ), patch.object(
        agent,
        "_enforce_prose_hygiene",
        side_effect=pass_hygiene,
    ), patch.object(
        agent,
        "_generate_relay",
        side_effect=no_relay,
    ), patch.object(
        agent.chapter_repo,
        "update_text",
        new_callable=AsyncMock,
    ), patch.object(
        agent.chapter_repo,
        "update_status",
        new_callable=AsyncMock,
    ), patch(
        "novel_dev.agents.writer_agent.GenreTemplateService.resolve",
        side_effect=fail_resolve,
    ):
        await agent.write_standalone("", context, "ch_empty_genre")

    assert captured["genre_template"] is None


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
