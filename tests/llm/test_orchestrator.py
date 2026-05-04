import asyncio

import pytest
from pydantic import BaseModel, ValidationError

from novel_dev.llm.models import LLMResponse, LLMToolCall, TaskConfig
from novel_dev.llm.orchestrator import LLMToolSpec, OrchestratedLLM, OrchestratedTaskConfig
from novel_dev.llm.subtasks import LightweightSubtaskOrchestrator, RepairerSubtask, RetrieverSubtask, ValidatorSubtask
from novel_dev.services.log_service import LogService


class Payload(BaseModel):
    value: str


class FakeClient:
    def __init__(self):
        self.calls = []

    async def acomplete(self, messages, config):
        self.calls.append((messages, config))
        if len(self.calls) == 1:
            return LLMResponse(
                text="",
                tool_calls=[LLMToolCall(id="c1", name="read_state", arguments={"novel_id": "n1"})],
            )
        return LLMResponse(text="", structured_payload={"value": "ok"})


@pytest.fixture(autouse=True)
def clear_logs():
    LogService._buffers.clear()
    LogService._listeners.clear()
    LogService._pending_tasks.clear()


@pytest.mark.asyncio
async def test_orchestrator_executes_whitelisted_readonly_tool_and_returns_structured_payload():
    async def read_state(args):
        return {"state": "draft", "requested": args["novel_id"]}

    client = FakeClient()
    base_config = TaskConfig(provider="test", model="test")
    orchestrator = OrchestratedLLM(
        client=client,
        base_config=base_config,
        response_schema=Payload,
        response_tool_name="emit_payload",
        tools=[
            LLMToolSpec(
                name="read_state",
                description="Read state",
                input_schema={"type": "object", "properties": {"novel_id": {"type": "string"}}},
                handler=read_state,
                read_only=True,
                max_return_chars=1000,
            )
        ],
        task_config=OrchestratedTaskConfig(
            tool_allowlist=["read_state"],
            max_tool_calls=2,
            max_tool_result_chars=1000,
        ),
    )

    result = await orchestrator.run("prompt", agent_name="TestAgent", task="demo", novel_id="novel-log")

    assert result == Payload(value="ok")
    assert client.calls[0][1].capability_tools[0].name == "read_state"
    assert client.calls[0][1].structured_output.tool_choice == "auto"
    assert "Tool read_state result" in client.calls[1][0][1].content
    assert "emit_payload" in client.calls[1][0][1].content
    assert "必须" in client.calls[1][0][1].content
    entries = list(LogService._buffers["novel-log"])
    assert any(entry.get("node") == "llm_tool_call" for entry in entries)


@pytest.mark.asyncio
async def test_orchestrator_skips_tool_calls_over_limit_after_executing_allowed_subset():
    async def read_state(args):
        return {"state": args["novel_id"]}

    class TooManyToolClient:
        def __init__(self):
            self.calls = []

        async def acomplete(self, messages, config):
            self.calls.append((messages, config))
            if len(self.calls) == 1:
                return LLMResponse(
                    text="",
                    tool_calls=[
                        LLMToolCall(id="c1", name="read_state", arguments={"novel_id": "n1"}),
                        LLMToolCall(id="c2", name="read_state", arguments={"novel_id": "n2"}),
                        LLMToolCall(id="c3", name="read_state", arguments={"novel_id": "n3"}),
                    ],
                )
            return LLMResponse(text="", structured_payload={"value": "ok"})

    client = TooManyToolClient()
    orchestrator = OrchestratedLLM(
        client=client,
        base_config=TaskConfig(provider="test", model="test"),
        response_schema=Payload,
        response_tool_name="emit_payload",
        tools=[
            LLMToolSpec(
                name="read_state",
                description="Read state",
                input_schema={"type": "object"},
                handler=read_state,
                read_only=True,
            )
        ],
        task_config=OrchestratedTaskConfig(tool_allowlist=["read_state"], max_tool_calls=2),
    )

    result = await orchestrator.run("prompt", agent_name="TestAgent", task="demo", novel_id="novel-tool-limit")

    assert result == Payload(value="ok")
    followup_text = "\n".join(message.content for message in client.calls[1][0])
    assert "n1" in followup_text
    assert "n2" in followup_text
    assert "n3" not in followup_text
    assert any(
        entry.get("node") == "llm_tool_call" and entry.get("status") == "skipped"
        for entry in LogService._buffers["novel-tool-limit"]
    )


