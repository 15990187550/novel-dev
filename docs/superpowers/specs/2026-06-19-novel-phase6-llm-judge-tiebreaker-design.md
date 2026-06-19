# Phase 6 — LLM-as-Judge Tie-Breaker 设计

> **日期**: 2026-06-19
> **分支**: `phase2-writer-protection` 之后
> **前置阶段**: Phase 5(A/B 自动采纳)完成,23 任务全绿,1881 测试通过,新服务 100% 覆盖

## 目标

解决"Phase 5 在 tie 情况下硬指标打平、无法判定胜负"的问题。引入 LLM 作为 tie-breaker judge,
对人物口吻、叙事连贯、风格调性三个语义维度打分,在硬指标差距 < 1% 时介入打破平局。
judge prompt 自身也走 Phase 5 A/B 基础设施,实现 meta 闭环。

## 用户决策(已确认)

| 决策点 | 选择 |
|---|---|
| 集成方式 | **纯 tie-breaker** — 硬指标差距 < 1% 才调 judge,不干预正常决策路径 |
| 评估维度 | **三维度** — 人物口吻、叙事连贯、风格调性(0-10 分) |
| 输出格式 | **分数 + 简要理由** — 3 个分数 + 每维度 1-2 句理由(≤200 字截断) |
| 采样范围 | **最近 1 个样本** — 决策时只看最新 1 个 chapter |
| 维度汇总 | **三维度均值** — tie_breaker = mean(口吻, 连贯, 风格),0-10 分 |
| Tie 阈值 | **1% 绝对差距** — `tie_threshold_pct=1.0` 可配 |
| Judge 模型 | **可配置,默认独立于 writer** — `judge_agent` 独立 LLMFactory 配置 |
| 存储 | **扩展 ab_decisions** — 加 6 列;新建 3 张表 |
| Meta 闭环 | **完整 Phase 5 复用** — judge prompt 也跑 A/B,自动采纳/回滚 |
| Meta 评估信号 | **Auto-calibration** — clear-cut cases(hard gap > 5%)上 judge-vs-hard 一致率 |
| 实施路径 | **Approach B** — judge prompt registry + Phase 5 模式复用 |

## 不在本期范围

- Judge prompt 的强化学习调优(留作 Phase 7)
- 互补性指标(judge-vs-downstream correlation,需要下游 outcome 数据,留作 Phase 7)
- Judge prompt 编辑历史 diff UI(留作 Phase 7)
- 多 provider 的 judge 路由(Phase 6 默认单 provider,Phase 7 再扩展)
- 人工标注的 held-out gold eval set(Phase 6 用 auto-calibration 自动化)

---

## §1 整体架构 + 触发流程

### 1.1 架构图

```
┌──────────────────────────────────────────────────────────────┐
│  Phase 5 ABAcceptanceDecider(扩展)                           │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ 1. weighted_score = 0.5*critic + 0.3*hook + 0.2*thrill │  │
│  │ 2. abs(baseline_w - challenger_w) >= tie_threshold?   │  │
│  │    YES → 走原 Phase 5 路径(不提 judge)                │  │
│  │    NO  ↓                                             │  │
│  │ 3. 检测到 tie → 调 JudgeAgent                          │  │
│  └────────────┬──────────────────────────────────────────┘  │
│               ▼                                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ JudgeAgent(新)                                         │  │
│  │ - 从 judge_prompt_versions 拿 active version          │  │
│  │ - 对 baseline + challenger 各自最近 1 个 chapter       │  │
│  │ - 各输出 3 维度分(0-10) + 理由(≤200字)                │  │
│  │ - 返回 tie_breaker = mean(3 维度)                     │  │
│  └────────────┬──────────────────────────────────────────┘  │
│               ▼                                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ ABAcceptanceDecider 续判                                │  │
│  │ tie_breaker_baseline vs tie_breaker_challenger         │  │
│  │ → 写 ab_decisions(扩展字段)                            │  │
│  │ → 写 judge_call_log(每次 judge 调用)                   │  │
│  └───────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
            ┌────────────────────────────┐
            │ JudgeAcceptanceDecider(新) │  ← meta-A/B 层
            │ 跟 ABAcceptanceDecider 平行│
            │ 跑在 JudgeAgent 之上       │
            └────────────────────────────┘
```

