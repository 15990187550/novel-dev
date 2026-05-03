# 大纲生成澄清门控 — 设计文档

**日期：** 2026-04-30  
**主题：** 将总纲、卷纲生成前的固定确认话术改为 LLM 驱动的多轮澄清流程  
**状态：** 待实现  
**依赖：** 现有 `OutlineWorkbenchService`、`outline_sessions` / `outline_messages`、`BrainstormAgent`、`VolumePlannerAgent`

---

## 1. 背景

当前大纲规划工作台在脑爆阶段遇到缺失的总纲或卷纲时，会返回一段写死的确认话术：

- 总纲固定询问题材、卷数规模、人物关系和终局方向
- 卷纲固定询问本卷目标、角色推进、节奏偏向

这个行为有两个问题：

- 无论已有上下文是否足够，每次都像第一次确认，容易打断用户。
- 问题内容不读取现有设定、历史对话和当前大纲项状态，无法像 `superpowers:brainstorming` 一样逐步判断信息是否已经足够。

本设计将这段固定确认逻辑替换为产品内的 LLM 澄清门控：系统先判断信息是否足够，足够则直接复用现有对话式生成 / 优化链路，不足则提出动态问题；最多 5 轮后仍不足时，必须基于现有设定生成，并明确列出假设。

---

## 2. 目标

- 总纲和卷纲生成前都支持同一套澄清门控逻辑。
- 澄清问题由 LLM 根据当前大纲项上下文动态生成，而不是写死。
- 如果现有上下文已经足够，系统应直接开始生成，不再额外确认。
- 澄清允许多轮，最多 5 轮。
- 第 5 轮后仍不完整时，系统不再继续追问，改为“基于现有设定生成，并列出假设”。
- 用户可以通过“按当前设定生成”“不用问了”“直接生成”等明确表达跳过澄清。
- 总纲和卷纲继续使用原先各自独立的上下文与对话式生成 / 优化链路。
- `OutlineClarificationAgent` 的模型配置默认继承当前要生成的大纲 agent 配置。

---

## 3. 非目标

- 不重做大纲规划工作台 UI。
- 不新增一套独立聊天系统。
- 不改变总纲、卷纲现有结构化结果 schema。
- 不把 `superpowers:brainstorming` skill 文件作为运行时依赖。
- 不在澄清阶段正式写入总纲、卷纲或设定实体。

---

## 4. 核心设计

### 4.1 澄清门控位置

澄清门控放在 `OutlineWorkbenchService.submit_feedback()` 的生成入口内，替换现有 `_should_request_generation_confirmation()` 和 `_build_generation_confirmation_message()` 的固定话术逻辑。

当用户在一个缺失的大纲项上提交生成意图时：

1. 后端保存用户消息。
2. 构建当前大纲项的 `OutlineContextWindow`。
3. 调用 `OutlineClarificationAgent` 判断是否需要继续澄清。
4. 如果 `ready_to_generate`，直接进入现有 `_optimize_outline()`。
5. 如果 `clarifying`，写入一条 assistant `question` 消息，等待用户回答。
6. 如果 `force_generate`，进入现有 `_optimize_outline()`，并把假设注入生成上下文。

已有大纲项的普通修改意见不进入澄清门控，继续按现有优化流程执行。

### 4.2 上下文复用

总纲和卷纲原本已经是不同上下文，本设计不新增平行上下文系统，而是复用现有边界：

- 总纲：`outline_type=synopsis`，`outline_ref=synopsis`
- 第 N 卷：`outline_type=volume`，`outline_ref=vol_N`

澄清判断读取同一个大纲项的：

- `OutlineContextWindow.conversation_summary`
- `OutlineContextWindow.recent_messages`
- `OutlineSession.last_result_snapshot`
- 工作区中的当前草稿快照
- 正式 checkpoint 中已存在的总纲 / 卷纲数据
- 与当前阶段相关的设定文档摘要

澄清产生的 assistant 问题也写回同一个 `outline_messages` 流，因此后续生成可以自然读取历史。

### 4.3 LLM 输出协议

`OutlineClarificationAgent` 必须返回严格 JSON：

```json
{
  "status": "clarifying",
  "confidence": 0.62,
  "missing_points": ["本卷结尾钩子不明确"],
  "questions": ["这一卷结尾要把危机推到什么程度？"],
  "clarification_summary": "用户希望生成第一卷卷纲，已有主角目标和修炼体系，但卷末转折尚不明确。",
  "assumptions": [],
  "reason": "缺少卷末钩子会影响章节排布。"
}
```

字段约束：

- `status`: `clarifying`、`ready_to_generate`、`force_generate`
- `confidence`: 0 到 1 的数字，用于日志和测试断言，不直接作为唯一决策
- `missing_points`: 信息缺口摘要
- `questions`: 需要继续问用户的问题，最多 3 个
- `clarification_summary`: 面向生成模型的压缩摘要
- `assumptions`: 生成时必须显式采用的假设
- `reason`: 简短内部原因，用于日志详情

当状态为 `clarifying` 时，`questions` 必须非空。  
当状态为 `force_generate` 时，`assumptions` 必须非空。  
当状态为 `ready_to_generate` 时，允许 `questions` 为空，但必须提供 `clarification_summary`。

### 4.4 轮次与状态

澄清轮次保存在 `outline_messages.meta` 中，不新增数据库表。

每条澄清问题消息写入：

```json
{
  "interaction_stage": "generation_clarification",
  "clarification_round": 2,
  "max_rounds": 5,
  "clarification_status": "clarifying",
  "missing_points": [],
  "clarification_summary": "",
  "assumptions": []
}
```

后端根据当前大纲项最近的澄清消息计算下一轮轮次：