@pytest.mark.asyncio
async def test_orchestrator_rejects_disallowed_or_writing_tools():
    async def write_state(args):
        return {"ok": True}

    client = FakeClient()
    orchestrator = OrchestratedLLM(
        client=client,
        base_config=TaskConfig(provider="test", model="test"),
        response_schema=Payload,
        response_tool_name="emit_payload",
        tools=[
            LLMToolSpec(
                name="write_state",
                description="Write state",
                input_schema={"type": "object"},
                handler=write_state,
                read_only=False,
            )
        ],
        task_config=OrchestratedTaskConfig(tool_allowlist=["write_state"], max_tool_calls=2),
    )

    with pytest.raises(PermissionError):
        await orchestrator.run("prompt", agent_name="TestAgent", task="demo")


@pytest.mark.asyncio
async def test_orchestrator_caps_tool_calls_and_truncates_results():
    async def read_state(args):
        return {"text": "x" * 50}

    class LoopingClient:
        def __init__(self):
            self.calls = 0

        async def acomplete(self, messages, config):
            self.calls += 1
            return LLMResponse(
                text="",
                tool_calls=[LLMToolCall(id=f"c{self.calls}", name="read_state", arguments={})],
            )

    client = LoopingClient()
    orchestrator = OrchestratedLLM(
        client=client,
        base_config=TaskConfig(provider="test", model="test"),
        response_schema=Payload,
        response_tool_name="emit_payload",
        tools=[
            LLMToolSpec(
                name="read_state",
                description="Read state",
                input_schema={"type": "object"},
                handler=read_state,
                read_only=True,
                max_return_chars=10,
            )
        ],
        task_config=OrchestratedTaskConfig(tool_allowlist=["read_state"], max_tool_calls=1),
    )

    with pytest.raises(RuntimeError, match="max tool calls"):
        await orchestrator.run("prompt", agent_name="TestAgent", task="demo")


@pytest.mark.asyncio
async def test_orchestrator_enforces_tool_timeout():
    async def slow_tool(args):
        await asyncio.sleep(0.05)
        return {"ok": True}

    client = FakeClient()
    orchestrator = OrchestratedLLM(
        client=client,
        base_config=TaskConfig(provider="test", model="test"),
        response_schema=Payload,
        response_tool_name="emit_payload",
        tools=[
            LLMToolSpec(
                name="read_state",
                description="Read state",
                input_schema={"type": "object"},
                handler=slow_tool,
                read_only=True,
                timeout_seconds=0.001,
            )
        ],
        task_config=OrchestratedTaskConfig(tool_allowlist=["read_state"], max_tool_calls=1),
    )

    with pytest.raises(TimeoutError):
        await orchestrator.run("prompt", agent_name="TestAgent", task="demo")


@pytest.mark.asyncio
async def test_orchestrator_runs_validator_and_repairer_subtasks_for_structured_payload():
    class PayloadClient:
        async def acomplete(self, messages, config):
            return LLMResponse(text="", structured_payload={"value": "bad"})

    def validate(payload):
        raw_payload = payload["payload"]
        return {
            "valid": raw_payload.get("value") == "ok",
            "reason": "value must be ok",
        }

    def repair(payload):
        assert payload["validation"]["reason"] == "value must be ok"
        fixed = dict(payload["payload"])
        fixed["value"] = "ok"
        return fixed

    orchestrator = OrchestratedLLM(
        client=PayloadClient(),
        base_config=TaskConfig(provider="test", model="test"),
        response_schema=Payload,
        response_tool_name="emit_payload",
        tools=[],
        task_config=OrchestratedTaskConfig(
            tool_allowlist=[],
            enable_subtasks=True,
            validator_subtask="semantic",
            repairer_subtask="semantic_repair",
        ),
        subtask_orchestrator=LightweightSubtaskOrchestrator(
            validators=[ValidatorSubtask(name="semantic", handler=validate)],
            repairers=[RepairerSubtask(name="semantic_repair", handler=repair)],
        ),
    )

    result = await orchestrator.run("prompt", agent_name="TestAgent", task="demo", novel_id="novel-subtasks")

    assert result == Payload(value="ok")
    entries = list(LogService._buffers["novel-subtasks"])
    assert any(entry.get("node") == "llm_validator" and entry.get("status") == "failed" for entry in entries)
    assert any(entry.get("node") == "llm_repairer" and entry.get("status") == "succeeded" for entry in entries)


