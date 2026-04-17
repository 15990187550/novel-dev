# 核心创作 Agent LLM 化 — 设计文档

**日期：** 2026-04-17  
**主题：** 将 VolumePlannerAgent、WriterAgent、CriticAgent、EditorAgent、FastReviewAgent 的占位符逻辑替换为真正的 LLM 调用  
**状态：** 待实现  
**依赖：** 现有 `llm_factory`、`BrainstormAgent` LLM 调用模式、Pydantic schemas

---

## 1. 目标

当前 5 个核心创作 Agent 的生成/评分逻辑仍是硬编码占位符（固定评分、拼接字符串、追加后缀）。本设计将它们全部接入 `llm_factory`，使系统能产出真正基于 LLM 的分卷规划、章节草稿、评审反馈和润色结果。

---

## 2. 用户旅程（无变化）

用户仍通过前端或 MCP 触发各阶段：`VOLUME_PLANNING` → `CONTEXT_PREPARATION` → `DRAFTING` → `REVIEWING` → `EDITING` → `FAST_REVIEWING` → `LIBRARIAN`。本设计只改变 Agent 内部实现，不改动 API 签名、状态机或前端界面。

---

## 3. 架构设计

### 3.1 统一调用模式

所有 Agent 遵循 `BrainstormAgent` 已验证的模式：

```python
from novel_dev.llm import llm_factory
from novel_dev.llm.models import ChatMessage

client = llm_factory.get("AgentName", task="task_name")
messages = [
    ChatMessage(role="system", content=system_prompt),
    ChatMessage(role="user", content=user_prompt),
]
response = await client.acomplete(messages)
data = SomeSchema.model_validate_json(response.text)
```

### 3.2 各 Agent 改动

#### VolumePlannerAgent (`src/novel_dev/agents/volume_planner.py`)

- `_generate_score`
  - 输入：`VolumePlan.model_dump_json()` + `SynopsisData.model_dump_json()`
  - LLM task: `"score_volume_plan"`
  - 输出：`VolumeScoreResult`
- `_revise_volume_plan`
  - 输入：当前 `VolumePlan.model_dump_json()` + `score.summary_feedback`
  - LLM task: `"revise_volume_plan"`
  - 输出：修正后的 `VolumePlan` JSON

#### WriterAgent (`src/novel_dev/agents/writer_agent.py`)

- `_generate_beat`
  - 输入：`BeatPlan.model_dump_json()` + `ChapterContext.model_dump_json()` + `previous_text`
  - LLM task: `"generate_beat"`
  - 输出：该节拍的正文字符串（要求约 target_word_count/3 字数）
- `_rewrite_angle`
  - 输入：同上，但额外说明「当前节拍过短，请扩写并保持连贯」
  - LLM task: `"rewrite_beat"`
  - 输出：扩写后的正文字符串

#### CriticAgent (`src/novel_dev/agents/critic_agent.py`)

- `_generate_score`
  - 输入：`raw_draft` + `chapter_context`
  - LLM task: `"score_chapter"`
  - 输出：`ScoreResult`（5 维度 + overall + summary_feedback）
- `_generate_beat_scores`
  - 输入：各节拍文本列表 + `chapter_context`
  - LLM task: `"score_beats"`
  - 输出：`List[dict]`，每个 dict 含 `beat_index` 和 `scores`

#### EditorAgent (`src/novel_dev/agents/editor_agent.py`)

- `_rewrite_beat`
  - 输入：当前节拍文本 + 低分维度说明（如 `{"humanity": 65}`）
  - LLM task: `"polish_beat"`
  - 输出：重写后的正文字符串，不包含解释

#### FastReviewAgent (`src/novel_dev/agents/fast_review_agent.py`)

- 把 `consistency_fixed` 和 `beat_cohesion_ok` 改为 LLM 检查
  - 输入：`polished_text` + `chapter_context` + `raw_draft`
  - LLM task: `"fast_review_check"`
  - 输出：JSON `{"consistency_fixed": bool, "beat_cohesion_ok": bool, "notes": [str]}`
  - `word_count_ok` 和 `ai_flavor_reduced` 保留现有启发式计算

### 3.3 Prompt 设计原则

- System prompt 必须声明「你是一个 XX 专家」，并给出输出 JSON Schema 示例
- User prompt 用结构化文本（如 `### 章节计划` `### 已写文本`）分隔不同上下文
- 所有 JSON 输出要求严格符合对应 Pydantic model，方便 `model_validate_json`

### 3.4 测试策略

全部测试改为和 `test_brainstorm_agent.py` 一致的 mock 模式：

```python
from unittest.mock import AsyncMock, patch
from novel_dev.llm.models import LLMResponse

mock_client = AsyncMock()
mock_client.acomplete.return_value = LLMResponse(text=expected_json)
with patch("novel_dev.llm.llm_factory") as mock_factory:
    mock_factory.get.return_value = mock_client
    ...
```

验证：
- `llm_factory.get` 被正确调用（agent name + task 匹配）
- 返回结果结构正确
- 状态推进/数据库写入行为不变

---

## 4. 数据模型

无新增模型，全部复用现有 schema：
- `VolumePlan`, `VolumeScoreResult` (`src/novel_dev/schemas/outline.py`)
- `ScoreResult`, `DimensionScore` (`src/novel_dev/schemas/review.py`)
- `ChapterContext`, `BeatPlan` (`src/novel_dev/schemas/context.py`)

---

## 5. 错误处理

| 场景 | 行为 |
|------|------|
| LLM 返回非 JSON | `model_validate_json` 抛异常，向上传播，由调用方捕获 |
| LLM 返回字段缺失 | Pydantic ValidationError，向上传播 |
| LLM factory 未配置 | 现有 `LLMConfigError` 机制处理 |

---

## 6. 明确范围

**包含：**
- 5 个 Agent 的 LLM 化改造
- 对应单元/集成测试的 mock 化更新

**不包含：**
- 前端改动
- 新增 API endpoint
- 状态机阶段变更
- SSE/WebSocket 改造
- LibrarianAgent 改动（已 LLM 化）
