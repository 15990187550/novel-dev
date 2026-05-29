from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.editor_agent import EditorAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.llm.models import LLMResponse
from novel_dev.services.chapter_structure_guard_service import ChapterStructureGuardResult
from novel_dev.services.log_service import LogService


@pytest.fixture(autouse=True)
def clear_log_buffers():
    LogService._buffers.clear()
    LogService._listeners.clear()


def test_clean_isolated_punctuation_paragraphs():
    text = "林照撞进泥地。\n\n。\n\n他撑着石壁起身。\n\n！"

    cleaned = EditorAgent._clean_isolated_punctuation_paragraphs(text)

    assert cleaned == "林照撞进泥地。\n\n他撑着石壁起身。"


def test_clean_text_integrity_fragments_drops_truncated_tails_without_inventing_content():
    text = "追查，还是。\n\n密层在地下。烛火压得只剩豆大，照。\n\n他连站都站不。\n\n守门人没动，剑柄上的。\n\n他没走正门，绕。\n\n手指僵在半。"

    cleaned = EditorAgent._clean_text_integrity_fragments(text)

    assert "追查。" in cleaned
    assert "密层在地下。" in cleaned
    assert "守门人没动。" in cleaned
    assert "他没走正门。" in cleaned
    assert "保全自身" not in cleaned
    assert "照出一片昏黄" not in cleaned
    assert "站不起来" not in cleaned
    assert "铜环" not in cleaned
    assert "偏殿" not in cleaned
    assert "僵在半空" not in cleaned


def test_clean_text_integrity_fragments_removes_markdown_section_separator():
    text = "第一段动作。\n\n---\n\n第二段动作。"

    cleaned = EditorAgent._clean_text_integrity_fragments(text)

    assert "---" not in cleaned
    assert cleaned == "第一段动作。\n\n第二段动作。"


def test_hook_score_below_quality_line_forces_last_beat_rewrite():
    assert EditorAgent._hook_score_requires_last_beat_rewrite(72)
    assert EditorAgent._hook_score_requires_last_beat_rewrite(74.9)
    assert not EditorAgent._hook_score_requires_last_beat_rewrite(75)
    assert not EditorAgent._hook_score_requires_last_beat_rewrite(None)


def test_repair_task_is_not_complete_when_flagged_phrase_remains():
    task = {
        "task_type": "prose_polish",
        "issue_codes": ["humanity"],
        "problem": "情感状态由作者总结式交代（'崩溃边缘''他只剩一个念头还清晰'），而非通过具体动作呈现。",
    }

    assert not EditorAgent._repair_task_completed_by_text(
        task,
        "他已经到了崩溃边缘。\n\n他只剩一个念头还清晰。",
        "视野边缘开始发黑，他只剩一个念头还清晰。",
    )


def test_repair_task_issue_prompts_dynamic_flagged_phrases_as_completion_criteria():
    task = {
        "task_type": "character_repair",
        "issue_codes": ["critical_dimension_score"],
        "problem": "关键维度 humanity 低于质量线。",
        "evidence": [
            "comment=作者替人物总结情绪和风险。'当场风险在累积''成了失控的佐证'仍是外部解释。",
        ],
        "success_criteria": ["人物心理改为当场身体反应和失败动作。"],
    }

    issue = EditorAgent._repair_task_to_issue(task)

    assert "当场风险在累积" in issue["problem"]
    assert "成了失控的佐证" in issue["problem"]
    assert "被评审点名的原文短语需改写到不再原样出现" in issue["problem"]
    assert "完成标准之一" in issue["suggestion"]


def test_editor_prose_hygiene_includes_narration_hygiene_issues():
    issues = EditorAgent._prose_hygiene_issues(
        "继续推进，还是强行收束？若此刻失控，经脉尽断；但若强行中断，线索断绝。此刻却成了失控的佐证。",
        1,
        {},
    )

    assert issues
    problem = issues[0]["problem"]
    assert "作者式理性选项题" in problem
    assert "条件推演式风险总结" in problem
    assert "抽象定性句" in problem


def test_editor_formats_cohesion_repair_task_prompt():
    prompt = EditorAgent._build_repair_task_prompt(
        "林照把残信收起。下一句忽然转到城门。",
        {
            "task_type": "cohesion",
            "issue_codes": ["jump_cut", "missing_transition"],
            "constraints": ["不能新增追兵", "保留残信"],
            "success_criteria": ["补出动作过渡", "只使用本章计划已有事实"],
        },
        {
            "chapter_plan": {
                "title": "残信入袖",
                "summary": "林照藏好残信后绕路离开。",
                "beats": [{"summary": "林照收起残信并判断去向"}],
            }
        },
    )

    assert "cohesion" in prompt
    assert "jump_cut" in prompt
    assert "不能新增追兵" in prompt
    assert "补出动作过渡" in prompt
    assert "残信入袖" in prompt
    assert "林照藏好残信后绕路离开" in prompt
    assert "林照把残信收起" in prompt
    assert "严禁新增章节计划外的人物、物件、线索、威胁、地点或事件" in prompt


@pytest.mark.asyncio
async def test_retry_unfinished_repair_tasks_prompts_remaining_flagged_phrases(async_session):
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="陆照指甲掐进掌心，借疼痛去截断失控真气。")
    task = {
        "task_type": "character_repair",
        "issue_codes": ["critical_dimension_score"],
        "evidence": ["'当场风险在累积'仍是作者替人物权衡。"],
    }

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await EditorAgent(async_session)._retry_unfinished_repair_tasks(
            source_text="当场风险在累积。",
            polished_text="当场风险在累积，陆照必须决断。",
            unfinished_tasks=[task],
            chapter_context={"chapter_plan": {"title": "识海异动"}},
        )

    assert result == "陆照指甲掐进掌心，借疼痛去截断失控真气。"
    prompt = mock_client.acomplete.call_args.args[0][0].content
    assert "必须改写到以下短语不再原样出现" in prompt
    assert "当场风险在累积" in prompt


