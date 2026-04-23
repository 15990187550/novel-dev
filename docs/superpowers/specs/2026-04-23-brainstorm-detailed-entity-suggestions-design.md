# 脑暴阶段详细设定建议卡 — 设计文档

**日期：** 2026-04-23  
**主题：** 在脑暴与卷纲生成阶段同步产出更详细的人物、势力、地点、物品/功法、关系建议，并在最终确认时统一提交  
**状态：** 待实现  
**依赖：** 现有 `BrainstormWorkspaceService`、`OutlineWorkbenchService`、`ExtractionService`、`RelationshipRepository`、`EntityRelationship`、`VolumePlan.vue`

---

## 1. 目标

当前脑暴与卷纲工作台已经支持：

- 总纲与卷纲的独立上下文
- 工作区草稿保存
- 最终确认后统一提交总纲、卷纲与设定导入草稿

但它仍然缺少一层稳定的“详细设定建议”结构。当前问题有三类：

- 总纲和卷纲结果仍偏剧情骨架，人物、势力、关系等关键信息不够细。
- `setting_docs_draft` 适合旧式导入草稿，不适合承载脑暴阶段的结构化增量建议。
- 关系虽然已有正式表和图谱展示，但脑暴阶段还不能稳定地产生可落地的关系建议。

本设计的目标是：

- 在每轮总纲/卷纲优化时，同步产出详细设定建议。
- 保持总纲/卷纲结果为“摘要层”，不把完整实体细节塞进 outline schema。
- 将详细设定建议单独存入工作区的结构化建议卡容器。
- 最终确认时，按类型将建议卡分别映射到现有正式链路：
  - 总纲与卷纲进入正式 checkpoint
  - 实体类建议进入 `pending_extractions`
  - 已解析的关系建议进入 `EntityRelationship`

---

## 2. 范围

### 2.1 包含

- 脑暴工作区新增结构化建议卡容器
- 每轮总纲/卷纲优化后联动生成详细设定建议
- 支持首批 5 类建议卡：
  - `character`
  - `faction`
  - `location`
  - `artifact_or_skill`
  - `relationship`
- 前端展示：
  - 总纲/卷纲详情中的设定摘要
  - 建议卡列表与展开详情
  - 本轮新增、更新、待解析、已覆盖状态提示
- 最终确认时的分渠道提交与校验

### 2.2 不包含

- 新建独立“设定建议中心”页面
- 在脑暴阶段直接编辑正式实体或正式关系
- 多人协作审批流
- 关系历史版本回滚
- 对旧 `setting_docs_draft` 协议做破坏式替换

---

## 3. 方案选择

本需求存在三种可选路线：

1. **轻量增强型**
   - 继续复用 `setting_docs_draft`
   - 只扩充大纲结果中的设定文本
   - 改动小，但无法稳定承载结构化增量建议

2. **工作区结构化增强型**
   - 总纲/卷纲保留摘要层
   - 工作区新增独立建议卡容器
   - 每轮更新摘要和建议卡
   - 最终确认时分渠道提交

3. **全量实体中心型**
   - 脑暴阶段直接维护完整实体树和关系网
   - 大纲只是实体状态的投影
   - 长期统一，但改动过大，不适合当前代码基线

本设计选择 **工作区结构化增强型**，原因：

- 能复用当前 `BrainstormWorkspace` 和 outline workbench
- 不破坏现有 `setting_docs_draft -> pending_extractions` 链路
- 能让“更详细的设定”成为可管理的结构化数据，而不是更长的文本
- 为关系图谱、百科页、后续实体管理预留清晰出口

---

## 4. 设计原则

1. **摘要与细节分层**
   - outline 结果负责创作摘要
   - 建议卡负责结构化细节

2. **新旧协议隔离**
   - `setting_docs_draft` 保持旧式导入草稿语义
   - 新建议卡使用独立容器，不强塞进旧 schema

3. **每轮联动，但不阻塞主链路**
   - 大纲更新成功优先
   - 建议卡生成失败时，不阻断大纲更新

4. **关系独立建模**
   - 关系是独立建议卡
   - 人物/势力详情只显示关系摘要

5. **最终确认统一提交**
   - 工作区阶段只保存建议
   - 正式写库只发生在最终确认时

6. **渐进落地**
   - 第一阶段先完成建议卡生成与展示
   - 再逐步打通关系提交与更强解析能力

---

## 5. 数据模型

### 5.1 `outline_drafts`

`BrainstormWorkspace.outline_drafts` 继续作为总纲与卷纲的权威草稿容器：