### 1.2 关键流程点

1. **judge 触发条件** = tie — 硬指标 weighted_score 差距 < 1%(可配)
2. **judge 范围** = 1 sample — 各自最近 1 个 chapter
3. **judge 决定胜负** — tie_breaker 分高者赢
4. **judge 失败 → 降级** — 不阻断决策,退到 tie-random 选 baseline
5. **judge cost → 上限硬约束** — `judge_max_cost_per_decision_usd` 配置,超就降级
6. **meta-A/B 独立闭环** — `JudgeAcceptanceDecider` 在 judge prompt A/B 实验里跑,跟 `ABAcceptanceDecider` 不互相阻塞

### 1.3 调用次数估算

- Phase 5 decider 跑一次 = 一次决策
- judge 仅在 tie 时触发(估算 5-15% 的决策会 tie)
- 一次 tie 触发 = 2 次 judge 调用(baseline + challenger)
- 一个 A/B 实验假设跑 50 个 sample ≈ 5-8 次 tie ≈ 10-16 次 judge 调用
- 每次 judge 调用 ~$0.005(Sonnet 级),单实验 ~$0.05-0.08

---

## §2 数据模型

涉及 1 张表扩展 + 3 张新表。所有表都沿用 Phase 5 已建立的命名风格(`meta` 而非 `metadata`)。

### 2.1 扩展 `ab_decisions` 表(加 6 列)

```python
# 新增列(在 Phase 5 已建表基础上)
judge_triggered: bool              # 这次决策是否触发了 judge
judge_error: Optional[str]         # "parse_failed" | "timeout" | "llm_error" | "cost_cap"
                                  # | "experiment_cost_cap" | "no_active_version" | NULL
judge_tie_breaker_baseline: Optional[float]   # mean(3 维度),0-10,meta-eval 用数值列查询
judge_tie_breaker_challenger: Optional[float] # 同上
judge_scores_baseline: JSONB       # {"口吻": 7.5, "叙事连贯": 8.0, "风格调性": 6.5}
judge_scores_challenger: JSONB     # 同上结构
judge_rationale_baseline: TEXT     # ≤200 字,模型输出
judge_rationale_challenger: TEXT   # 同上
judge_model: VARCHAR(64)           # 实际调用的模型名,如 "claude-sonnet-4-6"
```

**索引**: 已有 `experiment_id` 索引,新加 `(judge_triggered, decision_at)` 用于"列出最近 N 次触发 judge 的决策"。

### 2.2 新表 `judge_prompt_versions`(类比 `prompt_versions`)

```python
class JudgePromptVersion:
    id: str                          # uuid
    version: str                     # 人类可读,如 "judge-v1-baseline"
    agent_name: str                  # 固定为 "judge_agent"
    prompt_text: TEXT                # judge prompt 完整模板(含 3 维度定义)
    is_active: bool                  # 哪个是当前 default
    ab_test_id: Optional[str]        # 如果在 A/B 中,关联到 judge_ab_tests
    experiment_state: str            # active / monitoring / early_stopped / rolled_back
    last_score: Optional[float]      # meta-eval 分数(agreement_rate)
    last_decision_at: Optional[datetime]
    experiment_history: JSONB        # Phase 5 同款 append_history
    created_at: datetime
```

### 2.3 新表 `judge_ab_tests`(类比 `ab_tests`)

```python
class JudgeABTest:
    id: str
    agent_name: str                  # 固定为 "judge_agent"
    baseline_version: str            # FK → judge_prompt_versions
    challenger_version: str          # FK
    status: str                      # running / completed / early_stopped / rolled_back
    config: JSONB                    # 复用 ab_config 结构
    started_at: datetime
    ended_at: Optional[datetime]
    winner: Optional[str]            # baseline / challenger
```

### 2.4 新表 `judge_call_log`(审计 + 成本追踪)

```python
class JudgeCallLog:
    id: str
    decision_id: str                 # FK → ab_decisions
    prompt_version_id: str           # FK → judge_prompt_versions
    model: VARCHAR(64)
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float                  # 精确到 0.0001
    called_at: datetime
```

