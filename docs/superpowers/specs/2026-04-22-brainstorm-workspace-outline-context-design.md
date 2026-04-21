# 脑爆工作区与大纲上下文隔离 — 设计文档

**日期：** 2026-04-22  
**主题：** 为总纲、卷纲、设定草稿建立独立脑爆工作区，并在最终确认时统一提交到正式链路  
**状态：** 待实现  
**依赖：** 现有 `OutlineWorkbenchService`、`outline_sessions` / `outline_messages`、`ExtractionService`、`NovelState`

---

## 1. 目标

将当前“边对话边直接改正式总纲/卷纲”的模式，改造成一套完整的脑爆工作区机制：

- 脑爆阶段完整服用 `superpowers:brainstorming` 的逐步确定流程。
- 总纲和每一卷大纲都拥有各自独立的上下文窗口。
- 前端继续复用当前 outline workbench 的格子选择、详情面板和输入框逻辑。
- 脑爆期间只更新临时草稿，不直接写正式 `novel_documents`、`checkpoint_data` 或实体数据。
- 用户显式“最终确认”后，才统一提交：
  - 总纲草稿转正为正式 `synopsis`
  - 卷纲草稿转正为正式卷级大纲数据
  - 设定草稿进入现有 `pending` 导入链路，等待批准后再生成正式设定文档与实体

---

## 2. 设计原则

1. **上下文隔离**
   总纲和每一卷大纲必须各自拥有独立消息流，不能共享一份对话历史。

2. **正式数据延迟提交**
   在用户最终确认之前，所有脑爆产物都只存在于工作区和上下文快照中。

3. **导入链路复用**
   设定草稿不得绕过现有上传/待审批流程，必须进入 `pending_extractions`，以复用实体抽取、审批和管理能力。

4. **UI 复用优先**
   尽量复用当前 outline workbench 的左侧格子、右侧详情面板和输入框提交逻辑，不新建第二套主要交互壳。

5. **提交原子性**
   最终确认必须作为单次正式提交处理，不允许出现总纲已转正、卷纲或设定只提交一半的状态。

---

## 3. 数据模型与边界

### 3.1 `NovelState`

`NovelState` 继续只负责正式主流程状态与正式 checkpoint：

- 管理 `brainstorming -> volume_planning` 等阶段推进
- 保存正式 `synopsis_data`
- 保存正式卷级大纲数据
- 不保存脑爆过程中的临时总纲、卷纲、设定草稿

### 3.2 `BrainstormWorkspace`

新增独立脑爆工作区，作为脑爆阶段唯一的临时结构化状态容器。

建议字段：

```python
BrainstormWorkspace(
    id,
    novel_id,
    status,  # active / submitted / abandoned
    workspace_summary,
    outline_drafts,
    setting_docs_draft,
    last_saved_at,
    submitted_at,
)
```

约束：

- 一部小说同一时刻最多 1 个激活工作区
- 脑爆期间所有草稿只写这里
- 最终确认成功后，工作区标记为 `submitted`

### 3.3 大纲上下文项

总纲和每一卷大纲都需要自己的上下文。这里不新建新的消息系统，而是复用现有：

- `outline_sessions`
- `outline_messages`

每个上下文项由 `(outline_type, outline_ref)` 唯一标识：

- 总纲：`(synopsis, synopsis)`
- 第 N 卷：`(volume, vol_N)`

每个上下文项独立保存：

- `conversation_summary`
- `last_result_snapshot`
- `recent_messages`

### 3.4 大纲草稿

工作区中的结构化大纲草稿按上下文项拆分，并作为正式提交前的唯一权威草稿来源：

```python
outline_drafts = {
    "synopsis:synopsis": {...},
    "volume:vol_1": {...},
    "volume:vol_2": {...},
}
```

规则：

