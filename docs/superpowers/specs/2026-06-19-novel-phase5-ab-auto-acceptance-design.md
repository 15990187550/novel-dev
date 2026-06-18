# Phase 5 — A/B 赢家自动采纳设计

> **日期**: 2026-06-19
> **分支**: `phase2-writer-protection` 之后
> **前置阶段**: Phase 4(质量架构)完成,30 任务全绿,1805 测试通过,新服务 100% 覆盖

## 目标

解决"Phase 3 建好的 A/B 基础设施无人关停/采纳"问题:实验跑完后无人判定赢家、无人自动合入、无人回滚出错的合入。让 A/B 实验真正闭环。

## 用户决策(已确认)

| 决策点 | 选择 |
|---|---|
| 介入程度 | **全自动** — 达成即合入,不需用户确认 |
| 判定指标 | **多指标加权** — critic 总分 + 钩子达成率 + 爽点达成率 |
| 权重 | **A+B 混合** — 默认 50/30/20,跑 N 周期后贝叶斯微调 |
| 显著性 | **自适应** — 起步 B 标准,3 次未达显著放宽到 C |
| 兜底 | **三层全要** — 超时 + 早停 + 回滚 |
| UI | **三件套全要** — dashboard + 时间线 + toast |
| 架构 | **方案 3 混合** — 采纳内联 + 兜底定时扫 |

## 不在本期范围

- LLM-as-judge 作为 A/B 判定指标(成本高,留作 Phase 6)
- 多 LLM provider 的 A/B 路由
- A/B 实验的跨小说复用
- A/B 决策的强化学习(留作 Phase 7)
- 实时数据流式统计(沿用现有批处理)

---

## §1 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  触发层                                                      │
│  ┌─────────────────┐    ┌──────────────────┐                │
│  │ Writer/Critic   │    │ Scheduler(5min)  │                │
│  │ Hook/Thrill     │    │                  │                │
│  └────────┬────────┘    └────────┬─────────┘                │
│           │ 采样事件             │ 周期 tick                 │
└───────────┼─────────────────────┼───────────────────────────┘
            ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│  决策层                                                      │
│  ┌──────────────────────────┐ ┌─────────────────────────┐   │
│  │ ABAcceptanceDecider(内联)│ │ ABAcceptanceSweeper     │   │
│  │ - 显著检验               │ │ - 早停判定              │   │
│  │ - 加权得分对比           │ │ - 超时判定              │   │
│  │ - 采纳决策               │ │ - 回滚判定(24h 窗口)    │   │
│  │ - 写 ab_decisions        │ │ - 写 ab_decisions       │   │
│  └──────────────────────────┘ └─────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
            ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│  数据层                                                      │
│  prompt_versions(扩展)+ ab_decisions(新表)                  │
└─────────────────────────────────────────────────────────────┘
```

**决策器职责分离:**

| 决策器 | 触发 | 判定 | 延迟 |
|---|---|---|---|
| `ABAcceptanceDecider`(内联) | 采样后立即调用 | 显著检验 + 加权得分对比 + 采纳 | 亚毫秒 |
| `ABAcceptanceSweeper`(定时) | 每 5 分钟一次 | 早停 / 超时 / 回滚 | ≤5min |

---

## §2 组件清单

### 2.1 `WeightedScoreCalculator`
**职责**: 计算 A/B 实验的当前加权得分
**输入**: `experiment_id`,各版本样本的 `critic_scores`, `hook_achievement`, `thrill_verified`
**输出**: 各版本的加权得分(0-100)
**权重**: 默认 `{"critic": 0.5, "hook": 0.3, "thrill": 0.2}`(YAML 配置可调)
**公式**: `score = critic_mean × 0.5 + hook_rate × 100 × 0.3 + thrill_rate × 100 × 0.2`

### 2.2 `SignificanceTester`
**职责**: 判定"两版本加权得分差异是否显著"
**方法**: Welch's t-test(不假定等方差)
**输出**: `(is_significant: bool, p_value: float, effect_size: float)`
**自适应阈值**:
- 起步严格: `min_samples=50, p<0.05, min_lift=0.03`
- 3 次未达显著 → 放宽: `min_samples=30, p<0.10, min_lift=0.02`
- 反之收紧

### 2.3 `BayesianWeightUpdater`
**职责**: 在线更新指标权重
**方法**: Dirichlet-Multinomial 后验,每 N(默认 50)次采样更新一次
**输出**: 新权重 `(critic, hook, thrill)` 求和=1
**约束**: 任何权重偏离默认不超过 ±0.2(防漂移)
**首次运行**: 不更新,使用默认权重

### 2.4 `ABAcceptanceDecider`(内联)
**职责**: 采样后立即判定是否合入
**位置**: 调用 `ABTestRunner.increment_sample_count` 后立即调用
**逻辑**:
```
1. 拉实验状态(包含样本数、各版本得分)
2. 调用 WeightedScoreCalculator
3. 调用 SignificanceTester
4. 若所有版本 sample >= min_samples 且 is_significant:
   a. 选 winner(加权得分高者)
   b. 若 winner 是 challenger:
      - 调 PromptRegistry.set_active(winner_version_id)
      - 标记 prompt_version.experiment_state = "auto_accepted"
      - 启动 24h 回滚监控窗口(写 ab_decisions)
      - 返回 "ACCEPTED"
   c. 否则 winner 是 baseline → 停止 challenger,标记 "no_improvement"