@pytest.mark.asyncio
async def test_rewrite_beat_prompt_sanitizes_chapter_plan_meta_language(async_session):
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="陆照发现识海异动后压住呼吸。")

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = EditorAgent(async_session)
        await agent._rewrite_beat(
            "陆照发现识海异动。",
            {},
            [{"dim": "hook_strength", "problem": "章末偏弱", "suggestion": "强化停点。"}],
            [],
            {
                "chapter_plan": {
                    "title": "识海异动",
                    "beats": [
                        {
                            "summary": (
                                "陆照发现识海异动；"
                                "陆照推进“识海异动”时发现原计划受阻，对手或环境压力逼他立刻调整行动；"
                                "若局面继续拖延，陆照会失去处理“识海异动”的主动权。"
                            )
                        }
                    ],
                }
            },
        )

    prompt = mock_client.acomplete.call_args.args[0][0].content
    assert "陆照发现识海异动" in prompt
    assert "原计划受阻" not in prompt
    assert "对手或环境压力逼" not in prompt
    assert "主动权" not in prompt


def test_editor_repair_task_prompt_includes_evidence_without_mechanical_requirements():
    prompt = EditorAgent._build_repair_task_prompt(
        "林照垂眼，心中暗惊。他终于意识到麻烦来了。",
        {
            "task_type": "character_repair",
            "issue_codes": ["humanity"],
            "evidence": ["情绪由作者总结，没有落到人物动作和关系压力上"],
            "problem": "人味不足，角色反应停在概括层",
            "suggestion": "把反应落回当前场景已有动作、停顿、视线或身体变化。",
            "constraints": ["不新增人物或台词功能"],
            "success_criteria": ["读者能从行为读出压力，而不是由作者替角色总结"],
        },
        {
            "chapter_plan": {
                "title": "药圃夜声",
                "summary": "林照在药圃发现异常，但不能惊动巡夜弟子。",
            }
        },
    )

    assert "人味不足" in prompt
    assert "情绪由作者总结" in prompt
    assert "把反应落回当前场景已有动作" in prompt
    assert "不新增人物或台词功能" in prompt
    assert "必须加对话" not in prompt
    assert "必须出现" not in prompt


@pytest.mark.asyncio
async def test_rewrite_beat_uses_compiled_style_contract_instead_of_raw_json(async_session):
    agent = EditorAgent(async_session)
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="林照把残信压进袖口，没抬头。")

    with patch("novel_dev.llm.llm_factory.get", return_value=mock_client):
        await agent._rewrite_beat(
            "林照意识到麻烦来了。",
            {"humanity": 60},
            [{"dim": "humanity", "problem": "人味不足", "suggestion": "改成动作承载。"}],
            [],
            {
                "style_profile": {
                    "style_guide": "克制、具体。",
                    "character_rules": ["情绪用动作和停顿呈现。"],
                    "anti_ai_rules": ["不要作者总结。"],
                }
            },
        )

    prompt = mock_client.acomplete.call_args.args[0][0].content
    assert "### 写法合同" in prompt
    assert "#### 角色表达" in prompt
    assert "情绪用动作和停顿呈现" in prompt
    assert "#### 反AI风险" in prompt
    assert "不要作者总结" in prompt
    assert '"style_guide"' not in prompt
    assert '"character_rules"' not in prompt


def test_editor_selects_repair_tasks_for_beat():
    tasks = [
        {"task_type": "chapter_cohesion", "beat_index": None, "issue_codes": ["chapter_gap"]},
        {"task_type": "beat_1", "beat_index": 1, "issue_codes": ["beat_gap"]},
        {"task_type": "beat_2", "beat_index": 2, "issue_codes": ["other_beat_gap"]},
        {"beat_index": None, "issue_codes": ["missing_task_type"]},
        {"task_type": "malformed_chapter"},
        {"task_type": "empty_codes", "issue_codes": []},
        "invalid",
    ]

    selected = EditorAgent._repair_tasks_for_beat(tasks, 1)

    assert [task["task_type"] for task in selected] == ["chapter_cohesion", "beat_1"]


def test_editor_repair_task_keys_distinguish_constraints_and_success_criteria():
    base_task = {
        "task_type": "cohesion",
        "beat_index": 0,
        "issue_codes": ["missing_transition"],
        "constraints": ["保留残信"],
        "success_criteria": ["补出袖口动作"],
    }
    alternate_task = {
        "task_type": "cohesion",
        "beat_index": 0,
        "issue_codes": ["missing_transition"],
        "constraints": ["不能新增追兵"],
        "success_criteria": ["补出视线过渡"],
    }
    invalid_task = {"task_type": "malformed_chapter"}

    base_key = EditorAgent._repair_task_key(base_task)
    alternate_key = EditorAgent._repair_task_key(alternate_task)

    assert base_key != alternate_key

    outcomes = {
        base_key: {"selected": 1, "changed": 1},
        alternate_key: {"selected": 1, "changed": 0},
    }
    assert EditorAgent._unfinished_repair_tasks([base_task, alternate_task, invalid_task], outcomes) == [alternate_task]


