from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.volume_planner import (
    VolumeBeatExpansion,
    VolumeChapterSkeleton,
    VolumePlannerAgent,
    VolumePlanBlueprint,
    VolumePlanPatch,
    VolumePlanSemanticJudgement,
)
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.knowledge_domain_repo import KnowledgeDomainRepository
from novel_dev.schemas.outline import SynopsisData, VolumeScoreResult, VolumePlan, VolumeBeat
from novel_dev.schemas.context import BeatPlan
import uuid
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.services.domain_activation_service import DomainActivationService
from novel_dev.services.narrative_constraint_service import NarrativeConstraintBuilder
from novel_dev.llm.models import LLMResponse
from novel_dev.services.log_service import LogService


@pytest.fixture(autouse=True)
def clear_log_buffers():
    LogService._buffers.clear()
    LogService._listeners.clear()
    LogService._pending_tasks.clear()


def test_volume_plan_blueprint_accepts_flat_entity_highlights():
    blueprint = VolumePlanBlueprint.model_validate({
        "volume_id": "vol_1",
        "volume_number": 1,
        "title": "第一卷",
        "summary": "卷总述",
        "total_chapters": 1,
        "estimated_total_words": 3000,
        "chapters": [{"chapter_number": 1, "title": "启程", "summary": "陆照入局。"}],
        "entity_highlights": ["陆照——道经继承者", "神秘遗迹——因果所化"],
    })

    assert blueprint.entity_highlights == {
        "general": ["陆照——道经继承者", "神秘遗迹——因果所化"],
    }


def test_volume_plan_blueprint_backfills_missing_chapter_titles():
    blueprint = VolumePlanBlueprint.model_validate({
        "volume_id": "vol_1",
        "volume_number": 1,
        "title": "第一卷",
        "summary": "卷总述",
        "total_chapters": 2,
        "estimated_total_words": 6000,
        "chapters": [
            {"chapter_number": 1, "summary": "陆照发现轮回空间神秘标记。"},
            {"chapter_number": 2, "summary": "山门之中暗流正在缓慢扩散。"},
        ],
    })

    assert [chapter.title for chapter in blueprint.chapters] == [
        "陆照发现轮回空间神秘标记",
        "山门之中暗流正在缓慢扩散",
    ]
    assert [chapter.chapter_id for chapter in blueprint.chapters] == ["vol_1_ch_1", "vol_1_ch_2"]


@pytest.mark.asyncio
async def test_constraint_source_excludes_previous_volume_plan(async_session):
    repo = DocumentRepository(async_session)
    await repo.create(
        doc_id="doc_setting",
        novel_id="n_constraint_source",
        doc_type="setting",
        title="修炼体系",
        content="只允许使用：筑基、外景。",
    )
    await repo.create(
        doc_id="doc_bad_volume_plan",
        novel_id="n_constraint_source",
        doc_type="volume_plan",
        title="第1卷",
        content="旧错误卷纲：引气三层、引气七层。",
    )

    source = await VolumePlannerAgent(async_session)._load_constraint_source_text("n_constraint_source")

    assert "筑基" in source
    assert "引气三层" not in source
    assert "volume_plan" not in source


@pytest.mark.asyncio
async def test_domain_activation_source_excludes_previous_volume_plan(async_session):
    repo = DocumentRepository(async_session)
    await repo.create(
        doc_id="doc_domain_setting",
        novel_id="n_domain_source",
        doc_type="setting",
        title="修炼体系",
        content="只允许使用：筑基、外景。",
    )
    await repo.create(
        doc_id="doc_domain_bad_plan",
        novel_id="n_domain_source",
        doc_type="volume_plan",
        title="第1卷",
        content="旧错误卷纲：引气三层。",
    )

    source = await DomainActivationService(async_session)._load_source_text("n_domain_source")

    assert "筑基" in source
    assert "引气三层" not in source


@pytest.mark.asyncio
async def test_domain_activation_includes_power_ladder_boundaries_and_open_questions(async_session):
    long_rule = "境界说明" + "很长" * 200
    await KnowledgeDomainRepository(async_session).create(
        novel_id="n_domain_rules",
        name="灭运图录",
        activation_mode="always",
        rules={
            "power_ladder": ["练气：养魂→壮魂→出窍→引气锻魂", long_rule],
            "knowledge_boundaries": ["不得改写为引气三层、引气七层"],
            "open_questions": ["主角当前是否已接触该体系待确认"],
        },
    )
    synopsis = SynopsisData(
        title="道经照诸天",
        logline="陆照争夺超脱路径。",
        core_conflict="陆照 vs 末劫幕后布局者",
        estimated_volumes=1,
        estimated_total_chapters=2,
        estimated_total_words=6000,
    )

    context = await DomainActivationService(async_session).build_context(
        novel_id="n_domain_rules",
        synopsis=synopsis,
        volume_number=1,
    )
    prompt_block = context.to_prompt_block()

    assert "练气：养魂→壮魂→出窍→引气锻魂" in prompt_block
    assert "不得改写为引气三层、引气七层" in prompt_block
    assert "主角当前是否已接触该体系待确认" in prompt_block
    assert len(next(line for line in prompt_block.splitlines() if line.startswith("- 境界说明"))) <= 242


