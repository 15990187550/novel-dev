# Phase 4 质量架构升级设计

> **日期**: 2026-06-17
> **分支**: `phase2-writer-protection` 继续
> **前置阶段**: Phase 1 (observability) / Phase 2 (writer protection) / Phase 3 (prompt engineering) 全部完成并通过测试

## 目标

解决已识别但尚未修复的 6 类质量问题:

1. **死代码**: 阶段三 A/B 测试、`recent_issue_counts`、BeatCoverageValidator 三处投资未生效
2. **架构漏洞**: WriterAgent 整章模式绕过所有节拍级防护
3. **长篇上下文饥饿**: 无滚动叙事摘要,30+ 章后质量必然下降
4. **跨章漂移无检测**: 实体名漂移(陆照→陆昭)、身份漂移(师兄→师弟)、状态阶跃(凡人→筑基期无交代)
5. **跨章意象重复**: "碎石硌掌心" 3 章出现 3 次无追踪
6. **网文特定规则缺失**: 钩子、爽点、金手指、节奏感未建模为第一类概念

## 范围与分波

按用户决策:**单次交付,大计划一次执行**。25-30 任务的实施计划一次写完,所有任务通过 subagent-driven development 执行。

## 不在本期范围

- LLM 选型调整(模型/温度配置层面)
- 数据库迁移到 PostgreSQL 之外的存储
- 重写主 pipeline 编排
- Vue 前端样式重构(只加新视图/组件)
- 多 LLM provider 适配

---

## §1 P0 紧急修复:让已有投资生效

### 1.1 A/B 测试管道接通

**问题**: 阶段三的 `LLMFactory.get_with_metadata()` + `ABTestRunner.pick_version()` 整套基础设施完整,但 8 个 agent 内的 LLM 调用全部走 `llm_factory.get()` 而不是 `get_with_metadata()`。结果:`pick_version` 永远不被调用,A/B 测试赢了之后无人路由到该版本,UI 上的"采纳赢家"按钮是空操作。

**修复**:
- 在 `LLMFactory` 加一个 `get_with_chapter_id(agent_name, task, chapter_id)` 便捷方法(在 `get_with_metadata` 之上封装,自动调用 `pick_version` 并选择 prompt version)
- 8 个 agent 内的 LLM 调用点改为调用 `get_with_chapter_id`,传入 `chapter_id`
- `PromptRegistry` 在 `get_active` 之上加 `get_active_for_chapter(agent_name, chapter_id)`:先查 A/B 路由,无则降级到当前活跃版本
- A/B 测试的状态真正影响下一次生成

**测试**:
- 单元测试: `get_with_chapter_id` 在无 A/B 时等价于 `get_active`
- 单元测试: `get_with_chapter_id` 在有 A/B 时根据 hash 路由到 baseline/challenger
- 集成测试: 创建 A/B → 调用 `get_with_chapter_id` 多次 → 确认 50/50 分布

### 1.2 强制 beat_by_beat 模式

**问题**: `WriterAgent._should_generate_whole_chapter()` 默认返回 True(除非显式传 `drafting_mode=beat_by_beat`)。整章模式跳过了阶段二建的所有防护:`relay_history`、`_self_check_beat`、`_guard_writer_beat`、`_enforce_beat_word_budget`、`_enforce_prose_hygiene`、`_anchored_beat_coverage`。

**修复**:
- 修改 `_should_generate_whole_chapter` 默认返回 False,改为 `beat_by_beat` 为默认模式
- 加配置项 `quality.writer.default_drafting_mode`(默认 `"beat_by_beat"`)
- 整章模式仅在显式开启 + 跑全量自检(LLM judge 整章对每拍 boundary card)
- 全链路: Director.advance() / API 端点 / 现有调用方不需要改

**测试**:
- 单元测试: `_should_generate_whole_chapter` 默认返回 False
- 集成测试: 默认写作流程现在走节拍模式,每个节拍都有 relay+self_check+guard

### 1.3 recent_issue_counts 接入 UI

**修复**:
- `QualityRecommendationWidget.vue` 在 `loadRecommendation` 之前,先从 `GET /api/novels/{id}/chapters/recent-issue-counts` 拉最近 5-10 章的 issue_codes
- 计数后作为 `recent_issue_counts` 传入 `recommendChapterQuality`
- 模式检测规则生效:连续 3 章同 issue_code → 推荐 major_repair + suggested_action 中加 "pattern_fix"