@pytest.mark.asyncio
async def test_polish_rewrites_high_score_beat_with_prose_hygiene_drift(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_edit_hygiene",
        phase=Phase.EDITING,
        checkpoint_data={
            "chapter_context": {
                "chapter_plan": {
                    "title": "山门晨课",
                    "beats": [{"summary": "陆照在晨课中忍住伤势，选择继续站稳。"}],
                }
            },
            "beat_scores": [{"beat_index": 0, "scores": {"humanity": 88, "readability": 86}}],
        },
        volume_id="v_hygiene",
        chapter_id="c_hygiene",
    )
    await ChapterRepository(async_session).create("c_hygiene", "v_hygiene", 1, "Hygiene")
    await ChapterRepository(async_session).update_text(
        "c_hygiene",
        raw_draft="阻力不需要另起一条线，它就压在当前这件事上。他觉得这力道搁前世够把自己送进ICU。",
    )

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="陆照肩背一沉，喉间的血腥味被他硬压回去，只把脚跟重新钉在石阶上。")

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        await EditorAgent(async_session).polish("novel_edit_hygiene", "c_hygiene")

    assert mock_client.acomplete.await_count == 1
    prompt = mock_client.acomplete.call_args.args[0][0].content
    assert "正文卫生硬约束" in prompt
    assert "prose_hygiene" in prompt

    chapter = await ChapterRepository(async_session).get_by_id("c_hygiene")
    assert "ICU" not in chapter.polished_text
    assert "阻力不需要另起一条线" not in chapter.polished_text


@pytest.mark.asyncio
async def test_polish_low_score_beats(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_edit",
        phase=Phase.EDITING,
        checkpoint_data={
            "beat_scores": [
                {"beat_index": 0, "scores": {"humanity": 60}},
                {"beat_index": 1, "scores": {"humanity": 80}},
            ]
        },
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")
    await ChapterRepository(async_session).update_text("c1", raw_draft="第一段\n\n第二段")

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="润色后的第一段")

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = EditorAgent(async_session)
        await agent.polish("novel_edit", "c1")

    ch = await ChapterRepository(async_session).get_by_id("c1")
    assert "润色后的第一段" in ch.polished_text
    assert "第二段" in ch.polished_text
    assert ch.status == "edited"

    state = await director.resume("novel_edit")
    assert state.current_phase == Phase.FAST_REVIEWING.value


@pytest.mark.asyncio
async def test_polish_checkpoint_repair_task_forces_rewrite_and_records_history(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_edit_repair_task",
        phase=Phase.EDITING,
        checkpoint_data={
            "chapter_context": {
                "chapter_plan": {
                    "title": "残信入袖",
                    "summary": "林照藏好残信后绕路离开。",
                    "beats": [{"summary": "林照收起残信并判断去向"}],
                }
            },
            "beat_scores": [{"beat_index": 0, "scores": {"humanity": 90, "readability": 88}}],
            "repair_tasks": [
                {
                    "task_id": "repair-cohesion-1",
                    "task_type": "cohesion",
                    "chapter_id": "c_repair_task",
                    "scope": "beat",
                    "beat_index": 0,
                    "issue_codes": ["missing_transition"],
                    "allowed_materials": ["残信", "袖口", "城门"],
                    "constraints": ["不能新增追兵"],
                    "success_criteria": ["补出动作过渡"],
                }
            ],
        },
        volume_id="v_repair",
        chapter_id="c_repair_task",
    )
    await ChapterRepository(async_session).create("c_repair_task", "v_repair", 1, "Repair Task")
    await ChapterRepository(async_session).update_text(
        "c_repair_task",
        raw_draft="林照把残信收起。下一句忽然转到城门。",
    )

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="林照把残信收入袖中，确认纸角没有外露，才转向城门。")

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        await EditorAgent(async_session).polish("novel_edit_repair_task", "c_repair_task")

    assert mock_client.acomplete.await_count == 1
    prompt = mock_client.acomplete.call_args.args[0][0].content
    assert "质量修复任务" in prompt
    assert "cohesion" in prompt
    assert "repair-cohesion-1" in prompt
    assert "c_repair_task" in prompt
    assert "beat" in prompt
    assert "missing_transition" in prompt
    assert "残信" in prompt
    assert "不能新增追兵" in prompt
    assert "补出动作过渡" in prompt

    chapter = await ChapterRepository(async_session).get_by_id("c_repair_task")
    assert chapter.polished_text == "林照把残信收入袖中，确认纸角没有外露，才转向城门。"

    state = await director.resume("novel_edit_repair_task")
    assert state.checkpoint_data["repair_tasks"] == []
    assert state.checkpoint_data["repair_history"] == [
        {
            "beat_index": 0,
            "task_types": ["cohesion"],
            "issue_codes": ["missing_transition"],
            "task_ids": ["repair-cohesion-1"],
            "task_keys": [repr(EditorAgent._repair_task_key({
                "task_type": "cohesion",
                "task_id": "repair-cohesion-1",
                "chapter_id": "c_repair_task",
                "scope": "beat",
                "beat_index": 0,
                "issue_codes": ["missing_transition"],
                "allowed_materials": ["残信", "袖口", "城门"],
                "constraints": ["不能新增追兵"],
                "success_criteria": ["补出动作过渡"],
            }))],
            "completed": True,
            "status": "completed",
            "attempt": 1,
            "source_preview": "林照把残信收起。下一句忽然转到城门。",
            "polished_preview": "林照把残信收入袖中，确认纸角没有外露，才转向城门。",
            "source_hash": EditorAgent._short_text_hash("林照把残信收起。下一句忽然转到城门。"),
            "polished_hash": EditorAgent._short_text_hash("林照把残信收入袖中，确认纸角没有外露，才转向城门。"),
            "source_chars": len("林照把残信收起。下一句忽然转到城门。"),
            "polished_chars": len("林照把残信收入袖中，确认纸角没有外露，才转向城门。"),
        }
    ]


