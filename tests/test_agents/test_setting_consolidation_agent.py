import pytest

from novel_dev.agents.setting_consolidation_agent import (
    ConsolidationResult,
    SettingConsolidationAgent,
)


pytestmark = pytest.mark.asyncio


async def test_setting_consolidation_agent_uses_standard_llm_helper(monkeypatch):
    calls = {}

    async def fake_call_and_parse_model(
        agent_name,
        task,
        prompt,
        model_cls,
        *,
        max_retries,
        novel_id,
        config_agent_name,
        config_task,
    ):
        calls.update(
            {
                "agent_name": agent_name,
                "task": task,
                "prompt": prompt,
                "model_cls": model_cls,
                "max_retries": max_retries,
                "novel_id": novel_id,
                "config_agent_name": config_agent_name,
                "config_task": config_task,
            }
        )
        return ConsolidationResult(summary="ok", changes=[])

    monkeypatch.setattr(
        "novel_dev.agents.setting_consolidation_agent.call_and_parse_model",
        fake_call_and_parse_model,
    )

    result = await SettingConsolidationAgent().consolidate({"novel_id": "novel-a", "documents": []})

    assert result == {"summary": "ok", "changes": []}
    assert calls["agent_name"] == "SettingConsolidationAgent"
    assert calls["task"] == "consolidate"
    assert calls["model_cls"] is ConsolidationResult
    assert calls["max_retries"] == 3
    assert calls["novel_id"] == "novel-a"
    assert calls["config_agent_name"] == "setting_consolidation_agent"
    assert calls["config_task"] == "consolidate"
    assert "准确率第一" in calls["prompt"]
    assert "不得新增输入快照中不存在的事实" in calls["prompt"]
    assert "不得遗漏输入快照中的有效设定" in calls["prompt"]
    assert '"documents": []' in calls["prompt"]
    assert '"novel_id": "novel-a"' in calls["prompt"]
    assert "{'novel_id': 'novel-a'" not in calls["prompt"]