```python
outline_drafts = {
    "synopsis:synopsis": {...},
    "volume:vol_1": {...},
    "volume:vol_2": {...},
}
```

但每个快照只补充少量摘要字段，不承载完整实体细节。

建议新增：

- `entity_highlights`
- `relationship_highlights`

示意：

```json
{
  "title": "第一卷：寒门入宗",
  "summary": "主角进入宗门并卷入派系争斗",
  "entity_highlights": {
    "characters": ["陆照：寒门少年，目标是入宗立足"],
    "factions": ["天刑宗：内部派系分裂"],
    "locations": ["外门试炼场：第一卷核心舞台"]
  },
  "relationship_highlights": [
    "陆照 vs 韩广：竞争敌对",
    "陆照 / 苏清寒：从互疑到合作"
  ]
}
```

约束：

- 这些字段仅用于工作台详情展示
- 不作为正式实体数据来源
- 不替代建议卡中的结构化 payload

### 5.2 新增 `setting_suggestion_cards`

在 `BrainstormWorkspace` 中新增独立容器：

```python
setting_suggestion_cards = [
    {...},
    {...},
]
```

每张卡的公共字段：

```python
SettingSuggestionCard(
    card_id,
    card_type,           # character / faction / location / artifact_or_skill / relationship
    merge_key,
    title,
    summary,
    status,              # active / superseded / unresolved
    source_outline_refs, # ["synopsis", "vol_1", ...]
    payload,
    display_order,
)
```

字段含义：

- `card_id`
  - 卡片实例 ID，仅用于前端渲染与工作区引用
- `merge_key`
  - 卡片语义身份，用于每轮增量更新合并
- `status`
  - `active`：当前有效建议
  - `superseded`：被新版建议覆盖
  - `unresolved`：依赖实体解析或信息尚不完整
- `source_outline_refs`
  - 保留多轮来源，不能只保留最后一次来源

### 5.3 实体类卡的 payload

#### `character`

```json
{
  "canonical_name": "陆照",
  "aliases": [],
  "identity": "寒门少年",
  "goal": "在宗门立足并查清父母之死",
  "personality": "隐忍、警觉、好胜",
  "background": "出身边城猎户家庭",
  "ability": "刀法、残缺呼吸法",
  "resources": "祖传黑刀",
  "secrets": "体内藏有异火印记",
  "conflict": "与宗门考核体系及韩广对立",
  "arc": "从求生自保转向主动争命",
  "relationships_summary": "与苏清寒从互疑转向合作"
}
```

#### `faction`

```json
{
  "canonical_name": "天刑宗",
  "aliases": [],
  "role": "第一卷核心宗门势力",
  "position": "表面主持秩序，内部派系争权",
  "core_members": ["韩广", "苏清寒"],
  "resources": "功法传承、外门考核权",
  "goal": "维持宗门稳定并控制传承",
  "internal_conflict": "长老会与执法堂路线分裂",
  "external_conflict": "与散修势力争夺遗迹"
}
```

#### `location`

```json
{
  "canonical_name": "外门试炼场",
  "aliases": [],
  "role": "第一卷核心舞台",
  "description": "宗门考核与派系试探发生地",
  "controlling_faction": "天刑宗",
  "narrative_significance": "主角初次立足与冲突升级的场域"
}
```

#### `artifact_or_skill`

```json
{
  "canonical_name": "祖传黑刀",
  "aliases": [],
  "item_kind": "artifact",
  "description": "主角持有的家传兵器",
  "significance": "与身世线索相关",
  "owner": "陆照"
}
```

### 5.4 关系卡 payload

关系卡以“实体对”为主身份，不把 `relation_type` 放进 `merge_key`。

建议结构：

```json
{
  "source_entity_ref": "陆照",
  "target_entity_ref": "苏清寒",
  "source_entity_card_key": "character:lu-zhao",
  "target_entity_card_key": "character:su-qinghan",
  "relation_type": "亦敌亦友",
  "directionality": "bidirectional",
  "stage_change": "第一卷中后段转为短期同盟",
  "evidence_note": "共同面对外门试炼危机后建立合作",
  "confidence": 0.82,
  "unresolved_references": []
}
```

关系卡 `merge_key` 建议为：

```text
relationship:<source-ref>:<target-ref>
```

这样“敌对 -> 同盟”会更新同一张关系卡，而不是裂成两张并行卡，也更符合当前 `RelationshipRepository` 以 `(source_id, target_id)` 为主要身份的持久化模型。

### 5.5 `merge_key` 规则

建议：

