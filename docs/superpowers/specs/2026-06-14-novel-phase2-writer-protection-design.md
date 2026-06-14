# 小说产出质量优化 — 阶段二:Writer 防护设计文档

**状态:** 设计稿（待用户确认）
**日期:** 2026-06-14
**所属综合方案:** 阶段二（共三阶段：可观测性 → Writer 防护 → Prompt 工程化）
**前置依赖:** 阶段一完成（ChapterQualityMetric 数据层 + 5 个 API + 推荐服务 + Issue 提示表）

---

## TL;DR

在保持 WriterAgent 整章一次性产出的前提下，用 **预写加固 + 事后验证** 把防护夹在中间，并把现有的推荐服务从"展示"升级为"自动调度重写"。新增 3 个核心组件（`BeatCoverageValidator` / `RecommendationWirer` / `RewriteFeedbackWriter`）+ 1 个 `Chapter.attempt_index` 字段（带迁移）+ 1 个状态值（`rewriting`）+ 1 个配置键（`max_auto_rewrites`）；不动 editor_agent 的 hardcode（独立 PR）；不引入 beat-by-beat 模式（与现状一致）；复用阶段一的 `BeatBoundaryCard` / `BeatBoundaryService` / `WriterAgent._build_whole_chapter_context_message` 已实现的节拍卡预写加固（仅加测试覆盖）。

**核心目标**：让 `reports/test-runs/inkos-md-zhutian-real-*/` 中反复出现的 `BEAT_BOUNDARY_VIOLATION` / `EVENT_ORDER_DRIFT` / `PLANNED_CHARACTER_DRIFT` 不再静默通过归档，而是在 2 次硬上限内被自动拦截 + 重写，或在第 2 次失败后强制转入人工。

---

## 1. 目标与非目标

### 1.1 目标

1. **整章产出后**做严格的事后验证（LLM-as-judge + 确定性回退），把违规写入 `chapter_quality_metrics.issue_codes`
2. **预写加固（强化）**：阶段一已实现 `BeatBoundaryCard` → Writer prompt 渲染（`WriterAgent._build_whole_chapter_context_message:945-988`），阶段二加 fail-soft try/except + INFO 日志 + 回归测试覆盖，确保实际生效
3. **自动重写闭环**：当 `RecommendationService` 返回 `minor_repair` / `major_repair` 且未超过 `max_auto_rewrites` 时，自动调度 `ChapterRewriteService.rewrite`
4. **硬上限收手**：超过 `max_auto_rewrites`（默认 2）次重写后，章节进入 `manual_review_required`，等人工
5. **可观测性延伸**：所有自动重写结果回写 `chapter_quality_metrics`（phase="rewrite"），前端可看全过程

### 1.2 非目标

- ❌ 改 `editor_agent.py` / `volume_planner.py` 的 hardcode（独立 PR）
- ❌ 整章异步 export 评估（独立评估任务）
- ❌ 改 beat-by-beat 写作模式（保持 `drafting_mode="whole_chapter"` 默认）
- ❌ Prompt 抽取 / 版本化 / A/B harness（阶段三）
- ❌ 替换静态 `issue_code_hints` 表为 LLM-driven 根因分析（阶段三）
- ❌ 改 `QualityGateService` 的现有逻辑（阶段一已替换 hardcode，不动）

---

## 2. 设计原则

1. **防护失败不阻塞写作**：所有防护层（节拍卡渲染、LLM 验证、确定性回退）失败时降级，绝不抛
2. **真实状态以 DB 为准**：`chapter.attempt_index` 每次重读，不信任前端 / 缓存
3. **重复入队幂等**：并发触发重写时复用现有 active job，不重复排队
4. **配置错误启动期暴露**：复用阶段一 `ConfigError` 模式，缺 `recommendation.max_auto_rewrites` 启动即崩
5. **不破坏阶段一契约**：`recommendation_service` 的接口签名不变，UI 的 `QualityRecommendationWidget` API 不变
6. **最小新增依赖**：本阶段不引入新第三方库

---

## 3. 架构总览

```
[ContextAgent] ── context (含 chapter_plan.beat_boundary_cards) ──→ [WriterAgent._write_whole_chapter]
                                   │
                                   ├─ prompt = _build_whole_chapter_context_message(context)
                                   │     └─ 已含节拍卡渲染（945-988 行，阶段二强化 fail-soft + 日志）
                                   │
                                   ├─ LLM.acomplete(messages) → raw_draft
                                   │
                                   └─ coverage = BeatCoverageValidator.validate(beat_boundary_cards, raw_draft)
                                         └─ LLM 失败 → 确定性回退
                                              │
                                              ↓
                                   issues: list[BeatCoverageResult]
                                              │
                                              ↓
                                   FastReviewAgent.finalize:
                                     record(metric_input{issue_codes=issues.to_codes()})
                                              ↓
                                     RecommendationWirer.evaluate_and_dispatch:
                                       recommend() → ACCEPT / MINOR / MAJOR / STOP
                                       ↓ (decision table 4.4)
                                     → accept | auto_rewrite_queued | manual_review
                                              ↓
                                     chapter.quality_status 切换
                                              ↓
                                     Phase 推进 → [LibrarianAgent] / [rewriting loop] / [manual_review]
```

### 阶段二新增组件一览

| 组件 | 类型 | 用途 |
|------|------|------|
| `BeatCoverageValidator` | 新服务（`src/novel_dev/services/beat_coverage_validator.py`） | LLM-as-judge + 确定性回退，返回结构化覆盖率 |
| `PreWriteHardener` | `WriterAgent` 现有方法扩展 | 强化 `_build_whole_chapter_context_message` 的节拍卡渲染（fail-soft + 日志） |
| `RecommendationWirer` | 新服务 / 调度器（`src/novel_dev/services/recommendation_wirer.py`） | 在 `FastReviewAgent.finalize` 后跑推荐 → 决定是否调重写 |
| `RewriteFeedbackWriter` | `ChapterRewriteService` 钩子 | 重写完成后把结果写回 `chapter_quality_metrics` |