**测试**:
- 单元测试: Widget 接收 `recentIssueCounts` prop 后随请求发送
- 服务测试: `RecommendationService.recommend` 在检测到 pattern 时返回 `minor_repair`/`major_repair` + pattern_fix action

### 1.4 BeatCoverageValidator 接入主流程

**修复**:
- 在 `FastReviewAgent.review()` 末尾加调用:`BeatCoverageValidator(session, use_llm=True).validate(beat_cards, chapter_text)`
- 验证结果加入 `FastReviewReport`:`beat_coverage_results: list[BeatCoverageResult]`
- 在 `quality_gate_service` 评估时:`block` 级别的 coverage 结果 → gate 状态 `block`

**测试**:
- 单元测试: FastReviewAgent 调用 BeatCoverageValidator 并填入结果
- 集成测试: must_cover 缺失 → gate block

---

## §2 P0 配置级快速修复

### 2.1 WriterAgent 温度下调

`llm_config.yaml`:
- `writer_agent.tasks.generate_chapter.temperature`: 0.8 → 0.75
- 解释: 0.8 在中文网文风格一致性下偏高,降到 0.75 减少跑偏

### 2.2 CONTEXT_AGENT_PROMPT 重写

**当前**: 15 行,只有输出 schema,没有理论指导

**重写为**: ~40 行,包含:
- 输出 schema(保留)
- 实体筛选原则(相关性、距离当前章时间、状态匹配度)
- 文档检索原则(主题契合度高于字面匹配)
- 冲突解决原则(实体状态冲突时优先最近更新)
- 1 个 few-shot 示例

### 2.3 关键 prompt 加 few-shot

给以下 agent 加 1-2 个脱敏的 few-shot 示例:
- `WRITER_PROMPT`: 一个"差 → 好"开头的对比
- `CRITIC_PROMPT`: 一个 90+ humanity 评分 + 一个 40- humanity 评分
- `EDITOR_PROMPT`: 一个"修前 → 修后"对比
- 这些都是 PromptRegistry 条目,可 A/B 测试

### 2.4 Librarian 软状态 pass 提升为 PromptRegistry

**当前**: `librarian.py:145-198` 的 `_build_soft_state_prompt` 是 Python 字符串拼装,不能 A/B 测试

**修复**: 提取到 `_default_prompts.py` 作为 `LIBRARIAN_SOFT_STATE_PROMPT` 条目,在 librarian.py 中 `await self.prompt_registry.get_active("librarian_soft_state")` 取用

### 2.5 失败闭门策略(关键路径)

**当前**: `chapter_structure_guard_service.py:116-125` 编辑器守卫超时时返回 `passed=True`("保守通过")

**修复**:
- 守卫超时 / LLM 失败 → 返回 `passed=False, conservative_fallback=False`
- 闸门后续逻辑: `not passed and not conservative_fallback` → 触发章节重写(走根因分析 + retry)
- 配置项 `quality.guard.fail_open_on_timeout: bool` (默认 `False`)

---

## §3 P1 架构升级:滚动叙事摘要(RCS)

### 3.1 目标

解决"30+ 章后质量必然下降"问题。当前 `ContextAgent._narrative_source_from_checkpoint` 只读 brainstorm 阶段的静态 synopsis,无法承载长篇叙事的"故事走到哪里"。

### 3.2 触发策略

**自适应触发**,3 类事件:

1. **实体状态剧变**: Librarian 持久化 entity version 后,对本章所有状态变化批量调用 1 次 LLM,评估是否"重要叙事点"
2. **质量门 block**: `quality_gate_service.gate_status == "block"` 触发
3. **新实体出现 / 实体退出**: `entities` 表的新 insert 或 archived

伏笔事件**不**单独触发(用户决策)。

### 3.3 实体状态剧变判定

**新 prompt**: `ENTITY_CHANGE_IMPORTANCE_PROMPT`(Librarian 模型同款,低温度)
- 输入: 本章所有 entity state diffs(批量)
- 输出: `[{entity_id, is_important, reason, suggested_synopsis_section}]`
- 至少 1 个 `is_important=True` → 触发 RCS

### 3.4 输出格式

**混合输出**(用户决策):
- `narrative_prose`: 500-2000 字连续叙事,作为 `checkpoint_data["rolling_synopsis_cache"]` 缓存,供 writer `_narrative_source_from_checkpoint` 读取
- `structured_json`: `{plot_points: [...], unresolved_tensions: [...], character_arcs: {...}, foreshadowing_status: {...}}`,存入新表供其他服务查询

