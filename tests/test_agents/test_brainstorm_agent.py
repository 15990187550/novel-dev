import json
from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.brainstorm_agent import BrainstormAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.llm.models import ChatMessage, LLMResponse
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.schemas.outline import (
    SynopsisData,
    CharacterArc,
    PlotMilestone,
    SynopsisScoreResult,
    SynopsisVolumeOutline,
)


def make_volume_outline(number: int) -> SynopsisVolumeOutline:
    return SynopsisVolumeOutline(
        volume_number=number,
        title=f"第{number}卷",
        summary=f"第{number}卷围绕主线推进阶段目标。",
        narrative_role="阶段推进",
        main_goal="完成阶段目标",
        main_conflict="主角与阻力对抗",
        start_state="局势初启",
        end_state="阶段转折",
        climax="核心冲突爆发",
        hook_to_next="新矛盾出现",
        key_entities=["主角"],
        relationship_shifts=[],
        foreshadowing_setup=[],
        foreshadowing_payoff=[],
        target_chapter_range=f"{(number - 1) * 30 + 1}-{number * 30}",
    )


def test_synopsis_data_backfills_missing_title_from_logline():
    synopsis = SynopsisData.model_validate({
        "logline": "道经继承者陆照在末劫前争夺超脱路径。",
        "core_conflict": "陆照 vs 轮回空间幕后布局者",
        "themes": ["自由意志"],
        "character_arcs": [],
        "milestones": [],
        "estimated_volumes": 3,
        "estimated_total_chapters": 90,
        "estimated_total_words": 270000,
    })

    assert synopsis.title == "道经继承者陆照在末劫前争夺超脱路径"


def test_brainstorm_review_status_includes_synopsis_quality_report(async_session):
    synopsis = SynopsisData(
        title="天玄纪",
        logline="少年在乱世中成长。",
        core_conflict="正邪对立",
        themes=["成长"],
        character_arcs=[CharacterArc(name="陆照", arc_summary="成长", key_turning_points=["入门"])],
        milestones=[PlotMilestone(act="一", summary="修炼", climax_event="突破")],
        estimated_volumes=1,
        estimated_total_chapters=3,
        estimated_total_words=9000,
        volume_outlines=[],
    )
    score = SynopsisScoreResult(
        overall=80,
        logline_specificity=80,
        conflict_concreteness=80,
        character_arc_depth=80,
        structural_turns=80,
        hook_strength=80,
        summary_feedback="ok",
    )

    reviewed = BrainstormAgent(async_session)._with_review_status(
        synopsis,
        score=score,
        status="accepted",
        reason="ok",
        attempt=1,
    )

    quality = reviewed.review_status["synopsis_quality_report"]
    assert quality["passed"] is False
    assert quality["conflict_score"] < 75


@pytest.mark.asyncio
async def test_brainstorm_success(async_session):
    await DocumentRepository(async_session).create(
        "doc_wv", "n_brain", "worldview", "Worldview", "天玄大陆，万族林立。"
    )
    await DocumentRepository(async_session).create(
        "doc_st", "n_brain", "setting", "Setting", "修炼体系：炼气、筑基。"
    )

    mock_synopsis = SynopsisData(
        title="天玄纪元",
        logline="主角在修炼世界中崛起",
        core_conflict="个人复仇与天下大义",
        themes=["成长", "复仇"],
        character_arcs=[
            CharacterArc(
                name="主角",
                arc_summary="从废柴到巅峰",
                key_turning_points=["觉醒", "突破"],
            )
        ],
        milestones=[
            PlotMilestone(
                act="第一幕", summary="入门试炼", climax_event="外门大比"
            )
        ],
        estimated_volumes=3,
        estimated_total_chapters=90,
        estimated_total_words=270000,
    )
    mock_score = SynopsisScoreResult(
        overall=85,
        logline_specificity=85,
        conflict_concreteness=85,
        character_arc_depth=85,
        structural_turns=85,
        hook_strength=85,
        summary_feedback="ok",
    )
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=mock_synopsis.model_dump_json()),
        LLMResponse(text=json.dumps([make_volume_outline(i).model_dump() for i in range(1, 4)], ensure_ascii=False)),
        LLMResponse(text=mock_score.model_dump_json()),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = BrainstormAgent(async_session)
        synopsis_data = await agent.brainstorm("n_brain")

    assert synopsis_data.title == "天玄纪元"
    assert synopsis_data.estimated_volumes == 3
    assert len(synopsis_data.volume_outlines) == 3

    state = await NovelStateRepository(async_session).get_state("n_brain")
    assert state.current_phase == Phase.VOLUME_PLANNING.value
    assert "synopsis_data" in state.checkpoint_data
    assert state.checkpoint_data["synopsis_doc_id"] is not None

    docs = await DocumentRepository(async_session).get_by_type("n_brain", "synopsis")
    assert len(docs) == 1
    assert "天玄大陆" not in docs[0].content
    assert "天玄纪元" in docs[0].content


