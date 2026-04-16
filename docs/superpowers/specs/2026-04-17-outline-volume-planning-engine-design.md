# 大纲与卷级规划引擎 — 设计文档

**日期：** 2026-04-17  
**主题：** 第 6 子系统：BrainstormAgent + VolumePlannerAgent  
**状态：** 待实现  
**依赖：** 核心数据层、设定学习与风格提取引擎

---

## 1. 目标

本系统是全自动长篇小说流水线的**起点**，负责从已确认的世界观、设定文档中生成：

1. **`BrainstormAgent`**：小说总纲（`synopsis`），包含主线剧情、人物弧光、核心冲突、高潮节点、预计总卷数和总章数。
2. **`VolumePlannerAgent`**：卷级大纲（`volume_plan`），将总纲动态拆解为带子节拍的章节计划，支持基于已归档正文的世界状态回读进行动态调整。

产出将写入 `novel_documents` 及 `novel_state.checkpoint_data`，供 `ContextAgent` 和 `NovelDirector` 消费。

---

## 2. 整体架构

```
小说初始化
    │
    ▼
POST /brainstorm
    │
    ▼
┌─────────────────────────────────────────┐
│ BrainstormAgent                         │
│  • 读取 worldview/setting/concept       │
│  • 生成 synopsis_text (markdown)        │
│  • 生成 synopsis_data (结构化 JSON)     │
│  • 写入 novel_documents + checkpoint    │
└─────────────────────────────────────────┘
    │
    ▼
NovelDirector → VOLUME_PLANNING
    │
    ▼
POST /volume_plan
    │
    ▼
┌─────────────────────────────────────────┐
│ VolumePlannerAgent                      │
│  • 读取 synopsis_data                   │
│  • 若 volume_number > 1：               │
│    读取已归档章节摘要 + 当前 entity/    │
│    timeline/foreshadowing 状态          │
│  • 生成 VolumePlan (含 per-chapter      │
│    beats)                               │
│  • 自审评分（6 维度）                    │
│     ├─ < 60 或 60-84（未通过）          │
│     │   → revise 后再审（最多 3 次）    │
│     └─ ≥ 85 → 通过                      │
│  • 写入 current_volume_plan +           │
│    current_chapter_plan                 │
└─────────────────────────────────────────┘
    │
    ▼
NovelDirector → CONTEXT_PREPARATION
```

**设计原则：**
- `BrainstormAgent` 是小说生命周期的**入口点**，不依赖 `can_transition` 的前置状态检查。
- `VolumePlannerAgent` 是**全自动**的，内置自审与重试 guard，不需要人工审批节点。
- 所有状态推进由 `NovelDirector` 统一负责。

---

## 3. Pydantic Schemas

**文件：** `src/novel_dev/schemas/outline.py`

```python
from typing import List, Optional
from pydantic import BaseModel, Field

from novel_dev.schemas.context import BeatPlan


class CharacterArc(BaseModel):
    name: str
    arc_summary: str
    key_turning_points: List[str] = Field(default_factory=list)


class PlotMilestone(BaseModel):
    act: str
    summary: str
    climax_event: Optional[str] = None


class SynopsisData(BaseModel):
    title: str
    logline: str
    core_conflict: str
    themes: List[str] = Field(default_factory=list)
    character_arcs: List[CharacterArc] = Field(default_factory=list)
    milestones: List[PlotMilestone] = Field(default_factory=list)
    estimated_volumes: int
    estimated_total_chapters: int
    estimated_total_words: int


class VolumeBeat(BaseModel):
    chapter_id: str
    chapter_number: int
    title: str
    summary: str
    target_word_count: int
    target_mood: str
    key_entities: List[str] = Field(default_factory=list)
    foreshadowings_to_embed: List[str] = Field(default_factory=list)
    foreshadowings_to_recover: List[str] = Field(default_factory=list)
    beats: List[BeatPlan] = Field(default_factory=list)


class VolumePlan(BaseModel):
    volume_id: str
    volume_number: int
    title: str
    summary: str
    total_chapters: int
    estimated_total_words: int
    chapters: List[VolumeBeat] = Field(default_factory=list)


class VolumeScoreResult(BaseModel):
    overall: int
    outline_fidelity: int
    character_plot_alignment: int
    hook_distribution: int
    foreshadowing_management: int
    chapter_hooks: int
    page_turning: int
    summary_feedback: str
```