**复用阶段一已有**：`BeatBoundaryCard` / `BeatBoundaryService` / `ContextAgent._attach_beat_boundary_cards` / `WriterAgent._build_whole_chapter_context_message`（945-988 行）。阶段二不重写这些，只复用 + 加测试覆盖。

### 复用阶段一接口（不动）

- `ChapterQualityMetric.issue_codes` —— 阶段二写入新检测出的违规码
- `Chapter.attempt_index` —— 阶段二新增字段，记录当前重试次数（`RecommendationWirer` 决策表的输入）
- `ChapterQualityMetric.attempt_index` —— 与 `Chapter.attempt_index` 同步，用于 `issue_codes` 行级追溯
- `RecommendationService.stop_and_inspect` —— 超过 N 次重写的收手信号
- `Chapter.quality_status = "manual_review_required"` —— 阶段一已支持的状态值
- `ChapterRewriteService.rewrite` —— 现有重写服务，阶段二不重写它，只调度它

---

## 4. 组件详细规格

### 4.1 复用阶段一 `BeatBoundaryCard`（不新建）

**位置**：`src/novel_dev/schemas/quality.py:42`（已存在）

阶段一已实现完整的节拍边界卡链路：

- 模型：`BeatBoundaryCard`（`schemas/quality.py:42`），字段：`beat_index` / `must_cover` / `allowed_materials` / `allowed_bridge_details` / `forbidden_materials` / `reveal_boundary` / `ending_policy`
- 服务：`BeatBoundaryService.build_cards(chapter_plan)`（`services/beat_boundary_service.py:39`），从 `chapter_plan.beats` 渲染成 `List[BeatBoundaryCard]`
- 上下文注入：`ContextAgent._attach_beat_boundary_cards()`（`agents/context_agent.py:572`）自动调用，把卡写入 `ChapterPlan.beat_boundary_cards`
- 提示词渲染：`WriterAgent._build_whole_chapter_context_message`（`agents/writer_agent.py:945-988`）已经把每张卡的 `must_cover` / `allowed_materials` / `forbidden_materials` / `reveal_boundary` / `ending_policy` 拼到 prompt 的"整章写作合同"段

**阶段二不新建 `BeatCard` 模型**——直接消费 `ChapterPlan.beat_boundary_cards`（类型 `List[BeatBoundaryCard]`）。

**契约**：

- `BeatBoundaryService.build_cards` 失败 / `beat_boundary_cards` 为空 → `BeatCoverageValidator` 走确定性回退
- 防御性：`BeatBoundaryCard` 字段缺失已在阶段一 `_REQUIRED_THRESHOLD_KEYS` 之外通过 Pydantic 默认值处理，无需再校验

**`BeatCoverageValidator` 的输入契约**：`(beat_cards: list[BeatBoundaryCard], draft_text: str) -> list[BeatCoverageResult]`，把类型从阶段一的 `BeatBoundaryCard` 替换掉原先设想的 `BeatCard`。

### 4.2 `BeatCoverageValidator` (新服务)

**位置**：`src/novel_dev/services/beat_coverage_validator.py`（新建）

```python
@dataclass
class BeatCoverageResult:
    beat_index: int
    covered: bool
    deviation: str | None          # 没覆盖时填偏差描述
    severity: Literal["ok", "warn", "block"]

class BeatCoverageValidator:
    def __init__(self, session, llm_client=None, use_llm: bool = True):
        self.session = session
        self.llm = llm_client         # 可注入
        self.use_llm = use_llm          # 配置开关

    async def validate(
        self, beat_cards: list[BeatBoundaryCard], draft_text: str
    ) -> list[BeatCoverageResult]: ...
```

**双路径**：

- **LLM 路径（默认）**：一次 LLM 调用，prompt 喂 `BeatBoundaryCard[]` + 整章文本，要求逐 beat 返回 `{beat_index, covered, deviation, severity}` JSON 数组。复用 `call_and_parse` helper（阶段一已存在）做 markdown 剥离 + JSON 解析 + retry
- **确定性回退**：若 `use_llm=False` 或 LLM 调用失败（捕获所有 `Exception`，包括 `httpx.ConnectError` / `TimeoutError` / `JSONDecodeError` / `ValueError` 等），遍历每张卡：
  - 关键词覆盖判定：`matched = count(must_cover 关键词出现在文本中)`，`covered = (len(must_cover) == 0) or (matched / len(must_cover) >= 0.6)`
  - `forbidden_materials` 任一关键词在文本里出现 → 该 beat `severity=block`、`covered=False`
  - 全部 `must_cover` 都覆盖且无 forbidden 命中 → `covered=True, severity=ok`
  - 部分覆盖但未触发 forbidden → `covered=False, severity=warn`
  - 一张卡没有 `must_cover` 时跳过该张（避免空集除零）

**严重度 → IssueCode 映射**：

| severity | QualityIssueCode |
|----------|------------------|
| `ok` | 不写 |
| `warn` | `EVENT_ORDER_DRIFT`（默认）/ `HUMANITY_LOW`（deviation 涉及人物时） |
| `block` | `BEAT_BOUNDARY_VIOLATION`（默认）/ `PLANNED_CHARACTER_DRIFT`（deviation 涉及人物时） |

**契约**：

- 不抛异常（捕获所有 `Exception`）
- LLM 失败时 log warning + 走确定性
- 双重降级（`use_llm=False` 且 `beat_cards=[]`）→ 全部 `covered=True` + deviation 标记

