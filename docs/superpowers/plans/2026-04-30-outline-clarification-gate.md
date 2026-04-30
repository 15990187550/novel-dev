# Outline Clarification Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hardcoded total-outline and volume-outline generation confirmation prompts with an LLM-driven clarification gate that can ask dynamic questions, generate immediately when enough context exists, and force generation with assumptions after 5 rounds.

**Architecture:** Add a focused `OutlineClarificationAgent` that returns a strict Pydantic JSON decision. `OutlineWorkbenchService.submit_feedback()` will call this agent only for missing outline items during brainstorming, then either writes a dynamic `question` message or continues into the existing `_optimize_outline()` generation path. `call_and_parse_model()` will support separate config lookup identity and log identity so the clarification agent can inherit `BrainstormAgent/generate_synopsis` or `VolumePlannerAgent/generate_volume_plan` while logs still say `OutlineClarificationAgent`.

**Tech Stack:** Python 3.11, FastAPI service layer, SQLAlchemy async sessions, Pydantic models, pytest async tests, Vue 3 + Pinia + Vitest.

---

## File Structure

- Modify `src/novel_dev/agents/_llm_helpers.py`
  - Add optional `config_agent_name` and `config_task` parameters to `call_and_parse_model()`.
  - Use those parameters only for `llm_factory.get()`.
  - Keep parsing, structured schema names, normalizers, and logs under the logical `agent_name/task`.

- Create `src/novel_dev/agents/outline_clarification_agent.py`
  - Define `OutlineClarificationDecision` and `OutlineClarificationRequest`.
  - Implement prompt construction, config inheritance, decision normalization, force intent detection, max-round fallback, and concise logs.

- Modify `src/novel_dev/services/outline_workbench_service.py`
  - Replace fixed `_should_request_generation_confirmation()` / `_build_generation_confirmation_message()` use with `_run_generation_clarification_gate()`.
  - Add helpers for missing-item detection, clarification round counting, forced generation phrases, clarification prompt context, and generation context injection.
  - Preserve existing `_optimize_outline()` flow for actual generation / optimization.

- Modify `tests/test_agents/test_llm_helpers.py`
  - Add a test proving config lookup can use inherited config while logs retain the logical agent/task.

- Create `tests/test_agents/test_outline_clarification_agent.py`
  - Unit-test decision normalization, force phrase detection, inherited config metadata, and max-round forced assumptions.

- Modify `tests/test_services/test_outline_workbench_service.py`
  - Replace fixed confirmation tests with dynamic clarification tests.
  - Add ready-to-generate, forced-generate, max-5-round, and volume-context coverage.

- Modify `tests/test_api/test_outline_workbench_routes.py`
  - Update API assertion from `generation_confirmation` to `generation_clarification`.

- Modify `src/novel_dev/web/src/views/VolumePlan.vue`
  - Treat `generation_clarification` question messages as awaiting clarification.

- Modify `src/novel_dev/web/src/views/VolumePlan.test.js`
  - Update the current confirmation-label test to use `generation_clarification`.

---

### Task 1: LLM Helper Config Identity

**Files:**
- Modify: `src/novel_dev/agents/_llm_helpers.py`
- Test: `tests/test_agents/test_llm_helpers.py`

- [ ] **Step 1: Write the failing helper test**

Append this test near the other `call_and_parse_model()` tests in `tests/test_agents/test_llm_helpers.py`:

```python
@pytest.mark.asyncio
async def test_call_and_parse_model_can_inherit_config_from_another_agent():
    mock_client = AsyncMock()
    mock_client.config = TaskConfig(provider="anthropic", model="volume-model")
    mock_client.acomplete.return_value = LLMResponse(
        text="",
        structured_payload={"title": "澄清结果", "tags": ["继承配置"]},
    )

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await call_and_parse_model(
            "OutlineClarificationAgent",
            "outline_clarify",
            "prompt",
            ExamplePayload,
            max_retries=1,
            novel_id="novel-config-alias",
            context_metadata={"purpose": "clarification"},
            config_agent_name="VolumePlannerAgent",
            config_task="generate_volume_plan",
        )

    assert result.title == "澄清结果"
    mock_factory.get.assert_called_once_with("VolumePlannerAgent", task="generate_volume_plan")
    call_kwargs = mock_client.acomplete.call_args.kwargs
    assert call_kwargs["config"].response_tool_name == "emit_outline_clarify"

    entries = LogService._buffers["novel-config-alias"]
    assert any(
        entry.get("agent") == "OutlineClarificationAgent"
        and entry.get("task") == "outline_clarify"
        and entry.get("metadata", {}).get("purpose") == "clarification"
        for entry in entries
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=src pytest tests/test_agents/test_llm_helpers.py::test_call_and_parse_model_can_inherit_config_from_another_agent -q
```

Expected: FAIL with `TypeError: call_and_parse_model() got an unexpected keyword argument 'config_agent_name'`.

- [ ] **Step 3: Add config identity parameters**

Update the signature and client lookup in `src/novel_dev/agents/_llm_helpers.py`:

```python
async def call_and_parse_model(
    agent_name: str,
    task: str,
    prompt: str,
    model_cls: Any,
    max_retries: int = 3,
    novel_id: str = "",
    context_metadata: dict[str, Any] | None = None,
    config_agent_name: str | None = None,
    config_task: str | None = None,
) -> Any:
    context_metadata = context_metadata or {}
    adapter = TypeAdapter(model_cls)
    config_agent_name = config_agent_name or agent_name
    config_task = config_task or task
```

Then change:

```python
client = llm_factory.get(agent_name, task=task)
```

to:

```python
client = llm_factory.get(config_agent_name, task=config_task)
```

Do not change `_structured_config_for_client(client, task, model_cls)`. The structured tool name must remain based on the logical task, e.g. `emit_outline_clarify`.

- [ ] **Step 4: Run helper tests**

Run:

```bash
PYTHONPATH=src pytest tests/test_agents/test_llm_helpers.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/_llm_helpers.py tests/test_agents/test_llm_helpers.py
git commit -m "Add LLM config identity override"
```

---

### Task 2: Outline Clarification Agent

**Files:**
- Create: `src/novel_dev/agents/outline_clarification_agent.py`
- Test: `tests/test_agents/test_outline_clarification_agent.py`

- [ ] **Step 1: Write failing agent tests**

Create `tests/test_agents/test_outline_clarification_agent.py`:

```python
from unittest.mock import AsyncMock

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src pytest tests/test_agents/test_outline_clarification_agent.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'novel_dev.agents.outline_clarification_agent'`.

- [ ] **Step 3: Implement the agent**

Create `src/novel_dev/agents/outline_clarification_agent.py`:

```python
import json
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from novel_dev.agents._llm_helpers import call_and_parse_model
from novel_dev.schemas.outline_workbench import OutlineContextWindow
from novel_dev.services.log_service import log_service


MAX_CLARIFICATION_ROUNDS = 5


class OutlineClarificationDecision(BaseModel):
    status: Literal["clarifying", "ready_to_generate", "force_generate"]
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    missing_points: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    clarification_summary: str = ""
    assumptions: list[str] = Field(default_factory=list)
    reason: str = ""

    @field_validator("missing_points", "questions", "assumptions", mode="before")
    @classmethod
    def _coerce_str_list(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []

    @model_validator(mode="after")
    def _normalize_by_status(self):
        if self.status == "clarifying":
            self.questions = self.questions[:3]
            if not self.questions:
                self.questions = ["还需要补充哪些题材、角色关系或结尾方向？"]
        elif self.status == "ready_to_generate":
            self.questions = []
            if not self.clarification_summary.strip():
                self.clarification_summary = "现有设定和对话信息已足够开始生成。"
        elif self.status == "force_generate":
            self.questions = []
            if not self.assumptions:
                self.assumptions = ["信息仍不完整，系统将基于当前可见设定生成，并在结果中列出采用的假设。"]
        return self


class OutlineClarificationRequest(BaseModel):
    novel_id: str
    outline_type: str
    outline_ref: str
    feedback: str
    context_window: OutlineContextWindow
    round_number: int = 1
    max_rounds: int = MAX_CLARIFICATION_ROUNDS
    source_text: str = ""
    workspace_snapshot: Optional[dict[str, Any]] = None
    checkpoint_snapshot: Optional[dict[str, Any]] = None


class OutlineClarificationAgent:
    FORCE_GENERATE_PATTERNS = (
        "按当前设定生成",
        "按现有内容生成",
        "直接生成",
        "不用问了",
        "先生成",
        "确认生成",
    )

    @staticmethod
    def is_force_generate_intent(feedback: str) -> bool:
        normalized = re.sub(r"\\s+", "", feedback or "")
        return any(pattern in normalized for pattern in OutlineClarificationAgent.FORCE_GENERATE_PATTERNS)

    @staticmethod
    def force_generate_decision(reason: str) -> OutlineClarificationDecision:
        return OutlineClarificationDecision(
            status="force_generate",
            confidence=1.0,
            missing_points=[],
            questions=[],
            clarification_summary=reason,
            assumptions=[f"{reason}，以下内容基于当前设定、当前对话和系统可见资料生成。"],
            reason=reason,
        )

    async def clarify(self, request: OutlineClarificationRequest) -> OutlineClarificationDecision:
        if self.is_force_generate_intent(request.feedback):
            decision = self.force_generate_decision("用户要求跳过进一步澄清")
            self._log_decision(request, decision)
            return decision

        config_agent, config_task = self._config_source(request.outline_type)
        decision = await call_and_parse_model(
            "OutlineClarificationAgent",
            "outline_clarify",
            self._build_prompt(request),
            OutlineClarificationDecision,
            novel_id=request.novel_id,
            max_retries=2,
            context_metadata={
                "outline_type": request.outline_type,
                "outline_ref": request.outline_ref,
                "clarification_round": request.round_number,
                "max_rounds": request.max_rounds,
                "config_source_agent": config_agent,
                "config_source_task": config_task,
            },
            config_agent_name=config_agent,
            config_task=config_task,
        )
        if request.round_number >= request.max_rounds and decision.status == "clarifying":
            decision = OutlineClarificationDecision(
                status="force_generate",
                confidence=decision.confidence,
                missing_points=decision.missing_points,
                questions=[],
                clarification_summary=decision.clarification_summary,
                assumptions=[
                    "达到澄清上限，仍不完整的信息将作为假设处理，系统基于当前可见设定生成。"
                ],
                reason=decision.reason or "达到澄清上限。",
            )
        self._log_decision(request, decision, config_agent=config_agent, config_task=config_task)
        return decision

    def _config_source(self, outline_type: str) -> tuple[str, str]:
        if outline_type == "volume":
            return "VolumePlannerAgent", "generate_volume_plan"
        return "BrainstormAgent", "generate_synopsis"

    def _build_prompt(self, request: OutlineClarificationRequest) -> str:
        return (
            "你是大纲生成前的澄清判断器。根据当前大纲项上下文，判断是否可以开始生成，"
            "还是需要继续问用户。只返回符合 OutlineClarificationDecision Schema 的 JSON。\\n\\n"
            "状态规则：\\n"
            "- clarifying: 信息不足，需要继续问，questions 最多 3 个。\\n"
            "- ready_to_generate: 信息足够，可以直接生成，questions 为空。\\n"
            "- force_generate: 用户要求跳过，或达到上限，必须给出 assumptions。\\n"
            f"- 当前是第 {request.round_number}/{request.max_rounds} 轮澄清。\\n\\n"
            f"### outline_type\\n{request.outline_type}\\n\\n"
            f"### outline_ref\\n{request.outline_ref}\\n\\n"
            f"### 用户最新输入\\n{request.feedback}\\n\\n"
            f"### 历史摘要\\n{request.context_window.conversation_summary or '无'}\\n\\n"
            f"### 最近对话\\n{self._format_recent_messages(request.context_window) or '无'}\\n\\n"
            f"### 当前工作区快照\\n{json.dumps(request.workspace_snapshot, ensure_ascii=False) if request.workspace_snapshot else '无'}\\n\\n"
            f"### 当前正式快照\\n{json.dumps(request.checkpoint_snapshot, ensure_ascii=False) if request.checkpoint_snapshot else '无'}\\n\\n"
            f"### 参考设定\\n{(request.source_text or '无')[:5000]}"
        )

    def _format_recent_messages(self, context_window: OutlineContextWindow) -> str:
        lines = []
        for message in context_window.recent_messages[-8:]:
            role = "用户" if message.role == "user" else "系统"
            lines.append(f"{role}: {message.content}")
        return "\\n".join(lines)

    def _log_decision(
        self,
        request: OutlineClarificationRequest,
        decision: OutlineClarificationDecision,
        *,
        config_agent: str | None = None,
        config_task: str | None = None,
    ) -> None:
        if config_agent is None or config_task is None:
            config_agent, config_task = self._config_source(request.outline_type)
        if decision.status == "clarifying":
            message = f"澄清判断完成：需要继续补充（第 {request.round_number}/{request.max_rounds} 轮）"
        elif decision.status == "ready_to_generate":
            message = "澄清判断完成：信息足够，开始生成"
        else:
            message = "达到澄清上限或用户要求跳过，基于现有设定生成"
        log_service.add_log(
            request.novel_id,
            "OutlineClarificationAgent",
            message,
            event="agent.progress",
            status="succeeded",
            node="outline_clarification",
            task="outline_clarify",
            metadata={
                "outline_type": request.outline_type,
                "outline_ref": request.outline_ref,
                "clarification_round": request.round_number,
                "max_rounds": request.max_rounds,
                "clarification_status": decision.status,
                "confidence": decision.confidence,
                "missing_points": decision.missing_points,
                "assumptions": decision.assumptions,
                "config_source_agent": config_agent,
                "config_source_task": config_task,
            },
        )
```