**为什么 `judge_call_log` 独立成表**:
- 一个 decision 可能 0/1/2 次调用(0 = 未触发,1 = 降级,2 = 正常);扩展 `ab_decisions` 用 JSON 会让 schema 难以约束
- 成本聚合查询方便(`SUM(cost_usd) WHERE called_at > X`)

### 2.5 ab_config.yaml 扩展

```yaml
ab_acceptance:
  tie_threshold_pct: 1.0            # 硬指标差距 < 1% 触发 judge
  judge:
    enabled: true                   # 总开关(可一键关掉 judge 退回 Phase 5)
    model_default: "claude-sonnet-4-6"
    max_cost_per_decision_usd: 0.05 # 单次决策 judge 上限
    max_cost_per_experiment_usd: 0.50
    max_latency_ms: 10000            # 超时降级
    max_rationale_chars: 200         # 截断超长理由
    meta_eval:
      clear_cut_threshold_pct: 5.0  # 硬指标差距 > 5% 视为"clear cut"
      min_samples: 30               # meta-eval 至少 30 个样本才统计
      calibration_window_days: 14   # 用最近 14 天数据
```

---

## §3 JudgeAgent 设计

### 3.1 类骨架

```python
class JudgeAgent:
    def __init__(self, session, config: ABJudgeConfig):
        self.session = session
        self.config = config
        self.prompt_repo = JudgePromptVersionRepository(session)
        self.call_log_repo = JudgeCallLogRepository(session)

    async def judge_sample(
        self,
        chapter_text: str,
        version_id: Optional[str] = None,  # None = 拿 active version
    ) -> JudgeResult:
        # 1. 解析 prompt version
        pv = await self.prompt_repo.get_active_or_specific(version_id)
        # 2. 构造 prompt(chapter text + 3 维度定义)
        prompt = self._render_prompt(pv.prompt_text, chapter_text)
        # 3. 调 LLM
        client = llm_factory.get("JudgeAgent", task="judge_score")
        response = await client.acomplete([ChatMessage(role="user", content=prompt)], config)
        # 4. 解析 + 截断
        result = self._parse_response(response, pv.id)
        # 5. 写 call log
        await self.call_log_repo.log(result.call_metadata)
        return result.score_result
```

### 3.2 Judge prompt 模板(v1)

```
你是一位严格的网文质量评审,负责给单章打分。本章属于对比实验的一部分,
请独立于其他信息评估。

## 待评审章节
{chapter_text}

## 评分维度(0-10 分,允许小数)

1. **人物口吻**:角色对话和内心独白是否符合其既定性格、当前处境和关系网。
   - 9-10:口吻完全契合,角色感强
   - 7-8:基本一致,偶有可商榷处
   - 5-6:有 1-2 处明显偏差
   - <5:多处角色感崩塌

2. **叙事连贯**:时间线、空间、事件因果是否清晰,有无逻辑跳跃或重复。
   - 9-10:流畅自然
   - 7-8:可读,有 1 处小跳跃
   - 5-6:需要读者脑补才能跟上
   - <5:明显断裂

3. **风格调性**:与本作品已确立的语言风格、用词偏好、修辞习惯是否一致。
   - 9-10:风格统一
   - 7-8:基本统一,有 1-2 处可商榷
   - 5-6:出现风格漂移
   - <5:风格断裂

## 输出格式(严格 JSON,无任何额外文字)
{"口吻": 7.5, "叙事连贯": 8.0, "风格调性": 6.5, "理由": "≤200 字简评"}

不要在 JSON 之外输出任何内容。
```

### 3.3 输出解析 + 鲁棒性

```python
def _parse_response(self, response, version_id) -> JudgeResult:
    raw = strip_markdown_fences(response.content)
    try:
        data = json.loads(raw)
    except JSONDecodeError:
        # 提取第一个 { ... } 块(类似 call_and_parse 模式)
        data = extract_first_json_block(raw)
        if not data:
            raise JudgeParseError("无法解析 judge 输出")

    # 验证 3 个维度都在
    for dim in ("口吻", "叙事连贯", "风格调性"):
        if dim not in data or not isinstance(data[dim], (int, float)):
            raise JudgeParseError(f"缺失或非数值维度: {dim}")
        if not (0 <= data[dim] <= 10):
            raise JudgeParseError(f"维度超界: {dim}={data[dim]}")

    rationale = str(data.get("理由", ""))[: self.config.max_rationale_chars]
    return JudgeResult(
        scores={"口吻": data["口吻"], "叙事连贯": data["叙事连贯"], "风格调性": data["风格调性"]},
        rationale=rationale,
        call_metadata=CallMetadata(version_id=version_id, ...),
    )
```