**关键约定：**
- `VolumePlan` 使用 `chapters` 作为字段名（而非 `beats`），与现有 `NovelDirector._continue_to_next_chapter()` 兼容。
- `VolumeBeat` 显式包含 `chapter_id`，用于 `NovelDirector` 推进状态时写入 `current_chapter_id`。
- `VolumeBeat` 的卷级伏笔（`foreshadowings_to_embed`）在转换为 `current_chapter_plan` 时，若 `beats[0]` 未指定伏笔，则自动合并到第一个子节拍。

---

## 4. BrainstormAgent 详细设计

**文件：** `src/novel_dev/agents/brainstorm_agent.py`

### 4.1 职责
1. 读取 `novel_documents` 中的 `worldview`、`setting`、`concept` 类型文档（**不读取 `style_profile`**）。
2. 将设定信息合成为小说总纲。
3. 输出 `synopsis_text`（Markdown 文本）和 `synopsis_data`（结构化 JSON）。
4. 将 `synopsis_text` 写入 `novel_documents(doc_type="synopsis")`。
5. 将 `synopsis_data` 写入 `checkpoint_data["synopsis_data"]`，`synopsis_doc_id` 作为调试字段写入。
6. 通过 `NovelDirector` 将状态推进到 `VOLUME_PLANNING`。

### 4.2 输入
- `novel_id: str`
- 依赖表：`novel_documents(doc_type in ["worldview", "setting", "concept"])`

### 4.3 输出示例

**synopsis_text (Markdown):**
```markdown
# 天玄纪元

## 一句话梗概
林风因家族灭门之仇拜入青云宗...

## 核心冲突
内部：隐忍 vs 复仇；外部：正道 vs 魔宗

## 人物弧光
### 林风
- 起点：炼气三层外门弟子
- 转折：筑基期发现玉佩与身世关联
- 终点：元婴期登顶

## 剧情里程碑
### 第一幕·入门（第 1-3 卷）
青云试炼、外门大比、残缺玉佩觉醒...
```

**synopsis_data (JSON):**
```json
{
  "title": "天玄纪元",
  "logline": "林风因家族灭门之仇拜入青云宗...",
  "core_conflict": "隐忍 vs 复仇，正道 vs 魔宗",
  "themes": ["复仇", "成长", "救赎"],
  "character_arcs": [
    {"name": "林风", "arc_summary": "...", "key_turning_points": ["玉佩觉醒", "筑基", "元婴"]}
  ],
  "milestones": [
    {"act": "第一幕", "summary": "入门试炼", "climax_event": "外门大比夺冠"}
  ],
  "estimated_volumes": 12,
  "estimated_total_chapters": 360,
  "estimated_total_words": 1080000
}
```

### 4.4 状态推进

```python
checkpoint["synopsis_data"] = synopsis_data.model_dump()
checkpoint["synopsis_doc_id"] = doc_id
await director.save_checkpoint(
    novel_id,
    phase=Phase.VOLUME_PLANNING,
    checkpoint_data=checkpoint,
    current_volume_id=None,
    current_chapter_id=None,
)
```

**说明：** `BrainstormAgent` 不校验 `can_transition`，允许从空状态直接创建 `novel_state`。

---

## 5. VolumePlannerAgent 详细设计

**文件：** `src/novel_dev/agents/volume_planner.py`

### 5.1 职责
1. 读取 `checkpoint_data["synopsis_data"]`。
2. 若 `volume_number > 1`，读取已归档的上一卷章节摘要、当前 `entities`、`timeline`、`foreshadowings` 状态。
3. 生成 `VolumePlan`（含 `volume_id`、`chapters`、`estimated_total_words` 等）。
4. 对 `VolumePlan` 执行自审评分（6 维度）。
5. 根据评分决策：
   - `overall >= 85`：通过
   - `< 85`：根据 `summary_feedback` 执行 revise 后再审（最多 3 次）