@pytest.mark.asyncio
async def test_orchestrator_repairs_schema_validation_failure_with_repairer_subtask():
    class InvalidPayloadClient:
        async def acomplete(self, messages, config):
            return LLMResponse(text="", structured_payload={"wrong": "shape"})

    def repair(payload):
        assert payload["validation"]["reason"] == "schema_validation_failed"
        assert payload["validation"]["errors"]
        assert payload["payload"] == {"wrong": "shape"}
        return {"value": "ok"}

    orchestrator = OrchestratedLLM(
        client=InvalidPayloadClient(),
        base_config=TaskConfig(provider="test", model="test"),
        response_schema=Payload,
        response_tool_name="emit_payload",
        tools=[],
        task_config=OrchestratedTaskConfig(
            tool_allowlist=[],
            enable_subtasks=True,
            repairer_subtask="schema_repair",
        ),
        subtask_orchestrator=LightweightSubtaskOrchestrator(
            repairers=[RepairerSubtask(name="schema_repair", handler=repair)],
        ),
    )

    result = await orchestrator.run("prompt", agent_name="TestAgent", task="demo", novel_id="novel-schema")

    assert result == Payload(value="ok")
    entries = list(LogService._buffers["novel-schema"])
    assert any(
        entry.get("node") == "llm_validator"
        and entry.get("status") == "failed"
        and entry.get("metadata", {}).get("validation", {}).get("reason") == "schema_validation_failed"
        for entry in entries
    )
    assert any(entry.get("node") == "llm_repairer" and entry.get("status") == "succeeded" for entry in entries)


@pytest.mark.asyncio
async def test_orchestrator_runs_retriever_subtasks_before_generation():
    class ContextAwareClient:
        def __init__(self):
            self.messages = None

        async def acomplete(self, messages, config):
            self.messages = messages
            return LLMResponse(text="", structured_payload={"value": "ok"})

    def retrieve(payload):
        assert payload["prompt"] == "prompt"
        assert payload["agent_name"] == "TestAgent"
        assert payload["task"] == "demo"
        return {"scene": "retrieved context"}

    client = ContextAwareClient()
    orchestrator = OrchestratedLLM(
        client=client,
        base_config=TaskConfig(provider="test", model="test"),
        response_schema=Payload,
        response_tool_name="emit_payload",
        tools=[],
        task_config=OrchestratedTaskConfig(
            tool_allowlist=[],
            enable_subtasks=True,
            retriever_subtasks=["scene_context"],
        ),
        subtask_orchestrator=LightweightSubtaskOrchestrator(
            retrievers=[RetrieverSubtask(name="scene_context", handler=retrieve)],
        ),
    )

    result = await orchestrator.run("prompt", agent_name="TestAgent", task="demo", novel_id="novel-retriever")

    assert result == Payload(value="ok")
    assert client.messages is not None
    assert len(client.messages) == 2
    assert "Retriever scene_context result" in client.messages[1].content
    assert "retrieved context" in client.messages[1].content
    entries = list(LogService._buffers["novel-retriever"])
    assert any(entry.get("node") == "llm_retriever" and entry.get("status") == "succeeded" for entry in entries)


@pytest.mark.asyncio
async def test_orchestrator_logs_failed_repairer_when_repaired_payload_is_invalid():
    class InvalidPayloadClient:
        async def acomplete(self, messages, config):
            return LLMResponse(text="", structured_payload={"wrong": "shape"})

    def repair(payload):
        return {"still": "wrong"}

    orchestrator = OrchestratedLLM(
        client=InvalidPayloadClient(),
        base_config=TaskConfig(provider="test", model="test"),
        response_schema=Payload,
        response_tool_name="emit_payload",
        tools=[],
        task_config=OrchestratedTaskConfig(
            tool_allowlist=[],
            enable_subtasks=True,
            repairer_subtask="schema_repair",
        ),
        subtask_orchestrator=LightweightSubtaskOrchestrator(
            repairers=[RepairerSubtask(name="schema_repair", handler=repair)],
        ),
    )

    with pytest.raises(ValidationError):
        await orchestrator.run("prompt", agent_name="TestAgent", task="demo", novel_id="novel-bad-repair")

    entries = list(LogService._buffers["novel-bad-repair"])
    assert any(
        entry.get("node") == "llm_repairer"
        and entry.get("status") == "failed"
        and entry.get("metadata", {}).get("validation", {}).get("reason") == "schema_repair_failed"
        for entry in entries
    )
    assert not any(entry.get("node") == "llm_repairer" and entry.get("status") == "succeeded" for entry in entries)


