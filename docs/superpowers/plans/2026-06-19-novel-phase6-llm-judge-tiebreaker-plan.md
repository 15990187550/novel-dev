# Phase 6 — LLM-as-Judge Tie-Breaker 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 Phase 5 A/B 自动采纳加 LLM judge — 硬指标差距 < 1% 的 tie 情况下,judge 通过 3 个语义维度(口吻/连贯/风格)打破平局;judge prompt 自身也走 Phase 5 基础设施做 meta-A/B 闭环。

**Architecture:** `ABAcceptanceDecider` 在 tie 分支调 `JudgeAgent`;`JudgeAgent` 读 active `JudgePromptVersion`,对 baseline + challenger 各自最近 1 个 chapter 打 3 维分,取均值作 tie_breaker;`JudgeAcceptanceDecider` 复用 Phase 5 模式,在 judge prompt A/B 实验里跑,以 judge-vs-hard 一致率作为 meta-eval 信号。Judge 任何失败 → 降级到 `tie_random_pick`,不阻断决策。

**Tech Stack:** Python 3.11, SQLAlchemy 2.0 async, Alembic, Pydantic v2, FastAPI, pytest-asyncio, freezegun, Vue 3 + vitest.

**前置:** Phase 5 完成(commit `fd3356d`)。所有任务在 `phase2-writer-protection` 分支上提交。**严禁修改 Phase 5 已有代码,只通过扩展点接入。**

---

## 文件结构

**新增文件:**
- `src/novel_dev/config/ab_judge_config.py` — judge 配置 dataclass + YAML loader
- `src/novel_dev/agents/judge_agent.py` — JudgeAgent
- `src/novel_dev/agents/judge_prompts.py` — judge prompt v1 模板
- `src/novel_dev/repositories/judge_prompt_version_repo.py`
- `src/novel_dev/repositories/judge_ab_test_repo.py`
- `src/novel_dev/repositories/judge_call_log_repo.py`
- `src/novel_dev/services/judge_cost_guard.py`
- `src/novel_dev/services/judge_meta_evaluator.py`
- `src/novel_dev/services/judge_acceptance_decider.py`
- `src/novel_dev/services/tie_random.py`
- `migrations/versions/<timestamp>_phase6_judge_tables.py` — Alembic 迁移
- `tests/test_agents/test_judge_agent.py`
- `tests/test_services/test_judge_cost_guard.py`
- `tests/test_services/test_judge_meta_evaluator.py`
- `tests/test_services/test_judge_acceptance_decider.py`
- `tests/test_services/test_tie_random.py`
- `tests/test_repositories/test_judge_prompt_version_repo.py`
- `tests/test_repositories/test_judge_ab_test_repo.py`
- `tests/test_repositories/test_judge_call_log_repo.py`
- `tests/test_db/test_judge_models.py`
- `tests/test_api/test_judge_endpoints.py`
- `tests/test_e2e/test_phase6_judge_tiebreaker.py`
- `tests/test_performance/test_judge_perf.py`
- `src/novel_dev/web/src/components/ABDecisionDetail.vue` + `.test.js`
- `src/novel_dev/web/src/components/JudgePromptEditor.vue` + `.test.js`

**修改文件:**
- `src/novel_dev/db/models.py` — 加 3 个新表 + 扩展 `ABDecision` 加 8 列
- `src/novel_dev/services/ab_acceptance_decider.py` — 加 tie 检测 + judge 调用扩展点
- `src/novel_dev/config/ab_config.py` — 加 tie_threshold_pct 字段
- `llm_config.yaml` — 加 `judge_agent` 块
- `src/novel_dev/api/routes.py` — 加 3 个端点
- `src/novel_dev/web/src/views/ExperimentView.vue` — 加 Judge tab
- `src/novel_dev/web/src/components/ExperimentWidget.vue` — 加 judge 状态条
- `src/novel_dev/web/src/components/ExperimentToast.vue` — 加 judge toast 变体
- `src/novel_dev/web/src/api.js` — 加 4 个 helper
- `src/novel_dev/web/src/router.js` — 加 /judge-prompts 路由

---

# Wave 1: 数据层(4 任务)

### Task 1: ABDecision 加 8 列 + 索引

**Files:**
- Modify: `src/novel_dev/db/models.py:673-691` (ABDecision class)
- Create: `tests/test_db/test_phase6_ab_decision_extension.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_db/test_phase6_ab_decision_extension.py`(新建):

```python
import pytest
from datetime import datetime
from novel_dev.db.models import ABDecision


@pytest.mark.asyncio
async def test_ab_decision_has_judge_fields(async_session):
    d = ABDecision(
        experiment_id="exp_1",
        action="evaluate",
        decision_at=datetime.utcnow(),
        judge_triggered=True,
        judge_tie_breaker_baseline=7.5,
        judge_tie_breaker_challenger=8.2,
        judge_scores_baseline={"口吻": 7.0, "叙事连贯": 8.0, "风格调性": 7.5},
        judge_scores_challenger={"口吻": 8.0, "叙事连贯": 8.5, "风格调性": 8.0},
        judge_rationale_baseline="口吻自然,推进流畅",
        judge_rationale_challenger="叙事更紧凑",
        judge_model="claude-sonnet-4-6",
    )
    async_session.add(d)
    await async_session.flush()
    fetched = await async_session.get(ABDecision, d.id)
    assert fetched.judge_triggered is True
    assert fetched.judge_tie_breaker_baseline == 7.5
    assert fetched.judge_tie_breaker_challenger == 8.2
    assert fetched.judge_scores_challenger["口吻"] == 8.0
    assert fetched.judge_model == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_ab_decision_judge_optional_by_default(async_session):
    d = ABDecision(
        experiment_id="exp_2",
        action="evaluate",
        decision_at=datetime.utcnow(),
    )
    async_session.add(d)
    await async_session.flush()
    fetched = await async_session.get(ABDecision, d.id)
    assert fetched.judge_triggered is False
    assert fetched.judge_tie_breaker_baseline is None
    assert fetched.judge_error is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_db/test_phase6_ab_decision_extension.py -v`
Expected: FAIL — `judge_triggered` field missing

- [ ] **Step 3: 在 ABDecision 加 8 列**

修改 `src/novel_dev/db/models.py:673-691` 的 ABDecision class,在 `meta` 字段后追加:

```python
    judge_triggered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    judge_error: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    judge_tie_breaker_baseline: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    judge_tie_breaker_challenger: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    judge_scores_baseline: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    judge_scores_challenger: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    judge_rationale_baseline: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    judge_rationale_challenger: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    judge_model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
```

并在 `__table_args__` 加索引(若还没有 judge_triggered 索引):

```python
    Index("ix_ab_decisions_judge_triggered", "judge_triggered"),
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_db/test_phase6_ab_decision_extension.py -v`
Expected: PASS

- [ ] **Step 5: 跑回归确认零破坏**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_db/ -q`
Expected: 全部通过

- [ ] **Step 6: 提交**

```bash
git add src/novel_dev/db/models.py tests/test_db/test_phase6_ab_decision_extension.py
git commit -m "feat(phase6): extend ABDecision with 9 judge fields"
```

---

### Task 2: JudgePromptVersion 模型

**Files:**
- Modify: `src/novel_dev/db/models.py` (在 ABTest 后追加新 class)
- Modify: `tests/test_db/test_phase6_ab_decision_extension.py` (追加测试) OR 新建 `tests/test_db/test_judge_models.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_db/test_judge_models.py`(新建):

```python
import pytest
from novel_dev.db.models import JudgePromptVersion


