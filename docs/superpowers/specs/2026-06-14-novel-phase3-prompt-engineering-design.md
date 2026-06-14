# novel-dev 阶段三:Prompt 工程化 设计文档

> **For agentic workers:** 本 spec 进入实施阶段后会配套一个 `2026-06-14-novel-phase3-prompt-engineering-plan.md` 实施计划。

**日期:** 2026-06-14
**作者:** Claude + 用户
**状态:** 草案(待用户 review)
**衔接:** 阶段一(可观测性,已交付)+ 阶段二(Writer 防护,已交付)

---

## 1. 项目概述

阶段三把"Prompt 是散落在 agent 代码里的字符串"变成"Prompt 是可版本化、可测、可 A/B 的工程化资产",并把 LLM 根因分析嵌入自动重写决策,让重写更有针对性。

**核心交付:**
- 版本化 prompt 存储(`prompt_versions` 表)+ UI 采纳/回滚
- A/B test harness(agent 级 + 可配置 agent 列表)+ 概览 UI
- LLM 根因分析 service(`RootCauseAnalyzer`)+ 三个消费点接入(FastReview / Wirer / Writer)
- 8 个 agent 全部从 `PromptRegistry` 加载 prompt
- 1 波次交付(不分波)

---

## 2. 设计原则

- **不破坏阶段二**:阶段二已交付的 `RecommendationWirer` / `ChapterRewriteService` / `BeatCoverageValidator` 行为不变,根因分析作为**旁路**接入,不替换核心决策
- **不修改 QualityMetricsService 字段**:阶段一已预留 `prompt_version` 字段,本阶段只负责正确填值
- **失败软降级**:根因分析 LLM 失败 = summary 写"[分析失败]",confidence=0,流程不中断
- **A/B 不自动晋级**:每次采纳由人工点按钮,避免自动改默认 prompt 风险
- **冷启动安全**:`prompt_versions` 表空时,fallback 到 hardcoded 默认值 + 启动时同步

---

## 3. 整体架构与数据流

新增两个数据表:
- `prompt_versions` (agent_name, version, content, is_active, created_at, created_by, sample_count, parent_version, ab_test_id) — 版本化 prompt 存储
- `quality_root_cause` (chapter_id, analyzer_version, summary, suggested_actions JSONB, confidence, input_snapshot, created_at) — 根因分析结果
- `ab_tests` (agent_name, baseline_version, challenger_version, status, winner, started_at, ended_at, config) — A/B test 元数据

新增 3 个核心 service:
- `PromptRegistry` — 加载/版本切换/采纳回滚
- `ABTestRunner` — 拉起两个 prompt 版本,产出对比指标
- `RootCauseAnalyzer` — 同步 LLM 调用,读章节+元数据,产出 summary + suggested_actions

修改点:
- 8 个 agent 的 prompt 加载方式(从 hardcoded 字符串 → 调 `PromptRegistry.get(agent_name)`)
- `FastReviewAgent.review_standalone()` 末尾调 `RootCauseAnalyzer`
- `RecommendationWirer` 决策前读最近根因(给人工复审 UI 用)
- `WriterAgent` 拼装 chapter_context 时读上轮根因,作为顶部段
- 6 个 API 端点(prompt CRUD + A/B 启停 + 根因查询)
- 2 个前端视图(PromptVersionsManager + ABTestConsole)

数据流:
```
[LLM 调用] → agent 调 PromptRegistry.get_active(agent_name) → 拿当前 is_active 版本
                                    ↓
                          填 prompt_version 到调用上下文
                                    ↓
[指标落库] → chapter_quality_metrics (已有 prompt_version 字段)
                                    ↓
[A/B 启用] → ABTestRunner 同 agent 跑 v1+v2,记录两个版本的指标
                                    ↓
[UI] → 概览对比 → 一键采纳/回滚(改 is_active)
                                    ↓
[根因分析] → FastReviewAgent 末尾 → 存 quality_root_cause
                                    ↓
[消费方]
  - QualityRecommendationWidget 显示根因
  - RecommendationWirer 决策前读根因
  - WriterAgent 重写时把根因写进 chapter_context 顶部
```