def test_narrative_constraints_derive_required_sequence_from_settings():
    synopsis = SynopsisData(
        title="道经照诸天",
        logline="陆照争夺超脱路径。",
        core_conflict="陆照 vs 末劫幕后布局者",
        estimated_volumes=1,
        estimated_total_chapters=60,
        estimated_total_words=120000,
        volume_outlines=[{
            "volume_number": 1,
            "title": "筑基问道",
            "summary": "陆照百日筑基，卷末达半步外景。",
            "main_goal": "百日筑基至半步外景",
        }],
    )
    source_text = (
        "[setting] 修炼体系\n"
        "一世之尊正统修炼体系：百日筑基→蓄气锻体→开窍（九窍+眉心祖窍）→"
        "天人交感→天人合一→归真返璞→半步外景→外景"
    )

    context = NarrativeConstraintBuilder().build_for_volume(
        synopsis=synopsis,
        volume_number=1,
        source_text=source_text,
    )

    sequence = next(item for item in context.executable_constraints if item.constraint_type == "sequence")
    assert sequence.terms == [
        "百日筑基",
        "蓄气锻体",
        "开窍",
        "九窍",
        "眉心祖窍",
        "天人交感",
        "天人合一",
        "归真返璞",
        "半步外景",
    ]
    assert "可执行设定约束" in context.to_prompt_block()


@pytest.mark.asyncio
async def test_generate_volume_plan_repairs_missing_setting_constraints(async_session):
    await DocumentRepository(async_session).create(
        doc_id="doc_power_chain",
        novel_id="n_constraint_repair",
        doc_type="setting",
        title="修炼体系",
        content=(
            "一世之尊正统修炼体系：百日筑基→蓄气锻体→开窍（九窍+眉心祖窍）→"
            "天人交感→天人合一→归真返璞→半步外景→外景"
        ),
    )
    synopsis = SynopsisData(
        title="道经照诸天",
        logline="陆照争夺超脱路径。",
        core_conflict="陆照 vs 末劫幕后布局者",
        estimated_volumes=1,
        estimated_total_chapters=3,
        estimated_total_words=9000,
        volume_outlines=[{
            "volume_number": 1,
            "title": "筑基问道",
            "summary": "陆照百日筑基，卷末达半步外景。",
            "main_goal": "百日筑基至半步外景",
        }],
    )
    bad_blueprint = VolumePlanBlueprint(
        volume_id="vol_1",
        volume_number=1,
        title="第一卷",
        summary="陆照快速成长。",
        total_chapters=3,
        estimated_total_words=9000,
        chapters=[
            {"chapter_number": 1, "title": "古卷初现", "summary": "陆照得到道经。"},
            {"chapter_number": 2, "title": "修行初成", "summary": "陆照修为快速提升。"},
            {"chapter_number": 3, "title": "半步外景", "summary": "陆照抵达半步外景。"},
        ],
    )
    repaired_blueprint = VolumePlanBlueprint(
        volume_id="vol_1",
        volume_number=1,
        title="第一卷",
        summary="陆照按正统阶梯稳步成长。",
        total_chapters=3,
        estimated_total_words=9000,
        chapters=[
            {"chapter_number": 1, "title": "百日筑基", "summary": "陆照完成百日筑基，转入蓄气锻体。"},
            {"chapter_number": 2, "title": "九窍祖窍", "summary": "陆照踏入开窍，依次开九窍并触及眉心祖窍。"},
            {"chapter_number": 3, "title": "返璞半步", "summary": "陆照经历天人交感、天人合一与归真返璞，抵达半步外景。"},
        ],
    )
    expanded = [
        VolumeBeat(
            chapter_id=f"vol_1_ch_{index}",
            chapter_number=index,
            title=chapter.title,
            summary=chapter.summary,
            target_word_count=3000,
            target_mood="steady",
            beats=[BeatPlan(summary=chapter.summary, target_mood="steady")],
        )
        for index, chapter in enumerate(repaired_blueprint.chapters, start=1)
    ]
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=bad_blueprint.model_dump_json()),
        LLMResponse(text=repaired_blueprint.model_dump_json()),
        LLMResponse(text=VolumePlanSemanticJudgement(passed=True, confidence=0.92).model_dump_json()),
        LLMResponse(text=f"[{','.join(chapter.model_dump_json() for chapter in expanded)}]"),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        plan = await VolumePlannerAgent(async_session)._generate_volume_plan(
            synopsis,
            1,
            novel_id="n_constraint_repair",
            target_chapters=3,
        )

    assert mock_client.acomplete.await_count == 4
    assert "眉心祖窍" in plan.model_dump_json()
    entries = list(LogService._buffers["n_constraint_repair"])
    assert any(entry.get("node") == "volume_constraint_validation" and entry.get("status") == "failed" for entry in entries)
    assert any(entry.get("node") == "volume_constraint_validation" and entry.get("status") == "succeeded" for entry in entries)