### 3.4 复用模式(沿用 Phase 5)

- **call_and_parse** — `agents/_llm_helpers.py` 已有,自带 max_retries + 指数退避
- **LLMFactory.get("JudgeAgent", task="judge_score")** — 复用现有工厂,新加 `judge_agent` 配置块
- **JSON 解析鲁棒性** — 跟 critic_agent 一样的 fence-strip + first-JSON-block 提取

### 3.5 LLMFactory 配置新增

```yaml
# llm_config.yaml 追加
judge_agent:
  judge_score:
    primary:
      provider: "anthropic"
      model: "claude-sonnet-4-6"
      temperature: 0.2  # 低温度,judge 要稳定不要花样
    fallback:
      provider: "anthropic"
      model: "claude-haiku-4-5-20251001"
```

---

## §4 Meta-Eval:怎么评一个 judge prompt 的质量

这是 Phase 6 最关键的设计点 — judge 自己跑 A/B 时,**"准"的信号从哪来**。

### 4.1 Auto-Calibration:硬指标一致性(推荐方案)

**核心思想**: 当硬指标差距 **> 5%** 时(clear-cut case),"正确答案"已知 — 加权分高的版本就是更好的。这时候看 judge 跟正确答案的一致率。

```
clear-cut 例子:
  baseline weighted_score = 75
  challenger weighted_score = 82   # 差 7%,clear-cut
  → "正确答案" = challenger

  judge 给出:
    tie_breaker_baseline = 7.8
    tie_breaker_challenger = 8.2
  → judge 也选 challenger → 一致
```

**实现**:

```python
class JudgeMetaEvaluator:
    async def evaluate(self, judge_version_id: str) -> MetaEvalResult:
        """返回该 judge 版本最近 N 天内的一致率"""
        window_start = datetime.utcnow() - timedelta(days=self.config.calibration_window_days)

        # 1. 拉最近 14 天的 ab_decisions 中,
        #    hard_metric_gap > 5% 的子集(clear-cut cases)
        clear_cut_decisions = await self._fetch_clear_cut_decisions(window_start)

        # 2. 拉回当时这些决策的 judge tie_breaker 分数
        #    (judge 可能当时没被调用 — 因为不是 tie — 所以需要回放)
        #    → 见 §4.2 "事后重跑" 机制
        agreements = []
        for d in clear_cut_decisions:
            if d.judge_tie_breaker_baseline is None or d.judge_tie_breaker_challenger is None:
                continue  # 重放失败,跳过
            judge_winner = d.judge_tie_breaker_challenger > d.judge_tie_breaker_baseline
            hard_metric_winner = d.challenger_weighted > d.baseline_weighted
            agreements.append(judge_winner == hard_metric_winner)

        agreement_rate = sum(agreements) / len(agreements) if agreements else None
        return MetaEvalResult(
            version_id=judge_version_id,
            sample_size=len(agreements),
            agreement_rate=agreement_rate,
            window_start=window_start,
        )
```

**为什么是合适的信号**:
- 不需要人工标注,完全自动
- clear-cut case 的"正确答案"是 ground truth
- 一致率高 = judge 在硬指标明显时也能"看清"差距,质量高
- 一致率低 = judge 跟硬指标冲突,可能模型不适合做 judge

**已知局限**:
- 跟硬指标高一致 ≠ 真的好(可能只是"复述硬指标")
- 衡量的是"跟硬指标不矛盾",不是"看到硬指标看不到的东西"
- 这正是 §4.3 提到的"互补性"指标要补的,留作 Phase 7

### 4.2 事后重跑机制

**问题**: clear-cut 决策时 judge **未被调用**(只有 tie 才调)。要算一致率,得回放。

**解决方案**: `ab_decisions.judge_tie_breaker_*` 在真实 judge 调用时已写入。clear-cut 决策里这些列是 NULL(因为 judge 未被调用) — **回放时** 用 `decision.decided_at` 时点的 active judge version 重跑 JudgeAgent,得到 tie_breaker 值。

