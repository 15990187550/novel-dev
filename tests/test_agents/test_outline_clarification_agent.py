import pytest

from novel_dev.agents.outline_clarification_agent import (
    MAX_CLARIFICATION_ROUNDS,
    OutlineClarificationAgent,
    OutlineClarificationDecision,
    OutlineClarificationRequest,
)
from novel_dev.schemas.outline_workbench import OutlineContextWindow, OutlineMessagePayload
from novel_dev.services.log_service import LogService


@pytest.fixture(autouse=True)
def clear_logs():
    LogService._buffers.clear()
    LogService._listeners.clear()


def test_force_generation_intent_matches_common_phrases():
    assert OutlineClarificationAgent.is_force_generate_intent("按当前设定生成")
    assert OutlineClarificationAgent.is_force_generate_intent("不用问了，直接生成")
    assert OutlineClarificationAgent.is_force_generate_intent("先生成第一版")
    assert not OutlineClarificationAgent.is_force_generate_intent("请问我几个关键问题")
    assert not OutlineClarificationAgent.is_force_generate_intent("不要直接生成，先问我问题")
    assert not OutlineClarificationAgent.is_force_generate_intent("不要按当前设定生成，先确认几个问题")


def test_request_rejects_unknown_outline_type():
    with pytest.raises(ValueError):
        OutlineClarificationRequest(
            novel_id="novel-bad",
            outline_type="chapter",
            outline_ref="ch_1",
            feedback="生成",
            context_window=OutlineContextWindow(),
            round_number=1,
            max_rounds=MAX_CLARIFICATION_ROUNDS,
            source_text="",
            workspace_snapshot=None,
            checkpoint_snapshot=None,
        )


def test_prompt_bounds_large_snapshots_and_source_text():
    request = OutlineClarificationRequest(
        novel_id="novel-large",
        outline_type="synopsis",
        outline_ref="synopsis",
        feedback="生成",
        context_window=OutlineContextWindow(),
        round_number=1,
        max_rounds=MAX_CLARIFICATION_ROUNDS,
        source_text="源文本" + "x" * 6000 + "TAIL",
        workspace_snapshot={"content": "w" * 4000 + "WORKSPACE_TAIL"},
        checkpoint_snapshot={"content": "c" * 4000 + "CHECKPOINT_TAIL"},
    )

    prompt = OutlineClarificationAgent()._build_prompt(request)

    assert "TAIL" not in prompt
    assert "WORKSPACE_TAIL" not in prompt
    assert "CHECKPOINT_TAIL" not in prompt
    assert '"content": "' in prompt
    assert '\n  "content"' not in prompt


def test_force_generation_decision_contains_default_assumption():
    decision = OutlineClarificationAgent.force_generate_decision("用户要求跳过进一步澄清")

    assert decision.status == "force_generate"
    assert decision.questions == []
    assert decision.assumptions == ["用户要求跳过进一步澄清，以下内容基于当前设定、当前对话和系统可见资料生成。"]


@pytest.mark.asyncio
async def test_clarify_inherits_volume_generation_config(monkeypatch):
    calls = []

    async def fake_call_and_parse_model(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return OutlineClarificationDecision(
            status="clarifying",
            confidence=0.42,
            missing_points=["卷末钩子不明确"],
            questions=["这一卷结尾要留下什么危机？"],
            clarification_summary="已有卷目标，缺少卷末钩子。",
            assumptions=[],
            reason="缺少结尾方向。",
        )

    monkeypatch.setattr(
        "novel_dev.agents.outline_clarification_agent.call_and_parse_model",
        fake_call_and_parse_model,
    )

    request = OutlineClarificationRequest(
        novel_id="novel-vol",
        outline_type="volume",
        outline_ref="vol_1",
        feedback="生成第一卷卷纲",
        context_window=OutlineContextWindow(
            recent_messages=[
                OutlineMessagePayload(
                    id="m1",
                    role="user",
                    message_type="feedback",
                    content="主角要离开宗门",
                    meta={},
                )
            ]
        ),
        round_number=2,
        max_rounds=MAX_CLARIFICATION_ROUNDS,
        source_text="宗门设定",
        workspace_snapshot=None,
        checkpoint_snapshot=None,
    )

    decision = await OutlineClarificationAgent().clarify(request)

    assert decision.status == "clarifying"
    assert calls[0]["args"][:2] == ("OutlineClarificationAgent", "outline_clarify")
    assert calls[0]["kwargs"]["config_agent_name"] == "VolumePlannerAgent"
    assert calls[0]["kwargs"]["config_task"] == "generate_volume_plan"
    assert calls[0]["kwargs"]["context_metadata"]["outline_ref"] == "vol_1"
    assert "第 2/5 轮" in LogService._buffers["novel-vol"][-1]["message"]


@pytest.mark.asyncio
async def test_clarify_forces_generation_at_round_limit(monkeypatch):
    async def fake_call_and_parse_model(*args, **kwargs):
        return OutlineClarificationDecision(
            status="clarifying",
            confidence=0.2,
            missing_points=["主线目标不明确"],
            questions=["主线目标是什么？"],
            clarification_summary="信息仍不完整。",
            assumptions=[],
            reason="缺少主线。",
        )

    monkeypatch.setattr(
        "novel_dev.agents.outline_clarification_agent.call_and_parse_model",
        fake_call_and_parse_model,
    )

    request = OutlineClarificationRequest(
        novel_id="novel-limit",
        outline_type="synopsis",
        outline_ref="synopsis",
        feedback="继续问",
        context_window=OutlineContextWindow(),
        round_number=MAX_CLARIFICATION_ROUNDS,
        max_rounds=MAX_CLARIFICATION_ROUNDS,
        source_text="",
        workspace_snapshot=None,
        checkpoint_snapshot=None,
    )

    decision = await OutlineClarificationAgent().clarify(request)

    assert decision.status == "force_generate"
    assert decision.questions == []
    assert decision.assumptions
    assert "达到澄清上限" in decision.assumptions[0]