@pytest.mark.asyncio
async def test_polish_chapter_level_repair_task_rewrites_all_beats_and_records_history(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_edit_chapter_repair_task",
        phase=Phase.EDITING,
        checkpoint_data={
            "beat_scores": [
                {"beat_index": 0, "scores": {"humanity": 90}},
                {"beat_index": 1, "scores": {"humanity": 92}},
            ],
            "repair_tasks": [
                {
                    "task_type": "chapter_cohesion",
                    "beat_index": None,
                    "issue_codes": ["chapter_transition"],
                    "success_criteria": ["每个节拍都补足承接"],
                }
            ],
        },
        volume_id="v_repair",
        chapter_id="c_chapter_repair_task",
    )
    await ChapterRepository(async_session).create("c_chapter_repair_task", "v_repair", 1, "Chapter Repair")
    await ChapterRepository(async_session).update_text(
        "c_chapter_repair_task",
        raw_draft="林照收好残信。\n\n他绕向城门。",
    )

    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text="林照收好残信，先确认袖口压住纸角。"),
        LLMResponse(text="他绕向城门时，仍记着残信上的焦黑字迹。"),
    ]

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        await EditorAgent(async_session).polish(
            "novel_edit_chapter_repair_task",
            "c_chapter_repair_task",
        )

    assert mock_client.acomplete.await_count == 2
    state = await director.resume("novel_edit_chapter_repair_task")
    assert state.checkpoint_data["repair_tasks"] == []
    assert [entry["beat_index"] for entry in state.checkpoint_data["repair_history"]] == [0, 1]
    assert all(
        entry["task_types"] == ["chapter_cohesion"]
        and entry["issue_codes"] == ["chapter_transition"]
        for entry in state.checkpoint_data["repair_history"]
    )


@pytest.mark.asyncio
async def test_polish_whole_chapter_draft_without_anchors_edits_once(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_edit_whole_chapter",
        phase=Phase.EDITING,
        checkpoint_data={
            "drafting_mode": "whole_chapter",
            "draft_metadata": {
                "total_words": 42,
                "beat_coverage": [{"beat_index": None, "word_count": 42}],
            },
            "chapter_context": {
                "chapter_plan": {
                    "title": "同门试探",
                    "beats": [
                        {"summary": "王顺拦路试探"},
                        {"summary": "陆照被迫应招"},
                        {"summary": "围观弟子察觉异常"},
                    ],
                }
            },
            "beat_scores": [{"beat_index": None, "scores": {"humanity": 62}}],
            "repair_tasks": [
                {
                    "task_type": "cohesion_repair",
                    "beat_index": None,
                    "issue_codes": ["beat_cohesion"],
                    "success_criteria": ["只整体修复一次，不按自然段重复扩写"],
                }
            ],
        },
        volume_id="v_whole",
        chapter_id="c_whole",
    )
    await ChapterRepository(async_session).create("c_whole", "v_whole", 3, "Whole Chapter")
    raw_draft = "王顺拦住去路。\n\n陆照被迫应招。\n\n围观弟子低声议论。"
    await ChapterRepository(async_session).update_text("c_whole", raw_draft=raw_draft)

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="王顺拦住去路，陆照被迫应招，围观弟子低声议论。")

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = EditorAgent(async_session)
        agent._guard_editor_beat = AsyncMock(side_effect=AssertionError("whole chapter edit must not use beat guard"))
        await agent.polish("novel_edit_whole_chapter", "c_whole")

    assert mock_client.acomplete.await_count == 1
    chapter = await ChapterRepository(async_session).get_by_id("c_whole")
    assert chapter.polished_text == "王顺拦住去路，陆照被迫应招，围观弟子低声议论。"

    state = await director.resume("novel_edit_whole_chapter")
    assert state.current_phase == Phase.FAST_REVIEWING.value
    assert state.checkpoint_data["repair_tasks"] == []
    assert len(state.checkpoint_data["repair_history"]) == 1
    assert state.checkpoint_data["repair_history"][0]["beat_index"] is None


@pytest.mark.asyncio
async def test_polish_whole_chapter_final_gate_warnings_trigger_rewrite(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_edit_whole_chapter_gate_warning",
        phase=Phase.EDITING,
        checkpoint_data={
            "drafting_mode": "whole_chapter",
            "draft_metadata": {
                "total_words": 42,
                "beat_coverage": [{"beat_index": None, "word_count": 42}],
            },
            "chapter_context": {
                "chapter_plan": {
                    "title": "同门试探",
                    "beats": [
                        {"summary": "王顺拦路试探"},
                        {"summary": "陆照被迫应招"},
                        {"summary": "围观弟子察觉异常"},
                    ],
                }
            },
            "beat_scores": [{"beat_index": None, "scores": {"humanity": 82}}],
            "final_polish_issues": {
                "global_issues": [],
                "quality_gate_warnings": [
                    {
                        "code": "required_payoff",
                        "message": "章节计划要求的线索或章末钩子未充分兑现",
                        "detail": {"missing": ["陆照暴露异常并错过同门试探线索"]},
                    }
                ],
            },
        },
        volume_id="v_whole_gate",
        chapter_id="c_whole_gate",
    )
    await ChapterRepository(async_session).create("c_whole_gate", "v_whole_gate", 3, "Whole Chapter Gate")
    raw_draft = "王顺拦住去路。\n\n陆照被迫应招。\n\n围观弟子低声议论。"
    await ChapterRepository(async_session).update_text("c_whole_gate", raw_draft=raw_draft)

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="王顺拦住去路，陆照被迫应招，粥碗声停在他身后。")

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        await EditorAgent(async_session).polish("novel_edit_whole_chapter_gate_warning", "c_whole_gate")

    assert mock_client.acomplete.await_count == 1
    chapter = await ChapterRepository(async_session).get_by_id("c_whole_gate")
    assert chapter.polished_text == "王顺拦住去路，陆照被迫应招，粥碗声停在他身后。"