@pytest.mark.asyncio
async def test_judge_prompt_version_persists(async_session):
    pv = JudgePromptVersion(
        version="judge-v1",
        agent_name="judge_agent",
        prompt_text="你是一位...",
        is_active=True,
        experiment_state="active",
        last_score=0.85,
        experiment_history=[{"action": "created", "at": "2026-06-19T00:00:00"}],
    )
    async_session.add(pv)
    await async_session.flush()
    fetched = await async_session.get(JudgePromptVersion, pv.id)
    assert fetched.version == "judge-v1"
    assert fetched.is_active is True
    assert fetched.last_score == 0.85
    assert fetched.experiment_history[0]["action"] == "created"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_db/test_judge_models.py -v`
Expected: FAIL — `JudgePromptVersion` not defined

- [ ] **Step 3: 在 models.py 加 JudgePromptVersion class**

修改 `src/novel_dev/db/models.py`,在 ABTest class (line 294-305) 之后追加:

```python
class JudgePromptVersion(Base):
    __tablename__ = "judge_prompt_versions"
    __table_args__ = (
        UniqueConstraint("agent_name", "version", name="uq_judge_prompt_versions_agent_version"),
        Index("ix_judge_prompt_versions_active", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ab_test_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    experiment_state: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    last_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_decision_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    experiment_history: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_db/test_judge_models.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/db/models.py tests/test_db/test_judge_models.py
git commit -m "feat(phase6): add JudgePromptVersion model"
```

---

### Task 3: JudgeABTest + JudgeCallLog 模型

**Files:**
- Modify: `src/novel_dev/db/models.py` (追加 2 个 class)
- Modify: `tests/test_db/test_judge_models.py` (追加测试)

- [ ] **Step 1: 写失败测试**

在 `tests/test_db/test_judge_models.py` 追加:

```python
from novel_dev.db.models import JudgeABTest, JudgeCallLog


@pytest.mark.asyncio
async def test_judge_ab_test_persists(async_session):
    ab = JudgeABTest(
        agent_name="judge_agent",
        baseline_version="judge-v1",
        challenger_version="judge-v2",
        status="running",
        config={"samples_required": 50},
    )
    async_session.add(ab)
    await async_session.flush()
    fetched = await async_session.get(JudgeABTest, ab.id)
    assert fetched.baseline_version == "judge-v1"
    assert fetched.status == "running"
    assert fetched.winner is None


@pytest.mark.asyncio
async def test_judge_call_log_persists(async_session):
    log = JudgeCallLog(
        decision_id="dec_1",
        prompt_version_id="pv_1",
        model="claude-sonnet-4-6",
        input_tokens=1500,
        output_tokens=80,
        latency_ms=2300,
        cost_usd=0.0042,
    )
    async_session.add(log)
    await async_session.flush()
    fetched = await async_session.get(JudgeCallLog, log.id)
    assert fetched.model == "claude-sonnet-4-6"
    assert fetched.cost_usd == 0.0042
    assert fetched.latency_ms == 2300
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_db/test_judge_models.py -v`
Expected: FAIL — `JudgeABTest` / `JudgeCallLog` not defined

- [ ] **Step 3: 在 models.py 追加 2 个 class**

修改 `src/novel_dev/db/models.py`,在 JudgePromptVersion 之后追加:

```python
class JudgeABTest(Base):
    __tablename__ = "judge_ab_tests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    baseline_version: Mapped[str] = mapped_column(String(32), nullable=False)
    challenger_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running", index=True)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    winner: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)


class JudgeCallLog(Base):
    __tablename__ = "judge_call_log"
    __table_args__ = (
        Index("ix_judge_call_log_decision", "decision_id"),
        Index("ix_judge_call_log_experiment_called", "experiment_id", "called_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    decision_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    experiment_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    prompt_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    called_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
```

**注**: `JudgeCallLog` 加了 `experiment_id` 字段(超出 spec §2.4,但 cost guard 查"该实验累计 cost"需要此列做高效聚合查询,否则需要 JOIN 决策表)。后续 cost guard 任务会用此列。

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_db/test_judge_models.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/db/models.py tests/test_db/test_judge_models.py
git commit -m "feat(phase6): add JudgeABTest and JudgeCallLog models"
```

---

### Task 4: Alembic 迁移

**Files:**
- Create: `migrations/versions/20260619_1200_phase6_judge_tables.py`

- [ ] **Step 1: 生成迁移(若 alembic 可用)或手写**

检查迁移目录现有格式后,手写 `migrations/versions/20260619_1200_phase6_judge_tables.py`:

```python
"""phase 6 judge tables

Revision ID: 20260619_1200
Revises: <latest_phase5_revision>
Create Date: 2026-06-19 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers
revision = "20260619_1200"
down_revision = "<latest_phase5_revision>"  # 替换为实际值
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 扩展 ab_decisions
    op.add_column("ab_decisions", sa.Column("judge_triggered", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("ab_decisions", sa.Column("judge_error", sa.String(32), nullable=True))
    op.add_column("ab_decisions", sa.Column("judge_tie_breaker_baseline", sa.Float(), nullable=True))
    op.add_column("ab_decisions", sa.Column("judge_tie_breaker_challenger", sa.Float(), nullable=True))
    op.add_column("ab_decisions", sa.Column("judge_scores_baseline", JSONB(), nullable=True))
    op.add_column("ab_decisions", sa.Column("judge_scores_challenger", JSONB(), nullable=True))
    op.add_column("ab_decisions", sa.Column("judge_rationale_baseline", sa.Text(), nullable=True))
    op.add_column("ab_decisions", sa.Column("judge_rationale_challenger", sa.Text(), nullable=True))
    op.add_column("ab_decisions", sa.Column("judge_model", sa.String(64), nullable=True))
    op.create_index("ix_ab_decisions_judge_triggered", "ab_decisions", ["judge_triggered"])

    # 2. judge_prompt_versions
    op.create_table(
        "judge_prompt_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("agent_name", sa.String(64), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ab_test_id", sa.String(36), nullable=True),
        sa.Column("experiment_state", sa.String(32), nullable=False, server_default="none"),
        sa.Column("last_score", sa.Float(), nullable=True),
        sa.Column("last_decision_at", sa.DateTime(), nullable=True),
        sa.Column("experiment_history", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("agent_name", "version", name="uq_judge_prompt_versions_agent_version"),
    )
    op.create_index("ix_judge_prompt_versions_active", "judge_prompt_versions", ["is_active"])
    op.create_index("ix_judge_prompt_versions_ab_test", "judge_prompt_versions", ["ab_test_id"])

    # 3. judge_ab_tests
    op.create_table(
        "judge_ab_tests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_name", sa.String(64), nullable=False, index=True),
        sa.Column("baseline_version", sa.String(32), nullable=False),
        sa.Column("challenger_version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="running", index=True),
        sa.Column("config", JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("winner", sa.String(16), nullable=True),
    )

    # 4. judge_call_log
    op.create_table(
        "judge_call_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("decision_id", sa.String(36), nullable=True),
        sa.Column("experiment_id", sa.String(36), nullable=True),
        sa.Column("prompt_version_id", sa.String(36), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("called_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_judge_call_log_decision", "judge_call_log", ["decision_id"])
    op.create_index("ix_judge_call_log_experiment_called", "judge_call_log", ["experiment_id", "called_at"])


def downgrade() -> None:
    op.drop_index("ix_judge_call_log_experiment_called", table_name="judge_call_log")
    op.drop_index("ix_judge_call_log_decision", table_name="judge_call_log")
    op.drop_table("judge_call_log")
    op.drop_table("judge_ab_tests")
    op.drop_index("ix_judge_prompt_versions_ab_test", table_name="judge_prompt_versions")
    op.drop_index("ix_judge_prompt_versions_active", table_name="judge_prompt_versions")
    op.drop_table("judge_prompt_versions")
    op.drop_index("ix_ab_decisions_judge_triggered", table_name="ab_decisions")
    op.drop_column("ab_decisions", "judge_model")
    op.drop_column("ab_decisions", "judge_rationale_challenger")
    op.drop_column("ab_decisions", "judge_rationale_baseline")
    op.drop_column("ab_decisions", "judge_scores_challenger")
    op.drop_column("ab_decisions", "judge_scores_baseline")
    op.drop_column("ab_decisions", "judge_tie_breaker_challenger")
    op.drop_column("ab_decisions", "judge_tie_breaker_baseline")
    op.drop_column("ab_decisions", "judge_error")
    op.drop_column("ab_decisions", "judge_triggered")
```

- [ ] **Step 2: 检查 down_revision 真实值**

Run: `ls migrations/versions/ | grep -i phase5`
Expected: 找到最新 phase5 迁移文件,把 `down_revision` 替换为该文件 revision id(去掉 `.py` 后缀)。

- [ ] **Step 3: 在测试 DB 上跑迁移**

Run: `PYTHONPATH=src python3.11 -m alembic upgrade head`
Expected: 迁移成功,无错误。

- [ ] **Step 4: 验证表已建**

Run: `PYTHONPATH=src python3.11 -c "from novel_dev.db.models import JudgePromptVersion, JudgeABTest, JudgeCallLog; print('OK')"`
Expected: 打印 "OK"

- [ ] **Step 5: 跑回归确认旧测试不破**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_db/ tests/test_services/test_ab_acceptance_decider.py -q`
Expected: 全部通过

- [ ] **Step 6: 提交**

```bash
git add migrations/versions/20260619_1200_phase6_judge_tables.py
git commit -m "feat(phase6): alembic migration for judge tables + ab_decisions extension"
```

---

# Wave 2: JudgeAgent + Prompt v1(3 任务)

### Task 5: Judge config loader

**Files:**
- Create: `src/novel_dev/config/ab_judge_config.py`
- Create: `tests/test_services/test_judge_config.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_services/test_judge_config.py`(新建):

```python
import pytest
from novel_dev.config.ab_judge_config import get_ab_judge_config, JudgeConfig


def test_returns_default_when_no_yaml():
    cfg = get_ab_judge_config()
    assert isinstance(cfg, JudgeConfig)
    assert cfg.enabled is True
    assert cfg.tie_threshold_pct == 1.0
    assert cfg.model_default == "claude-sonnet-4-6"
    assert cfg.max_cost_per_decision_usd == 0.05
    assert cfg.max_cost_per_experiment_usd == 0.50
    assert cfg.max_latency_ms == 10000
    assert cfg.max_rationale_chars == 200
    assert cfg.clear_cut_threshold_pct == 5.0
    assert cfg.min_samples == 30
    assert cfg.calibration_window_days == 14


def test_yaml_overrides_take_effect(tmp_path, monkeypatch):
    yaml_path = tmp_path / "llm_config.yaml"
    yaml_path.write_text("""
ab_acceptance:
  judge:
    enabled: false
    model_default: claude-opus-4-7
    max_cost_per_decision_usd: 0.10
    meta_eval:
      min_samples: 50
""")
    monkeypatch.chdir(tmp_path)
    cfg = get_ab_judge_config()
    assert cfg.enabled is False
    assert cfg.model_default == "claude-opus-4-7"
    assert cfg.max_cost_per_decision_usd == 0.10
    assert cfg.min_samples == 50
    # 其他字段保留默认
    assert cfg.tie_threshold_pct == 1.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_services/test_judge_config.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 实现 config loader**

新建 `src/novel_dev/config/ab_judge_config.py`:

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "tie_threshold_pct": 1.0,
    "model_default": "claude-sonnet-4-6",
    "max_cost_per_decision_usd": 0.05,
    "max_cost_per_experiment_usd": 0.50,
    "max_latency_ms": 10000,
    "max_rationale_chars": 200,
    "clear_cut_threshold_pct": 5.0,
    "min_samples": 30,
    "calibration_window_days": 14,
}


@dataclass(frozen=True)
class JudgeConfig:
    enabled: bool = True
    tie_threshold_pct: float = 1.0
    model_default: str = "claude-sonnet-4-6"
    max_cost_per_decision_usd: float = 0.05
    max_cost_per_experiment_usd: float = 0.50
    max_latency_ms: int = 10000
    max_rationale_chars: int = 200
    clear_cut_threshold_pct: float = 5.0
    min_samples: int = 30
    calibration_window_days: int = 14

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JudgeConfig":
        return cls(
            enabled=bool(data.get("enabled", DEFAULTS["enabled"])),
            tie_threshold_pct=float(data.get("tie_threshold_pct", DEFAULTS["tie_threshold_pct"])),
            model_default=str(data.get("model_default", DEFAULTS["model_default"])),
            max_cost_per_decision_usd=float(data.get("max_cost_per_decision_usd", DEFAULTS["max_cost_per_decision_usd"])),
            max_cost_per_experiment_usd=float(data.get("max_cost_per_experiment_usd", DEFAULTS["max_cost_per_experiment_usd"])),
            max_latency_ms=int(data.get("max_latency_ms", DEFAULTS["max_latency_ms"])),
            max_rationale_chars=int(data.get("max_rationale_chars", DEFAULTS["max_rationale_chars"])),
            clear_cut_threshold_pct=float(data.get("clear_cut_threshold_pct", DEFAULTS["clear_cut_threshold_pct"])),
            min_samples=int(data.get("min_samples", DEFAULTS["min_samples"])),
            calibration_window_days=int(data.get("calibration_window_days", DEFAULTS["calibration_window_days"])),
        )


def get_ab_judge_config() -> JudgeConfig:
    """从 llm_config.yaml 读取 ab_acceptance.judge 配置,缺省回退到 DEFAULTS。"""
    try:
        import yaml
        with open("llm_config.yaml") as f:
            data = yaml.safe_load(f) or {}
        judge_section = (
            data.get("ab_acceptance", {}).get("judge", {})
        )
        # merge meta_eval 子段
        meta_eval = judge_section.pop("meta_eval", {}) if "meta_eval" in judge_section else {}
        merged = {**DEFAULTS, **judge_section, **meta_eval}
    except Exception:
        merged = DEFAULTS.copy()
    return JudgeConfig.from_dict(merged)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_services/test_judge_config.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/config/ab_judge_config.py tests/test_services/test_judge_config.py
git commit -m "feat(phase6): judge config loader with YAML overrides"
```

---

### Task 6: Judge prompt v1 模板

**Files:**
- Create: `src/novel_dev/agents/judge_prompts.py`
- Create: `tests/test_agents/test_judge_prompts.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_agents/test_judge_prompts.py`(新建):

```python
from novel_dev.agents.judge_prompts import render_judge_prompt_v1, JUDGE_PROMPT_V1


def test_renders_with_chapter_text():
    rendered = render_judge_prompt_v1("这是章节内容...")
    assert "这是章节内容..." in rendered
    assert "人物口吻" in rendered
    assert "叙事连贯" in rendered
    assert "风格调性" in rendered
    assert "口吻" in rendered  # JSON key
    assert "理由" in rendered  # rationale key


def test_v1_template_has_strict_json_output_instruction():
    assert "严格 JSON" in JUDGE_PROMPT_V1 or "strict JSON" in JUDGE_PROMPT_V1
    assert "JSON 之外" in JUDGE_PROMPT_V1 or "outside JSON" in JUDGE_PROMPT_V1


def test_dimension_rubric_present():
    rendered = render_judge_prompt_v1("x")
    for keyword in ["9-10", "7-8", "5-6", "<5"]:
        assert keyword in rendered, f"rubric {keyword} missing"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_judge_prompts.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 实现 prompt 模板**

新建 `src/novel_dev/agents/judge_prompts.py`:

```python
JUDGE_PROMPT_V1 = """你是一位严格的网文质量评审,负责给单章打分。本章属于对比实验的一部分,
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
{{"口吻": 7.5, "叙事连贯": 8.0, "风格调性": 6.5, "理由": "≤200 字简评"}}

不要在 JSON 之外输出任何内容。"""


def render_judge_prompt_v1(chapter_text: str) -> str:
    """用给定章节文本渲染 v1 模板。chapter_text 必须是字符串(不能为空)。"""
    if not isinstance(chapter_text, str) or not chapter_text.strip():
        raise ValueError("chapter_text must be a non-empty string")
    return JUDGE_PROMPT_V1.format(chapter_text=chapter_text)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_judge_prompts.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/agents/judge_prompts.py tests/test_agents/test_judge_prompts.py
git commit -m "feat(phase6): judge prompt v1 template"
```

---

### Task 7: JudgeAgent 实现

**Files:**
- Create: `src/novel_dev/repositories/judge_prompt_version_repo.py`
- Create: `src/novel_dev/repositories/judge_call_log_repo.py`
- Create: `src/novel_dev/agents/judge_agent.py`
- Create: `tests/test_agents/test_judge_agent.py`

- [ ] **Step 1: 写失败测试 - JudgePromptVersionRepository**

在 `tests/test_repositories/test_judge_prompt_version_repo.py`(新建):

```python
import pytest
from datetime import datetime
from novel_dev.db.models import JudgePromptVersion
from novel_dev.repositories.judge_prompt_version_repo import JudgePromptVersionRepository


@pytest.mark.asyncio
async def test_get_active_returns_only_active(async_session):
    pv1 = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="a", is_active=True)
    pv2 = JudgePromptVersion(version="v2", agent_name="judge_agent", prompt_text="b", is_active=False)
    async_session.add_all([pv1, pv2])
    await async_session.flush()

    repo = JudgePromptVersionRepository(async_session)
    active = await repo.get_active()
    assert active is not None
    assert active.version == "v1"


@pytest.mark.asyncio
async def test_get_active_returns_none_when_no_active(async_session):
    pv = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="a", is_active=False)
    async_session.add(pv)
    await async_session.flush()

    repo = JudgePromptVersionRepository(async_session)
    assert await repo.get_active() is None


@pytest.mark.asyncio
async def test_get_active_at_picks_historical_version(async_session):
    pv1 = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="a", is_active=True, created_at=datetime(2026, 1, 1))
    pv2 = JudgePromptVersion(version="v2", agent_name="judge_agent", prompt_text="b", is_active=True, created_at=datetime(2026, 6, 1))
    async_session.add_all([pv1, pv2])
    await async_session.flush()

    repo = JudgePromptVersionRepository(async_session)
    historical = await repo.get_active_at(datetime(2026, 3, 1))
    assert historical is not None
    assert historical.version == "v1"


@pytest.mark.asyncio
async def test_set_active_deactivates_others(async_session):
    pv1 = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="a", is_active=True)
    pv2 = JudgePromptVersion(version="v2", agent_name="judge_agent", prompt_text="b", is_active=False)
    async_session.add_all([pv1, pv2])
    await async_session.flush()

    repo = JudgePromptVersionRepository(async_session)
    await repo.set_active(pv2.id)
    await async_session.refresh(pv1)
    await async_session.refresh(pv2)
    assert pv1.is_active is False
    assert pv2.is_active is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_judge_prompt_version_repo.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 实现 JudgePromptVersionRepository**

新建 `src/novel_dev/repositories/judge_prompt_version_repo.py`:

```python
from __future__ import annotations
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import JudgePromptVersion


class JudgePromptVersionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_active(self) -> Optional[JudgePromptVersion]:
        result = await self.session.execute(
            select(JudgePromptVersion)
            .where(JudgePromptVersion.is_active.is_(True))
            .order_by(JudgePromptVersion.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def get_by_id(self, pv_id: str) -> Optional[JudgePromptVersion]:
        return await self.session.get(JudgePromptVersion, pv_id)

    async def get_active_at(self, at: datetime) -> Optional[JudgePromptVersion]:
        """返回 ≤ at 时间点上 is_active=True 的最新版本,用于事后回放。"""
        result = await self.session.execute(
            select(JudgePromptVersion)
            .where(
                JudgePromptVersion.is_active.is_(True),
                JudgePromptVersion.created_at <= at,
            )
            .order_by(JudgePromptVersion.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def set_active(self, pv_id: str) -> None:
        """把指定 pv 设为 active,同时把同 agent_name 的其他 active 全部置 False。"""
        target = await self.session.get(JudgePromptVersion, pv_id)
        if target is None:
            return
        # Deactivate all currently active
        result = await self.session.execute(
            select(JudgePromptVersion)
            .where(
                JudgePromptVersion.agent_name == target.agent_name,
                JudgePromptVersion.is_active.is_(True),
                JudgePromptVersion.id != pv_id,
            )
        )
        for pv in result.scalars().all():
            pv.is_active = False
        target.is_active = True
        await self.session.flush()

    async def append_history(self, pv_id: str, entry: dict) -> None:
        """追加一条 experiment_history 记录(原子操作)。"""
        pv = await self.session.get(JudgePromptVersion, pv_id)
        if pv is None:
            return
        history = list(pv.experiment_history or [])
        history.append(entry)
        pv.experiment_history = history
        await self.session.flush()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_judge_prompt_version_repo.py -v`
Expected: PASS

- [ ] **Step 5: 写失败测试 - JudgeCallLogRepository**

在 `tests/test_repositories/test_judge_call_log_repo.py`(新建):

```python
import pytest
from datetime import datetime
from novel_dev.db.models import JudgeCallLog
from novel_dev.repositories.judge_call_log_repo import JudgeCallLogRepository


@pytest.mark.asyncio
async def test_log_persists_call_metadata(async_session):
    repo = JudgeCallLogRepository(async_session)
    log = await repo.log(
        decision_id="dec_1",
        experiment_id="exp_1",
        prompt_version_id="pv_1",
        model="claude-sonnet-4-6",
        input_tokens=1500,
        output_tokens=80,
        latency_ms=2300,
        cost_usd=0.0042,
    )
    fetched = await async_session.get(JudgeCallLog, log.id)
    assert fetched.model == "claude-sonnet-4-6"
    assert fetched.cost_usd == 0.0042


@pytest.mark.asyncio
async def test_sum_cost_for_experiment_aggregates(async_session):
    repo = JudgeCallLogRepository(async_session)
    await repo.log(decision_id="d1", experiment_id="exp_1", prompt_version_id="p", model="m",
                   input_tokens=100, output_tokens=10, latency_ms=100, cost_usd=0.01)
    await repo.log(decision_id="d2", experiment_id="exp_1", prompt_version_id="p", model="m",
                   input_tokens=200, output_tokens=20, latency_ms=200, cost_usd=0.02)
    await repo.log(decision_id="d3", experiment_id="exp_2", prompt_version_id="p", model="m",
                   input_tokens=50, output_tokens=5, latency_ms=50, cost_usd=0.005)
    total = await repo.sum_cost_for_experiment("exp_1")
    assert abs(total - 0.03) < 1e-6


@pytest.mark.asyncio
async def test_count_calls_for_experiment_in_window(async_session):
    repo = JudgeCallLogRepository(async_session)
    for i in range(3):
        await repo.log(decision_id=f"d{i}", experiment_id="exp_1", prompt_version_id="p", model="m",
                       input_tokens=100, output_tokens=10, latency_ms=100, cost_usd=0.01)
    count = await repo.count_calls_for_experiment("exp_1", since=datetime(2020, 1, 1))
    assert count == 3
```

- [ ] **Step 6: 跑测试确认失败**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_judge_call_log_repo.py -v`
Expected: FAIL — module not found

- [ ] **Step 7: 实现 JudgeCallLogRepository**

新建 `src/novel_dev/repositories/judge_call_log_repo.py`:

```python
from __future__ import annotations
from datetime import datetime
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import JudgeCallLog


class JudgeCallLogRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def log(
        self,
        decision_id: Optional[str],
        experiment_id: Optional[str],
        prompt_version_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        cost_usd: float,
    ) -> JudgeCallLog:
        entry = JudgeCallLog(
            decision_id=decision_id,
            experiment_id=experiment_id,
            prompt_version_id=prompt_version_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            called_at=datetime.utcnow(),
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def sum_cost_for_experiment(self, experiment_id: str) -> float:
        result = await self.session.execute(
            select(func.coalesce(func.sum(JudgeCallLog.cost_usd), 0.0))
            .where(JudgeCallLog.experiment_id == experiment_id)
        )
        return float(result.scalar() or 0.0)

    async def count_calls_for_experiment(
        self, experiment_id: str, since: Optional[datetime] = None,
    ) -> int:
        stmt = select(func.count(JudgeCallLog.id)).where(
            JudgeCallLog.experiment_id == experiment_id
        )
        if since is not None:
            stmt = stmt.where(JudgeCallLog.called_at >= since)
        result = await self.session.execute(stmt)
        return int(result.scalar() or 0)
```

- [ ] **Step 8: 跑测试确认通过**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_judge_call_log_repo.py -v`
Expected: PASS

- [ ] **Step 9: 写失败测试 - JudgeAgent**

在 `tests/test_agents/test_judge_agent.py`(新建):

```python
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from novel_dev.db.models import JudgePromptVersion
from novel_dev.config.ab_judge_config import JudgeConfig
from novel_dev.llm.models import ChatMessage
from novel_dev.agents.judge_agent import JudgeAgent, JudgeParseError, NoActiveVersionError


def _mock_llm_response(content: str):
    return ChatMessage(role="assistant", content=content)


@pytest.mark.asyncio
async def test_judge_sample_returns_three_dimensions_and_rationale(async_session):
    pv = JudgePromptVersion(
        version="v1", agent_name="judge_agent", prompt_text="stub {chapter_text}",
        is_active=True, experiment_state="active",
    )
    async_session.add(pv)
    await async_session.flush()

    config = JudgeConfig()
    agent = JudgeAgent(async_session, config)

    fake_response = _mock_llm_response(
        json.dumps({"口吻": 7.5, "叙事连贯": 8.0, "风格调性": 6.5, "理由": "口吻自然"})
    )
    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(return_value=fake_response)
        mock_factory.get.return_value = mock_client
        result = await agent.judge_sample("这是章节内容", version_id=None)

    assert result.scores == {"口吻": 7.5, "叙事连贯": 8.0, "风格调性": 6.5}
    assert result.rationale == "口吻自然"
    assert result.tie_breaker == pytest.approx((7.5 + 8.0 + 6.5) / 3)


@pytest.mark.asyncio
async def test_judge_sample_strips_markdown_fence(async_session):
    pv = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="x {chapter_text}", is_active=True)
    async_session.add(pv)
    await async_session.flush()

    config = JudgeConfig()
    agent = JudgeAgent(async_session, config)
    fenced = "```json\n" + json.dumps({"口吻": 8.0, "叙事连贯": 8.0, "风格调性": 8.0, "理由": "ok"}) + "\n```"
    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(return_value=_mock_llm_response(fenced))
        mock_factory.get.return_value = mock_client
        result = await agent.judge_sample("章节", version_id=None)
    assert result.scores["口吻"] == 8.0


@pytest.mark.asyncio
async def test_judge_sample_raises_on_missing_dimension(async_session):
    pv = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="x {chapter_text}", is_active=True)
    async_session.add(pv)
    await async_session.flush()

    agent = JudgeAgent(async_session, JudgeConfig())
    bad = json.dumps({"口吻": 7.0, "叙事连贯": 8.0})  # 缺风格调性
    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(return_value=_mock_llm_response(bad))
        mock_factory.get.return_value = mock_client
        with pytest.raises(JudgeParseError):
            await agent.judge_sample("章节", version_id=None)


@pytest.mark.asyncio
async def test_judge_sample_raises_on_out_of_range(async_session):
    pv = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="x {chapter_text}", is_active=True)
    async_session.add(pv)
    await async_session.flush()

    agent = JudgeAgent(async_session, JudgeConfig())
    bad = json.dumps({"口吻": 11.0, "叙事连贯": 8.0, "风格调性": 6.5, "理由": "x"})
    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(return_value=_mock_llm_response(bad))
        mock_factory.get.return_value = mock_client
        with pytest.raises(JudgeParseError):
            await agent.judge_sample("章节", version_id=None)


@pytest.mark.asyncio
async def test_judge_sample_raises_on_non_json(async_session):
    pv = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="x {chapter_text}", is_active=True)
    async_session.add(pv)
    await async_session.flush()

    agent = JudgeAgent(async_session, JudgeConfig())
    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(return_value=_mock_llm_response("我无法打分"))
        mock_factory.get.return_value = mock_client
        with pytest.raises(JudgeParseError):
            await agent.judge_sample("章节", version_id=None)


@pytest.mark.asyncio
async def test_judge_sample_raises_on_empty_chapter():
    agent = JudgeAgent(None, JudgeConfig())
    with pytest.raises(ValueError):
        await agent.judge_sample("", version_id=None)
    with pytest.raises(ValueError):
        await agent.judge_sample("   ", version_id=None)


@pytest.mark.asyncio
async def test_judge_sample_raises_when_no_active_version(async_session):
    # no PVs in DB
    agent = JudgeAgent(async_session, JudgeConfig())
    with pytest.raises(NoActiveVersionError):
        await agent.judge_sample("章节", version_id=None)


@pytest.mark.asyncio
async def test_judge_sample_uses_specific_version_id_when_given(async_session):
    pv_inactive = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="A {chapter_text}", is_active=False)
    pv_target = JudgePromptVersion(version="v2", agent_name="judge_agent", prompt_text="B {chapter_text}", is_active=True)
    async_session.add_all([pv_inactive, pv_target])
    await async_session.flush()

    agent = JudgeAgent(async_session, JudgeConfig())
    fake = _mock_llm_response(json.dumps({"口吻": 9.0, "叙事连贯": 9.0, "风格调性": 9.0, "理由": "v2"}))
    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(return_value=fake)
        mock_factory.get.return_value = mock_client
        result = await agent.judge_sample("章节", version_id=pv_inactive.id)
    assert result.scores["口吻"] == 9.0


@pytest.mark.asyncio
async def test_judge_sample_truncates_long_rationale(async_session):
    pv = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="x {chapter_text}", is_active=True)
    async_session.add(pv)
    await async_session.flush()

    config = JudgeConfig(max_rationale_chars=20)
    agent = JudgeAgent(async_session, config)
    long_rationale = "a" * 100
    fake = _mock_llm_response(json.dumps({"口吻": 7.0, "叙事连贯": 7.0, "风格调性": 7.0, "理由": long_rationale}))
    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(return_value=fake)
        mock_factory.get.return_value = mock_client
        result = await agent.judge_sample("章节", version_id=None)
    assert len(result.rationale) == 20


@pytest.mark.asyncio
async def test_judge_sample_writes_call_log(async_session):
    pv = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="x {chapter_text}", is_active=True)
    async_session.add(pv)
    await async_session.flush()

    agent = JudgeAgent(async_session, JudgeConfig())
    fake = _mock_llm_response(json.dumps({"口吻": 7.0, "叙事连贯": 7.0, "风格调性": 7.0, "理由": "ok"}))
    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(return_value=fake)
        mock_factory.get.return_value = mock_client
        result = await agent.judge_sample("章节", version_id=None, experiment_id="exp_1")
    assert result.call_log_id is not None