@pytest.mark.asyncio
async def test_brainstorm_missing_documents(async_session):
    agent = BrainstormAgent(async_session)
    with pytest.raises(ValueError, match="No source documents found"):
        await agent.brainstorm("n_empty")


@pytest.mark.asyncio
async def test_brainstorm_uses_llm_factory(async_session):
    await DocumentRepository(async_session).create(
        "doc_wv2", "n_brain2", "worldview", "Worldview", "天玄大陆。"
    )

    synopsis_json = SynopsisData(
        title="天玄纪元",
        logline="主角崛起",
        core_conflict="复仇",
        themes=["成长"],
        character_arcs=[],
        milestones=[],
        estimated_volumes=3,
        estimated_total_chapters=90,
        estimated_total_words=270000,
    ).model_dump_json()

    score_json = SynopsisScoreResult(
        overall=85,
        logline_specificity=85,
        conflict_concreteness=85,
        character_arc_depth=85,
        structural_turns=85,
        hook_strength=85,
        summary_feedback="ok",
    ).model_dump_json()

    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=synopsis_json),
        LLMResponse(text=json.dumps([make_volume_outline(i).model_dump() for i in range(1, 4)], ensure_ascii=False)),
        LLMResponse(text=score_json),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = BrainstormAgent(async_session)
        result = await agent.brainstorm("n_brain2")

    assert result.title == "天玄纪元"
    # self-review 会触发顶层总纲、卷级概要批次、评分等模型任务
    get_tasks = [call.kwargs.get("task") or (call.args[1] if len(call.args) > 1 else None)
                 for call in mock_factory.get.call_args_list]
    assert "generate_synopsis_top_level" in get_tasks
    assert "generate_synopsis_volume_outlines_batch" in get_tasks
    assert "score_synopsis" in get_tasks


@pytest.mark.asyncio
async def test_brainstorm_prompt_includes_resolved_genre_rules(async_session):
    from novel_dev.db.models import NovelState

    async_session.add(
        NovelState(
            novel_id="n_brain_genre",
            current_phase="brainstorming",
            checkpoint_data={
                "genre": {
                    "primary_slug": "xuanyi",
                    "primary_name": "悬疑",
                    "secondary_slug": "detective",
                    "secondary_name": "推理探案",
                }
            },
        )
    )
    await DocumentRepository(async_session).create(
        "doc_brain_genre",
        "n_brain_genre",
        "setting",
        "案件设定",
        "一桩封闭空间案件，所有证词互相矛盾。",
    )
    await async_session.commit()

    captured_prompts = []
    mock_synopsis = SynopsisData(
        title="雾中证词",
        logline="侦探在证词互相矛盾的封闭案件中寻找真相。",
        core_conflict="侦探 vs 隐藏关键事实的嫌疑人",
        themes=["真相", "选择"],
        character_arcs=[],
        milestones=[],
        estimated_volumes=1,
        estimated_total_chapters=12,
        estimated_total_words=36000,
    )
    mock_score = SynopsisScoreResult(
        overall=85,
        logline_specificity=85,
        conflict_concreteness=85,
        character_arc_depth=85,
        structural_turns=85,
        hook_strength=85,
        summary_feedback="ok",
    )

    async def fake_call_and_parse_model(agent_name, task_name, prompt, model_type, **kwargs):
        captured_prompts.append(prompt)
        if task_name == "generate_synopsis_top_level":
            return mock_synopsis
        if task_name == "generate_synopsis_volume_outlines_batch":
            return [make_volume_outline(1)]
        if task_name == "score_synopsis":
            return mock_score
        raise AssertionError(f"unexpected task: {task_name}")

    with patch(
        "novel_dev.agents.brainstorm_agent.call_and_parse_model",
        side_effect=fake_call_and_parse_model,
    ):
        await BrainstormAgent(async_session).brainstorm("n_brain_genre")

    joined = "\n\n".join(captured_prompts)
    assert "线索" in joined
    assert "信息披露" in joined