- [ ] **Step 4: Run agent tests**

Run:

```bash
PYTHONPATH=src pytest tests/test_agents/test_outline_clarification_agent.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/outline_clarification_agent.py tests/test_agents/test_outline_clarification_agent.py
git commit -m "Add outline clarification agent"
```

---

### Task 3: Service Gate for Dynamic Clarification

**Files:**
- Modify: `src/novel_dev/services/outline_workbench_service.py`
- Test: `tests/test_services/test_outline_workbench_service.py`

- [ ] **Step 1: Replace the fixed-confirmation service tests with dynamic clarification tests**

Edit the two existing tests named:

- `test_submit_feedback_requests_confirmation_before_generating_missing_brainstorm_synopsis`
- `test_submit_feedback_generates_after_confirmation_for_missing_brainstorm_synopsis`

Replace them with these tests:

```python
async def test_submit_feedback_requests_dynamic_clarification_before_generating_missing_brainstorm_synopsis(async_session, monkeypatch):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_brainstorm_clarify",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={
            "synopsis_data": {
                "title": "旧总纲",
                "logline": "",
                "core_conflict": "",
                "themes": [],
                "character_arcs": [],
                "milestones": [],
                "estimated_volumes": 2,
                "estimated_total_chapters": 10,
                "estimated_total_words": 30000,
            }
        },
        volume_id=None,
        chapter_id=None,
    )

    service = OutlineWorkbenchService(async_session)

    async def fail_optimize_outline(**kwargs):
        raise AssertionError("should not optimize while clarification is needed")

    async def fake_clarify(self, request):
        assert request.outline_type == "synopsis"
        assert request.outline_ref == "synopsis"
        assert request.round_number == 1
        return OutlineClarificationDecision(
            status="clarifying",
            confidence=0.4,
            missing_points=["题材卖点不明确"],
            questions=["题材、基调和核心卖点更偏哪一类？"],
            clarification_summary="用户想生成总纲，但题材卖点不明确。",
            assumptions=[],
            reason="缺少题材方向。",
        )

    monkeypatch.setattr(service, "_optimize_outline", fail_optimize_outline)
    monkeypatch.setattr(OutlineClarificationAgent, "clarify", fake_clarify)

    response = await service.submit_feedback(
        novel_id="n_brainstorm_clarify",
        outline_type="synopsis",
        outline_ref="synopsis",
        feedback="请基于当前设定生成完整总纲草稿，补齐一句话梗概、核心冲突、卷数规模、人物弧光和关键里程碑。",
    )

    assert response.assistant_message.role == "assistant"
    assert response.assistant_message.message_type == "question"
    assert response.last_result_snapshot is None
    assert "题材、基调和核心卖点" in response.assistant_message.content
    assert response.assistant_message.meta["interaction_stage"] == "generation_clarification"
    assert response.assistant_message.meta["clarification_round"] == 1
    assert response.assistant_message.meta["max_rounds"] == 5
    assert response.assistant_message.meta["clarification_status"] == "clarifying"
    assert response.assistant_message.meta["missing_points"] == ["题材卖点不明确"]

    session = await OutlineSessionRepository(async_session).get_or_create(
        novel_id="n_brainstorm_clarify",
        outline_type="synopsis",
        outline_ref="synopsis",
    )
    assert session.status == "awaiting_confirmation"
    assert session.last_result_snapshot is None
```

