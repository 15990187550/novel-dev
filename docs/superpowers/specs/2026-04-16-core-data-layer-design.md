# 全自动长篇网络小说创作 Agent — 核心数据层设计文档

**日期：** 2026-04-16  
**主题：** 核心数据层（知识库与状态管理）  
**状态：** 待实现

---

## 1. 项目概述

本系统是一个全自动长篇网络小说创作 Agent，核心目标是：
- 支持从原始设定到卷级大纲再到章节正文的完整流水线
- 通过结构化知识库管理解决大模型长上下文幻觉问题
- 维持小说的追读力与设定一致性
- 支持断点续作与全自动无人值守运行

**本设计文档聚焦于系统的第一子项目：核心数据层（知识库与状态管理）。** 所有后续模块（大纲生成、章节写作、审核评分、全自动调度）都依赖此数据层作为唯一真实来源（Source of Truth）。

---

## 2. 设计原则

1. **强一致性优先**：人物状态、时间线、空间线、伏笔状态必须使用关系型数据库精确管理，不能依赖向量检索的模糊匹配。
2. **完整历史保留**：每次章节回写都生成实体的新版本，旧版本不覆盖，以支持回溯、调试、分支探索和批量 review。
3. **混合存储**：结构化数据存 PostgreSQL，语义检索用 pgvector，正文副本存纯 Markdown 文件供人工审阅。
4. **接口分层**：核心流程走 Python SDK（高效、确定），外部交互走 REST API 和 MCP Server（便于调试与监控）。
5. **双轨时间/空间表示**：结构化坐标用于系统计算，叙事描述用于提示词注入。

---

## 3. 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    外部接口层 (REST / MCP)                    │
│         供人工查询、调试、监控、以及第三方工具接入               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Python SDK (核心内层)                      │
│  实体管理 · 版本链 · 时间/空间线 · 伏笔 · 状态机 · 全文索引      │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
┌──────────────────────────┐    ┌──────────────────────────┐
│    PostgreSQL 主存储      │    │    pgvector 向量索引      │
│  (状态机 · 版本 · 结构化)   │    │  (语义检索 · 风格样本 ·    │
│                          │    │   概念相似度匹配)          │
└──────────────────────────┘    └──────────────────────────┘
              │                               │
              └───────────────┬───────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              纯 Markdown 文件副本 (每章一个 .md)               │
│                    供人工直接阅读和版本控制                    │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. 数据库核心模型设计

### 4.1 核心实体表 (`entities`)

存储人物、物品、地点、概念、势力等实体的元数据和当前版本指针。

