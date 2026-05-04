from typing import Any

from pydantic import BaseModel, Field

from novel_dev.llm import llm_factory
from novel_dev.llm.models import ChatMessage


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
        prompt = (
            "你是小说设定整合助手。请只根据输入快照整合设定。"
            "不要直接裁决冲突；冲突必须输出 target_type=conflict, operation=resolve。"
            "旧内容被新整合内容吸收时，输出 archive 变更，不要输出 delete。"
            "返回 JSON: {summary: string, changes: array}。"
        )
        messages = [
            ChatMessage(role="system", content=prompt),
            ChatMessage(role="user", content=str(snapshot)),
        ]

        if hasattr(llm_factory, "get_driver"):
            driver = llm_factory.get_driver()
        else:
            driver = llm_factory.get("SettingConsolidationAgent", task="consolidate")

        if hasattr(driver, "chat"):
            response = await driver.chat(
                messages,
                temperature=0.45,
                response_format={"type": "json_object"},
            )
            content = response.content
        else:
            config = getattr(driver, "config", None)
            if config is not None:
                config = config.model_copy(update={"temperature": 0.45})
            response = await driver.acomplete(messages, config)
            content = response.text

        parsed = ConsolidationResult.model_validate_json(content)
        return parsed.model_dump()