```python
async def _fetch_or_replay_tie_breaker(self, decision) -> tuple[Optional[float], Optional[float]]:
    """优先用 ab_decisions 上的真实 judge 结果,没有则用对应 prompt version 重跑"""
    if decision.judge_tie_breaker_baseline is not None and decision.judge_tie_breaker_challenger is not None:
        return decision.judge_tie_breaker_baseline, decision.judge_tie_breaker_challenger
    # 重放:用 decision.decided_at 时点的 active judge version
    historical_version = await self.prompt_repo.get_active_at(decision.decided_at)
    if historical_version is None:
        return None, None  # 历史 judge prompt 已删,无法回放
    return await self._replay_judge(historical_version, decision)
```

**成本控制**: 重放只在 meta-eval 时发生,不在线上路径。频率限制: 每 6 小时一次,或每次 `judge_prompt_versions` 更新后一次。

### 4.3 互补性指标(可选增强,Phase 6 留接口)

衡量"judge 看到了硬指标看不到的东西"。

**实现思路**: 在 tie cases 上,看 judge 给出的 tie_breaker 跟下游指标(`chapter_acceptance` 的最终 outcome、读者留存等)的相关性。

**Phase 6 处理**: 留接口,跑 stub 返回 `None`,**实现留到 Phase 7**(需要先有下游 outcome 数据积累)。

### 4.4 JudgeAcceptanceDecider 简化逻辑

meta-eval 给出 agreement_rate 后,Phase 5 的 `ABAcceptanceDecider` 直接复用:

```python
# JudgeAcceptanceDecider 内部
agreement_rate = meta_eval.agreement_rate
if agreement_rate >= 0.80:           # 跟硬指标高一致
    return DecideResult(action="accept", target="challenger")
elif agreement_rate <= 0.55:         # 几乎随机
    return DecideResult(action="early_stop", reason="low_calibration")
else:                                 # 中间地带,需要更多样本
    return DecideResult(action="continue_monitoring")
```

---

## §5 错误处理 + 成本控制

设计原则: **judge 任何失败都不能阻断决策** — judge 是辅助层,Phase 5 必须是 self-contained。

### 5.1 错误分类 + 降级路径

| 错误类型 | 触发条件 | 降级动作 | ab_decisions 记录 |
|---|---|---|---|
| **judge 解析失败** | LLM 输出非 JSON, 维度缺失/超界 | tie → 随机选 baseline | `judge_triggered=false, judge_error="parse_failed"` |
| **judge 超时** | `latency > max_latency_ms` (10s) | tie → 随机选 baseline | `judge_triggered=false, judge_error="timeout"` |
| **judge LLM 调用失败** | API 4xx/5xx, 重试 max_retries 后仍失败 | tie → 随机选 baseline | `judge_triggered=false, judge_error="llm_error"` |
| **单次 cost 超限** | `cost > max_cost_per_decision_usd` ($0.05) | 当前决策不调 judge | `judge_triggered=false, judge_error="cost_cap"` |
| **实验累计 cost 超限** | `sum(cost) > max_cost_per_experiment_usd` ($0.50) | 该实验后续决策都不调 judge | `judge_triggered=false, judge_error="experiment_cost_cap"` |
| **tie 双方 judge 失败** | baseline + challenger judge 都报错 | 退到 Phase 5 路径 — 随机或 baseline 胜 | 同上 |
| **judge prompt version 找不到** | `judge_prompt_versions` 没有 active | 全局禁用 judge,等同 `enabled=false` | `judge_triggered=false, judge_error="no_active_version"` |

**关键设计**: 所有降级路径都退到 Phase 5 的 **tie-random** 行为 — 不是阻塞决策,不是抛异常。

### 5.2 重试策略(沿用 call_and_parse)

```python
# agents/_llm_helpers.py 的 call_and_parse 已经处理:
# - 最多 max_retries(默认 3)次重试
# - 指数退避
# - 解析失败重试(可能模型第一次输出 markdown fence,第二次直接 JSON)
# - 单次调用失败不抛异常,返回 None 让上层处理
```

`JudgeAgent._parse_response` 只在 `call_and_parse` 重试用尽后才抛 `JudgeParseError` — 进入降级路径。

### 5.3 成本追踪 + 告警