@pytest.mark.asyncio
async def test_generate_volume_plan_repairs_semantic_conflicts(async_session):
    await DocumentRepository(async_session).create(
        doc_id="doc_boundary",
        novel_id="n_semantic_repair",
        doc_type="setting",
        title="完美世界边界",
        content="设定事实：主角低境界不得正面接触高原始祖，只能作为传闻、残影或远景伏笔。",
    )
    synopsis = SynopsisData(
        title="道经照诸天",
        logline="陆照争夺超脱路径。",
        core_conflict="陆照 vs 末劫幕后布局者",
        estimated_volumes=1,
        estimated_total_chapters=2,
        estimated_total_words=6000,
        volume_outlines=[{
            "volume_number": 1,
            "title": "初入诸天",
            "summary": "陆照低境界时感知完美世界远景。",
            "main_goal": "确认诸天存在",
        }],
    )
    bad_blueprint = VolumePlanBlueprint(
        volume_id="vol_1",
        volume_number=1,
        title="第一卷",
        summary="陆照越级对抗高原。",
        total_chapters=2,
        estimated_total_words=6000,
        chapters=[
            {"chapter_number": 1, "title": "远景初现", "summary": "陆照感知完美世界。"},
            {"chapter_number": 2, "title": "镇退始祖", "summary": "陆照以道经正面镇退高原始祖意志。"},
        ],
    )
    repaired_blueprint = VolumePlanBlueprint(
        volume_id="vol_1",
        volume_number=1,
        title="第一卷",
        summary="陆照只获得远景伏笔。",
        total_chapters=2,
        estimated_total_words=6000,
        chapters=[
            {"chapter_number": 1, "title": "远景初现", "summary": "陆照感知完美世界的模糊远景。"},
            {"chapter_number": 2, "title": "残影警兆", "summary": "高原只以不可理解残影掠过，陆照无法接触也无法判断真相。"},
        ],
    )
    expanded = [
        VolumeBeat(
            chapter_id=f"vol_1_ch_{index}",
            chapter_number=index,
            title=chapter.title,
            summary=chapter.summary,
            target_word_count=3000,
            target_mood="ominous",
            beats=[BeatPlan(summary=chapter.summary, target_mood="ominous")],
        )
        for index, chapter in enumerate(repaired_blueprint.chapters, start=1)
    ]
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=bad_blueprint.model_dump_json()),
        LLMResponse(text=VolumePlanSemanticJudgement(
            passed=False,
            hard_conflicts=["低境界陆照正面镇退高原始祖意志，违反只能伏笔的边界。"],
            repair_suggestions=["改为远景残影或不可理解警兆，不产生正面交锋结果。"],
            confidence=0.95,
        ).model_dump_json()),
        LLMResponse(text=repaired_blueprint.model_dump_json()),
        LLMResponse(text=VolumePlanSemanticJudgement(passed=True, confidence=0.93).model_dump_json()),
        LLMResponse(text=f"[{','.join(chapter.model_dump_json() for chapter in expanded)}]"),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        plan = await VolumePlannerAgent(async_session)._generate_volume_plan(
            synopsis,
            1,
            novel_id="n_semantic_repair",
            target_chapters=2,
        )

    assert mock_client.acomplete.await_count == 5
    assert "正面镇退" not in plan.model_dump_json()
    entries = list(LogService._buffers["n_semantic_repair"])
    assert any(entry.get("node") == "volume_semantic_judge" and entry.get("status") == "failed" for entry in entries)
    assert any(entry.get("node") == "volume_semantic_judge" and entry.get("status") == "succeeded" for entry in entries)


@pytest.mark.asyncio
async def test_expand_volume_plan_batch_backfills_missing_skeleton_fields(async_session):
    agent = VolumePlannerAgent(async_session)
    blueprint = VolumePlanBlueprint(
        volume_id="vol_1",
        volume_number=1,
        title="第一卷",
        summary="卷总述",
        total_chapters=2,
        estimated_total_words=6000,
        chapters=[
            {"chapter_number": 1, "title": "照见旧碑", "summary": "陆照发现古碑异动。"},
            {"chapter_number": 2, "title": "山门问罪", "summary": "长老会借机发难。"},
        ],
    )
    synopsis = SynopsisData(
        title="道经照诸天",
        logline="陆照争夺超脱路径。",
        core_conflict="陆照 vs 末劫幕后布局者",
        estimated_volumes=1,
        estimated_total_chapters=2,
        estimated_total_words=6000,
    )
    incomplete_batch = [
        {
            "target_word_count": 3200,
            "target_mood": "tense",
            "beats": [{"summary": "古碑裂开，显出因果纹路。", "target_mood": "mysterious"}],
        },
        {
            "target_word_count": 3500,
            "target_mood": "压迫",
            "beats": [{"summary": "长老逼问陆照传承来源。", "target_mood": "tense"}],
        },
    ]
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text=__import__("json").dumps(incomplete_batch, ensure_ascii=False))

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        chapters = await agent._expand_volume_plan_batches(
            blueprint,
            synopsis,
            world_snapshot=None,
            novel_id="n_backfill",
        )

    assert [chapter.chapter_number for chapter in chapters] == [1, 2]
    assert [chapter.title for chapter in chapters] == ["照见旧碑", "山门问罪"]
    assert chapters[0].summary == "陆照发现古碑异动。"
    assert chapters[0].chapter_id == "vol_1_ch_1"
    assert chapters[0].target_word_count == 3200


