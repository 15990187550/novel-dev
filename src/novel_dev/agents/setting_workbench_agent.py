import json
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
    source_ref: Optional[str] = None
    target_ref: Optional[str] = None
    target_id: Optional[str] = None
    before_snapshot: Optional[dict[str, Any]] = None
    after_snapshot: Optional[dict[str, Any]] = None
    conflict_hints: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_conflict_hints(cls, value: Any):
        if not isinstance(value, dict):
            return value
        conflict_hints = value.get("conflict_hints")
        if conflict_hints is None:
            return value
        if isinstance(conflict_hints, str):
            conflict_hints = [conflict_hints]
        if not isinstance(conflict_hints, list):
            return value
        normalized = []
        changed = False
        for hint in conflict_hints:
            if isinstance(hint, dict):
                normalized.append(hint)
                continue
            if isinstance(hint, str) and hint.strip():
                normalized.append({"type": "llm_note", "message": hint.strip()})
                changed = True
                continue
            normalized.append(hint)
        if not changed:
            return value
        return {**value, "conflict_hints": normalized}

    @model_validator(mode="after")
    def validate_review_change_shape(self):
        if self.operation in {"update", "delete"} and not self.target_id:
            raise ValueError(f"{self.target_type} {self.operation} target_id is required")

        if self.target_type == "relationship" and self.operation == "create":
            snapshot = self.after_snapshot or {}
            if not all(snapshot.get(key) for key in ("source_id", "target_id", "relation_type")):
                raise ValueError("relationship create after_snapshot.source_id, target_id, and relation_type are required")
            ref_fields = [
                field
                for field in ("source_ref", "target_ref")
                if str(snapshot.get(field) or "").strip()
            ]
            if self.source_ref:
                ref_fields.append("source_ref")
            if self.target_ref:
                ref_fields.append("target_ref")
            if ref_fields:
                raise ValueError(f"relationship create must not use ref fields: {', '.join(ref_fields)}")
        return self


class SettingBatchDraft(BaseModel):
    summary: str
    changes: list[SettingBatchChangeDraft] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def parse_stringified_changes(cls, value: Any):
        if not isinstance(value, dict):
            return value
        changes = value.get("changes")
        if not isinstance(changes, str):
            return value
        text = changes.strip()
        if not text:
            return value
        parsed = _parse_json_array_from_text(text)
        if not isinstance(parsed, list):
            return value
        return {**value, "changes": parsed}


