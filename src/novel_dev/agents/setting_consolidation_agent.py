import json
from typing import Any

from pydantic import BaseModel, Field

from novel_dev.agents._llm_helpers import call_and_parse_model


class ConsolidationChange(BaseModel):
    target_type: str
    operation: str
    target_id: str | None = None
    before_snapshot: dict[str, Any] | None = None
    after_snapshot: dict[str, Any] | None = None
    conflict_hints: list[dict[str, Any]] = Field(default_factory=list)


class ConsolidationResult(BaseModel):
    summary: str
    changes: list[ConsolidationChange] = Field(default_factory=list)


class SettingConsolidationAgent:
    async def consolidate(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        snapshot_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str)
        prompt = (
            "你是小说设定整合助手。准确率第一，完整性第二，表达润色第三。\n"
            "硬性约束：\n"
            "1. 只能根据输入快照整合设定，不得新增输入快照中不存在的事实、人物、关系、设定、剧情或因果。\n"
            "2. 不得遗漏输入快照中的有效设定；如果多个来源表达同一设定，必须合并保留全部有效信息。\n"
            "3. 不要直接裁决冲突；冲突必须输出 target_type=conflict, operation=resolve，并在 conflict_hints 中列出冲突来源。\n"
            "4. 旧内容被新整合内容吸收时，输出 archive 变更，不要输出 delete。\n"
            "5. 不确定的信息不要补全；保留原文证据或作为 conflict/待确认项进入审核记录。\n"
            "返回 JSON: {summary: string, changes: array}。"
            "\n\n输入快照 JSON:\n"
            f"{snapshot_json}"
        )
        result = await call_and_parse_model(
            "SettingConsolidationAgent",
            "consolidate",
            prompt,
            ConsolidationResult,
            max_retries=3,
            novel_id=str(snapshot.get("novel_id") or ""),
            config_agent_name="setting_consolidation_agent",
            config_task="consolidate",
        )
        return result.model_dump()