@pytest.mark.asyncio
async def test_polish_repair_task_rollback_keeps_task_and_skips_success_history(async_session):
    director = NovelDirector(session=async_session)
    repair_task = {
        "task_type": "cohesion",
        "beat_index": 0,
        "issue_codes": ["missing_transition"],
        "success_criteria": ["补出动作过渡"],
    }
    await director.save_checkpoint(
        "novel_edit_repair_task_rollback",
        phase=Phase.EDITING,
        checkpoint_data={
            "beat_scores": [{"beat_index": 0, "scores": {"humanity": 90}}],
            "repair_tasks": [repair_task],
        },
        volume_id="v_repair",
        chapter_id="c_repair_task_rollback",
    )
    await ChapterRepository(async_session).create("c_repair_task_rollback", "v_repair", 1, "Repair Rollback")
    await ChapterRepository(async_session).update_text(
        "c_repair_task_rollback",
        raw_draft="林照把残信收起。",
    )

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="林照把残信收入袖中，立刻听见追兵逼近。")

    async def rollback_guard(**kwargs):
        return kwargs["source_text"]

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = EditorAgent(async_session)
        agent._guard_editor_beat = AsyncMock(side_effect=rollback_guard)
        await agent.polish("novel_edit_repair_task_rollback", "c_repair_task_rollback")

    state = await director.resume("novel_edit_repair_task_rollback")
    assert state.checkpoint_data["repair_tasks"] == [repair_task]
    assert "repair_history" not in state.checkpoint_data


@pytest.mark.asyncio
async def test_polish_same_beat_multiple_repair_tasks_complete_together_when_changed(async_session):
    director = NovelDirector(session=async_session)
    repair_tasks = [
        {
            "task_type": "cohesion",
            "beat_index": 0,
            "issue_codes": ["missing_transition"],
            "constraints": ["保留残信"],
            "success_criteria": ["补出袖口动作"],
        },
        {
            "task_type": "cohesion",
            "beat_index": 0,
            "issue_codes": ["missing_transition"],
            "constraints": ["不能新增追兵"],
            "success_criteria": ["补出视线过渡"],
        },
    ]
    await director.save_checkpoint(
        "novel_edit_ambiguous_repair_tasks",
        phase=Phase.EDITING,
        checkpoint_data={
            "beat_scores": [{"beat_index": 0, "scores": {"humanity": 90}}],
            "repair_tasks": repair_tasks,
        },
        volume_id="v_repair",
        chapter_id="c_ambiguous_repair_tasks",
    )
    await ChapterRepository(async_session).create("c_ambiguous_repair_tasks", "v_repair", 1, "Ambiguous Repair")
    await ChapterRepository(async_session).update_text(
        "c_ambiguous_repair_tasks",
        raw_draft="林照把残信收起。",
    )

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="林照把残信压进袖中，视线扫过城门。")

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        await EditorAgent(async_session).polish(
            "novel_edit_ambiguous_repair_tasks",
            "c_ambiguous_repair_tasks",
        )

    state = await director.resume("novel_edit_ambiguous_repair_tasks")
    assert state.checkpoint_data["repair_tasks"] == []
    assert len(state.checkpoint_data["repair_history"]) == 1
    history = state.checkpoint_data["repair_history"][0]
    assert history["completed"] is True
    assert history["status"] == "completed"
    assert history["task_keys"] == [repr(EditorAgent._repair_task_key(task)) for task in repair_tasks]
    assert history["source_preview"] == "林照把残信收起。"
    assert history["polished_preview"] == "林照把残信压进袖中，视线扫过城门。"
    assert len(history["source_hash"]) == 12
    assert len(history["polished_hash"]) == 12


@pytest.mark.asyncio
async def test_polish_emits_direct_llm_rewrite_step_logs(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_edit_logs",
        phase=Phase.EDITING,
        checkpoint_data={
            "beat_scores": [
                {"beat_index": 0, "scores": {"humanity": 60}},
            ]
        },
        volume_id="v1",
        chapter_id="c_logs",
    )
    await ChapterRepository(async_session).create("c_logs", "v1", 1, "Test")
    await ChapterRepository(async_session).update_text("c_logs", raw_draft="Beat one")

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="润色后的 Beat one")

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = EditorAgent(async_session)
        await agent.polish("novel_edit_logs", "c_logs")

    entries = list(LogService._buffers["novel_edit_logs"])
    assert any(
        entry.get("event") == "agent.step"
        and entry.get("status") == "started"
        and entry.get("node") == "polish_beat"
        for entry in entries
    )
    assert any(
        entry.get("event") == "agent.step"
        and entry.get("status") == "succeeded"
        and entry.get("task") == "polish_beat"
        for entry in entries
    )


@pytest.mark.asyncio
async def test_polish_preserves_high_readability(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_edit_high_readability",
        phase=Phase.EDITING,
        checkpoint_data={
            "beat_scores": [
                {"beat_index": 0, "scores": {"readability": 80}},
            ]
        },
        volume_id="v1",
        chapter_id="c2",
    )
    await ChapterRepository(async_session).create("c2", "v1", 2, "Test")
    await ChapterRepository(async_session).update_text("c2", raw_draft="这是一段可读的正文。")

    agent = EditorAgent(async_session)
    await agent.polish("novel_edit_high_readability", "c2")

    ch = await ChapterRepository(async_session).get_by_id("c2")
    assert ch.polished_text == "这是一段可读的正文。"
    assert ch.status == "edited"


@pytest.mark.asyncio
async def test_rewrite_beat_prompt_requires_cleaning_english_terms(async_session):
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="他摸到竹筒，翻身坐起。")

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = EditorAgent(async_session)
        await agent._rewrite_beat(
            "他摸到竹筒，脑子里冒出一句 snooze。",
            {},
            [],
            [],
            {"style_profile": {}},
        )

    prompt = mock_client.acomplete.call_args.args[0][0].content
    assert "自然中文表达" in prompt
    assert "贴合角色处境" in prompt
    assert "snooze" in prompt


@pytest.mark.asyncio
async def test_rewrite_beat_prompt_includes_context_genre_rules(async_session):
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="他收起账册，先核对合同条款。")

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = EditorAgent(async_session)
        await agent._rewrite_beat(
            "他收起账册。",
            {"readability": 62},
            [{"dim": "readability", "problem": "信息推进太薄", "suggestion": "补具体行动"}],
            [],
            {
                "style_profile": {},
                "genre_prompt_block": "### 类型模板约束\n- 现实组织、合同、资金、法律、职位关系和商业因果应保持可信。",
                "genre_quality_config": {
                    "modern_terms_policy": "allow",
                    "required_setting_dimensions": ["career_status", "business_stakes"],
                },
            },
        )

    prompt = mock_client.acomplete.call_args.args[0][0].content
    assert "类型模板约束" in prompt
    assert "现实组织、合同、资金" in prompt
    assert "career_status" in prompt


