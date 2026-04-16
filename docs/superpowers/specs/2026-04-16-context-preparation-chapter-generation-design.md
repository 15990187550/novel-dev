# 上下文准备与章节生成引擎 — 设计文档

**日期：** 2026-04-16  
**主题：** 第三子系统：ContextAgent + WriterAgent  
**状态：** 待实现  
**依赖：** 核心数据层（已完成）、设定学习与风格提取引擎（已完成）

---

## 1. 目标

本系统负责：
1. **ContextAgent**：根据当前小说状态与章节计划，从数据库中检索并组装一个结构化的「写作上下文包」（ChapterContext）。
2. **WriterAgent**：接收 ChapterContext，按章节计划中的节拍逐段生成低 AI 味、有强读感的章节草稿（raw_draft），并写入 `chapters` 表。

本系统边界：**仅包含上下文准备与初稿生成**。审阅、编辑、精修（CriticAgent、EditorAgent、FastReviewer、LibrarianAgent）归属第四子系统。

---

## 2. 整体架构

```
NovelState (current_phase = CONTEXT_PREPARATION)
    │
    ▼
┌─────────────────────────────────┐
│ ContextAgent                    │
│  • 读取 checkpoint_data 中的    │
│    current_chapter_plan         │
│  • 分析节拍，识别出场实体/地点   │
│  • 检索 entities / spaceline    │
│    / timeline / foreshadowings  │
│  • 组装 ChapterContext          │
│  • 缓存到 checkpoint_data       │
└─────────────────────────────────┘
    │
    ▼
NovelDirector 推进到 DRAFTING
    │
    ▼
┌─────────────────────────────────┐
│ WriterAgent                     │
│  • 加载 style_profile + 参考片段 │
│  • 按 beats 逐段生成             │
│  • 声景模仿去 AI 味              │
│  • 角度重写（可选）              │
│  • 合并为 raw_draft              │
│  • 生成 draft_metadata           │
└─────────────────────────────────┘
    │
    ▼
写入 Chapter.raw_draft
NovelDirector 推进到 REVIEWING
```

---

## 3. ContextAgent

### 3.1 职责

根据 `novel_id`、`current_volume_id`、`current_chapter_id` 及 `checkpoint_data` 中的卷章计划，从数据库检索相关数据，组装成 `ChapterContext`。

### 3.2 输入

- `novel_id: str`
- `chapter_id: str`
- 依赖数据库表：`novel_state`、`novel_documents`、`entities`、`entity_versions`、`spaceline`、`timeline`、`foreshadowings`、`chapters`

### 3.3 核心流程

**步骤 1：读取并校验章节计划**
- 从 `NovelState.checkpoint_data["current_chapter_plan"]` 读取章节计划
- 若缺失，抛出 `400` 错误，提示需先完成卷章规划
- 解析出 `beats` 列表、目标字数、标题、本章核心情绪

**步骤 2：智能检索相关实体**
- 用轻量 LLM 调用分析 `chapter_plan`，输出计划出场的人物、势力、物品、地点名称列表
- 查询 `entities` + `entity_versions`：匹配名称且 `is_active=True`（关系表）或最新版本的实体
- 查询 `spaceline`：匹配地点及其父级地点，构建地点上下文树

**步骤 3：检索时间线与伏笔**
- 查询 `timeline`：取本章时间 tick 前后各 3 条叙事事件（或按 `anchor_chapter_id` 关联）
- 查询 `foreshadowings`：
  - `回收状态 = "pending"`
  - 且满足以下条件之一：`埋下_time_tick` 接近本章时间、`埋下_location_id` 匹配本章地点、`相关人物_ids` 与本章出场人物有交集
  - 这些伏笔标记为「待埋入」或「待回收」

