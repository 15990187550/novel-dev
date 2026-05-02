from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class SettingClarificationDecision(BaseModel):
    status: Literal["needs_clarification", "ready"]
    assistant_message: str
    questions: list[str] = Field(default_factory=list)
    target_categories: list[str] = Field(default_factory=list)
    conversation_summary: str = ""


class SettingBatchChangeDraft(BaseModel):
    target_type: Literal["setting_card", "entity", "relationship"]
    operation: Literal["create", "update", "delete"]
    target_ref: Optional[str] = None
    target_id: Optional[str] = None
    before_snapshot: Optional[dict[str, Any]] = None
    after_snapshot: Optional[dict[str, Any]] = None
    conflict_hints: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_review_change_shape(self):
        if self.operation in {"update", "delete"} and not self.target_id:
            raise ValueError(f"{self.target_type} {self.operation} target_id is required")

        if self.target_type == "relationship" and self.operation == "create":
            snapshot = self.after_snapshot or {}
            if not all(snapshot.get(key) for key in ("source_id", "target_id", "relation_type")):
                raise ValueError("relationship create after_snapshot.source_id, target_id, and relation_type are required")
        return self


class SettingBatchDraft(BaseModel):
    summary: str
    changes: list[SettingBatchChangeDraft]


class SettingWorkbenchAgent:
    @staticmethod
    def build_clarification_prompt(
        *,
        title: str,
        target_categories: list[str],
        messages: list[dict[str, Any]],
        conversation_summary: str | None = None,
        max_rounds: int = 5,
    ) -> str:
        return "\n".join(
            [
                "你是小说设定工作台的设定澄清助手。",
                "目标：判断用户信息是否足够生成待审核设定批次。",
                "禁止生成正式设定；不足时只提出澄清问题。",
                f"会话标题：{title}",
                f"目标分类：{', '.join(target_categories) if target_categories else '默认全量'}",
                f"最大澄清轮数：{max_rounds}",
                f"会话摘要：{conversation_summary or '暂无'}",
                "消息历史：",
                *[f"{item.get('role')}: {item.get('content')}" for item in messages],
                "返回 SettingClarificationDecision JSON。",
            ]
        )

    @staticmethod
    def build_generation_prompt(
        *,
        title: str,
        target_categories: list[str],
        messages: list[dict[str, Any]],
        conversation_summary: str | None = None,
        focused_context: dict[str, Any] | None = None,
    ) -> str:
        return "\n".join(
            [
                "你是小说设定工作台的设定生成助手。",
                "只生成待审核批次，不直接写入正式设定。",
                "每个批次必须包含 changes，change target_type 只能是 setting_card、entity、relationship。",
                "operation 只能是 create、update、delete。",
                "update/delete 必须提供 target_id，禁止用名称引用代替目标 ID。",
                "setting_card 需要 after_snapshot.doc_type、title、content。",
                "entity 需要 after_snapshot.type、name、state。",
                "relationship create 必须提供 after_snapshot.source_id、target_id、relation_type。",
                "如果只有实体名称，先生成 entity create，并在 relationship after_snapshot 使用那些 entity 的 id 或稳定临时 id。",
                f"会话标题：{title}",
                f"目标分类：{', '.join(target_categories) if target_categories else '默认全量'}",
                f"会话摘要：{conversation_summary or '暂无'}",
                f"聚焦上下文：{focused_context or {}}",
                "消息历史：",
                *[f"{item.get('role')}: {item.get('content')}" for item in messages],
                "返回 SettingBatchDraft JSON。",
            ]
        )