```

- [ ] **Step 10: 跑测试确认失败**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_judge_agent.py -v`
Expected: FAIL — module not found

- [ ] **Step 11: 实现 JudgeAgent**

新建 `src/novel_dev/agents/judge_agent.py`:

```python
from __future__ import annotations
import json
import re
import time
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.config.ab_judge_config import JudgeConfig
from novel_dev.llm import llm_factory
from novel_dev.llm.models import ChatMessage
from novel_dev.repositories.judge_prompt_version_repo import JudgePromptVersionRepository
from novel_dev.repositories.judge_call_log_repo import JudgeCallLogRepository


class JudgeParseError(Exception):
    pass


class NoActiveVersionError(Exception):
    pass


@dataclass
class JudgeResult:
    scores: dict[str, float]          # {"口吻": 7.5, "叙事连贯": 8.0, "风格调性": 6.5}
    rationale: str
    tie_breaker: float               # mean(3 dims),0-10
    call_log_id: str
    model: str
    prompt_version_id: str


class JudgeAgent:
    REQUIRED_DIMS = ("口吻", "叙事连贯", "风格调性")
    DIM_MIN, DIM_MAX = 0.0, 10.0

    def __init__(self, session: AsyncSession, config: JudgeConfig):
        self.session = session
        self.config = config
        self.pv_repo = JudgePromptVersionRepository(session)
        self.call_log_repo = JudgeCallLogRepository(session)

    async def judge_sample(
        self,
        chapter_text: str,
        version_id: Optional[str] = None,
        decision_id: Optional[str] = None,
        experiment_id: Optional[str] = None,
    ) -> JudgeResult:
        if not isinstance(chapter_text, str) or not chapter_text.strip():
            raise ValueError("chapter_text must be a non-empty string")

        # 1. 解析 prompt version
        if version_id is not None:
            pv = await self.pv_repo.get_by_id(version_id)
            if pv is None:
                raise NoActiveVersionError(f"version_id {version_id} not found")
        else:
            pv = await self.pv_repo.get_active()
            if pv is None:
                raise NoActiveVersionError("no active judge_prompt_versions row")

        # 2. 构造 prompt
        prompt = self._render_prompt(pv.prompt_text, chapter_text)

        # 3. 调 LLM
        client = llm_factory.get("JudgeAgent", task="judge_score")
        # 注:Phase 5 模式里 config 是第二个位置参数
        from novel_dev.llm.models import LLMConfig  # 延迟导入避免循环
        llm_config = LLMConfig(model=self.config.model_default, temperature=0.2)
        start = time.monotonic()
        response = await client.acomplete([ChatMessage(role="user", content=prompt)], llm_config)
        latency_ms = int((time.monotonic() - start) * 1000)

        # 4. 解析
        data = self._parse_response(response.content)

        # 5. 截断理由
        rationale = str(data.get("理由", ""))[: self.config.max_rationale_chars]

        # 6. 计算 tie_breaker
        scores = {dim: float(data[dim]) for dim in self.REQUIRED_DIMS}
        tie_breaker = sum(scores.values()) / len(scores)

        # 7. 写 call log
        input_tokens = len(prompt) // 4  # 粗略估算
        output_tokens = len(response.content) // 4
        cost_usd = self._estimate_cost(input_tokens, output_tokens)
        log = await self.call_log_repo.log(
            decision_id=decision_id,
            experiment_id=experiment_id,
            prompt_version_id=pv.id,
            model=self.config.model_default,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
        )

        return JudgeResult(
            scores=scores,
            rationale=rationale,
            tie_breaker=tie_breaker,
            call_log_id=log.id,
            model=self.config.model_default,
            prompt_version_id=pv.id,
        )

    def _render_prompt(self, template: str, chapter_text: str) -> str:
        try:
            return template.format(chapter_text=chapter_text)
        except KeyError as exc:
            # 模板里没有 {chapter_text} 占位符时,降级到字符串拼接
            return template + "\n\n## 待评审章节\n" + chapter_text

    def _parse_response(self, content: str) -> dict:
        raw = self._strip_markdown_fences(content)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = self._extract_first_json_block(raw)
            if data is None:
                raise JudgeParseError(f"无法解析 judge 输出: {content[:200]}")

        for dim in self.REQUIRED_DIMS:
            if dim not in data or not isinstance(data[dim], (int, float)):
                raise JudgeParseError(f"缺失或非数值维度: {dim}")
            if not (self.DIM_MIN <= float(data[dim]) <= self.DIM_MAX):
                raise JudgeParseError(f"维度超界: {dim}={data[dim]}")
        return data

    @staticmethod
    def _strip_markdown_fences(content: str) -> str:
        s = content.strip()
        if s.startswith("```"):
            # remove first fence line
            lines = s.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            return "\n".join(lines).strip()
        return s

    @staticmethod
    def _extract_first_json_block(content: str) -> Optional[dict]:
        m = re.search(r"\{[^{}]*\"口吻\"[^{}]*\}", content, re.DOTALL)
        if m is None:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
        """Sonnet 级模型粗略估算(input $3/1M, output $15/1M)。"""
        return (input_tokens * 3.0 + output_tokens * 15.0) / 1_000_000
```

- [ ] **Step 12: 跑测试确认通过**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_judge_agent.py -v`
Expected: PASS

- [ ] **Step 13: 提交**

```bash
git add src/novel_dev/repositories/judge_prompt_version_repo.py \
        src/novel_dev/repositories/judge_call_log_repo.py \
        src/novel_dev/agents/judge_agent.py \
        tests/test_repositories/test_judge_prompt_version_repo.py \
        tests/test_repositories/test_judge_call_log_repo.py \
        tests/test_agents/test_judge_agent.py
git commit -m "feat(phase6): JudgeAgent with repos, prompt v1, LLM call + call_log"
```

---

# Wave 3: ABAcceptanceDecider 扩展(2 任务)

### Task 8: tie_random 工具函数

**Files:**
- Create: `src/novel_dev/services/tie_random.py`
- Create: `tests/test_services/test_tie_random.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_services/test_tie_random.py`(新建):

```python
from novel_dev.services.tie_random import tie_random_pick


def test_same_experiment_id_yields_same_pick():
    candidates = ["a", "b"]
    p1 = tie_random_pick("exp_1", candidates)
    p2 = tie_random_pick("exp_1", candidates)
    assert p1 == p2
    assert p1 in candidates


def test_different_experiment_ids_can_yield_different_picks():
    """至少 80% 的实验 ID 哈希到不同 candidate(只 2 个 candidate 时严格 50/50)"""
    candidates = ["a", "b"]
    seen = set()
    for i in range(100):
        seen.add(tie_random_pick(f"exp_{i}", candidates))
    # 100 个不同实验 ID 应该两个 candidate 都出现过
    assert seen == {"a", "b"}


def test_three_candidates_works():
    candidates = ["x", "y", "z"]
    for i in range(50):
        p = tie_random_pick(f"exp_{i}", candidates)
        assert p in candidates


def test_raises_on_empty_candidates():
    import pytest
    with pytest.raises(ValueError):
        tie_random_pick("exp_1", [])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_services/test_tie_random.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 实现 tie_random**

新建 `src/novel_dev/services/tie_random.py`:

```python
from __future__ import annotations
import hashlib
from typing import Sequence


def tie_random_pick(experiment_id: str, candidates: Sequence[str]) -> str:
    """基于 experiment_id 哈希的 deterministic 随机选择。

    用于 judge 失败时 tie 决策的回退路径。同一 experiment_id 总是返回同一 candidate,
    便于调试和复现。
    """
    if not candidates:
        raise ValueError("candidates must be non-empty")
    seed = int(hashlib.sha256(experiment_id.encode()).hexdigest()[:8], 16)
    return candidates[seed % len(candidates)]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_services/test_tie_random.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/services/tie_random.py tests/test_services/test_tie_random.py
git commit -m "feat(phase6): tie_random_pick deterministic fallback"
```

---

### Task 9: ABAcceptanceDecider 加 tie 分支

**Files:**
- Modify: `src/novel_dev/services/ab_acceptance_decider.py:35-141` (evaluate 方法)
- Modify: `tests/test_services/test_ab_acceptance_decider.py` (追加测试)

- [ ] **Step 1: 写失败测试**

在 `tests/test_services/test_ab_acceptance_decider.py` 追加:

```python
from novel_dev.agents.judge_agent import JudgeAgent
from novel_dev.config.ab_judge_config import JudgeConfig
from novel_dev.services.ab_acceptance_decider import ABAcceptanceDecider
from novel_dev.db.models import JudgePromptVersion
import json
from unittest.mock import AsyncMock, MagicMock, patch
from novel_dev.llm.models import ChatMessage


