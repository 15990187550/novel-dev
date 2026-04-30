import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from novel_dev.agents._llm_helpers import call_and_parse_model
from novel_dev.schemas.outline_workbench import OutlineContextWindow
from novel_dev.services.log_service import log_service


MAX_CLARIFICATION_ROUNDS = 5
SOURCE_TEXT_PROMPT_LIMIT = 5000
SNAPSHOT_PROMPT_LIMIT = 3000
CONVERSATION_SUMMARY_PROMPT_LIMIT = 2000
RECENT_MESSAGE_PROMPT_LIMIT = 800
FEEDBACK_PROMPT_LIMIT = 2000
DEFAULT_CLARIFICATION_QUESTION = "请补充一个最关键的方向：你希望这个大纲优先突出人物成长、主线冲突还是世界设定？"
DEFAULT_READY_SUMMARY = "当前信息已足够进入大纲生成。"
DEFAULT_FORCE_ASSUMPTION = "信息仍不完整，以下内容基于当前设定、当前对话和系统可见资料生成。"


def _clean_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _clean_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = value.strip()
        return [value] if value else []
    if isinstance(value, list):
        return [item for item in (_clean_string(item) for item in value) if item]
    cleaned = _clean_string(value)
    return [cleaned] if cleaned else []


class OutlineClarificationDecision(BaseModel):
    status: Literal["clarifying", "ready_to_generate", "force_generate"]
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    missing_points: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    clarification_summary: str = ""
    reason: str = ""

    @field_validator("missing_points", "questions", "assumptions", mode="before")
    @classmethod
    def _coerce_string_lists(cls, value: Any) -> list[str]:
        return _clean_string_list(value)

    @field_validator("clarification_summary", "reason", mode="before")
    @classmethod
    def _coerce_strings(cls, value: Any) -> str:
        return _clean_string(value)

    @model_validator(mode="after")
    def _normalize_for_status(self):
        if self.status == "clarifying":
            self.questions = self.questions[:3] or [DEFAULT_CLARIFICATION_QUESTION]
        elif self.status == "ready_to_generate":
            self.questions = []
            if not self.clarification_summary:
                self.clarification_summary = DEFAULT_READY_SUMMARY
        elif self.status == "force_generate":
            self.questions = []
            self.assumptions = self.assumptions or [DEFAULT_FORCE_ASSUMPTION]
        return self


class OutlineClarificationRequest(BaseModel):
    novel_id: str
    outline_type: Literal["synopsis", "volume"]
    outline_ref: str
    feedback: str
    context_window: OutlineContextWindow
    round_number: int
    max_rounds: int
    source_text: str
    workspace_snapshot: Any = None
    checkpoint_snapshot: Any = None