### 3.5 数据模型

**新表 `chapter_synopsis`** (append-only):
- `id` UUID PK
- `novel_id` FK
- `chapter_range_start`, `chapter_range_end` (覆盖章节范围,通常 start 是 prev_synopsis.end+1, end 是当前 chapter)
- `narrative_prose` TEXT
- `structured_json` JSONB
- `trigger_event` JSONB(`{type, chapter_id, entity_id, ...}`)
- `prev_synopsis_id` UUID FK self
- `analyzer_version` str
- `created_at` TIMESTAMP

**Alembic 迁移**: 单一 phase4 迁移脚本,创建 3 个新表(`chapter_synopsis` / `thrill_point` / `imagery_inventory`)。`thrill_point` 字段定义见 §4.3,`imagery_inventory` 见 §6.2

### 3.6 服务设计

**新服务 `RollingChapterSynopsisService`**:
- `should_update(novel_id, chapter_id, event_type, event_payload) -> bool`
- `update(novel_id, chapter_id, trigger_event) -> ChapterSynopsis`
  1. 读 prev synopsis
  2. 读 prev_synopsis.chapter_range_end+1 到 chapter_id 之间所有章节文本(可能从 `chapters` 表读)
  3. 调 LLM with `ROLLING_SYNOPSIS_PROMPT`,输入 prev_synopsis + 新章节摘要 + trigger_event
  4. 解析 narrative_prose + structured_json
  5. insert chapter_synopsis
  6. 写 `novel_state.checkpoint_data["rolling_synopsis_cache"]`
- `get_latest(novel_id) -> ChapterSynopsis`
- `cache_to_checkpoint(novel_id, synopsis)`: 写 checkpoint

### 3.7 新 prompt

**`ROLLING_SYNOPSIS_PROMPT`**(在 `_default_prompts.py`,Librarian 模型同款,温度 0.2):
- 输入模板: prev synopsis + 新章节范围(摘要) + trigger_event 详情
- 输出 JSON: `{narrative_prose, structured_json}`
- 强调"延续前情、标注新增重大事件、保留未解决张力"

**`ENTITY_CHANGE_IMPORTANCE_PROMPT`**(同款模型):
- 输入: `[entity_id, entity_name, prev_state, new_state, diff_summary]`
- 输出 JSON: `[{entity_id, is_important, reason, suggested_synopsis_section}]`

### 3.8 接入点

- **LibrarianAgent.persist() 末尾**: 调用 `RollingChapterSynopsisService.should_update()` 决定是否触发;若触发,`update()`
- **ContextAgent._narrative_source_from_checkpoint**: 优先读 `rolling_synopsis_cache`,若无则降级到现有 keys
- **VolumePlanner / 人工审核 UI**: 可读最新 synopsis 了解"故事走到哪里"

### 3.9 测试

- 单元测试: should_update 在 3 类事件下返回 True,其他情况 False
- 单元测试: update 写入新表 + checkpoint
- 单元测试: get_latest 返回最新一条
- 集成测试: Librarian persist 触发 update,ContextAgent 后续读到
- 集成测试: 多次更新后 get_latest 返回最新

---

## §4 P1 架构升级:网文特定规则(钩子/爽点/金手指/节奏)

### 4.1 目标

解决"27/15 章节缺钩子""无爽点建模""金手指零引导""节奏感零建模"问题。

### 4.2 章末钩子(最直接)

**`BeatBoundaryCard` 扩展字段**:
- `required_open_question: Optional[str]`(对末拍必填)
- 加 model validation: `is_last_beat and not required_open_question` → 抛 ValidationError

**接入点**:
- `VolumePlannerAgent` 在生成末拍时,prompt 强制要求输出 `required_open_question`
- `WriterAgent` 收到末拍 boundary card 时,prompt 强调"以这个 open_question 收束"
- `FastReviewAgent` 验证:末拍文本中是否能找到指向 open_question 的语言(简单正则或 LLM 校验)

**测试**:
- 单元测试: BeatBoundaryCard 末拍缺 required_open_question 抛错
- 单元测试: VolumePlanner prompt 包含 required_open_question 要求
- 集成测试: 完整章节流末拍文本确实围绕 open_question 收束

### 4.3 爽点(新表 + Planner + FastReview)

**新表 `thrill_point`** (id, novel_id, chapter_id, beat_idx, type, intensity, planner_predicted, fast_review_verified, ...)

**类型枚举** (8 类): `face_slap / show_off / level_up / reward_gain / revelation / revenge / plot_twist / recognition`