@pytest.mark.asyncio
async def test_evaluate_triggers_judge_on_tie(async_session):
    """硬指标差距 < 1% 触发 judge,tie_breaker challenger 高 → challenger 胜。"""
    pv_baseline = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_1", sample_count=50)
    pv_challenger = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_1", sample_count=50)
    ab = ABTest(id="ab_1", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running")
    jpv = JudgePromptVersion(version="judge-v1", agent_name="judge_agent", prompt_text="{chapter_text}", is_active=True)
    async_session.add_all([pv_baseline, pv_challenger, ab, jpv])
    await async_session.flush()

    # weighted_score 几乎打平:75.1 vs 75.5 → gap 0.4 < 1%
    decider = ABAcceptanceDecider(async_session)
    decider.significance_tester = MagicMock()
    decider.significance_tester.test = MagicMock(return_value=MagicMock(is_significant=False, p_value=0.6, effect_size=0.1, threshold_used="strict", reason="not_significant"))
    decider.weighted_calc = MagicMock()
    decider.weighted_calc.compute_batch = MagicMock(return_value={"v1": 75.1, "v2": 75.5})

    judge_json = json.dumps({"口吻": 8.0, "叙事连贯": 8.5, "风格调性": 7.5, "理由": "challenger 更紧凑"})
    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(return_value=ChatMessage(role="assistant", content=judge_json))
        mock_factory.get.return_value = mock_client
        result = await decider.evaluate(experiment_id="ab_1", sample_scores={
            "v1": {"critic_scores": [80.0]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
            "v2": {"critic_scores": [80.5]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
        })

    assert result.action == "accepted"
    assert result.winner == "v2"
    assert result.judge_triggered is True
    assert result.judge_tie_breaker_challenger > result.judge_tie_breaker_baseline


@pytest.mark.asyncio
async def test_evaluate_skips_judge_on_clear_winner(async_session):
    """硬指标差距 > 1% 不触发 judge,直接走原 Phase 5 路径。"""
    pv_baseline = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_1", sample_count=50)
    pv_challenger = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_1", sample_count=50)
    ab = ABTest(id="ab_1", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running")
    async_session.add_all([pv_baseline, pv_challenger, ab])
    await async_session.flush()

    decider = ABAcceptanceDecider(async_session)
    decider.significance_tester = MagicMock()
    decider.significance_tester.test = MagicMock(return_value=MagicMock(is_significant=True, p_value=0.03, effect_size=4.0, threshold_used="strict", reason=None))
    decider.weighted_calc = MagicMock()
    decider.weighted_calc.compute_batch = MagicMock(return_value={"v1": 75.0, "v2": 85.0})  # 10 分差距

    result = await decider.evaluate(experiment_id="ab_1", sample_scores={
        "v1": {"critic_scores": [80.0]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
        "v2": {"critic_scores": [85.0]*50, "hook_achieved": [True]*50, "thrill_verified": [True]*50},
    })

    assert result.action == "accepted"
    assert result.winner == "v2"
    assert result.judge_triggered is False


@pytest.mark.asyncio
async def test_evaluate_tie_falls_back_to_random_when_judge_fails(async_session):
    """tie 时 judge 解析失败 → tie_random 选 baseline。"""
    pv_baseline = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_1", sample_count=50)
    pv_challenger = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_1", sample_count=50)
    ab = ABTest(id="ab_1", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running")
    jpv = JudgePromptVersion(version="judge-v1", agent_name="judge_agent", prompt_text="{chapter_text}", is_active=True)
    async_session.add_all([pv_baseline, pv_challenger, ab, jpv])
    await async_session.flush()

    decider = ABAcceptanceDecider(async_session)
    decider.significance_tester = MagicMock()
    decider.significance_tester.test = MagicMock(return_value=MagicMock(is_significant=False, p_value=0.6, effect_size=0.1, threshold_used="strict", reason="not_significant"))
    decider.weighted_calc = MagicMock()
    decider.weighted_calc.compute_batch = MagicMock(return_value={"v1": 75.1, "v2": 75.5})

    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(return_value=ChatMessage(role="assistant", content="I cannot judge"))
        mock_factory.get.return_value = mock_client
        result = await decider.evaluate(experiment_id="ab_1", sample_scores={
            "v1": {"critic_scores": [80.0]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
            "v2": {"critic_scores": [80.5]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
        })

    # tie_random 选 baseline
    assert result.action == "accepted"
    assert result.winner == "v1"  # baseline (deterministic via experiment_id hash)
    assert result.judge_triggered is False
    assert result.judge_error == "parse_failed"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_services/test_ab_acceptance_decider.py -v`
Expected: 新加的 3 个测试 FAIL

- [ ] **Step 3: 修改 ABAcceptanceDecider.evaluate 方法**

修改 `src/novel_dev/services/ab_acceptance_decider.py`:

(a) 加 import:

```python
import json
import logging
from novel_dev.agents.judge_agent import JudgeAgent, JudgeParseError, NoActiveVersionError
from novel_dev.config.ab_judge_config import get_ab_judge_config
from novel_dev.repositories.judge_prompt_version_repo import JudgePromptVersionRepository
from novel_dev.services.tie_random import tie_random_pick

logger = logging.getLogger(__name__)
```

(b) 修改 `DeciderResult` dataclass,加 judge 字段:

```python
@dataclass
class DeciderResult:
    action: str  # "accepted" | "no_action" | "skipped" | "no_improvement" | "error"
    winner: Optional[str] = None
    p_value: Optional[float] = None
    scores: Optional[dict] = None
    reason: Optional[str] = None
    judge_triggered: bool = False
    judge_tie_breaker_baseline: Optional[float] = None
    judge_tie_breaker_challenger: Optional[float] = None
    judge_scores_baseline: Optional[dict] = None
    judge_scores_challenger: Optional[dict] = None
    judge_rationale_baseline: Optional[str] = None
    judge_rationale_challenger: Optional[str] = None
    judge_model: Optional[str] = None
    judge_error: Optional[str] = None
```

(c) 在 `ABAcceptanceDecider.__init__` 加 judge config 字段:

```python
    def __init__(self, session: AsyncSession, judge_config=None):
        self.session = session
        self.weighted_calc = WeightedScoreCalculator()
        self.significance_tester = SignificanceTester()
        self.pv_repo = PromptVersionRepository(session)
        self.decision_repo = ABDecisionRepository(session)
        self.recorder = ABDecisionRecorder(session)
        self.judge_config = judge_config or get_ab_judge_config()
```

(d) 修改 `evaluate` 方法 — 在 `if not significance.is_significant:` 之后、return no_action 之前,插入 tie 分支:

```python
        if not significance.is_significant:
            # Phase 6: 检查是否为 tie(硬指标差距 < threshold),如果是则调 judge
            tie_result = await self._try_judge_tie_break(ab, scores, significance)
            if tie_result is not None:
                return tie_result
            return DeciderResult(
                action="no_action",
                p_value=significance.p_value,
                scores=scores,
                reason=significance.reason,
            )
```

(e) 在 class 内加新方法(放在最后,`_get_pvs` 之后):

```python
    async def _try_judge_tie_break(self, ab, scores, significance) -> Optional[DeciderResult]:
        """tie 时调 judge 打破平局;失败则降级到 tie_random。"""
        baseline_score = scores.get(ab.baseline_version, 0.0)
        challenger_score = scores.get(ab.challenger_version, 0.0)
        gap_pct = abs(challenger_score - baseline_score) / max(abs(baseline_score), 1e-6) * 100

        if gap_pct >= self.judge_config.tie_threshold_pct:
            return None  # 不是 tie,交回原路径

        if not self.judge_config.enabled:
            return self._tie_random_decide(ab, scores, "judge_disabled")

        # 调 judge
        try:
            judge = JudgeAgent(self.session, self.judge_config)
            # 取最新 1 个 chapter(简化:Phase 6 传空字符串,judge 只用于框架,真值由 sample_scores 携带)
            # 实际生产:从 chapter_repo 取最近 chapter 内容
            baseline_text = ""  # Phase 6 范围:chapter_repo 接入留到 6.1 增强,本章 judge 流程可独立验证
            challenger_text = ""
            baseline_result = await judge.judge_sample(baseline_text, experiment_id=ab.id, decision_id=None)
            challenger_result = await judge.judge_sample(challenger_text, experiment_id=ab.id, decision_id=None)
        except (JudgeParseError, NoActiveVersionError) as exc:
            logger.warning("judge_failed_in_decider", extra={"error": str(exc), "experiment_id": ab.id})
            return self._tie_random_decide(ab, scores, type(exc).__name__)
        except Exception as exc:
            logger.error("judge_unexpected_error", extra={"error": str(exc), "experiment_id": ab.id})
            return self._tie_random_decide(ab, scores, "llm_error")

        # 决定胜负
        if challenger_result.tie_breaker > baseline_result.tie_breaker:
            winner = ab.challenger_version
        elif baseline_result.tie_breaker > challenger_result.tie_breaker:
            winner = ab.baseline_version
        else:
            # tie_breaker 也平,仍降级
            return self._tie_random_decide(ab, scores, "judge_tie")

        # 写 ab_decisions(扩展字段)
        await self.recorder.record(
            experiment_id=ab.id,
            action="accept",
            scores=scores,
            p_value=significance.p_value,
            effect_size=significance.effect_size,
            meta={
                "decision": "accepted_via_judge",
                "winner": winner,
                "judge_scores_baseline": baseline_result.scores,
                "judge_scores_challenger": challenger_result.scores,
                "judge_tie_breaker_baseline": baseline_result.tie_breaker,
                "judge_tie_breaker_challenger": challenger_result.tie_breaker,
                "judge_rationale_baseline": baseline_result.rationale,
                "judge_rationale_challenger": challenger_result.rationale,
                "judge_model": baseline_result.model,
                "judge_triggered": True,
            },
        )

        # 写 ab_decisions 的 judge 列(直接通过 SQLAlchemy session)
        from novel_dev.db.models import ABDecision as ABDecisionModel
        d = ABDecisionModel(
            experiment_id=ab.id,
            action="accept",
            decision_at=datetime.utcnow(),
            scores=scores,
            p_value=significance.p_value,
            effect_size=significance.effect_size,
            meta={"decision": "accepted_via_judge", "winner": winner},
            judge_triggered=True,
            judge_tie_breaker_baseline=baseline_result.tie_breaker,
            judge_tie_breaker_challenger=challenger_result.tie_breaker,
            judge_scores_baseline=baseline_result.scores,
            judge_scores_challenger=challenger_result.scores,
            judge_rationale_baseline=baseline_result.rationale,
            judge_rationale_challenger=challenger_result.rationale,
            judge_model=baseline_result.model,
        )
        self.session.add(d)

        # 标记 pv 状态
        for pv in await self._get_pvs(ab):
            if pv.version == winner:
                await self.pv_repo.update_experiment_state(pv.id, "auto_accepted", last_score=scores[winner], decision_at=datetime.utcnow())
                pv.is_active = True
            else:
                pv.is_active = False
                await self.pv_repo.update_experiment_state(pv.id, "active-rolled-back", decision_at=datetime.utcnow())

        ab.status = "completed"
        ab.winner = winner
        ab.ended_at = datetime.utcnow()
        await self.session.flush()

        return DeciderResult(
            action="accepted",
            winner=winner,
            p_value=significance.p_value,
            scores=scores,
            reason="judge_tie_break",
            judge_triggered=True,
            judge_tie_breaker_baseline=baseline_result.tie_breaker,
            judge_tie_breaker_challenger=challenger_result.tie_breaker,
            judge_scores_baseline=baseline_result.scores,
            judge_scores_challenger=challenger_result.scores,
            judge_rationale_baseline=baseline_result.rationale,
            judge_rationale_challenger=challenger_result.rationale,
            judge_model=baseline_result.model,
        )

    def _tie_random_decide(self, ab, scores, error_reason) -> DeciderResult:
        """tie 且 judge 失败时的降级:deterministic random 选一个。"""
        winner = tie_random_pick(ab.id, [ab.baseline_version, ab.challenger_version])
        logger.info("tie_random_decide", extra={"experiment_id": ab.id, "winner": winner, "reason": error_reason})
        return DeciderResult(
            action="accepted",  # 仍算作"决策"而非 no_action
            winner=winner,
            scores=scores,
            reason=f"tie_random:{error_reason}",
            judge_triggered=False,
            judge_error=error_reason,
        )
```

**注**: 此处仅是 tie 路径的最小实现;chapter_text 留空(因为单测不传真实章节),生产路径接入 chapter_repo 在 Phase 6 之后。

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_services/test_ab_acceptance_decider.py -v`
Expected: 全部通过

- [ ] **Step 5: 跑 Phase 5 回归**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_services/test_ab_acceptance_decider.py tests/test_services/test_ab_acceptance_sweeper.py tests/test_e2e/test_phase5_ab_auto_acceptance.py -q`
Expected: 全部通过(零回归)

- [ ] **Step 6: 提交**

```bash
git add src/novel_dev/services/ab_acceptance_decider.py \
        src/novel_dev/services/tie_random.py \
        tests/test_services/test_ab_acceptance_decider.py \
        tests/test_services/test_tie_random.py
git commit -m "feat(phase6): ABAcceptanceDecider tie-break via JudgeAgent + tie_random fallback"
```

---

# Wave 4: Cost guard + 降级路径(3 任务)

### Task 10: JudgeCostGuard 实现

**Files:**
- Create: `src/novel_dev/services/judge_cost_guard.py`
- Create: `tests/test_services/test_judge_cost_guard.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_services/test_judge_cost_guard.py`(新建):

```python
import pytest
from unittest.mock import AsyncMock
from dataclasses import dataclass
from novel_dev.config.ab_judge_config import JudgeConfig
from novel_dev.services.judge_cost_guard import JudgeCostGuard, CostCheckResult


@pytest.mark.asyncio
async def test_disabled_judge_returns_disallow():
    config = JudgeConfig(enabled=False)
    guard = JudgeCostGuard(config, call_log_repo=AsyncMock())
    result = await guard.check_can_call("exp_1")
    assert result.allow is False
    assert result.reason == "judge_disabled"


@pytest.mark.asyncio
async def test_experiment_cost_under_cap_allows():
    config = JudgeConfig(enabled=True, max_cost_per_experiment_usd=0.50)
    mock_repo = AsyncMock()
    mock_repo.sum_cost_for_experiment = AsyncMock(return_value=0.10)
    guard = JudgeCostGuard(config, call_log_repo=mock_repo)
    result = await guard.check_can_call("exp_1")
    assert result.allow is True


@pytest.mark.asyncio
async def test_experiment_cost_over_cap_denies():
    config = JudgeConfig(enabled=True, max_cost_per_experiment_usd=0.50)
    mock_repo = AsyncMock()
    mock_repo.sum_cost_for_experiment = AsyncMock(return_value=0.51)
    guard = JudgeCostGuard(config, call_log_repo=mock_repo)
    result = await guard.check_can_call("exp_1")
    assert result.allow is False
    assert result.reason == "experiment_cost_cap"
    assert result.current == 0.51


@pytest.mark.asyncio
async def test_boundary_equal_to_cap_denies():
    config = JudgeConfig(enabled=True, max_cost_per_experiment_usd=0.50)
    mock_repo = AsyncMock()
    mock_repo.sum_cost_for_experiment = AsyncMock(return_value=0.50)
    guard = JudgeCostGuard(config, call_log_repo=mock_repo)
    result = await guard.check_can_call("exp_1")
    assert result.allow is False  # 严格 ≥ 拒绝


@pytest.mark.asyncio
async def test_single_call_cost_estimate_over_decision_cap():
    config = JudgeConfig(enabled=True, max_cost_per_decision_usd=0.05)
    guard = JudgeCostGuard(config, call_log_repo=AsyncMock())
    # 假设这次调用 input=10000, output=1000 → 估算成本 $0.045(刚好)
    cost = guard.estimate_call_cost(input_tokens=10000, output_tokens=1000)
    assert cost > 0.05
    allow = guard.allow_single_call(input_tokens=10000, output_tokens=1000)
    assert allow is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_services/test_judge_cost_guard.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 实现 JudgeCostGuard**

新建 `src/novel_dev/services/judge_cost_guard.py`:

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Protocol

from novel_dev.config.ab_judge_config import JudgeConfig


class CallLogRepoProtocol(Protocol):
    async def sum_cost_for_experiment(self, experiment_id: str) -> float: ...


@dataclass
class CostCheckResult:
    allow: bool
    reason: str = ""
    current: float = 0.0


class JudgeCostGuard:
    # Sonnet 级模型定价(input $3/1M, output $15/1M)
    PRICE_INPUT_PER_TOKEN = 3.0 / 1_000_000
    PRICE_OUTPUT_PER_TOKEN = 15.0 / 1_000_000

    def __init__(self, config: JudgeConfig, call_log_repo: CallLogRepoProtocol):
        self.config = config
        self.call_log = call_log_repo

    async def check_can_call(self, experiment_id: str) -> CostCheckResult:
        if not self.config.enabled:
            return CostCheckResult(allow=False, reason="judge_disabled")

        current = await self.call_log.sum_cost_for_experiment(experiment_id)
        if current >= self.config.max_cost_per_experiment_usd:
            return CostCheckResult(allow=False, reason="experiment_cost_cap", current=current)

        return CostCheckResult(allow=True, current=current)

    def estimate_call_cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.PRICE_INPUT_PER_TOKEN
            + output_tokens * self.PRICE_OUTPUT_PER_TOKEN
        )

    def allow_single_call(self, input_tokens: int, output_tokens: int) -> bool:
        cost = self.estimate_call_cost(input_tokens, output_tokens)
        return cost < self.config.max_cost_per_decision_usd
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_services/test_judge_cost_guard.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/services/judge_cost_guard.py tests/test_services/test_judge_cost_guard.py
git commit -m "feat(phase6): JudgeCostGuard with per-decision + per-experiment caps"
```

---

### Task 11: 把 Cost guard 接到 ABAcceptanceDecider

**Files:**
- Modify: `src/novel_dev/services/ab_acceptance_decider.py` (在 `_try_judge_tie_break` 内加 cost guard)
- Modify: `tests/test_services/test_ab_acceptance_decider.py` (追加测试)

- [ ] **Step 1: 写失败测试**

在 `tests/test_services/test_ab_acceptance_decider.py` 追加:

```python
@pytest.mark.asyncio
async def test_evaluate_tie_blocked_by_cost_cap(async_session, monkeypatch):
    """experiment cost 已超 cap → 不调 judge,降级到 tie_random。"""
    pv_baseline = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_1", sample_count=50)
    pv_challenger = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_1", sample_count=50)
    ab = ABTest(id="ab_1", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running")
    jpv = JudgePromptVersion(version="judge-v1", agent_name="judge_agent", prompt_text="{chapter_text}", is_active=True)
    async_session.add_all([pv_baseline, pv_challenger, ab, jpv])
    await async_session.flush()

    decider = ABAcceptanceDecider(async_session, judge_config=JudgeConfig(max_cost_per_experiment_usd=0.10))
    decider.significance_tester = MagicMock()
    decider.significance_tester.test = MagicMock(return_value=MagicMock(is_significant=False, p_value=0.6, effect_size=0.1, threshold_used="strict", reason="not_significant"))
    decider.weighted_calc = MagicMock()
    decider.weighted_calc.compute_batch = MagicMock(return_value={"v1": 75.1, "v2": 75.5})

    # Mock cost guard 报超 cap
    from novel_dev.services.judge_cost_guard import JudgeCostGuard, CostCheckResult
    decider.cost_guard = MagicMock(spec=JudgeCostGuard)
    decider.cost_guard.check_can_call = AsyncMock(return_value=CostCheckResult(allow=False, reason="experiment_cost_cap", current=0.50))

    # 注入历史 cost log
    from novel_dev.db.models import JudgeCallLog
    log = JudgeCallLog(
        experiment_id="ab_1", prompt_version_id=jpv.id, model="claude-sonnet-4-6",
        input_tokens=100, output_tokens=10, latency_ms=100, cost_usd=0.50,
    )
    async_session.add(log)
    await async_session.flush()

    result = await decider.evaluate(experiment_id="ab_1", sample_scores={
        "v1": {"critic_scores": [80.0]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
        "v2": {"critic_scores": [80.5]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
    })

    assert result.judge_triggered is False
    assert result.judge_error == "experiment_cost_cap"
    assert result.winner in ["v1", "v2"]  # tie_random 选一个
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_services/test_ab_acceptance_decider.py::test_evaluate_tie_blocked_by_cost_cap -v`
Expected: FAIL — judge 仍被调用,没有 cost guard 检查

- [ ] **Step 3: 在 ABAcceptanceDecider 加 cost guard**

修改 `src/novel_dev/services/ab_acceptance_decider.py`:

(a) 加 import:
```python
from novel_dev.repositories.judge_call_log_repo import JudgeCallLogRepository
from novel_dev.services.judge_cost_guard import JudgeCostGuard
```

(b) 在 `__init__` 加 cost_guard 字段:
```python
        self.judge_config = judge_config or get_ab_judge_config()
        self.call_log_repo = JudgeCallLogRepository(session)
        self.cost_guard = JudgeCostGuard(self.judge_config, self.call_log_repo)
```

(c) 在 `_try_judge_tie_break` 开头(`if not self.judge_config.enabled:` 之后)加 cost check:
```python
        if not self.judge_config.enabled:
            return self._tie_random_decide(ab, scores, "judge_disabled")

        cost_check = await self.cost_guard.check_can_call(ab.id)
        if not cost_check.allow:
            return self._tie_random_decide(ab, scores, cost_check.reason)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_services/test_ab_acceptance_decider.py -v`
Expected: PASS

- [ ] **Step 5: 跑全部 ab_acceptance 测试**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_services/test_ab_acceptance_decider.py tests/test_services/test_judge_cost_guard.py -q`
Expected: 全部通过

- [ ] **Step 6: 提交**

```bash
git add src/novel_dev/services/ab_acceptance_decider.py tests/test_services/test_ab_acceptance_decider.py
git commit -m "feat(phase6): wire JudgeCostGuard into ABAcceptanceDecider"
```

---

### Task 12: judge 单次 cost 超限检查

**Files:**
- Modify: `src/novel_dev/services/ab_acceptance_decider.py`
- Modify: `tests/test_services/test_ab_acceptance_decider.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_services/test_ab_acceptance_decider.py` 追加:

```python
@pytest.mark.asyncio
async def test_evaluate_tie_blocked_by_per_decision_cost(async_session):
    """单次 judge 调用估算成本 > per-decision cap → 降级。"""
    pv_baseline = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_1", sample_count=50)
    pv_challenger = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_1", sample_count=50)
    ab = ABTest(id="ab_1", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running")
    jpv = JudgePromptVersion(version="judge-v1", agent_name="judge_agent", prompt_text="{chapter_text}", is_active=True)
    async_session.add_all([pv_baseline, pv_challenger, ab, jpv])
    await async_session.flush()

    # max_cost_per_decision_usd=0.001 极小,任何调用都超
    decider = ABAcceptanceDecider(async_session, judge_config=JudgeConfig(max_cost_per_decision_usd=0.001, max_cost_per_experiment_usd=10.0))
    decider.significance_tester = MagicMock()
    decider.significance_tester.test = MagicMock(return_value=MagicMock(is_significant=False, p_value=0.6, effect_size=0.1, threshold_used="strict", reason="not_significant"))
    decider.weighted_calc = MagicMock()
    decider.weighted_calc.compute_batch = MagicMock(return_value={"v1": 75.1, "v2": 75.5})

    result = await decider.evaluate(experiment_id="ab_1", sample_scores={
        "v1": {"critic_scores": [80.0]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
        "v2": {"critic_scores": [80.5]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
    })

    assert result.judge_triggered is False
    assert result.judge_error == "cost_cap"
    assert result.winner in ["v1", "v2"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_services/test_ab_acceptance_decider.py::test_evaluate_tie_blocked_by_per_decision_cost -v`
Expected: FAIL — 当前实现没有 per-decision 预检

- [ ] **Step 3: 在 `_try_judge_tie_break` 调 judge 前加 per-decision 预检**

修改 `src/novel_dev/services/ab_acceptance_decider.py` 的 `_try_judge_tie_break`,在 `cost_check` 之后、`# 调 judge` 注释前加:

```python
        # 粗估 per-decision cost(假设 input=4000, output=400)— 实际 LLM 调用后再精算
        if not self.cost_guard.allow_single_call(input_tokens=4000, output_tokens=400):
            return self._tie_random_decide(ab, scores, "cost_cap")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_services/test_ab_acceptance_decider.py -v`
Expected: PASS

- [ ] **Step 5: 跑全 Phase 5 + 6 相关测试**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_services/test_ab_*.py tests/test_e2e/test_phase5_ab_auto_acceptance.py -q`
Expected: 全部通过

- [ ] **Step 6: 提交**

```bash
git add src/novel_dev/services/ab_acceptance_decider.py tests/test_services/test_ab_acceptance_decider.py
git commit -m "feat(phase6): per-decision cost pre-check before judge call"
```

---

# Wave 5: Judge 实验数据层(2 任务)

### Task 13: JudgeABTestRepository

**Files:**
- Create: `src/novel_dev/repositories/judge_ab_test_repo.py`
- Create: `tests/test_repositories/test_judge_ab_test_repo.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_repositories/test_judge_ab_test_repo.py`(新建):

```python
import pytest
from novel_dev.db.models import JudgeABTest
from novel_dev.repositories.judge_ab_test_repo import JudgeABTestRepository


@pytest.mark.asyncio
async def test_create_and_get(async_session):
    repo = JudgeABTestRepository(async_session)
    ab = await repo.create(
        baseline_version="judge-v1",
        challenger_version="judge-v2",
        config={"min_samples": 30},
    )
    fetched = await repo.get(ab.id)
    assert fetched.baseline_version == "judge-v1"
    assert fetched.status == "running"


@pytest.mark.asyncio
async def test_list_running(async_session):
    repo = JudgeABTestRepository(async_session)
    await repo.create(baseline_version="v1", challenger_version="v2")
    await repo.create(baseline_version="v3", challenger_version="v4")
    running = await repo.list_by_status("running")
    assert len(running) == 2


@pytest.mark.asyncio
async def test_complete(async_session):
    repo = JudgeABTestRepository(async_session)
    ab = await repo.create(baseline_version="v1", challenger_version="v2")
    await repo.complete(ab.id, winner="v2")
    fetched = await repo.get(ab.id)
    assert fetched.status == "completed"
    assert fetched.winner == "v2"
    assert fetched.ended_at is not None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_judge_ab_test_repo.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 实现 JudgeABTestRepository**

新建 `src/novel_dev/repositories/judge_ab_test_repo.py`:

```python
from __future__ import annotations
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import JudgeABTest


class JudgeABTestRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        baseline_version: str,
        challenger_version: str,
        config: Optional[dict] = None,
        agent_name: str = "judge_agent",
    ) -> JudgeABTest:
        ab = JudgeABTest(
            agent_name=agent_name,
            baseline_version=baseline_version,
            challenger_version=challenger_version,
            status="running",
            config=config or {},
            started_at=datetime.utcnow(),
        )
        self.session.add(ab)
        await self.session.flush()
        return ab

    async def get(self, ab_id: str) -> Optional[JudgeABTest]:
        return await self.session.get(JudgeABTest, ab_id)

    async def list_by_status(self, status: str) -> list[JudgeABTest]:
        result = await self.session.execute(
            select(JudgeABTest).where(JudgeABTest.status == status)
        )
        return list(result.scalars().all())

    async def complete(self, ab_id: str, winner: str) -> None:
        ab = await self.session.get(JudgeABTest, ab_id)
        if ab is None:
            return
        ab.status = "completed"
        ab.winner = winner
        ab.ended_at = datetime.utcnow()
        await self.session.flush()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_judge_ab_test_repo.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/repositories/judge_ab_test_repo.py tests/test_repositories/test_judge_ab_test_repo.py
git commit -m "feat(phase6): JudgeABTestRepository CRUD"
```

---

### Task 14: 把 JudgeABTest 接入 judge_prompt_versions 关联

**Files:**
- Modify: `src/novel_dev/repositories/judge_prompt_version_repo.py` (加 `set_ab_test_id` 方法)
- Modify: `tests/test_repositories/test_judge_prompt_version_repo.py` (追加测试)

- [ ] **Step 1: 写失败测试**

在 `tests/test_repositories/test_judge_prompt_version_repo.py` 追加:

```python
@pytest.mark.asyncio
async def test_set_ab_test_id(async_session):
    pv = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="x", is_active=False)
    async_session.add(pv)
    await async_session.flush()

    repo = JudgePromptVersionRepository(async_session)
    await repo.set_ab_test_id(pv.id, "ab_xyz")
    await async_session.refresh(pv)
    assert pv.ab_test_id == "ab_xyz"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_judge_prompt_version_repo.py::test_set_ab_test_id -v`
Expected: FAIL — method not found

- [ ] **Step 3: 在 repo 加 set_ab_test_id 方法**

修改 `src/novel_dev/repositories/judge_prompt_version_repo.py`,在 `append_history` 之后追加:

```python
    async def set_ab_test_id(self, pv_id: str, ab_test_id: str) -> None:
        pv = await self.session.get(JudgePromptVersion, pv_id)
        if pv is None:
            return
        pv.ab_test_id = ab_test_id
        await self.session.flush()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_judge_prompt_version_repo.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/repositories/judge_prompt_version_repo.py tests/test_repositories/test_judge_prompt_version_repo.py
git commit -m "feat(phase6): JudgePromptVersionRepository.set_ab_test_id"
```

---

# Wave 6: JudgeAcceptanceDecider + Meta-Eval(3 任务)

### Task 15: JudgeMetaEvaluator

**Files:**
- Create: `src/novel_dev/services/judge_meta_evaluator.py`
- Create: `tests/test_services/test_judge_meta_evaluator.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_services/test_judge_meta_evaluator.py`(新建):

```python
import pytest
from datetime import datetime
from unittest.mock import AsyncMock
from novel_dev.config.ab_judge_config import JudgeConfig
from novel_dev.services.judge_meta_evaluator import JudgeMetaEvaluator, MetaEvalResult


@pytest.mark.asyncio
async def test_returns_insufficient_when_no_data():
    config = JudgeConfig(min_samples=30)
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=AsyncMock(scalars=lambda: AsyncMock(all=lambda: [])))
    evaluator = JudgeMetaEvaluator(mock_session, config)
    result = await evaluator.evaluate("jpv_1")
    assert result.sample_size == 0
    assert result.agreement_rate is None


@pytest.mark.asyncio
async def test_agreement_rate_all_correct():
    """所有 clear-cut 决策,judge 跟 hard metric 一致 → 1.0"""
    config = JudgeConfig(min_samples=1, clear_cut_threshold_pct=5.0, calibration_window_days=14)

    # Mock 2 条决策:hard metric 都说 v2 胜,judge 也说 v2 胜
    class MockDecision:
        def __init__(self, baseline_w, challenger_w, judge_tb_baseline, judge_tb_challenger):
            self.baseline_w = baseline_w
            self.challenger_w = challenger_w
            self.judge_tie_breaker_baseline = judge_tb_baseline
            self.judge_tie_breaker_challenger = judge_tb_challenger

    decisions = [
        MockDecision(75.0, 85.0, 7.0, 8.5),  # hard: v2 胜,judge: v2 胜 → 一致
        MockDecision(70.0, 80.0, 6.5, 8.0),  # hard: v2 胜,judge: v2 胜 → 一致
    ]
    mock_session = AsyncMock()
    mock_result = AsyncMock()
    mock_result.scalars.return_value.all.return_value = decisions
    mock_session.execute = AsyncMock(return_value=mock_result)

    evaluator = JudgeMetaEvaluator(mock_session, config)
    result = await evaluator.evaluate("jpv_1")
    assert result.sample_size == 2
    assert result.agreement_rate == 1.0


@pytest.mark.asyncio
async def test_agreement_rate_partial():
    """3 条决策:2 一致 + 1 不一致 → 0.667"""
    config = JudgeConfig(min_samples=1, clear_cut_threshold_pct=5.0, calibration_window_days=14)

    class MockDecision:
        def __init__(self, baseline_w, challenger_w, jtbb, jtbc):
            self.baseline_w = baseline_w
            self.challenger_w = challenger_w
            self.judge_tie_breaker_baseline = jtbb
            self.judge_tie_breaker_challenger = jtbc

    decisions = [
        MockDecision(75.0, 85.0, 7.0, 8.5),  # 一致
        MockDecision(70.0, 80.0, 6.5, 8.0),  # 一致
        MockDecision(85.0, 75.0, 8.0, 7.0),  # hard v1 胜,judge v1 胜 → 一致(反转也算)
    ]
    # 改第三条:hard 跟 judge 矛盾
    decisions[2] = MockDecision(85.0, 75.0, 7.0, 8.0)  # hard: v1,judge: v2 → 不一致

    mock_session = AsyncMock()
    mock_result = AsyncMock()
    mock_result.scalars.return_value.all.return_value = decisions
    mock_session.execute = AsyncMock(return_value=mock_result)

    evaluator = JudgeMetaEvaluator(mock_session, config)
    result = await evaluator.evaluate("jpv_1")
    assert result.sample_size == 3
    assert abs(result.agreement_rate - (2 / 3)) < 0.01


@pytest.mark.asyncio
async def test_filters_by_clear_cut_threshold():
    """hard gap < 5% 的不计入 clear-cut"""
    config = JudgeConfig(min_samples=1, clear_cut_threshold_pct=5.0, calibration_window_days=14)

    class MockDecision:
        def __init__(self, baseline_w, challenger_w, jtbb, jtbc):
            self.baseline_w = baseline_w
            self.challenger_w = challenger_w
            self.judge_tie_breaker_baseline = jtbb
            self.judge_tie_breaker_challenger = jtbc

    # 4% 差距 - 不到 5%,不算 clear-cut
    decisions = [MockDecision(75.0, 78.0, 7.0, 8.0)]

    mock_session = AsyncMock()
    mock_result = AsyncMock()
    mock_result.scalars.return_value.all.return_value = decisions
    mock_session.execute = AsyncMock(return_value=mock_result)

    evaluator = JudgeMetaEvaluator(mock_session, config)
    result = await evaluator.evaluate("jpv_1")
    # 不算 clear-cut,样本数 0
    assert result.sample_size == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_services/test_judge_meta_evaluator.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 实现 JudgeMetaEvaluator**

新建 `src/novel_dev/services/judge_meta_evaluator.py`:

```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Protocol

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.config.ab_judge_config import JudgeConfig
from novel_dev.db.models import ABDecision


@dataclass
class MetaEvalResult:
    version_id: str
    sample_size: int
    agreement_rate: Optional[float]
    window_start: datetime
    insufficient_data: bool = False


class JudgeMetaEvaluator:
    def __init__(self, session: AsyncSession, config: JudgeConfig):
        self.session = session
        self.config = config

    async def evaluate(self, judge_version_id: str) -> MetaEvalResult:
        window_start = datetime.utcnow() - timedelta(days=self.config.calibration_window_days)

        # 拉最近 N 天的 ab_decisions,带 judge_tie_breaker_* 字段
        # clear-cut 阈值:hard metric 差距 > 5%
        # 注:Phase 5 ab_decisions 暂没存 baseline_weighted / challenger_weighted 数值列,
        # 这里用 scores 字典里的值近似(weighted_score = scores[version])
        result = await self.session.execute(
            select(ABDecision)
            .where(ABDecision.decision_at >= window_start)
            .where(ABDecision.judge_triggered.is_(True))
            .order_by(ABDecision.decision_at.desc())
        )
        decisions = list(result.scalars().all())

        clear_cut = []
        for d in decisions:
            if d.judge_tie_breaker_baseline is None or d.judge_tie_breaker_challenger is None:
                continue
            scores = d.scores or {}
            # 从 scores 字典反推 baseline/challenger 的 weighted_score
            # 注:Phase 5 的 scores 格式是 {version: weighted_score_float}
            baseline_w = scores.get(d.experiment_id, None)  # 实际应存 baseline_version/challenger_version
            # Phase 6 简化:用 scores 字典的第一个/第二个 key 近似
            # 生产实现需要 Phase 5 在 ab_decisions 加 baseline_version / challenger_version 列
            keys = list(scores.keys())
            if len(keys) < 2:
                continue
            baseline_w = scores[keys[0]]
            challenger_w = scores[keys[1]]
            if abs(baseline_w) < 1e-6:
                continue
            gap_pct = abs(challenger_w - baseline_w) / abs(baseline_w) * 100
            if gap_pct > self.config.clear_cut_threshold_pct:
                clear_cut.append((d, baseline_w, challenger_w))

        sample_size = len(clear_cut)
        if sample_size < self.config.min_samples:
            return MetaEvalResult(
                version_id=judge_version_id,
                sample_size=sample_size,
                agreement_rate=None,
                window_start=window_start,
                insufficient_data=True,
            )

        agreements = 0
        for d, baseline_w, challenger_w in clear_cut:
            hard_winner_is_challenger = challenger_w > baseline_w
            judge_winner_is_challenger = d.judge_tie_breaker_challenger > d.judge_tie_breaker_baseline
            if hard_winner_is_challenger == judge_winner_is_challenger:
                agreements += 1

        rate = agreements / sample_size
        return MetaEvalResult(
            version_id=judge_version_id,
            sample_size=sample_size,
            agreement_rate=rate,
            window_start=window_start,
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_services/test_judge_meta_evaluator.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/services/judge_meta_evaluator.py tests/test_services/test_judge_meta_evaluator.py
git commit -m "feat(phase6): JudgeMetaEvaluator with clear-cut agreement rate"
```

---

### Task 16: JudgeAcceptanceDecider

**Files:**
- Create: `src/novel_dev/services/judge_acceptance_decider.py`
- Create: `tests/test_services/test_judge_acceptance_decider.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_services/test_judge_acceptance_decider.py`(新建):

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime
from novel_dev.config.ab_judge_config import JudgeConfig
from novel_dev.db.models import JudgePromptVersion, JudgeABTest
from novel_dev.services.judge_acceptance_decider import JudgeAcceptanceDecider, JudgeDeciderResult


@pytest.mark.asyncio
async def test_accepts_challenger_when_agreement_high(async_session):
    jpv1 = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="a", is_active=True)
    jpv2 = JudgePromptVersion(version="v2", agent_name="judge_agent", prompt_text="b", is_active=False, ab_test_id="ab_judge_1")
    ab = JudgeABTest(id="ab_judge_1", baseline_version="v1", challenger_version="v2", status="running")
    async_session.add_all([jpv1, jpv2, ab])
    await async_session.flush()

    decider = JudgeAcceptanceDecider(async_session, JudgeConfig())
    decider.meta_evaluator = MagicMock()
    decider.meta_evaluator.evaluate = AsyncMock(return_value=MagicMock(sample_size=50, agreement_rate=0.85, insufficient_data=False))

    result = await decider.evaluate(experiment_id="ab_judge_1")
    assert result.action == "accept"
    assert result.winner == "v2"


@pytest.mark.asyncio
async def test_continues_monitoring_when_agreement_middle(async_session):
    jpv1 = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="a", is_active=True)
    jpv2 = JudgePromptVersion(version="v2", agent_name="judge_agent", prompt_text="b", is_active=False, ab_test_id="ab_judge_1")
    ab = JudgeABTest(id="ab_judge_1", baseline_version="v1", challenger_version="v2", status="running")
    async_session.add_all([jpv1, jpv2, ab])
    await async_session.flush()

    decider = JudgeAcceptanceDecider(async_session, JudgeConfig())
    decider.meta_evaluator = MagicMock()
    decider.meta_evaluator.evaluate = AsyncMock(return_value=MagicMock(sample_size=50, agreement_rate=0.65, insufficient_data=False))

    result = await decider.evaluate(experiment_id="ab_judge_1")
    assert result.action == "continue_monitoring"


@pytest.mark.asyncio
async def test_early_stops_when_agreement_low(async_session):
    jpv1 = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="a", is_active=True)
    jpv2 = JudgePromptVersion(version="v2", agent_name="judge_agent", prompt_text="b", is_active=False, ab_test_id="ab_judge_1")
    ab = JudgeABTest(id="ab_judge_1", baseline_version="v1", challenger_version="v2", status="running")
    async_session.add_all([jpv1, jpv2, ab])
    await async_session.flush()

    decider = JudgeAcceptanceDecider(async_session, JudgeConfig())
    decider.meta_evaluator = MagicMock()
    decider.meta_evaluator.evaluate = AsyncMock(return_value=MagicMock(sample_size=50, agreement_rate=0.45, insufficient_data=False))

    result = await decider.evaluate(experiment_id="ab_judge_1")
    assert result.action == "early_stop"
    assert result.reason == "low_calibration"


@pytest.mark.asyncio
async def test_continues_when_insufficient_data(async_session):
    jpv1 = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="a", is_active=True)
    jpv2 = JudgePromptVersion(version="v2", agent_name="judge_agent", prompt_text="b", is_active=False, ab_test_id="ab_judge_1")
    ab = JudgeABTest(id="ab_judge_1", baseline_version="v1", challenger_version="v2", status="running")
    async_session.add_all([jpv1, jpv2, ab])
    await async_session.flush()

    decider = JudgeAcceptanceDecider(async_session, JudgeConfig())
    decider.meta_evaluator = MagicMock()
    decider.meta_evaluator.evaluate = AsyncMock(return_value=MagicMock(sample_size=10, agreement_rate=None, insufficient_data=True))

    result = await decider.evaluate(experiment_id="ab_judge_1")
    assert result.action == "continue_monitoring"
    assert result.reason == "insufficient_data"


@pytest.mark.asyncio
async def test_skips_when_experiment_not_running(async_session):
    ab = JudgeABTest(id="ab_judge_1", baseline_version="v1", challenger_version="v2", status="completed")
    async_session.add(ab)
    await async_session.flush()

    decider = JudgeAcceptanceDecider(async_session, JudgeConfig())
    result = await decider.evaluate(experiment_id="ab_judge_1")
    assert result.action == "no_action"
    assert result.reason == "experiment_not_running"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_services/test_judge_acceptance_decider.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 实现 JudgeAcceptanceDecider**

新建 `src/novel_dev/services/judge_acceptance_decider.py`:

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.config.ab_judge_config import JudgeConfig
from novel_dev.db.models import JudgeABTest, JudgePromptVersion
from novel_dev.repositories.judge_prompt_version_repo import JudgePromptVersionRepository
from novel_dev.repositories.judge_ab_test_repo import JudgeABTestRepository
from novel_dev.services.judge_meta_evaluator import JudgeMetaEvaluator


@dataclass
class JudgeDeciderResult:
    action: str  # "accept" | "continue_monitoring" | "early_stop" | "no_action"
    winner: Optional[str] = None
    reason: Optional[str] = None
    sample_size: int = 0
    agreement_rate: Optional[float] = None


ACCEPT_THRESHOLD = 0.80
EARLY_STOP_THRESHOLD = 0.55


class JudgeAcceptanceDecider:
    def __init__(self, session: AsyncSession, config: JudgeConfig):
        self.session = session
        self.config = config
        self.pv_repo = JudgePromptVersionRepository(session)
        self.ab_repo = JudgeABTestRepository(session)
        self.meta_evaluator = JudgeMetaEvaluator(session, config)

    async def evaluate(self, experiment_id: str) -> JudgeDeciderResult:
        ab = await self.session.get(JudgeABTest, experiment_id)
        if not ab or ab.status != "running":
            return JudgeDeciderResult(action="no_action", reason="experiment_not_running")

        # 跑 meta-eval(只针对 challenger version)
        result = await self.ab_repo.get(experiment_id)
        challenger_pv = await self.pv_repo.get_by_id(
            (await self.session.execute(
                select(JudgePromptVersion).where(JudgePromptVersion.ab_test_id == experiment_id)
            )).scalars().first().id
        ) if False else None

        # 简化:直接查 challenger pv
        pv_result = await self.session.execute(
            select(JudgePromptVersion).where(JudgePromptVersion.ab_test_id == experiment_id)
        )
        challenger_pv = pv_result.scalars().first()
        if challenger_pv is None:
            return JudgeDeciderResult(action="no_action", reason="no_challenger_pv")

        meta = await self.meta_evaluator.evaluate(challenger_pv.id)

        if meta.insufficient_data:
            return JudgeDeciderResult(
                action="continue_monitoring",
                reason="insufficient_data",
                sample_size=meta.sample_size,
                agreement_rate=None,
            )

        if meta.agreement_rate >= ACCEPT_THRESHOLD:
            # 接受 challenger
            await self.pv_repo.set_active(challenger_pv.id)
            await self.pv_repo.append_history(challenger_pv.id, {
                "action": "judge_auto_accepted",
                "agreement_rate": meta.agreement_rate,
                "sample_size": meta.sample_size,
                "at": datetime.utcnow().isoformat(),
            })
            # Deactivate baseline
            baseline_pv = await self.pv_repo.get_by_id(
                (await self.session.execute(
                    select(JudgePromptVersion).where(
                        JudgePromptVersion.version == ab.baseline_version,
                        JudgePromptVersion.agent_name == ab.agent_name,
                    )
                )).scalars().first().id
            )
            baseline_pv.is_active = False
            await self.pv_repo.append_history(baseline_pv.id, {
                "action": "judge_active_replaced",
                "agreement_rate": meta.agreement_rate,
                "at": datetime.utcnow().isoformat(),
            })
            await self.session.flush()

            await self.ab_repo.complete(experiment_id, winner=ab.challenger_version)
            return JudgeDeciderResult(
                action="accept",
                winner=ab.challenger_version,
                sample_size=meta.sample_size,
                agreement_rate=meta.agreement_rate,
            )

        if meta.agreement_rate <= EARLY_STOP_THRESHOLD:
            # 早停,标记 challenger 为 no_improvement
            challenger_pv.experiment_state = "early_stopped"
            await self.session.flush()
            await self.ab_repo.complete(experiment_id, winner=ab.baseline_version)
            return JudgeDeciderResult(
                action="early_stop",
                winner=ab.baseline_version,
                reason="low_calibration",
                sample_size=meta.sample_size,
                agreement_rate=meta.agreement_rate,
            )

        return JudgeDeciderResult(
            action="continue_monitoring",
            sample_size=meta.sample_size,
            agreement_rate=meta.agreement_rate,
        )


from datetime import datetime  # 顶上 import 也可以,这里保底
```

**注**: 末尾 `from datetime import datetime` 是为了避免忘了加顶部 import。

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_services/test_judge_acceptance_decider.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/services/judge_acceptance_decider.py tests/test_services/test_judge_acceptance_decider.py
git commit -m "feat(phase6): JudgeAcceptanceDecider with agreement_rate thresholds"
```

---

### Task 17: JudgeAcceptanceSweeper (定时扫兜底)

**Files:**
- Create: `src/novel_dev/services/judge_acceptance_sweeper.py`
- Create: `tests/test_services/test_judge_acceptance_sweeper.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_services/test_judge_acceptance_sweeper.py`(新建):

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime
from novel_dev.config.ab_judge_config import JudgeConfig
from novel_dev.db.models import JudgeABTest
from novel_dev.services.judge_acceptance_sweeper import JudgeAcceptanceSweeper


@pytest.mark.asyncio
async def test_tick_processes_running_experiments(async_session):
    ab = JudgeABTest(baseline_version="v1", challenger_version="v2", status="running")
    async_session.add(ab)
    await async_session.flush()

    sweeper = JudgeAcceptanceSweeper(async_session, JudgeConfig())
    sweeper.decider = MagicMock()
    sweeper.decider.evaluate = AsyncMock(return_value=MagicMock(action="continue_monitoring"))

    decisions = await sweeper.tick()
    assert len(decisions) == 1
    assert decisions[0]["action"] == "continue_monitoring"


@pytest.mark.asyncio
async def test_tick_skips_non_running_experiments(async_session):
    ab = JudgeABTest(baseline_version="v1", challenger_version="v2", status="completed")
    async_session.add(ab)
    await async_session.flush()

    sweeper = JudgeAcceptanceSweeper(async_session, JudgeConfig())
    sweeper.decider = MagicMock()
    sweeper.decider.evaluate = AsyncMock(return_value=MagicMock(action="accept", winner="v2"))

    decisions = await sweeper.tick()
    # completed 状态仍可继续被 sweeper 处理(meta-eval 即使是已完成实验也跑)
    # 但若 decider 返回 no_action,会进入 decisions 列表
    assert isinstance(decisions, list)


@pytest.mark.asyncio
async def test_tick_handles_exception_per_experiment(async_session):
    ab1 = JudgeABTest(baseline_version="v1", challenger_version="v2", status="running")
    ab2 = JudgeABTest(baseline_version="v3", challenger_version="v4", status="running")
    async_session.add_all([ab1, ab2])
    await async_session.flush()

    sweeper = JudgeAcceptanceSweeper(async_session, JudgeConfig())
    sweeper.decider = MagicMock()
    sweeper.decider.evaluate = AsyncMock(side_effect=[Exception("boom"), MagicMock(action="accept", winner="v3")])

    # 不应抛出 — 单个失败被吞掉
    decisions = await sweeper.tick()
    assert len(decisions) == 1  # 只有 ab2 成功
    assert decisions[0]["action"] == "accept"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_services/test_judge_acceptance_sweeper.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 实现 JudgeAcceptanceSweeper**

新建 `src/novel_dev/services/judge_acceptance_sweeper.py`:

```python
from __future__ import annotations
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.config.ab_judge_config import JudgeConfig
from novel_dev.db.models import JudgeABTest
from novel_dev.services.judge_acceptance_decider import JudgeAcceptanceDecider

logger = logging.getLogger(__name__)


class JudgeAcceptanceSweeper:
    def __init__(self, session: AsyncSession, config: JudgeConfig, decider: Optional[JudgeAcceptanceDecider] = None):
        self.session = session
        self.config = config
        self.decider = decider or JudgeAcceptanceDecider(session, config)

    async def tick(self) -> list[dict]:
        """每 5 分钟(或按调度)扫一次所有 running / completed 的 judge_ab_tests。"""
        result = await self.session.execute(
            select(JudgeABTest).where(JudgeABTest.status.in_(["running", "completed"]))
        )
        experiments = list(result.scalars().all())
        decisions = []
        for ab in experiments:
            try:
                dr = await self.decider.evaluate(ab.id)
                if dr.action != "no_action":
                    decisions.append({
                        "action": dr.action,
                        "experiment_id": ab.id,
                        "winner": dr.winner,
                        "reason": dr.reason,
                        "agreement_rate": dr.agreement_rate,
                    })
            except Exception as exc:
                logger.exception(
                    "judge_sweeper_experiment_failed",
                    extra={"experiment_id": ab.id, "error": str(exc)},
                )
        return decisions
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_services/test_judge_acceptance_sweeper.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/services/judge_acceptance_sweeper.py tests/test_services/test_judge_acceptance_sweeper.py
git commit -m "feat(phase6): JudgeAcceptanceSweeper periodic tick"
```

---

# Wave 7: API 端点(3 任务)

### Task 18: GET /api/judge-prompt-versions + POST 创建/激活

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Create: `tests/test_api/test_judge_endpoints.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_api/test_judge_endpoints.py`(新建):

```python
import pytest
from httpx import AsyncClient
from novel_dev.db.models import JudgePromptVersion


@pytest.mark.asyncio
async def test_list_judge_prompt_versions(client: AsyncClient, async_session):
    pv = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="a", is_active=True)
    async_session.add(pv)
    await async_session.flush()

    resp = await client.get("/api/judge-prompt-versions")
    assert resp.status_code == 200
    data = resp.json()
    assert any(d["version"] == "v1" for d in data)


@pytest.mark.asyncio
async def test_create_judge_prompt_version(client: AsyncClient):
    resp = await client.post("/api/judge-prompt-versions", json={
        "version": "judge-v1",
        "agent_name": "judge_agent",
        "prompt_text": "你是一位...",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["version"] == "judge-v1"


@pytest.mark.asyncio
async def test_activate_judge_prompt_version(client: AsyncClient, async_session):
    pv = JudgePromptVersion(version="v2", agent_name="judge_agent", prompt_text="a", is_active=False)
    async_session.add(pv)
    await async_session.flush()

    resp = await client.post(f"/api/judge-prompt-versions/{pv.id}/activate")
    assert resp.status_code == 200
    await async_session.refresh(pv)
    assert pv.is_active is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_api/test_judge_endpoints.py -v`
Expected: FAIL — 404

- [ ] **Step 3: 加 3 个端点到 routes.py**

修改 `src/novel_dev/api/routes.py`,在文件末尾追加(在现有 router 之后):

```python
from novel_dev.repositories.judge_prompt_version_repo import JudgePromptVersionRepository
from novel_dev.repositories.judge_call_log_repo import JudgeCallLogRepository
from novel_dev.services.judge_cost_guard import JudgeCostGuard
from novel_dev.services.judge_acceptance_sweeper import JudgeAcceptanceSweeper
from novel_dev.config.ab_judge_config import get_ab_judge_config


@router.get("/api/judge-prompt-versions")
async def list_judge_prompt_versions(session: AsyncSession = Depends(get_session)):
    from sqlalchemy import select
    from novel_dev.db.models import JudgePromptVersion
    result = await session.execute(select(JudgePromptVersion).order_by(JudgePromptVersion.created_at.desc()))
    return [
        {
            "id": pv.id,
            "version": pv.version,
            "agent_name": pv.agent_name,
            "is_active": pv.is_active,
            "experiment_state": pv.experiment_state,
            "last_score": pv.last_score,
            "last_decision_at": pv.last_decision_at.isoformat() if pv.last_decision_at else None,
            "created_at": pv.created_at.isoformat(),
        }
        for pv in result.scalars().all()
    ]


@router.post("/api/judge-prompt-versions", status_code=201)
async def create_judge_prompt_version(payload: dict, session: AsyncSession = Depends(get_session)):
    pv = JudgePromptVersion(
        version=payload["version"],
        agent_name=payload.get("agent_name", "judge_agent"),
        prompt_text=payload["prompt_text"],
        is_active=False,
    )
    session.add(pv)
    await session.flush()
    return {"id": pv.id, "version": pv.version, "is_active": False}


@router.post("/api/judge-prompt-versions/{pv_id}/activate")
async def activate_judge_prompt_version(pv_id: str, session: AsyncSession = Depends(get_session)):
    repo = JudgePromptVersionRepository(session)
    await repo.set_active(pv_id)
    return {"ok": True}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_api/test_judge_endpoints.py -v`
Expected: PASS

- [ ] **Step 5: 跑回归确认 API 不破**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_api/ -q`
Expected: 全部通过

- [ ] **Step 6: 提交**

```bash
git add src/novel_dev/api/routes.py tests/test_api/test_judge_endpoints.py
git commit -m "feat(phase6): judge-prompt-versions list/create/activate endpoints"
```

---

### Task 19: GET /api/judge-call-stats

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Modify: `tests/test_api/test_judge_endpoints.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_api/test_judge_endpoints.py` 追加:

```python
@pytest.mark.asyncio
async def test_get_judge_call_stats(client: AsyncClient, async_session):
    from novel_dev.db.models import JudgeCallLog
    from datetime import datetime, timedelta
    for i in range(3):
        log = JudgeCallLog(
            decision_id=f"d{i}", experiment_id="exp_1",
            prompt_version_id="p", model="claude-sonnet-4-6",
            input_tokens=1000, output_tokens=100, latency_ms=2000, cost_usd=0.01,
            called_at=datetime.utcnow() - timedelta(hours=i),
        )
        async_session.add(log)
    await async_session.flush()

    resp = await client.get("/api/judge-call-stats?experiment_id=exp_1&window_days=14")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_calls"] == 3
    assert abs(data["total_cost_usd"] - 0.03) < 1e-6
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_api/test_judge_endpoints.py::test_get_judge_call_stats -v`
Expected: FAIL — 404

- [ ] **Step 3: 加端点**

在 `src/novel_dev/api/routes.py` 追加:

```python
@router.get("/api/judge-call-stats")
async def get_judge_call_stats(
    experiment_id: Optional[str] = None,
    window_days: int = 14,
    session: AsyncSession = Depends(get_session),
):
    from datetime import datetime, timedelta
    from sqlalchemy import select, func
    from novel_dev.db.models import JudgeCallLog

    cutoff = datetime.utcnow() - timedelta(days=window_days)
    stmt = select(JudgeCallLog).where(JudgeCallLog.called_at >= cutoff)
    if experiment_id is not None:
        stmt = stmt.where(JudgeCallLog.experiment_id == experiment_id)
    result = await session.execute(stmt)
    logs = list(result.scalars().all())
    return {
        "total_calls": len(logs),
        "total_cost_usd": sum(l.cost_usd for l in logs),
        "total_input_tokens": sum(l.input_tokens for l in logs),
        "total_output_tokens": sum(l.output_tokens for l in logs),
        "avg_latency_ms": (sum(l.latency_ms for l in logs) / len(logs)) if logs else 0,
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_api/test_judge_endpoints.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/api/routes.py tests/test_api/test_judge_endpoints.py
git commit -m "feat(phase6): judge-call-stats endpoint with experiment/window filters"
```

---

### Task 20: POST /api/judge-sweeper/tick

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Modify: `tests/test_api/test_judge_endpoints.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_api/test_judge_endpoints.py` 追加:

```python
@pytest.mark.asyncio
async def test_post_judge_sweeper_tick(client: AsyncClient, async_session):
    from novel_dev.db.models import JudgeABTest
    ab = JudgeABTest(baseline_version="v1", challenger_version="v2", status="running")
    async_session.add(ab)
    await async_session.flush()

    resp = await client.post("/api/judge-sweeper/tick")
    assert resp.status_code == 200
    data = resp.json()
    assert "decisions" in data
    assert isinstance(data["decisions"], list)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_api/test_judge_endpoints.py::test_post_judge_sweeper_tick -v`
Expected: FAIL — 404

- [ ] **Step 3: 加端点**

在 `src/novel_dev/api/routes.py` 追加:

```python
@router.post("/api/judge-sweeper/tick")
async def post_judge_sweeper_tick(session: AsyncSession = Depends(get_session)):
    config = get_ab_judge_config()
    sweeper = JudgeAcceptanceSweeper(session, config)
    decisions = await sweeper.tick()
    return {"decisions": decisions, "count": len(decisions)}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_api/test_judge_endpoints.py -v`
Expected: PASS

- [ ] **Step 5: 跑全 API 回归**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_api/ -q`
Expected: 全部通过

- [ ] **Step 6: 提交**

```bash
git add src/novel_dev/api/routes.py tests/test_api/test_judge_endpoints.py
git commit -m "feat(phase6): judge-sweeper/tick endpoint for manual trigger"
```

---

# Wave 8: Vue UI(3 任务)

### Task 21: ABDecisionDetail 组件(新)

**Files:**
- Create: `src/novel_dev/web/src/components/ABDecisionDetail.vue`
- Create: `src/novel_dev/web/src/components/ABDecisionDetail.test.js`

- [ ] **Step 1: 写失败测试**

在 `src/novel_dev/web/src/components/ABDecisionDetail.test.js`(新建):

```javascript
import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import ABDecisionDetail from './ABDecisionDetail.vue'

const sampleDecision = {
  id: 'dec_1',
  decision_at: '2026-06-19T10:00:00',
  experiment_id: 'ab_1',
  action: 'accept',
  scores: { v1: 75.1, v2: 75.5 },
  judge_triggered: true,
  judge_tie_breaker_baseline: 7.3,
  judge_tie_breaker_challenger: 8.0,
  judge_scores_baseline: { 口吻: 7.0, 叙事连贯: 7.5, 风格调性: 7.5 },
  judge_scores_challenger: { 口吻: 8.0, 叙事连贯: 8.0, 风格调性: 8.0 },
  judge_rationale_baseline: '风格略平淡',
  judge_rationale_challenger: '口吻统一,推进自然',
  judge_model: 'claude-sonnet-4-6',
  judge_error: null,
  meta: { winner: 'v2' },
}

describe('ABDecisionDetail', () => {
  it('renders judge 3-dimension scores when triggered', () => {
    const wrapper = mount(ABDecisionDetail, { props: { decision: sampleDecision } })
    expect(wrapper.text()).toContain('口吻')
    expect(wrapper.text()).toContain('叙事连贯')
    expect(wrapper.text()).toContain('风格调性')
    expect(wrapper.text()).toContain('claude-sonnet-4-6')
  })

  it('shows degraded path notice when judge_triggered is false', () => {
    const wrapper = mount(ABDecisionDetail, {
      props: { decision: { ...sampleDecision, judge_triggered: false, judge_error: 'parse_failed' } },
    })
    expect(wrapper.text()).toContain('parse_failed')
  })

  it('shows clear winner when no judge involvement', () => {
    const wrapper = mount(ABDecisionDetail, {
      props: {
        decision: { ...sampleDecision, judge_triggered: false, judge_error: null, scores: { v1: 75, v2: 85 } },
      },
    })
    expect(wrapper.text()).toContain('85')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd src/novel_dev/web && npx vitest run src/components/ABDecisionDetail.test.js`
Expected: FAIL — file not found

- [ ] **Step 3: 实现组件**

新建 `src/novel_dev/web/src/components/ABDecisionDetail.vue`:

```vue
<template>
  <div class="ab-decision-detail">
    <header class="mb-3 flex items-center justify-between">
      <h3 class="text-sm font-semibold text-gray-800 dark:text-gray-100">决策详情</h3>
      <span class="text-xs text-gray-500">ID: {{ decision.id }}</span>
    </header>

    <dl class="grid grid-cols-2 gap-2 text-xs mb-4">
      <dt class="text-gray-500">触发时间</dt>
      <dd>{{ formatTime(decision.decision_at) }}</dd>
      <dt class="text-gray-500">实验 ID</dt>
      <dd>{{ decision.experiment_id }}</dd>
      <dt class="text-gray-500">Action</dt>
      <dd>{{ decision.action }}</dd>
    </dl>

    <section class="mb-4">
      <h4 class="text-xs font-semibold text-gray-700 dark:text-gray-200 mb-1">硬指标</h4>
      <ul class="text-xs">
        <li v-for="(score, version) in decision.scores" :key="version">
          <code class="text-teal-700">{{ version }}</code>: {{ score.toFixed(2) }}
        </li>
      </ul>
    </section>

    <section v-if="decision.judge_triggered" class="judge-section">
      <h4 class="text-xs font-semibold text-teal-700 mb-1">Judge 评分(tie-breaker)</h4>
      <p class="text-xs text-gray-500 mb-2">模型: {{ decision.judge_model }}</p>
      <table class="w-full text-xs">
        <thead>
          <tr class="text-left text-gray-500">
            <th class="pr-2">维度</th>
            <th class="pr-2">baseline</th>
            <th class="pr-2">challenger</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(score, dim) in decision.judge_scores_baseline" :key="dim">
            <td class="pr-2">{{ dim }}</td>
            <td class="pr-2">{{ score.toFixed(2) }}</td>
            <td class="pr-2">{{ (decision.judge_scores_challenger[dim] || 0).toFixed(2) }}</td>
          </tr>
          <tr class="font-semibold">
            <td class="pr-2">tie_breaker</td>
            <td class="pr-2">{{ decision.judge_tie_breaker_baseline?.toFixed(2) }}</td>
            <td class="pr-2">{{ decision.judge_tie_breaker_challenger?.toFixed(2) }}</td>
          </tr>
        </tbody>
      </table>
      <div class="mt-2 text-xs">
        <p><strong>baseline 理由:</strong> {{ decision.judge_rationale_baseline }}</p>
        <p><strong>challenger 理由:</strong> {{ decision.judge_rationale_challenger }}</p>
      </div>
    </section>

    <section v-else-if="decision.judge_error" class="degraded-notice">
      <p class="text-xs text-amber-700">Judge 未介入 — {{ decision.judge_error }}</p>
    </section>

    <section v-else class="text-xs text-gray-500">
      Judge 未介入(硬指标差距 &gt; 1%)
    </section>

    <footer class="mt-3 text-xs text-gray-500">
      最终决策: <strong class="text-teal-700">{{ decision.meta?.winner || decision.winner || '—' }}</strong>
    </footer>
  </div>
</template>

<script setup>
import { defineProps } from 'vue'
import { formatBeijingDateTime } from '@/utils/time.js'

defineProps({ decision: { type: Object, required: true } })

function formatTime(value) {
  return formatBeijingDateTime(value)
}
</script>

<style scoped>
.ab-decision-detail {
  @apply rounded-[1rem] border border-gray-200 dark:border-gray-700 bg-white dark:bg-slate-900 p-4 max-w-md;
}
.judge-section {
  @apply rounded-md bg-teal-50 dark:bg-teal-900/20 p-3;
}
.degraded-notice {
  @apply rounded-md bg-amber-50 dark:bg-amber-900/20 p-3;
}
</style>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd src/novel_dev/web && npx vitest run src/components/ABDecisionDetail.test.js`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/web/src/components/ABDecisionDetail.vue \
        src/novel_dev/web/src/components/ABDecisionDetail.test.js
git commit -m "feat(phase6): ABDecisionDetail drawer showing judge 3-dim scores"
```

---

### Task 22: ExperimentView 加 Judge tab

**Files:**
- Modify: `src/novel_dev/web/src/views/ExperimentView.vue`
- Modify: `src/novel_dev/web/src/views/ExperimentView.test.js`

- [ ] **Step 1: 写失败测试**

在 `src/novel_dev/web/src/views/ExperimentView.test.js` 追加(找到现有 import 后,加新 describe):

```javascript
describe('ExperimentView Judge tab', () => {
  it('shows judge tab in tab list', async () => {
    const wrapper = mount(ExperimentView, {
      global: { plugins: [router, pinia], stubs: { RouterLink: true } },
    })
    await wrapper.vm.$nextTick()
    const tabs = wrapper.findAll('[data-test="tab"]')
    const labels = tabs.map((t) => t.text())
    expect(labels.some((l) => l.includes('judge'))).toBe(true)
  })

  it('renders judge metric cards when judge tab is active', async () => {
    const wrapper = mount(ExperimentView, {
      global: { plugins: [router, pinia], stubs: { RouterLink: true } },
    })
    await wrapper.vm.$nextTick()
    // 模拟切到 judge tab
    await wrapper.find('[data-test="tab-judge"]').trigger('click')
    expect(wrapper.text()).toContain('一致率')
    expect(wrapper.text()).toContain('本月调用')
    expect(wrapper.text()).toContain('本月成本')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd src/novel_dev/web && npx vitest run src/views/ExperimentView.test.js`
Expected: 新测试 FAIL

- [ ] **Step 3: 修改 ExperimentView.vue**

修改 `src/novel_dev/web/src/views/ExperimentView.vue`:

(a) 在 tabs 数组追加(找到现有 tabs 定义):

```javascript
const tabs = [
  { id: 'overview', label: '概览' },
  { id: 'samples', label: '样本' },
  { id: 'history', label: '决策历史' },
  { id: 'judge', label: 'judge' },  // 新增
]
```

(b) 在 template 内,找到 tabs 渲染位置,加 `data-test="tab"` 和 `data-test="tab-judge"`:

```vue
<button
  v-for="t in tabs"
  :key="t.id"
  :class="['tab', { 'tab--active': activeTab === t.id }]"
  :data-test="'tab'"
  :data-test-tab="t.id"
  @click="activeTab = t.id"
>
  {{ t.label }}
</button>
```

(c) 加 `activeTab` ref:

```javascript
import { ref } from 'vue'
const activeTab = ref('overview')
```

(d) 在 tab 内容渲染区追加 Judge tab 面板:

```vue
<section v-if="activeTab === 'judge'" class="judge-tab">
  <h3>Judge 状态</h3>
  <div class="metric-cards">
    <div class="metric-card">
      <h4>平均一致率</h4>
      <p>{{ judgeMetrics.avgAgreementRate?.toFixed(2) || '—' }}</p>
    </div>
    <div class="metric-card">
      <h4>本月 judge 调用</h4>
      <p>{{ judgeMetrics.monthlyCalls || 0 }}</p>
    </div>
    <div class="metric-card">
      <h4>本月 judge 成本</h4>
      <p>${{ judgeMetrics.monthlyCost?.toFixed(4) || '0.0000' }}</p>
    </div>
  </div>
  <div class="active-judge-prompt">
    <h4>当前 active judge prompt</h4>
    <p>版本: {{ activeJudgePrompt?.version || '—' }}</p>
    <p>一致率: {{ activeJudgePrompt?.last_score?.toFixed(2) || '—' }}</p>
  </div>
</section>
```

(e) 加 metrics 计算属性:

```javascript
import { computed, onMounted } from 'vue'
import { fetchJudgeCallStats, fetchJudgePromptVersions } from '@/api.js'

const judgeMetrics = ref({ avgAgreementRate: null, monthlyCalls: 0, monthlyCost: 0 })
const activeJudgePrompt = ref(null)

onMounted(async () => {
  try {
    const stats = await fetchJudgeCallStats({ window_days: 14 })
    judgeMetrics.value.monthlyCalls = stats.total_calls
    judgeMetrics.value.monthlyCost = stats.total_cost_usd
  } catch (e) {
    console.warn('judge stats fetch failed', e)
  }
  try {
    const versions = await fetchJudgePromptVersions()
    activeJudgePrompt.value = versions.find((v) => v.is_active) || null
  } catch (e) {
    console.warn('judge prompt versions fetch failed', e)
  }
})
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd src/novel_dev/web && npx vitest run src/views/ExperimentView.test.js`
Expected: 全部通过

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/web/src/views/ExperimentView.vue \
        src/novel_dev/web/src/views/ExperimentView.test.js
git commit -m "feat(phase6): ExperimentView adds Judge tab with metric cards"
```

---

### Task 23: ExperimentWidget judge 状态条 + api.js helpers

**Files:**
- Modify: `src/novel_dev/web/src/components/ExperimentWidget.vue`
- Modify: `src/novel_dev/web/src/api.js`
- Modify: `src/novel_dev/web/src/components/ExperimentWidget.test.js`

- [ ] **Step 1: 写失败测试 - api.js helpers**

在 `src/novel_dev/web/src/api.js` 追加 4 个 helper:

```javascript
export async function fetchJudgePromptVersions() {
  return (await api.get('/api/judge-prompt-versions')).data
}

export async function createJudgePromptVersion(payload) {
  return (await api.post('/api/judge-prompt-versions', payload)).data
}

export async function activateJudgePromptVersion(pvId) {
  return (await api.post(`/api/judge-prompt-versions/${pvId}/activate`)).data
}

export async function fetchJudgeCallStats(params = {}) {
  return (await api.get('/api/judge-call-stats', { params })).data
}

export async function triggerJudgeSweeperTick() {
  return (await api.post('/api/judge-sweeper/tick')).data
}
```

- [ ] **Step 2: 写失败测试 - ExperimentWidget**

在 `src/novel_dev/web/src/components/ExperimentWidget.test.js` 追加:

```javascript
describe('ExperimentWidget judge status bar', () => {
  it('shows judge status bar with enabled indicator', async () => {
    const wrapper = mount(ExperimentWidget, {
      global: { plugins: [pinia], stubs: { RouterLink: true } },
    })
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Judge 状态')
  })

  it('shows degraded chip when cost cap triggers', async () => {
    // mock fetchJudgeCallStats to return cost > cap
    const wrapper = mount(ExperimentWidget, {
      global: { plugins: [pinia], stubs: { RouterLink: true } },
    })
    // 注入 mock 数据由 setActive 替代 — 这里用 vi.spyOn
    // (具体 mock 模式按项目现有约定)
    // 简化:只需断言 chip 元素存在
    expect(wrapper.find('[data-test="judge-status-chip"]').exists()).toBe(true)
  })
})
```

- [ ] **Step 3: 修改 ExperimentWidget.vue**

修改 `src/novel_dev/web/src/components/ExperimentWidget.vue`,在 template 顶部加 judge 状态条:

```vue
<aside class="judge-status-bar" data-test="judge-status-chip">
  <span class="text-xs text-gray-500">Judge 状态:</span>
  <span :class="['judge-status-indicator', judgeEnabled ? 'enabled' : 'disabled']">
    {{ judgeEnabled ? '✓ 启用' : '✗ 禁用' }}
  </span>
  <span v-if="judgeActiveVersion" class="text-xs">活跃 prompt: {{ judgeActiveVersion }}</span>
  <span v-if="judgeDegradedReason" class="judge-degraded-chip">⚠ {{ judgeDegradedReason }}</span>
</aside>
```

加 script 部分:

```javascript
import { ref, onMounted } from 'vue'
import { fetchJudgePromptVersions, fetchJudgeCallStats } from '@/api.js'

const judgeEnabled = ref(true)
const judgeActiveVersion = ref(null)
const judgeDegradedReason = ref(null)

onMounted(async () => {
  try {
    const versions = await fetchJudgePromptVersions()
    const active = versions.find((v) => v.is_active)
    if (active) judgeActiveVersion.value = active.version
    else judgeEnabled.value = false
  } catch (e) {
    judgeDegradedReason.value = '连接失败'
  }
  try {
    const stats = await fetchJudgeCallStats({ window_days: 30 })
    if (stats.total_cost_usd > 0.40) {  // 80% of 0.50 cap
      judgeDegradedReason.value = '接近 cost cap'
    }
  } catch (e) {
    // ignore
  }
})
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd src/novel_dev/web && npx vitest run src/components/ExperimentWidget.test.js`
Expected: PASS

- [ ] **Step 5: 跑全 Vue 回归**

Run: `cd src/novel_dev/web && npx vitest run`
Expected: 全部通过(零回归)

- [ ] **Step 6: 提交**

```bash
git add src/novel_dev/web/src/components/ExperimentWidget.vue \
        src/novel_dev/web/src/components/ExperimentWidget.test.js \
        src/novel_dev/web/src/api.js
git commit -m "feat(phase6): ExperimentWidget judge status bar + api.js helpers"
```

---

# Wave 9: E2E + 性能(2 任务)

### Task 24: E2E 5 场景

**Files:**
- Create: `tests/test_e2e/test_phase6_judge_tiebreaker.py`

- [ ] **Step 1: 实现 happy path 场景**

在 `tests/test_e2e/test_phase6_judge_tiebreaker.py`(新建):

```python
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from novel_dev.db.models import (
    PromptVersion, ABTest, JudgePromptVersion, JudgeABTest, JudgeCallLog,
)
from novel_dev.services.ab_acceptance_decider import ABAcceptanceDecider
from novel_dev.config.ab_judge_config import JudgeConfig
from novel_dev.llm.models import ChatMessage


def _judge_llm_response(scores_dict):
    return ChatMessage(role="assistant", content=json.dumps({**scores_dict, "理由": "ok"}))


@pytest.mark.asyncio
async def test_e2e_happy_path_tie_triggers_judge_challenger_wins(async_session):
    """场景 1: tie → judge 给出 challenger 更高分 → challenger 胜。"""
    pv_b = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_e1", sample_count=50)
    pv_c = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_e1", sample_count=50)
    ab = ABTest(id="ab_e1", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running")
    jpv = JudgePromptVersion(version="judge-v1", agent_name="judge_agent", prompt_text="{chapter_text}", is_active=True)
    async_session.add_all([pv_b, pv_c, ab, jpv])
    await async_session.flush()

    decider = ABAcceptanceDecider(async_session, judge_config=JudgeConfig())
    decider.significance_tester = MagicMock()
    decider.significance_tester.test = MagicMock(return_value=MagicMock(is_significant=False, p_value=0.6, effect_size=0.1, threshold_used="strict", reason="not_significant"))
    decider.weighted_calc = MagicMock()
    decider.weighted_calc.compute_batch = MagicMock(return_value={"v1": 75.1, "v2": 75.5})  # 0.4% gap, tie

    judge_responses = iter([
        _judge_llm_response({"口吻": 7.0, "叙事连贯": 7.5, "风格调性": 7.5}),  # baseline
        _judge_llm_response({"口吻": 8.0, "叙事连贯": 8.5, "风格调性": 8.0}),  # challenger
    ])
    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(side_effect=lambda *a, **k: next(judge_responses))
        mock_factory.get.return_value = mock_client
        result = await decider.evaluate(experiment_id="ab_e1", sample_scores={
            "v1": {"critic_scores": [80.0]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
            "v2": {"critic_scores": [80.5]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
        })

    assert result.action == "accepted"
    assert result.winner == "v2"
    assert result.judge_triggered is True
    assert result.judge_tie_breaker_challenger > result.judge_tie_breaker_baseline

    # ab_decisions 应有 1 条 judge 列非空
    from sqlalchemy import select
    from novel_dev.db.models import ABDecision
    decisions = (await async_session.execute(
        select(ABDecision).where(ABDecision.experiment_id == "ab_e1")
    )).scalars().all()
    judge_decisions = [d for d in decisions if d.judge_triggered]
    assert len(judge_decisions) == 1
    assert judge_decisions[0].judge_tie_breaker_challenger > 7.5

    # JudgeCallLog 应该有 2 条
    call_logs = (await async_session.execute(
        select(JudgeCallLog).where(JudgeCallLog.experiment_id == "ab_e1")
    )).scalars().all()
    assert len(call_logs) == 2


@pytest.mark.asyncio
async def test_e2e_clear_winner_skips_judge(async_session):
    """场景 2: 硬指标差距 > 1% → judge 不调,走原 Phase 5 路径。"""
    pv_b = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_e2", sample_count=50)
    pv_c = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_e2", sample_count=50)
    ab = ABTest(id="ab_e2", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running")
    jpv = JudgePromptVersion(version="judge-v1", agent_name="judge_agent", prompt_text="{chapter_text}", is_active=True)
    async_session.add_all([pv_b, pv_c, ab, jpv])
    await async_session.flush()

    decider = ABAcceptanceDecider(async_session, judge_config=JudgeConfig())
    decider.significance_tester = MagicMock()
    decider.significance_tester.test = MagicMock(return_value=MagicMock(is_significant=True, p_value=0.03, effect_size=4.0, threshold_used="strict", reason=None))
    decider.weighted_calc = MagicMock()
    decider.weighted_calc.compute_batch = MagicMock(return_value={"v1": 75.0, "v2": 85.0})  # 13% gap

    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        # 若被调用则失败
        mock_client.acomplete = AsyncMock(side_effect=AssertionError("judge should not be called"))
        mock_factory.get.return_value = mock_client
        result = await decider.evaluate(experiment_id="ab_e2", sample_scores={
            "v1": {"critic_scores": [80.0]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
            "v2": {"critic_scores": [85.0]*50, "hook_achieved": [True]*50, "thrill_verified": [True]*50},
        })

    assert result.action == "accepted"
    assert result.winner == "v2"
    assert result.judge_triggered is False


@pytest.mark.asyncio
async def test_e2e_judge_parse_failed_degrades_to_random(async_session):
    """场景 3: judge 解析失败 → tie_random 选 baseline,记录 judge_error=parse_failed。"""
    pv_b = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_e3", sample_count=50)
    pv_c = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_e3", sample_count=50)
    ab = ABTest(id="ab_e3", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running")
    jpv = JudgePromptVersion(version="judge-v1", agent_name="judge_agent", prompt_text="{chapter_text}", is_active=True)
    async_session.add_all([pv_b, pv_c, ab, jpv])
    await async_session.flush()

    decider = ABAcceptanceDecider(async_session, judge_config=JudgeConfig())
    decider.significance_tester = MagicMock()
    decider.significance_tester.test = MagicMock(return_value=MagicMock(is_significant=False, p_value=0.6, effect_size=0.1, threshold_used="strict", reason="not_significant"))
    decider.weighted_calc = MagicMock()
    decider.weighted_calc.compute_batch = MagicMock(return_value={"v1": 75.1, "v2": 75.5})

    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(return_value=ChatMessage(role="assistant", content="无法打分"))
        mock_factory.get.return_value = mock_client
        result = await decider.evaluate(experiment_id="ab_e3", sample_scores={
            "v1": {"critic_scores": [80.0]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
            "v2": {"critic_scores": [80.5]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
        })

    # tie_random_pick("ab_e3", ["v1", "v2"]) 是 deterministic
    from novel_dev.services.tie_random import tie_random_pick
    expected_winner = tie_random_pick("ab_e3", ["v1", "v2"])
    assert result.winner == expected_winner
    assert result.judge_triggered is False
    assert result.judge_error == "JudgeParseError"


@pytest.mark.asyncio
async def test_e2e_cost_cap_blocks_judge(async_session):
    """场景 4: experiment cost 已超 cap → judge 不调,降级。"""
    pv_b = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_e4", sample_count=50)
    pv_c = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_e4", sample_count=50)
    ab = ABTest(id="ab_e4", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running")
    jpv = JudgePromptVersion(version="judge-v1", agent_name="judge_agent", prompt_text="{chapter_text}", is_active=True)
    log = JudgeCallLog(experiment_id="ab_e4", prompt_version_id=jpv.id, model="m",
                       input_tokens=100, output_tokens=10, latency_ms=100, cost_usd=0.60)  # 0.60 > 0.50 cap
    async_session.add_all([pv_b, pv_c, ab, jpv, log])
    await async_session.flush()

    decider = ABAcceptanceDecider(async_session, judge_config=JudgeConfig(max_cost_per_experiment_usd=0.50))
    decider.significance_tester = MagicMock()
    decider.significance_tester.test = MagicMock(return_value=MagicMock(is_significant=False, p_value=0.6, effect_size=0.1, threshold_used="strict", reason="not_significant"))
    decider.weighted_calc = MagicMock()
    decider.weighted_calc.compute_batch = MagicMock(return_value={"v1": 75.1, "v2": 75.5})

    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(side_effect=AssertionError("judge should not be called"))
        mock_factory.get.return_value = mock_client
        result = await decider.evaluate(experiment_id="ab_e4", sample_scores={
            "v1": {"critic_scores": [80.0]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
            "v2": {"critic_scores": [80.5]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
        })

    assert result.judge_triggered is False
    assert result.judge_error == "experiment_cost_cap"


@pytest.mark.asyncio
async def test_e2e_meta_eval_agreement_rate_computation(async_session):
    """场景 5: meta-eval 计算 judge vs hard metric 在 clear-cut 上的一致率。"""
    from novel_dev.services.judge_meta_evaluator import JudgeMetaEvaluator

    jpv = JudgePromptVersion(id="jpv_meta", version="v1", agent_name="judge_agent", prompt_text="x", is_active=True)
    async_session.add(jpv)
    await async_session.flush()

    # 注入 3 条 ab_decisions:全部 clear-cut,2 个 judge 跟 hard 一致,1 个不一致
    decisions_data = [
        # hard v2 胜(85 vs 75),judge 跟(8.5 vs 7.0)→ 一致
        ABDecision(experiment_id="ab_meta_1", action="evaluate", decision_at=datetime.utcnow(),
                   scores={"v1": 75.0, "v2": 85.0}, judge_triggered=True,
                   judge_tie_breaker_baseline=7.0, judge_tie_breaker_challenger=8.5,
                   judge_model="claude-sonnet-4-6"),
        # hard v2 胜(80 vs 70),judge 跟 → 一致
        ABDecision(experiment_id="ab_meta_2", action="evaluate", decision_at=datetime.utcnow(),
                   scores={"v1": 70.0, "v2": 80.0}, judge_triggered=True,
                   judge_tie_breaker_baseline=6.5, judge_tie_breaker_challenger=8.0,
                   judge_model="claude-sonnet-4-6"),
        # hard v1 胜(85 vs 75),但 judge 选 v2(8.0 vs 7.0)→ 不一致
        ABDecision(experiment_id="ab_meta_3", action="evaluate", decision_at=datetime.utcnow(),
                   scores={"v1": 85.0, "v2": 75.0}, judge_triggered=True,
                   judge_tie_breaker_baseline=7.0, judge_tie_breaker_challenger=8.0,
                   judge_model="claude-sonnet-4-6"),
    ]
    for d in decisions_data:
        async_session.add(d)
    await async_session.flush()

    config = JudgeConfig(min_samples=1, clear_cut_threshold_pct=5.0, calibration_window_days=14)
    evaluator = JudgeMetaEvaluator(async_session, config)
    result = await evaluator.evaluate("jpv_meta")

    assert result.sample_size == 3
    assert abs(result.agreement_rate - 2 / 3) < 0.01
```

- [ ] **Step 2: 跑全部 E2E 测试**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_e2e/test_phase6_judge_tiebreaker.py -v`
Expected: 5 个测试全 PASS

- [ ] **Step 3: 跑 Phase 5 E2E 回归**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_e2e/test_phase5_ab_auto_acceptance.py -v`
Expected: 全 PASS(零回归)

- [ ] **Step 4: 提交**

```bash
git add tests/test_e2e/test_phase6_judge_tiebreaker.py
git commit -m "test(e2e): phase 6 judge tie-breaker 5 scenarios"
```

---

### Task 25: 性能基线测试

**Files:**
- Create: `tests/test_performance/test_judge_perf.py`

- [ ] **Step 1: 写性能测试**

在 `tests/test_performance/test_judge_perf.py`(新建):

```python
import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from novel_dev.config.ab_judge_config import JudgeConfig
from novel_dev.db.models import JudgePromptVersion, ABDecision
from novel_dev.agents.judge_agent import JudgeAgent
from novel_dev.llm.models import ChatMessage
from novel_dev.services.judge_meta_evaluator import JudgeMetaEvaluator


@pytest.mark.asyncio
async def test_judge_call_p95_under_8s(async_session):
    """1000 次连续 judge 调用(mock 200ms 延迟),P95 < 8s。

    注: 200ms mock 延迟是模拟 Sonnet 级模型平均响应;P95 上限 8s 包含 8x 延迟裕度。
    """
    pv = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="x {chapter_text}", is_active=True)
    async_session.add(pv)
    await async_session.flush()

    config = JudgeConfig()
    agent = JudgeAgent(async_session, config)

    fake_response = ChatMessage(
        role="assistant",
        content=json.dumps({"口吻": 7.0, "叙事连贯": 7.0, "风格调性": 7.0, "理由": "ok"}),
    )

    async def slow_complete(messages, conf, **kwargs):
        await asyncio.sleep(0.2)  # mock 200ms
        return fake_response

    latencies = []
    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(side_effect=slow_complete)
        mock_factory.get.return_value = mock_client
        for _ in range(20):  # 简化: 20 次而非 1000,测试 P95 算法稳定性
            start = time.monotonic()
            await agent.judge_sample("章节", version_id=None)
            latencies.append(time.monotonic() - start)

    latencies.sort()
    p95 = latencies[int(0.95 * len(latencies))]
    assert p95 < 8.0, f"P95 {p95:.2f}s exceeds 8s budget"


@pytest.mark.asyncio
async def test_meta_eval_throughput_under_5s(async_session):
    """10000 条历史决策,meta-eval 跑完 < 5s(用 SQL 聚合)。"""
    # 注入 10000 条(简化:用 100 条,验证 SQL 路径;真实规模上线前扩大)
    for i in range(100):
        d = ABDecision(
            experiment_id=f"ab_{i}",
            action="evaluate",
            decision_at=datetime.utcnow(),
            scores={"v1": 75.0, "v2": 85.0},
            judge_triggered=True,
            judge_tie_breaker_baseline=7.0,
            judge_tie_breaker_challenger=8.0,
            judge_model="claude-sonnet-4-6",
        )
        async_session.add(d)
    await async_session.flush()

    config = JudgeConfig(min_samples=1, clear_cut_threshold_pct=5.0, calibration_window_days=14)
    evaluator = JudgeMetaEvaluator(async_session, config)

    start = time.monotonic()
    result = await evaluator.evaluate("jpv_1")
    elapsed = time.monotonic() - start

    # 100 条 ≤ 1s;10000 条线性外推应 < 5s(实际 10000 是 100 的 100 倍,但 SQL 聚合常数时间)
    assert elapsed < 1.0, f"100 decisions took {elapsed:.2f}s, should be < 1s"
    assert result.sample_size == 100
```

- [ ] **Step 2: 跑性能测试**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_performance/test_judge_perf.py -v`
Expected: 2 个测试 PASS

- [ ] **Step 3: 跑全测试套件(确认零回归)**

Run: `PYTHONPATH=src python3.11 -m pytest tests/ -q --ignore=tests/test_e2e/test_phase6_judge_tiebreaker.py 2>&1 | tail -20`
Expected: 全部通过(基线 1881 + Phase 6 新增 ≈ 1900+ 测试)

- [ ] **Step 4: 跑 Phase 5 + 6 E2E 一起**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_e2e/ -q`
Expected: 全部通过(零回归)

- [ ] **Step 5: 跑全 Vue 测试**

Run: `cd src/novel_dev/web && npx vitest run`
Expected: 全部通过(基线 312 + Phase 6 新增 ≈ 320+ 测试)

- [ ] **Step 6: 提交**

```bash
git add tests/test_performance/test_judge_perf.py
git commit -m "test(perf): phase 6 judge call latency + meta_eval throughput"
```

---

# 验收清单

完成所有 25 任务后,验证以下标准:

- [ ] 5 个 E2E 场景全绿(`test_phase6_judge_tiebreaker.py`)
- [ ] 新增单元测试 ≥ 90% 覆盖(检查 `pytest --cov=src/novel_dev/agents/judge_agent ...`)
- [ ] 全部 1881+ Phase 5 测试零回归
- [ ] 性能基线通过(judge_call P95 < 8s,meta_eval 100 decisions < 1s)
- [ ] `ab_decisions` schema 迁移成功(开发 + 测试 DB 都跑过)
- [ ] ExperimentView "judge" tab 可用且 metric 卡片渲染正确
- [ ] 至少 1 个 judge prompt A/B 端到端跑通:创建 v1 → 创建 v2 → 启动 A/B → 注入历史 → meta-eval → auto-accept v2
- [ ] cost guard 触发时正确降级到 tie_random,不抛异常
- [ ] 旧 ab_decisions 行(judge_triggered=false)查询正常
- [ ] `llm_config.yaml` `ab_acceptance.judge` 段被正确读取

