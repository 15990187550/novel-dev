# 小说产出质量优化 — 阶段一:完整可观测性设计文档

**日期:** 2026-06-13
**主题:** 反馈闭环 & 可观测性
**状态:** 待实现
**所属综合方案:** 阶段一(共三阶段:可观测性 → Writer 节拍防护 → Prompt 工程化)

---

## 1. 项目概述

本系统是一个多 Agent 长篇小说创作流水线。当前 9 个 phase(Brainstorm → VolumePlan → Context → Draft → Review → Edit → FastReview → Librarian → Completed)运转稳定,但质量产出存在三个系统性问题:

1. **质量数据散落**: 各 phase 的反馈数据只存于 JSON snapshot,数据库中虽已建模(`chapters.final_review_feedback` 等),却未被消费。无趋势查询、无跨章对比、无决策支持。
2. **反馈闭环断裂**: CriticAgent 对成稿的复评结果(`final_review_feedback`)在 fast review 流程中被丢弃,导致 6 维度详细评分不可用。此 bug 当前正在修复中(未提交)。
3. **产线高频故障**: `export` 步骤在几乎每个 generation run 中都报 `exported_path not returned`,阻塞归档。

本阶段(阶段一)目标: **先把数据层和可观测性建好,再谈优化**。具体交付:
- 补全持久化路径,确保所有 phase 反馈可查询
- 新增 4 个查询/分析 API 端点
- 新增 3 个 Vue 视图 + 1 个 Dashboard 嵌入组件
- 规则式决策支持("下一章该做什么")
- LLM 评分一致性 utility
- 修复 export 步骤根因

阶段二(Writer 节拍防护)和阶段三(Prompt 工程化)将在本阶段数据底座上,各自独立 spec → plan → 实施。

---

## 2. 设计原则

1. **加挂优先于替换**: 不修改现有 9-phase 流程,所有改动是"加"而非"换"。保证不破坏正在生产的长篇任务。
2. **数据先于优化**: 没有可量化的趋势,优化就是盲人摸象。本阶段只负责把数据搞对搞全。
3. **规则起步,LLM 升级**: 决策支持先用确定性规则(rule-based),为阶段三的 LLM-driven 留接口,不在阶段一做超出范围的智能化。
4. **集中配置,消除 hardcode**: 把散落在 `quality_gate_service.py`、`editor_agent.py` 等处的 82 / 75 / 70 / 40 阈值统一到 `llm_config.yaml` 的 `quality_thresholds` 段。
5. **故障可回滚**: 分 3 波上线,每波独立可回滚。任何一波失败不影响其他波。
6. **保留所有 attempt**: 不只存"最终那次"评分,存 attempt 级别历史。retry11 / retry14 的事故数据揭示: 同一 chapter 不同 attempt 差异巨大,趋势分析必须基于历史。

---

## 3. 整体架构与数据流