**intensity 枚举**: `low / medium / high / peak`(对应爽度)

**接入点**:
- `VolumePlannerAgent` 生成 chapter plan 时,在 beat_plan 中标记 `expected_thrills: [{beat_idx, type, intensity}]`
- `FastReviewAgent.review()`: LLM 扫描本章文本,识别实际爽点,写入 `thrill_point` 表,`fast_review_verified=True`
- 推荐服务: `thrill_point` 表中 `planner_predicted=True, fast_review_verified=False` 数量 → 计入 `plot_tension` 评分

**测试**:
- 单元测试: VolumePlanner 输出 expected_thrills
- 单元测试: FastReview 检测并写表
- 推荐测试: 未达成爽点影响 plot_tension 分数

### 4.4 金手指(Entity 字段)

**Entity 模型扩展**:
- `cheat_ability: Optional[str]`(能力描述,例如"残玉空间 + 时间倒流")
- `cheat_activation_rules: Optional[list[str]]`(激活条件列表)
- `cheat_first_activation_chapter: Optional[str]`

**接入点**:
- 在 BrainstormAgent prompt 加金手指识别要求;`WriterAgent` 写金手指首秀时,prompt 提示"以震撼感激活金手指"
- VolumePlanner 在 beat plan 中如某拍涉及金手指,加 `requires_cheat_activation: bool` 标记
- FastReview 验证:激活条件是否被遵守

**测试**:
- 单元测试: Entity cheat 字段持久化
- 单元测试: VolumePlanner 在 cheat 章节中加 requires_cheat_activation
- 集成测试: 金手指首秀章节的写作质量监控

### 4.5 节奏感(章节原型 + 可选拍阶段)

**新枚举 `ChapterArchetype`**: `action / setup / payoff / mixed`
- 加到 `ChapterPlan` / `VolumePlan` 的 chapter 级别
- VolumePlanner 在 plan 时为每章指定 archetype

**BeatPlan 扩展**(可选字段):
- `mood_phase: Optional[Enum[setup, tension, release, climax, cooldown]]`
- VolumePlanner 仅为"关键拍"指定(其他 beat 留 None)

**接入点**:
- WriterAgent 收到 chapter context 时,archetype 注入到 writing_rules 块:"本章是 [action] 章节,聚焦动作/打斗节奏"
- mood_phase 在 beat context 中注入:"这一拍是 [climax],需高强度对峙"

**测试**:
- 单元测试: ChapterPlan.archetype 字段持久化
- 单元测试: VolumePlanner 输出包含 archetype
- 单元测试: WriterAgent 收到 archetype 后 prompt 含对应指令

---

## §5 P2 架构升级:跨章实体连续性

### 5.1 目标

检测 3 类跨章实体漂移(用户决策):
- **名谐漂移**: 陆照 (ch1-30) → 陆昭 (ch31+)
- **身份漂移**: 陆照 ch1 是"师兄",ch50 被写成"师弟"
- **状态阶跃**: 陆照 ch1 是"凡人",ch20 突然"筑基期"无交代

### 5.2 数据模型扩展

**Entity 模型扩展**:
- `canonical_profile.identity_role: Optional[str]`(例如"陆照 = 师兄")

**沿用 EntityVersion** 现有模型,新增 `change_type` 字段分类:
- `power_level / location / relationship / status / identity_role / other`
- 用于判断"阶跃"

### 5.3 服务设计

**新服务 `CrossChapterContinuityService`**:

**Pre-write 部分**(用户决策:质量左移 + 双管齐下):
- 方法: `build_pre_write_constraints(novel_id, chapter_plan) -> str`
  1. 从 chapter_plan 解析本章将出现的实体列表
  2. 查每个实体的最近 N=3 个 EntityVersion
  3. 生成"实体连续性约束"提示块(确定性文本,无 LLM 调用)
  4. 格式:
     ```
     ### 实体连续性约束
     - 陆照: 上一状态 = 凡人, 实力 = 0; 身份 = 师兄。本章不得: 让其突然获得修为, 改变身份称谓
     - 玉佩: 上一状态 = 在陆照腰间; 本章不得: 改变其归属
     ```
- 接入: `ContextAgent.prepare_chapter_context()` 末尾追加此 block

**Post-write 部分**(FastReview 跨章检查):
- 方法: `detect_drift(novel_id, chapter_id, polished_text) -> list[DriftIssue]`
  1. 拉最近 5-10 章的章节文本
  2. 对本章文本中每个出现的实体,LLM 批量评估: 是否出现 3 类漂移
  3. 输出: `[{type, entity, severity, evidence, suggested_fix}]`
