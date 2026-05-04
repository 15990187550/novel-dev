from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pydantic import TypeAdapter, ValidationError

from novel_dev.llm.drivers.base import BaseDriver
from novel_dev.llm.models import (
    CapabilityToolConfig,
    ChatMessage,
    LLMToolCall,
    StructuredOutputConfig,
    TaskConfig,
)
from novel_dev.llm.subtasks import LightweightSubtaskOrchestrator
from novel_dev.services.log_service import log_service

ToolHandler = Callable[[dict[str, Any]], Awaitable[Any] | Any]


@dataclass(frozen=True)
class LLMToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler
    read_only: bool = True
    timeout_seconds: float = 5.0
    max_return_chars: int = 4000

    def to_config(self) -> CapabilityToolConfig:
        return CapabilityToolConfig(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
        )


@dataclass(frozen=True)
class OrchestratedTaskConfig:
    tool_allowlist: list[str]
    max_tool_calls: int = 3
    tool_timeout_seconds: float | None = None
    max_tool_result_chars: int = 4000
    allow_writes: bool = False
    enable_mcp_tools: bool = False
    enable_subtasks: bool = False
    retriever_subtasks: list[str] | None = None
    validator_subtask: str | None = None
    repairer_subtask: str | None = None


class OrchestratedLLM:
    def __init__(
        self,
        *,
        client: BaseDriver,
        base_config: TaskConfig,
        response_schema: Any,
        response_tool_name: str,
        tools: list[LLMToolSpec],
        task_config: OrchestratedTaskConfig,
        subtask_orchestrator: LightweightSubtaskOrchestrator | None = None,
    ):
        self.client = client
        self.base_config = base_config
        self.response_schema = response_schema
        self.response_tool_name = response_tool_name
        self.tools = {tool.name: tool for tool in tools}
        self.task_config = task_config
        self.subtask_orchestrator = subtask_orchestrator

    async def run(
        self,
        prompt: str,
        *,
        agent_name: str,
        task: str,
        novel_id: str = "",
        context_metadata: dict[str, Any] | None = None,
    ) -> Any:
        allowed_tools = self._allowed_tools()
        adapter = TypeAdapter(self.response_schema)
        messages = [ChatMessage(role="user", content=prompt)]
        retriever_context, retriever_metadata = await self._build_retriever_context(
            prompt=prompt,
            agent_name=agent_name,
            task=task,
            novel_id=novel_id,
            context_metadata=context_metadata,
        )
        if retriever_context:
            messages.append(ChatMessage(role="user", content=retriever_context))
        config = self._build_request_config(allowed_tools)
        tool_call_count = 0
        started_at = time.perf_counter()
        while True:
            response = await self.client.acomplete(messages, config=config)
            if response.structured_payload is not None:
                result = await self._validate_and_repair_payload(
                    response.structured_payload,
                    adapter=adapter,
                    prompt=prompt,
                    agent_name=agent_name,
                    task=task,
                    novel_id=novel_id,
                )
                self._log(
                    novel_id,
                    agent_name,
                    task,
                    f"{task} 编排调用完成",
                    status="succeeded",
                    node="llm_orchestrator",
                    metadata={
                        **(context_metadata or {}),
                        "prompt_chars": len(prompt),
                        "tool_calls": tool_call_count,
                        "retriever_subtasks": retriever_metadata,
                    },
                    duration_ms=int((time.perf_counter() - started_at) * 1000),
                )
                return result
            if response.tool_calls:
                executed_this_turn = 0
                for call in response.tool_calls:
                    if tool_call_count >= self.task_config.max_tool_calls:
                        self._log(
                            novel_id,
                            agent_name,
                            task,
                            f"{task} 跳过超额工具调用 {call.name}",
                            status="skipped",
                            node="llm_tool_call",
                            level="warning",
                            metadata={
                                "tool_name": call.name,
                                "max_tool_calls": self.task_config.max_tool_calls,
                            },
                        )
                        continue
                    result_text = await self._execute_tool(call, novel_id, agent_name, task)
                    tool_call_count += 1
                    executed_this_turn += 1
                    messages.append(ChatMessage(
                        role="user",
                        content=(
                            f"Tool {call.name} result:\n{result_text}\n\n"
                            f"你现在必须调用 response tool `{self.response_tool_name}` 输出最终结构化结果。"
                            "不要再用普通文本回答，不要继续解释工具结果。"
                        ),
                    ))
                if executed_this_turn == 0:
                    raise RuntimeError(f"{task} exceeded max tool calls: {self.task_config.max_tool_calls}")
                continue
            if response.text and response.text.strip():
                result = await self._parse_and_validate_text_payload(
                    response.text,
                    adapter=adapter,
                    prompt=prompt,
                    agent_name=agent_name,
                    task=task,
                    novel_id=novel_id,
                )
                self._log(
                    novel_id,
                    agent_name,
                    task,
                    f"{task} 编排调用完成",
                    status="succeeded",
                    node="llm_orchestrator",
                    metadata={
                        **(context_metadata or {}),
                        "prompt_chars": len(prompt),
                        "tool_calls": tool_call_count,
                        "retriever_subtasks": retriever_metadata,
                        "output_source": "text",
                        "finish_reason": response.finish_reason,
                    },
                    duration_ms=int((time.perf_counter() - started_at) * 1000),
                )
                return result
            raise RuntimeError(f"{task} did not return structured payload or tool calls")

    def _allowed_tools(self) -> list[LLMToolSpec]:
        allowed = []
        for name in self.task_config.tool_allowlist:
            tool = self.tools.get(name)
            if tool is None:
                continue
            if not tool.read_only and not self.task_config.allow_writes:
                raise PermissionError(f"Tool {name} is not read-only and cannot be exposed automatically")
            allowed.append(tool)
        return allowed

    def _build_request_config(self, allowed_tools: list[LLMToolSpec]) -> TaskConfig:
        config = self.base_config.model_copy(deep=True)
        config.response_tool_name = self.response_tool_name
        config.response_json_schema = self._schema_for_response()
        config.capability_tools = [tool.to_config() for tool in allowed_tools]
        if allowed_tools:
            structured_output = config.structured_output or StructuredOutputConfig()
            config.structured_output = structured_output.model_copy(update={"tool_choice": "auto"})
        return config

    def _schema_for_response(self) -> dict[str, Any]:
        if hasattr(self.response_schema, "model_json_schema"):
            return self.response_schema.model_json_schema()
        return TypeAdapter(self.response_schema).json_schema()

    async def _parse_and_validate_text_payload(
        self,
        text: str,
        *,
        adapter: TypeAdapter,
        prompt: str,
        agent_name: str,
        task: str,
        novel_id: str,
    ) -> Any:
        payload = json.loads(self._strip_markdown_json(text))
        return await self._validate_and_repair_payload(
            payload,
            adapter=adapter,
            prompt=prompt,
            agent_name=agent_name,
            task=task,
            novel_id=novel_id,
        )

    def _strip_markdown_json(self, text: str) -> str:
        text = re.sub(r"```(?:json)?\s*", "", text or "")
        text = re.sub(r"\s*```", "", text)
        text = text.strip()
        start_obj = text.find("{")
        start_arr = text.find("[")
        starts = [pos for pos in (start_obj, start_arr) if pos != -1]
        if not starts:
            return text
        start = min(starts)
        brace_count = 0
        in_string = False
        escape_next = False
        for idx, ch in enumerate(text[start:], start):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\":
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch in "[{":
                brace_count += 1
            elif ch in "]}":
                brace_count -= 1
                if brace_count == 0:
                    return text[start:idx + 1]
        return text[start:]

    async def _build_retriever_context(
        self,
        *,
        prompt: str,
        agent_name: str,
        task: str,
        novel_id: str,
        context_metadata: dict[str, Any] | None,
    ) -> tuple[str, list[dict[str, Any]]]:
        if not self.task_config.enable_subtasks or self.subtask_orchestrator is None:
            return "", []
        retriever_names = self.task_config.retriever_subtasks or []
        if not retriever_names:
            return "", []

        parts: list[str] = []
        metadata: list[dict[str, Any]] = []
        for name in retriever_names:
            started_at = time.perf_counter()
            result = await self.subtask_orchestrator.run_retriever(
                name,
                {
                    "prompt": prompt,
                    "agent_name": agent_name,
                    "task": task,
                    "novel_id": novel_id,
                    "context_metadata": context_metadata or {},
                },
            )
            result_text, truncated = self._serialize_subtask_result(result.payload)
            item_metadata = {
                "subtask": result.name,
                "duration_ms": result.duration_ms,
                "result_chars": len(result_text),
                "truncated": truncated,
            }
            metadata.append(item_metadata)
            self._log(
                novel_id,
                agent_name,
                task,
                f"{task} 检索子任务 {result.name} 完成",
                status="succeeded",
                node="llm_retriever",
                metadata=item_metadata,
                duration_ms=int((time.perf_counter() - started_at) * 1000),
            )
            parts.append(f"Retriever {result.name} result:\n{result_text}")
        return "\n\n".join(parts), metadata

    async def _validate_and_repair_payload(
        self,
        payload: Any,
        *,
        adapter: TypeAdapter,
        prompt: str,
        agent_name: str,
        task: str,
        novel_id: str,
    ) -> Any:
        if not self.task_config.enable_subtasks:
            return adapter.validate_python(payload)
        if self.subtask_orchestrator is None:
            return adapter.validate_python(payload)

        payload, schema_validated_payload = await self._validate_schema_or_repair(
            payload,
            adapter=adapter,
            prompt=prompt,
            agent_name=agent_name,
            task=task,
            novel_id=novel_id,
        )
        if not self.task_config.validator_subtask:
            return schema_validated_payload

        validation = await self.subtask_orchestrator.run_validator(
            self.task_config.validator_subtask,
            {
                "payload": payload,
                "prompt": prompt,
                "agent_name": agent_name,
                "task": task,
            },
        )
        validation_payload = validation.payload if isinstance(validation.payload, dict) else {"valid": bool(validation.payload)}
        is_valid = bool(validation_payload.get("valid"))
        self._log(
            novel_id,
            agent_name,
            task,
            f"{task} 子任务校验{'通过' if is_valid else '失败'}",
            status="succeeded" if is_valid else "failed",
            node="llm_validator",
            level="info" if is_valid else "warning",
            metadata={
                "subtask": validation.name,
                "validation": validation_payload,
                "duration_ms": validation.duration_ms,
            },
            duration_ms=validation.duration_ms,
        )
        if is_valid:
            return schema_validated_payload
        if not self.task_config.repairer_subtask:
            raise RuntimeError(f"{task} failed validator subtask: {validation_payload}")

        repair = await self.subtask_orchestrator.run_repairer(
            self.task_config.repairer_subtask,
            {
                "payload": payload,
                "validation": validation_payload,
                "prompt": prompt,
                "agent_name": agent_name,
                "task": task,
            },
        )
        repaired = self._validate_repair_payload(
            repair.payload,
            adapter=adapter,
            subtask_name=repair.name,
            duration_ms=repair.duration_ms,
            novel_id=novel_id,
            agent_name=agent_name,
            task=task,
            success_message=f"{task} 子任务修复完成",
            failure_message=f"{task} 子任务修复失败",
        )
        repaired_validation = await self._run_validator_subtask(
            repair.payload,
            prompt=prompt,
            agent_name=agent_name,
            task=task,
            novel_id=novel_id,
        )
        repaired_validation_payload = (
            repaired_validation.payload
            if isinstance(repaired_validation.payload, dict)
            else {"valid": bool(repaired_validation.payload)}
        )
        if not bool(repaired_validation_payload.get("valid")):
            raise RuntimeError(f"{task} failed validator subtask after repair: {repaired_validation_payload}")
        return repaired

    async def _run_validator_subtask(
        self,
        payload: Any,
        *,
        prompt: str,
        agent_name: str,
        task: str,
        novel_id: str,
    ):
        validation = await self.subtask_orchestrator.run_validator(
            self.task_config.validator_subtask,
            {
                "payload": payload,
                "prompt": prompt,
                "agent_name": agent_name,
                "task": task,
            },
        )
        validation_payload = validation.payload if isinstance(validation.payload, dict) else {"valid": bool(validation.payload)}
        is_valid = bool(validation_payload.get("valid"))
        self._log(
            novel_id,
            agent_name,
            task,
            f"{task} 子任务校验{'通过' if is_valid else '失败'}",
            status="succeeded" if is_valid else "failed",
            node="llm_validator",
            level="info" if is_valid else "warning",
            metadata={
                "subtask": validation.name,
                "validation": validation_payload,
                "duration_ms": validation.duration_ms,
            },
            duration_ms=validation.duration_ms,
        )
        return validation

    async def _validate_schema_or_repair(
        self,
        payload: Any,
        *,
        adapter: TypeAdapter,
        prompt: str,
        agent_name: str,
        task: str,
        novel_id: str,
    ) -> tuple[Any, Any]:
        try:
            return payload, adapter.validate_python(payload)
        except ValidationError as exc:
            if not self.task_config.repairer_subtask:
                raise

            validation_payload = {
                "valid": False,
                "reason": "schema_validation_failed",
                "errors": self._validation_errors(exc),
            }
            self._log(
                novel_id,
                agent_name,
                task,
                f"{task} schema 校验失败",
                status="failed",
                node="llm_validator",
                level="warning",
                metadata={"validation": validation_payload},
            )
            repair = await self.subtask_orchestrator.run_repairer(
                self.task_config.repairer_subtask,
                {
                    "payload": payload,
                    "validation": validation_payload,
                    "validation_error": exc,
                    "prompt": prompt,
                    "agent_name": agent_name,
                    "task": task,
                },
            )
            repaired = self._validate_repair_payload(
                repair.payload,
                adapter=adapter,
                subtask_name=repair.name,
                duration_ms=repair.duration_ms,
                novel_id=novel_id,
                agent_name=agent_name,
                task=task,
                success_message=f"{task} schema 子任务修复完成",
                failure_message=f"{task} schema 子任务修复失败",
            )
            return repair.payload, repaired

    def _validate_repair_payload(
        self,
        payload: Any,
        *,
        adapter: TypeAdapter,
        subtask_name: str,
        duration_ms: int,
        novel_id: str,
        agent_name: str,
        task: str,
        success_message: str,
        failure_message: str,
    ) -> Any:
        try:
            repaired = adapter.validate_python(payload)
        except ValidationError as exc:
            validation = {
                "valid": False,
                "reason": "schema_repair_failed",
                "errors": self._validation_errors(exc),
            }
            self._log(
                novel_id,
                agent_name,
                task,
                failure_message,
                status="failed",
                node="llm_repairer",
                level="warning",
                metadata={
                    "subtask": subtask_name,
                    "duration_ms": duration_ms,
                    "validation": validation,
                },
                duration_ms=duration_ms,
            )
            raise
        self._log(
            novel_id,
            agent_name,
            task,
            success_message,
            status="succeeded",
            node="llm_repairer",
            metadata={
                "subtask": subtask_name,
                "duration_ms": duration_ms,
            },
            duration_ms=duration_ms,
        )
        return repaired

    def _validation_errors(self, exc: ValidationError) -> list[dict[str, Any]]:
        errors = exc.errors(include_url=False)
        return json.loads(json.dumps(errors, ensure_ascii=False, default=str))

    async def _execute_tool(
        self,
        call: LLMToolCall,
        novel_id: str,
        agent_name: str,
        task: str,
    ) -> str:
        tool = self.tools.get(call.name)
        if tool is None or call.name not in self.task_config.tool_allowlist:
            raise PermissionError(f"Tool {call.name} is not allowed for {agent_name}/{task}")
        if not tool.read_only and not self.task_config.allow_writes:
            raise PermissionError(f"Tool {call.name} is not read-only and cannot be exposed automatically")

        timeout = self.task_config.tool_timeout_seconds or tool.timeout_seconds
        started_at = time.perf_counter()
        try:
            result = tool.handler(call.arguments)
            if asyncio.iscoroutine(result):
                result = await asyncio.wait_for(result, timeout=timeout)
        except asyncio.TimeoutError as exc:
            self._log(
                novel_id,
                agent_name,
                task,
                f"{task} 工具 {call.name} 超时",
                status="failed",
                node="llm_tool_call",
                level="warning",
                metadata={"tool_name": call.name, "timeout_seconds": timeout},
                duration_ms=int((time.perf_counter() - started_at) * 1000),
            )
            raise TimeoutError(f"Tool {call.name} timed out after {timeout}s") from exc

        result_text, truncated = self._serialize_tool_result(result, tool)
        self._log(
            novel_id,
            agent_name,
            task,
            f"{task} 工具 {call.name} 调用完成",
            status="succeeded",
            node="llm_tool_call",
            metadata={
                "tool_name": call.name,
                "tool_call_id": call.id,
                "result_chars": len(result_text),
                "truncated": truncated,
            },
            duration_ms=int((time.perf_counter() - started_at) * 1000),
        )
        return result_text

    def _serialize_tool_result(self, result: Any, tool: LLMToolSpec) -> tuple[str, bool]:
        text = json.dumps(result, ensure_ascii=False, default=str)
        limit = min(tool.max_return_chars, self.task_config.max_tool_result_chars)
        if len(text) <= limit:
            return text, False
        return text[:limit] + "\n...[truncated]", True

    def _serialize_subtask_result(self, result: Any) -> tuple[str, bool]:
        text = json.dumps(result, ensure_ascii=False, default=str)
        limit = self.task_config.max_tool_result_chars
        if len(text) <= limit:
            return text, False
        return text[:limit] + "\n...[truncated]", True

    def _log(
        self,
        novel_id: str,
        agent_name: str,
        task: str,
        message: str,
        *,
        status: str,
        node: str,
        level: str = "info",
        metadata: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> None:
        if not novel_id:
            return
        log_service.add_log(
            novel_id,
            agent_name,
            message,
            level=level,
            event="llm.orchestrator",
            status=status,
            node=node,
            task=task,
            metadata=metadata,
            duration_ms=duration_ms,
        )