```
┌─────────────────────────────────────────────────────────────────┐
│                    9-Phase Pipeline (现状, 不变)                  │
│  Brainstorm → VolumePlan → Context → Draft → Review → Edit     │
│  → FastReview → Librarian → Completed                          │
└──────────────────────────┬──────────────────────────────────────┘
                           │ 每个 phase 产出
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  持久化层 (补全 + 新增)                                            │
│  • chapters.final_review_feedback / draft_review_feedback (补全)│
│  • chapter_quality_metrics (新表) — attempt 粒度结构化指标         │
│  • alembic migration                                            │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Analysis API (新)                                                │
│  GET  /api/novels/{id}/quality/trends                            │
│  GET  /api/novels/{id}/quality/issues                            │
│  POST /api/novels/{id}/chapters/{cid}/quality/recommend          │
│  GET  /api/quality/judge-consistency                             │
│  GET  /api/novels/{id}/quality/runs (可选)                        │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Frontend (Vue 3 + Element Plus + ECharts)                       │
│  • QualityTrendsView (per-novel 折线图)                            │
│  • QualityIssuesView (issue 频次表 + 根因提示)                     │
│  • QualityRunsView (历史 generation run 列表)                     │
│  • QualityRecommendationWidget (Dashboard 嵌入)                   │
└─────────────────────────────────────────────────────────────────┘

横向能力:
┌─────────────────────────────────────────────────────────────────┐
│  • config/quality_config.py — 集中读取 quality_thresholds / hints │
│  • export_service.py 修复 — 根因 + 重试 + 失败可观测               │
│  • QualityIssueCode 枚举 — 标准化问题分类                          │
│  • recommendation_service.py — 规则式决策引擎                      │
│  • judge_consistency.py — LLM 评分一致性 utility                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. 持久化 Schema

### 4.1 已有表补全 (`chapters`)

不新增列,补全现有字段的消费路径。当前 `chapters` 表(参考 `src/novel_dev/db/models.py:221-246`)已有但未被充分利用的字段:

| 字段 | 状态 | 阶段一处理 |
|---|---|---|
| `score_breakdown: JSON` | 已存, 未消费 | 补 query API 消费 |
| `final_review_feedback: JSON` | **正在修(未提交)** | 验证修复, 加持久化回归测试 |
| `draft_review_feedback: JSON` | **正在修(未提交)** | 验证修复, 加持久化回归测试 |
| `quality_reasons: JSON` | 已存 | 补 query API 消费 |
| `quality_checked_at: timestamp` | 已存 | 补 trend 计算 |

### 4.2 新表 `chapter_quality_metrics`

attempt 粒度结构化指标(同一 chapter 多次重试都留痕):

```python
# src/novel_dev/db/models.py (新增)
class ChapterQualityMetric(Base):
    __tablename__ = "chapter_quality_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    novel_id: Mapped[int] = mapped_column(
        ForeignKey("novels.id", ondelete="CASCADE"), index=True
    )
    chapter_id: Mapped[int] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), index=True
    )

    # phase 标识
    phase: Mapped[str]                                      # "drafting"/"reviewing"/"editing"/"fast_reviewing"/"final"
    attempt_index: Mapped[int] = 0                          # 第几次重试 (0, 1, 2, ...)

    # LLM 评分
    overall_score: Mapped[Optional[int]]
    dimension_scores: Mapped[Optional[dict]]                # {plot_tension: 82, ...}
    dimension_feedback: Mapped[Optional[dict]]             # {plot_tension: "亮点/问题/建议", ...}

    # 门禁结果(规则判断)
    gate_status: Mapped[str]                                # pass/warn/block/manual_review_required
    blocking_items: Mapped[Optional[list]]
    warning_items: Mapped[Optional[list]]

    # 问题分类
    issue_codes: Mapped[Optional[list]]                     # ["AI_FLAVOR_HIGH", "BEAT_BOUNDARY_VIOLATION", ...]
    repairable: Mapped[Optional[bool]]

    # 元数据
    latency_ms: Mapped[Optional[int]]
    token_usage: Mapped[Optional[dict]]
    model_version: Mapped[Optional[str]]                    # 追踪模型切换影响
    prompt_version: Mapped[Optional[str]]                   # 为阶段三 A/B 留位
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
```

**索引**:
- `(novel_id, chapter_id, phase, created_at)` 复合索引
- `issue_codes` GIN 索引(按 code 聚合用)

**写入触发点**:
- `fast_review_agent.review()` 结束
- `critic_agent.score_draft()` 结束
- `critic_agent.score_final()` 结束
- `editor_agent.rewrite_beat()` 结束(可选, 等阶段二再加)

不强制每 phase 都写, 阶段一覆盖 fast_review 和 final review 两个高价值点。

### 4.3 Issue Code 词汇表

`src/novel_dev/schemas/quality_issues.py`:

```python
class QualityIssueCode(str, Enum):
    # 结构类
    BEAT_BOUNDARY_VIOLATION = "BEAT_BOUNDARY_VIOLATION"
    EVENT_ORDER_DRIFT = "EVENT_ORDER_DRIFT"
    PLANNED_CHARACTER_DRIFT = "PLANNED_CHARACTER_DRIFT"

    # 内容类
    AI_FLAVOR_HIGH = "AI_FLAVOR_HIGH"
    WORD_COUNT_DRIFT = "WORD_COUNT_DRIFT"
    CONSISTENCY_BROKEN = "CONSISTENCY_BROKEN"
    FORESHADOW_LEAKED = "FORESHADOW_LEAKED"
    HUMANITY_LOW = "HUMANITY_LOW"
    HOOK_WEAK = "HOOK_WEAK"
    PLOT_TENSION_LOW = "PLOT_TENSION_LOW"

    # 流程类
    REVIEW_TIMEOUT = "REVIEW_TIMEOUT"
    EXPORT_FAILED = "EXPORT_FAILED"
    LLM_PARSE_ERROR = "LLM_PARSE_ERROR"
    LLM_JUDGE_INCONSISTENT = "LLM_JUDGE_INCONSISTENT"
    # 持续扩充