- `BrainstormWorkspace.outline_drafts` 保存当前权威草稿
- `outline_sessions.last_result_snapshot` 保存当前上下文项最近一次结果快照，服务前端展示与对话续接
- 两者通常同步更新，但正式提交时应以 `BrainstormWorkspace.outline_drafts` 为准

具体草稿形态：

- 总纲上下文对应 `novel_synopsis_draft`
  - 复用现有 `SynopsisData`
- 每卷上下文对应自己的 `volume_outline_draft`
  - 建议最少字段：
    - `outline_ref`
    - `title`
    - `summary`
    - `target_chapter_count`
    - `arc_goals`
    - `milestones`
    - `status`

`last_result_snapshot` 代表该上下文项最近一次展示快照，前端详情面板直接读取并展示。

### 3.5 设定草稿

设定草稿挂在工作区层，而不是某一卷上下文下：

```python
SettingDocDraft(
    draft_id,
    source_outline_ref,   # synopsis / vol_1 / vol_2 ...
    source_kind,         # character / faction / location / item / worldview / setting / concept
    target_import_mode,  # auto_classify / explicit_type
    target_doc_type,     # optional, used when explicit_type
    title,
    content,
    order_index,
)
```

约束：

- 设定草稿在最终确认前不是正式文档
- 设定草稿在最终确认前也不是 `pending`
- 设定草稿最终确认后才批量进入现有导入链路

---

## 4. 交互流程

### 4.1 启动脑爆工作区

用户进入脑爆阶段时：

1. 创建或恢复该小说的 `BrainstormWorkspace`
2. 加载左侧大纲格子：
   - `总纲`
   - `第1卷` 到 `第N卷`
3. 为每个格子准备独立上下文项

### 4.2 切换上下文

用户点击左侧格子时：

- 加载对应 `(outline_type, outline_ref)` 的会话上下文
- 右侧详情面板显示该格子的 `last_result_snapshot`
- 下方输入框继续复用现有 workbench 的提交逻辑

效果：

- 在总纲格子里输入，修改的是总纲草稿
- 在某一卷格子里输入，修改的是该卷草稿
- 不同卷之间不会互相污染上下文

### 4.3 提交修改意见

用户在输入框提交意见后：

1. 读取当前格子的上下文消息
2. 读取当前工作区中该格子的草稿
3. 调用对应优化逻辑：
   - 总纲优化：更新 `novel_synopsis_draft`
   - 卷纲优化：更新当前卷的 `volume_outline_draft`
4. 将 assistant 回复写入该格子的 `outline_messages`
5. 更新该格子的 `last_result_snapshot`
6. 如有需要，同步合并工作区中的 `setting_docs_draft[]`

注意：

- 这一步只保存草稿
- 不写正式 `checkpoint_data`
- 不写正式 `novel_documents`
- 不生成实体

### 4.4 最终确认

用户显式点击“最终确认”时，执行一次正式提交：

1. 校验工作区状态和必要草稿完整性
2. 总纲草稿转正式 `synopsis`
3. 卷纲草稿转正式卷级大纲数据
4. 设定草稿批量转成 `pending_extractions`
5. `NovelState` 推进到 `volume_planning`
6. 工作区状态改为 `submitted`

---

## 5. 前端设计

### 5.1 交互壳复用

不新建一套脑爆页，直接扩展当前 outline workbench 模式：

- 左侧：总纲 + 各卷格子
- 右侧：当前格子的结构化详情
- 下方：继续复用当前输入框和提交按钮
- 额外增加：
  - “最终确认”按钮
  - “设定草稿”面板或抽屉

### 5.2 左侧格子的数据来源

脑爆模式下，左侧列表优先来自工作区草稿，而不是正式 checkpoint：

- 总纲格子：来自 `novel_synopsis_draft`
- 卷格子：来自 `volume_outline_drafts[]`
- 缺失卷：根据总纲预计卷数生成占位格子

### 5.3 右侧详情面板

右侧详情面板继续复用当前 `last_result_snapshot -> detail panel` 的展示方式：