@pytest.mark.asyncio
async def test_complete_expanded_batch_reorders_by_skeleton_and_rejects_invalid_numbers(async_session):
    agent = VolumePlannerAgent(async_session)
    skeletons = [
        {"chapter_number": 1, "title": "照见旧碑", "summary": "陆照发现古碑异动。"},
        {"chapter_number": 2, "title": "山门问罪", "summary": "长老会借机发难。"},
    ]
    out_of_order = [
        {
            "chapter_number": 2,
            "title": "山门问罪",
            "summary": "长老会借机发难。",
            "target_word_count": 3000,
            "target_mood": "tense",
            "beats": [{"summary": "长老发难。", "target_mood": "tense"}],
        },
        {
            "chapter_number": 1,
            "title": "照见旧碑",
            "summary": "陆照发现古碑异动。",
            "target_word_count": 3000,
            "target_mood": "mysterious",
            "beats": [{"summary": "旧碑裂开。", "target_mood": "mysterious"}],
        },
    ]

    chapters = agent._complete_expanded_batch(
        [VolumeBeatExpansion.model_validate(item) for item in out_of_order],
        [VolumeChapterSkeleton.model_validate(item) for item in skeletons],
    )
    assert [chapter.chapter_number for chapter in chapters] == [1, 2]
    assert chapters[0].title == "照见旧碑"

    with pytest.raises(ValueError, match="duplicate chapter_number"):
        agent._complete_expanded_batch(
            [
                VolumeBeatExpansion.model_validate({**out_of_order[0], "chapter_number": 1}),
                VolumeBeatExpansion.model_validate({**out_of_order[1], "chapter_number": 1}),
            ],
            [VolumeChapterSkeleton.model_validate(item) for item in skeletons],
        )

    with pytest.raises(ValueError, match="chapter_number mismatch"):
        agent._complete_expanded_batch(
            [
                VolumeBeatExpansion.model_validate({**out_of_order[0], "chapter_number": 1}),
                VolumeBeatExpansion.model_validate({**out_of_order[1], "chapter_number": 3}),
            ],
            [VolumeChapterSkeleton.model_validate(item) for item in skeletons],
        )

    with pytest.raises(ValueError, match="duplicate chapter_number"):
        agent._complete_expanded_batch(
            [
                VolumeBeatExpansion.model_validate({**out_of_order[0], "chapter_number": 2}),
                VolumeBeatExpansion.model_validate({k: v for k, v in out_of_order[1].items() if k != "chapter_number"}),
            ],
            [VolumeChapterSkeleton.model_validate(item) for item in skeletons],
        )


@pytest.mark.asyncio
async def test_generate_volume_plan_logs_specific_context_sources(async_session):
    doc_repo = DocumentRepository(async_session)
    await doc_repo.create("doc_world", "n_volume_log", "worldview", "世界观", "轮回空间规则")
    await doc_repo.create("doc_setting", "n_volume_log", "setting", "修炼体系", "道印体系")
    await async_session.flush()

    synopsis = SynopsisData(
        title="道经照诸天",
        logline="陆照争夺超脱路径。",
        core_conflict="陆照 vs 末劫幕后布局者",
        estimated_volumes=1,
        estimated_total_chapters=2,
        estimated_total_words=6000,
    )
    blueprint = VolumePlanBlueprint(
        volume_id="vol_1",
        volume_number=1,
        title="第一卷",
        summary="卷总述",
        total_chapters=1,
        estimated_total_words=3000,
        chapters=[{"chapter_number": 1, "title": "照见旧碑", "summary": "陆照发现古碑异动。"}],
    )
    chapter_batch = [{
        "chapter_id": "ch_1",
        "chapter_number": 1,
        "title": "照见旧碑",
        "summary": "陆照发现古碑异动。",
        "target_word_count": 3000,
        "target_mood": "mysterious",
        "beats": [{"summary": "古碑裂开，显出因果纹路。", "target_mood": "mysterious"}],
    }]
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=blueprint.model_dump_json()),
        LLMResponse(text=VolumePlanSemanticJudgement(passed=True, confidence=0.9).model_dump_json()),
        LLMResponse(text=__import__("json").dumps(chapter_batch, ensure_ascii=False)),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = VolumePlannerAgent(async_session)
        await agent._generate_volume_plan(synopsis, 1, novel_id="n_volume_log")

    entries = list(LogService._buffers["n_volume_log"])
    source_log = next(entry for entry in entries if entry.get("node") == "volume_context_sources")
    assert "世界观" in source_log["message"]
    assert "修炼体系" in source_log["message"]
    assert source_log["metadata"]["documents"] == [
        {"id": "doc_world", "type": "worldview", "title": "世界观", "version": 1},
        {"id": "doc_setting", "type": "setting", "title": "修炼体系", "version": 1},
    ]
    constraints_log = next(entry for entry in entries if entry.get("node") == "volume_constraints")
    assert "source_snippets" in constraints_log["metadata"]