6. 将通过的 `VolumePlan` 写入 `checkpoint_data["current_volume_plan"]` 和 `novel_documents(doc_type="volume_plan")`。
7. 提取 `volume_plan.chapters[0]` 为 `current_chapter_plan`（执行伏笔合并规则后）写入 `checkpoint_data`。
8. 推进状态到 `CONTEXT_PREPARATION`。

### 5.2 输入
- `novel_id: str`
- `volume_number: Optional[int]`（未指定时自动推算：从 `checkpoint["current_volume_id"]` 提取 `vol_N` 的 N，或默认 1）
- 依赖：`synopsis_data`、已归档章节、`entities`、`entity_versions`、`timeline`、`foreshadowings`

### 5.3 动态世界状态回读

当 `volume_number > 1` 时，Agent 自动查询：

| 查询 | 来源 | 用途 |
|------|------|------|
| 上一卷最后 3 章 `polished_text` | `chapters` 表 | 提取剧情摘要，确定本卷起点 |
| 核心实体最新版本 | `entities` + `entity_versions` | 确认人物境界、势力格局变化 |
| 当前 timeline tick | `timeline` | 确定本卷起始时间刻度 |
| pending / recovered 伏笔 | `foreshadowings` | 规划伏笔回收与埋下 |

### 5.4 自审评分细则

**6 维度及权重：**

| 维度 | 权重 | 说明 |
|------|------|------|
| `outline_fidelity` | 1.0 | 是否符合总纲设定的剧情走向 |
| `character_plot_alignment` | 1.2 | 人物行为是否与其当前版本状态一致 |
| `hook_distribution` | 1.0 | 爽点/高潮是否在全卷均匀分布 |
| `foreshadowing_management` | 1.2 | 伏笔埋下与回收是否逻辑自洽 |
| `chapter_hooks` | 1.0 | 每章结尾是否有有效钩子 |
| `page_turning` | 1.2 | 整体追读力与节奏把控 |

- `overall` = 加权平均分（四舍五入为整数）
- `overall >= 85` → 通过
- `overall < 85` → 根据 `summary_feedback` revise 后再审

**Retry Guard：**
- `checkpoint_data["volume_plan_attempt_count"]` 每次未通过时 +1
- 达到 3 次仍失败则抛出 `RuntimeError("Max volume plan attempts exceeded")`，状态保持 `VOLUME_PLANNING`
- 通过后该计数清零

### 5.5 输出与状态推进

```python
checkpoint["current_volume_plan"] = volume_plan.model_dump()
checkpoint["current_chapter_plan"] = self._extract_chapter_plan(volume_plan.chapters[0])
checkpoint["volume_plan_attempt_count"] = 0

await director.save_checkpoint(
    novel_id,
    phase=Phase.CONTEXT_PREPARATION,
    checkpoint_data=checkpoint,
    current_volume_id=volume_plan.volume_id,
    current_chapter_id=volume_plan.chapters[0].chapter_id,
)
```

### 5.6 `VolumeBeat` → `ChapterPlan` 转换规则

```python
def _extract_chapter_plan(self, volume_beat: VolumeBeat) -> dict:
    chapter_plan = volume_beat.model_dump()
    if volume_beat.foreshadowings_to_embed and volume_beat.beats:
        if not volume_beat.beats[0].foreshadowings_to_embed:
            volume_beat.beats[0].foreshadowings_to_embed = volume_beat.foreshadowings_to_embed[:]
    chapter_plan["beats"] = [b.model_dump() for b in volume_beat.beats]
    return chapter_plan
```

---

## 6. NovelDirector 集成

**文件：** `src/novel_dev/agents/director.py`

### 6.1 状态机修复

现有 `VALID_TRANSITIONS` 缺少 `COMPLETED → VOLUME_PLANNING`，需要修改为：

