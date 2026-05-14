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


def test_clean_text_integrity_fragments_repairs_semantic_truncation():
    text = "追查，还是。\n\n密层在地下。烛火压得只剩豆大，照。\n\n他连站都站不。"

    cleaned = EditorAgent._clean_text_integrity_fragments(text)

    assert "追查，还是保全自身。" in cleaned
    assert "烛火压得只剩豆大，照出一片昏黄。" in cleaned
    assert "他连站都站不起来。" in cleaned


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
    await ChapterRepository(async_session).update_text("c1", raw_draft="Beat one\n\nBeat two")

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="润色后的 Beat one")

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = EditorAgent(async_session)
        await agent.polish("novel_edit", "c1")

    ch = await ChapterRepository(async_session).get_by_id("c1")
    assert "润色后的 Beat one" in ch.polished_text
    assert "Beat two" in ch.polished_text
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
    await ChapterRepository(async_session).update_text("c2", raw_draft="A readable beat")

    agent = EditorAgent(async_session)
    await agent.polish("novel_edit_high_readability", "c2")

    ch = await ChapterRepository(async_session).get_by_id("c2")
    assert ch.polished_text == "A readable beat"
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
    assert "使用已有悬念" in prompt
    assert "已有物件、风险、情绪余波" in prompt
    assert "有限留白" in prompt
    assert "计划和原段已经给出的事实" in prompt
    assert "正文只升级已有事实" in prompt
    assert "黑影、追兵、身份背景、额外线索" in prompt
    assert "只吸收其读感目标" in prompt


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
    assert "当场后果、人物迟疑、身体反应、未完成动作和已知风险逼近" in prompt


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