@pytest.mark.asyncio
async def test_plan_volume_success(async_session):
    director = NovelDirector(session=async_session)
    synopsis = SynopsisData(
        title="Test",
        logline="Logline",
        core_conflict="Conflict",
        estimated_volumes=1,
        estimated_total_chapters=3,
        estimated_total_words=9000,
    )
    await director.save_checkpoint(
        "n_plan",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={"synopsis_data": synopsis.model_dump()},
        volume_id=None,
        chapter_id=None,
    )

    blueprint = VolumePlanBlueprint(
        volume_id="vol_1",
        volume_number=1,
        title="第一卷",
        summary="卷总述",
        total_chapters=3,
        estimated_total_words=9000,
        chapters=[
            {
                "chapter_number": 1,
                "title": "第一章",
                "summary": "第一章剧情",
            },
            {
                "chapter_number": 2,
                "title": "第二章",
                "summary": "第二章剧情",
            },
            {
                "chapter_number": 3,
                "title": "第三章",
                "summary": "第三章剧情",
            },
        ],
    )
    chapter_batch = [
        VolumeBeat(
            chapter_id=str(uuid.uuid4()),
            chapter_number=1,
            title="第一章",
            summary="第一章剧情",
            target_word_count=3000,
            target_mood="tense",
            beats=[BeatPlan(summary="B1", target_mood="tense")],
        ),
        VolumeBeat(
            chapter_id=str(uuid.uuid4()),
            chapter_number=2,
            title="第二章",
            summary="第二章剧情",
            target_word_count=3000,
            target_mood="tense",
            beats=[BeatPlan(summary="B2", target_mood="tense")],
        ),
        VolumeBeat(
            chapter_id=str(uuid.uuid4()),
            chapter_number=3,
            title="第三章",
            summary="第三章剧情",
            target_word_count=3000,
            target_mood="tense",
            beats=[BeatPlan(summary="B3", target_mood="tense")],
        ),
    ]

    score_result = VolumeScoreResult(
        overall=88,
        outline_fidelity=88,
        character_plot_alignment=88,
        hook_distribution=88,
        foreshadowing_management=88,
        chapter_hooks=88,
        page_turning=88,
        summary_feedback="good",
    )
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=blueprint.model_dump_json()),
        LLMResponse(text=f"[{','.join(chapter.model_dump_json() for chapter in chapter_batch)}]"),
        LLMResponse(text=score_result.model_dump_json()),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_helpers_factory:
        mock_helpers_factory.get.return_value = mock_client
        agent = VolumePlannerAgent(async_session)
        plan = await agent.plan("n_plan", volume_number=1)

    assert plan.volume_id == "vol_1"
    assert len(plan.chapters) == 3

    state = await director.resume("n_plan")
    assert state.current_phase == Phase.CONTEXT_PREPARATION.value
    assert "current_volume_plan" in state.checkpoint_data
    assert "current_chapter_plan" in state.checkpoint_data
    persisted_chapters = await ChapterRepository(async_session).list_by_volume("vol_1")
    assert [chapter.id for chapter in persisted_chapters] == [chapter.chapter_id for chapter in chapter_batch]
    assert {chapter.novel_id for chapter in persisted_chapters} == {"n_plan"}

    docs = await DocumentRepository(async_session).get_by_type("n_plan", "volume_plan")
    assert len(docs) == 1
    assert docs[0].doc_type == "volume_plan"