### 4.3 `PreWriteHardener` (复用 + 强化 `WriterAgent` 现有节拍卡渲染)

**位置**：`src/novel_dev/agents/writer_agent.py` 第 945-988 行的现有代码（**不新建独立方法**）。

阶段一已经在 `_build_whole_chapter_context_message` 里实现了节拍卡预写加固。**阶段二的工作**：

1. **确认现有渲染完整性**：检查 `must_cover` / `allowed_materials` / `forbidden_materials` / `reveal_boundary` / `ending_policy` 五个字段全部进 prompt（现已有 945-988 行实现，阶段二只需要补回归测试）
2. **强化 fail-soft 行为**：单张卡渲染抛异常 → log warning，跳过该卡；不破坏主流程
3. **强化日志**：在 prompt 拼接完成后 log INFO（含 `chapter_id` / `beat_cards_count`），方便追踪是否真的把节拍卡喂给了 LLM

**契约**：

- 输入：`context: ChapterContext`（其中 `context.chapter_plan.beat_boundary_cards` 已由 ContextAgent 注入）
- 输出：现有 `_build_whole_chapter_context_message` 的返回（Markdown 字符串），**不修改返回结构**（向后兼容）
- `beat_boundary_cards` 为空 → 不追加节拍段，原样返回基础 prompt（阶段一已实现）
- 单张卡渲染失败 → log warning，跳过该卡，继续渲染其他
- 不动现有 `_build_whole_chapter_context_message` 内部结构（向后兼容）

**节拍卡渲染格式（阶段一已存在，阶段二不重写）**：

```markdown
### 整章写作合同
#### beat 0
- 摘要: ...
- 情绪: ...
- 关键实体: ...
- 必须覆盖: ...；...；...
- 允许材料: ...、...、...
- 允许桥接: ...；...
- 禁止越界: ...；...
- 信息释放边界: ...
- 停点策略: ...
```

### 4.4 `RecommendationWirer` (新服务)

**位置**：`src/novel_dev/services/recommendation_wirer.py`（新建）

```python
class RecommendationWirer:
    def __init__(self, session, max_auto_rewrites: int = 2):
        self.session = session
        self.max_auto_rewrites = max_auto_rewrites  # 来自 quality_config

    async def evaluate_and_dispatch(
        self, novel_id: str, chapter_id: str
    ) -> WireResult: ...

@dataclass
class WireResult:
    action: Literal["accept", "auto_rewrite_queued", "manual_review"]
    recommendation: Recommendation
    rewrite_job_id: str | None
```

**逻辑**：

1. 查 `Chapter` 当前行，得到 `final_review_score` / `quality_status` / `score_breakdown` / `id`（这是 `RecommendationService` 的输入契约）
2. 查 `Chapter.attempt_index`（阶段二新增字段，见 11.1）作为当前重试次数
3. 跑 `RecommendationService.recommend(accept_with_warn=False)` —— 拿推荐 + 置信度
4. **决策表**：

| 推荐 | attempt < N | 决策 |
|------|------|------|
| `accept` | — | `accept` |
| `minor_repair` | 是 | `auto_rewrite_queued` |
| `minor_repair` | 否 | `manual_review` |
| `major_repair` | 是 | `auto_rewrite_queued` |
| `major_repair` | 否 | `manual_review` |
| `stop_and_inspect` | — | `manual_review`（不论 attempt） |

5. 若 `auto_rewrite_queued`：调 `ChapterRewriteService.rewrite(novel_id, chapter_id)`，返回 `rewrite_job_id`，并 `chapter.attempt_index += 1`

**配置**：`max_auto_rewrites` 默认 2，从 `quality_config.recommendation.max_auto_rewrites` 读取。

**attempt 计数漂移保护**：若 `chapter.attempt_index > 5`（> `max_auto_rewrites + 3`），强制 `manual_review` + log error。

### 4.5 `RewriteFeedbackWriter` (`ChapterRewriteService` 钩子)

**位置**：`src/novel_dev/services/chapter_rewrite_service.py` 修改

在 `rewrite()` 完成后（所有阶段跑完），追加：

```python
await QualityMetricsService(session).record(QualityMetricInput(
    chapter_id=chapter_id,
    novel_id=novel_id,
    phase="rewrite",
    attempt_index=chapter.attempt_index + 1,
    overall_score=chapter.fast_review_score,
    gate_status=chapter.quality_status,
    issue_codes=extract_remaining_issues(chapter.fast_review_feedback),
    dimension_feedback=chapter.fast_review_feedback,
    model_version=llm_config,
    prompt_version=prompt_version,
))
```

**契约**：

- 不重写 `ChapterRewriteService` 的核心循环
- 终态钩子加一行 metric 记录
- `record()` 抛 `IntegrityError` → log warning，不破坏重写结果
- `extract_remaining_issues()` 工具函数：从 `fast_review_feedback` 提取尚未解决的 issue 码

---

## 5. 数据流

### 5.1 正常路径（无问题，accept）

```
[ContextAgent] ── context (含 chapter_plan.beat_boundary_cards) ──→ [WriterAgent._write_whole_chapter]
                                   │
                                   ├─ prompt = _build_whole_chapter_context_message(context)
                                   │     └─ 已含节拍卡渲染（945-988 行）
                                   │
                                   ├─ LLM.acomplete(messages) → raw_draft
                                   │
                                   └─ coverage = BeatCoverageValidator.validate(beat_boundary_cards, raw_draft)
                                              ↓
                                   issues: list[BeatCoverageResult]
                                              ↓
                                   FastReviewAgent.finalize:
                                     record(metric_input{issue_codes=issues.to_codes()})
                                              ↓
                                     RecommendationWirer.evaluate_and_dispatch:
                                       recommend() → ACCEPT
                                       → return WireResult(action="accept")
                                              ↓
                                     Chapter.quality_status = "pass"
                                              ↓
                                     Phase 推进 → [LibrarianAgent]
```