**步骤 4：读取风格与世界观摘要**
- 从 `novel_documents(doc_type="style_profile")` 取 `version` 最新的记录（若 `checkpoint_data` 有 `active_style_profile_version` 则按该版本）
- 从 `novel_documents(doc_type="worldview")` 取世界观摘要
- 从 `chapters` 取上一章（`chapter_number - 1`）的 `raw_draft` 或 `polished_text` 的前 500 字摘要（可用 LLM 提取关键剧情节点，或简单取末尾）

**步骤 5：组装 ChapterContext**

输出结构：

```json
{
  "chapter_plan": {
    "chapter_number": 5,
    "title": "青云试炼",
    "target_word_count": 3500,
    "beats": [
      {
        "summary": "林风踏入试炼场，感受到压迫气氛",
        "target_mood": "压抑紧张",
        "key_entities": ["林风", "青云宗长老"],
        "foreshadowings_to_embed": ["伏笔-001"]
      }
    ]
  },
  "style_profile": { ... },
  "worldview_summary": "天玄大陆修炼体系概述",
  "active_entities": [
    {
      "entity_id": "ent-001",
      "name": "林风",
      "type": "character",
      "current_state": "炼气三层，隐忍低调"
    }
  ],
  "location_context": {
    "current": "青云宗试炼场",
    "parent": "青云宗外门",
    "narrative": "云雾缭绕的石台，四周是万丈深渊"
  },
  "timeline_events": [
    {"tick": 12, "narrative": "林风入门"},
    {"tick": 15, "narrative": "外门大比开始"}
  ],
  "pending_foreshadowings": [
    {
      "id": "伏笔-001",
      "content": "残缺玉佩在关键时刻会发出微光",
      "role_in_chapter": "埋下"
    }
  ],
  "previous_chapter_summary": "上一章林风突破炼气三层，准备参加外门大比"
}
```

**步骤 6：缓存**
- 将 `ChapterContext` 序列化为 JSON 后写入 `NovelState.checkpoint_data["chapter_context"]`
- 更新 `checkpoint_data["drafting_progress"]` 为初始状态：`{"beat_index": 0, "total_beats": N}`

### 3.4 性能与扩展

- 实体检索先用 LLM 提取关键词，再精确匹配数据库，避免全表扫描。
- 若未来实体数量极大，可为 `entities.name` 和 `entities.type` 加联合索引。

---

## 4. WriterAgent

### 4.1 职责

接收 `ChapterContext`，按 `beats` 逐段生成正文，最终输出完整 `raw_draft`。核心要求是**低 AI 味、强读感**。

### 4.2 核心原则：声景模仿

不采用「禁止清单」式的机械校验，而是通过**参考片段 + 声景引导**让 LLM 自然沉浸到目标文风里。

### 4.3 核心流程

**步骤 1：加载风格画像与参考片段**
- 从 `ChapterContext.style_profile` 读取 `style_config`
- 从 `novel_documents` 或原始风格样本库中，**动态检索 1~2 段与当前 beat 情绪/场景最相似的原文片段**（如打斗、对话、内心独白）
- 将参考片段注入 prompt

**步骤 2：逐 beat 生成**

每个 beat 的 prompt 结构：

1. **剧情目标**：本 beat 要达成的场景、冲突、情绪转折
2. **声景引导**：把风格要求翻译成感官目标和情绪场，例如：「闷热，压抑，信息密度低，多用环境白描烘托焦躁」
3. **参考片段**：1~2 段原文，供 LLM 模仿节奏和呼吸
4. **上下文信息**：出场实体状态、地点氛围、时间线压力、待埋伏笔
5. **衔接文本**：上一 beat 末尾的 800 字（running draft），保证情绪和动作连贯
6. **输出要求**：纯文本段落，禁止总结性上帝视角

**步骤 3：角度重写（去 AI 味）**
- 某 beat 生成后，若检测到明显的 AI 味（通过轻量启发式规则：连续出现「然而」「突然」「只见」超过阈值，或存在大量抽象情绪标签），触发一次「角度重写」：
  - 提取该 beat 的核心动作/对话
  - 换一个焦距重写（如从远景概括切成近景跟拍，或从叙述者总结切成人物感官流）
  - 取两次生成中读感更好的一版