@pytest.mark.asyncio
async def test_plan_volume_large_outline_skips_full_revise(async_session):
    director = NovelDirector(session=async_session)
    synopsis = SynopsisData(
        title="大长篇",
        logline="长篇升级之路",
        core_conflict="主角与幕后黑手对抗",
        estimated_volumes=26,
        estimated_total_chapters=1300,
        estimated_total_words=3900000,
        volume_outlines=[
            {
                "volume_number": 1,
                "title": "轮回初醒",
                "summary": "陆照初入局，确认轮回空间的威胁。",
                "main_goal": "夺回第一枚道印",
                "main_conflict": "陆照 vs 轮回使者",
                "climax": "夺印成功",
                "hook_to_next": "第二枚道印现世",
            },
            {
                "volume_number": 2,
                "title": "道庭追索",
                "summary": "道庭介入，陆照被迫离开旧地。",
                "main_goal": "查明道庭来历",
            },
        ],
    )
    await director.save_checkpoint(
        "n_large_skip",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={"synopsis_data": synopsis.model_dump()},
        volume_id=None,
        chapter_id=None,
    )

    chapters = [
        VolumeBeat(
            chapter_id=f"ch_{index}",
            chapter_number=index,
            title=f"第{index}章",
            summary=f"第{index}章剧情",
            target_word_count=3000,
            target_mood="tense",
            beats=[BeatPlan(summary=f"B{index}", target_mood="tense")],
        )
        for index in range(1, 21)
    ]
    large_plan = VolumePlan(
        volume_id="vol_1",
        volume_number=1,
        title="第一卷",
        summary="卷总述",
        total_chapters=20,
        estimated_total_words=60000,
        chapters=chapters,
    )
    agent = VolumePlannerAgent(async_session)
    agent._generate_volume_plan = AsyncMock(return_value=large_plan)
    agent._generate_score = AsyncMock(return_value=VolumeScoreResult(
        overall=60,
        outline_fidelity=80,
        character_plot_alignment=60,
        hook_distribution=60,
        foreshadowing_management=80,
        chapter_hooks=70,
        page_turning=65,
        summary_feedback="需要继续细化",
    ))
    agent._revise_volume_plan = AsyncMock(side_effect=AssertionError("large plan should not trigger full revise"))

    plan = await agent.plan("n_large_skip", volume_number=1)

    assert plan.total_chapters == 20
    agent._revise_volume_plan.assert_not_called()


@pytest.mark.asyncio
async def test_generate_volume_plan_batches_large_projects(async_session):
    agent = VolumePlannerAgent(async_session)
    synopsis = SynopsisData(
        title="道经照诸天",
        logline="陆照在诸天万界争夺超脱路径。",
        core_conflict="陆照 vs 末劫幕后布局者",
        estimated_volumes=26,
        estimated_total_chapters=1300,
        estimated_total_words=3900000,
        volume_outlines=[
            {
                "volume_number": 1,
                "title": "轮回初醒",
                "summary": "陆照初入局，确认轮回空间的威胁。",
                "main_goal": "夺回第一枚道印",
                "main_conflict": "陆照 vs 轮回使者",
                "climax": "夺印成功",
                "hook_to_next": "第二枚道印现世",
            },
            {
                "volume_number": 2,
                "title": "道庭追索",
                "summary": "道庭介入，陆照被迫离开旧地。",
                "main_goal": "查明道庭来历",
            },
        ],
    )

    blueprint = VolumePlanBlueprint(
        volume_id="vol_1",
        volume_number=1,
        title="第一卷",
        summary="卷总述",
        total_chapters=10,
        estimated_total_words=30000,
        chapters=[
            {"chapter_number": index, "title": f"第{index}章", "summary": f"第{index}章摘要"}
            for index in range(1, 11)
        ],
    )
    first_batch = [
        VolumeBeat(
            chapter_id=f"ch_{index}",
            chapter_number=index,
            title=f"第{index}章",
            summary=f"第{index}章剧情",
            target_word_count=3000,
            target_mood="tense",
            beats=[BeatPlan(summary=f"B{index}", target_mood="tense")],
        )
        for index in range(1, 9)
    ]
    second_batch = [
        VolumeBeat(
            chapter_id=f"ch_{index}",
            chapter_number=index,
            title=f"第{index}章",
            summary=f"第{index}章剧情",
            target_word_count=3000,
            target_mood="tense",
            beats=[BeatPlan(summary=f"B{index}", target_mood="tense")],
        )
        for index in range(9, 11)
    ]
    middle_batch = [
        VolumeBeat(
            chapter_id=f"ch_{index}",
            chapter_number=index,
            title=f"第{index}章",
            summary=f"第{index}章剧情",
            target_word_count=3000,
            target_mood="tense",
            beats=[BeatPlan(summary=f"B{index}", target_mood="tense")],
        )
        for index in range(5, 9)
    ]

    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=blueprint.model_dump_json()),
        LLMResponse(text=f"[{','.join(chapter.model_dump_json() for chapter in first_batch[:4])}]"),
        LLMResponse(text=f"[{','.join(chapter.model_dump_json() for chapter in middle_batch)}]"),
        LLMResponse(text=f"[{','.join(chapter.model_dump_json() for chapter in second_batch)}]"),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        plan = await agent._generate_volume_plan(synopsis, 1, novel_id="n_large_batches")

    assert len(plan.chapters) == 10
    assert mock_client.acomplete.await_count == 4