```

**设计原则**: 新 code 必须先在此枚举里定义,再被 agent / service 使用,避免 string typo 导致聚合失败。

### 4.4 数据回填(可选, 不强制)

`scripts/backfill_quality_metrics.py`:
- 读所有 `chapters` 的 `score_overall`, `score_breakdown`, `quality_status`, `quality_reasons`, `final_review_feedback`
- 写一条 `chapter_quality_metrics` 记录, `phase='final'`, `attempt_index=0`
- 幂等: 用 `(chapter_id, phase, attempt_index)` 作天然去重

**不强制**: 阶段一可以只接受"新数据从这一刻开始", 老数据靠 API 回退路径(优先查新表, 缺失回退老字段)。

---

## 5. API Surface

所有端点挂在现有 `src/novel_dev/api/routes.py` 上, 不另起 router。新增端点统一用 `/api/novels/{id}/quality/*` 前缀。

### 5.1 `GET /api/novels/{id}/quality/trends`

某小说所有 chapter 的评分时间线。

**Query 参数**:
- `dimension` (可选, 默认 `overall`): `plot_tension` / `characterization` / `readability` / `consistency` / `humanity` / `hook_strength` / `overall`
- `phase` (可选): `drafting` / `reviewing` / `editing` / `fast_reviewing` / `final`
- `from_chapter` / `to_chapter` (可选): 范围过滤

**Response**:
```json
{
  "novel_id": 42,
  "dimension": "overall",
  "phase": "final",
  "data_points": [
    {
      "chapter_id": 101,
      "chapter_number": 1,
      "title": "第一章 山雨欲来",
      "value": 85,
      "gate_status": "pass",
      "issue_codes": [],
      "created_at": "2026-06-13T10:23:45Z"
    }
  ],
  "summary": {
    "count": 2,
    "mean": 83.5,
    "min": 82,
    "max": 85,
    "trend": "stable"
  }
}
```

**后端实现**:
- 优先查 `chapter_quality_metrics` (新表)
- 缺失时回退 `chapters.score_overall` (兼容老数据)
- `summary.trend` 用简单线性回归(自己实现, 不引入 numpy)

### 5.2 `GET /api/novels/{id}/quality/issues`

问题频次统计 + 根因提示。

**Query 参数**:
- `group_by` (默认 `code`): `code` / `phase` / `chapter` / `severity` / `repairability`
- `severity` (可选): `block` / `warn` / `manual_review`
- `since` (可选): ISO 时间, 过滤起始

**Response**:
```json
{
  "novel_id": 42,
  "group_by": "code",
  "total_issues": 7,
  "groups": [
    {
      "code": "AI_FLAVOR_HIGH",
      "count": 3,
      "chapters": [102, 104, 105],
      "first_seen": "2026-06-13T12:11:02Z",
      "last_seen": "2026-06-13T18:42:01Z",
      "severity": "warn"
    }
  ],
  "root_cause_hints": [
    {
      "code": "AI_FLAVOR_HIGH",
      "occurrences": 3,
      "hint": "在 3 章连续出现, 可能与 EditorAgent 的重写策略有关。检查 editor_agent.py 的 ai_flavor 关键词列表"
    }
  ]
}
```

**`root_cause_hints` 机制**:
- 静态映射表 `ISSUE_CODE_HINTS` 在 `llm_config.yaml` 配置
- 出现次数达到 `threshold` 触发提示
- 阶段一是文本提示; 阶段三可替换为 LLM-driven 根因分析

### 5.3 `POST /api/novels/{id}/chapters/{cid}/quality/recommend`

规则式决策支持 — "下一章该做什么?"

**Request body**:
```json
{ "current_attempt": 0, "accept_with_warn": false }
```

**Response**:
```json
{
  "chapter_id": 102,
  "recommendation": "major_repair",
  "confidence": 0.85,
  "rationale": [
    "final_review_score=78 < publishable_threshold(82)",
    "critical_dimension plot_tension=72 < 75",
    "AI_FLAVOR_HIGH 在最近 3 章连续出现, 模式性故障"
  ],
  "suggested_actions": [
    { "type": "targeted_repair", "scope": ["plot_tension", "ai_flavor"], "estimated_iterations": 2 },
    { "type": "manual_review", "reason": "需人工评估是否调整本章 outline" }
  ]
}
```

**决策规则**(`src/novel_dev/services/recommendation_service.py`):

| 条件 | 推荐 |
|---|---|
| `gate_status == "pass"` | `accept` |
| `gate_status == "warn" && critical_dims >= 75 && final_score >= publishable` | `accept` (with warn) |
| `gate_status == "warn" && final_score >= 78 && critical_dims >= 72` | `minor_repair` (指定维度) |
| `gate_status == "warn" && final_score >= 70` | `major_repair` |
| `gate_status == "block" \|\| 同一 issue_code 出现 >= 3 次` | `stop_and_inspect` |
| `current_attempt >= stop_after_attempts (默认 3)` | `stop_and_inspect` (强制) |

### 5.4 `GET /api/quality/judge-consistency`

LLM 评分一致性 utility(不绑定 novel)。

**Query 参数**:
- `sample_chapter_id` (必需): 拿哪一章做测试
- `n` (默认 3, 最大 5): 跑几次取方差
- `model` (可选, 默认用 critic 的配置)

**Response**:
```json
{
  "chapter_id": 102,
  "model": "deepseek",
  "n": 3,
  "scores": [82, 85, 79],
  "mean": 82.0,
  "std_dev": 2.45,
  "variance_coefficient": 0.030,
  "dimension_variance": {
    "plot_tension": {"mean": 78, "std_dev": 4.2},
    "consistency": {"mean": 90, "std_dev": 1.5}
  },
  "interpretation": "stable"
}
```

**interpretation 阈值**(在 `llm_config.yaml` 配置):
- `variance_coefficient <= 0.05` → `stable`
- `<= 0.10` → `moderate`
- `> 0.10` → `unstable`

**用法**:
- 阶段一: 手动调用, 用于校准
- 阶段三: 在 A/B harness 里自动跑

### 5.5 `GET /api/novels/{id}/quality/runs` (可选)

返回该小说的所有 generation run 历史(从 `reports/test-runs` 解析,只读不迁移)。

**Response**:
```json
{
  "novel_id": 42,
  "runs": [
    {
      "run_id": "inkos-md-zhutian-real-vol1-ch2-qualityfix-targeted-repair-20260527",
      "started_at": "2026-05-27T...",
      "finished_at": "2026-05-27T...",
      "status": "passed",
      "chapters_archived": 3,
      "total_words": 4478,
      "path": "reports/test-runs/.../summary.json"
    }
  ]
}
```

---

## 6. 决策支持逻辑(详细规则)

### 6.1 输入聚合

`recommendation_service.recommend(novel_id, chapter_id, current_attempt)` 输入:
- `chapter.final_review_score`
- `chapter.score_breakdown` (各维度)
- `chapter.quality_status` 和 `quality_reasons`
- `chapter_quality_metrics` 最近 N 条(检测模式性故障)
- `current_attempt` (请求体传入)
- 阈值(从 `quality_config.get_quality_config()` 读)

### 6.2 规则优先级

按顺序匹配,首个命中决定结果:

1. **强制 stop**: `current_attempt >= stop_after_attempts` → `stop_and_inspect`
2. **模式性故障**: 同一 `issue_code` 在最近 3 章出现 → `stop_and_inspect`
3. **Block**: `gate_status == "block"` → `stop_and_inspect`
4. **Pass**: `gate_status == "pass"` → `accept`
5. **Warn 良好**: `final_score >= publishable AND critical_dims >= 75` → `accept` (with warn, 仅在 `accept_with_warn=true` 时)
6. **Warn 轻度**: `final_score >= 78 AND critical_dims >= 72` → `minor_repair`
7. **Warn 重度**: `final_score >= 70` → `major_repair`
8. **其他 warn**: → `major_repair`

### 6.3 `confidence` 字段计算

简单启发式:
- `accept`: `confidence = 1.0` (确定性)
- `minor_repair` / `major_repair`: `confidence = max(0, (final_score - 60) / 30)` (分数越接近阈值,越有把握)
- `stop_and_inspect`: `confidence = 1.0` (强制)

### 6.4 `suggested_actions` 生成

根据命中规则附加操作建议:
- `minor_repair`: `[{ type: "targeted_repair", scope: [低分维度名] }]`
- `major_repair`: `[{ type: "targeted_repair", scope: [低分维度名] }, { type: "manual_review", reason: "需评估 outline" }]`
- `stop_and_inspect`: `[{ type: "manual_review", reason: "模式性故障 / 强制停止" }]`

---

## 7. LLM Judge 一致性

### 7.1 用途

LLM-as-judge 的最大隐患: 同一输入, 不同次调用, 分数波动。本 utility 让用户(阶段一)或自动化(阶段三)能测量这种波动。

### 7.2 实现

`src/novel_dev/llm/judge_consistency.py`:

```python
async def measure_judge_consistency(
    chapter_id: int,
    n: int = 3,
    model: str | None = None,
) -> JudgeConsistencyReport:
    """Run the same chapter through critic N times, compute variance.

    - Concurrency: sequential by default to avoid rate limits; configurable.
    - Token cost: N × single scoring call. Caller is responsible for cost awareness.
    - Time cost: N × typical scoring latency. Can be slow.
    """
    chapter = await chapter_repo.get(chapter_id)
    config = get_quality_config()["judge_consistency"]

    scores, dimension_scores_list = [], []
    for _ in range(n):
        result = await critic.score_polished(chapter.polished_text, chapter.context)
        scores.append(result.overall)
        dimension_scores_list.append(result.dimension_scores)

    overall_var = compute_variance_metrics(scores)
    dim_var = {
        dim: compute_variance_metrics([ds[dim] for ds in dimension_scores_list])
        for dim in dimension_scores_list[0].keys()
    }

    interpretation = (
        "stable" if overall_var["variance_coefficient"] <= config["stable_max_cv"]
        else "moderate" if overall_var["variance_coefficient"] <= config["moderate_max_cv"]
        else "unstable"
    )

    return JudgeConsistencyReport(...)
```

### 7.3 调用成本与节制

- 端点默认 N=3,最大 5,显式声明不静默跑大批量
- 阶段一不加自动调用,只在手动校准时用
- 阶段三在 A/B harness 里调用前,需在文档中明确 token 成本

---

## 8. 前端视图

沿用现有 Vue 3 + Element Plus + ECharts 栈。**复用**: `api.js`, `useNovelStore`, Element Plus, ECharts。**不重写**: `ScoreRadar`, `ChapterProgressGantt`, `DashboardVolumeSummary`。

### 8.1 `QualityTrendsView.vue`

**路由**: `/novels/:id/quality/trends`

```
┌─────────────────────────────────────────────────┐
│  章节评分趋势              [维度: overall ▼]    │
├─────────────────────────────────────────────────┤
│  ┌─ 折线图 (ECharts) ───────────────────────┐  │
│  │  100┤                                    │  │
│  │   90┤   ●─●                              │  │
│  │   82├─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ── 阈值线     │  │
│  │   75├─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ── 关键维度线  │  │
│  │   60┤                                    │  │
│  │     └───────────────────                 │  │
│  │      ch1  ch2  ch3  ch4  ch5              │  │
│  └────────────────────────────────────────────┘  │
│  摘要: 均值 83.5, 趋势 declining, 5 章           │
├─────────────────────────────────────────────────┤
│  维度雷达切换: [情节张力][人物][可读性][一致]...│
│  选中后下方显示该维度 6 章折线                    │
└─────────────────────────────────────────────────┘
```

**实现要点**:
- ECharts `line` + `markLine` 标 82/75 阈值线
- Hover tooltip 显示 `gate_status` 和 `issue_codes`

### 8.2 `QualityIssuesView.vue`

**路由**: `/novels/:id/quality/issues`

```
┌─────────────────────────────────────────────────┐
│  质量问题频次分析                                │
│  聚合方式: [按 code ▼]  严重度: [全部 ▼]        │
├─────────────────────────────────────────────────┤
│  AI_FLAVOR_HIGH          3 次   [warn]          │
│  出现章节: ch2, ch4, ch5                         │
│  ⚠ 模式性故障: 在 3 章连续出现                   │
│  💡 提示: 检查 editor_agent.py 的 ai_flavor     │
│     关键词列表...                                │
├─────────────────────────────────────────────────┤
│  BEAT_BOUNDARY_VIOLATION 2 次  [block]         │
│  ...                                             │
└─────────────────────────────────────────────────┘
```

**实现要点**:
- Element Plus `el-collapse` 每 code 一个 panel
- 严重度用 `el-tag` 颜色区分(block 红, warn 黄, manual_review 蓝)
- 提示文本用 `el-alert`, 严重时 `type="warning"`

### 8.3 `QualityRecommendationWidget.vue`

**位置**: 嵌入 `Dashboard.vue` 的 `DashboardNextActions` 区

```
┌─────────────────────────────────────────┐
│  质量建议                                  │
│  当前: 第 3 章, 评分 78                  │
├─────────────────────────────────────────┤
│  推荐: 🔧 major_repair                  │
│  置信度: 85%                             │
│  理由:                                   │
│  • final_review_score=78 < 82          │
│  • plot_tension=72 < 75                 │
│  建议操作:                                │
│  • 定点修复: plot_tension, ai_flavor    │
│  • 预计迭代: 2 轮                        │
│                                          │
│  [查看详情] [忽略, 继续]                  │
└─────────────────────────────────────────┘
```

**交互**:
- "查看详情" 跳到 `QualityIssuesView` 并预过滤该 chapter
- "忽略, 继续" 仅前端 UI 状态, 不写库
- "应用建议" 阶段一只展示, 不实际触发后端修复(后端接口留给阶段二)

### 8.4 `QualityRunsView.vue` (可选)

**路由**: `/novels/:id/quality/runs`

把 `reports/test-runs/` 下的历史 run 用表格列出(只读, JSON 解析)。

### 8.5 路由与导航更新

- `src/novel_dev/web/src/router.js`: 注册新路由
- `src/novel_dev/web/src/views/Dashboard.vue`: 在侧栏加"质量分析"快捷入口
- 顶栏 nav 同步更新

---

## 9. Pipeline 可靠性修复 (Export Bug)

### 9.1 故障画像

`reports/test-runs/*/summary.md` 揭示:
- **频率**: 几乎每个 run 都有
- **现象**: `EXPORT_FAILED`, `exported_path` 为 `None`
- **后果**: 流程卡住或 `failed`, 即使所有章节通过 quality gate 也无法归档

### 9.2 根因假设(待代码确认)

代码位置候选: `src/novel_dev/services/export_service.py`, `src/novel_dev/api/routes.py`(export endpoint), `src/novel_dev/agents/director.py`(librarian 之后)

可能原因:
1. 同步 IO 在 async 上下文被 event loop 中断
2. 函数成功写文件但 `exported_path` 未回传
3. 目录权限/路径问题
4. 副作用顺序: commit 前就 try 读路径, 文件未落盘

### 9.3 修复策略 — 选档二(根因 + 重试)

不选最小修复(只重试, 留根因),也不选全异步重写(超出阶段一范围):

1. 读 `export_service.py` 和 export 端点, **先定位根因**
2. 修根因(具体修法依根因而定, 但至少有 `try/except` 记录 trace)
3. 加 idempotent 重试(最多 2 次, 指数退避)
4. 失败时把错误细节写入 `quality_reasons.export_error`, issue code 标 `EXPORT_FAILED`
5. 单元测试覆盖 4 个 case: 成功 / 路径为空 / 文件系统错误 / 数据库不一致

### 9.4 验收标准

- [ ] `pytest tests/test_export.py` 全绿, 含 4 个新增 case
- [ ] 跑一次端到端 `auto_run_chapters` + `export`, 看 snapshot `export_status` 字段
- [ ] 历史 reports `EXPORT_FAILED` 复现率 < 20%
- [ ] 失败时 `quality_reasons.export_error` 含 trace 摘要(脱敏)

---

## 10. 集中配置 (`llm_config.yaml` 新增段)

### 10.1 阈值与规则

```yaml
# 在 llm_config.yaml 末尾新增
quality_thresholds:
  publishable_final_review_score: 82
  critical_dimension_min_score: 75
  judge_consistency:
    stable_max_cv: 0.05
    moderate_max_cv: 0.10
  recommendation:
    block_threshold: 60
    minor_repair_min_score: 78
    minor_repair_min_critical: 72
    major_repair_min_score: 70
    stop_after_attempts: 3
    pattern_issue_threshold: 3