@pytest.mark.asyncio
async def test_orchestrator_logs_failed_semantic_repairer_when_repaired_payload_is_invalid():
    class PayloadClient:
        async def acomplete(self, messages, config):
            return LLMResponse(text="", structured_payload={"value": "bad"})

    def validate(payload):
        return {"valid": False, "reason": "value must be ok"}

    def repair(payload):
        return {"wrong": "shape"}

    orchestrator = OrchestratedLLM(
        client=PayloadClient(),
        base_config=TaskConfig(provider="test", model="test"),
        response_schema=Payload,
        response_tool_name="emit_payload",
        tools=[],
        task_config=OrchestratedTaskConfig(
            tool_allowlist=[],
            enable_subtasks=True,
            validator_subtask="semantic",
            repairer_subtask="semantic_repair",
        ),
        subtask_orchestrator=LightweightSubtaskOrchestrator(
            validators=[ValidatorSubtask(name="semantic", handler=validate)],
            repairers=[RepairerSubtask(name="semantic_repair", handler=repair)],
        ),
    )

    with pytest.raises(ValidationError):
        await orchestrator.run("prompt", agent_name="TestAgent", task="demo", novel_id="novel-bad-semantic-repair")

    entries = list(LogService._buffers["novel-bad-semantic-repair"])
    assert any(
        entry.get("node") == "llm_repairer"
        and entry.get("status") == "failed"
        and entry.get("metadata", {}).get("validation", {}).get("reason") == "schema_repair_failed"
        for entry in entries
    )
    assert not any(entry.get("node") == "llm_repairer" and entry.get("status") == "succeeded" for entry in entries)


@pytest.mark.asyncio
async def test_orchestrator_parses_json_text_after_tool_result_without_retrying():
    async def read_state(args):
        return {"state": "draft"}

    class TextAfterToolClient:
        def __init__(self):
            self.calls = []

        async def acomplete(self, messages, config):
            self.calls.append((messages, config))
            if len(self.calls) == 1:
                return LLMResponse(
                    text="",
                    tool_calls=[LLMToolCall(id="c1", name="read_state", arguments={})],
                    finish_reason="tool_use",
                )
            return LLMResponse(
                text='```json\n{"value": "ok"}\n```',
                finish_reason="end_turn",
            )

    client = TextAfterToolClient()
    orchestrator = OrchestratedLLM(
        client=client,
        base_config=TaskConfig(provider="test", model="test"),
        response_schema=Payload,
        response_tool_name="emit_payload",
        tools=[
            LLMToolSpec(
                name="read_state",
                description="Read state",
                input_schema={"type": "object"},
                handler=read_state,
                read_only=True,
            )
        ],
        task_config=OrchestratedTaskConfig(tool_allowlist=["read_state"], max_tool_calls=1),
    )

    result = await orchestrator.run("prompt", agent_name="TestAgent", task="demo", novel_id="novel-text-fallback")

    assert result == Payload(value="ok")
    assert len(client.calls) == 2
    entries = list(LogService._buffers["novel-text-fallback"])
    assert any(
        entry.get("node") == "llm_orchestrator"
        and entry.get("status") == "succeeded"
        and entry.get("metadata", {}).get("output_source") == "text"
        for entry in entries
    )


@pytest.mark.asyncio
async def test_orchestrator_prioritizes_tool_calls_over_text_fallback():
    async def read_state(args):
        return {"state": "draft"}

    class ToolCallWithTextClient:
        def __init__(self):
            self.calls = []

        async def acomplete(self, messages, config):
            self.calls.append((messages, config))
            if len(self.calls) == 1:
                return LLMResponse(
                    text="I need to call the context tool first.",
                    tool_calls=[LLMToolCall(id="c1", name="read_state", arguments={})],
                    finish_reason="tool_use",
                )
            assert "Tool read_state result" in messages[1].content
            return LLMResponse(text="", structured_payload={"value": "ok"})

    client = ToolCallWithTextClient()
    orchestrator = OrchestratedLLM(
        client=client,
        base_config=TaskConfig(provider="test", model="test"),
        response_schema=Payload,
        response_tool_name="emit_payload",
        tools=[
            LLMToolSpec(
                name="read_state",
                description="Read state",
                input_schema={"type": "object"},
                handler=read_state,
                read_only=True,
            )
        ],
        task_config=OrchestratedTaskConfig(tool_allowlist=["read_state"], max_tool_calls=1),
    )

    result = await orchestrator.run("prompt", agent_name="TestAgent", task="demo", novel_id="novel-tool-priority")

    assert result == Payload(value="ok")
    assert len(client.calls) == 2
    assert any(entry.get("node") == "llm_tool_call" for entry in LogService._buffers["novel-tool-priority"])