@pytest.mark.asyncio
async def test_generate_volume_plan_prompt_limits_output_scale_for_large_projects(async_session):
    agent = VolumePlannerAgent(async_session)
    synopsis = SynopsisData(
        title="道经照诸天",
        logline="陆照在诸天万界争夺超脱路径。",
        core_conflict="陆照 vs 末劫幕后布局者",
        estimated_volumes=26,
        estimated_total_chapters=1300,
        estimated_total_words=3900000,
        volume_outlines=[
            {
                "volume_number": 1,
                "title": "轮回初醒",
                "summary": "陆照初入局，确认轮回空间的威胁。",
                "main_goal": "夺回第一枚道印",
                "main_conflict": "陆照 vs 轮回使者",
                "climax": "夺印成功",
                "hook_to_next": "第二枚道印现世",
            },
            {
                "volume_number": 2,
                "title": "道庭追索",
                "summary": "道庭介入，陆照被迫离开旧地。",
                "main_goal": "查明道庭来历",
            },
        ],
    )

    blueprint = VolumePlanBlueprint(
        volume_id="vol_1",
        volume_number=1,
        title="第一卷",
        summary="卷总述",
        total_chapters=20,
        estimated_total_words=60000,
        chapters=[
            {"chapter_number": index, "title": f"第{index}章", "summary": f"第{index}章摘要"}
            for index in range(1, 9)
        ],
    )
    first_expanded_batch = [
        VolumeBeat(
            chapter_id=f"ch_{index}",
            chapter_number=index,
            title=f"第{index}章",
            summary=f"第{index}章剧情",
            target_word_count=3000,
            target_mood="tense",
            beats=[BeatPlan(summary=f"B{index}", target_mood="tense")],
        )
        for index in range(1, 5)
    ]
    second_expanded_batch = [
        VolumeBeat(
            chapter_id=f"ch_{index}",
            chapter_number=index,
            title=f"第{index}章",
            summary=f"第{index}章剧情",
            target_word_count=3000,
            target_mood="tense",
            beats=[BeatPlan(summary=f"B{index}", target_mood="tense")],
        )
        for index in range(5, 9)
    ]
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=blueprint.model_dump_json()),
        LLMResponse(text=f"[{','.join(chapter.model_dump_json() for chapter in first_expanded_batch)}]"),
        LLMResponse(text=f"[{','.join(chapter.model_dump_json() for chapter in second_expanded_batch)}]"),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        await agent._generate_volume_plan(synopsis, 1, novel_id="n_large")

    first_prompt = mock_client.acomplete.await_args_list[0].args[0][0].content
    second_prompt = mock_client.acomplete.await_args_list[1].args[0][0].content
    assert "VolumePlanBlueprint" in first_prompt
    assert "本卷总纲契约" in first_prompt
    assert "夺回第一枚道印" in first_prompt
    assert "下一卷契约" in first_prompt
    assert "ActiveConstraintContext" in first_prompt
    assert "当前阶段边界" in first_prompt
    assert "高阶敌人、终局真相、后续世界/体系" in first_prompt
    assert "不要返回 beats" in first_prompt
    assert "total_chapters 必须控制在 20-36 章之间" in first_prompt
    assert "不要试图一次覆盖整部小说的全部章节" in first_prompt
    assert "只返回合法 JSON 数组" in second_prompt
    assert "chapter_id 必须逐项使用本批待扩展章节提供的 chapter_id" in second_prompt
    assert "ActiveConstraintContext" in second_prompt
    assert "不要把只能伏笔的高阶内容写成本批正面冲突" in second_prompt


@pytest.mark.asyncio
async def test_revise_volume_plan_applies_patch_without_rewriting_full_plan(async_session, monkeypatch):
    agent = VolumePlannerAgent(async_session)
    original = VolumePlan(
        volume_id="vol_1",
        volume_number=1,
        title="第一卷",
        summary="旧卷摘要",
        total_chapters=2,
        estimated_total_words=6000,
        chapters=[
            VolumeBeat(
                chapter_id="ch_1",
                chapter_number=1,
                title="第一章",
                summary="第一章旧摘要",
                target_word_count=3000,
                target_mood="tense",
                beats=[BeatPlan(summary="第一章节拍", target_mood="tense")],
            ),
            VolumeBeat(
                chapter_id="ch_2",
                chapter_number=2,
                title="第二章",
                summary="第二章旧摘要",
                target_word_count=3000,
                target_mood="tense",
                beats=[BeatPlan(summary="第二章旧节拍", target_mood="tense")],
            ),
        ],
    )
    captured = {}

    async def fake_call_and_parse_model(agent_name, task, prompt, model_cls, max_retries=3, novel_id=""):
        captured["task"] = task
        captured["model_cls"] = model_cls
        captured["prompt"] = prompt
        return VolumePlanPatch(
            summary="新卷摘要",
            chapter_patches=[
                {
                    "chapter_number": 2,
                    "summary": "第二章新摘要",
                    "beats": [{"summary": "第二章新节拍", "target_mood": "紧张"}],
                }
            ],
        )

    monkeypatch.setattr("novel_dev.agents.volume_planner.call_and_parse_model", fake_call_and_parse_model)

    revised = await agent._revise_volume_plan(original, "第二章冲突不足", "上下文", "n_patch")

    assert captured["task"] == "revise_volume_plan"
    assert captured["model_cls"] is VolumePlanPatch
    assert "只返回需要修改的字段" in captured["prompt"]
    assert revised.summary == "新卷摘要"
    assert revised.total_chapters == 2
    assert revised.chapters[0].summary == "第一章旧摘要"
    assert revised.chapters[1].summary == "第二章新摘要"
    assert revised.chapters[1].beats[0].summary == "第二章新节拍"