```python
async def test_submit_feedback_generates_when_clarification_reports_ready(async_session, monkeypatch):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_brainstorm_ready",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={
            "synopsis_data": {
                "title": "旧总纲",
                "logline": "",
                "core_conflict": "",
                "themes": [],
                "character_arcs": [],
                "milestones": [],
                "estimated_volumes": 2,
                "estimated_total_chapters": 10,
                "estimated_total_words": 30000,
            }
        },
        volume_id=None,
        chapter_id=None,
    )

    service = OutlineWorkbenchService(async_session)

    async def fake_clarify(self, request):
        return OutlineClarificationDecision(
            status="ready_to_generate",
            confidence=0.88,
            missing_points=[],
            questions=[],
            clarification_summary="用户已确认仙侠升级流、两卷、弱感情线。",
            assumptions=[],
            reason="信息足够。",
        )

    optimize_calls = []

    async def fake_optimize_outline(*, novel_id, outline_type, outline_ref, feedback, context_window):
        optimize_calls.append({"feedback": feedback, "context_window": context_window})
        return {
            "content": "已生成总纲草稿，请继续提出修改意见。",
            "result_snapshot": {
                "title": "新总纲",
                "logline": "新的故事主线",
                "core_conflict": "新的冲突",
                "themes": [],
                "character_arcs": [],
                "milestones": [],
                "estimated_volumes": 2,
                "estimated_total_chapters": 120,
                "estimated_total_words": 360000,
            },
            "conversation_summary": "用户已确认仙侠升级流、两卷、弱感情线。",
        }

    monkeypatch.setattr(OutlineClarificationAgent, "clarify", fake_clarify)
    monkeypatch.setattr(service, "_optimize_outline", fake_optimize_outline)

    response = await service.submit_feedback(
        novel_id="n_brainstorm_ready",
        outline_type="synopsis",
        outline_ref="synopsis",
        feedback="走仙侠升级流，预计两卷，感情线弱一些，按这个方向生成。",
    )

    assert optimize_calls
    assert "澄清摘要：用户已确认仙侠升级流、两卷、弱感情线。" in optimize_calls[0]["feedback"]
    assert response.assistant_message.message_type == "result"
    assert response.last_result_snapshot["title"] == "新总纲"
```

Add these imports near the top of `tests/test_services/test_outline_workbench_service.py`:

```python
from novel_dev.agents.outline_clarification_agent import OutlineClarificationAgent, OutlineClarificationDecision
```

- [ ] **Step 2: Run the rewritten tests to verify they fail**

Run:

```bash
PYTHONPATH=src pytest tests/test_services/test_outline_workbench_service.py::test_submit_feedback_requests_dynamic_clarification_before_generating_missing_brainstorm_synopsis tests/test_services/test_outline_workbench_service.py::test_submit_feedback_generates_when_clarification_reports_ready -q
```

Expected: FAIL because the service still writes `generation_confirmation` and does not call `OutlineClarificationAgent`.

- [ ] **Step 3: Import the agent and add service helpers**

In `src/novel_dev/services/outline_workbench_service.py`, add:

```python
from novel_dev.agents.outline_clarification_agent import (
    MAX_CLARIFICATION_ROUNDS,
    OutlineClarificationAgent,
    OutlineClarificationDecision,
    OutlineClarificationRequest,
)
```

Add these methods to `OutlineWorkbenchService`, replacing the old fixed-message helpers:

```python
    async def _run_generation_clarification_gate(
        self,
        *,
        novel_id: str,
        state: Any,
        outline_session: Any,
        outline_type: str,
        outline_ref: str,
        feedback: str,
        context_window: OutlineContextWindow,
        workspace_outline_drafts: Optional[dict[str, dict[str, Any]]],
    ) -> OutlineClarificationDecision | None:
        if not self._should_run_generation_clarification(
            state=state,
            outline_session=outline_session,
            outline_type=outline_type,
            outline_ref=outline_ref,
            workspace_outline_drafts=workspace_outline_drafts,
        ):
            return None

        round_number = self._next_clarification_round(context_window)
        if OutlineClarificationAgent.is_force_generate_intent(feedback):
            return OutlineClarificationAgent.force_generate_decision("用户要求跳过进一步澄清")

        request = OutlineClarificationRequest(
            novel_id=novel_id,
            outline_type=outline_type,
            outline_ref=outline_ref,
            feedback=feedback,
            context_window=context_window,
            round_number=round_number,
            max_rounds=MAX_CLARIFICATION_ROUNDS,
            source_text=await self._load_brainstorm_source_text(novel_id),
            workspace_snapshot=self._get_workspace_snapshot(
                workspace_outline_drafts,
                outline_type,
                outline_ref,
            ),
            checkpoint_snapshot=self._get_checkpoint_snapshot(
                state.checkpoint_data or {},
                outline_type,
                outline_ref,
            ),
        )
        try:
            return await OutlineClarificationAgent().clarify(request)
        except Exception as exc:
            if round_number <= 1 and not self._has_user_clarification_answer(context_window):
                log_service.add_log(
                    novel_id,
                    "OutlineClarificationAgent",
                    f"澄清判断失败，使用本地兜底问题: {exc}",
                    level="warning",
                    event="agent.progress",
                    status="failed",
                    node="outline_clarification",
                    task="outline_clarify",
                    metadata={
                        "outline_type": outline_type,
                        "outline_ref": outline_ref,
                        "clarification_round": round_number,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
                return OutlineClarificationDecision(
                    status="clarifying",
                    confidence=0.0,
                    missing_points=["澄清模型暂不可用"],
                    questions=[self._fallback_clarification_question(outline_type, outline_ref)],
                    clarification_summary="澄清模型暂不可用，先收集用户最关键的生成偏好。",
                    assumptions=[],
                    reason=f"{type(exc).__name__}: {exc}",
                )
            return OutlineClarificationDecision(
                status="force_generate",
                confidence=0.0,
                missing_points=["澄清模型暂不可用"],
                questions=[],
                clarification_summary="澄清模型暂不可用，系统基于当前可见设定生成。",
                assumptions=["澄清模型暂不可用，系统基于当前可见设定生成。"],
                reason=f"{type(exc).__name__}: {exc}",
            )

    def _should_run_generation_clarification(
        self,
        *,
        state: Any,
        outline_session: Any,
        outline_type: str,
        outline_ref: str,
        workspace_outline_drafts: Optional[dict[str, dict[str, Any]]],
    ) -> bool:
        if not self._is_brainstorming_phase(getattr(state, "current_phase", None)):
            return False
        items = self.build_outline_items(
            state.checkpoint_data or {},
            workspace_outline_drafts=workspace_outline_drafts,
            phase=state.current_phase,
        )
        current_item = next(
            (
                item
                for item in items
                if item.outline_type == outline_type and item.outline_ref == outline_ref
            ),
            None,
        )
        if current_item is None or current_item.status != "missing":
            return False
        return True

    def _next_clarification_round(self, context_window: OutlineContextWindow) -> int:
        rounds = [
            int((message.meta or {}).get("clarification_round") or 0)
            for message in context_window.recent_messages
            if (message.meta or {}).get("interaction_stage") == "generation_clarification"
        ]
        return min((max(rounds) if rounds else 0) + 1, MAX_CLARIFICATION_ROUNDS)

    def _has_user_clarification_answer(self, context_window: OutlineContextWindow) -> bool:
        seen_question = False
        for message in context_window.recent_messages:
            if (
                message.role == "assistant"
                and message.message_type == "question"
                and (message.meta or {}).get("interaction_stage") == "generation_clarification"
            ):
                seen_question = True
                continue
            if seen_question and message.role == "user":
                return True
        return False

    def _fallback_clarification_question(self, outline_type: str, outline_ref: str) -> str:
        if outline_type == "volume":
            volume_number = self._parse_volume_number(outline_ref)
            label = f"第 {volume_number} 卷" if volume_number else "当前卷"
            return f"开始生成{label}卷纲前，请补充这一卷最关键的主线目标、卷末钩子或必须出现的角色推进。也可以回复“按当前设定生成”。"
        return "开始生成总纲前，请补充题材基调、核心卖点或必须保留/避免的关键设定。也可以回复“按当前设定生成”。"

    def _build_clarification_question_content(self, decision: OutlineClarificationDecision) -> str:
        question_text = "\n".join(
            f"{index}. {question}"
            for index, question in enumerate(decision.questions[:3], start=1)
        )
        suffix = "如果已经足够，也可以直接回复“按当前设定生成”。"
        return f"{question_text}\n{suffix}".strip()

    def _append_clarification_context(self, feedback: str, decision: OutlineClarificationDecision) -> str:
        parts = [feedback.strip()]
        if decision.clarification_summary:
            parts.append(f"澄清摘要：{decision.clarification_summary}")
        if decision.assumptions:
            parts.append("生成假设：\n" + "\n".join(f"- {item}" for item in decision.assumptions))
        return "\n\n".join(part for part in parts if part)
```