**关键不变量**：metric 行必然写入，无论 `beat_boundary_cards` 是否成功渲染、LLM 验证是否成功。

### 5.2 自动重写路径（minor/major）

```
                  (接 5.1 末尾,推荐 = minor_repair)
                                     ↓
RecommendationWirer:
  attempt = chapter.attempt_index (e.g. 0)
  if attempt < max_auto_rewrites (default 2):
     → wire to ChapterRewriteService.rewrite(novel_id, chapter_id)
         - 创建 GenerationJob (CHAPTER_REWRITE_JOB)
         - schedule_generation_job
         - chapter.attempt_index += 1（DB 持久化）
         - chapter.quality_status = "rewriting"（新状态值）
     return WireResult(action="auto_rewrite_queued", rewrite_job_id=...)
                                     ↓
[Phase 暂停在 fast_reviewing]
                                     ↓
[Job worker 拉起]
  → ChapterRewriteService.rewrite():
      - EditorAgent.polish_standalone()
      - FastReviewAgent 复测
      - 写新 metric 行 (phase="rewrite", attempt_index=N+1)
      - RewriteFeedbackWriter.record(...)
                                     ↓
[Phase 回到 fast_reviewing]
  → FastReviewAgent.finalize (第二次)
  → RecommendationWirer.evaluate_and_dispatch (attempt=1)
      - 若仍 minor/major 且 attempt < 2: 再次入队
      - 若仍 minor/major 且 attempt >= 2: → manual_review
      - 若 accept: → pass
```

### 5.3 收手路径（attempt 用尽 / stop_and_inspect）

```
RecommendationWirer (attempt >= max_auto_rewrites OR 推荐=stop_and_inspect):
   → action = "manual_review"
   → chapter.quality_status = "manual_review_required"
   → 不入 rewrite 队列
   → log.warning("Quality gate hit stop_and_inspect", extra={...})
                                     ↓
[Phase 暂停]
                                     ↓
[前端] DashboardHero / QualityRecommendationWidget 显示:
   "本章需人工介入：连续 N 次未达标"
   提供两个按钮:
   - "继续重试" (人工确认) → 把 attempt 计数清零，再跑一次推荐
   - "接受当前版本" → 强制 pass，进 LibrarianAgent
```

**关键不变量**：超 N 次后**永不**自动重试；用户必须显式操作。

### 5.4 LLM-as-judge 失败 / 不可用

```
BeatCoverageValidator.validate(beat_boundary_cards, draft):
  try:
     result = await self.llm_judge(beat_boundary_cards, draft)  # 一次 LLM 调用
  except (Exception) as e:   # 包括 httpx.ConnectError / TimeoutError / JSONDecodeError / ValueError
     log.warning("Beat coverage LLM judge failed, falling back", extra={...})
     result = self._deterministic_check(beat_boundary_cards, draft)
  return result
```

`use_llm=False`（配置开关）→ 跳过 try，直接确定性检查。**确定性检查也失败**（`beat_boundary_cards` 为空）→ 返回所有 beat `covered=True`（不阻断，但记 INFO log，让用户知道降级了）。

### 5.5 状态机变化

```
                ┌──── pass ──────────────→ [librarian]
                │
[drafting] ──→  [fast_reviewing] ──→ (pass)
                │      │
                │      └─ (min/maj) attempt<N → [rewriting] ──→ [fast_reviewing]
                │            │                          (loop back)
                │            └─ attempt>=N OR stop ──→ [manual_review_required]
                │                                       ├─ "继续重试" → 清零 attempt
                │                                       └─ "接受当前版本" → pass
                ↓
            (上述任何路径都可能进 librarian 或 manual_review)
```

> 说明：`RecommendationWirer` 调用 `RecommendationService.recommend(accept_with_warn=False)`，warn 状态不会自动 pass——会被推为 minor_repair，从而走重写分支（与上述状态机一致）。

`chapter.quality_status` 取值集扩充（阶段一已有的 `pass` / `warn` / `block` / `manual_review_required` / `unchecked` 不变）：

- 新增 `"rewriting"` —— 重写进行中（前端可显示 spinner）
- 不修改其它值

### 5.6 配置数据流

`llm_config.yaml` 在 `quality_thresholds.recommendation` 块下新增 1 个键：

```yaml
quality_thresholds:
  recommendation:
    # 阶段一已有
    stop_after_attempts: 3
    pattern_issue_threshold: 3
    minor_repair_min_score: 78
    minor_repair_min_critical: 72
    major_repair_min_score: 70
    # 阶段二新增
    max_auto_rewrites: 2            # 硬上限
```

LLM 开关不进 yaml（`use_llm_beat_coverage` 不引入 —— 默认开 LLM，配置开关放到后续优化 PR）。理由：减少本阶段配置复杂度；想关 LLM 验证时直接改 `BeatCoverageValidator.__init__` 默认值即可。

读路径：`get_quality_config()["recommendation"]["max_auto_rewrites"]`。`recommendation` 块本身在阶段一已在 `_REQUIRED_THRESHOLD_KEYS` 中存在，所以 `get_quality_config()` 不会因此 fail；但 `max_auto_rewrites` 子键缺失时，`RecommendationWirer.__init__` 主动读该键会抛 `KeyError`。可在 `__init__` 加显式检查并抛 `ConfigError("Missing required key quality_thresholds.recommendation.max_auto_rewrites")` 让启动期即崩。

---

## 6. 错误处理