```python
class JudgeCostGuard:
    def __init__(self, config, call_log_repo):
        self.config = config
        self.call_log = call_log_repo

    async def check_can_call(self, experiment_id: str) -> CostCheckResult:
        if not self.config.enabled:
            return CostCheckResult(allow=False, reason="judge_disabled")

        experiment_cost = await self.call_log.sum_cost_for_experiment(experiment_id)
        if experiment_cost > self.config.max_cost_per_experiment_usd:
            return CostCheckResult(allow=False, reason="experiment_cost_cap",
                                   current=experiment_cost)

        return CostCheckResult(allow=True)
```

**告警**(可选,Phase 6 可省): 当 `experiment_cost > 0.80 * max_cost_per_experiment_usd` 时,在 ExperimentView 上显示黄色 warning chip。

### 5.4 tie-random 的随机种子

为了可复现,`tie_random` 用 `experiment_id` 做种子哈希:

```python
def tie_random_pick(experiment_id: str, candidates: list[str]) -> str:
    seed = int(hashlib.sha256(experiment_id.encode()).hexdigest()[:8], 16)
    return candidates[seed % len(candidates)]
```

**好处**: 同一实验的 tie 决策可复现,debug 友好。**坏处**: 如果 baseline 一直命中,challenger 永远拿不到胜场 — 但这种 "systematic bias" 反而是想要观察的信号(可以人工干预)。

### 5.5 judge 自身异常的日志

```python
logger.error(
    "judge_failed",
    extra={
        "decision_id": decision_id,
        "experiment_id": experiment_id,
        "error_type": "parse_failed" | "timeout" | "llm_error" | ...,
        "error_detail": str(exc),
        "fallback": "tie_random",
    },
)
```

---

## §6 UI / 可视化

设计原则: **judge 结果对用户透明,但不打扰主流程**。在 Phase 5 既有 UI 上叠加,不重建。

### 6.1 涉及组件

```
ExperimentView.vue         ← 加 "judge" tab
ExperimentWidget.vue       ← 加 "judge 状态" 卡片
ExperimentToast.vue        ← 触发时多推一条 judge toast
ab_decisions 详情组件(新)  ← 展示单次决策的 judge 分数
```

### 6.2 ExperimentView 新增 Judge Tab

**入口**: 在现有 ExperimentView 的 tabs 列表追加:

```
[概览] [样本] [决策历史] [judge]    ← 顺序
```

**Judge Tab 内容**:

1. **顶部 metric 卡片**(3 张)
   - 平均一致率(agreement_rate) — 最近 14 天
   - 本月 judge 调用次数
   - 本月 judge 总成本
2. **当前 active judge prompt 卡片**
   - 版本号、创建时间、agreement_rate、sample_size
   - "view prompt" 按钮 → 弹窗显示完整 prompt template
3. **judge 决策历史表格**(类似 Phase 5 的 ab_decisions 表格)
   - 列:`decided_at | experiment_id | version_under_test | judge_winner | agreement_with_hard_metric | rationale_preview`
   - 点击行 → 展开 3 维度详细分(雷达图)
4. **judge 状态趋势折线图**(agreement_rate over time)

### 6.3 ExperimentWidget 改动(Dashboard 顶部)

在现有 "活跃实验 / 监控中实验" 卡片组旁,加 **judge 状态条**:

```
┌────────────────────────────────────────────────┐
│ Judge 状态: ✓ 启用  活跃 prompt: judge-v2      │
│ 一致率: 0.83  本月调用: 47 次  本月成本: $0.23 │
└────────────────────────────────────────────────┘
```

**降级时显示黄色 chip**:`Judge 已禁用 (experiment_cost_cap 触发)`。

### 6.4 ExperimentToast 改动

Phase 5 已经推 "实验采纳/回滚" 的 toast。judge 触发的决策加一条独立 toast:

```
🔍 judge 已介入,baseline 与 challenger 评分差距 0.4%
  → challenger 胜(tie_breaker 8.2 vs 7.9)
```

**toast 频率控制**: 不增加频率 — 一次决策只发一条 toast,带 judge 状态字段(`with_judge: true/false`)。

### 6.5 ab_decisions 详情(新组件 `ABDecisionDetail.vue`)

点击决策历史行 → 弹窗或抽屉,显示:

```
决策 ID: dec_abc123
触发时间: 2026-06-19 14:32
触发条件: tie (硬指标差距 0.6%)

硬指标:
  baseline:    critic=78  hook=true  thrill=true  → 0.5*78 + 0.3*1 + 0.2*1 = 39.5
  challenger:  critic=79  hook=true  thrill=true  → 0.5*79 + 0.3*1 + 0.2*1 = 39.8  [tie]

Judge 评分:
  baseline:    口吻=7.5  叙事连贯=8.0  风格调性=6.5  → tie_breaker=7.33
  challenger:  口吻=8.0  叙事连贯=8.5  风格调性=7.5  → tie_breaker=8.00
  模型: claude-sonnet-4-6
  理由 (baseline): "...风格略平淡,主角语气稍显犹豫..."
  理由 (challenger): "...口吻统一,推进节奏自然,伏笔铺垫到位..."

最终决策: challenger 胜
```

**雷达图**: 3 维度 baseline vs challenger 叠加显示,直观看出差距。

### 6.6 Judge Prompt 注册 UI(Phase 6 范围内,简化版)

**最小可用**: 一个 Modal + textarea,可以:
- 创建新 judge prompt version
- 设为 active
- 触发 judge_ab_test(选择 baseline + challenger)

**不做的**:
- A/B 启动/监控的完整 UI(沿用 Phase 5 ExperimentView)
- judge prompt 的版本对比视图(留到 Phase 7)
- judge prompt 的编辑历史 diff(留到 Phase 7)

---

## §7 测试策略

### 7.1 单元测试(目标 ≥ 90% 覆盖)

```
tests/
├── test_agents/
│   └── test_judge_agent.py                 (新) ~12 tests
├── test_services/
│   ├── test_judge_meta_evaluator.py         (新) ~8 tests
│   └── test_judge_cost_guard.py             (新) ~6 tests
├── test_repositories/
│   ├── test_judge_prompt_version_repo.py    (新) ~6 tests
│   └── test_judge_call_log_repo.py          (新) ~5 tests
└── test_api/
    └── test_judge_endpoints.py              (新) ~6 tests
```

**JudgeAgent 单测覆盖**:
- 正常路径(返回 3 维度 + 理由)
- 输出带 markdown fence 解析
- 维度缺失 → 抛 JudgeParseError
- 维度超界 → 抛 JudgeParseError
- 非 JSON 输出 → 抛 JudgeParseError
- 空 chapter_text → 抛 ValidationError
- LLM 超时 → 降级到 tie_random
- LLM 4xx/5xx → 重试 max_retries 后降级
- call_log 正确写入(检查 token/cost/latency 字段)
- 显式 version_id 走指定 prompt version
- version_id=None 拿 active version
- active version 找不到 → 抛 NoActiveVersionError

**Meta-evaluator 单测覆盖**:
- 空数据 → 返回 None 不抛异常
- 样本数 < min_samples → 返回 insufficient_data
- 全一致 → agreement_rate=1.0
- 全不一致 → agreement_rate=0.0
- 部分一致 → 算术平均
- clear-cut 筛选逻辑(> 5% 阈值)
- 时间窗口过滤
- 事后重跑机制(call_log 命中 vs 重新调用)

**Cost guard 单测覆盖**:
- enabled=false → 拒绝
- 实验累计 cost 超限 → 拒绝
- 实验累计 cost 在阈值内 → 允许
- 边界值(刚好等于阈值 → 拒绝)
- 并发安全(用锁防止 race condition 跨过阈值)

### 7.2 E2E 测试(`tests/test_e2e/test_phase6_judge_tiebreaker.py`)

**5 个核心场景**:

1. **happy path**: tie 触发 → judge 给出分数 → challenger 胜 → ab_decisions 正确记录 judge 字段
2. **非 tie 不触发**: 硬指标差距 > 1% → judge 跳过 → 走原 Phase 5 路径
3. **judge 解析失败 → 降级**: mock LLM 返回非 JSON → tie_random 选 baseline → 记录 `judge_error=parse_failed`
4. **cost cap 触发**: mock 高单价 token → 第二次 judge 调用被 cost guard 拒绝 → 记录 `judge_error=cost_cap`
5. **meta-eval agreement_rate 计算**: 注入历史 clear-cut 决策 → meta-eval 返回正确一致率