- 接入: `FastReviewAgent.review()` 末尾调用,结果加入 `FastReviewReport.cross_chapter_drift: list[DriftIssue]`
- `quality_gate_service`:`severity == "block"` 的项 → gate block

**LLM prompt**: `CROSS_CHAPTER_DRIFT_DETECTION_PROMPT`(Librarian 同款)
- 输入: 本章文本 + 最近 5-10 章文本 + 本章出现的实体列表(带历史状态)
- 输出 JSON: `[{entity_name, drift_type, severity, evidence_quote, suggested_fix}]`

### 5.4 测试

- 单元测试: build_pre_write_constraints 生成确定性文本
- 单元测试: detect_drift 调用 LLM 并解析
- 集成测试: pre-write 约束被注入到 writer context
- 集成测试: 模拟"陆照→陆昭"漂移,post-write 检测到

---

## §6 P2 架构升级:跨章意象追踪

### 6.1 目标

解决"碎石硌掌心 3 章出现 3 次""5 个'像'字比喻密集"等重复问题。

### 6.2 数据模型

**新表 `imagery_inventory`**:
- `id` UUID PK
- `novel_id` FK
- `chapter_id` FK
- `item` str(意象/比喻/口吻指纹)
- `item_type` enum (`physical_imagery / metaphor / author_voice / idiom`)
- `frequency_in_chapter` int(本章节出现次数)
- `extracted_at` TIMESTAMP

### 6.3 服务设计

**新服务 `ImageryInventoryService`**:

**Extract (生成后)**:
- 方法: `extract_and_store(novel_id, chapter_id, chapter_text) -> int` (返回存储条数)
- 1 次 LLM 调用(Librarian 同款),prompt: `IMAGERY_EXTRACTION_PROMPT`
  - 输入: 章节全文
  - 输出: `[{item, item_type, frequency_in_chapter}]`
- 批量 insert 到 imagery_inventory

**Feedback (写前)**:
- 方法: `build_avoidance_list(novel_id, current_chapter_id, window=5) -> str`
  1. 查最近 5 章的所有 imagery_inventory
  2. 按 `frequency * 出现章节数` 排序
  3. 取 top 20
  4. 格式化为提示文本:
     ```
     ### 本章应避免意象(最近 5 章已多次使用)
     - 碎石硌掌心(物理意象,4 次)
     - 像石子投入枯井(比喻,3 次)
     - 突然/竟然(口吻,6 次)
     ```
- 接入: `ContextAgent.prepare_chapter_context()` 末尾追加此 block(与实体连续性约束同位置)

**LLM prompt**: `IMAGERY_EXTRACTION_PROMPT`(Librarian 同款)
- 输出 JSON: `[{item, item_type, frequency_in_chapter}]`

### 6.4 测试

- 单元测试: extract_and_store 调 LLM 并 insert
- 单元测试: build_avoidance_list 排序 + 格式化
- 集成测试: ContextAgent 注入 avoidance block
- 集成测试: 模拟"碎石硌掌心"出现 3 次,生成第 4 章时 avoidance 列表包含

---

## §7 UI 扩展

### 7.1 新视图

**`QualityTrendsV2View.vue`** (扩展现有 QualityTrendsView):
- 跨章质量指标聚合
- 含爽点达成率、钩子达成率、实体漂移事件数、意象重复 top 5

**`RCSViewerView.vue`** (新):
- 显示当前 novel 的滚动叙事摘要列表
- 每次更新的 prose + structured_json
- 可对比相邻两次

**`ImageryInventoryView.vue`** (新):
- 显示最近 N 章的意象库存
- top 重复意象列表
- 标记"过度使用"项

### 7.2 QualityRecommendationWidget 增强

- 加可展开"评分明细": Critic 5 维度分数 + 实际批评文本
- 加可展开"失败 beat 列表": coverage 结果 + drift 项
- 加可展开"未达成爽点": expected vs actual
- 接收 `recentIssueCounts` prop(配合 §1.3)

---

## §8 配置

