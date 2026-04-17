# 交互式大纲脑暴 — 设计文档

**日期：** 2026-04-17  
**主题：** 将 BrainstormAgent 改造为 "Claude Code 对话 + Web 实时预览" 的交互模式  
**状态：** 待实现  
**依赖：** 现有 BrainstormAgent、MCP Server、Vue 3 前端

---

## 1. 目标

将现有的一次性大纲生成（`POST /brainstorm`）改造为**人机协作的交互式脑暴流程**：

- **Claude Code** 作为对话界面：用户用自然语言与 LLM 迭代、修正大纲。
- **Web 前端**作为实时监视器：展示 Claude 最新生成的结构化大纲（只读）。
- 避免在前端自研对话框，同时保留结构化内容的可视性。

---

## 2. 用户旅程

```
┌─────────────────────────────────────────────────────────────────┐
│  前端: 用户上传设定文档 → 点击「开始脑暴」                       │
│       状态变为 BRAINSTORMING                                    │
│       显示预填充 prompt，用户复制后粘贴到 Claude Code           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Claude Code: 用户粘贴命令                                      │
│  Claude 读取数据库中的 worldview/setting/concept 文档            │
│  开始多轮对话迭代大纲                                            │
│  每轮生成后调用 MCP save_brainstorm_draft 写回 pending_synopsis │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  前端: 轮询 /api/novels/{id}/state                               │
│       发现 checkpoint_data.pending_synopsis 后                   │
│       实时渲染为结构化卡片（标题、梗概、人物、里程碑）            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Claude Code: 用户说「确认」                                     │
│  Claude 调用 MCP confirm_brainstorm                             │
│  pending_synopsis 转正 → 写入 novel_documents                   │
│  状态推进到 VOLUME_PLANNING                                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 架构设计

### 3.1 新增后端 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/novels/{novel_id}/brainstorm/start` | 前端调用，状态切为 `BRAINSTORMING`，生成并返回给 Claude 的 prompt 模板。状态切换直接调用 `NovelDirector.save_checkpoint`，绕过 `VALID_TRANSITIONS` 限制。 |

### 3.1.1 新增 MCP Tools

以下工具通过基于官方 MCP SDK 的 `NovelDevMCPServer`（stdio server）暴露给 Claude Code，**不对外提供 HTTP endpoint**。用户需要在 Claude Code 中注册该 server（例如 `claude mcp add novel-dev "python -m novel_dev.mcp_server"`），Claude 会自动发现并调用这些 tools。

### 3.2 新增 MCP Tools

- `get_novel_document_full(novel_id: str, doc_id: str)`
  - 读取指定文档的完整内容，不做截断。
  - 供 Claude 在脑暴前获取世界观/设定文档全文。
  - 返回 `{"id": ..., "title": ..., "content": ..., "doc_type": ...}`。

- `save_brainstorm_draft(novel_id: str, synopsis_data: dict)`
  - 校验当前 novel 状态为 `BRAINSTORMING`。
  - 内部把 `synopsis_data` 用 `SynopsisData.model_validate()` 校验。
  - 写入 `checkpoint_data["pending_synopsis"]`。
  - 返回 `{"saved": true}`。

- `confirm_brainstorm(novel_id: str)`
  - 校验当前 novel 状态为 `BRAINSTORMING`，且 `checkpoint_data` 中存在 `pending_synopsis`。
  - **复用 `BrainstormAgent._format_synopsis_text`** 生成 synopsis markdown。
  - 将 markdown 与 `SynopsisData` 写入 `novel_documents`。
  - 状态推进到 `VOLUME_PLANNING`。
  - 清理 `pending_synopsis`。
  - 返回 `{"confirmed": true}`。

### 3.3 状态机扩展

`NovelDirector.Phase` 新增一个阶段：

```python
class Phase(Enum):
    # ... existing phases
    BRAINSTORMING = "brainstorming"
```

状态流转：

```
volume_planning（用户点击开始）
    → BRAINSTORMING（Claude 对话中）
    → volume_planning（Claude 确认后）
```

> 注：`VALID_TRANSITIONS` 需要更新：允许 `VOLUME_PLANNING → BRAINSTORMING`，以及 `BRAINSTORMING → VOLUME_PLANNING`。

### 3.4 前端改动

在 `index.html` 的「操作」面板和「文档」视图中做以下调整：