@pytest.mark.asyncio
async def test_top_level_synopsis_without_novel_id_skips_genre_resolution(async_session):
    captured = {}
    mock_synopsis = SynopsisData(
        title="无名总纲",
        logline="主角在压力中寻找出路。",
        core_conflict="主角 vs 外部阻力",
        themes=["选择"],
        character_arcs=[],
        milestones=[],
        estimated_volumes=1,
        estimated_total_chapters=10,
        estimated_total_words=30000,
    )

    async def fake_call_and_parse_model(agent_name, task_name, prompt, model_type, **kwargs):
        captured["prompt"] = prompt
        return mock_synopsis

    async def fail_resolve(*args, **kwargs):
        raise AssertionError("GenreTemplateService.resolve should not be called without novel_id")

    with patch(
        "novel_dev.agents.brainstorm_agent.call_and_parse_model",
        side_effect=fake_call_and_parse_model,
    ), patch(
        "novel_dev.agents.brainstorm_agent.GenreTemplateService.resolve",
        side_effect=fail_resolve,
    ):
        result = await BrainstormAgent(async_session)._generate_top_level_synopsis("资料", "")

    assert result.title == "无名总纲"
    assert "类型模板约束" not in captured["prompt"]


def test_synopsis_score_result_accepts_nested_scores_shape():
    payload = {
        "scores": {
            "overall": 82,
            "logline_specificity": 80,
            "conflict_concreteness": 81,
            "character_arc_depth": 79,
            "structural_turns": 78,
            "hook_strength": 77,
        },
        "feedback": "需要把一句话梗概写得更具体。",
    }

    result = SynopsisScoreResult.model_validate(payload)

    assert result.overall == 82
    assert result.logline_specificity == 80
    assert result.conflict_concreteness == 81
    assert result.character_arc_depth == 79
    assert result.structural_turns == 78
    assert result.hook_strength == 77
    assert result.summary_feedback == "需要把一句话梗概写得更具体。"


@pytest.mark.asyncio
async def test_generate_synopsis_prompt_explicitly_constrains_schema(async_session):
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=SynopsisData(
        title="天玄纪元",
        logline="主角崛起",
        core_conflict="复仇",
        themes=["成长"],
        character_arcs=[],
        milestones=[],
        estimated_volumes=3,
        estimated_total_chapters=90,
        estimated_total_words=270000,
    ).model_dump_json()),
        LLMResponse(text=json.dumps([make_volume_outline(i).model_dump() for i in range(1, 4)], ensure_ascii=False)),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = BrainstormAgent(async_session)
        await agent._generate_synopsis("世界观设定", "n_prompt")

    prompt = mock_client.acomplete.call_args_list[0].args[0][0].content
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
    assert '"volume_outlines"' in prompt
    assert "本步骤必须是空数组" in prompt
    assert "不要写任何卷级概要、章节列表或 beats" in prompt
    assert "禁止输出任何额外字段" in prompt

    batch_prompt = mock_client.acomplete.call_args_list[1].args[0][0].content
    assert "只生成第 1 卷到第 3 卷" in batch_prompt
    assert "必须正好 3 项" in batch_prompt
    assert "ActiveConstraintContext" in batch_prompt
    assert "当前阶段可触达冲突" in batch_prompt
    assert "高阶概念只能作为伏笔" in batch_prompt