- 选中总纲：显示总纲草稿快照
- 选中某卷：显示该卷草稿快照
- 若该卷尚未生成：显示缺失态，并允许直接通过输入框要求生成

### 5.4 输入框复用

输入框交互尽量保持不变，只修改提交语义：

- 旧语义：直接优化正式 outline
- 新语义：优化当前上下文项的工作区草稿

### 5.5 设定草稿展示

设定草稿不挂在单个卷格子的详情区，而是在单独面板中展示：

- 标题
- 来源（总纲 / 第几卷）
- 草稿类型
- 导入模式
- 内容摘要

该面板在最终确认前只表示“待提交草稿”，不是正式文档，也不是 pending。

---

## 6. 后端组件划分

### 6.1 保留 `OutlineWorkbenchService` 的交互壳能力

继续复用它负责的部分：

- 构建当前选中的上下文窗口
- 获取消息历史
- 记录消息流
- 驱动输入框提交的会话编排

但在脑爆模式下，`OutlineWorkbenchService` 不再直接把优化结果写回正式 checkpoint。

### 6.2 新增 `BrainstormWorkspaceService`

建议新增独立服务，职责仅限于：

- 读取/创建当前工作区
- 保存结构化草稿
- 合并设定草稿
- 执行最终正式提交

建议接口：

- `get_or_create_workspace(novel_id)`
- `get_workspace_payload(novel_id)`
- `save_outline_draft(novel_id, outline_type, outline_ref, result_snapshot)`
- `merge_setting_drafts(novel_id, setting_draft_updates)`
- `submit_workspace(novel_id)`

### 6.3 优化结果统一结构

为总纲和卷纲优化统一一套返回结构：

```python
{
    "assistant_content": str,
    "outline_result_snapshot": dict,
    "setting_draft_updates": list[dict],
    "conversation_summary": str,
}
```

这样可复用一套提交主流程，仅在具体 prompt / agent 选择上分叉。

---

## 7. 提交与落库策略

### 7.1 三层数据隔离

系统中同时存在三类数据，必须严格分层：

1. `outline_sessions` / `outline_messages`
   - 交互历史
   - 只回答“用户怎么聊的”

2. `brainstorm_workspace`
   - 当前脑爆草稿
   - 只回答“当前临时确定到哪一步”
   - 包含权威 `outline_drafts` 与 `setting_docs_draft[]`

3. 正式数据：`novel_documents` / `pending_extractions` / `NovelState.checkpoint_data`
   - 正式生产数据
   - 只回答“系统最终生效了什么”

### 7.2 正式提交映射

最终确认时建议按以下方式映射：

- `novel_synopsis_draft`
  - 写 1 份正式 `synopsis`
  - 同步写入 `checkpoint_data.synopsis_data`

- `volume_outline_drafts[]`
  - 写入正式卷级大纲数据
  - 与现有 `volume_planning` / `current_volume_plan` 流程兼容
  - 提交后可由系统指定第一卷或当前激活卷为 `current_volume_plan`

- `setting_docs_draft[]`
  - 不直接写正式 `novel_documents`
  - 一律先生成 `pending_extractions`
  - 后续仍由现有批准流程生成正式设定文档与实体

### 7.3 导入模式

提交设定草稿时支持两种模式：

- `auto_classify`
  - 复用现有分类逻辑
  - 适合粗粒度草稿

- `explicit_type`
  - 脑爆模块可为角色、势力、地点、道具等细粒度草稿附带类型提示
  - 但仍然进入 `pending`
  - 不能绕过现有审批链路

### 7.4 原子性要求

最终确认应作为单次正式提交处理：

- 如果 `synopsis` 写成功但卷纲或设定投递失败，整体回滚
- 工作区保持 `active`
- 用户可修复后重新提交

禁止部分成功。

---

## 8. API 与服务接口建议

