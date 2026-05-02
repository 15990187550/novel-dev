# 设定建议卡处理入口设计

## 背景

生成总纲和卷大纲时，系统已经会在 brainstorm workspace 中持续维护 `setting_suggestion_cards`。当前页面能展示这些建议卡，但缺少处理入口，导致用户无法在最终确认前对卡片做采纳、忽略、补充反馈或转入正式设定审批。

本设计补齐建议卡的处理闭环，同时保留现有工作流原则：总纲、卷大纲和设定建议仍先停留在 brainstorm workspace，只有用户最终确认或明确转审批时，才进入正式持久化/审批链路。

## 目标

- 在现有“设定建议卡”区域提供清晰处理入口。
- 支持单卡处理：回填到输入区、标记已解决、忽略、转为待审批设定。
- 根据建议卡内容智能判断主处理方式，避免把大纲优化类建议误导成设定入库。
- 复用现有 `pending_extractions` 审批流，不直接把建议卡写入正式设定。
- 保持卡片列表可扫读，避免把所有动作直接堆在卡片上。
- 让已处理卡片不再阻塞最终确认，同时保留历史可追溯。

## 非目标

- 不新增独立“建议处理中心”页面。
- 不做批量处理。
- 不直接创建正式设定文档或正式实体。
- 不改变总纲/卷大纲生成和反馈优化主链路。

## 推荐方案

采用“卡片轻动作 + 详情抽屉”。

卡片列表只放两个轻入口：

- `处理`：打开详情抽屉。
- 智能主按钮：根据卡片内容显示 `转设定`、`继续优化`、`补充信息` 或 `查看处理`。

详情抽屉承载复杂操作：

- `转为待审批设定`
- `回填到输入区`
- `标记已解决`
- `忽略`
- `重新激活`
- 查看完整 payload、来源、状态、推荐动作原因和调试字段

这样列表仍然适合大量卡片快速浏览，处理动作也有足够上下文，避免误操作。

## 智能动作判定

建议卡内容种类很多，不是所有卡都能转为设定。系统需要为每张卡计算一个动作提示：

```json
{
  "recommended_action": "continue_outline_feedback",
  "available_actions": ["open_detail", "fill_conversation", "resolve", "dismiss"],
  "reason": "这张卡是大纲结构或主题表达建议，不是可落库的实体设定。"
}
```

动作提示由后端服务层计算，随 workspace payload 返回给前端。前端只负责展示，不重复维护另一套业务规则。

判定规则：

- 可转设定类：`card_type` 是 `character/faction/location/item/artifact/skill/artifact_or_skill`，并且 payload 中能解析出 `canonical_name/name/title`。推荐动作是 `submit_to_pending`，主按钮文案是 `转设定`。
- 关系类：`card_type` 是 `relationship`。推荐动作是 `continue_outline_feedback` 或 `open_detail`，详情中说明“关系建议将在最终确认时解析处理”，不开放单卡转 pending。
- 大纲优化类：`card_type` 是 `revision/addition/outline/structure/theme/pacing/hook/arc`，或 payload/summary 明显指向总纲、卷纲、篇幅、钩子、动机、结构、主题闭环。推荐动作是 `continue_outline_feedback`，主按钮文案是 `继续优化`。
- 信息不足类：无法判断类型、payload 为空或缺少关键字段。推荐动作是 `request_more_info`，主按钮文案是 `补充信息`。

不可用动作必须在详情抽屉中置灰并显示原因，不能只隐藏。

## 状态模型

建议卡状态扩展为：

- `active`：待处理，可回填、转审批、解决或忽略。
- `unresolved`：信息不足，最终确认前提醒用户处理。
- `resolved`：用户确认已解决，不再显示在待处理列表。
- `dismissed`：用户忽略，不参与最终确认。
- `submitted`：已转成待审批设定，避免重复提交。
- `superseded`：被新建议覆盖，进入历史区。

默认待处理列表只展示 `active` 和 `unresolved`。`resolved`、`dismissed`、`submitted`、`superseded` 放入折叠的“历史建议”区，其中 `resolved/dismissed` 支持重新激活。`submitted` 已经产生待审批设定，不通过建议卡重新激活，避免重复提交。

## 前端设计

### 列表层

`BrainstormSuggestionCards.vue` 继续展示建议卡网格。每张待处理卡增加：

- 智能主按钮：按后端动作提示显示。
- `处理` 按钮。
- 一句动作原因，例如“适合继续优化大纲，不适合转设定”。

状态 badge 使用明确文案：

- `active` -> `待处理`
- `unresolved` -> `需补充`
- `submitted` -> `已提交审批`
- `resolved` -> `已解决`
- `dismissed` -> `已忽略`
- `superseded` -> `已覆盖`

### 详情抽屉

点 `处理` 后打开右侧抽屉，展示：

- 标题、类型、来源、状态。
- 摘要。
- 推荐动作和原因。
- 结构化 payload。
- `merge_key`、`card_id` 等调试信息，默认折叠。
- 操作按钮。

操作规则：

- `转为待审批设定` 只对支持构建 pending payload 的卡片可用。
- `回填到输入区` 对所有非终态卡片可用。
- `标记已解决` 和 `忽略` 对 `active/unresolved` 可用。
- `重新激活` 对 `resolved/dismissed` 可用。
- `superseded` 只读，不允许重新激活。
- `submitted` 只读，可提示用户去设定审批入口继续处理。