按失败层级组织（内到外），每条说明：触发条件 / 检测点 / 处理 / 用户可见行为。

### 6.1 `BeatBoundaryCard` 渲染失败

- **触发**：`BeatBoundaryService.build_cards()` 抛异常，或 `chapter_plan.beat_boundary_cards` 为空（上游失败）
- **检测**：阶段一已有 `_attach_beat_boundary_cards` 内部 try/except，失败时 `beat_boundary_cards = []`（不抛）
- **处理**：
  - `beat_boundary_cards = []` → `WriterAgent._build_whole_chapter_context_message` 不追加节拍段，原样返回基础 prompt（向后兼容）
  - 单张卡渲染失败 → 阶段一实现是 `log.warning` + 跳过该卡，阶段二加 INFO 日志（含 `chapter_id` / `beat_cards_count`）
- **用户可见**：无；内部降级，不阻断

### 6.2 LLM-as-judge 失败

- **触发**：`BeatCoverageValidator.validate` 调 LLM 时：`httpx.ConnectError` / `TimeoutError` / `JSONDecodeError` / `LLMCallError`
- **检测**：try/except，捕获所有 `Exception`（不细分类别）
- **处理**：
  - 走确定性回退（关键词命中检查）
  - 写 `log.warning(extra={chapter_id, fallback: "deterministic", reason: repr(e)})`
  - **绝不抛出** —— 防护层失败不能阻塞写作
- **用户可见**：无；metric 行的 `issue_codes` 可能是空（如果确定性也判定 covered）

### 6.3 确定性回退也失败

- **触发**：`beat_boundary_cards = []`（6.1 失败）且 LLM judge 也失败（6.2）→ 双重降级
- **检测**：`BeatCoverageValidator.validate` 在开头判断 `if not beat_boundary_cards and not self.use_llm: return [BeatCoverageResult(covered=True, deviation="no_cards_no_llm")]`
- **处理**：返回所有 beat `covered=True`、deviation 标记降级；不写入 `issue_codes`
- **用户可见**：无；前端 `QualityRecommendationWidget` 不会显示 "无覆盖"，但 `QualityRunsView` 看 `issue_codes=[]` 可知降级发生过

### 6.4 `RecommendationWirer.evaluate_and_dispatch` 失败

- **触发**：`RecommendationService.recommend()` 抛异常（罕见，因规则引擎纯本地），或 `Chapter` 找不到
- **检测**：try/except `Exception`
- **处理**：
  - **不写 `quality_status`**（保持原值），**不调度重写**
  - 写 `log.error("RecommendationWirer failed", extra={chapter_id, error: repr(e)})`
  - 返回 `WireResult(action="manual_review", recommendation=None, rewrite_job_id=None)` 兜底（fail-safe：宁可人工也不要漏重）
- **用户可见**：质量门暂时阻塞；前端 `QualityRecommendationWidget` 显示"决策失败，请人工处理"

### 6.5 `ChapterRewriteService.rewrite` 排队失败

- **触发**：`GenerationJobRepository.create()` 抛 `IntegrityError`（重复 job），或 `schedule_generation_job` 失败
- **检测**：`RecommendationWirer` 调 `rewrite()` 时 try/except
- **处理**：
  - 捕获 `IntegrityError` → 检查是否已有 active job → 若有，**复用现有 job_id**（不去重排队）
  - 其他异常 → 写 `log.error`，`WireResult(action="manual_review")`
  - 章节 `quality_status` 不变（不强行改 manual_review —— 这是排队的临时失败）
- **用户可见**：短暂 spinner → 正常进入 rewriting 状态 / 或 manual_review

### 6.6 并发重写竞态

- **触发**：两次 `FastReviewAgent.finalize` 几乎同时跑（理论可能：异步 job 重叠）
- **检测**：`ChapterRewriteService.rewrite()` 内部已有 `get_active(novel_id, CHAPTER_REWRITE_JOB)` 检查 —— 复用阶段一基础设施
- **处理**：第二次调用直接抛 `409`（已有 rewrite 在跑），`RecommendationWirer` 捕获后返回 `WireResult(action="auto_rewrite_queued", rewrite_job_id=existing_job_id)` —— 不会重复入队
- **用户可见**：无；幂等行为

### 6.7 `attempt_index` 计数漂移

- **触发**：job 失败 / 重启 / 并发导致 `chapter.attempt_index` 计数错乱
- **检测**：`RecommendationWirer` 重新查 `chapter.attempt_index`（DB 读，不信任前端 / 不信任缓存）
- **处理**：
  - 真实值 = `chapter.attempt_index`（DB 读）
  - 若 `attempt_index` > 5（> `max_auto_rewrites + 3`）→ 触发"强制 manual_review"分支，`log.error("attempt_index drift detected")`
- **用户可见**：manual_review 状态

### 6.8 manual_review 状态卡死

- **触发**：用户从不点"继续重试"或"接受当前版本"，章节永远停在 `manual_review_required`
- **检测**：**不自动检测**（避免误操作）
- **处理**：纯人工；前端 `QualityRecommendationWidget` 在 manual_review 状态下显示**一直可见的**操作按钮
- **用户可见**：手动处理（接受/继续/编辑后重试）

### 6.9 配置缺失

- **触发**：`llm_config.yaml` 缺 `quality_thresholds.recommendation.max_auto_rewrites`
- **检测**：`RecommendationWirer.__init__` 显式 `KeyError` 检查，抛 `ConfigError`（阶段一模式）
- **处理**：启动失败，开发环境立即报错；生产环境部署前必须先改 yaml
- **用户可见**：服务起不来

### 6.10 DB 完整性错误