- [ ] **Step 4: Wire the gate into `submit_feedback()`**

In `submit_feedback()`, replace the existing `if self._should_request_generation_confirmation(...):` block with:

```python
        clarification_decision = await self._run_generation_clarification_gate(
            novel_id=novel_id,
            state=state,
            outline_session=outline_session,
            outline_type=outline_type,
            outline_ref=outline_ref,
            feedback=feedback,
            context_window=context_window,
            workspace_outline_drafts=workspace_outline_drafts,
        )
        if clarification_decision and clarification_decision.status == "clarifying":
            outline_session.status = "awaiting_confirmation"
            outline_session.conversation_summary = self._merge_conversation_summary(
                context_window.conversation_summary,
                feedback,
            )
            round_number = self._next_clarification_round(context_window)
            assistant_message = await self.outline_message_repo.create(
                session_id=outline_session.id,
                role="assistant",
                message_type="question",
                content=self._build_clarification_question_content(clarification_decision),
                meta={
                    "outline_type": outline_type,
                    "outline_ref": outline_ref,
                    "interaction_stage": "generation_clarification",
                    "clarification_round": round_number,
                    "max_rounds": MAX_CLARIFICATION_ROUNDS,
                    "clarification_status": clarification_decision.status,
                    "confidence": clarification_decision.confidence,
                    "missing_points": clarification_decision.missing_points,
                    "clarification_summary": clarification_decision.clarification_summary,
                    "assumptions": clarification_decision.assumptions,
                },
            )
            await self.session.commit()
            return OutlineSubmitResponse(
                session_id=outline_session.id,
                assistant_message=self._serialize_message(assistant_message),
                last_result_snapshot=outline_session.last_result_snapshot,
                conversation_summary=outline_session.conversation_summary,
                setting_update_summary=None,
            )

        if clarification_decision:
            feedback = self._append_clarification_context(feedback, clarification_decision)
```

Remove `_should_request_generation_confirmation()` and `_build_generation_confirmation_message()` after the tests pass.

- [ ] **Step 5: Run the two service tests**

Run:

```bash
PYTHONPATH=src pytest tests/test_services/test_outline_workbench_service.py::test_submit_feedback_requests_dynamic_clarification_before_generating_missing_brainstorm_synopsis tests/test_services/test_outline_workbench_service.py::test_submit_feedback_generates_when_clarification_reports_ready -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/services/outline_workbench_service.py tests/test_services/test_outline_workbench_service.py
git commit -m "Replace fixed outline confirmation with clarification gate"
```

---

### Task 4: Service Edge Cases

**Files:**
- Modify: `tests/test_services/test_outline_workbench_service.py`
- Modify: `src/novel_dev/services/outline_workbench_service.py`

- [ ] **Step 1: Add service tests for force, max rounds, and volume context**

Append these tests near the clarification service tests:

```python
async def test_submit_feedback_force_generates_without_calling_clarification_agent(async_session, monkeypatch):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_brainstorm_force",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={"synopsis_data": {"estimated_volumes": 1}},
        volume_id=None,
        chapter_id=None,
    )

    service = OutlineWorkbenchService(async_session)

    async def fail_clarify(self, request):
        raise AssertionError("force generation should not call LLM clarification")

    optimize_calls = []

    async def fake_optimize_outline(*, novel_id, outline_type, outline_ref, feedback, context_window):
        optimize_calls.append(feedback)
        return {
            "content": "已生成",
            "result_snapshot": {
                "title": "强制生成总纲",
                "logline": "主线",
                "core_conflict": "冲突",
                "themes": [],
                "character_arcs": [],
                "milestones": [],
                "estimated_volumes": 1,
                "estimated_total_chapters": 30,
                "estimated_total_words": 90000,
            },
            "conversation_summary": "用户要求直接生成。",
        }

    monkeypatch.setattr(OutlineClarificationAgent, "clarify", fail_clarify)
    monkeypatch.setattr(service, "_optimize_outline", fake_optimize_outline)

    response = await service.submit_feedback(
        novel_id="n_brainstorm_force",
        outline_type="synopsis",
        outline_ref="synopsis",
        feedback="不用问了，按当前设定生成",
    )

    assert response.assistant_message.message_type == "result"
    assert "用户要求跳过进一步澄清" in optimize_calls[0]


async def test_submit_feedback_forces_generation_after_fifth_clarification_round(async_session, monkeypatch):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_brainstorm_round_limit",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={"synopsis_data": {"estimated_volumes": 1}},
        volume_id=None,
        chapter_id=None,
    )

    service = OutlineWorkbenchService(async_session)
    session = await service.outline_session_repo.get_or_create(
        novel_id="n_brainstorm_round_limit",
        outline_type="synopsis",
        outline_ref="synopsis",
        status="awaiting_confirmation",
    )
    for index in range(1, 6):
        await service.outline_message_repo.create(
            session_id=session.id,
            role="assistant",
            message_type="question",
            content=f"第 {index} 轮问题",
            meta={
                "interaction_stage": "generation_clarification",
                "clarification_round": index,
                "max_rounds": 5,
            },
        )
        await service.outline_message_repo.create(
            session_id=session.id,
            role="user",
            message_type="feedback",
            content=f"第 {index} 轮回答",
            meta={"outline_type": "synopsis", "outline_ref": "synopsis"},
        )

    async def fake_clarify(self, request):
        assert request.round_number == 5
        return OutlineClarificationDecision(
            status="force_generate",
            confidence=0.2,
            missing_points=["终局方向不完整"],
            questions=[],
            clarification_summary="已经多轮澄清，仍缺终局。",
            assumptions=["达到澄清上限，按开放式终局生成。"],
            reason="达到上限。",
        )

    optimize_calls = []

    async def fake_optimize_outline(*, novel_id, outline_type, outline_ref, feedback, context_window):
        optimize_calls.append(feedback)
        return {
            "content": "已按假设生成",
            "result_snapshot": {
                "title": "上限生成总纲",
                "logline": "主线",
                "core_conflict": "冲突",
                "themes": [],
                "character_arcs": [],
                "milestones": [],
                "estimated_volumes": 1,
                "estimated_total_chapters": 30,
                "estimated_total_words": 90000,
            },
            "conversation_summary": "达到上限后生成。",
        }

    monkeypatch.setattr(OutlineClarificationAgent, "clarify", fake_clarify)
    monkeypatch.setattr(service, "_optimize_outline", fake_optimize_outline)

    response = await service.submit_feedback(
        novel_id="n_brainstorm_round_limit",
        outline_type="synopsis",
        outline_ref="synopsis",
        feedback="还是不确定，但继续",
    )

    assert response.assistant_message.message_type == "result"
    assert "达到澄清上限，按开放式终局生成。" in optimize_calls[0]


async def test_submit_feedback_clarifies_missing_volume_with_volume_context(async_session, monkeypatch):
    synopsis = SynopsisData(
        title="九霄行",
        logline="主角逆势而上",
        core_conflict="家仇与天命相撞",
        estimated_volumes=2,
        estimated_total_chapters=20,
        estimated_total_words=60000,
    )
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_brainstorm_volume_clarify",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={"synopsis_data": synopsis.model_dump()},
        volume_id=None,
        chapter_id=None,
    )

    service = OutlineWorkbenchService(async_session)

    async def fail_optimize_outline(**kwargs):
        raise AssertionError("volume should wait for clarification")

    async def fake_clarify(self, request):
        assert request.outline_type == "volume"
        assert request.outline_ref == "vol_1"
        assert request.checkpoint_snapshot is None
        assert "九霄行" in request.source_text or request.source_text == ""
        return OutlineClarificationDecision(
            status="clarifying",
            confidence=0.5,
            missing_points=["卷末钩子不明确"],
            questions=["第一卷末尾要留下什么钩子？"],
            clarification_summary="缺少卷末钩子。",
            assumptions=[],
            reason="影响章节收束。",
        )

    monkeypatch.setattr(service, "_optimize_outline", fail_optimize_outline)
    monkeypatch.setattr(OutlineClarificationAgent, "clarify", fake_clarify)

    response = await service.submit_feedback(
        novel_id="n_brainstorm_volume_clarify",
        outline_type="volume",
        outline_ref="vol_1",
        feedback="生成第一卷卷纲",
    )

    assert response.assistant_message.message_type == "question"
    assert "第一卷末尾" in response.assistant_message.content
    assert response.assistant_message.meta["outline_type"] == "volume"
    assert response.assistant_message.meta["outline_ref"] == "vol_1"
```

- [ ] **Step 2: Run edge-case tests**

Run:

```bash
PYTHONPATH=src pytest tests/test_services/test_outline_workbench_service.py::test_submit_feedback_force_generates_without_calling_clarification_agent tests/test_services/test_outline_workbench_service.py::test_submit_feedback_forces_generation_after_fifth_clarification_round tests/test_services/test_outline_workbench_service.py::test_submit_feedback_clarifies_missing_volume_with_volume_context -q
```

Expected: PASS after Task 3. If `request.source_text` does not include synopsis text, keep the assertion permissive exactly as written.

- [ ] **Step 3: Run all outline workbench service tests**

Run:

```bash
PYTHONPATH=src pytest tests/test_services/test_outline_workbench_service.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/novel_dev/services/outline_workbench_service.py tests/test_services/test_outline_workbench_service.py
git commit -m "Cover outline clarification edge cases"
```

---

### Task 5: API and Frontend Compatibility

**Files:**
- Modify: `tests/test_api/test_outline_workbench_routes.py`
- Modify: `src/novel_dev/web/src/views/VolumePlan.vue`
- Modify: `src/novel_dev/web/src/views/VolumePlan.test.js`

- [ ] **Step 1: Update API test assertion**

In `tests/test_api/test_outline_workbench_routes.py`, replace:

```python
assert data["assistant_message"]["meta"]["interaction_stage"] == "generation_confirmation"
```

with:

```python
assert data["assistant_message"]["meta"]["interaction_stage"] == "generation_clarification"
assert data["assistant_message"]["meta"]["clarification_round"] == 1
assert data["assistant_message"]["meta"]["max_rounds"] == 5
```

Because the API test runs the real service, monkeypatch `OutlineClarificationAgent.clarify` inside that test before the client call:

```python
async def fake_clarify(self, request):
    return OutlineClarificationDecision(
        status="clarifying",
        confidence=0.5,
        missing_points=["题材卖点不明确"],
        questions=["题材、基调和核心卖点是什么？"],
        clarification_summary="需要补充题材卖点。",
        assumptions=[],
        reason="信息不足。",
    )

monkeypatch.setattr(OutlineClarificationAgent, "clarify", fake_clarify)
```

Add the imports:

```python
from novel_dev.agents.outline_clarification_agent import OutlineClarificationAgent, OutlineClarificationDecision
```

If the test function currently lacks `monkeypatch`, add it to the signature.

- [ ] **Step 2: Update frontend computed property**

In `src/novel_dev/web/src/views/VolumePlan.vue`, replace the interaction-stage check:

```js
lastMessage?.meta?.interaction_stage === 'generation_confirmation'
```

with:

```js
['generation_confirmation', 'generation_clarification'].includes(lastMessage?.meta?.interaction_stage)
```

Keeping `generation_confirmation` is intentional backward compatibility for already-open sessions or persisted old messages.

- [ ] **Step 3: Update frontend test fixture**

In `src/novel_dev/web/src/views/VolumePlan.test.js`, replace the fixture meta:

```js
meta: {
  interaction_stage: 'generation_confirmation',
},
```

with:

```js
meta: {
  interaction_stage: 'generation_clarification',
  clarification_round: 1,
  max_rounds: 5,
},
```

Also update the test name from:

```js
it('switches the missing-outline action label to confirmation after assistant follow-up questions', async () => {
```

to:

```js
it('switches the missing-outline action label to confirmation during generation clarification', async () => {
```

- [ ] **Step 4: Run API and frontend tests**

Run:

```bash
PYTHONPATH=src pytest tests/test_api/test_outline_workbench_routes.py::test_submit_outline_workbench_feedback_returns_confirmation_question_for_missing_brainstorm_synopsis -q
```

Then run from `src/novel_dev/web`:

```bash
npm test -- --run src/views/VolumePlan.test.js
```

Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_api/test_outline_workbench_routes.py src/novel_dev/web/src/views/VolumePlan.vue src/novel_dev/web/src/views/VolumePlan.test.js
git commit -m "Update outline clarification UI contract"
```

---

### Task 6: Full Verification and Local Restart

**Files:**
- No planned source edits unless verification reveals a regression.

- [ ] **Step 1: Run focused backend suite**

Run:

```bash
PYTHONPATH=src pytest tests/test_agents/test_llm_helpers.py tests/test_agents/test_outline_clarification_agent.py tests/test_services/test_outline_workbench_service.py tests/test_api/test_outline_workbench_routes.py -q
```

Expected: PASS.

- [ ] **Step 2: Run focused frontend suite**

Run:

```bash
npm test -- --run src/views/VolumePlan.test.js
```

Working directory: `src/novel_dev/web`.

Expected: PASS.

- [ ] **Step 3: Restart service with the project script**

Run:

```bash
./scripts/run_local.sh
```

Expected: service starts cleanly. If the script leaves a long-running process attached, wait until health checks are reachable before final reporting.

- [ ] **Step 4: Verify health endpoints**

Run:

```bash
curl -sf http://127.0.0.1:8000/healthz
curl -sf http://127.0.0.1:9997/v1/models
```

Expected: both commands return successful responses.

- [ ] **Step 5: Final commit if verification required fixes**

If verification required any source/test corrections, commit only those files:

```bash
git add <changed-files>
git commit -m "Stabilize outline clarification gate"
```

If no corrections were needed, do not create an empty commit.

---

## Self-Review Checklist

- Spec coverage:
  - Dynamic LLM questions: Task 2 and Task 3.
  - Smart skip when information is enough: Task 3 ready-to-generate test.
  - Multi-round up to 5: Task 2 and Task 4.
  - Force generation with assumptions: Task 2 and Task 4.
  - Total outline and volume outline support: Task 3 and Task 4.
  - Existing context reuse: Task 3 request construction uses `OutlineContextWindow`, workspace snapshot, and checkpoint snapshot.
  - Model config inheritance: Task 1 and Task 2.
  - Frontend compatibility: Task 5.
  - Logs and metadata: Task 2 log assertions and context metadata.

- Placeholder scan:
  - No `TBD`, `TODO`, or vague “add tests” steps are present.
  - Each task includes exact files, test commands, and expected outcomes.

- Type consistency:
  - `generation_clarification`, `clarification_round`, `max_rounds`, `clarification_summary`, and `assumptions` are used consistently across tests, service meta, and frontend fixture.
  - `OutlineClarificationDecision.status` values match the spec exactly: `clarifying`, `ready_to_generate`, `force_generate`.