```

### 10.2 Issue Code 根因提示

```yaml
issue_code_hints:
  AI_FLAVOR_HIGH:
    severity: warn
    threshold: 3
    hint: "检查 editor_agent.py 的 ai_flavor 关键词列表;考虑在 EditorAgent 改写规则中强化对短句堆砌的检查"
  BEAT_BOUNDARY_VIOLATION:
    severity: block
    threshold: 2
    hint: "Writer 节拍边界问题,通常源于 writer 提前执行后续 beat 的事件。在 WriterAgent prompt 中强化 'must stay in beat scope' 指令"
  EXPORT_FAILED:
    severity: block
    threshold: 1
    hint: "导出步骤失败,检查 export_service.py 的路径回传和文件落盘时序"
  CONSISTENCY_BROKEN:
    severity: block
    threshold: 1
    hint: "设定一致性被破坏,检查 ContextAgent 注入的 worldview 是否完整,以及 Writer 是否引用了已变更的实体状态"
  WORD_COUNT_DRIFT:
    severity: warn
    threshold: 2
    hint: "字数偏离目标 ±10%,检查 StoryQualityService 的 beat 字数分配数学"
  REVIEW_TIMEOUT:
    severity: warn
    threshold: 1
    hint: "Reviewing 阶段超时,考虑拆分 critic prompt 减少单次输入长度,或增加 timeout"
  LLM_PARSE_ERROR:
    severity: block
    threshold: 1
    hint: "LLM 输出无法解析,检查 call_and_parse 的 retry 逻辑和 prompt 中的 JSON 格式指令"
  # 持续扩充