- **触发**：`chapter_quality_metrics` 写入时 `IntegrityError`（FK 不存在、`novel_id` 缺失）
- **检测**：`QualityMetricsService.record` 内 try/except，捕获 `IntegrityError`
- **处理**：复用阶段一模式 —— `log.warning` + 不阻断上游（`FastReviewAgent._finalize_and_record_metric` 已有此逻辑）
- **用户可见**：无；metric 缺失，UI 不可见

### 6.11 错误处理总原则

| 原则 | 体现 |
|------|------|
| 防护层失败不阻塞写作 | 6.2, 6.3, 6.4 |
| 重复入队幂等 | 6.6 |
| 真实状态以 DB 为准 | 6.7 |
| 配置错误启动期暴露 | 6.9 |
| 计量层失败不影响主流程 | 6.10 |
| 不可恢复 → 收手 + 人工 | 6.4, 6.7, 6.8 |

---

## 7. 测试策略

按测试金字塔组织，从快到慢、覆盖面从窄到宽。

### 7.1 单元测试（每个新组件独立）

#### `BeatBoundaryCard` 已有测试（阶段一）+ 输入契约测试（阶段二）

阶段一已有 `test_beat_boundary_service.py` 等。阶段二新增：

- `test_beat_coverage_validator_accepts_beat_boundary_card_list`: 喂 `list[BeatBoundaryCard]`（来自 `chapter_plan.beat_boundary_cards`），验证 `BeatCoverageResult[]` 长度匹配
- `test_beat_coverage_validator_handles_empty_beat_boundary_cards`: 喂 `[]` → 走确定性回退（即使 LLM 失败也不抛）

#### `BeatCoverageValidator`

- `test_validate_with_llm_happy_path`: mock LLM 返回 5 个 beat 的合规 JSON → 返回 `BeatCoverageResult[]` 长度匹配
- `test_validate_with_llm_markdown_wrapped`: LLM 返回 ```json ... ``` 包裹 → 正确剥离
- `test_validate_with_llm_invalid_json`: LLM 返乱码 → 走确定性回退 + log warning
- `test_validate_with_llm_timeout`: LLM 超时 → 走确定性回退
- `test_validate_use_llm_false`: 配置开关关 → 直接确定性（不调 LLM）
- `test_validate_deterministic_full_coverage`: 文本包含所有 `must_cover` 关键词 → 全部 covered=True
- `test_validate_deterministic_missing_keyword`: 缺 1 个 `must_cover` → 该 beat covered=False, severity=warn
- `test_validate_deterministic_forbidden_match`: 文本出现 `forbidden_materials` → 该 beat severity=block
- `test_validate_empty_beat_boundary_cards_and_no_llm`: 双重降级 → 全部 covered=True + deviation 标记
- `test_validate_returns_quality_issue_codes`: 严重度 → `QualityIssueCode` 映射正确

#### `PreWriteHardener` (回归 `WriterAgent._build_whole_chapter_context_message`)

- `test_hardened_prompt_includes_beat_boundary_cards`: 注入 3 张 `BeatBoundaryCard` → 文本包含 3 个 `#### beat N` 标头（沿用阶段一格式）
- `test_hardened_prompt_empty_boundary_cards_returns_base_prompt`: `beat_boundary_cards=[]` → 不追加节拍段
- `test_hardened_prompt_render_failure_skipped`: 卡渲染失败 → log warning，不抛出（fail-soft）
- `test_hardened_prompt_logs_card_count_info`: 渲染完成 INFO 日志包含 `beat_cards_count` 字段
- `test_hardened_prompt_preserves_base_structure`: 原有 context 内容仍存在

#### `RecommendationWirer`

- `test_wirer_accept_passes_through`: 规则返回 accept → action=accept, rewrite_job_id=None
- `test_wirer_minor_repair_within_budget_queues_rewrite`: attempt=0, max=2 → 调 `ChapterRewriteService.rewrite` 排队
- `test_wirer_minor_repair_exceeds_budget_manual`: attempt=2, max=2 → action=manual_review
- `test_wirer_major_repair_within_budget_queues_rewrite`: 同 minor
- `test_wirer_major_repair_exceeds_budget_manual`: 同 minor
- `test_wirer_stop_and_inspect_always_manual`: 推荐=stop_and_inspect 不论 attempt
- `test_wirer_recommendation_service_failure_failsafe`: `recommend()` 抛异常 → action=manual_review, log error
- `test_wirer_rewrite_queue_failure_failsafe`: `rewrite()` 抛 IntegrityError → 复用 active job_id（如有）
- `test_wirer_respects_max_auto_rewrites_config`: 改配置为 3 → attempt=2 仍 queue
- `test_wirer_attempt_index_drift_detection`: attempt_index=10 → 强制 manual_review + log error

#### `RewriteFeedbackWriter` (`ChapterRewriteService` 钩子)

- `test_rewrite_writes_metric_with_remaining_issues`: 重写后 fast_review 仍报 issue → metric 行的 `issue_codes` 反映
- `test_rewrite_writes_metric_with_phase_rewrite`: phase 字段 = "rewrite"
- `test_rewrite_writes_metric_attempt_incremented`: attempt_index 递增
- `test_rewrite_metric_write_failure_does_not_break_rewrite`: `record()` 抛 → log warning，重写结果仍保留
- `test_rewrite_no_remaining_issues_metric`: 重写后 pass → `issue_codes=[]`, gate_status=pass

### 7.2 集成测试（Phase 1 设施复用）

#### `tests/test_agents/test_whole_chapter_validation.py`

端到端跑 `_write_whole_chapter`，mock LLM：

- 写"完美章节"（覆盖所有 beat） → 无 issue_codes
- 写"跳到后续 beat"章节 → BEAT_BOUNDARY_VIOLATION
- 写"漏掉一个 beat"章节 → EVENT_ORDER_DRIFT
- 写"出现 forbidden 角色"章节 → PLANNED_CHARACTER_DRIFT