---

## 4. 数据模型

### 4.1 `prompt_versions` 表

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | |
| `agent_name` | str | 8 个 agent 中的一个(`writer` / `critic` / ... 蛇形) |
| `version` | str | 语义化版本,例如 `v1.0`、`v1.1`、`v2.0` |
| `content` | text | prompt 模板,支持 `{var}` 占位 |
| `is_active` | bool | 是否为默认使用版本;同一 agent 只能有一个 true |
| `created_at` | datetime | |
| `created_by` | str | `user` / `system` / `ab_test_winner` |
| `sample_count` | int | 累积调用次数(回写 chapter_quality_metrics 时 +1) |
| `parent_version` | str? | A/B 晋级关系(从哪个版本晋级) |
| `ab_test_id` | UUID? | 关联的 A/B test |

唯一约束:(`agent_name`, `version`)

### 4.2 `quality_root_cause` 表

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | |
| `chapter_id` | str | 关联 chapter |
| `analyzer_version` | str | 根因分析器用的 prompt 版本(用于 A/B 评估根因质量) |
| `summary` | text | 2-3 句话的根因总结 |
| `suggested_actions` | JSONB | `[{action: str, target: str, severity: str}, ...]` |
| `confidence` | float | LLM 自评 0-1 |
| `input_snapshot` | JSONB | 章节前 500 字 + 元数据,审计用 |
| `created_at` | datetime | |

### 4.3 `ab_tests` 表

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | |
| `agent_name` | str | 哪个 agent 在跑 A/B(8 个 agent 中的一个) |
| `baseline_version` | str | 对照组 |
| `challenger_version` | str | 挑战组 |
| `status` | str | `running` / `completed` / `aborted` |
| `winner` | str? | `baseline` / `challenger` / `inconclusive` |
| `started_at` / `ended_at` | datetime | |
| `config` | JSONB | `{max_samples, min_samples_for_significance, score_field, scope_filter}` |

---

## 5. PromptRegistry 详细 API

```python
class PromptRegistry:
    async def get_active(self, agent_name: str) -> str:
        """拿当前 is_active 的 content,空则 fallback 到 hardcoded 默认值(冷启动)"""
    
    async def get_by_version(self, agent_name: str, version: str) -> str:
        """拿指定版本,用于 A/B 跑 challenger"""
    
    async def list_versions(self, agent_name: str) -> list[PromptVersion]:
        """列出所有版本(按 created_at 倒序)"""
    
    async def create_version(
        self, agent_name: str, version: str, content: str,
        is_active: bool = False, created_by: str = "user",
        parent_version: str | None = None,
    ) -> PromptVersion:
        """创建新版本,默认不激活"""
    
    async def set_active(self, agent_name: str, version: str) -> None:
        """原子切换默认版本:旧 active 关 + 新 active 开(同事务)"""
    
    async def rollback(self, agent_name: str, to_version: str) -> None:
        """回滚,等价于 set_active(agent_name, to_version)"""
    
    async def delete_version(self, agent_name: str, version: str) -> None:
        """只能删非 is_active,active 版本保护"""
```

---

## 6. A/B test 设计

### 6.1 接入位置

在 `LLMFactory` 层做版本选择(不是 agent 层),原因:
- 8 个 agent 改造成本最低,只改加载 prompt 的方式
- 同一 LLM client 可以服务多个 agent,A/B 决策集中
- 调用追踪和指标落库都在 LLM 边界,A/B 自然能复用到指标体系

```
Agent.llm_call() → 
  PromptRegistry.get_active(agent_name) → "v1.0 content" 
                              ↓
                ABTestMiddleware(agent_name) 
                              ↓
              if A/B running for this agent:
                  return (baseline_or_challenger, version)
              else:
                  return (active_version, "v1.0")
                              ↓
                    LLMFactory.get(agent_name).acomplete(messages, config)
                              ↓
                    QualityMetricsService.record(..., prompt_version=version)
```