@pytest.mark.asyncio
async def test_rewrite_beat_prompt_targets_low_ai_flavor_patterns(async_session):
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="陆照扶着石壁坐稳，先去看掌心。")

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = EditorAgent(async_session)
        await agent._rewrite_beat(
            "光像潮水，意识深处又像万花筒，仿佛有什么存在从古经里醒来。",
            {"humanity": 60, "readability": 62},
            [
                {
                    "dim": "humanity",
                    "problem": "比喻连续堆叠，抽象玄幻词过密",
                    "suggestion": "压缩异象，只保留一个具体画面和一个身体后果",
                }
            ],
            [],
            {"style_profile": {}},
        )

    prompt = mock_client.acomplete.call_args.args[0][0].content
    assert "增强读感" in prompt
    assert "比喻过密" in prompt
    assert "抽象玄幻词" in prompt
    assert "最有辨识度的画面" in prompt
    assert "身体反应、行动阻碍或具体后果" in prompt


@pytest.mark.asyncio
async def test_rewrite_beat_prompt_forbids_plan_external_additions(async_session):
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="林照把玉佩收入掌心，没有回头。")

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = EditorAgent(async_session)
        await agent._rewrite_beat(
            "林照把玉佩收入掌心，没有回头。",
            {"hook_strength": 62},
            [
                {
                    "dim": "hook_strength",
                    "problem": "章末钩子偏弱",
                    "suggestion": "强化已存在悬念，不要扩出新主线",
                }
            ],
            [],
            {
                "style_profile": {},
                "chapter_plan": {
                    "summary": "林照得到玉佩后藏入怀中",
                    "beats": [{"summary": "林照得到玉佩后藏入怀中"}],
                },
            },
        )

    prompt = mock_client.acomplete.call_args.args[0][0].content
    assert "保留叙事事实" in prompt
    assert "局部修补模式" in prompt
    assert "原事件集合" in prompt
    assert "信息释放顺序" in prompt
    assert "不要为了满足形式要求机械添加对话、动作、感官或悬念" in prompt
    assert "让读者的关注点发生推进" in prompt
    assert "已有物件、风险、情绪余波、人物关系" in prompt
    assert "有限留白" in prompt
    assert "计划和原段已经给出的事实" in prompt
    assert "正文只升级已有事实" in prompt
    assert "黑影、追兵、身份背景、额外线索" in prompt
    assert "只吸收其读感目标" in prompt


@pytest.mark.asyncio
async def test_rewrite_beat_prompt_uses_soft_strategy_pool_without_checklist(async_session):
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="陆照把密函往袖底压了半寸，没接执事的话。")

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = EditorAgent(async_session)
        await agent._rewrite_beat(
            "陆照意识到麻烦来了。",
            {"humanity": 60, "plot_tension": 62},
            [
                {
                    "dim": "humanity",
                    "problem": "人物反应停在作者总结",
                    "suggestion": "从软策略池里选择最贴近原段的一种修法。",
                }
            ],
            [],
            {
                "style_profile": {},
                "writing_cards": [
                    {
                        "beat_index": 0,
                        "scene_pressure_lenses": ["可选: 让压力落在门口距离、搜身风险和密函藏处。"],
                        "relationship_subtext_lenses": ["可选: 用执事的停顿、视线和陆照的避让承载试探。"],
                        "prose_texture_lenses": ["优先把抽象压力落到手心、门缝冷光和药灰味。"],
                        "freshness_lenses": ["避免复用上一章的昏迷式收束，改用关系压力停点。"],
                    }
                ],
            },
        )

    prompt = mock_client.acomplete.call_args.args[0][0].content
    assert "可选叙事策略池" in prompt
    assert "这些策略不是逐项硬性完成" in prompt
    assert "门口距离、搜身风险" in prompt
    assert "执事的停顿、视线" in prompt
    assert "最小有效修法" in prompt
    assert "必须短对话" not in prompt


def test_editor_bounds_hook_suggestion_without_copying_review_examples():
    bounded = EditorAgent._bounded_suggestion_for_issue({
        "dim": "hook_strength",
        "suggestion": (
            "在章末最后两段补入一个由本章已出现线索触发的即时新信号："
            "例如主角摊开残页，发现虫蛀处露出一行被墨迹覆盖过的模糊字迹；"
            "或体内穴窍突然抽吸真气。这样章末从压力汇总升级为下一个行动。"
        ),
    })

    assert "即时新信号" in bounded
    assert "虫蛀" not in bounded
    assert "穴窍突然抽吸" not in bounded
    assert "不要照搬评审示例" in bounded
    assert "必须出现异变" not in bounded


@pytest.mark.asyncio
async def test_rewrite_beat_bounds_risky_hook_suggestions(async_session):
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="林照把残信按在伤口旁，指节迟迟没有松开。")

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = EditorAgent(async_session)
        await agent._rewrite_beat(
            "林照把残信收入怀中，只能绕路。",
            {"hook_strength": 62},
            [
                {
                    "dim": "hook_strength",
                    "problem": "章末钩子偏弱",
                    "suggestion": "加入新的反转，例如：禁地深处亮起一盏灯，有人正朝这边走来。",
                }
            ],
            [],
            {
                "style_profile": {},
                "chapter_plan": {
                    "summary": "林照带伤藏好残信并决定绕路",
                    "beats": [{"summary": "林照带伤藏好残信并决定绕路"}],
                },
            },
        )

    prompt = mock_client.acomplete.call_args.args[0][0].content
    assert "加入新的反转" in prompt
    assert "只使用原文和章节计划已出现的物件、伤势、选择、风险或伏笔" in prompt
    assert "先判断这一段最自然的牵引来源" in prompt
    assert "信息差、关系变化、行动压力、情绪余波、环境异常或人物选择" in prompt