### 7.3 性能测试(`tests/test_performance/test_judge_perf.py`)

2 个性能基线:

- **judge_call_latency**: 1000 次连续 judge 调用,P95 < 8s,Sonnet 级模型 mock 200ms/次
- **meta_eval_throughput**: 10000 条历史决策,meta-eval 跑完 < 5s(必须用 SQL 聚合,不能 in-Python loop)

### 7.4 集成测试(可选,如果时间允许)

- 端到端跑一个完整 judge_ab_test lifecycle:创建 judge prompt v1 → 创建 judge prompt v2 → 启动 A/B → 注入 clear-cut 历史 → meta-eval 给出 challenger agreement_rate=0.85 → auto-accept v2 → 验证 active version 切换

### 7.5 测试 mock 模式(沿用 Phase 5)

```python
# conftest.py 已有 mock_llm_factory fixture(autouse)
# 写新测试时,需要 mock 特定 judge 输出,直接覆盖:

@pytest.fixture
def mock_judge_output():
    async def fake_complete(messages, config, **kwargs):
        return ChatMessage(role="assistant", content='{"口吻": 8.0, ...}')
    with patch("novel_dev.llm.llm_factory.get") as mock:
        mock.return_value.acomplete = fake_complete
        yield mock
```

### 7.6 回归保护

- 跑全部 1881+ Phase 5 测试,**确保零回归**
- JudgeAgent 不修改 Phase 5 任何代码,只通过 `ABAcceptanceDecider` 的扩展点接入
- `ab_decisions` 表加列用 Alembic 迁移,旧数据 `judge_triggered` 默认为 false

---

## §8 实施分波(预估 25 任务 / 9 波)

| 波次 | 内容 | 任务数 | 依赖 |
|---|---|---|---|
| 1 | 数据层:3 张新表 + ab_decisions 扩展 + Alembic 迁移 | 4 | Phase 5 |
| 2 | JudgeAgent + LLMFactory 配置 + judge prompt v1 | 3 | 波 1 |
| 3 | ABAcceptanceDecider 扩展(tie 检测 + 调 judge) | 2 | 波 2 |
| 4 | Cost guard + 降级路径 + tie-random | 3 | 波 2 |
| 5 | judge_prompt_versions / judge_ab_tests repository | 2 | 波 1 |
| 6 | JudgeAcceptanceDecider + meta-evaluator | 3 | 波 5 |
| 7 | API 端点(3 个)+ 单元测试补全 | 3 | 波 4 |
| 8 | Vue UI(Judge tab + DecisionDetail + Widget 状态条) | 3 | 波 7 |
| 9 | E2E + perf + 回归 | 2 | 全部 |

**总预估任务**: 25 个,5-6 个 wave。

---

## §9 风险 + 缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| judge LLM 调用延迟阻塞决策 | 中 | 高 | 10s timeout + 降级到 tie-random |
| 成本超支 | 低 | 中 | 单次 + 实验双重 cost cap |
| judge prompt v1 跟硬指标低一致 | 中 | 中 | 起步 v1 保守设计 + meta-eval 早停低一致版本 |
| meta-eval 样本不足(冷启动) | 高 | 低 | 留 `insufficient_data` 状态 + Phase 6 期间不自动切换 |
| 回放成本失控 | 低 | 中 | 重放频率限制(6h 一次) + 重放 cost 不计入实验 cap |
| judge 跟硬指标冲突导致决策回滚 | 中 | 中 | agreement_rate 阈值 0.80/0.55 + 早停机制 |

---

## §10 验收标准

- [ ] 5 个 E2E 场景全绿
- [ ] 新增单元测试 ≥ 90% 覆盖
- [ ] 全部 1881+ Phase 5 测试零回归
- [ ] 性能基线通过(judge_call P95 < 8s,meta_eval 10000 decisions < 5s)
- [ ] `ab_decisions` schema 迁移成功(开发 + 测试 DB)
- [ ] ExperimentView "judge" tab 可用
- [ ] 至少 1 个 judge_ab_test 完整跑完(baseline + challenger → meta-eval → auto-accept)
- [ ] cost guard 触发时正确降级,不抛异常
- [ ] ab_decisions `judge_triggered=false` 旧数据查询正常