@pytest.mark.asyncio
async def test_plan_volume_missing_synopsis(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_no_syn",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )
    agent = VolumePlannerAgent(async_session)
    with pytest.raises(ValueError, match="synopsis_data missing"):
        await agent.plan("n_no_syn")


@pytest.mark.asyncio
async def test_plan_volume_max_attempts(async_session):
    director = NovelDirector(session=async_session)
    synopsis = SynopsisData(
        title="Test",
        logline="Logline",
        core_conflict="Conflict",
        estimated_volumes=1,
        estimated_total_chapters=1,
        estimated_total_words=3000,
    )
    await director.save_checkpoint(
        "n_max",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={"synopsis_data": synopsis.model_dump(), "volume_plan_attempt_count": 2},
        volume_id=None,
        chapter_id=None,
    )

    agent = VolumePlannerAgent(async_session)

    async def _mock_generate_score(plan, novel_id=""):
        return VolumeScoreResult(
            overall=50,
            outline_fidelity=50,
            character_plot_alignment=50,
            hook_distribution=50,
            foreshadowing_management=50,
            chapter_hooks=50,
            page_turning=50,
            summary_feedback="too weak",
        )

    async def _mock_revise_volume_plan(plan, feedback, plan_context="", novel_id=""):
        return plan

    agent._generate_score = _mock_generate_score
    agent._revise_volume_plan = _mock_revise_volume_plan

    plan = await agent.plan("n_max")

    state = await director.resume("n_max")
    assert state.current_phase == Phase.VOLUME_PLANNING.value
    assert plan.volume_id == "vol_1"
    assert state.checkpoint_data["volume_plan_attempt_count"] == 3
    review_status = state.checkpoint_data["current_volume_plan"]["review_status"]
    assert review_status["status"] == "revise_failed"
    assert review_status["score"]["overall"] == 50
    assert "最大自动修订次数" in review_status["reason"]


@pytest.mark.asyncio
async def test_plan_volume_keeps_review_status_when_revise_fails(async_session):
    director = NovelDirector(session=async_session)
    synopsis = SynopsisData(
        title="Test",
        logline="Logline",
        core_conflict="Conflict",
        estimated_volumes=1,
        estimated_total_chapters=1,
        estimated_total_words=3000,
    )
    await director.save_checkpoint(
        "n_revise_failed",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={"synopsis_data": synopsis.model_dump()},
        volume_id=None,
        chapter_id=None,
    )

    plan = VolumePlan(
        volume_id="vol_1",
        volume_number=1,
        title="第一卷",
        summary="卷总述",
        total_chapters=1,
        estimated_total_words=3000,
        chapters=[
            VolumeBeat(
                chapter_id="ch_1",
                chapter_number=1,
                title="第一章",
                summary="章摘要",
                target_word_count=3000,
                target_mood="tense",
                beats=[BeatPlan(summary="B1", target_mood="tense")],
            )
        ],
    )
    agent = VolumePlannerAgent(async_session)
    agent._generate_volume_plan = AsyncMock(return_value=plan)
    agent._generate_score = AsyncMock(return_value=VolumeScoreResult(
        overall=50,
        outline_fidelity=50,
        character_plot_alignment=50,
        hook_distribution=50,
        foreshadowing_management=50,
        chapter_hooks=50,
        page_turning=50,
        summary_feedback="too weak",
    ))
    agent._revise_volume_plan = AsyncMock(side_effect=RuntimeError("parse failed"))

    result = await agent.plan("n_revise_failed")

    state = await director.resume("n_revise_failed")
    assert state.current_phase == Phase.VOLUME_PLANNING.value
    assert result.volume_id == "vol_1"
    review_status = state.checkpoint_data["current_volume_plan"]["review_status"]
    assert review_status["status"] == "revise_failed"
    assert review_status["score"]["overall"] == 50
    assert "parse failed" in review_status["reason"]


@pytest.mark.asyncio
async def test_extract_chapter_plan_merges_foreshadowings(async_session):
    from novel_dev.schemas.context import BeatPlan
    from novel_dev.schemas.outline import VolumeBeat

    agent = VolumePlannerAgent(async_session)
    vb = VolumeBeat(
        chapter_id="ch_1",
        chapter_number=1,
        title="T",
        summary="S",
        target_word_count=100,
        target_mood="tense",
        foreshadowings_to_embed=["fs_1"],
        beats=[BeatPlan(summary="B1", target_mood="dark")],
    )
    cp = agent._extract_chapter_plan(vb)
    assert cp["beats"][0]["foreshadowings_to_embed"] == ["fs_1"]