- 这不是机械修正，而是像真人作家一样「删了重写过」。

**步骤 4：进度缓存**
- 每完成一个 beat，将当前 draft 内容追加到 `checkpoint_data["drafting_progress"]`：
  ```json
  {
    "beat_index": 2,
    "total_beats": 5,
    "current_word_count": 2100
  }
  ```
- 这样支持意外中断后恢复。

**步骤 5：合并与生成 draft_metadata**

所有 beats 完成后，拼接为完整 `raw_draft`，并生成：

```json
{
  "total_words": 3680,
  "beat_coverage": [
    {"beat_index": 0, "word_count": 820},
    {"beat_index": 1, "word_count": 910}
  ],
  "style_violations": [
    "Beat 3 出现连续 4 个长从句，建议拆分"
  ],
  "embedded_foreshadowings": ["伏笔-001", "伏笔-003"]
}
```

**步骤 6：写入数据库**
- `Chapter.raw_draft = raw_draft`
- `Chapter.status = "drafted"`
- `NovelState.checkpoint_data["draft_metadata"] = draft_metadata`
- `NovelDirector` 推进状态到 `REVIEWING`

### 4.4 去 AI 味的具体策略

| 策略 | 说明 |
|---|---|
| **参考片段模仿** | 用原文节奏带动新文本，而不是背诵规则 |
| **声景引导** | 把风格要求翻译为感官和情绪场 |
| **视角切换重写** | 从叙述者切换到人物感官，打破概括性陈述 |
| **对话极简标签** | 用动作和神态替代「他说道」「她回答」 |
| **限知视角禁令** | 禁止总结性上帝视角，所有信息必须通过人物感知呈现 |

---

## 5. 数据流与状态管理

### 5.1 状态流转

```
CONTEXT_PREPARATION
    │ POST /context
    ▼
DRAFTING
    │ POST /draft
    ▼
REVIEWING
```

### 5.2 checkpoint_data 新增字段

```json
{
  "current_volume_plan": { ... },
  "current_chapter_plan": { ... },
  "chapter_context": { ... },
  "drafting_progress": {
    "beat_index": 0,
    "total_beats": 5,
    "current_word_count": 0
  },
  "draft_metadata": { ... },
  "drafting_error": null
}
```

---

## 6. API 接口

在现有 FastAPI `routes.py` 中新增：

| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/novels/{novel_id}/chapters/{chapter_id}/context` | POST | 触发 ContextAgent，组装并缓存上下文包 |
| `/api/novels/{novel_id}/chapters/{chapter_id}/draft` | POST | 触发 WriterAgent，生成本章草稿 |
| `/api/novels/{novel_id}/chapters/{chapter_id}/draft` | GET | 查询草稿状态、进度、已生成内容 |

### 6.1 POST /context

- 校验 `current_phase == CONTEXT_PREPARATION`
- 调用 `ContextAgent.assemble(novel_id, chapter_id)`
- 写入 `checkpoint_data["chapter_context"]`
- `NovelDirector` 推进到 `DRAFTING`
- 返回 `ChapterContext` 摘要（不含完整实体详情，避免响应过大）

### 6.2 POST /draft

- 校验 `current_phase == DRAFTING`
- 从 `checkpoint_data` 读取 `chapter_context`
- 调用 `WriterAgent.write(context, chapter_id)`
- 写入 `Chapter.raw_draft`，更新 `status = "drafted"`
- `NovelDirector` 推进到 `REVIEWING`
- 返回 `draft_metadata`

### 6.3 GET /draft

- 返回 `Chapter.raw_draft`（若已生成）
- 返回 `checkpoint_data["drafting_progress"]` 和 `draft_metadata`

---

## 7. MCP 工具

在现有 MCP Server 中新增：

| 工具名 | 说明 |
|---|---|
| `prepare_chapter_context` | 调用 POST /context |
| `generate_chapter_draft` | 调用 POST /draft |
| `get_chapter_draft_status` | 调用 GET /draft |

---

## 8. 数据模型（Pydantic，不新增数据库表）

```python
class BeatPlan(BaseModel):
    summary: str
    target_mood: str
    key_entities: List[str] = Field(default_factory=list)
    foreshadowings_to_embed: List[str] = Field(default_factory=list)