@pytest.mark.asyncio
async def test_polish_uses_final_polish_issues_for_targeted_repair(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_edit_final_polish",
        phase=Phase.EDITING,
        checkpoint_data={
            "chapter_context": {
                "chapter_plan": {
                    "chapter_number": 1,
                    "title": "Test",
                    "target_word_count": 1000,
                    "beats": [{"summary": "林照展开残信", "target_mood": "tense"}],
                }
            },
            "beat_scores": [{"beat_index": 0, "scores": {"hook_strength": 80}}],
            "final_polish_issues": {
                "source": "final_review",
                "beat_issues": [
                    {
                        "beat_index": 0,
                        "issues": [
                            {
                                "dim": "hook_strength",
                                "problem": "章末没有兑现残信线索",
                                "suggestion": "用残信字迹和林照的身体反应强化停点",
                            }
                        ],
                    }
                ],
            },
        },
        volume_id="v_final",
        chapter_id="c_final_polish",
    )
    await ChapterRepository(async_session).create("c_final_polish", "v_final", 1, "Final Polish")
    await ChapterRepository(async_session).update_text("c_final_polish", raw_draft="林照展开残信，慢慢收进袖中。")

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="林照展开残信，指腹停在焦黑字迹上，呼吸慢了半拍。")

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        await EditorAgent(async_session).polish("novel_edit_final_polish", "c_final_polish")

    prompt = mock_client.acomplete.call_args.args[0][0].content
    assert "章末没有兑现残信线索" in prompt
    assert "用残信字迹和林照的身体反应强化停点" in prompt

    state = await director.resume("novel_edit_final_polish")
    assert "final_polish_issues" not in state.checkpoint_data


@pytest.mark.asyncio
async def test_polish_treats_quality_gate_required_payoff_as_actionable_repair(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_edit_required_payoff",
        phase=Phase.EDITING,
        checkpoint_data={
            "chapter_context": {
                "chapter_plan": {
                    "chapter_number": 2,
                    "title": "异样感知",
                    "target_word_count": 1000,
                    "beats": [{"summary": "陆照试探残页感知并决定明早去后山查看"}],
                }
            },
            "beat_scores": [{"beat_index": 0, "scores": {"plot_tension": 82, "hook_strength": 80}}],
            "final_polish_issues": {
                "source": "final_review",
                "global_issues": [
                    {"dim": "plot_tension", "problem": f"全章问题 {idx}", "suggestion": "压缩重复试探"}
                    for idx in range(5)
                ],
                "quality_gate_warnings": [
                    {
                        "code": "required_payoff",
                        "message": "章节计划要求的线索或章末钩子未充分兑现",
                        "detail": {"missing": ["感知范围远超当前修为"]},
                    }
                ],
            },
        },
        volume_id="v_required_payoff",
        chapter_id="c_required_payoff",
    )
    await ChapterRepository(async_session).create("c_required_payoff", "v_required_payoff", 2, "Required Payoff")
    await ChapterRepository(async_session).update_text(
        "c_required_payoff",
        raw_draft="陆照按住残页，感知在屋内转了一圈，最后把残页藏回枕下。",
    )

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="陆照按住残页，听见远处滴水声清晰得反常，才把残页藏回枕下。")

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        await EditorAgent(async_session).polish("novel_edit_required_payoff", "c_required_payoff")

    assert mock_client.acomplete.called
    prompt = mock_client.acomplete.call_args.args[0][0].content
    assert "感知范围远超当前修为" in prompt
    assert "章节计划要求的线索或章末钩子未充分兑现" in prompt


@pytest.mark.asyncio
async def test_polish_rolls_back_when_editor_guard_detects_plan_external_addition(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_edit_guard",
        phase=Phase.EDITING,
        checkpoint_data={
            "chapter_context": {
                "chapter_plan": {
                    "chapter_number": 1,
                    "title": "Test",
                    "target_word_count": 1000,
                    "beats": [{"summary": "林照藏起玉佩", "target_mood": "tense"}],
                }
            },
            "beat_scores": [
                {"beat_index": 0, "scores": {"humanity": 60}},
            ],
        },
        volume_id="v_guard",
        chapter_id="c_guard",
    )
    await ChapterRepository(async_session).create("c_guard", "v_guard", 1, "Test")
    await ChapterRepository(async_session).update_text("c_guard", raw_draft="林照藏起玉佩。")

    class FakeGuard:
        async def check_editor_beat(self, **kwargs):
            return ChapterStructureGuardResult(
                passed=False,
                completed_current_beat=True,
                premature_future_beat=False,
                introduced_plan_external_fact=True,
                changed_event_order=False,
                issues=["新增计划外黑影台词"],
                suggested_rewrite_focus="删除计划外台词",
            )

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="林照藏起玉佩。黑影说：你逃不掉。")

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = EditorAgent(async_session, structure_guard=FakeGuard())
        await agent.polish("novel_edit_guard", "c_guard")

    ch = await ChapterRepository(async_session).get_by_id("c_guard")
    assert ch.polished_text == "林照藏起玉佩。"
    state = await director.resume("novel_edit_guard")
    assert state.checkpoint_data["editor_guard_warnings"][0]["issues"] == ["新增计划外黑影台词"]