```

### 10.3 加载逻辑

新文件 `src/novel_dev/config/quality_config.py`:

```python
from functools import lru_cache
from pathlib import Path
import yaml

@lru_cache
def get_quality_config() -> dict:
    """Load quality_thresholds and issue_code_hints from llm_config.yaml.

    Fail loud on missing required keys — better to crash at startup than
    silently use stale defaults during a run.
    """
    config_path = Path(__file__).parent.parent.parent.parent / "llm_config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)

    quality = config.get("quality_thresholds", {})
    required = [
        "publishable_final_review_score",
        "critical_dimension_min_score",
        "judge_consistency",
        "recommendation",
    ]
    for key in required:
        if key not in quality:
            raise ConfigError(f"Missing required key quality_thresholds.{key} in llm_config.yaml")
    return quality

@lru_cache
def get_issue_code_hints() -> dict:
    config_path = Path(__file__).parent.parent.parent.parent / "llm_config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return config.get("issue_code_hints", {})

class ConfigError(Exception):
    pass
```

### 10.4 现有 hardcode 替换

| 文件 | 现有 hardcode | 替换为 |
|---|---|---|
| `src/novel_dev/services/quality_gate_service.py:17` | `PUBLISHABLE_FINAL_REVIEW_SCORE = 82` | `get_quality_config()["publishable_final_review_score"]` |
| `src/novel_dev/services/quality_gate_service.py` | `CRITICAL_DIMENSION_MIN_SCORE = 75` | `get_quality_config()["critical_dimension_min_score"]` |

**原则**: 阶段一改 `quality_gate_service` 范围内, 不动其他 agent 的 hardcode(避免回归)。`volume_planner.py` / `editor_agent.py` 的 hardcode 留到对应阶段处理。

---

## 11. 测试策略

### 11.1 单元测试(目标 80% 覆盖率)

| 模块 | 测试文件 | 关键 case |
|---|---|---|
| `services/recommendation_service.py` | `tests/test_services/test_recommendation_service.py` | 6 种规则边界值: pass/warn/block/manual_review/threshold 临界/stop_and_inspect 强制 |
| `services/issue_hints.py` | `tests/test_services/test_issue_hints.py` | hint 匹配正确性 / 阈值触发 / code 缺失 fallback |
| `services/quality_metrics_service.py` | `tests/test_services/test_quality_metrics_service.py` | 写入 / 聚合 / 维度切换 / 时间范围 |
| `llm/judge_consistency.py` | `tests/test_llm/test_judge_consistency.py` | mocked LLM 返回不同分数, 验证 std_dev / variance_coefficient / interpretation |
| `config/quality_config.py` | `tests/test_config/test_quality_thresholds.py` | 从 yaml 读取 / 默认覆盖 / 缺字段报错 |

### 11.2 集成测试(目标 15-20 个)

每个新 API 端点至少 1 个 happy path + 1 个 edge case:

| 端点 | 测试文件 | case |
|---|---|---|
| `GET /quality/trends` | `tests/test_api/test_quality_trends.py` | 空数据 / 多 chapter 排序 / dimension 切换 / 老数据回退 |
| `GET /quality/issues` | `tests/test_api/test_quality_issues.py` | group_by 4 种 / severity 过滤 / root_cause_hints 触发 |
| `POST /quality/recommend` | `tests/test_api/test_quality_recommend.py` | 6 种 recommendation 路径 / current_attempt=3 强制 stop |
| `GET /quality/judge-consistency` | `tests/test_api/test_judge_consistency.py` | n=3 / n=5 / chapter 不存在 404 / model 切换 |
| `GET /quality/runs` | `tests/test_api/test_quality_runs.py` | reports/ 目录读取 / 路径解析失败 graceful |

### 11.3 持久化层回归测试

`tests/test_persistence/test_review_feedback_persistence.py`:

- `test_final_review_feedback_persists_to_chapter` — 验证在飞修复确实落库
- `test_draft_review_feedback_persists_to_chapter` — 同上
- `test_feedback_survives_checkpoint_round_trip` — director.advance() 后仍可查
- `test_recommendation_service_reads_persisted_feedback` — 端到端

### 11.4 关键 E2E(1 个, real LLM, 允许 flaky)

`tests/test_e2e/test_quality_observability_e2e.py`:
- 完整流程: 创建 novel → 上传材料 → 跑 2 章 → 检查:
  1. `chapters.final_review_feedback` 非空
  2. `/quality/trends` 返回 2 个数据点
  3. `/quality/recommend` 返回合理 recommendation
  4. `/export` 成功(档二修复后)

`pytest.mark.slow` 默认不跑, release 前跑。

### 11.5 Mock 与覆盖

- 单测/集成测: 复用 `mock_llm_factory` fixture
- E2E: 真实 LLM,允许 flaky
- 覆盖率: 新增代码行 `>= 80%`,关键服务 `>= 90%`,修改的现有代码维持原覆盖率

### 11.6 回归保护

`tests/test_pipeline/test_pipeline_smoke.py`: 跑完整 mock pipeline, 确保所有 phase transition 正常, 不被新代码破坏。

---

## 12. 迁移与上线

### 12.1 Alembic 迁移

新文件 `alembic/versions/YYYYMMDD_HHMMSS_add_chapter_quality_metrics.py`:

```python
def upgrade():
    op.create_table(
        "chapter_quality_metrics",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("novel_id", sa.Integer, sa.ForeignKey("novels.id", ondelete="CASCADE")),
        sa.Column("chapter_id", sa.Integer, sa.ForeignKey("chapters.id", ondelete="CASCADE")),
        sa.Column("phase", sa.String(32), nullable=False),
        sa.Column("attempt_index", sa.Integer, default=0),
        sa.Column("overall_score", sa.Integer, nullable=True),
        sa.Column("dimension_scores", JSON, nullable=True),
        sa.Column("dimension_feedback", JSON, nullable=True),
        sa.Column("gate_status", sa.String(32), nullable=False),
        sa.Column("blocking_items", JSON, nullable=True),
        sa.Column("warning_items", JSON, nullable=True),
        sa.Column("issue_codes", JSON, nullable=True),
        sa.Column("repairable", sa.Boolean, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("token_usage", JSON, nullable=True),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("prompt_version", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_chapter_quality_metrics_novel_chapter_phase",
        "chapter_quality_metrics",
        ["novel_id", "chapter_id", "phase", "created_at"],
    )
    op.execute(
        "CREATE INDEX ix_chapter_quality_metrics_issue_codes "
        "ON chapter_quality_metrics USING GIN (issue_codes)"
    )

def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_chapter_quality_metrics_issue_codes")
    op.drop_index("ix_chapter_quality_metrics_novel_chapter_phase", "chapter_quality_metrics")
    op.drop_table("chapter_quality_metrics")
```

### 12.2 上线分 3 波(每波独立可回滚)

#### 波 1: 数据层
1. Alembic 迁移
2. 部署后端
3. 验证 `chapter_quality_metrics` 表存在
4. 跑数据回填脚本(可选)
5. **用户无感知**

**回滚**: `alembic downgrade -1`

#### 波 2: API + 决策支持
1. 部署后端, 新增 4 个 API 端点
2. curl 内部验证
3. **前端不部署**

**回滚**: revert commit, 后端无新依赖

#### 波 3: 前端
1. 部署前端
2. 新路由可访问
3. Dashboard 嵌入 widget

**回滚**: 前端 revert commit

### 12.3 兼容性

- API 新端点用 `/quality/*` 前缀, 不与现有冲突
- DB 新表独立, 不修改现有 schema
- LLM 调用: 不改 prompt, 不改模型配置
- 配置: 新增 yaml 段, 不删任何现有键

### 12.4 监控

阶段一交付后, 加 3 条 logging(不引入 Prometheus):

```python
# 在 quality_metrics_service.py 写入处
if gate_status == "block":
    log.warning("chapter_block", extra={"chapter_id": ..., "issue_codes": ...})
if overall_score and overall_score < config["publishable_final_review_score"]:
    log.info("below_publishable", extra={"chapter_id": ..., "score": overall_score})
if export_error:
    log.error("export_failed", extra={"chapter_id": ..., "error": export_error_snippet})
```

---

## 13. 阶段二、三衔接点(不实施, 仅留接口)

| 阶段 | 衔接点 |
|---|---|
| 阶段二: Writer 节拍防护 | 复用 `recommendation_service` 的 stop_and_inspect 触发条件; 复用 `chapter_quality_metrics.issue_codes` 监控 beat 违规 |
| 阶段三: Prompt 工程化 | 复用 `chapter_quality_metrics.prompt_version` 字段做 A/B; 复用 `judge_consistency` utility 测 prompt 改动效果; 复用 `issue_code_hints` 表定位 prompt 改动方向 |

---

## 14. 验收清单(阶段一完成标准)

### 功能

- [ ] `chapter_quality_metrics` 表存在, Alembic 迁移可上可下
- [ ] 4 个新 API 端点全通, 集成测试覆盖
- [ ] `recommendation_service` 6 种规则全测, 置信度计算正确
- [ ] `judge_consistency` utility 可用, mock 测稳定
- [ ] `QualityTrendsView`, `QualityIssuesView`, `QualityRunsView`, `QualityRecommendationWidget` 4 个 Vue 视图/组件加载无错
- [ ] `export` 步骤单元测试 4 个 case 全绿
- [ ] `llm_config.yaml` 集中配置加载, 缺字段启动报错
- [ ] 现有 82/75 hardcode 替换为 config 引用, 不破坏现有测试

### 质量

- [ ] 新增代码行覆盖率 `>= 80%`
- [ ] `recommendation_service` / `quality_metrics_service` 覆盖率 `>= 90%`
- [ ] 现有 `pytest tests/` 全绿(除 e2e 标记)
- [ ] E2E `tests/test_e2e/test_quality_observability_e2e.py` 跑通

### 文档与监控

- [ ] `quality_thresholds` / `issue_code_hints` 在 `llm_config.yaml` 有完整注释
- [ ] 3 条 logging 触发并落盘
- [ ] Spec 文档 commit, 关联到阶段二/三的衔接点

---

## 15. 范围外(明确不做)

- Prompt 抽取/版本化/快照 → 阶段三
- Writer 节拍边界强化 → 阶段二
- A/B test harness → 阶段三
- LLM-driven 根因分析(替换静态 hint 表) → 阶段三
- 现有 `volume_planner.py` / `editor_agent.py` 的 hardcode 替换 → 对应阶段
- 引入 Prometheus / Grafana → 阶段一用 logging, 后续阶段评估
- 重写 export 为全异步(档三) → 阶段二评估
- 自动化 retry 决策执行(只展示, 不实际触发) → 阶段二

---

## 16. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 在飞修复的 `final_review_feedback` 持久化与新表写入冲突 | 中 | 中 | 先验证在飞修复, 再做新表迁移; 严格测试持久化回归 |
| Export 根因无法定位 | 中 | 中 | 档二最差情况降级为档一(只加重试), 留技术债文档 |
| LLM 一致性 utility 成本失控 | 低 | 中 | 端点默认 N=3, 显式不静默批量 |
| 新增 API 端点性能问题(trend 计算) | 低 | 低 | 数据量小(单小说最多 100+ 章), 简单实现即可; 真出现再加缓存 |
| 决策建议被用户误信 | 中 | 中 | UI 显式标 "建议" 而非 "决定", 默认不触发后端操作 |
| 阶段二/三 衔接点预留不足 | 低 | 高 | 第 13 节明确列出衔接字段; 阶段一不做超出范围的事 |

---

**文档结束。下一步: 自审 → 用户 review → 调用 writing-plans skill 写实施计划。**