class ChapterPlan(BaseModel):
    chapter_number: int
    title: Optional[str] = None
    target_word_count: int
    beats: List[BeatPlan]


class EntityState(BaseModel):
    entity_id: str
    name: str
    type: str
    current_state: str


class LocationContext(BaseModel):
    current: str
    parent: Optional[str] = None
    narrative: Optional[str] = None


class ChapterContext(BaseModel):
    chapter_plan: ChapterPlan
    style_profile: dict
    worldview_summary: str
    active_entities: List[EntityState]
    location_context: LocationContext
    timeline_events: List[dict]
    pending_foreshadowings: List[dict]
    previous_chapter_summary: Optional[str] = None


class DraftMetadata(BaseModel):
    total_words: int
    beat_coverage: List[dict]
    style_violations: List[str]
    embedded_foreshadowings: List[str]
```

---

## 9. 错误处理

| 场景 | 处理 |
|---|---|
| `current_chapter_plan` 缺失 | 返回 400，提示需先完成卷章规划 |
| `style_profile` 缺失 | 返回 400，提示需先上传风格样本 |
| LLM 调用失败 | 重试 2 次，仍失败则写入 `checkpoint_data["drafting_error"]`，状态不推进，返回 503 |
| 某 beat 字数严重偏离（<50% 或 >200%） | 记录 warning 到 `draft_metadata`，不中断生成 |
| 实体检索为空 | 记录 warning，继续生成（可能计划中的实体尚未录入） |

---

## 10. 测试策略

### 10.1 单元测试

- **ContextAgent**：
  - 给定 `chapter_plan` 和模拟数据库，验证 `active_entities` 和 `pending_foreshadowings` 过滤正确
  - 验证缺失 `current_chapter_plan` 或 `style_profile` 时抛出预期异常

- **WriterAgent**：
  - 给定 2-beat 的简化 `ChapterContext`，验证输出草稿按 beats 拼接正确
  - 验证 `draft_metadata` 字数统计和 `beat_coverage` 正确
  - 验证 `checkpoint_data["drafting_progress"]` 被正确更新

- **API 状态校验**：
  - 验证 `CONTEXT_PREPARATION` → `DRAFTING` → `REVIEWING` 合法流转
  - 验证错误阶段调用时返回 400

### 10.2 集成测试

- 预置完整数据：小说、风格画像、世界观、实体、时间线、伏笔
- 写入 `current_chapter_plan` 到 `checkpoint_data`
- POST `/context` → 断言摘要返回、状态变为 `DRAFTING`
- POST `/draft` → 断言 `raw_draft` 非空、`status = "drafted"`、状态变为 `REVIEWING`
- 断言 `draft_metadata.embedded_foreshadowings` 包含预期伏笔

### 10.3 LLM Mock 策略

- 所有测试对 LLM 调用做 mock，返回预设文本
- 集成测试中增加一个「风格模仿」测试：给 mock 一段参考片段，验证输出句长分布与参考片段相近

---

## 11. 风险与未来扩展

1. **参考片段检索精度**：当前按情绪和场景做简单匹配，未来可扩展为三维匹配（实体 + 场景 + 情绪）。
2. **上下文窗口限制**：超长章节（>1 万字）的 running draft 回传可能超限，未来可考虑只回传情节摘要而非原文。
3. **伏笔回收的自动化程度**：当前由 ContextAgent 做规则匹配，未来可引入 LLM 判断哪些伏笔适合在本章回收。
4. **角度重写的成本**：每个 beat 多一次 LLM 调用，token 成本翻倍。未来可改为只在检测到高 AI 味时才触发。
