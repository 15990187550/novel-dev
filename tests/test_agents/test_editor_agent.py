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