@pytest.mark.asyncio
async def test_editor_guard_retry_pass_records_resolved_not_warning(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_edit_guard_retry_pass",
        phase=Phase.EDITING,
        checkpoint_data={
            "chapter_context": {
                "chapter_plan": {
                    "chapter_number": 1,
                    "title": "Test",
                    "target_word_count": 1000,
                    "beats": [{"summary": "林照藏起玉佩", "target_mood": "tense"}],
                }
            },
            "beat_scores": [{"beat_index": 0, "scores": {"humanity": 60}}],
        },
        volume_id="v_guard",
        chapter_id="c_guard_retry_pass",
    )
    await ChapterRepository(async_session).create("c_guard_retry_pass", "v_guard", 1, "Test")
    await ChapterRepository(async_session).update_text("c_guard_retry_pass", raw_draft="林照藏起玉佩。")

    class FakeGuard:
        def __init__(self):
            self.calls = 0

        async def check_editor_beat(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return ChapterStructureGuardResult(
                    passed=False,
                    completed_current_beat=True,
                    premature_future_beat=False,
                    introduced_plan_external_fact=True,
                    changed_event_order=False,
                    issues=["新增计划外黑影台词"],
                    suggested_rewrite_focus="删除计划外台词",
                )
            return ChapterStructureGuardResult(
                passed=True,
                completed_current_beat=True,
                premature_future_beat=False,
                introduced_plan_external_fact=False,
                changed_event_order=False,
                issues=[],
                suggested_rewrite_focus="",
            )

    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text="林照藏起玉佩。黑影说：你逃不掉。"),
        LLMResponse(text="林照藏起玉佩，指腹在裂纹上停了半息。"),
    ]

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = EditorAgent(async_session, structure_guard=FakeGuard())
        await agent.polish("novel_edit_guard_retry_pass", "c_guard_retry_pass")

    ch = await ChapterRepository(async_session).get_by_id("c_guard_retry_pass")
    assert ch.polished_text == "林照藏起玉佩，指腹在裂纹上停了半息。"
    state = await director.resume("novel_edit_guard_retry_pass")
    assert "editor_guard_warnings" not in state.checkpoint_data
    assert state.checkpoint_data["editor_guard_resolved"][0]["issues"] == ["新增计划外黑影台词"]


@pytest.mark.asyncio
async def test_polish_standalone_uses_continuity_rewrite_plan_without_low_scores(async_session):
    repo = ChapterRepository(async_session)
    await repo.create("c_continuity_edit", "v_continuity_edit", 1, "Continuity Edit")
    await repo.update_text(
        "c_continuity_edit",
        raw_draft="林照忽然醒来，开口说出隐藏多年的真相。",
    )
    await async_session.commit()

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="林照的尸身没有醒来，仍停在黑水城寒榻上。")

    checkpoint = {
        "chapter_context": {
            "chapter_plan": {
                "chapter_number": 1,
                "title": "Continuity Edit",
                "target_word_count": 20,
                "beats": [{"summary": "处理林照尸身异常", "target_mood": "tense"}],
            }
        },
        "continuity_rewrite_plan": {
            "source": "continuity_audit",
            "rewrite_all": True,
            "global_issues": [{
                "code": "dead_entity_acted",
                "dim": "continuity",
                "problem": "林照 当前状态为死亡/尸身，但成稿写成了可行动角色。",
                "suggestion": "不要让死亡/尸身状态角色行动、开口或醒来。",
            }],
        },
    }

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        await EditorAgent(async_session).polish_standalone(
            "novel_continuity_edit",
            "c_continuity_edit",
            checkpoint,
        )

    assert mock_client.acomplete.await_count == 1
    prompt = mock_client.acomplete.call_args.args[0][0].content
    assert "连续性" in prompt
    assert "不要让死亡/尸身状态角色行动、开口或醒来" in prompt

    chapter = await repo.get_by_id("c_continuity_edit")
    assert chapter.polished_text == "林照的尸身没有醒来，仍停在黑水城寒榻上。"


@pytest.mark.asyncio
async def test_polish_retries_once_with_guard_focus_before_rollback(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_edit_guard_retry",
        phase=Phase.EDITING,
        checkpoint_data={
            "chapter_context": {
                "chapter_plan": {
                    "chapter_number": 1,
                    "title": "Test",
                    "target_word_count": 1000,
                    "beats": [{"summary": "林照藏起玉佩", "target_mood": "tense"}],
                }
            },
            "beat_scores": [
                {"beat_index": 0, "scores": {"humanity": 60}},
            ],
        },
        volume_id="v_guard",
        chapter_id="c_guard_retry",
    )
    await ChapterRepository(async_session).create("c_guard_retry", "v_guard", 1, "Test")
    await ChapterRepository(async_session).update_text("c_guard_retry", raw_draft="林照藏起玉佩。")

    class FakeGuard:
        def __init__(self):
            self.calls = 0

        async def check_editor_beat(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return ChapterStructureGuardResult(
                    passed=False,
                    completed_current_beat=True,
                    premature_future_beat=False,
                    introduced_plan_external_fact=True,
                    changed_event_order=False,
                    issues=["新增计划外黑影台词"],
                    suggested_rewrite_focus="删除计划外台词，只保留藏起玉佩",
                )
            assert "黑影" not in kwargs["polished_text"]
            return ChapterStructureGuardResult(passed=True)

    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text="林照藏起玉佩。黑影说：你逃不掉。"),
        LLMResponse(text="林照把玉佩压进袖中，指腹停在裂纹上，慢慢松开呼吸。"),
    ]

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        guard = FakeGuard()
        agent = EditorAgent(async_session, structure_guard=guard)
        await agent.polish("novel_edit_guard_retry", "c_guard_retry")

    ch = await ChapterRepository(async_session).get_by_id("c_guard_retry")
    assert ch.polished_text == "林照把玉佩压进袖中，指腹停在裂纹上，慢慢松开呼吸。"
    assert mock_client.acomplete.await_count == 2
    state = await director.resume("novel_edit_guard_retry")
    assert "editor_guard_warnings" not in state.checkpoint_data
    assert state.checkpoint_data["editor_guard_resolved"][0]["issues"] == ["新增计划外黑影台词"]