- `character:<stable-slug>`
- `faction:<stable-slug>`
- `location:<stable-slug>`
- `artifact_or_skill:<stable-slug>`
- `relationship:<source-ref>:<target-ref>`

其中 `stable-slug` 不能仅依赖原始名称文本，必须预留：

- `canonical_name`
- `aliases`
- `disambiguation_hint`

避免“同名不同人”在工作区阶段被误合并。

---

## 6. 每轮优化时的联动更新流程

### 6.1 总体流程

每轮用户提交反馈后，按三步处理：

1. **主链路更新大纲**
   - 调用现有总纲或卷纲优化逻辑
   - 产出新的 `result_snapshot`
   - 更新 `conversation_summary`

2. **联动生成建议卡**
   - 基于新快照、历史建议卡、用户最新意见、对话摘要和原始设定文档
   - 调用专门的 suggestion updater

3. **合并建议卡到工作区**
   - 按 `merge_key` 更新 `setting_suggestion_cards`
   - 返回本轮新增、更新、覆盖、待解析统计

### 6.2 主链路输出

`_optimize_synopsis()` 与 `_optimize_volume()` 继续负责：

- `content`
- `result_snapshot`
- `conversation_summary`

并在 `result_snapshot` 中附加：

- `entity_highlights`
- `relationship_highlights`

### 6.3 建议卡生成器输入

建议输入包含：

- 当前轮新的 `result_snapshot`
- 当前工作区已有的 `setting_suggestion_cards`
- 用户最新意见
- 当前 outline 的 `conversation_summary`
- 必要的原始设定文档片段

生成器职责：

- 识别本轮新增的重要实体和关系
- 补充已有卡的字段
- 标记被新版本覆盖的旧卡
- 发现无法解析的关系引用

### 6.4 建议卡生成器输出

建议格式：

```json
{
  "cards": [
    {
      "operation": "upsert",
      "card_type": "character",
      "merge_key": "character:lu-zhao",
      "title": "陆照",
      "summary": "补充第一卷主角目标、资源与秘密",
      "source_outline_refs": ["synopsis", "vol_1"],
      "payload": {...}
    },
    {
      "operation": "upsert",
      "card_type": "relationship",
      "merge_key": "relationship:lu-zhao:su-qinghan",
      "title": "陆照 / 苏清寒",
      "summary": "两人关系从互疑转向合作",
      "source_outline_refs": ["vol_1"],
      "payload": {...}
    }
  ],
  "summary": {
    "created": 2,
    "updated": 1,
    "superseded": 0,
    "unresolved": 1
  }
}
```

### 6.5 工作区合并规则

新增 `merge_suggestion_cards()`，替代旧 `merge_setting_drafts()` 的语义。

规则：

- `upsert`
  - 找到同 `merge_key` 且状态为 `active` 的卡：更新其 `summary`、`payload`、`source_outline_refs`
  - 未找到：创建新卡
- `supersede`
  - 将当前 `active` 卡标记为 `superseded`
- `mark_unresolved`
  - 保留卡，但将状态改为 `unresolved`

`source_outline_refs` 合并时做并集去重。

### 6.6 降级策略

- 主链路成功、建议卡生成失败：
  - 允许本轮只更新大纲结果
  - assistant message 追加失败提示
- 建议卡输出 schema 非法：
  - 丢弃本轮建议卡更新
  - 不影响大纲结果提交
- 关系卡引用实体未解析：
  - 标记为 `unresolved`
  - 保留在工作区，等待后续轮次补全或最终确认前解析

---

## 7. 前端展示

### 7.1 工作台详情区

在总纲/卷纲详情中新增两个轻量区块：

- `关键实体摘要`
- `关键关系摘要`

这里只展示摘要级信息，帮助用户理解当前大纲项已经细化到了哪些设定点。

### 7.2 建议卡区

当前 `Setting Drafts` 区块升级为“建议卡列表 + 展开详情”：

- 列表项显示：
  - 标题
  - 类型
  - 来源
  - 当前状态
  - 一句摘要
- 展开后显示结构化字段

默认只展示：

- `active`
- `unresolved`

`superseded` 放入折叠的“历史建议”区。

### 7.3 本轮变化提示

每轮提交后：

- assistant message 追加本轮建议卡变化摘要
- 建议卡区高亮：
  - `新增`
  - `已更新`
  - `待解析`
  - `已覆盖`

示例：

> 已更新第一卷卷纲，并新增 1 条人物建议、1 条关系建议，另有 1 条关系待解析实体引用。

---

## 8. 最终确认与正式提交

### 8.1 提交前收口

最终确认前先扫描工作区：