#### `tests/test_agents/test_auto_rewrite_loop.py`

完整重写闭环：

1. 写章节，fast_review 失败
2. `RecommendationWirer` 调度重写
3. rewrite job 跑完
4. fast_review 重测
5. 通过 → pass; 失败 → 再调一次 / 或进 manual_review

验证 `chapter.attempt_index` 正确递增；`chapter_quality_metrics` 写入多行（每次重写一行，phase=rewrite）。

### 7.3 E2E 测试（真实 Pipeline + 真实 LLM mock）

`tests/test_e2e/test_phase2_protection_loop.py`：

- 跑全 9 阶段 + 阶段二新增的"防护 + 自动重写"循环
- 准备 3 个 chapter 数据：
  - ch1: 干净章节 → 直接 pass
  - ch2: 触发 1 次重写 → 重写后 pass
  - ch3: 触发 2 次重写都失败 → manual_review
- 验证最终状态：ch1 pass、ch2 pass（attempt=1）、ch3 manual_review
- 验证 `chapter_quality_metrics` 行数：ch1 = 1, ch2 = 2, ch3 = 3

### 7.4 前端测试

`src/novel_dev/web/src/components/QualityRecommendationWidget.test.js`（扩展已有文件）：

- `test_widget_shows_rewriting_spinner_during_auto_rewrite`: action=auto_rewrite_queued → 显示 spinner
- `test_widget_shows_manual_review_buttons`: action=manual_review → "继续重试" / "接受当前版本" 按钮可见
- `test_widget_continue_retry_emits_event`: 点"继续重试" → emit `continue-retry` 事件
- `test_widget_accept_version_emits_event`: 点"接受当前版本" → emit `accept-version` 事件
- `test_widget_handles_404_gracefully`: novel 不存在 → 显示错误而非崩

Dashboard 测试：

- `test_dashboard_widget_hidden_when_no_chapter`: currentChapter 为空 → 隐藏 widget
- `test_dashboard_widget_shows_rewriting_state`: chapter.quality_status = "rewriting" → widget 显示对应状态

### 7.5 回归 / 防退化

- 跑全部 `tests/`（阶段一 + 阶段二）必须绿
- 重点关注：
  - `tests/test_smoke/test_full_pipeline_smoke.py`（阶段一冒烟）必须仍过
  - `tests/test_api/test_quality_routes.py`（阶段一 5 个 API 端点）必须仍过
  - `tests/test_api/test_quality_observability_e2e.py`（阶段一 E2E）必须仍过
- 性能：`_write_whole_chapter` 端到端延迟增加 ≤ 30%（LLM-as-judge 一次调用）

### 7.6 覆盖率目标

| 模块 | 目标 |
|------|------|
| `BeatCoverageValidator` | ≥ 95%（含 10 个测试用例） |
| `PreWriteHardener`（回归 `WriterAgent._build_whole_chapter_context_message`） | ≥ 90%（5 个回归测试） |
| `RecommendationWirer` | ≥ 95%（10+ 决策分支） |
| `RewriteFeedbackWriter` 钩子 | ≥ 90% |
| `BeatBoundaryCard` 阶段一已有测试 | 维持现有覆盖率，不需新增 |

### 7.7 已知不要测的

- ❌ 真实 LLM 调通（mock 即可）
- ❌ 前端视觉回归（用 `data-testid` 断言即可）
- ❌ 跨时区 / 跨进程并发（理论上 4.6 的幂等性已覆盖）

---

## 8. 迁移 / 部署计划

### 8.1 阶段（按风险递增）

1. **第一波**：新增组件 + 单元测试（不接线）
   - `BeatCoverageValidator` 服务（带测试）
   - `PreWriteHardener` 回归测试（不改 `_build_whole_chapter_context_message` 行为，仅加 fail-soft + INFO 日志）
   - 不接 `RecommendationWirer` / 不改推荐流程
   - 这一波发出去用户无感知

2. **第二波**：接线（不改用户行为）
   - `RecommendationWirer` 服务（带测试）
   - `FastReviewAgent.finalize` 后调 `RecommendationWirer`
   - **`max_auto_rewrites=0`**（默认不自动重写，保留旧行为）
   - `chapter.quality_status = "rewriting"` 状态值加入
   - 这一波发出去：防护层跑了，但都不自动重写

3. **第三波**：启用自动重写
   - 把 `max_auto_rewrites` 改成 2
   - 端到端测试
   - 前端 widget 加 rewriting spinner + manual_review 按钮

### 8.2 回滚策略

- 每波独立可回滚（git revert 到前一波 commit）
- 配置开关：`max_auto_rewrites=0` 一键回到"只展示不重写"
- 数据库：metric 表不变，无 schema 迁移

### 8.3 监控 / 告警（建议但本阶段不实施）

- 阶段二不发上线后 24h 的 metric 报表
- 关注：`auto_rewrite_queued` 占比、`manual_review` 占比、`attempt_index` 分布

---

## 9. 验收清单

### 9.1 功能

- [ ] `BeatCoverageValidator` 单元测试全过（10 用例）
- [ ] `PreWriteHardener` 回归测试全过（5 用例），不破坏现有 WriterAgent 测试
- [ ] `RecommendationWirer` 单元测试全过（10+ 用例）
- [ ] `ChapterRewriteService` 钩子写入 metric 行
- [ ] `chapter.quality_status = "rewriting"` 状态值可用
- [ ] `max_auto_rewrites` 配置生效，缺键启动失败
- [ ] 集成测试 `test_auto_rewrite_loop` 全过
- [ ] E2E 测试 `test_phase2_protection_loop` 全过
- [ ] 前端 widget rewriting spinner + manual_review 按钮可见

