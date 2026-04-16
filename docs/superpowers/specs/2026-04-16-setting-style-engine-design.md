# 设定学习与风格提取引擎 — 设计文档

**日期：** 2026-04-16  
**主题：** 第二子系统：设定学习与风格提取引擎  
**状态：** 待实现  
**依赖：** 核心数据层（已完成）

---

## 1. 目标

本系统负责从原始设定文件和目标小说样本中，自动提取并结构化：
1. **核心设定**（世界观、修炼体系、势力格局、人物、物品、剧情梗概）
2. **文笔文风画像**（句式特征、对话风格、修辞、节奏、词汇偏好、叙事视角、基调）

所有产出写入 `novel_documents` 表，供后续 ContextAgent 查询使用。提取过程以 LLM 驱动为主，但首次提取需要人工校验。

---

## 2. 整体架构

```
用户上传文件
    │
    ▼
┌─────────────────────┐
│  FileClassifier     │
│  (设定文件 / 风格样本) │
└─────────────────────┘
    │
    ├── 设定文件 ──► ┌─────────────────────────┐
    │                │ SettingExtractorAgent   │
    │                │  • 解析原始设定文本      │
    │                │  • 提取结构化设定        │
    │                │  • 拆分为多个 doc_type   │
    │                │  • 同步创建 Entity 草稿  │
    │                └─────────────────────────┘
    │                           │
    │                           ▼
    │                ┌─────────────────────────┐
    │                │ 人工校验节点 (首次)     │
    │                │ 写入 pending_extractions│
    │                └─────────────────────────┘
    │                           │
    │                           ▼
    │                ┌─────────────────────────┐
    │                │ 用户确认后写入数据库     │
    │                │ novel_documents + entities│
    │                └─────────────────────────┘
    │
    └── 风格样本 ──► ┌─────────────────────────┐
                     │ StyleProfilerAgent      │
                     │  • 动态密度分块采样      │
                     │  • 逐块分析文风特征      │
                     │  • 聚合生成风格画像      │
                     └─────────────────────────┘
                                │
                                ▼
                     ┌─────────────────────────┐
                     │ 人工校验节点 (首次)     │
                     │ 写入 pending_extractions│
                     └─────────────────────────┘
                                │
                                ▼
                     ┌─────────────────────────┐
                     │ ProfileMerger (增量合并) │
                     │ 若已有旧版本则自动合并   │
                     └─────────────────────────┘
                                │
                                ▼
                     ┌─────────────────────────┐
                     │ 写入 novel_documents    │
                     │ doc_type="style_profile"│
                     │ version 自动递增         │
                     └─────────────────────────┘
```

---

## 3. FileClassifier

### 3.1 职责
判断上传文件是"设定文件"还是"风格样本"。

### 3.2 分类逻辑

**规则快速通道：**
- 文件名含 `设定`、`世界观`、`大纲`、`setting`、`worldview` → 设定文件
- 文件名含 `样本`、`风格`、`sample`、`style` → 风格样本

**LLM 兜底：**
若规则无法判定，读取文件前 500 字，由轻量 LLM prompt 做二分类。

### 3.3 输出格式

```json
{
  "file_type": "setting" | "style_sample",
  "confidence": 0.95,
  "reason": "文件名包含'设定'，且内容中出现大量世界观描述词汇"
}
```

---

## 4. SettingExtractorAgent

### 4.1 输入
纯文本格式的原始设定文件（`.md` 或 `.txt`）。

### 4.2 LLM 结构化提取

要求 LLM 输出以下结构化 JSON（不存在的字段留空）：

```json
{
  "worldview": "天玄大陆，万族林立...",
  "power_system": "修炼境界分为：炼气、筑基、金丹...",
  "factions": "青云宗：正道魁首... 魔道：...",
  "character_profiles": [
    {"name": "林风", "identity": "青云宗外门弟子", "personality": "坚韧隐忍", "goal": "为父报仇"}
  ],
  "important_items": [
    {"name": "残缺玉佩", "description": "上古魔宗信物", "significance": "揭示主角身世"}
  ],
  "plot_synopsis": "主角林风因家族被灭门，拜入青云宗..."
}
```

### 4.3 写入 `novel_documents`

每个非空字段生成一条记录，doc_type 映射如下：

| 提取字段 | doc_type |
|---|---|
| `worldview` | `worldview` |
| `power_system` | `setting` |
| `factions` | `setting` |
| `character_profiles` | `concept` |
| `important_items` | `concept` |
| `plot_synopsis` | `synopsis` |

### 4.4 同步创建 Entity 草稿

- `character_profiles` 中的每个人物 → `Entity(type="character")`
- `factions` 中的每个势力 → `Entity(type="faction")`
- `important_items` 中的每个物品 → `Entity(type="item")`

首次提取时，这些 Entity 作为"拟创建列表"存入 `pending_extractions.proposed_entities`，待用户确认后正式创建。

### 4.5 人工校验节点

系统暂停，向用户展示：
- 提取出了哪些 `doc_type` 及各自摘要
- 拟创建多少个 Entity

用户通过 `/api/novels/{novel_id}/documents/pending/approve` 确认后入库。

---

## 5. StyleProfilerAgent

### 5.1 采样策略（动态密度采样）

- **分块大小**：3000 字/块
- **采样数量**：
  - 总块数 = 总字数 / 3000
  - 采样率 50%
  - **最少 8 个块**
  - **最多 24 个块**
- **采样分布**：均匀分层采样，覆盖开头、中段、结尾

**示例：**
- 15 万字 → 50 块 → 采样 24 块
- 5 万字 → 16 块 → 采样 8 块
- 2 万字 → 6 块 → 全采

### 5.2 分析维度

每个样本块要求 LLM 从以下维度分析：