建议新增明确的工作区接口，而不是继续复用旧接口名承载新语义：

- `POST /api/novels/{novel_id}/brainstorm/workspace/start`
- `GET /api/novels/{novel_id}/brainstorm/workspace`
- `POST /api/novels/{novel_id}/brainstorm/workspace/submit`

对于现有 workbench 接口，有两种可接受实现方式：

1. 在现有接口上增加脑爆模式参数，例如 `mode=brainstorm_workspace`
2. 新增一组脑爆版 workbench 接口，但底层继续复用相同的 session/message 逻辑

推荐原则：

- 前端组件可复用
- 后端上下文逻辑可复用
- 正式 checkpoint 写入必须与脑爆工作区逻辑分流

---

## 9. 错误处理

| 场景 | 处理方式 |
|------|----------|
| 当前格子优化失败 | 保留原草稿和原快照，仅返回错误 |
| 工作区不存在 | 自动创建，或返回明确错误并提示重新开始脑爆 |
| 最终确认缺少总纲草稿 | 阻止提交并提示先完成总纲 |
| 最终确认缺少卷纲草稿 | 阻止提交并提示补齐卷纲 |
| 设定草稿投递 `pending` 失败 | 整体回滚，不写任何正式数据 |
| 工作区已提交却再次提交 | 返回冲突错误，要求用户重新开启脑爆 |

---

## 10. 测试策略

### 10.1 服务层测试

- `BrainstormWorkspaceService` 创建/读取工作区
- 保存总纲草稿
- 保存卷纲草稿
- 合并设定草稿
- 提交失败时事务回滚

### 10.2 Workbench 集成测试

- 切换总纲/卷纲时加载各自独立上下文
- 同一输入框提交后只更新当前格子的草稿与消息
- 缺失卷纲可通过输入框直接生成

### 10.3 导入链路测试

- `setting_docs_draft[]` 提交后生成 `pending_extractions`
- `auto_classify` 模式能进入预期分类流程
- `explicit_type` 模式能携带类型提示但仍停留在 `pending`

### 10.4 端到端测试

最少覆盖以下主链路：

1. 开始脑爆工作区
2. 修改总纲
3. 修改某一卷
4. 查看设定草稿
5. 最终确认
6. 验证：
   - 正式 `synopsis` 已生成
   - 正式卷纲已生成
   - 设定已进入 `pending`
   - `NovelState` 推进到 `volume_planning`
   - 实体仍需待批准后才出现

---

## 11. 实现范围

**明确包含：**

- 新增脑爆工作区数据模型与服务
- 总纲与每卷大纲的独立上下文支持
- 前端复用现有 workbench 输入框与详情壳
- 最终确认时统一提交总纲、卷纲与设定草稿
- 设定草稿接入现有 `pending` 导入链路

**明确不包含：**

- 自动批准设定草稿
- 在脑爆阶段直接生成实体
- 为脑爆单独重写第二套前端主界面
- 多阶段局部锁定与局部提交
- 将设定草稿直接写成正式 `novel_documents`

---

## 12. 推荐实现顺序

1. 增加 `BrainstormWorkspace` 数据模型与仓储
2. 让脑爆模式下的 workbench 提交写入工作区草稿，而不是正式 checkpoint
3. 接入总纲与卷纲独立上下文
4. 接入设定草稿收集与展示
5. 实现最终确认提交事务
6. 补齐服务层、接口层、前端和端到端测试

---

## 13. 结论

本设计将脑爆阶段从“直接改正式大纲”升级为“工作区草稿 + 独立上下文 + 最终统一提交”的完整机制。

它满足以下关键要求：

- 完整服用 brainstorming 的逐步确定流程
- 总纲和每一卷大纲拥有独立上下文
- 复用当前格子的输入框逻辑
- 总纲、卷纲和设定都只在最终确认时进入正式链路
- 设定仍然走现有导入与审批流程，以保证实体可管理