def _parse_json_array_from_text(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("[")
    if start < 0:
        return None
    decoder = json.JSONDecoder()
    try:
        parsed, _ = decoder.raw_decode(text[start:])
    except json.JSONDecodeError:
        try:
            parsed, _ = decoder.raw_decode(_escape_raw_control_chars_in_json_strings(text[start:]))
        except json.JSONDecodeError:
            return None
    return parsed


def _escape_raw_control_chars_in_json_strings(text: str) -> str:
    result: list[str] = []
    in_string = False
    escape_next = False
    for ch in text:
        if escape_next:
            if in_string and ch == "\n":
                if result and result[-1] == "\\":
                    result.pop()
                result.append("\\n")
                escape_next = False
                continue
            if in_string and ch == "\r":
                if result and result[-1] == "\\":
                    result.pop()
                result.append("\\r")
                escape_next = False
                continue
            if in_string and ch == "\t":
                if result and result[-1] == "\\":
                    result.pop()
                result.append("\\t")
                escape_next = False
                continue
            result.append(ch)
            escape_next = False
            continue
        if ch == "\\":
            result.append(ch)
            escape_next = True
            continue
        if ch == '"':
            result.append(ch)
            in_string = not in_string
            continue
        if in_string and ch == "\n":
            result.append("\\n")
            continue
        if in_string and ch == "\r":
            result.append("\\r")
            continue
        if in_string and ch == "\t":
            result.append("\\t")
            continue
        result.append(ch)
    return "".join(result)


class SettingWorkbenchAgent:
    @staticmethod
    def build_clarification_prompt(
        *,
        title: str,
        target_categories: list[str],
        messages: list[dict[str, Any]],
        conversation_summary: str | None = None,
        max_rounds: int = 5,
        current_setting_context: dict[str, Any] | None = None,
    ) -> str:
        return "\n".join(
            [
                "你是小说设定工作台的设定澄清助手。",
                "目标：判断用户信息是否足够生成待审核设定批次。",
                "禁止生成正式设定；不足时只提出澄清问题。",
                "澄清问题必须参考当前已生效设定上下文，避免重复询问已有设定。",
                f"会话标题：{title}",
                f"目标分类：{', '.join(target_categories) if target_categories else '默认全量'}",
                f"最大澄清轮数：{max_rounds}",
                f"会话摘要：{conversation_summary or '暂无'}",
                f"当前已生效设定上下文：{current_setting_context or {}}",
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
        current_setting_context: dict[str, Any] | None = None,
        required_sections: list[dict[str, str]] | None = None,
    ) -> str:
        required_section_lines = []
        if required_sections:
            required_section_lines = [
                "必须完整生成以下建议批次：",
                *[
                    f"- {section.get('label') or f'批次{index + 1}'}：{section.get('title', '').strip()}"
                    for index, section in enumerate(required_sections)
                    if section.get("title")
                ],
                "每个建议批次必须对应 1 条 setting_card create change；禁止只生成其中一部分。",
                "setting_card.after_snapshot.title 必须保留对应批次主题，content 必须展开该批次内容。",
                "如果某个建议批次仍有不确定项，也要生成该批次的待审核设定卡，并在 content 或 conflict_hints 中标明待确认点。",
            ]
        return "\n".join(
            [
                "你是小说设定工作台的设定生成助手。",
                "只生成待审核批次，不直接写入正式设定。",
                "准确率第一：不得新增、遗漏、改写用户已确认事实；资料不足时必须标注待确认，禁止凭模型记忆补原著设定。",
                "必须基于当前已生效设定上下文生成，避免重复、串域和覆盖既有设定。",
                "如果当前已生效设定上下文标记 catalog_only，实体 state 只保留索引；涉及已有实体细节、境界、阵营或关系判断时，先调用 query_entity 读取完整详情，不要凭名称猜测。",
                "如果 current_setting_context.source_coverage 已提供 matched_doc_ids，优先用这些 doc_id 调用 get_novel_document_full 获取来源正文；不要重复用 search_domain_documents 搜索同一批已覆盖资料。",
                "涉及外部作品、原著境界体系、跨作品联动、人物归属或世界观对标时，必须先调用 search_domain_documents 按作品名和主题检索资料；需要全文时再调用 get_novel_document_full。",
                "外部作品设定卡的 after_snapshot 必须写入 source_doc_ids，列出支撑该设定的文档 ID；没有足够来源时不要硬生成结论。",
                "境界对标请按来源作品分组或提供来源作品列，每组从低到高排列，并让人物、主角归属与来源资料保持一致。",
                "如需修改或删除已有设定/实体/关系，必须使用上下文中的真实 ID 作为 target_id。",
                "每个批次必须包含至少 1 个 changes，change target_type 只能是 setting_card、entity、relationship。",
                "operation 只能是 create、update、delete。",
                "update/delete 必须提供 target_id，禁止用名称引用代替目标 ID。",
                "setting_card 需要 after_snapshot.doc_type、title、content。",
                "setting_card.after_snapshot.doc_type 使用规范值：worldview、power_system、plot、core_conflict、character_profile；中文展示名写入 title，不要把中文类别写入 doc_type。",
                "全量设定生成必须覆盖：世界观、修炼/力量规则、主角目标与当前动机、核心冲突、第一章可执行目标。",
                "entity 需要 after_snapshot.type、name、state。",
                "entity.after_snapshot.state 优先输出结构化对象，至少包含 goal、motivation、conflict、constraints；不要只输出一段不可解析描述。",
                "relationship create 必须提供 after_snapshot.source_id、target_id、relation_type。",
                "relationship create 的 source_id/target_id 必须引用已存在实体 ID，或同一批次中 entity create 的 after_snapshot.id。",
                "如果无法确定实体 ID，不要生成 relationship change；只在实体 state 或设定 content 中描述关系，留待后续优化。",
                "conflict_hints 每项使用对象，例如 {\"type\":\"source_gap\",\"message\":\"待确认内容\"}。",
                "跨作品人物请采用原世界+人物的清晰组合，例如“完美世界石昊、吞噬星空罗峰”，用于表达联动对象和来源归属。",
                *required_section_lines,
                f"会话标题：{title}",
                f"目标分类：{', '.join(target_categories) if target_categories else '默认全量'}",
                f"会话摘要：{conversation_summary or '暂无'}",
                f"聚焦上下文：{focused_context or {}}",
                f"当前已生效设定上下文：{current_setting_context or {}}",
                "消息历史：",
                *[f"{item.get('role')}: {item.get('content')}" for item in messages],
                "返回 SettingBatchDraft JSON。",
            ]
        )
