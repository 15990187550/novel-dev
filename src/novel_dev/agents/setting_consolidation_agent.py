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
            "你是小说设定整合助手。请只根据输入快照整合设定。"
            "不要直接裁决冲突；冲突必须输出 target_type=conflict, operation=resolve。"
            "旧内容被新整合内容吸收时，输出 archive 变更，不要输出 delete。"
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
            config_agent_name="SettingExtractorAgent",
            config_task="extract_setting",
        )
        return result.model_dump()