class OutlineClarificationAgent:
    FORCE_GENERATE_PATTERNS = [
        "按当前设定生成",
        "按现有内容生成",
        "直接生成",
        "不用问了",
        "先生成",
        "确认生成",
    ]
    NEGATION_MARKERS = ["不需要马上", "不是让你", "不要现在", "不需要", "不要先", "不想", "先别", "不是", "不要", "别", "不"]
    NEGATION_LOOKBACK_CHARS = 12
    CLARIFICATION_TARGET_MARKERS = ["补问题", "追问", "澄清", "确认", "问"]

    @staticmethod
    def is_force_generate_intent(text: str | None) -> bool:
        normalized = re.sub(r"\s+", "", text or "")
        for pattern in OutlineClarificationAgent.FORCE_GENERATE_PATTERNS:
            start = 0
            while True:
                index = normalized.find(pattern, start)
                if index == -1:
                    break
                if not OutlineClarificationAgent._is_negated_match(normalized, index):
                    return True
                start = index + len(pattern)
        return False

    @staticmethod
    def _is_negated_match(text: str, match_index: int) -> bool:
        prefix = text[max(0, match_index - OutlineClarificationAgent.NEGATION_LOOKBACK_CHARS):match_index]
        marker_positions = [
            (prefix.rfind(marker), marker)
            for marker in OutlineClarificationAgent.NEGATION_MARKERS
            if marker in prefix
        ]
        if not marker_positions:
            return False
        marker_index, marker = max(marker_positions, key=lambda item: item[0])
        after_marker = prefix[marker_index + len(marker):]
        if any(target in after_marker for target in OutlineClarificationAgent.CLARIFICATION_TARGET_MARKERS):
            return False
        return True

    @staticmethod
    def force_generate_decision(reason: str) -> OutlineClarificationDecision:
        return OutlineClarificationDecision(
            status="force_generate",
            confidence=1.0,
            assumptions=[f"{reason}，以下内容基于当前设定、当前对话和系统可见资料生成。"],
            reason=reason,
        )

    async def clarify(self, request: OutlineClarificationRequest) -> OutlineClarificationDecision:
        config_agent, config_task = self._config_source(request.outline_type)
        if self.is_force_generate_intent(request.feedback):
            decision = self.force_generate_decision("用户要求跳过进一步澄清")
            self._log_decision(request, decision, config_agent, config_task)
            return decision

        prompt = self._build_prompt(request)
        metadata = self._context_metadata(request, config_agent, config_task)
        decision = await call_and_parse_model(
            "OutlineClarificationAgent",
            "outline_clarify",
            prompt,
            OutlineClarificationDecision,
            novel_id=request.novel_id,
            max_retries=2,
            context_metadata=metadata,
            config_agent_name=config_agent,
            config_task=config_task,
        )
        if request.round_number >= request.max_rounds and decision.status == "clarifying":
            decision = self.force_generate_decision(
                f"达到澄清上限（第 {request.round_number}/{request.max_rounds} 轮），停止追问"
            )
        self._log_decision(request, decision, config_agent, config_task)
        return decision

    @staticmethod
    def _config_source(outline_type: str) -> tuple[str, str]:
        if outline_type == "volume":
            return "VolumePlannerAgent", "generate_volume_plan"
        return "BrainstormAgent", "generate_synopsis"

    @staticmethod
    def _context_metadata(
        request: OutlineClarificationRequest,
        config_agent: str,
        config_task: str,
    ) -> dict[str, Any]:
        return {
            "outline_type": request.outline_type,
            "outline_ref": request.outline_ref,
            "clarification_round": request.round_number,
            "max_rounds": request.max_rounds,
            "config_source_agent": config_agent,
            "config_source_task": config_task,
        }

    def _build_prompt(self, request: OutlineClarificationRequest) -> str:
        context_window = request.context_window
        workspace_snapshot = self._bounded_json(request.workspace_snapshot, SNAPSHOT_PROMPT_LIMIT)
        checkpoint_snapshot = self._bounded_json(request.checkpoint_snapshot, SNAPSHOT_PROMPT_LIMIT)
        source_text = self._bounded_text(request.source_text, SOURCE_TEXT_PROMPT_LIMIT)
        feedback = self._bounded_text(request.feedback, FEEDBACK_PROMPT_LIMIT)
        conversation_summary = self._bounded_text(
            context_window.conversation_summary,
            CONVERSATION_SUMMARY_PROMPT_LIMIT,
        )
        recent_messages = self._format_recent_messages(context_window)
        return (
            "你是小说大纲澄清决策 Agent。你的任务不是生成大纲，而是判断在生成缺失的总纲/卷纲之前，"
            "是否还需要向用户提出关键澄清问题。\n\n"
            "## 当前目标\n"
            f"- outline_type: {request.outline_type}\n"
            f"- outline_ref: {request.outline_ref}\n"
            f"- clarification_round: 第 {request.round_number}/{request.max_rounds} 轮\n\n"
            "## 用户本轮反馈\n"
            f"{feedback or '[EMPTY]'}\n\n"
            "## 对话摘要\n"
            f"{conversation_summary or '[EMPTY]'}\n\n"
            "## 最近消息\n"
            f"{recent_messages or '[EMPTY]'}\n\n"
            "## 工作区快照 JSON\n"
            f"{workspace_snapshot}\n\n"
            "## 检查点快照 JSON\n"
            f"{checkpoint_snapshot}\n\n"
            "## 可见源文本\n"
            f"{source_text or '[EMPTY]'}\n\n"
            "## 输出规则\n"
            "只返回严格 JSON，字段必须符合 OutlineClarificationDecision。\n"
            "- status=clarifying: 仅当缺口会显著改变故事方向时使用，questions 必须 1-3 个，问题要具体可回答。\n"
            "- status=ready_to_generate: 当前信息足够生成，questions 必须为空，clarification_summary 总结可用方向。\n"
            "- status=force_generate: 用户要求跳过澄清或已达上限，questions 必须为空，assumptions 写明生成假设。\n"
            "- missing_points 只列真正阻塞质量的缺口，不要泛泛而谈。\n"
            "- confidence 为 0 到 1 的数字。\n"
        )

    @staticmethod
    def _bounded_json(value: Any, limit: int) -> str:
        return OutlineClarificationAgent._bounded_text(
            json.dumps(value, ensure_ascii=False, default=str),
            limit,
        )

    @staticmethod
    def _bounded_text(value: str | None, limit: int) -> str:
        text = value or ""
        if len(text) <= limit:
            return text
        return f"{text[:limit]}\n[TRUNCATED {len(text) - limit} CHARS]"

    @staticmethod
    def _format_recent_messages(context_window: OutlineContextWindow) -> str:
        role_labels = {
            "user": "用户",
            "assistant": "系统",
            "system": "系统",
        }
        lines = []
        for message in context_window.recent_messages[-8:]:
            role = role_labels.get(message.role, "系统")
            message_type = f"[{message.message_type}]" if message.message_type else ""
            content = OutlineClarificationAgent._bounded_text(message.content, RECENT_MESSAGE_PROMPT_LIMIT)
            lines.append(f"{role}{message_type}: {content}")
        return "\n".join(lines)

    def _log_decision(
        self,
        request: OutlineClarificationRequest,
        decision: OutlineClarificationDecision,
        config_agent: str,
        config_task: str,
    ) -> None:
        metadata = {
            **self._context_metadata(request, config_agent, config_task),
            "clarification_status": decision.status,
            "confidence": decision.confidence,
            "missing_points": decision.missing_points,
            "assumptions": decision.assumptions,
        }
        log_service.add_log(
            request.novel_id,
            "OutlineClarificationAgent",
            f"大纲澄清决策: {decision.status}（第 {request.round_number}/{request.max_rounds} 轮）",
            event="agent.step",
            status=decision.status,
            node="outline_clarification",
            task="outline_clarify",
            metadata=metadata,
        )