1. **操作按钮**
   - 当状态为 `volume_planning` 时，显示「开始脑暴」按钮。
   - 当状态为 `brainstorming` 时，按钮变为禁用状态，显示提示文案：
     > "请在 Claude Code 中粘贴以下 prompt 继续脑暴："
   - 提供一键复制预填充 prompt 的功能。

2. **实时预览面板**
   - 在「文档」标签页或独立卡片中，增加「脑暴预览」区域。
   - 轮询 `GET /api/novels/{id}/state`，间隔 3 秒。
   - 若 `checkpoint_data.pending_synopsis` 存在，将其渲染为结构化卡片：
     - 标题 + 一句话梗概
     - 核心冲突
     - 主题列表
     - 人物弧光（可折叠卡片）
     - 剧情里程碑（时间线）
     - 预计卷数 / 章数 / 总字数
   - 面板只读，不开放编辑。

3. **轮询停止条件**
   - 状态离开 `BRAINSTORMING` 后自动停止轮询。

### 3.5 Claude Code 侧的交互方式

**不要求修改 Claude Code 本体**，而是通过以下方式触达：

- **方式**：用户在前端复制预填充 prompt，粘贴到 Claude Code 的输入框中。
- **Claude 侧行为**：Claude 读取 MCP 暴露的 tools，按需获取文档、保存草稿、最终确认。

**本设计采用最轻量的实现**：前端返回一段预填充的 prompt，用户复制到 Claude Code 即可开始对话。Claude 通过 MCP tools 读写项目状态。

**建议的预填充 prompt（前端提供复制）**：

```
请为小说 "{novel_id}" 脑暴一份大纲。

已上传的设定文档列表如下，你可以调用 get_novel_document_full 获取完整内容：
{documents}

请基于这些文档生成大纲。每次修改后请调用 save_brainstorm_draft 保存。
当我确认满意后，调用 confirm_brainstorm 完成脑暴。
```

> 其中 `{documents}` 只包含文档的 `doc_id`、`title`、`doc_type` 列表，不附带全文，由 Claude 按需调用 `get_novel_document_full`。

---

## 4. 数据模型

`checkpoint_data` 新增字段：

```json
{
  "pending_synopsis": {
    "title": "...",
    "logline": "...",
    "core_conflict": "...",
    "themes": [...],
    "character_arcs": [...],
    "milestones": [...],
    "estimated_volumes": 3,
    "estimated_total_chapters": 90,
    "estimated_total_words": 270000
  }
}
```

数据结构完全复用现有的 `SynopsisData` schema，无新增模型。

---

## 5. 错误处理

| 场景 | 行为 |
|------|------|
| `start` 时无 source documents | 返回 400，提示用户先上传世界观/设定文档 |
| `save_brainstorm_draft` 时状态不是 `BRAINSTORMING` | MCP tool 返回错误信息，Claude 向用户解释 |
| `confirm_brainstorm` 时无 `pending_synopsis` | MCP tool 返回错误信息，Claude 向用户解释 |
| MCP tool 调用失败 | 返回错误详情给 Claude，由 Claude 向用户解释 |

---

## 6. 测试策略

1. **API 测试**
   - `test_brainstorm_start`：验证状态切换和 prompt 返回。

2. **MCP 测试**
   - `test_mcp_get_novel_document_full`：验证可读取文档完整内容。
   - `test_mcp_save_brainstorm_draft`：验证 tool 可写回 pending_synopsis。
   - `test_mcp_confirm_brainstorm`：验证 tool 可转正并推进状态。

3. **状态机测试**
   - 验证 `volume_planning → BRAINSTORMING → volume_planning` 流转正确。

---

## 7. 实现范围

**明确包含：**
- 1 个新 API endpoint (`/brainstorm/start`)
- 3 个新 MCP tools
- `Phase.BRAINSTORMING` 状态
- 前端「开始脑暴」按钮 + prompt 复制 + 实时预览面板（轮询）
- 将 `NovelDevMCPServer` 迁移到官方 MCP SDK（stdio server）

**明确不包含：**
- 前端内嵌对话界面
- SSE/WebSocket（先用轮询）
- 自动唤起 Claude Code（用户手动复制命令）
- 大纲历史版本对比

---

## 8. 未来扩展

- 将轮询升级为 SSE，减少延迟。
- 在 Claude Code 中注册一个真正的 slash command（`/brainstorm <novel-id>`），免去复制粘贴。
- 支持脑暴历史版本回退（类似 style_profile 的 rollback）。