```python
VALID_TRANSITIONS = {
    Phase.VOLUME_PLANNING: [Phase.CONTEXT_PREPARATION],
    Phase.CONTEXT_PREPARATION: [Phase.DRAFTING],
    Phase.DRAFTING: [Phase.REVIEWING],
    Phase.REVIEWING: [Phase.EDITING, Phase.DRAFTING],
    Phase.EDITING: [Phase.FAST_REVIEWING],
    Phase.FAST_REVIEWING: [Phase.LIBRARIAN, Phase.DRAFTING, Phase.EDITING],
    Phase.LIBRARIAN: [Phase.COMPLETED],
    Phase.COMPLETED: [Phase.CONTEXT_PREPARATION, Phase.VOLUME_PLANNING],
}
```

### 6.2 `advance()` 扩展

```python
async def advance(self, novel_id: str) -> NovelState:
    state = await self.resume(novel_id)
    if not state:
        raise ValueError(f"Novel state not found for {novel_id}")
    current = Phase(state.current_phase)

    if current == Phase.VOLUME_PLANNING:
        return await self._run_volume_planner(state)
    elif current == Phase.REVIEWING:
        return await self._run_critic(state)
    elif current == Phase.EDITING:
        return await self._run_editor(state)
    elif current == Phase.FAST_REVIEWING:
        return await self._run_fast_review(state)
    elif current == Phase.LIBRARIAN:
        return await self._run_librarian(state)
    else:
        raise ValueError(f"Cannot auto-advance from {current}")
```

### 6.3 `_run_volume_planner()`

```python
async def _run_volume_planner(self, state: NovelState) -> NovelState:
    from novel_dev.agents.volume_planner import VolumePlannerAgent
    agent = VolumePlannerAgent(self.session)
    await agent.plan(state.novel_id)
    return await self.resume(state.novel_id)
```

---

## 7. API 接口

**文件：** `src/novel_dev/api/routes.py`

| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/novels/{novel_id}/brainstorm` | POST | 触发 BrainstormAgent，生成总纲 |
| `/api/novels/{novel_id}/volume_plan` | POST | 触发 VolumePlannerAgent，生成卷纲 |
| `/api/novels/{novel_id}/synopsis` | GET | 查询当前总纲文本与结构化数据 |
| `/api/novels/{novel_id}/volume_plan` | GET | 查询当前卷级大纲 |

### 7.1 POST /brainstorm

- 调用 `BrainstormAgent.brainstorm(novel_id)`
- 写入 `novel_documents(doc_type="synopsis")` 和 `checkpoint_data`
- 推进状态到 `VOLUME_PLANNING`
- 返回 `synopsis_data` 摘要

### 7.2 POST /volume_plan

Request body（可选）：
```json
{
  "volume_number": 1
}
```

- 校验 `current_phase == VOLUME_PLANNING`
- 调用 `VolumePlannerAgent.plan(novel_id, volume_number)`
- 自审循环（最多 3 次）
- 通过后写入 `current_volume_plan`、`current_chapter_plan`
- 推进状态到 `CONTEXT_PREPARATION`
- 返回 `VolumePlan` 摘要

### 7.3 GET /synopsis

- 查询 `novel_documents(doc_type="synopsis")` 最新版本
- 返回 `content`、`synopsis_data`（从 `checkpoint_data` 读取）
- 若总纲不存在返回 404

### 7.4 GET /volume_plan

- 从 `checkpoint_data["current_volume_plan"]` 读取
- 若不存在返回 404

---

## 8. MCP 工具

**文件：** `src/novel_dev/mcp_server/server.py`

新增 4 个工具：

| 工具名 | 说明 |
|---|---|
| `brainstorm_novel` | 生成小说总纲 |
| `plan_volume` | 生成指定卷的大纲 |
| `get_synopsis` | 获取当前总纲 |
| `get_volume_plan` | 获取当前卷级大纲 |

---

## 9. 错误处理

| 场景 | 处理 |
|---|---|
| Brainstorm 时找不到设定文档 | 返回 400，提示需先上传设定文件 |
| VolumePlanner 时 `synopsis_data` 缺失 | 返回 400，提示需先调用 Brainstorm |
| VolumePlanner 自审 3 次均失败 | 抛出 `RuntimeError`，状态保持 `VOLUME_PLANNING`，`checkpoint_data["volume_plan_attempt_count"]=3` |
| POST /volume_plan 时 phase 不是 `VOLUME_PLANNING` | 返回 400 |
| LLM 调用失败 | 重试 2 次，仍失败则返回 503，状态不推进 |

---

## 10. 测试策略

### 10.1 单元测试

**`tests/test_agents/test_brainstorm_agent.py`**
- 成功生成总纲并写入 `novel_documents` 和 `checkpoint_data`
- 从空状态创建 `novel_state` 并推进到 `VOLUME_PLANNING`
- 缺失设定文档时抛出 `ValueError`

**`tests/test_agents/test_volume_planner.py`**
- 成功生成 `VolumePlan` 并通过自审
- 评分 `< 85` 时触发 revise 并重试
- 3 次失败后抛出 `RuntimeError`，状态保持 `VOLUME_PLANNING`
- `volume_number > 1` 时读取已归档章节和实体状态
- `VolumeBeat` → `ChapterPlan` 转换时正确合并伏笔

### 10.2 集成测试

**`tests/test_api/test_outline_routes.py`**
- POST /brainstorm → 返回 synopsis_data，状态变为 `VOLUME_PLANNING`
- POST /volume_plan → 返回 volume_plan，状态变为 `CONTEXT_PREPARATION`
- GET /synopsis → 返回正确内容
- GET /volume_plan → 返回正确内容

**`tests/test_agents/test_director_volume_planning.py`**
- `advance()` 从 `VOLUME_PLANNING` 自动推进到 `CONTEXT_PREPARATION`
- `COMPLETED → VOLUME_PLANNING` 的合法流转

**`tests/test_mcp_server.py`**（更新）
- 新增 4 个 MCP 工具的注册与行为测试

### 10.3 LLM Mock 策略

- 所有测试对 LLM 调用做 mock
- `BrainstormAgent` mock 返回固定 Markdown + JSON
- `VolumePlannerAgent` mock 返回固定 `VolumePlan`，自审通过

---

## 11. 文件映射

| 文件 | 职责 |
|---|---|
| `src/novel_dev/schemas/outline.py` | `SynopsisData`, `VolumePlan`, `VolumeBeat`, `VolumeScoreResult` 等 |
| `src/novel_dev/agents/brainstorm_agent.py` | BrainstormAgent 实现 |
| `src/novel_dev/agents/volume_planner.py` | VolumePlannerAgent 实现（含自审循环） |
| `src/novel_dev/agents/director.py` | 扩展 `advance()`, `_run_volume_planner()`, 修复 `VALID_TRANSITIONS` |
| `src/novel_dev/api/routes.py` | 新增 `/brainstorm`, `/volume_plan`, `/synopsis`, `/volume_plan` 路由 |
| `src/novel_dev/mcp_server/server.py` | 新增 4 个 MCP 工具 |
| `tests/test_agents/test_brainstorm_agent.py` | BrainstormAgent 单元测试 |
| `tests/test_agents/test_volume_planner.py` | VolumePlannerAgent 单元测试 |
| `tests/test_agents/test_director_volume_planning.py` | Director 卷纲阶段流转测试 |
| `tests/test_api/test_outline_routes.py` | API 路由集成测试 |

---

## 12. 风险与未来扩展

1. **LLM 总纲一致性**：同样的设定文档，不同模型版本可能生成不同结构的总纲。建议固定 `synopsis_data` 的输出 schema，并在 prompt 中给出完整示例。
2. **长系列小说的动态偏离**：当小说写到第 10+ 卷时，原始总纲可能已严重不适用。未来可考虑让 BrainstormAgent 支持"总纲修订模式"。
3. **VolumePlanner 的 Token 成本**：动态回读需要把前几卷的摘要和实体状态注入 prompt，token 消耗随卷数增长。未来可引入"世界状态摘要"机制，只回读压缩后的关键节点。