```sql
CREATE TABLE entities (
    id TEXT PRIMARY KEY,              -- 如 character_001
    type TEXT NOT NULL,               -- character / item / location / concept / faction
    name TEXT NOT NULL,
    current_version INTEGER NOT NULL DEFAULT 1,
    created_at_chapter_id TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### 4.2 版本链表 (`entity_versions`)

每次章节回写时，若实体状态发生变化，主动插入一条新版本记录。旧版本完整保留，可通过 `entity_id + version` 精确回溯。

```sql
CREATE TABLE entity_versions (
    id SERIAL PRIMARY KEY,
    entity_id TEXT REFERENCES entities(id),
    version INTEGER NOT NULL,
    chapter_id TEXT,                  -- 触发本次变更的章节
    state JSONB NOT NULL,             -- 完整状态（人物属性、物品描述、势力格局等）
    diff_summary JSONB,               -- 变更摘要（方便快速查看）
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(entity_id, version)
);
```

**查询最新状态：**
```sql
SELECT state FROM entity_versions
WHERE entity_id = ?
ORDER BY version DESC LIMIT 1;
```

**查询历史状态（第 N 章结束后）：**
```sql
SELECT state FROM entity_versions
WHERE entity_id = ? AND chapter_id <= ?
ORDER BY version DESC LIMIT 1;
```

### 4.3 关系表 (`entity_relationships`)

记录实体间的关系，预留图扩展字段。

```sql
CREATE TABLE entity_relationships (
    id SERIAL PRIMARY KEY,
    source_id TEXT REFERENCES entities(id),
    target_id TEXT REFERENCES entities(id),
    relation_type TEXT NOT NULL,      -- master_of / belongs_to / located_in / enemy_of / allied_with / participant_of_event
    metadata JSONB,
    created_at_chapter_id TEXT,
    is_active BOOLEAN DEFAULT TRUE,   -- 关系可能随剧情断裂/解除
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 4.4 时间线 (`timeline`)

```sql
CREATE TABLE timeline (
    id SERIAL PRIMARY KEY,
    tick INTEGER NOT NULL UNIQUE,     -- 系统内部绝对刻度
    narrative TEXT NOT NULL,          -- 叙事描述，如 "天玄历384年冬，宗门大比后第三日"
    anchor_chapter_id TEXT,           -- 关联章节
    anchor_event_id TEXT              -- 关联事件
);
```

### 4.5 空间线 (`spaceline`)

```sql
CREATE TABLE spaceline (
    id TEXT PRIMARY KEY,              -- location_id
    name TEXT NOT NULL,
    parent_id TEXT REFERENCES spaceline(id),  -- 层级链：天玄大陆 -> 东荒 -> 青云山脉 -> 青云宗
    narrative TEXT,                   -- 叙事描述，如 "青云宗·外门弟子居所·深秋夜雨"
    metadata JSONB
);
```

### 4.6 伏笔表 (`foreshadowings`)

```sql
CREATE TABLE foreshadowings (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,            -- 伏笔内容描述
   埋下_chapter_id TEXT,
    埋下_time_tick INTEGER,
    埋下_location_id TEXT,
    相关人物_ids TEXT[],              -- 埋下时相关的人物
    回收条件 JSONB,                   -- {必要条件: [...], 预计回收卷: "", 预计回收章: ""}
    回收状态 TEXT DEFAULT 'pending',   -- pending / recovered / abandoned
    recovered_chapter_id TEXT,
    recovered_event_id TEXT,
    回收影响 JSONB                    -- 回收后触发的剧情影响
);
```

### 4.7 状态机表 (`novel_state`) — 断点续作核心

```sql
CREATE TABLE novel_state (
    novel_id TEXT PRIMARY KEY,
    current_phase TEXT NOT NULL,      -- e.g. "volume_planning", "writing_chapter_47_draft"
    current_volume_id TEXT,
    current_chapter_id TEXT,
    checkpoint_data JSONB NOT NULL,   -- 该阶段的输入参数、中间结果、错误信息
    last_updated TIMESTAMP DEFAULT NOW()
);
```

### 4.8 章节表 (`chapters`)

```sql
CREATE TABLE chapters (
    id TEXT PRIMARY KEY,
    volume_id TEXT NOT NULL,
    chapter_number INTEGER NOT NULL,
    title TEXT,
    status TEXT DEFAULT 'pending',    -- pending / drafting / reviewing / editing / fast_reviewing / completed
    raw_draft TEXT,                   -- WriterAgent 草稿
    polished_text TEXT,               -- EditorAgent 精修后正文
    score_overall INTEGER,            -- 深度审核总分
    score_breakdown JSONB,            -- 各维度得分明细
    review_feedback JSONB,            -- 审核意见
    fast_review_score INTEGER,        -- 快速二审得分
    fast_review_feedback JSONB,       -- 快速二审意见
    UNIQUE(volume_id, chapter_number)
);
```

### 4.9 文档库 (`novel_documents`)

存储世界观、核心设定、风格画像、总纲等全局文档，并建立向量索引供语义检索。

```sql
CREATE TABLE novel_documents (
    id TEXT PRIMARY KEY,
    novel_id TEXT NOT NULL,
    doc_type TEXT NOT NULL,           -- worldview / setting / style_profile / synopsis / volume_plan
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    vector_embedding VECTOR(1536),    -- 用于语义检索（维度根据模型调整）
    version INTEGER DEFAULT 1,
    updated_at TIMESTAMP DEFAULT NOW()
);
```

---

## 5. 外部接口层

### 5.1 MCP Server 工具集

| 工具名 | 用途 |
|---|---|
| `query_entity` | 按 ID 查询实体最新状态 |
| `query_entity_at_chapter` | 按章节回溯实体历史状态 |
| `search_entities` | 语义搜索实体（pgvector） |
| `list_relationships` | 查询实体关系网 |
| `get_timeline` | 获取当前及相邻时间刻度 |
| `get_spaceline_chain` | 获取地点完整层级链 |
| `get_active_foreshadowings` | 获取所有 pending 伏笔 |
| `get_novel_documents` | 按类型查询世界观/设定/风格文档 |
| `get_novel_state` | 获取当前写作进度与断点状态 |
| `resume_novel` | 从断点恢复全自动写作流程 |

### 5.2 REST API

- `GET /api/novels/{novel_id}/state`
- `GET /api/novels/{novel_id}/entities/{entity_id}`
- `GET /api/novels/{novel_id}/chapters/{chapter_id}`
- `POST /api/novels/{novel_id}/resume`
- `GET /api/novels/{novel_id}/chapters/{chapter_id}/export.md`

---

## 6. Agent 架构设计

采用 **主 Agent + 子 Agent** 模式。

```
┌─────────────────────────────────────────────────────────┐
│                   NovelDirector                         │
│         状态机维护 · 流程调度 · 断点恢复 · 决策判断          │
└─────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ Brainstorm   │    │ VolumePlanner│    │ ContextAgent │
│   Agent      │    │    Agent     │    │              │
│  (大纲脑爆)   │    │  (卷级规划)   │    │ (上下文准备)  │
└──────────────┘    └──────────────┘    └──────────────┘
        │                   │                   │
        ▼                   ▼                   ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ WriterAgent  │    │ CriticAgent  │    │ EditorAgent  │
│  (正文写作)   │    │  (深度审核)   │    │  (精修润色)   │
└──────────────┘    └──────────────┘    └──────────────┘
                                               │
                                               ▼
                                      ┌──────────────┐
                                      │ FastReviewer │
                                      │  (快速二审)   │
                                      └──────────────┘
                                               │
                                               ▼
                                      ┌──────────────┐
                                      │ LibrarianAgent│
                                      │  (提取入库)   │
                                      └──────────────┘
```

### 6.1 角色职责

- **`NovelDirector`**：唯一持有 `novel_state` 写入权。负责流程推进、断点恢复、审核决策（通过/修复/重写）、Agent 调度。
- **`BrainstormAgent`**：接收原始设定，输出小说总纲和世界观文档。
- **`VolumePlannerAgent`**：接收总纲 + 当前世界状态，输出卷级大纲；审核未达标时循环修改或重写。
- **`ContextAgent`**：查询数据库，组装包含卷级大纲、世界观、设定、风格画像、相关实体、时间/空间线、伏笔的完整上下文包。
- **`WriterAgent`**：接收上下文包，输出正文草稿。要求：限人物视角叙事、禁止上帝视角、弱 AI 味。
- **`CriticAgent`**：深度审核。规则引擎（40%）+ LLM 软性评分（60%）。返回结构化评分和修改意见。
- **`EditorAgent`**：精修润色。去 AI 味、格式清理、微调语句，不做大改。
- **`FastReviewer`**：精修后的快速二审。4 个维度，总分 100，门槛 85 分。
- **`LibrarianAgent`**：从精修稿中自动提取时间/空间进展、人物状态变更、新实体、伏笔回收/埋下，写入数据库。

### 6.2 FastReviewer 细则

**评审维度（总分 100，门槛 85）：**
1. **编辑是否引入新错误**（设定矛盾、人物性格突变、剧情断档）—— 30%
2. **AI 味/机械味残留** —— 25%
3. **格式合规**（无 markdown 标签、无英文字符、标点规范）—— 20%
4. **章节钩子保留度**（精修是否弱化或丢失了原有钩子）—— 25%

**未通过处理：**
- 85-89 分：退回 `EditorAgent` 针对性修正
- <85 分：退回 `WriterAgent` 重新生成草稿

---

## 7. 核心数据流（单章写作示例）

1. **NovelDirector 读取 `novel_state`**
   - 确定当前阶段，如 `writing_chapter_47_draft`

2. **ContextAgent 准备上下文**
   - 读取本章在卷级大纲中的计划
   - 查询 `novel_documents`：世界观、核心设定、风格画像
   - 查询相关实体（出场人物、地点、物品）
   - 查询当前时间/空间状态
   - 查询 pending 伏笔（需回收或埋下）
   - 组装上下文包返回 Director

3. **WriterAgent 生成草稿**
   - 接收上下文包，输出正文草稿

4. **CriticAgent 深度审核**
   - 规则引擎检查 + LLM 软性评分
   - 返回总分和各维度得分、修改意见

5. **NovelDirector 决策**
   - ≥90 分 → 进入 `EditorAgent`
   - 80-89 分 → 退回 `WriterAgent` 修改（渐进式修复）
   - <80 分 → 触发重写条件
   - 更新 `novel_state`

6. **EditorAgent 精修**
   - 输出精修稿

7. **FastReviewer 快速二审**
   - ≥85 分 → 进入 `LibrarianAgent`
   - <85 分 → 退回 `WriterAgent` 重写
   - 更新 `novel_state`

8. **LibrarianAgent 提取入库（全自动）**
   - 新人物/物品/地点/概念 → `entities` + `entity_versions`
   - 时间线进展 → `timeline`
   - 空间线变化 → 更新相关实体的位置
   - 伏笔回收/埋下 → `foreshadowings`
   - 人物状态变更 → 新增 `entity_versions`

9. **NovelDirector 校验与收尾**
   - 将精修稿写入 `chapters` 表的 `polished_text`
   - 同步生成纯 Markdown 文件（无 YAML frontmatter）
   - 更新 `novel_state` 为下一章的 `context_preparation`

---

## 8. 断点续作机制

**权威状态存储在 `novel_state` 表中。**

`checkpoint_data` 包含：
- `current_volume_plan`：当前卷级大纲
- `current_chapter_plan`：本章计划
- `pending_inputs`：当前阶段等待的输入（如 WriterAgent 的上下文包）
- `intermediate_results`：上一阶段的输出（如草稿、审核意见）
- `retry_count`：当前阶段的修复/重试次数
- `last_error`：如果上次运行报错，记录错误信息

**恢复流程：**
1. 读取 `novel_state` 获取 `current_phase`
2. 恢复 `checkpoint_data` 中的上下文
3. 从该阶段的入口继续执行
4. 若上一阶段报错，根据 `last_error` 决定重试或回退

---

## 9. 审核评分机制

### 9.1 卷级大纲审核

**评分维度：** 大纲符合度、人物剧情符合度、爽点分布、伏笔管理、章节钩子、追读力。
- **≥85 分**：进入正文写作
- **60-84 分**：根据意见修改后再审
- **<60 分**：重写

### 9.2 章节草稿深度审核

**规则引擎（40%）：**
- 设定符合性：新出场实体是否在数据库中
- 时间/空间一致性：人物是否在同一时间出现在两个地点
- 伏笔状态检查：该回收的伏笔是否回收、该埋下的是否埋下

**LLM 软性评分（60%）：**
- 剧情推进是否合理
- 文笔优美度
- 章节钩子是否勾人
- 追读力
- AI 味/机械味

**总分 100，门槛 90 分。**

### 9.3 快速二审（精修后）

见 6.2 节，门槛 85 分。

### 9.4 10 章批量 review

每完成 10 章，系统对最近 10 章进行批量审核，维度：剧情合理性、设定符合性、爽点分布、追读力。
- **<85 分的章节**：标记为待修复，全部修复完毕后继续后续写作。

---

## 10. 技术栈

- **后端语言**：Python 3.11+
- **数据库**：PostgreSQL 16 + pgvector 扩展
- **ORM/数据访问**：SQLAlchemy + Alembic（ migrations ）
- **MCP Server**：官方 MCP Python SDK
- **REST API**：FastAPI（轻量、异步友好）
- **LLM 调用**：Anthropic SDK / 其他兼容接口
- **文件副本**：本地纯 Markdown 文件，按 `novels/{novel_id}/chapters/vol_X_ch_Y.md` 组织

---

## 11. 风险与未来扩展

### 已知风险

1. **LibrarianAgent 的全自动提取准确率**：这是整个闭环的潜在瓶颈。如果提取遗漏或错误，幻觉问题会从数据层重新引入。初期需要严格校验逻辑兜底。
2. **LLM 评分一致性**：软性维度（文笔、追读力）在不同模型版本或 prompt 微调下可能波动。建议为评分 prompt 建立基线测试集。
3. **长文本的向量嵌入成本**：整章正文做嵌入费用较高。建议只对 `novel_documents` 和实体摘要做向量索引，章节本身走结构化查询。

### 未来扩展

1. **图数据库迁移**：当关系推理需求变复杂时，可将 `entity_relationships` 同步到图数据库（如 Neo4j），而不破坏现有表结构。
2. **动态风格画像**：在 A（离线静态画像）跑通后，可叠加动态修正层，从已写章节中学习这本小说自身形成的独特文风。
3. **Web UI 可视化**：利用 REST API 构建时间线、人物关系图、伏笔状态看板。