### 6.2 调度策略

- 启用 A/B 时,`ABTestMiddleware` 在每次该 agent 的 LLM 调用前摇一个 hash(chapter_id) % 2:
  - 0 → baseline
  - 1 → challenger
- 这样同一 chapter 在 A/B 期间**稳定走一个版本**,避免同一章节被两种 prompt 各跑一遍(浪费)
- 统计口径:以 chapter_id 为单位,而不是 LLM 调用次数

### 6.3 终止行为

- 主动 stop():后续调用立即回到单版本模式,已完成指标保留
- 达到 `max_samples`:自动 stop,出 results
- 任意时刻都可以看 `results()`(部分数据也可看)

### 6.4 结果判定(写在 ABTestRunner.results())

- 必看:`overall_score` 的均值 + p 值(Welch's t-test)
- 次看:`issue_codes` 分布(挑战组 block 类问题更少 → 赢)
- 三看:`judge_consistency.cv` 系数(挑战组评分更稳定 → 赢)
- 都不显著 → `inconclusive`,需要更长样本
- `min_samples_for_significance` 阈值未达 → 标 `pending`,results 接口仍可访问但 winner 为 null

### 6.5 ABTestRunner 关键 API

```python
class ABTestRunner:
    async def start(
        self, agent_name: str,
        baseline_version: str, challenger_version: str,
        max_samples: int = 10, min_samples: int = 3,
    ) -> ABTest:
        """注册一个 A/B test,但不立即生效。生效靠 ABTestMiddleware 在每次 LLM 调用时检查"""
    
    async def stop(self, test_id: str) -> ABTest:
        """停 A/B,所有 agent 调用回到单版本模式"""
    
    async def results(self, test_id: str) -> ABTestResult:
        """计算 baseline vs challenger 的指标对比(score 均值/方差, issue_codes 分布)"""
    
    async def declare_winner(
        self, test_id: str, winner: str  # "baseline" | "challenger"
    ) -> None:
        """采纳赢家:set_active(agent_name, winner_version) + 标 ab_tests.winner"""
```

---

## 7. RootCauseAnalyzer 设计

```python
class RootCauseAnalyzer:
    def __init__(self, session, llm_factory, prompt_registry):
        self.session = session
        self.llm_factory = llm_factory
        self.prompt_registry = prompt_registry
    
    async def analyze(
        self, novel_id: str, chapter_id: str,
        chapter_text: str, score_breakdown: dict,
        issue_codes: list[str], beat_boundary_cards: list[BeatBoundaryCard],
    ) -> RootCauseResult:
        """读最新根因分析器 prompt 版本,跑 LLM,持久化结果"""
        
        prompt_template = await self.prompt_registry.get_active("root_cause_analyzer")
        prompt = prompt_template.format(
            chapter_text=chapter_text[:5000],  # 截断保护成本
            score_breakdown=json.dumps(score_breakdown, ensure_ascii=False),
            issue_codes=", ".join(issue_codes),
            beat_cards=format_beat_cards(beat_boundary_cards),
        )
        
        # 同步 LLM 调用,失败软降级
        try:
            response = await self.llm_factory.get("RootCauseAnalyzer").acomplete(...)
            result = self._parse_response(response.text)
        except Exception as exc:
            logger.warning("root_cause_analysis_failed", extra={...})
            return RootCauseResult(summary="[分析失败,请人工]", suggested_actions=[], confidence=0.0)
        
        # 持久化(成功 + 失败都记)
        await self._persist(novel_id, chapter_id, result)
        return result
```

### 7.1 输入构造规则

- 章节文本:截断到 5000 字(超过的部分用 "...[截断]" 标记)
- score_breakdown:JSON 序列化,内联
- issue_codes:逗号分隔字符串
- beat_boundary_cards:格式化文本(beat_index + must_cover + forbidden_materials)

### 7.2 输出 schema(LLM 必须返回)

```json
{
  "summary": "本章在 beat 2 处出现严重越界,主角色在 1500 字处提前执行了 beat 3 的对决事件。",
  "suggested_actions": [
    {"action": "重写 beat 2 之后", "target": "beat_index:2", "severity": "high"},
    {"action": "强化主角的内部冲突", "target": "dimension:character_consistency", "severity": "medium"}
  ],
  "confidence": 0.82
}
```

### 7.3 调用与持久化关系

- 每次 FastReview 后调一次,**无论章节 pass/warn/block**
- 失败软降级:LLM 出错时 summary 写"[分析失败]",confidence=0,继续流程
- 不写 A/B test 范围(根因分析质量提升是另一条线,后续阶段评估)

---

## 8. 与阶段二的连接

### 8.1 RecommendationWirer

`RecommendationWirer.evaluate_and_dispatch()` 第 1 步,增加:
```python
root_cause = await self.root_cause_repo.get_latest_for_chapter(chapter_id)
# 把 root_cause 写入 WireResult,给 UI 和下游用
return WireResult(action=..., recommendation=..., root_cause=root_cause)
```

### 8.2 ChapterRewriteService

`ChapterRewriteService.rewrite()` 调 `WriterAgent.write_standalone()` 前,增加:
```python
checkpoint["root_cause_segment"] = await self._build_root_cause_segment(chapter_id)
# WriterAgent 拼装 chapter_context 时,在顶部插入这个段
```

### 8.3 WriterAgent

`WriterAgent` 拼装 chapter_context 时,从 checkpoint 读 `root_cause_segment`,在 `chapter_context` 顶部加一个 `## 上轮根因建议` 段:
```
## 上轮根因建议
- summary: 本章在 beat 2 出现严重越界
- 建议动作 1: 重写 beat 2 之后(severity: high)
- 建议动作 2: 强化主角的内部冲突(severity: medium)
- confidence: 0.82
```

---

## 9. API 端点

```
GET    /api/prompts/{agent_name}/versions         # 列出版本
POST   /api/prompts/{agent_name}/versions         # 创建新版本
PATCH  /api/prompts/{agent_name}/versions/{ver}   # 改 content / is_active / rollback
DELETE /api/prompts/{agent_name}/versions/{ver}   # 只能删非 active

POST   /api/ab-tests                              # 启动 A/B
GET    /api/ab-tests                              # 列所有 A/B
GET    /api/ab-tests/{test_id}                    # 单个 A/B 详情 + results
POST   /api/ab-tests/{test_id}/stop               # 停 A/B
POST   /api/ab-tests/{test_id}/declare-winner     # 采纳赢家

GET    /api/chapters/{chapter_id}/root-cause      # 拿最近根因
```

---

## 10. 前端 UI

### 10.1 PromptVersionsManager.vue — `/admin/prompts`

- 顶部下拉:8 个 agent 切换
- 主区:版本列表(每行 = version / is_active 标记 / created_at / sample_count / 三个按钮)
- 按钮:查看 content(展开 modal)/ 编辑 / 设 active / 删除
- 创建新版本:弹窗输入 version 字符串 + content(textarea)
- 冷启动提示:"此 agent 尚无 prompt,使用系统默认值" + 按钮"导入默认"

### 10.2 ABTestConsole.vue — `/admin/ab-tests`

- 顶部:正在运行的 A/B 列表(每个卡片:agent_name / baseline vs challenger / 进度 n/max_samples / 当前 p 值)
- 卡片底部:三个按钮 — 查看详细 results / stop / 采纳 challenger(挑战者赢时高亮)
- 历史 A/B 列表:折叠区,只读
- 新建 A/B:弹窗,选 agent_name + baseline_version(默认 is_active) + challenger_version + max_samples

---

## 11. 配置段(llm_config.yaml 新增)

```yaml
phase3:
  root_cause_analyzer:
    enabled: true
    max_input_chars: 5000
    llm_client: "root_cause_analyzer"  # 复用现有 LLMFactory 客户端
  ab_test:
    enabled: true
    default_max_samples: 10
    default_min_samples: 3
    significance_alpha: 0.05
  prompt_registry:
    bootstrap_default: true  # 启动时若表空则同步 hardcoded 默认值
  cold_start:
    allow_hardcoded_fallback: true  # 找不到 prompt 时是否回退到代码内 hardcoded
```

---

## 12. 默认 prompt 来源

`src/novel_dev/agents/_default_prompts.py` 新文件,9 个常量字符串(8 个 agent + 1 个根因分析器):

```python
DEFAULT_PROMPTS = {
    "brainstorm": "...",
    "volume_planner": "...",
    "context_agent": "...",
    "writer": "...",
    "critic": "...",
    "editor": "...",
    "fast_review": "...",
    "librarian": "...",
    "root_cause_analyzer": "...",
}
```

每个 agent 文件内部改成:`PROMPT = await PromptRegistry(...).get_active(agent_name)`,在 `acomplete` 之前查一次并传入。

---

## 13. 错误处理

| 场景 | 行为 |
|---|---|
| `prompt_versions` 表空 + cold_start 关闭 | 启动报错 `ConfigError: prompt registry empty and cold_start disabled` |
| `prompt_versions` 表空 + cold_start 开启 | 启动时从 `_default_prompts.py` 同步,记日志 `prompt_registry_bootstrap` |
| A/B 进行中且引用版本被删除 | `set_active` / `delete_version` 拒绝并报错"version 正在 A/B test 中" |
| 根因分析 LLM 调用失败 | 软降级,summary 写"[分析失败]",confidence=0,继续流程 |
| 根因分析 LLM 输出无法解析 | 软降级同 LLM 失败 |
| A/B 中途 stop | 已生成的指标保留,后续调用走单版本 |
| `set_active` 旧版本与新版本同事务 | 旧 active 关 + 新 active 开,失败回滚 |
| UI 误删 active 版本 | API 拒绝(只能删非 active) |
| 多人同时编辑同一 agent 的 prompt | last-write-wins,记 `version_conflict` 警告日志 |
| QualityMetricsService 在 A/B 期记录时,`prompt_version` 字段 | 必填,且值是实际跑的版本(baseline 或 challenger) |

---

## 14. 测试策略

| 层级 | 覆盖范围 | 目标覆盖率 |
|---|---|---|
| PromptRegistry 单元 | CRUD、原子切换、cold start fallback、A/B 互斥保护 | ≥ 95% |
| ABTestRunner 单元 | 调度策略、results 计算、welch t-test、inconclusive 判定 | ≥ 90% |
| RootCauseAnalyzer 单元 | 输入构造、LLM 失败软降级、解析失败、持久化 | ≥ 90% |
| Agent 集成 | 8 个 agent 都通过 `PromptRegistry.get_active` 拿 prompt,跑通测试 | ≥ 80% |
| API 集成 | 6 个端点 round-trip,A/B 启停 → 采纳 → 切换生效 | ≥ 90% |
| E2E | 新小说从 brainstorm → librarian 全流程,每阶段 prompt_version 正确 | 必通 |

测试关键数据:
- 准备 5-10 个历史 chapter + 真实 quality_metrics 数据做 A/B 回放测试
- 根因分析 LLM 全部 mock(用 fixture 喂 LLM 输出)
- E2E 用 `test_novel_dev.db` 真实跑

---

## 15. 验收清单(阶段三完成标准)

### 功能

- [ ] 3 个新表(`prompt_versions` / `quality_root_cause` / `ab_tests`)Alembic 迁移可上可下
- [ ] 8 个 agent 全部从 `PromptRegistry.get_active` 加载 prompt,代码中无 hardcoded 字符串残留
- [ ] 启动时 cold-start 同步 `_default_prompts.py` → DB
- [ ] 6 个新 API 端点全通,集成测试覆盖
- [ ] 2 个新前端视图加载无错,关键交互(创建版本/启停 A/B/采纳)有端到端测试
- [ ] A/B test harness 跑通 baseline vs challenger,results 接口出 p 值 + winner
- [ ] 根因分析 LLM 跑通,summary + suggested_actions 落库,失败软降级
- [ ] WriterAgent 重写时从 DB 读根因,正确插入 chapter_context 顶部段
- [ ] RecommendationWirer 决策前读最近根因,WireResult 带 root_cause 字段
- [ ] QualityRecommendationWidget 显示根因 summary + suggested_actions
- [ ] `llm_config.yaml` 阶段三配置段有完整注释

### 质量

- [ ] PromptRegistry / ABTestRunner / RootCauseAnalyzer 覆盖率 ≥ 90%
- [ ] 8 个 agent 新代码行覆盖率 ≥ 80%
- [ ] 现有 `pytest tests/` 全绿(除 e2e 标记)
- [ ] 阶段三 E2E 测试 `tests/test_e2e/test_phase3_prompt_engineering.py` 跑通

### 文档与监控

- [ ] spec 文档 commit,关联阶段二的衔接点
- [ ] 5 条 logging 触发并落盘(prompt_registry_bootstrap, ab_test_started/stopped, root_cause_analysis_failed, version_conflict, prompt_version_applied)
- [ ] README 阶段三 section 更新

---

## 16. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 8 个 agent 一次改动,prompt 抽取时漏掉某个 case | 中 | 中 | 实施前先全量 grep 列出所有 prompt 字符串,逐个迁移;每个 agent 跑原有测试用例 |
| A/B test 把生产章节质量拉低 | 中 | 高 | A/B 默认不开启(需显式 API 调用);UI 上有"启用影响生产"的明确提示;新 prompt 必须先跑通 ab_test 才能采纳 |
| 根因分析 LLM 调用成本失控 | 中 | 中 | 截断章节 5000 字上限;同 chapter 只跑一次(用 cache key chapter_id+attempt_index);失败不计费 |
| Prompt 冷启动时 race condition(并发请求同时触发 bootstrap) | 低 | 中 | bootstrap 用 DB advisory lock 串行化 |
| 多人同时改 prompt 导致版本号冲突 | 中 | 低 | API 创建版本前查 `version` 唯一性,重复报错 |
| 8 个 agent 同时启用 A/B,LLM 调用次数翻倍 | 中 | 中 | 显式 `max_samples` 限流;`config.scope_filter` 限制参与 chapter(如只对某小说某章节) |
| 采纳 challenger 后旧 baseline 的指标被错误归属 | 低 | 中 | QualityMetricsService 落库时,`prompt_version` 字段就是实际跑的版本,采纳操作不影响历史数据 |

---

## 17. 范围外(明确不做)

- 根因分析本身的 A/B 评估(根因质量提升是另一条线,后续阶段评估)
- LLM 评分提示词 A/B(只覆盖 8 个生产 agent)
- Prompt diff 可视化(prompt 工程师级别的详细对比面板,UI 只给运营者看结果)
- 跨小说 prompt 共享市场(每个小说的 prompt 独立)
- 自动晋级(A/B 出结论后必须人工采纳)
- 引入第三方 prompt registry(自建即可)
- 阶段四及以后的工作(本 spec 终止于阶段三交付)

---

## 18. 实施策略

**1 波次交付**(不分波),按以下顺序:
1. DB 表 + migration + 默认 prompts 文件
2. PromptRegistry 实现 + 单元测试
3. 8 个 agent 迁移到 PromptRegistry
4. ABTestRunner + ABTestMiddleware 实现
5. RootCauseAnalyzer 实现
6. 3 个消费点接入(FastReview / Wirer / Writer)
7. API 端点实现
8. 前端视图实现
9. E2E 测试 + 全量测试 + 覆盖率验证

预计 18-25 个 commit。