### 9.2 质量

- [ ] 新增代码行覆盖率 ≥ 80%
- [ ] `BeatCoverageValidator` / `RecommendationWirer` 覆盖率 ≥ 95%
- [ ] 现有 `pytest tests/` 全绿（除已知的 pre-existing failure）
- [ ] `_write_whole_chapter` 端到端延迟增加 ≤ 30%
- [ ] 阶段一所有冒烟 / E2E 测试仍过

### 9.3 文档

- [ ] Spec 文档 commit
- [ ] `llm_config.yaml` 注释 `max_auto_rewrites` 含义
- [ ] 至少 3 条 logging（防护层失败、推荐决策、收手）

### 9.4 衔接点（与阶段三）

- [ ] `chapter_quality_metrics.prompt_version` 字段预留（阶段三用）
- [ ] `BeatCoverageValidator` 的 LLM 调用入口可注入（阶段三可换 prompt）
- [ ] 不修改 `recommendation_service` 接口（阶段三 A/B 可观察）

---

## 10. 开放问题

| 问题 | 状态 | 决策 |
|------|------|------|
| 重写后再回 fast_review 是否合理？ | 待确认 | 当前选"重写完 → fast_review 复测"，可能浪费；候选方案：重写完直接 librarian（双重 fast_review 浪费）。本次保持现状。 |
| "继续重试"按钮清零 attempt 计数是否太激进？ | 待确认 | 当前选清零（与"用户显式同意重置"语义一致）；候选方案：+1 而不是清零（更保守）。本次保持清零。 |
| LLM-as-judge 失败兜底为 manual_review 是否太保守？ | 待确认 | 当前选 fail-safe manual；候选方案：自动重试 1 次后 manual。本次保持 fail-safe 一次。 |
| 5.2 重写后再回 fast_review 的延迟成本 | 已知 | 一章额外 ~5-15s 延迟（fast_review 一次 LLM 调用）；通过把 fast_review 的 prompt 减半（仅核心维度）来缓解，超出本阶段范围。 |
| attempt_index 漂移阈值的具体数值 | 5（max + 3） | 拍脑袋定；如有真实数据可调 |
| `use_llm_beat_coverage` 配置键的引入时机 | 推迟到后续优化 PR | 本阶段减少配置复杂度 |
| 阶段二是否对 `polish_standalone` 加防护 | 不加 | `polish_standalone` 是手动操作触发，防护层接入是过度设计 |

---

## 11. 附录

### 11.1 关键文件路径

**新建**：
- `src/novel_dev/services/beat_coverage_validator.py`
- `src/novel_dev/services/recommendation_wirer.py`
- `alembic/versions/xxxx_add_chapter_attempt_index.py`（DB 迁移，阶段二必备——`Chapter` 表原本无 attempt_index 字段，需新建列）
- `tests/test_services/test_beat_coverage_validator.py`
- `tests/test_services/test_recommendation_wirer.py`
- `tests/test_agents/test_pre_write_hardener.py`（针对 `WriterAgent._build_whole_chapter_context_message` 的回归）
- `tests/test_agents/test_whole_chapter_validation.py`
- `tests/test_agents/test_auto_rewrite_loop.py`
- `tests/test_e2e/test_phase2_protection_loop.py`

**修改**：
- `src/novel_dev/services/chapter_rewrite_service.py`（在 `rewrite()` 末尾追加 `RewriteFeedbackWriter.record(...)` 钩子）
- `src/novel_dev/agents/fast_review_agent.py`（`finalize` 后调 `RecommendationWirer`）
- `src/novel_dev/agents/writer_agent.py`（`_build_whole_chapter_context_message` 加 fail-soft try/except + INFO 日志，不动结构）
- `src/novel_dev/db/models.py`（`Chapter` 加 `attempt_index: Mapped[int] = mapped_column(default=0)`）
- `llm_config.yaml`（在 `quality_thresholds.recommendation` 下加 `max_auto_rewrites: 2`）
- `src/novel_dev/web/src/components/QualityRecommendationWidget.vue`（rewriting spinner + manual_review 按钮）

**复用（不动，仅加测试）**：
- `src/novel_dev/schemas/quality.py:42` —— `BeatBoundaryCard`（已有）
- `src/novel_dev/services/beat_boundary_service.py` —— `BeatBoundaryService.build_cards`（已有）
- `src/novel_dev/agents/context_agent.py:572` —— `_attach_beat_boundary_cards`（已有）
- `src/novel_dev/agents/writer_agent.py:945-988` —— 节拍卡 prompt 渲染（已有）

### 11.2 阶段一接口引用

- `ChapterQualityMetric` 模型：`src/novel_dev/db/models.py:534-573`
- `QualityMetricsService.record()`：`src/novel_dev/services/quality_metrics_service.py:33-58`
- `RecommendationService.recommend()`：`src/novel_dev/services/recommendation_service.py:53-137`
- `ChapterRewriteService.rewrite()`：`src/novel_dev/services/chapter_rewrite_service.py:71`（方法体跨多行，本阶段不重写，仅在其末尾追加 metric 记录钩子）
- `call_and_parse` helper：`src/novel_dev/agents/_llm_helpers.py`

### 11.3 阶段三衔接点（不实施，留接口）

- `chapter_quality_metrics.prompt_version` 字段已预留，阶段三 A/B 可观察
- `BeatCoverageValidator` 的 LLM 调用入口接受 `llm_client` 注入，阶段三可换 prompt
- `chapter_quality_metrics.issue_codes` 持续累积，阶段三做 batch LLM 根因分析时直接读
- `IssueHintsService.matched_hints()` 的 `hint` 字段，阶段三可替换为 LLM-driven

---

**文档结束。**