**`llm_config.yaml` 新增 phase4 段**:
```yaml
phase4:
  rcs:
    enabled: true
    trigger_window_chapters: 5
    max_synopsis_chars: 2000
    llm_client: root_cause_analyzer  # 与 librarian 同款
  cross_chapter_continuity:
    enabled: true
    pre_write_window: 3
    post_write_window: 5
    llm_client: root_cause_analyzer
  imagery_inventory:
    enabled: true
    avoidance_window: 5
    avoidance_top_n: 20
    llm_client: root_cause_analyzer
  web_novel:
    chapter_archetypes: [action, setup, payoff, mixed]
    mood_phases: [setup, tension, release, climax, cooldown]
    thrill_types: [face_slap, show_off, level_up, reward_gain, revelation, revenge, plot_twist, recognition]
  writer:
    default_drafting_mode: beat_by_beat
    temperature: 0.75
  guard:
    fail_open_on_timeout: false
```

**`quality_config.py`**:
- `get_phase4_config() -> dict`
- 与 `get_phase3_config` 同模式

---

## §9 验收清单(本期末必达)

- [ ] 1681 → 1900+ 测试通过(预期 +30-50 任务对应)
- [ ] 8 个 agent 全部走 `get_with_chapter_id`,A/B 测试真生效
- [ ] WriterAgent 默认走 beat_by_beat
- [ ] QualityRecommendationWidget 发送 recent_issue_counts
- [ ] FastReviewAgent 调用 BeatCoverageValidator
- [ ] BeatCoverageValidator block 结果进入 gate
- [ ] RCS 服务完整可用,ContextAgent 读到 rolling_synopsis_cache
- [ ] 跨章实体连续性 pre-write + post-write 双管齐下
- [ ] 跨章意象库存 + avoidance list 完整可用
- [ ] 末拍 boundary card required_open_question 强制校验
- [ ] thrill_point 表 + Planner 预标 + FastReview 验证
- [ ] Entity.cheat_ability 字段可用
- [ ] ChapterPlan.archetype + BeatPlan.mood_phase 可用
- [ ] prompt caching 实现(LLMFactory)
- [ ] 失败闭门策略默认启用
- [ ] 关键 prompt 含 few-shot

---

## §10 实施计划(预览,详细 plan 在 docs/superpowers/plans/)

预计 28-32 任务,大致分 8 个 wave:

**Wave 1 (P0 修复, 6 任务)**:
1. A/B 接入 (8 agent 改 1 行)
2. 强制 beat_by_beat
3. recent_issue_counts UI
4. BeatCoverageValidator 接入
5. Writer 温度调到 0.75
6. 失败闭门策略

**Wave 2 (配置级 quick wins, 4 任务)**:
7. CONTEXT_AGENT_PROMPT 重写
8. WRITER/CRITIC/EDITOR prompt few-shot
9. Librarian 软状态 pass 提升
10. llm_config.yaml phase4 段 + quality_config 加载

**Wave 3 (RCS 架构, 5 任务)**:
11. chapter_synopsis model + migration
12. ROLLING_SYNOPSIS_PROMPT + ENTITY_CHANGE_IMPORTANCE_PROMPT
13. RollingChapterSynopsisService
14. LibrarianAgent.persist 触发 RCS
15. ContextAgent._narrative_source_from_checkpoint 读 rolling_synopsis_cache

**Wave 4 (网文规则, 6 任务)**:
16. BeatBoundaryCard.required_open_question + 末拍校验
17. VolumePlanner prompt 末拍钩子要求
18. WriterAgent 末拍钩子强调
19. FastReview 钩子达成验证
20. thrill_point model + migration
21. VolumePlanner expected_thrills + FastReview 验证

**Wave 5 (金手指 + 节奏, 4 任务)**:
22. Entity.cheat_ability 字段
23. VolumePlanner cheat 章节标记
24. ChapterPlan.archetype + BeatPlan.mood_phase
25. WriterAgent 接收 archetype + mood_phase

**Wave 6 (跨章实体连续性, 4 任务)**:
26. CrossChapterContinuityService
27. CROSS_CHAPTER_DRIFT_DETECTION_PROMPT
28. ContextAgent build_pre_write_constraints
29. FastReview detect_drift

**Wave 7 (跨章意象追踪, 3 任务)**:
30. imagery_inventory model + migration
31. ImageryInventoryService + IMAGERY_EXTRACTION_PROMPT
32. ContextAgent build_avoidance_list

**Wave 8 (UI, 5 任务)**:
33. QualityRecommendationWidget 增强(recentIssueCounts + 评分明细展开)
34. QualityTrendsV2View
35. RCSViewerView
36. ImageryInventoryView
37. 端到端测试 + 全量验证

详细 plan 在 writing-plans 阶段生成。