- 第一次澄清为 `clarification_round=1`
- 用户回答后再次判断，若仍不足则进入下一轮
- 达到第 5 轮后，下一次处理不得继续返回追问
- 第 5 轮仍不足时，强制转为 `force_generate`

为了避免异常循环，`OutlineSession.status` 可以继续使用 `awaiting_confirmation` 表示等待用户补充，但新的消息 meta 必须使用 `generation_clarification`，不要再依赖固定 confirmation 文案。

### 4.5 用户强制生成

在澄清阶段，如果用户消息包含明确跳过意图，后端不再调用澄清判断，直接进入生成。

第一版支持这些意图：

- `按当前设定生成`
- `直接生成`
- `不用问了`
- `先生成`
- `按现有内容生成`

强制生成时，需要注入一条默认假设：

> 用户要求跳过进一步澄清，以下内容基于当前设定、当前对话和系统可见资料生成。

### 4.6 生成上下文注入

生成仍走现有 `_optimize_outline()`，但在调用总纲或卷纲 agent 前，需要把澄清产物压缩为独立上下文段：

- 用户最新生成意图
- `clarification_summary`
- `assumptions`
- 当前 `OutlineContextWindow`
- 当前草稿或正式快照

不要把全部多轮问答原样塞进主生成 prompt。原始问答已经在 `recent_messages` 中可见，生成 prompt 只需要额外强调澄清摘要和假设。

---

## 5. 模型配置

新增运行身份 `OutlineClarificationAgent`，但模型配置默认继承目标生成 agent：

- 总纲澄清继承 `BrainstormAgent / generate_synopsis`
- 卷纲澄清继承 `VolumePlannerAgent / generate_volume_plan`

日志中的 agent 名称仍记录为 `OutlineClarificationAgent`，并在 metadata 中记录：

```json
{
  "config_source_agent": "VolumePlannerAgent",
  "config_source_task": "generate_volume_plan",
  "outline_type": "volume",
  "outline_ref": "vol_1"
}
```

实现上可以在 LLM helper 层支持“配置身份”和“日志身份”分离；如果当前 helper 不适合拆分，也可以提供明确的配置别名映射，但不能让澄清 agent 静默使用 unrelated 默认模型。

---

## 6. 错误处理

澄清 LLM 失败时分两层处理：

1. 首次失败且当前没有有效补充信息：返回一条本地兜底澄清问题，避免直接生成低质量结果。
2. 连续失败、用户已经补充过，或轮次已经接近上限：进入 `force_generate`，并加入假设：
   - `澄清模型暂不可用，系统基于当前可见设定生成。`

如果澄清 LLM 返回非法 JSON，沿用现有 LLM JSON 修复 / 重试机制。多次修复失败后走上述失败兜底。

生成阶段失败仍沿用现有大纲生成 / 优化错误处理，不由澄清门控吞掉。

---

## 7. 前端行为

前端主流程基本不变：

- 用户仍在当前大纲项输入框里提交生成或修改意见。
- 后端返回 `question` 消息时，前端继续按现有消息列表展示。
- 问题不再固定，由后端返回的动态文本决定。

可选增强：

- 对 `generation_clarification` 消息展示 `2/5` 轮次提示。
- 在问题下方显示“也可以回复按当前设定生成”。

这些增强不是第一版必要条件。第一版只要前端能展示后端返回的问题，并允许用户继续回复即可。

---

## 8. 日志与可观测性

每次澄清判断写入日志，便于区分总纲和卷纲：

- agent: `OutlineClarificationAgent`
- task: `outline_clarify`
- outline_type
- outline_ref
- clarification_round
- status
- confidence
- missing_points
- assumptions
- config_source_agent
- config_source_task

日志正文保持简短，例如：

- `澄清判断完成：需要继续补充（第 2/5 轮）`
- `澄清判断完成：信息足够，开始生成`
- `达到澄清上限，基于现有设定生成`

---

## 9. 测试计划

后端服务测试：

- 缺失总纲时，澄清 agent 返回 `clarifying`，应写入动态 question 消息。
- 缺失卷纲时，澄清 agent 返回 `clarifying`，应写入动态 question 消息，且上下文为当前卷。
- 澄清 agent 返回 `ready_to_generate` 时，不写固定三问，直接进入现有生成 / 优化流程。
- 用户回复“按当前设定生成”时，不再调用澄清 agent，直接生成并带默认假设。
- 连续澄清最多 5 轮，第 5 轮后仍不足时强制生成。
- 总纲澄清使用 `BrainstormAgent / generate_synopsis` 配置来源。
- 卷纲澄清使用 `VolumePlannerAgent / generate_volume_plan` 配置来源。
- 澄清 LLM 超时或 JSON 失败时，按失败兜底策略处理。

前端测试：

- `question` 消息仍能在大纲规划工作台展示。
- 固定三问文案不再作为断言目标。
- 可选轮次提示展示正确。

回归测试：

- 已有总纲的普通优化不进入澄清门控。
- 已有卷纲的普通优化不进入澄清门控。
- 总纲和不同卷的消息历史仍保持隔离。

---

## 10. 实施边界

第一版实现以可测试、行为正确为准：

- 可以先把 `OutlineClarificationAgent` 实现在 service 层或 agents 层的轻量封装中。
- 不要求前端新增复杂组件。
- 不要求新增数据库迁移。
- 不要求展示完整 missing points UI。

实现完成后，用户看到的核心变化是：

- 不再每次都收到固定三问。
- 系统能根据当前设定决定是否继续问。
- 问题会跟总纲或当前卷的真实上下文相关。
- 最多 5 轮后一定会开始生成，并明确说明采用了哪些假设。