关系类建议卡第一版不做单卡转 pending。抽屉中禁用“转为待审批设定”，说明“关系建议将在最终确认时解析处理”。

### 回填到输入区

`回填到输入区` 不调用后端，沿用现有 `OutlineConversation.setDraft()`。前端基于卡片生成结构化 prompt：

```text
请根据这张设定建议卡继续优化当前大纲：
标题：{card.title}
类型：{card.card_type}
来源：{source_outline_refs}
状态：{status_label}
建议：{card.summary}
需要补充/确认的设定字段：{payload_summary}
```

如果 payload 中有关键字段，追加到“需要补充/确认的设定字段”中。这个动作只把内容放进输入区，不会自动发送请求。用户必须自己检查、编辑，并点击现有发送按钮后才会提交。

## 后端设计

新增轻量操作接口：

```http
PATCH /api/novels/{novel_id}/brainstorm/suggestion_cards/{card_id}
```

请求体：

```json
{
  "action": "resolve"
}
```

支持 action：

- `resolve`
- `dismiss`
- `submit_to_pending`
- `reactivate`

响应使用独立 envelope：

```json
{
  "workspace": {},
  "pending_extraction": null
}
```

其中 `workspace` 是最新 `BrainstormWorkspacePayload`，`pending_extraction` 只在 `submit_to_pending` 成功时返回简要信息。

服务层新增 `BrainstormWorkspaceService.update_suggestion_card()`，职责：

- 加载当前 active workspace。
- 根据 `card_id` 或 `merge_key` 定位卡片。
- 校验当前状态和目标 action 是否允许。
- 更新 workspace 内 `setting_suggestion_cards`。
- 对 `submit_to_pending` 复用 `ExtractionService.build_pending_payload_from_suggestion_card()`，创建 pending extraction 后将卡片标记为 `submitted`。
- 提交事务后返回最新 workspace payload。

不新增表。建议卡仍属于 brainstorm workspace 的结构化内容。

服务层同时新增 `BrainstormWorkspaceService.build_suggestion_card_action_hint()`，职责：

- 根据 `card_type`、`payload`、`summary` 和 `source_outline_refs` 计算推荐动作。
- 给出可用动作列表。
- 给出前端可直接展示的原因。
- 在 `_serialize_workspace()` 时为每张建议卡补充动作提示字段。

## 数据流

1. 页面加载时，`GET /brainstorm/workspace` 返回 `setting_suggestion_cards`。
2. 前端按状态拆分待处理列表和历史列表。
3. 用户点 `继续优化`、`补充信息` 或 `回填到输入区`，前端生成 prompt 并写入现有输入框，不自动发送。
4. 用户在抽屉内执行处理动作，前端调用 PATCH 接口。
5. 后端更新 workspace 或创建 pending extraction。
6. 前端用返回的 workspace payload 刷新建议卡区域。
7. 最终确认时，`resolved/dismissed/submitted/superseded` 不再参与待处理阻塞。

## 错误处理

- workspace 不存在：404。
- 卡片不存在：404。
- 当前阶段不是 brainstorming：409。
- action 不支持：400。
- 状态不允许执行该 action：409。
- 重复 `submit_to_pending`：409。
- payload 不合法：409，并返回可读错误。
- 网络失败：前端保持抽屉打开，展示错误，可重试。

前端执行失败时不乐观更新状态，避免 UI 与 workspace 数据不一致。

## 测试设计

### 后端

`tests/test_services/test_brainstorm_workspace_service.py`：

- 可转设定类卡片的动作提示推荐 `submit_to_pending`。
- 大纲优化类卡片的动作提示推荐 `continue_outline_feedback`。
- 信息不足类卡片的动作提示推荐 `request_more_info`。
- `resolve` 将 `active/unresolved` 改为 `resolved`。
- `dismiss` 将 `active/unresolved` 改为 `dismissed`。
- `reactivate` 将 `resolved/dismissed` 改为 `active`。
- `submit_to_pending` 创建 pending extraction，并将卡片改为 `submitted`。
- `superseded` 卡片不能重新激活。
- `submitted` 卡片不能重新激活或重复提交。
- 不存在卡片返回明确错误。
- 重复提交返回明确错误。

API route 测试：

- PATCH 成功返回最新 workspace。
- 不存在卡片返回 404。
- 非法状态返回 409。

### 前端

`BrainstormSuggestionCards.test.js`：

- 渲染智能主按钮和 `处理`。
- 点击 `处理` 打开详情抽屉。
- 点击抽屉动作发出对应事件。
- 大纲优化类卡片显示 `继续优化`，不会显示可用的 `转为待审批设定`。
- 可转设定类卡片显示 `转设定`。
- 信息不足类卡片显示 `补充信息`。
- 历史状态默认折叠。
- 关系类卡片禁用单卡转审批。

`VolumePlan.test.js`：

- 接收回填事件后写入现有 conversation draft。
- 验证回填事件不会调用 `store.submitOutlineFeedback()`。
- 接收处理事件后调用 store action。

`novel.test.js`：

- store action 调用 PATCH API。
- 成功后刷新 `brainstormWorkspace.data`。
- 失败时保留错误状态，不清空 workspace。

## 验证

- 后端目标 pytest。
- 前端相关 vitest。
- 前端 build。
- 本地重启后确认工作台能显示建议卡入口，处理后状态刷新。