| 维度 | 说明 |
|---|---|
| `sentence_patterns` | 句式偏好（长短句、整散句、口语化/书面化） |
| `dialogue_style` | 对话风格（直接/间接引语、对话标签使用、简洁度） |
| `rhetoric_devices` | 常用修辞及频率 |
| `pacing` | 叙事节奏（快/慢、信息密度、场景切换） |
| `vocabulary_preferences` | 词汇偏好（文言/白话、抽象/具象、高频词） |
| `perspective` | 叙事视角（限知/全知） |
| `tone` | 基调（严肃/轻松、热血/压抑） |

### 5.3 聚合与输出

1. 对所有 `chunk_analysis` 按"开头段/中段/结尾段"分组聚类
2. 识别文风是否随剧情演变
3. 输出最终风格画像：

```json
{
  "style_guide": "整体文风偏向短促有力，多用四字短语营造节奏感...",
  "style_config": {
    "sentence_patterns": {...},
    "dialogue_style": {...},
    "rhetoric_devices": {...},
    "pacing": "快节奏，场景切换频繁",
    "vocabulary_preferences": ["凌厉", "蛰伏"],
    "perspective": "限知视角，禁止上帝视角",
    "tone": "热血压抑交织",
    "evolution_notes": "前期压抑内敛，中期逐渐热血外放"
  }
}
```

### 5.4 人工校验节点

首次提取完成后，系统展示：
- `style_guide` 全文
- `style_config` 结构化摘要
- 样本来源（字数、块数、分布）

确认后进入 `ProfileMerger`（若已有旧版本）或直接入库。

---

## 6. ProfileMerger（增量合并与版本管理）

### 6.1 触发条件
新风格样本分析完成，且数据库中已存在 `doc_type="style_profile"` 记录。

### 6.2 合并流程

1. 读取最新版本的 `style_guide` + `style_config`
2. 读取新样本的 `new_guide` + `new_config`
3. 输入 LLM 执行智能合并：
   - 保留旧版有效特征
   - 补充新版新特征
   - 修正矛盾描述
   - 标记冲突
4. 输出 `merged_guide` + `merged_config`

### 6.3 冲突标记

```json
{
  "conflicts": [
    {
      "field": "pacing",
      "old_value": "快节奏",
      "new_value": "中慢节奏",
      "resolution": "样本来源不同导致差异，建议确认"
    }
  ]
}
```

### 6.4 版本写入

- `version = old_version + 1`
- 写入 `novel_documents(doc_type="style_profile", version=N)`
- 旧版本完整保留

### 6.5 版本回滚

通过修改 `novel_state.checkpoint_data` 中的生效版本指针实现：

```json
{
  "active_style_profile_version": 3
}
```

回滚接口：
- `POST /api/novels/{novel_id}/style_profile/rollback`
- Body: `{"version": 3}`

`get_latest_style_profile` 查询时，优先读取 `checkpoint_data` 中标记的生效版本，而非物理最新版本。

---

## 7. 数据库设计

### 7.1 新增表：`pending_extractions`

```sql
CREATE TABLE pending_extractions (
    id TEXT PRIMARY KEY,
    novel_id TEXT NOT NULL,
    extraction_type TEXT NOT NULL,  -- "setting" | "style_profile"
    status TEXT DEFAULT "pending",   -- pending | approved | rejected
    raw_result JSONB NOT NULL,
    proposed_entities JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 7.2 复用现有表

- `novel_documents`：存储最终确认的所有文档（worldview/setting/concept/synopsis/style_profile）
- `entities` + `entity_versions`：存储 SettingExtractor 提取出的人物、势力、物品
- `novel_state`：存储风格画像的生效版本指针

---

## 8. API 接口

在现有 FastAPI `routes.py` 中新增：

| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/novels/{novel_id}/documents/upload` | POST | 上传文件触发自动提取 |
| `/api/novels/{novel_id}/documents/pending` | GET | 获取待人工校验结果 |
| `/api/novels/{novel_id}/documents/pending/approve` | POST | 确认入库 |
| `/api/novels/{novel_id}/style_profile/versions` | GET | 列出版本历史 |
| `/api/novels/{novel_id}/style_profile/rollback` | POST | 回滚到指定版本 |

---

## 9. MCP 工具

在现有 MCP Server 中新增：

| 工具名 | 说明 |
|---|---|
| `upload_document` | 上传并触发自动提取 |
| `get_pending_documents` | 获取待审结果 |
| `approve_pending_documents` | 确认入库 |
| `list_style_profile_versions` | 列出版本 |
| `rollback_style_profile` | 回滚版本 |
| `analyze_style_from_text` | 直接对文本做风格分析 |

---

## 10. 错误处理

- 文件无法读取 → 返回 400，记录错误日志
- LLM 提取失败/返回非法 JSON → 重试 2 次，仍失败则存入 `pending_extractions` 并标记 `status="failed"`
- 人工校验超时（暂不设硬性超时，由用户主动触发 approve/reject）

---

## 11. 测试策略

- **单元测试**：`FileClassifier` 分类准确性、`ProfileMerger` 合并逻辑
- **集成测试**：上传模拟设定文件 → 提取 → 入库 → 查询完整链路
- **风格测试**：对已知文本样本（如鲁迅/金庸片段）提取画像，人工校验合理性

---

## 12. 风险与未来扩展

1. **LLM 提取一致性**：同样的设定文件，不同模型版本可能输出不同结构。建议固定输出 schema，并在 prompt 中给出完整示例。
2. **风格样本偏差**：若用户上传的样本本身风格不统一（如多人合著），画像会失真。未来可增加"风格一致性评分"预警。
3. **Token 成本控制**：24 个块 × 每块分析 token 消耗较高。未来可对分析结果做缓存，避免重复分析相同文本。