- 只取 `active` 建议卡参与正式提交
- `superseded` 不提交
- `unresolved` 进入校验清单

并执行统一实体解析：

1. 优先使用 `source_entity_card_key` / `target_entity_card_key`
2. 再用 suggestion cards 中的 `canonical_name + aliases`
3. 最后尝试匹配正式实体

产物：

- `resolved_entity_suggestions`
- `resolved_relationship_suggestions`

### 8.2 校验策略

#### 硬校验

- 缺少总纲草稿
- 卷纲结构非法
- suggestion card payload 不合法
- 关系卡缺少源或目标，且无法解析
- 提交步骤会造成数据不一致

#### 软校验

- 实体字段过于稀疏
- 关系只有摘要，没有阶段变化
- 匹配实体时存在低置信度歧义

前端规则：

- 硬校验失败：禁止最终确认
- 软校验存在：允许提交，但展示 warning

### 8.3 分渠道提交

最终确认时，按类型分别提交：

1. `outline_drafts`
   - 总纲转正式 `synopsis`
   - 卷纲进入正式 checkpoint

2. 实体类建议卡
   - `character`
   - `faction`
   - `location`
   - `artifact_or_skill`
   - 转换为可兼容的 `pending_extractions`
   - 这里新增“从 suggestion card 到 pending payload”的映射层

3. 关系建议卡
   - 源和目标实体都成功解析时，写入 `EntityRelationship`
   - `relation_type`、`stage_change`、`evidence_note`、`confidence` 写入 `meta`

### 8.4 原子提交顺序

建议顺序：

1. 写正式 `synopsis`
2. 写卷纲 checkpoint
3. 写实体类 pending items
4. 写关系结果
5. 标记 workspace 为 `submitted`
6. 记录提交摘要

若第 3 或第 4 步失败，应整体回滚，避免半提交状态。

### 8.5 关系提交策略

本设计推荐：

- 已解析关系：
  - 直接写入 `EntityRelationship`
  - 并在 `meta.submission_source` 中标记 `brainstorm_workspace`
- 未解析关系：
  - 不写正式关系表
  - 以 warning 形式反馈给用户

---

## 9. 兼容策略与分阶段落地

### 9.1 第一阶段

- 新增 `setting_suggestion_cards`
- 每轮生成和展示建议卡
- 最终确认时先只提交实体类建议
- 关系卡先停留在工作区展示层

### 9.2 第二阶段

- 引入关系实体解析
- 最终确认时允许将已解析关系写入 `EntityRelationship`
- 未解析关系继续 warning

### 9.3 第三阶段

- 将旧 `setting_docs_draft` 的脑暴职责彻底移除
- 仅保留为旧式导入兼容出口

---

## 10. 测试策略

### 10.1 后端

- `merge_suggestion_cards()` 按 `merge_key` 合并，而不是按实例 ID 堆重复卡
- `superseded` 卡不会参与最终提交
- 关系卡以“实体对”为主身份，不因 `relation_type` 变化裂成多张当前卡
- `unresolved` 关系在最终确认时触发正确 warning 或 hard error
- 提交阶段失败时整体回滚

### 10.2 前端

- 详情区正确展示 `entity_highlights / relationship_highlights`
- 建议卡区默认只展示当前有效卡
- 展开卡片能展示结构化字段
- 本轮新增、更新、待解析、已覆盖状态显示正确
- 最终确认前 warning 与禁用逻辑正确

---

## 11. 预期收益

- 脑暴与卷纲阶段不再只产出剧情骨架，也能稳定沉淀人物、势力、地点、物品和关系细节
- 不破坏现有旧式导入链路
- 关系建议能逐步接入正式图谱，而不是继续埋在人物长文本里
- 前端工作台能明确体现“本轮不仅改了大纲，也细化了设定”

---

## 12. 风险与控制

### 风险 1：建议卡和旧式导入草稿语义混淆

控制：

- 使用独立 `setting_suggestion_cards`
- 不把新建议卡直接塞进旧 `setting_docs_draft`

### 风险 2：关系解析失败导致提交阻塞

控制：

- 脑暴阶段允许 unresolved
- 最终确认前统一解析
- 已解析关系先提交，未解析关系以 warning 保留

### 风险 3：同名实体误合并

控制：

- `merge_key` 预留稳定 slug 与别名
- payload 中保留 `canonical_name`、`aliases`、`disambiguation_hint`

### 风险 4：每轮都更新建议卡导致工作区膨胀

控制：

- 以 `merge_key` 为主身份做 upsert
- 被新版替代的卡标记为 `superseded`
- 前端默认只展示当前有效卡