5. 写 ab_decisions(action="evaluate", p_value, scores, decision) — `decision` 字段值: `"accepted" | "rejected" | "no_action"(样本不足或未达显著) | "skipped"(评分缺失或异常)`
```

### 2.5 `ABAcceptanceSweeper`(定时)
**职责**: 兜底判定(早停 / 超时 / 回滚)
**周期**: 5 分钟(可配)
**逻辑**:
```
对每个 active 实验:
  1. 早停判定:
     若 challenger 得分持续落后 baseline 10%+ 达 N 次(默认 3)采样
     → 停掉 challenger,标 baseline 为 active,记 ab_decisions("early_stop")
  2. 超时判定:
     若实验运行 ≥ 7 天(可配)且未达显著
     → 停止实验,保留 baseline 为 active,记 ab_decisions("timeout")
  3. 回滚判定(采纳后 24h 窗口):
     若在 24h 监控窗口内,新 active 版本加权得分下降 ≥ 5%
     → 回滚到上一个 stable 版本,记 ab_decisions("rolled_back")
```

### 2.6 `prompt_versions` 扩展字段
新增字段:
- `experiment_state`: `"running" | "auto_accepted" | "early_stopped" | "timeout" | "rolled_back" | "no_improvement" | "stable" | "active-rolled-back"`
- `last_decision_at`: datetime
- `last_score`: float
- `experiment_history`: JSON(list of decision events,只追加)

### 2.7 新表 `ab_decisions`
```sql
CREATE TABLE ab_decisions (
  id UUID PRIMARY KEY,
  experiment_id UUID NOT NULL,
  prompt_version_id UUID,
  action TEXT NOT NULL,  -- evaluate / accept / early_stop / timeout / rolled_back / monitoring_window_closed / rollback_no_target / manual_override / accept_failed
  decision_at TIMESTAMP NOT NULL,
  p_value FLOAT,
  scores JSON,  -- {version_id: weighted_score}
  effect_size FLOAT,
  metadata JSON,
  created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_ab_decisions_experiment ON ab_decisions(experiment_id);
CREATE INDEX idx_ab_decisions_action ON ab_decisions(action);
CREATE INDEX idx_ab_decisions_decision_at ON ab_decisions(decision_at);
```

---

## §3 数据流

### 场景:用户启动 `writer` agent 的 A/B 实验(v1 baseline vs v2 challenger)

```
T0  用户操作
    POST /api/prompts/writer/ab-experiments
      body: { "baseline_version": "v1_uuid", "challenger_version": "v2_uuid",
              "max_samples": 200, "min_samples_start": 50 }
    → prompt_versions.v2.experiment_state = "running"

T1  WriterAgent 写第 1 章
    LLMFactory.get_with_chapter_id("writer", ..., chapter_id="ch_5")
      → ABTestRunner.pick_version("writer", "ch_5") → 路由到 v2(challenger)
      → PromptRegistry.get_active_for_chapter("writer", "ch_5") → v2 prompt
    生成完成后:
      ABTestRunner.increment_sample_count("writer", "v2", score=82, ...)
        → 触发 ABAcceptanceDecider.evaluate(experiment_id)
          → 样本数: v1=0, v2=1 → 不达标,跳过
          → 写 ab_decisions(action="evaluate", scores={v1:null, v2:1})

T2..T99 继续采样(每次采样后内联判定)
    每次:
      - 更新 sample_count
      - 跑 WeightedScoreCalculator(数据可能不足,score 仍可计算)
      - 跑 SignificanceTester(若样本未达 min_samples → 返回 not_significant)
      - 写 ab_decisions

T100 累积样本: v1=50, v2=50
    SignificanceTester 返回 is_significant=True, p=0.03, v2 加权得分高于 v1 4%
    ABAcceptanceDecider 判定:
      winner=v2(challenger), is_significant=True
      → PromptRegistry.set_active(v2)
      → prompt_versions.v2.experiment_state = "auto_accepted"
      → 启动 24h 回滚监控(写 ab_decisions action="accept")
      → 实验状态: experiment_state = "completed"
      → 返回 API 响应给用户(通知:auto_accepted)

T101..T+24h  Sweeper 每 5 分钟跑一次
    每次:
      - 拉最近 24h 的新 active 版本样本(只看 v2)
      - 计算 v2 现在的加权得分 vs T100 时的得分
      - 若下降 ≥ 5% → 触发回滚:
        a. PromptRegistry.set_active(v1)
        b. v2.experiment_state = "rolled_back"
        c. v1.experiment_state = "active-rolled-back"
        d. 写 ab_decisions action="rolled_back"
        e. 不重开 A/B(避免循环)
      - 若无下降 → 不操作,继续监控

T+24h  监控窗口结束
    v2 仍稳定 → 保持 active,标记 v2.experiment_state = "stable"
    写 ab_decisions action="monitoring_window_closed"
```

### 早停场景(challenger 显著失败)

```
T50  v1=25, v2=25,但 v2 加权得分持续落后 v1 12%(连续 3 次采样)
    ABAcceptanceSweeper 早停判定触发:
      → ABTestRunner.stop_challenger(experiment_id)
      → v2.experiment_state = "early_stopped"
      → 写 ab_decisions action="early_stop", metadata={consecutive_loss: 3}
      → v1 保持 active
```

### 超时场景(永远不显著)

```
T+7d  实验已运行 7 天,累积样本 v1=140, v2=140
    SignificanceTester 仍返回 not_significant
    ABAcceptanceSweeper 超时判定触发:
      → 停止实验,保留 v1 为 active
      → 写 ab_decisions action="timeout"
      → v2.experiment_state = "no_improvement"
```

---

## §4 错误处理

### 4.1 采样层错误
| 错误 | 处理 |
|---|---|
| `increment_sample_count` 写入失败 | 重试 3 次(指数退避),失败则丢弃本次样本 |
| LLM 生成失败 | 已有 fallback 链(Phase 3 建的),不影响 A/B 计数 |
| 样本评分缺失(critic/hook/thrill 任一为 None) | 跳过该次 `evaluate`,只更新计数;不写 ab_decisions |

### 4.2 决策层错误
| 错误 | 处理 |
|---|---|
| `WeightedScoreCalculator` 输入异常 | 返回 `None`,Decider 跳过本次判定 |
| `SignificanceTester` 计算异常 | 提前返回 `(is_significant=False, p_value=None)`,Decider 跳过 |
| `set_active` 写失败 | 重试 3 次;失败则回滚 in-memory 状态,写 ab_decisions action="accept_failed" |
| 贝叶斯更新异常 | 跳过本次更新,保留旧权重,记 warning 日志 |

### 4.3 调度层错误
| 错误 | 处理 |
|---|---|
| Sweeper tick 中单个实验失败 | 捕获异常,记日志,继续处理其他实验(隔离) |
| Sweeper 整个 tick 失败 | 重试 1 次(等 30s),失败则记 error,等下个 tick |
| 并发 Sweeper(多进程) | 用 `SELECT ... FOR UPDATE` 锁 `ab_decisions` 的 action 行 |

### 4.4 边界条件
| 边界 | 处理 |
|---|---|
| baseline 和 challenger 同时被外部设为 active | `set_active` 用乐观锁(版本号),冲突则 retry 1 次 |
| 实验运行期间用户手动改了 active 版本 | 记录 `manual_override` 到 ab_decisions,Sweeper 检测后暂停自动决策 |
| 回滚时上一个 stable 版本不存在 | 不回滚,标记 v2 为 "unstable",写 ab_decisions action="rollback_no_target" |
| 新表 `ab_decisions` 已存在(迁移重入) | Alembic 检测并跳过(`IF NOT EXISTS`) |

### 4.5 监控与告警
- 每个 ab_decisions action 都写到 `log_service`
- 关键事件(`accept` / `rolled_back` / `early_stop`)产生 ERROR 级别日志(便于 grep)
- API 端点 `GET /api/ab-decisions/recent?window=24h` 返回最近事件(供 UI 拉取)

---

## §5 测试策略

### 5.1 单元测试(目标覆盖率 ≥90%)
| 组件 | 测试文件 | 覆盖点 |
|---|---|---|
| `WeightedScoreCalculator` | `tests/test_services/test_weighted_score.py` | 默认权重、自定义权重、空样本、单指标缺失 |
| `SignificanceTester` | `tests/test_services/test_significance_tester.py` | 等样本、不等样本、单样本、零方差、自适应阈值切换 |
| `BayesianWeightUpdater` | `tests/test_services/test_bayesian_weight_updater.py` | 首次不更新、连续更新后收敛、±0.2 约束 |
| `ABAcceptanceDecider` | `tests/test_services/test_ab_acceptance_decider.py` | 采纳决策、未达显著、winner 是 baseline、并发回滚 |
| `ABAcceptanceSweeper` | `tests/test_services/test_ab_acceptance_sweeper.py` | 早停、超时、回滚、监控窗口结束、隔离错误 |

### 5.2 集成测试
- `tests/test_api/test_ab_decisions_api.py`: A/B 实验启停 API、ab_decisions 列表 API
- `tests/test_db/test_ab_decisions_table.py`: 表创建、索引、JSON 字段读写

### 5.3 E2E 测试
- `tests/test_e2e/test_phase5_ab_auto_acceptance.py`:
  - 场景 1: 完整 A/B → 采纳 → 稳定
  - 场景 2: A/B → 早停
  - 场景 3: A/B → 超时
  - 场景 4: A/B → 采纳 → 24h 后回滚(用 freezegun)
  - 场景 5: 用户手动改 active 后 Sweeper 暂停

### 5.4 Mocking 策略
- LLM 调用:`mock_llm_factory` fixture(全局 autouse)
- 时间:用 `freezegun` 控制 `datetime.now()`(用于回滚窗口判定)
- 贝叶斯随机性:固定 random seed
- DB:沿用现有 SQLite 测试 DB

### 5.5 性能测试(可选)
- 1000 个采样样本的显著性计算时间(<100ms)
- Sweeper 处理 50 个 active 实验的时间(<5s)

---

## §6 UI 设计

### 6.1 Dashboard 小部件(`QualityTrendsView` 或新建 `ExperimentWidget`)
位置:小说 dashboard 角落
显示:
- 当前 running 实验数
- 最近 24h auto_accepted 数
- 当前 active 版本 + 上次采纳时间
- 最近一次事件(accepted/early_stopped/timeout/rolled_back)

### 6.2 专门实验视图 `/novels/:id/experiments`
展示所有 A/B 实验的时间线:
- 每条实验一行(开始 / baseline vs challenger / 当前状态 / 得分曲线)
- 点击展开看完整决策日志(ab_decisions)
- 筛选:by status / by agent / by date

### 6.3 Toast 通知
触发方式:**前端每 30 秒轮询** `GET /api/ab-decisions/recent?window=5m`,对比已显示的事件 ID 集合,新事件则弹 toast(简单可靠,避免引入 WebSocket)。
关键事件:
- `auto_accepted` — "writer v2 已自动采纳为 active"
- `early_stopped` — "writer v2 已早停,writer v1 保持 active"
- `rolled_back` — "writer v2 24h 内表现下降,已回滚到 writer v1"
- `timeout` — "writer A/B 实验 7 天未达显著,已结束"

---

## §7 验收清单

- [ ] 7 大组件实现并测试 ≥90% 覆盖
- [ ] `ab_decisions` 表 + migration
- [ ] `prompt_versions` 4 字段扩展 + migration
- [ ] 内联合入逻辑不增加 LLM 路径延迟
- [ ] Sweeper 每 5 分钟跑一次,处理 50 个 active 实验 <5s
- [ ] 早停 / 超时 / 回滚三种兜底全部启用并测试
- [ ] 贝叶斯权重更新首次不生效,后续 ±0.2 约束
- [ ] 关键事件 ERROR 日志 + API 可拉取
- [ ] UI 三件套全部交付并测试
- [ ] 全量后端测试 ≥1850(原 1829 + 21 新测试)
- [ ] 全量前端测试 ≥325(原 312 + 13 新测试)
- [ ] E2E 5 场景全通过

---

## §8 实施分波(预)

按 subagent-driven development 拆分,预计 25-30 任务:

- **Wave 1(基础设施,5 任务)**: db 迁移、prompt_versions 扩展、ab_decisions 表 + repo、log_service 扩展
- **Wave 2(判定组件,5 任务)**: WeightedScoreCalculator、SignificanceTester、BayesianWeightUpdater
- **Wave 3(决策器,5 任务)**: ABAcceptanceDecider(内联)、ABAcceptanceSweeper(定时)、调度器入口
- **Wave 4(API + UI,8 任务)**: 启停 API、ab_decisions 列表 API、Dashboard 组件、ExperimentView、Toast、3 个视图测试
- **Wave 5(E2E + 性能,3 任务)**: E2E 5 场景、性能基准、最终回归