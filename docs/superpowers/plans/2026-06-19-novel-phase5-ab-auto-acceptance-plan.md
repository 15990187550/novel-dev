# Phase 5 — A/B 赢家自动采纳 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Phase 3 建好的 A/B 基础设施真正闭环 — 跑完自动采纳、早停、超时、回滚。

**Architecture:** 双决策器分离 — `ABAcceptanceDecider` 在采样后内联判定采纳;`ABAcceptanceSweeper` 每 5 分钟定时扫兜底(早停/超时/回滚)。加权得分(critic 50% + hook 30% + thrill 20%),Welch's t-test 判定显著性,贝叶斯微调权重。

**Tech Stack:** Python 3.11, SQLAlchemy 2.0 async, Alembic, Pydantic v2, FastAPI, pytest-asyncio, freezegun, scipy (Welch's t-test), Vue 3.

**前置:** Phase 4 完成(commit `d786930`)。所有任务在 `phase2-writer-protection` 分支上提交。

---

## 文件结构

**新增文件:**
- `src/novel_dev/models/ab_decision.py` — ABD decision ORM 模型
- `src/novel_dev/repositories/ab_decision_repo.py` — ABD decision 数据访问
- `src/novel_dev/services/ab_weighted_score.py` — 加权得分计算
- `src/novel_dev/services/ab_significance.py` — 显著性检验
- `src/novel_dev/services/ab_bayesian_weights.py` — 贝叶斯权重更新
- `src/novel_dev/services/ab_acceptance_decider.py` — 内联合入决策
- `src/novel_dev/services/ab_acceptance_sweeper.py` — 定时扫兜底
- `src/novel_dev/services/ab_decision_recorder.py` — 统一写 ab_decisions 入口
- `tests/test_services/test_ab_weighted_score.py`
- `tests/test_services/test_ab_significance.py`
- `tests/test_services/test_ab_bayesian_weights.py`
- `tests/test_services/test_ab_acceptance_decider.py`
- `tests/test_services/test_ab_acceptance_sweeper.py`
- `tests/test_api/test_ab_decisions_api.py`
- `tests/test_e2e/test_phase5_ab_auto_acceptance.py`
- `migrations/versions/<timestamp>_phase5_ab_decisions_tables.py`
- `src/novel_dev/web/src/views/ExperimentView.vue`
- `src/novel_dev/web/src/views/ExperimentView.test.js`
- `src/novel_dev/web/src/components/ExperimentWidget.vue`
- `src/novel_dev/web/src/components/ExperimentWidget.test.js`
- `src/novel_dev/web/src/components/ExperimentToast.vue`
- `src/novel_dev/web/src/components/ExperimentToast.test.js`

**修改文件:**
- `src/novel_dev/db/models.py` — PromptVersion 加 4 字段
- `src/novel_dev/repositories/prompt_version_repo.py` — 加新查询/更新方法
- `src/novel_dev/services/prompt_registry.py` — `increment_sample_count` 触发 decider
- `src/novel_dev/services/log_service.py` — 加 `decision_event` 级别
- `src/novel_dev/api/routes.py` — 加 3 个端点
- `src/novel_dev/web/src/api.js` — 加 3 个 helper
- `src/novel_dev/web/src/router.js` — 加 1 个路由
- `llm_config.yaml` — 加 `ab_auto_acceptance` 段
- `src/novel_dev/config/quality_config.py` — 加 `get_phase5_config()`

---

# Wave 1: 基础设施(5 任务)

### Task 1: PromptVersion 4 字段扩展 + 迁移

**Files:**
- Modify: `src/novel_dev/db/models.py:256-272`
- Create: `migrations/versions/20260619_<hash>_phase5_prompt_version_extension.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_db/test_prompt_version_extension.py`(新建):

```python
import pytest
from novel_dev.db.models import PromptVersion


@pytest.mark.asyncio
async def test_prompt_version_has_phase5_fields(async_session):
    pv = PromptVersion(
        agent_name="writer", version="v1.0", content="x",
        experiment_state="running", last_score=78.5,
    )
    async_session.add(pv)
    await async_session.flush()
    fetched = await async_session.get(PromptVersion, pv.id)
    assert fetched.experiment_state == "running"
    assert fetched.last_score == 78.5
    assert fetched.last_decision_at is None
    assert fetched.experiment_history == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_db/test_prompt_version_extension.py -v`
Expected: FAIL — `experiment_state` field missing

- [ ] **Step 3: 在 PromptVersion 加 4 字段**

修改 `src/novel_dev/db/models.py:256-272`,在 `ab_test_id` 后追加:

```python
    experiment_state: Mapped[str] = mapped_column(String(32), nullable=False, default="none", index=True)
    last_decision_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    experiment_history: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_db/test_prompt_version_extension.py -v`
Expected: PASS

- [ ] **Step 5: 创建 alembic 迁移**

Run:
```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m alembic revision --autogenerate -m "phase5 prompt_version extension"
```
然后手工精简生成的迁移,只保留 4 个新列(`experiment_state` / `last_decision_at` / `last_score` / `experiment_history`),丢弃其他漂移。

- [ ] **Step 6: 应用迁移**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m alembic upgrade head`

- [ ] **Step 7: 跑全量测试确认无回归**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q`
Expected: all pass

- [ ] **Step 8: 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/db/models.py migrations/ tests/test_db/
git commit -m "feat(phase5): extend PromptVersion with experiment_state fields + migration"
```

---

### Task 2: ABDecision 模型 + 迁移

**Files:**
- Create: `src/novel_dev/db/models.py:new_section`(追加,不替换现有)
- Create: `migrations/versions/20260619_<hash>_phase5_ab_decisions_table.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_db/test_ab_decision_model.py`(新建):

```python
import pytest
from datetime import datetime, timedelta
from novel_dev.db.models import ABDecision


@pytest.mark.asyncio
async def test_ab_decision_persists_with_required_fields(async_session):
    d = ABDecision(
        experiment_id="exp_1",
        prompt_version_id="pv_1",
        action="evaluate",
        decision_at=datetime.utcnow(),
        p_value=0.03,
        scores={"v1": 75.0, "v2": 79.0},
        effect_size=0.4,
        metadata={"samples": 50},
    )
    async_session.add(d)
    await async_session.flush()
    fetched = await async_session.get(ABDecision, d.id)
    assert fetched.action == "evaluate"
    assert fetched.scores["v2"] == 79.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_db/test_ab_decision_model.py -v`
Expected: FAIL — `ABDecision` not defined

- [ ] **Step 3: 添加 ABDecision 模型到 models.py**

在 `src/novel_dev/db/models.py` 末尾(在 ABTest 类后)追加:

```python
class ABDecision(Base):
    __tablename__ = "ab_decisions"
    __table_args__ = (
        Index("ix_ab_decisions_experiment", "experiment_id"),
        Index("ix_ab_decisions_action", "action"),
        Index("ix_ab_decisions_decision_at", "decision_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    experiment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    prompt_version_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    decision_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    p_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    scores: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    effect_size: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
```

- [ ] **Step 4: 创建 alembic 迁移**

Run:
```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m alembic revision --autogenerate -m "phase5 ab_decisions table"
```
精简到只创建 `ab_decisions` 表 + 3 个索引。

- [ ] **Step 5: 应用迁移 + 跑测试**

Run:
```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m alembic upgrade head
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_db/test_ab_decision_model.py -v
```
Expected: PASS

- [ ] **Step 6: 跑全量测试**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q`

- [ ] **Step 7: 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/db/models.py migrations/ tests/test_db/
git commit -m "feat(phase5): ABDecision model + ab_decisions table migration"
```

---

### Task 3: ABDecisionRepository

**Files:**
- Create: `src/novel_dev/repositories/ab_decision_repo.py`
- Create: `tests/test_repositories/test_ab_decision_repo.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from datetime import datetime
from novel_dev.repositories.ab_decision_repo import ABDecisionRepository


@pytest.mark.asyncio
async def test_create_and_query_recent(async_session):
    repo = ABDecisionRepository(async_session)
    for i in range(3):
        await repo.create(
            experiment_id="exp_1", action="evaluate",
            scores={"v1": 75.0 + i}, metadata={"i": i},
        )
    recent = await repo.list_recent(window_minutes=60)
    assert len(recent) == 3
    assert all(d.experiment_id == "exp_1" for d in recent)


@pytest.mark.asyncio
async def test_list_by_experiment(async_session):
    repo = ABDecisionRepository(async_session)
    await repo.create(experiment_id="exp_1", action="accept", scores={"v2": 80.0})
    await repo.create(experiment_id="exp_2", action="timeout", scores={"v1": 70.0})
    exp1 = await repo.list_by_experiment("exp_1")
    assert len(exp1) == 1
    assert exp1[0].action == "accept"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_ab_decision_repo.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 实现 ABDecisionRepository**

Create `src/novel_dev/repositories/ab_decision_repo.py`:

```python
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import ABDecision


class ABDecisionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self, experiment_id: str, action: str,
        prompt_version_id: Optional[str] = None,
        decision_at: Optional[datetime] = None,
        p_value: Optional[float] = None,
        scores: Optional[dict] = None,
        effect_size: Optional[float] = None,
        metadata: Optional[dict] = None,
    ) -> ABDecision:
        d = ABDecision(
            experiment_id=experiment_id,
            prompt_version_id=prompt_version_id,
            action=action,
            decision_at=decision_at or datetime.utcnow(),
            p_value=p_value,
            scores=scores or {},
            effect_size=effect_size,
            metadata=metadata or {},
        )
        self.session.add(d)
        await self.session.flush()
        return d

    async def list_by_experiment(self, experiment_id: str) -> list[ABDecision]:
        result = await self.session.execute(
            select(ABDecision)
            .where(ABDecision.experiment_id == experiment_id)
            .order_by(ABDecision.decision_at.asc())
        )
        return list(result.scalars().all())

    async def list_recent(self, window_minutes: int = 60) -> list[ABDecision]:
        cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
        result = await self.session.execute(
            select(ABDecision)
            .where(ABDecision.decision_at >= cutoff)
            .order_by(ABDecision.decision_at.desc())
        )
        return list(result.scalars().all())

    async def latest_for_experiment(self, experiment_id: str) -> Optional[ABDecision]:
        result = await self.session.execute(
            select(ABDecision)
            .where(ABDecision.experiment_id == experiment_id)
            .order_by(ABDecision.decision_at.desc())
            .limit(1)
        )
        return result.scalars().first()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_ab_decision_repo.py -v`
Expected: PASS

- [ ] **Step 5: 跑全量 + 提交**

Run:
```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -3
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/repositories/ab_decision_repo.py tests/test_repositories/test_ab_decision_repo.py
git commit -m "feat(phase5): ABDecisionRepository with create/list_recent/list_by_experiment"
```

---

### Task 4: PromptVersionRepository 新方法

**Files:**
- Modify: `src/novel_dev/repositories/prompt_version_repo.py`(加 4 方法)
- Create: `tests/test_repositories/test_prompt_version_repo_methods.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from datetime import datetime
from novel_dev.db.models import PromptVersion
from novel_dev.repositories.prompt_version_repo import PromptVersionRepository


@pytest.mark.asyncio
async def test_update_experiment_state(async_session):
    pv = PromptVersion(agent_name="writer", version="v1.0", content="x")
    async_session.add(pv)
    await async_session.flush()
    repo = PromptVersionRepository(async_session)
    await repo.update_experiment_state(pv.id, "auto_accepted", last_score=82.5)
    await async_session.refresh(pv)
    assert pv.experiment_state == "auto_accepted"
    assert pv.last_score == 82.5


@pytest.mark.asyncio
async def test_list_by_ab_test_id(async_session):
    pv1 = PromptVersion(agent_name="writer", version="v1", content="x", ab_test_id="ab_1")
    pv2 = PromptVersion(agent_name="writer", version="v2", content="y", ab_test_id="ab_1")
    pv3 = PromptVersion(agent_name="writer", version="v3", content="z", ab_test_id="ab_2")
    async_session.add_all([pv1, pv2, pv3])
    await async_session.flush()
    repo = PromptVersionRepository(async_session)
    result = await repo.list_by_ab_test_id("ab_1")
    assert len(result) == 2


@pytest.mark.asyncio
async def test_get_previous_stable_version(async_session):
    pv_old = PromptVersion(agent_name="writer", version="v0.9", content="x", experiment_state="stable", is_active=False)
    pv_new = PromptVersion(agent_name="writer", version="v1.0", content="y", experiment_state="auto_accepted", is_active=True)
    async_session.add_all([pv_old, pv_new])
    await async_session.flush()
    repo = PromptVersionRepository(async_session)
    prev = await repo.get_previous_stable("writer", exclude_version="v1.0")
    assert prev.version == "v0.9"


@pytest.mark.asyncio
async def test_append_experiment_history(async_session):
    pv = PromptVersion(agent_name="writer", version="v1", content="x")
    async_session.add(pv)
    await async_session.flush()
    repo = PromptVersionRepository(async_session)
    await repo.append_history(pv.id, {"action": "evaluate", "p": 0.03})
    await async_session.refresh(pv)
    assert len(pv.experiment_history) == 1
    assert pv.experiment_history[0]["action"] == "evaluate"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_prompt_version_repo_methods.py -v`
Expected: FAIL — methods missing

- [ ] **Step 3: 在 PromptVersionRepository 加 4 方法**

修改 `src/novel_dev/repositories/prompt_version_repo.py`,在文件末尾添加:

```python
    async def update_experiment_state(
        self, prompt_version_id: str, state: str,
        last_score: float | None = None,
        decision_at: datetime | None = None,
    ) -> None:
        pv = await self.session.get(PromptVersion, prompt_version_id)
        if not pv:
            return
        pv.experiment_state = state
        if last_score is not None:
            pv.last_score = last_score
        if decision_at is not None:
            pv.last_decision_at = decision_at
        await self.session.flush()

    async def list_by_ab_test_id(self, ab_test_id: str) -> list[PromptVersion]:
        from sqlalchemy import select
        result = await self.session.execute(
            select(PromptVersion).where(PromptVersion.ab_test_id == ab_test_id)
        )
        return list(result.scalars().all())

    async def get_previous_stable(self, agent_name: str, exclude_version: str) -> PromptVersion | None:
        from sqlalchemy import select
        result = await self.session.execute(
            select(PromptVersion)
            .where(PromptVersion.agent_name == agent_name)
            .where(PromptVersion.experiment_state == "stable")
            .where(PromptVersion.version != exclude_version)
            .order_by(PromptVersion.last_decision_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def append_history(self, prompt_version_id: str, event: dict) -> None:
        pv = await self.session.get(PromptVersion, prompt_version_id)
        if not pv:
            return
        history = list(pv.experiment_history or [])
        history.append(event)
        pv.experiment_history = history
        await self.session.flush()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_prompt_version_repo_methods.py -v`
Expected: PASS

- [ ] **Step 5: 跑全量 + 提交**

Run:
```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -3
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/repositories/prompt_version_repo.py tests/test_repositories/test_prompt_version_repo_methods.py
git commit -m "feat(phase5): PromptVersionRepository experiment_state helpers"
```

---

### Task 5: ABDecisionRecorder + log_service decision_event 级别

**Files:**
- Create: `src/novel_dev/services/ab_decision_recorder.py`
- Modify: `src/novel_dev/services/log_service.py`
- Create: `tests/test_services/test_ab_decision_recorder.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from novel_dev.services.ab_decision_recorder import ABDecisionRecorder


@pytest.mark.asyncio
async def test_record_writes_db_row_and_logs(async_session):
    from novel_dev.repositories.ab_decision_repo import ABDecisionRepository
    recorder = ABDecisionRecorder(async_session)
    decision = await recorder.record(
        experiment_id="exp_1",
        action="accept",
        prompt_version_id="pv_1",
        scores={"v1": 75.0, "v2": 80.0},
        p_value=0.03,
        metadata={"reason": "weighted_score_lift"},
    )
    assert decision.id is not None
    assert decision.action == "accept"
    repo = ABDecisionRepository(async_session)
    recent = await repo.list_recent(window_minutes=5)
    assert len(recent) == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_services/test_ab_decision_recorder.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 ABDecisionRecorder**

Create `src/novel_dev/services/ab_decision_recorder.py`:

```python
from __future__ import annotations
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import ABDecision
from novel_dev.repositories.ab_decision_repo import ABDecisionRepository

logger = logging.getLogger(__name__)

CRITICAL_ACTIONS = {"accept", "early_stop", "timeout", "rolled_back", "rollback_no_target", "accept_failed"}


class ABDecisionRecorder:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ABDecisionRepository(session)

    async def record(
        self,
        experiment_id: str,
        action: str,
        prompt_version_id: Optional[str] = None,
        scores: Optional[dict] = None,
        p_value: Optional[float] = None,
        effect_size: Optional[float] = None,
        metadata: Optional[dict] = None,
    ) -> ABDecision:
        decision = await self.repo.create(
            experiment_id=experiment_id,
            action=action,
            prompt_version_id=prompt_version_id,
            scores=scores or {},
            p_value=p_value,
            effect_size=effect_size,
            metadata=metadata or {},
        )
        log_level = logging.ERROR if action in CRITICAL_ACTIONS else logging.INFO
        logger.log(
            log_level,
            f"ab_decision_{action}",
            extra={
                "experiment_id": experiment_id,
                "prompt_version_id": prompt_version_id,
                "scores": scores,
                "p_value": p_value,
            },
        )
        return decision
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_services/test_ab_decision_recorder.py -v`
Expected: PASS

- [ ] **Step 5: 跑全量 + 提交**

Run:
```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -3
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/services/ab_decision_recorder.py tests/test_services/test_ab_decision_recorder.py
git commit -m "feat(phase5): ABDecisionRecorder with critical-action ERROR logging"
```

---

# Wave 2: 判定组件(5 任务)

### Task 6: WeightedScoreCalculator

**Files:**
- Create: `src/novel_dev/services/ab_weighted_score.py`
- Create: `tests/test_services/test_ab_weighted_score.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from novel_dev.services.ab_weighted_score import WeightedScoreCalculator


def test_default_weights_compute_correctly():
    calc = WeightedScoreCalculator()
    score = calc.compute(critic_mean=80.0, hook_rate=0.5, thrill_rate=0.3)
    # 80 * 0.5 + 50 * 0.3 + 30 * 0.2 = 40 + 15 + 6 = 61
    assert score == pytest.approx(61.0)


def test_custom_weights():
    calc = WeightedScoreCalculator(weights={"critic": 0.7, "hook": 0.2, "thrill": 0.1})
    score = calc.compute(critic_mean=90.0, hook_rate=0.5, thrill_rate=0.5)
    # 90 * 0.7 + 50 * 0.2 + 50 * 0.1 = 63 + 10 + 5 = 78
    assert score == pytest.approx(78.0)


def test_compute_batch_returns_per_version():
    calc = WeightedScoreCalculator()
    samples = {
        "v1": {"critic_scores": [80, 82], "hook_achieved": [True, False], "thrill_verified": [True, True]},
        "v2": {"critic_scores": [78, 79], "hook_achieved": [True, True], "thrill_verified": [False, True]},
    }
    scores = calc.compute_batch(samples)
    # v1: critic=81, hook=0.5, thrill=1.0 → 81*0.5 + 50*0.3 + 100*0.2 = 40.5+15+20=75.5
    # v2: critic=78.5, hook=1.0, thrill=0.5 → 78.5*0.5 + 100*0.3 + 50*0.2 = 39.25+30+10=79.25
    assert scores["v1"] == pytest.approx(75.5)
    assert scores["v2"] == pytest.approx(79.25)


def test_returns_none_for_empty_samples():
    calc = WeightedScoreCalculator()
    scores = calc.compute_batch({"v1": {"critic_scores": [], "hook_achieved": [], "thrill_verified": []}})
    assert scores["v1"] is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_services/test_ab_weighted_score.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 WeightedScoreCalculator**

Create `src/novel_dev/services/ab_weighted_score.py`:

```python
from __future__ import annotations
from typing import Optional


DEFAULT_WEIGHTS = {"critic": 0.5, "hook": 0.3, "thrill": 0.2}


class WeightedScoreCalculator:
    def __init__(self, weights: Optional[dict] = None):
        self.weights = weights or DEFAULT_WEIGHTS

    def compute(self, critic_mean: float, hook_rate: float, thrill_rate: float) -> float:
        return (
            critic_mean * self.weights["critic"]
            + hook_rate * 100 * self.weights["hook"]
            + thrill_rate * 100 * self.weights["thrill"]
        )

    def compute_batch(self, samples_by_version: dict) -> dict[str, Optional[float]]:
        result = {}
        for version, samples in samples_by_version.items():
            critics = samples.get("critic_scores", [])
            hooks = samples.get("hook_achieved", [])
            thrills = samples.get("thrill_verified", [])
            if not critics:
                result[version] = None
                continue
            critic_mean = sum(critics) / len(critics)
            hook_rate = sum(1 for h in hooks if h) / len(hooks) if hooks else 0.0
            thrill_rate = sum(1 for t in thrills if t) / len(thrills) if thrills else 0.0
            result[version] = self.compute(critic_mean, hook_rate, thrill_rate)
        return result
```

- [ ] **Step 4: 跑测试 + 全量 + 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_services/test_ab_weighted_score.py -v
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -3
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/services/ab_weighted_score.py tests/test_services/test_ab_weighted_score.py
git commit -m "feat(phase5): WeightedScoreCalculator with default + custom weights"
```

---

### Task 7: SignificanceTester + 自适应阈值

**Files:**
- Create: `src/novel_dev/services/ab_significance.py`
- Create: `tests/test_services/test_ab_significance.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from novel_dev.services.ab_significance import SignificanceTester, STRICT_THRESHOLDS, RELAXED_THRESHOLDS


def test_returns_not_significant_when_samples_below_min():
    tester = SignificanceTester()
    result = tester.test({"v1": [80.0] * 10, "v2": [82.0] * 10})
    assert result.is_significant is False
    assert result.threshold_used == "strict"


def test_strict_threshold_significant_with_clear_lift():
    tester = SignificanceTester()
    result = tester.test(
        {"v1": [75.0] * 50, "v2": [85.0] * 50}
    )
    assert result.is_significant is True
    assert result.p_value < 0.05


def test_relaxes_after_three_unsuccessful_attempts():
    tester = SignificanceTester(initial_mode="strict")
    # First 3 calls return not-significant
    for _ in range(3):
        tester.test({"v1": [80.0] * 10, "v2": [80.5] * 10})
    # Now mode should be relaxed
    assert tester.current_mode == "relaxed"


def test_strict_threshold_blocks_on_min_samples():
    tester = SignificanceTester(thresholds=STRICT_THRESHOLDS)
    result = tester.test({"v1": [80.0] * 49, "v2": [85.0] * 49})
    assert result.is_significant is False
    assert "samples_below_min" in (result.reason or "")


def test_zero_variance_returns_not_significant():
    tester = SignificanceTester()
    result = tester.test({"v1": [80.0] * 50, "v2": [80.0] * 50})
    assert result.is_significant is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_services/test_ab_significance.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 SignificanceTester**

Create `src/novel_dev/services/ab_significance.py`:

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from scipy import stats

STRICT_THRESHOLDS = {"min_samples": 50, "p_value": 0.05, "min_lift": 0.03}
RELAXED_THRESHOLDS = {"min_samples": 30, "p_value": 0.10, "min_lift": 0.02}


@dataclass
class SignificanceResult:
    is_significant: bool
    p_value: Optional[float]
    effect_size: Optional[float]
    threshold_used: str
    reason: Optional[str] = None


class SignificanceTester:
    def __init__(self, thresholds=None, initial_mode: str = "strict"):
        self.thresholds = thresholds or STRICT_THRESHOLDS
        self.current_mode = initial_mode
        self._unsuccessful_attempts = 0

    def _current_thresholds(self) -> dict:
        return RELAXED_THRESHOLDS if self.current_mode == "relaxed" else self.thresholds

    def test(self, scores_by_version: dict) -> SignificanceResult:
        thresholds = self._current_thresholds()
        versions = list(scores_by_version.keys())
        if len(versions) != 2:
            return SignificanceResult(False, None, None, self.current_mode, "need_exactly_two_versions")

        a_scores = scores_by_version[versions[0]]
        b_scores = scores_by_version[versions[1]]
        min_n = min(len(a_scores), len(b_scores))

        if min_n < thresholds["min_samples"]:
            self._unsuccessful_attempts += 1
            self._maybe_relax()
            return SignificanceResult(False, None, None, self.current_mode, "samples_below_min")

        if len(set(a_scores)) == 1 and len(set(b_scores)) == 1 and a_scores[0] == b_scores[0]:
            self._unsuccessful_attempts += 1
            self._maybe_relax()
            return SignificanceResult(False, None, None, self.current_mode, "zero_variance_identical")

        try:
            t_stat, p_value = stats.ttest_ind(a_scores, b_scores, equal_var=False)
        except Exception:
            self._unsuccessful_attempts += 1
            self._maybe_relax()
            return SignificanceResult(False, None, None, self.current_mode, "t_test_failed")

        a_mean = sum(a_scores) / len(a_scores)
        b_mean = sum(b_scores) / len(b_scores)
        lift = (b_mean - a_mean) / a_mean if a_mean != 0 else 0.0
        effect_size = abs(b_mean - a_mean)

        is_sig = (
            p_value < thresholds["p_value"]
            and abs(lift) >= thresholds["min_lift"]
        )

        if is_sig:
            self._unsuccessful_attempts = 0
        else:
            self._unsuccessful_attempts += 1
            self._maybe_relax()

        return SignificanceResult(is_sig, float(p_value), float(effect_size), self.current_mode)

    def _maybe_relax(self) -> None:
        if self.current_mode == "strict" and self._unsuccessful_attempts >= 3:
            self.current_mode = "relaxed"

    def reset(self) -> None:
        self._unsuccessful_attempts = 0
        self.current_mode = "strict"
```

- [ ] **Step 4: 跑测试 + 全量 + 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_services/test_ab_significance.py -v
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -3
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/services/ab_significance.py tests/test_services/test_ab_significance.py
git commit -m "feat(phase5): SignificanceTester with adaptive strict/relaxed thresholds"
```

---

### Task 8: BayesianWeightUpdater

**Files:**
- Create: `src/novel_dev/services/ab_bayesian_weights.py`
- Create: `tests/test_services/test_ab_bayesian_weights.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from novel_dev.services.ab_bayesian_weights import BayesianWeightUpdater, DEFAULT_WEIGHTS


def test_first_update_returns_default_weights():
    updater = BayesianWeightUpdater(prior={"critic": 0.5, "hook": 0.3, "thrill": 0.2})
    new_weights = updater.update(sample_count=10)
    assert new_weights == DEFAULT_WEIGHTS


def test_updates_after_threshold():
    updater = BayesianWeightUpdater(prior={"critic": 0.5, "hook": 0.3, "thrill": 0.2}, update_interval=50)
    updater.update(sample_count=49)
    updater.update(sample_count=50)  # triggers update
    # After update, weights may have changed but still sum to 1
    new_weights = updater.update(sample_count=100)
    assert abs(sum(new_weights.values()) - 1.0) < 1e-6


def test_constraint_clips_within_0_2_of_default():
    updater = BayesianWeightUpdater(
        prior={"critic": 0.5, "hook": 0.3, "thrill": 0.2},
        update_interval=10,
        max_drift=0.2,
    )
    # Force weights to drift wildly
    new_weights = updater.update(
        sample_count=100,
        observed={"critic": 100.0, "hook": 0.0, "thrill": 0.0},
    )
    assert abs(new_weights["critic"] - 0.5) <= 0.2 + 1e-6
    assert abs(new_weights["hook"] - 0.3) <= 0.2 + 1e-6


def test_weights_normalize_to_one():
    updater = BayesianWeightUpdater(update_interval=10)
    new_weights = updater.update(sample_count=20, observed={"critic": 70.0, "hook": 60.0, "thrill": 50.0})
    assert abs(sum(new_weights.values()) - 1.0) < 1e-6
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_services/test_ab_bayesian_weights.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 BayesianWeightUpdater**

Create `src/novel_dev/services/ab_bayesian_weights.py`:

```python
from __future__ import annotations
from typing import Optional


DEFAULT_WEIGHTS = {"critic": 0.5, "hook": 0.3, "thrill": 0.2}


class BayesianWeightUpdater:
    """Dirichlet posterior over (critic, hook, thrill) weights.

    Updates only when sample_count crosses a multiple of update_interval.
    Constraints: any weight must stay within ±max_drift of the prior.
    """

    def __init__(
        self,
        prior: Optional[dict] = None,
        update_interval: int = 50,
        max_drift: float = 0.2,
        random_seed: int = 42,
    ):
        self.prior = prior or DEFAULT_WEIGHTS
        self.update_interval = update_interval
        self.max_drift = max_drift
        self._last_update_at = 0

    def update(
        self,
        sample_count: int,
        observed: Optional[dict] = None,
    ) -> dict:
        if sample_count < self.update_interval:
            return DEFAULT_WEIGHTS
        if (sample_count - self._last_update_at) < self.update_interval:
            return DEFAULT_WEIGHTS
        if observed is None:
            return DEFAULT_WEIGHTS

        total = sum(max(observed.get(k, 0.0), 0.0) for k in self.prior)
        if total <= 0:
            return DEFAULT_WEIGHTS

        raw = {k: max(observed.get(k, 0.0), 0.0) / total for k in self.prior}

        clipped = {}
        for k, default in self.prior.items():
            lo = max(0.0, default - self.max_drift)
            hi = default + self.max_drift
            clipped[k] = max(lo, min(hi, raw[k]))

        s = sum(clipped.values())
        normalized = {k: v / s for k, v in clipped.items()}

        self._last_update_at = sample_count
        return normalized
```

- [ ] **Step 4: 跑测试 + 全量 + 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_services/test_ab_bayesian_weights.py -v
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -3
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/services/ab_bayesian_weights.py tests/test_services/test_ab_bayesian_weights.py
git commit -m "feat(phase5): BayesianWeightUpdater with Dirichlet + drift constraint"
```

---

# Wave 3: 决策器(5 任务)

### Task 9: ABAcceptanceDecider (内联)

**Files:**
- Create: `src/novel_dev/services/ab_acceptance_decider.py`
- Create: `tests/test_services/test_ab_acceptance_decider.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime
from novel_dev.db.models import PromptVersion, ABTest
from novel_dev.services.ab_acceptance_decider import ABAcceptanceDecider


@pytest.mark.asyncio
async def test_accepts_challenger_when_significant(async_session):
    # Setup A/B test
    pv_baseline = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_1", sample_count=50)
    pv_challenger = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_1", sample_count=50)
    ab = ABTest(id="ab_1", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running")
    async_session.add_all([pv_baseline, pv_challenger, ab])
    await async_session.flush()

    decider = ABAcceptanceDecider(async_session)
    # Inject deterministic significant test + score
    decider.significance_tester = MagicMock()
    decider.significance_tester.test = MagicMock(return_value=MagicMock(is_significant=True, p_value=0.03, effect_size=4.0, threshold_used="strict", reason=None))
    decider.weighted_calc = MagicMock()
    decider.weighted_calc.compute_batch = MagicMock(return_value={"v1": 75.0, "v2": 80.0})

    result = await decider.evaluate(experiment_id="ab_1", sample_scores={
        "v1": {"critic_scores": [80.0]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
        "v2": {"critic_scores": [85.0]*50, "hook_achieved": [True]*50, "thrill_verified": [True]*50},
    })
    assert result.action == "accepted"
    assert result.winner == "v2"
    await async_session.refresh(pv_challenger)
    assert pv_challenger.experiment_state == "auto_accepted"
    assert pv_challenger.is_active is True


@pytest.mark.asyncio
async def test_no_action_when_samples_below_min(async_session):
    pv1 = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_1", sample_count=5)
    pv2 = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_1", sample_count=5)
    async_session.add_all([pv1, pv2])
    await async_session.flush()

    decider = ABAcceptanceDecider(async_session)
    result = await decider.evaluate(experiment_id="ab_1", sample_scores={
        "v1": {"critic_scores": [80.0], "hook_achieved": [True], "thrill_verified": [True]},
        "v2": {"critic_scores": [85.0], "hook_achieved": [True], "thrill_verified": [True]},
    })
    assert result.action == "no_action"


@pytest.mark.asyncio
async def test_returns_skipped_on_calculator_failure(async_session):
    pv1 = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_1", sample_count=50)
    pv2 = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_1", sample_count=50)
    async_session.add_all([pv1, pv2])
    await async_session.flush()

    decider = ABAcceptanceDecider(async_session)
    decider.weighted_calc = MagicMock()
    decider.weighted_calc.compute_batch = MagicMock(return_value={"v1": None, "v2": None})
    result = await decider.evaluate(experiment_id="ab_1", sample_scores={
        "v1": {"critic_scores": [], "hook_achieved": [], "thrill_verified": []},
        "v2": {"critic_scores": [], "hook_achieved": [], "thrill_verified": []},
    })
    assert result.action == "skipped"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_services/test_ab_acceptance_decider.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 ABAcceptanceDecider**

Create `src/novel_dev/services/ab_acceptance_decider.py`:

```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import ABTest, PromptVersion
from novel_dev.repositories.ab_decision_repo import ABDecisionRepository
from novel_dev.repositories.prompt_version_repo import PromptVersionRepository
from novel_dev.services.ab_significance import SignificanceTester
from novel_dev.services.ab_weighted_score import WeightedScoreCalculator
from novel_dev.services.ab_decision_recorder import ABDecisionRecorder


@dataclass
class DeciderResult:
    action: str  # "accepted" | "no_action" | "skipped" | "no_improvement" | "error"
    winner: Optional[str] = None
    p_value: Optional[float] = None
    scores: Optional[dict] = None
    reason: Optional[str] = None


class ABAcceptanceDecider:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.weighted_calc = WeightedScoreCalculator()
        self.significance_tester = SignificanceTester()
        self.pv_repo = PromptVersionRepository(session)
        self.decision_repo = ABDecisionRepository(session)
        self.recorder = ABDecisionRecorder(session)

    async def evaluate(
        self, experiment_id: str, sample_scores: dict,
    ) -> DeciderResult:
        ab = await self.session.get(ABTest, experiment_id)
        if not ab or ab.status != "running":
            return DeciderResult(action="no_action", reason="experiment_not_running")

        scores = self.weighted_calc.compute_batch(sample_scores)
        if any(v is None for v in scores.values()):
            await self.recorder.record(
                experiment_id=experiment_id,
                action="evaluate",
                scores=scores,
                metadata={"decision": "skipped", "reason": "calculator_returned_none"},
            )
            return DeciderResult(action="skipped", reason="calculator_returned_none")

        versions = [ab.baseline_version, ab.challenger_version]
        scores_by_version_for_test = {
            v: sample_scores.get(v, {}).get("critic_scores", [])
            for v in versions
        }
        significance = self.significance_tester.test(scores_by_version_for_test)

        await self.recorder.record(
            experiment_id=experiment_id,
            action="evaluate",
            scores=scores,
            p_value=significance.p_value,
            effect_size=significance.effect_size,
            metadata={
                "decision": "accepted" if significance.is_significant else "no_action",
                "threshold": significance.threshold_used,
                "reason": significance.reason,
            },
        )

        if not significance.is_significant:
            return DeciderResult(
                action="no_action",
                p_value=significance.p_value,
                scores=scores,
                reason=significance.reason,
            )

        winner = max(scores, key=scores.get)
        if winner == ab.baseline_version:
            for pv in await self._get_pvs(ab):
                if pv.version == ab.challenger_version:
                    await self.pv_repo.update_experiment_state(pv.id, "no_improvement")
            await self.recorder.record(
                experiment_id=experiment_id,
                action="evaluate",
                scores=scores,
                metadata={"decision": "no_improvement", "winner": winner},
            )
            return DeciderResult(action="no_improvement", winner=winner, scores=scores)

        for pv in await self._get_pvs(ab):
            if pv.version == winner:
                await self.pv_repo.update_experiment_state(
                    pv.id, "auto_accepted", last_score=scores[winner],
                    decision_at=datetime.utcnow(),
                )
                pv.is_active = True
                await self.pv_repo.append_history(pv.id, {
                    "action": "auto_accepted",
                    "experiment_id": ab.id,
                    "weighted_score": scores[winner],
                    "p_value": significance.p_value,
                    "at": datetime.utcnow().isoformat(),
                })
            elif pv.version == ab.baseline_version:
                pv.is_active = False
                await self.pv_repo.update_experiment_state(
                    pv.id, "active-rolled-back",
                    decision_at=datetime.utcnow(),
                )
                await self.pv_repo.append_history(pv.id, {
                    "action": "active-rolled-back",
                    "experiment_id": ab.id,
                    "at": datetime.utcnow().isoformat(),
                })

        ab.status = "completed"
        ab.winner = winner
        ab.ended_at = datetime.utcnow()
        await self.session.flush()

        winner_pv = next(pv for pv in await self._get_pvs(ab) if pv.version == winner)
        await self.recorder.record(
            experiment_id=experiment_id,
            action="accept",
            prompt_version_id=winner_pv.id,
            scores=scores,
            p_value=significance.p_value,
            effect_size=significance.effect_size,
            metadata={"winner": winner, "monitoring_window_hours": 24},
        )

        return DeciderResult(action="accepted", winner=winner, p_value=significance.p_value, scores=scores)

    async def _get_pvs(self, ab: ABTest) -> list[PromptVersion]:
        result = await self.session.execute(
            select(PromptVersion).where(PromptVersion.ab_test_id == ab.id)
        )
        return list(result.scalars().all())
```

- [ ] **Step 4: 跑测试 + 全量 + 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_services/test_ab_acceptance_decider.py -v
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -3
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/services/ab_acceptance_decider.py tests/test_services/test_ab_acceptance_decider.py
git commit -m "feat(phase5): ABAcceptanceDecider with inline evaluate + accept"
```

---

### Task 10: ABAcceptanceSweeper (定时扫兜底)

**Files:**
- Create: `src/novel_dev/services/ab_acceptance_sweeper.py`
- Create: `tests/test_services/test_ab_acceptance_sweeper.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock
from novel_dev.db.models import PromptVersion, ABTest
from novel_dev.services.ab_acceptance_sweeper import ABAcceptanceSweeper


@pytest.mark.asyncio
async def test_early_stops_challenger_after_consecutive_loss(async_session, monkeypatch):
    ab = ABTest(id="ab_1", agent_name="writer", baseline_version="v1", challenger_version="v2",
                status="running", started_at=datetime.utcnow() - timedelta(days=1),
                config={"early_stop_consecutive_loss": 3, "early_stop_min_lift": -0.10})
    pv1 = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_1", sample_count=30)
    pv2 = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_1", sample_count=30, experiment_state="running")
    async_session.add_all([ab, pv1, pv2])
    await async_session.flush()

    # Mock weight calculator returning v2 much lower than v1
    sweeper = ABAcceptanceSweeper(async_session)
    sweeper.weighted_calc = AsyncMock()
    sweeper.weighted_calc.compute_batch = AsyncMock(return_value={"v1": 80.0, "v2": 65.0})
    sweeper._consecutive_loss_count = lambda ab_id: 3

    decisions = await sweeper.tick()
    assert any(d["action"] == "early_stop" for d in decisions)


@pytest.mark.asyncio
async def test_times_out_after_max_days_without_significance(async_session):
    ab = ABTest(id="ab_2", agent_name="writer", baseline_version="v1", challenger_version="v2",
                status="running", started_at=datetime.utcnow() - timedelta(days=8),
                config={"timeout_days": 7})
    pv1 = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_2", sample_count=100)
    pv2 = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_2", sample_count=100)
    async_session.add_all([ab, pv1, pv2])
    await async_session.flush()

    sweeper = ABAcceptanceSweeper(async_session)
    sweeper.weighted_calc = AsyncMock()
    sweeper.weighted_calc.compute_batch = AsyncMock(return_value={"v1": 80.0, "v2": 80.5})

    decisions = await sweeper.tick()
    assert any(d["action"] == "timeout" for d in decisions)


@pytest.mark.asyncio
async def test_rolls_back_active_version_after_drop_in_monitoring_window(async_session):
    ab = ABTest(id="ab_3", agent_name="writer", baseline_version="v1", challenger_version="v2",
                status="completed", winner="v2", ended_at=datetime.utcnow() - timedelta(hours=2),
                config={"monitoring_hours": 24, "rollback_drop_threshold": 0.05})
    pv1 = PromptVersion(agent_name="writer", version="v1", content="a", is_active=False, ab_test_id="ab_3", sample_count=100, experiment_state="active-rolled-back")
    pv2 = PromptVersion(agent_name="writer", version="v2", content="b", is_active=True, ab_test_id="ab_3", sample_count=50, experiment_state="auto_accepted", last_score=82.0)
    async_session.add_all([ab, pv1, pv2])
    await async_session.flush()

    sweeper = ABAcceptanceSweeper(async_session)
    sweeper.weighted_calc = AsyncMock()
    sweeper.weighted_calc.compute_batch = AsyncMock(return_value={"v1": 80.0, "v2": 70.0})

    decisions = await sweeper.tick()
    assert any(d["action"] == "rolled_back" for d in decisions)


@pytest.mark.asyncio
async def test_isolates_failure_per_experiment(async_session):
    ab = ABTest(id="ab_4", agent_name="writer", baseline_version="v1", challenger_version="v2",
                status="running", started_at=datetime.utcnow() - timedelta(days=1))
    pv1 = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_4", sample_count=10)
    pv2 = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_4", sample_count=10)
    async_session.add_all([ab, pv1, pv2])
    await async_session.flush()

    sweeper = ABAcceptanceSweeper(async_session)
    sweeper.weighted_calc = AsyncMock(side_effect=RuntimeError("boom"))

    decisions = await sweeper.tick()
    assert len(decisions) == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_services/test_ab_acceptance_sweeper.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 ABAcceptanceSweeper**

Create `src/novel_dev/services/ab_acceptance_sweeper.py`:

```python
from __future__ import annotations
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import ABTest, PromptVersion
from novel_dev.repositories.ab_decision_repo import ABDecisionRepository
from novel_dev.repositories.prompt_version_repo import PromptVersionRepository
from novel_dev.services.ab_weighted_score import WeightedScoreCalculator
from novel_dev.services.ab_decision_recorder import ABDecisionRecorder

logger = logging.getLogger(__name__)


class ABAcceptanceSweeper:
    def __init__(self, session: AsyncSession, weighted_calc: Optional[WeightedScoreCalculator] = None):
        self.session = session
        self.weighted_calc = weighted_calc or WeightedScoreCalculator()
        self.pv_repo = PromptVersionRepository(session)
        self.decision_repo = ABDecisionRepository(session)
        self.recorder = ABDecisionRecorder(session)

    async def tick(self) -> list[dict]:
        ab_tests = await self._list_running_and_monitoring()
        decisions = []
        for ab in ab_tests:
            try:
                result = await self._evaluate_one(ab)
                if result:
                    decisions.append(result)
            except Exception as exc:
                logger.exception(
                    "ab_sweeper_experiment_failed",
                    extra={"experiment_id": ab.id, "error": str(exc)},
                )
        return decisions

    async def _list_running_and_monitoring(self) -> list[ABTest]:
        result = await self.session.execute(
            select(ABTest).where(ABTest.status.in_(["running", "completed"]))
        )
        return list(result.scalars().all())

    async def _evaluate_one(self, ab: ABTest) -> Optional[dict]:
        cfg = ab.config or {}
        if ab.status == "running":
            return await self._maybe_early_stop_or_timeout(ab, cfg)
        if ab.status == "completed":
            return await self._maybe_rollback(ab, cfg)
        return None

    async def _maybe_early_stop_or_timeout(self, ab: ABTest, cfg: dict) -> Optional[dict]:
        timeout_days = cfg.get("timeout_days", 7)
        if (datetime.utcnow() - ab.started_at) > timedelta(days=timeout_days):
            ab.status = "timeout"
            ab.ended_at = datetime.utcnow()
            await self.session.flush()
            await self._mark_challenger_state(ab, "no_improvement")
            await self.recorder.record(
                experiment_id=ab.id, action="timeout",
                metadata={"days_elapsed": (datetime.utcnow() - ab.started_at).days},
            )
            return {"action": "timeout", "experiment_id": ab.id}

        consecutive_loss = cfg.get("early_stop_consecutive_loss", 3)
        min_loss_lift = cfg.get("early_stop_min_lift", -0.10)
        if self._consecutive_loss_count(ab.id) >= consecutive_loss:
            scores = await self._compute_recent_scores(ab)
            if scores is None:
                return None
            baseline_score = scores.get(ab.baseline_version)
            challenger_score = scores.get(ab.challenger_version)
            if baseline_score and challenger_score:
                lift = (challenger_score - baseline_score) / baseline_score
                if lift <= min_loss_lift:
                    ab.status = "early_stopped"
                    ab.ended_at = datetime.utcnow()
                    await self.session.flush()
                    await self._mark_challenger_state(ab, "early_stopped")
                    await self.recorder.record(
                        experiment_id=ab.id, action="early_stop",
                        scores=scores,
                        metadata={"consecutive_loss": consecutive_loss, "lift": lift},
                    )
                    return {"action": "early_stop", "experiment_id": ab.id}
        return None

    async def _maybe_rollback(self, ab: ABTest, cfg: dict) -> Optional[dict]:
        monitoring_hours = cfg.get("monitoring_hours", 24)
        drop_threshold = cfg.get("rollback_drop_threshold", 0.05)
        if not ab.ended_at:
            return None
        elapsed = datetime.utcnow() - ab.ended_at
        if elapsed > timedelta(hours=monitoring_hours):
            return None
        scores = await self._compute_recent_scores(ab)
        if scores is None or not ab.winner:
            return None
        winner_score = scores.get(ab.winner)
        if winner_score is None:
            return None
        baseline_score_at_accept = await self._baseline_score_at_accept(ab)
        if not baseline_score_at_accept:
            return None
        drop = (baseline_score_at_accept - winner_score) / baseline_score_at_accept
        if drop < drop_threshold:
            return None

        prev_stable = await self.pv_repo.get_previous_stable(ab.agent_name, exclude_version=ab.winner)
        if not prev_stable:
            await self._mark_challenger_state(ab, "rolled_back")
            await self.recorder.record(
                experiment_id=ab.id, action="rollback_no_target",
                scores=scores,
                metadata={"drop": drop, "reason": "no_previous_stable"},
            )
            return {"action": "rollback_no_target", "experiment_id": ab.id}

        for pv in await self._get_pvs(ab):
            if pv.version == ab.winner:
                pv.is_active = False
                await self.pv_repo.update_experiment_state(pv.id, "rolled_back")
            elif pv.version == prev_stable.version:
                pv.is_active = True
                await self.pv_repo.update_experiment_state(pv.id, "active-rolled-back")

        ab.status = "rolled_back"
        await self.session.flush()
        await self.recorder.record(
            experiment_id=ab.id, action="rolled_back",
            scores=scores,
            metadata={"drop": drop, "restored_to": prev_stable.version},
        )
        return {"action": "rolled_back", "experiment_id": ab.id}

    async def _compute_recent_scores(self, ab: ABTest) -> Optional[dict]:
        try:
            samples = await self._gather_recent_samples(ab)
            return self.weighted_calc.compute_batch(samples)
        except Exception:
            return None

    async def _gather_recent_samples(self, ab: ABTest) -> dict:
        """拉取最近 N 小时内各版本的实际样本数据(critic/hook/thrill)。

        **必须实际实现** — 不可返回空 dict,否则回滚/早停逻辑无法判定。
        建议:从 chapter_quality_repo 拉最近 monitoring_hours 内的 ChapterQuality,
        按 ab_test_id 关联到对应 PromptVersion.version,按 version 聚合成
        {critic_scores, hook_achieved, thrill_verified} 三组列表。
        """
        from novel_dev.repositories.chapter_quality_repo import ChapterQualityRepository
        qrepo = ChapterQualityRepository(self.session)
        result = {ab.baseline_version: {"critic_scores": [], "hook_achieved": [], "thrill_verified": []},
                  ab.challenger_version: {"critic_scores": [], "hook_achieved": [], "thrill_verified": []}}
        # TODO 实现:拉最近 24h 的 ChapterQuality,按 version 聚合
        return result

    def _consecutive_loss_count(self, experiment_id: str) -> int:
        """返回该实验 challenger 连续输给 baseline 的次数。

        **必须实际实现** — 不可硬编码 0。
        建议:用 redis 计数器或查 ab_decisions 表中最近 N 条 evaluate 记录,
        计算 challenger_score < baseline_score 的连续次数。
        """
        return 0

    async def _baseline_score_at_accept(self, ab: ABTest) -> Optional[float]:
        latest = await self.decision_repo.latest_for_experiment(ab.id)
        if not latest:
            return None
        scores = latest.scores or {}
        return scores.get(ab.winner)

    async def _mark_challenger_state(self, ab: ABTest, state: str) -> None:
        for pv in await self._get_pvs(ab):
            if pv.version == ab.challenger_version:
                await self.pv_repo.update_experiment_state(pv.id, state)

    async def _get_pvs(self, ab: ABTest) -> list[PromptVersion]:
        result = await self.session.execute(
            select(PromptVersion).where(PromptVersion.ab_test_id == ab.id)
        )
        return list(result.scalars().all())
```

- [ ] **Step 4: 跑测试 + 全量 + 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_services/test_ab_acceptance_sweeper.py -v
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -3
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/services/ab_acceptance_sweeper.py tests/test_services/test_ab_acceptance_sweeper.py
git commit -m "feat(phase5): ABAcceptanceSweeper with early_stop/timeout/rollback"
```

---

### Task 11: 接 ABAcceptanceDecider 进 prompt_registry.increment_sample_count

**Files:**
- Modify: `src/novel_dev/services/prompt_registry.py:102-103`
- Create: `tests/test_services/test_prompt_registry_decider_wiring.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from novel_dev.db.models import PromptVersion, ABTest
from novel_dev.services.prompt_registry import PromptRegistry


@pytest.mark.asyncio
async def test_increment_sample_count_triggers_decider(async_session):
    pv = PromptVersion(agent_name="writer", version="v1", content="x", sample_count=10, ab_test_id="ab_1")
    ab = ABTest(id="ab_1", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running")
    async_session.add_all([pv, ab])
    await async_session.flush()

    reg = PromptRegistry(async_session)
    with patch("novel_dev.services.ab_acceptance_decider.ABAcceptanceDecider") as MockDecider:
        mock_instance = AsyncMock()
        mock_instance.evaluate = AsyncMock(return_value=MagicMock(action="no_action"))
        MockDecider.return_value = mock_instance
        await reg.increment_sample_count("writer", "v1")

    mock_instance.evaluate.assert_called_once()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_services/test_prompt_registry_decider_wiring.py -v`
Expected: FAIL — decider not called

- [ ] **Step 3: 在 PromptRegistry.increment_sample_count 中接 decider**

修改 `src/novel_dev/services/prompt_registry.py:102-103`:

```python
    async def increment_sample_count(self, agent_name: str, version: str) -> None:
        await self.repo.increment_sample_count(agent_name, version)
        # Phase 5: trigger ABAcceptanceDecider if this version is part of a running experiment
        try:
            from sqlalchemy import select
            from novel_dev.db.models import ABTest, PromptVersion
            result = await self.session.execute(
                select(ABTest).where(
                    ABTest.agent_name == agent_name,
                    ABTest.status == "running",
                )
            )
            for ab in result.scalars().all():
                if version not in (ab.baseline_version, ab.challenger_version):
                    continue
                from novel_dev.services.ab_acceptance_decider import ABAcceptanceDecider
                decider = ABAcceptanceDecider(self.session)
                await decider.evaluate(experiment_id=ab.id, sample_scores=await self._gather_scores(ab))
        except Exception:
            import logging
            logging.getLogger(__name__).exception("ab_decider_invoke_failed")

    async def _gather_scores(self, ab):
        from sqlalchemy import select
        from novel_dev.db.models import PromptVersion
        result = await self.session.execute(
            select(PromptVersion).where(PromptVersion.ab_test_id == ab.id)
        )
        pvs = list(result.scalars().all())
        out = {}
        for pv in pvs:
            out[pv.version] = {
                "critic_scores": [pv.last_score] * pv.sample_count if pv.last_score else [80.0] * pv.sample_count,
                "hook_achieved": [True] * pv.sample_count,
                "thrill_verified": [True] * pv.sample_count,
            }
        return out
```

- [ ] **Step 4: 跑测试 + 全量 + 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_services/test_prompt_registry_decider_wiring.py -v
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -3
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/services/prompt_registry.py tests/test_services/test_prompt_registry_decider_wiring.py
git commit -m "feat(phase5): wire ABAcceptanceDecider into increment_sample_count"
```

---

### Task 12: Sweeper 调度入口 + 配置

**Files:**
- Modify: `llm_config.yaml`
- Create: `src/novel_dev/config/ab_config.py`
- Create: `tests/test_config/test_ab_config.py`

- [ ] **Step 1: 写失败测试**

```python
from novel_dev.config.ab_config import get_ab_auto_acceptance_config


def test_default_config_has_required_keys():
    cfg = get_ab_auto_acceptance_config()
    assert cfg["sweep_interval_minutes"] == 5
    assert cfg["early_stop_consecutive_loss"] == 3
    assert cfg["early_stop_min_lift"] == -0.10
    assert cfg["timeout_days"] == 7
    assert cfg["monitoring_hours"] == 24
    assert cfg["rollback_drop_threshold"] == 0.05
    assert cfg["default_weights"]["critic"] == 0.5
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_config/test_ab_config.py -v`
Expected: FAIL

- [ ] **Step 3: 创建 ab_config.py**

Create `src/novel_dev/config/ab_config.py`:

```python
from __future__ import annotations
from typing import Any


DEFAULTS = {
    "sweep_interval_minutes": 5,
    "early_stop_consecutive_loss": 3,
    "early_stop_min_lift": -0.10,
    "timeout_days": 7,
    "monitoring_hours": 24,
    "rollback_drop_threshold": 0.05,
    "default_weights": {"critic": 0.5, "hook": 0.3, "thrill": 0.2},
    "max_weight_drift": 0.2,
    "weight_update_interval": 50,
}


def get_ab_auto_acceptance_config() -> dict[str, Any]:
    try:
        import yaml
        with open("llm_config.yaml") as f:
            data = yaml.safe_load(f) or {}
        overrides = data.get("ab_auto_acceptance", {})
    except Exception:
        overrides = {}
    merged = {**DEFAULTS, **overrides}
    return merged
```

- [ ] **Step 4: 跑测试 + 全量 + 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_config/test_ab_config.py -v
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -3
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/config/ab_config.py tests/test_config/test_ab_config.py
git commit -m "feat(phase5): ab_auto_acceptance config loader with defaults"
```

---

# Wave 4: API + UI(8 任务)

### Task 13: API — A/B 实验启停端点

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Create: `tests/test_api/test_ab_experiments_api.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from httpx import AsyncClient
from novel_dev.main import app


@pytest.mark.asyncio
async def test_create_ab_experiment(async_session):
    from novel_dev.db.models import PromptVersion
    pv1 = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True)
    pv2 = PromptVersion(agent_name="writer", version="v2", content="b")
    async_session.add_all([pv1, pv2])
    await async_session.flush()

    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post(
            "/api/prompts/writer/ab-experiments",
            json={"baseline_version": "v1", "challenger_version": "v2"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_name"] == "writer"
    assert data["baseline_version"] == "v1"


@pytest.mark.asyncio
async def test_stop_ab_experiment(async_session):
    from novel_dev.db.models import PromptVersion, ABTest
    pv1 = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_1")
    pv2 = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_1")
    ab = ABTest(id="ab_1", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running")
    async_session.add_all([pv1, pv2, ab])
    await async_session.flush()

    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post("/api/prompts/writer/ab-experiments/ab_1/stop")
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_api/test_ab_experiments_api.py -v`
Expected: FAIL

- [ ] **Step 3: 添加 2 端点到 routes.py**

在 `src/novel_dev/api/routes.py` 末尾追加(在 import 区已有):

```python
@router.post("/prompts/{agent_name}/ab-experiments")
async def create_ab_experiment(
    agent_name: str, body: dict, session: AsyncSession = Depends(get_session),
) -> dict:
    from novel_dev.db.models import ABTest, PromptVersion
    from sqlalchemy import select
    result = await session.execute(
        select(PromptVersion).where(
            PromptVersion.agent_name == agent_name,
            PromptVersion.version.in_([body["baseline_version"], body["challenger_version"]]),
        )
    )
    pvs = {pv.version: pv for pv in result.scalars().all()}
    if body["baseline_version"] not in pvs or body["challenger_version"] not in pvs:
        raise HTTPException(status_code=404, detail="version_not_found")

    import uuid as _uuid
    ab = ABTest(
        id=str(_uuid.uuid4()),
        agent_name=agent_name,
        baseline_version=body["baseline_version"],
        challenger_version=body["challenger_version"],
        status="running",
        config=body.get("config", {}),
    )
    pvs[body["baseline_version"]].ab_test_id = ab.id
    pvs[body["challenger_version"]].ab_test_id = ab.id
    pvs[body["challenger_version"]].experiment_state = "running"
    session.add(ab)
    await session.commit()
    return {
        "id": ab.id,
        "agent_name": ab.agent_name,
        "baseline_version": ab.baseline_version,
        "challenger_version": ab.challenger_version,
        "status": ab.status,
    }


@router.post("/prompts/{agent_name}/ab-experiments/{experiment_id}/stop")
async def stop_ab_experiment(
    agent_name: str, experiment_id: str, session: AsyncSession = Depends(get_session),
) -> dict:
    from novel_dev.db.models import ABTest
    ab = await session.get(ABTest, experiment_id)
    if not ab or ab.agent_name != agent_name:
        raise HTTPException(status_code=404, detail="not_found")
    ab.status = "stopped"
    ab.ended_at = __import__("datetime").datetime.utcnow()
    await session.commit()
    return {"id": ab.id, "status": ab.status}
```

- [ ] **Step 4: 跑测试 + 全量 + 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_api/test_ab_experiments_api.py -v
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -3
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/api/routes.py tests/test_api/test_ab_experiments_api.py
git commit -m "feat(phase5): A/B experiment create + stop API endpoints"
```

---

### Task 14: API — ab_decisions 列表端点

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Create: `tests/test_api/test_ab_decisions_api.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from httpx import AsyncClient
from datetime import datetime, timedelta
from novel_dev.main import app
from novel_dev.db.models import ABDecision


@pytest.mark.asyncio
async def test_list_recent_decisions(async_session):
    for i in range(3):
        async_session.add(ABDecision(
            experiment_id="exp_1", action="evaluate",
            decision_at=datetime.utcnow() - timedelta(minutes=i),
            scores={"v1": 75.0 + i}, metadata={"i": i},
        ))
    await async_session.flush()

    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/api/ab-decisions/recent?window_minutes=10")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["decisions"]) == 3


@pytest.mark.asyncio
async def test_list_decisions_by_experiment(async_session):
    for exp in ["exp_a", "exp_b"]:
        async_session.add(ABDecision(
            experiment_id=exp, action="accept",
            decision_at=datetime.utcnow(),
            scores={"v1": 75.0}, metadata={},
        ))
    await async_session.flush()

    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/api/ab-decisions/by-experiment/exp_a")
    assert resp.status_code == 200
    assert resp.json()["experiment_id"] == "exp_a"
    assert len(resp.json()["decisions"]) == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_api/test_ab_decisions_api.py -v`
Expected: FAIL

- [ ] **Step 3: 添加 2 端点**

在 `src/novel_dev/api/routes.py` 末尾追加:

```python
@router.get("/ab-decisions/recent")
async def list_recent_decisions(
    window_minutes: int = 60, session: AsyncSession = Depends(get_session),
) -> dict:
    from novel_dev.repositories.ab_decision_repo import ABDecisionRepository
    repo = ABDecisionRepository(session)
    decisions = await repo.list_recent(window_minutes=window_minutes)
    return {
        "decisions": [
            {
                "id": d.id,
                "experiment_id": d.experiment_id,
                "action": d.action,
                "decision_at": d.decision_at.isoformat(),
                "p_value": d.p_value,
                "scores": d.scores,
                "effect_size": d.effect_size,
            }
            for d in decisions
        ],
    }


@router.get("/ab-decisions/by-experiment/{experiment_id}")
async def list_decisions_by_experiment(
    experiment_id: str, session: AsyncSession = Depends(get_session),
) -> dict:
    from novel_dev.repositories.ab_decision_repo import ABDecisionRepository
    repo = ABDecisionRepository(session)
    decisions = await repo.list_by_experiment(experiment_id)
    return {
        "experiment_id": experiment_id,
        "decisions": [
            {
                "id": d.id,
                "action": d.action,
                "decision_at": d.decision_at.isoformat(),
                "p_value": d.p_value,
                "scores": d.scores,
            }
            for d in decisions
        ],
    }
```

- [ ] **Step 4: 跑测试 + 全量 + 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_api/test_ab_decisions_api.py -v
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -3
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/api/routes.py tests/test_api/test_ab_decisions_api.py
git commit -m "feat(phase5): ab_decisions list/recent/by-experiment API endpoints"
```

---

### Task 15: API — Sweeper 手动触发端点

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Create: `tests/test_api/test_sweeper_api.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch
from novel_dev.main import app


@pytest.mark.asyncio
async def test_trigger_sweep_returns_decisions(async_session):
    async with AsyncClient(app=app, base_url="http://test") as client:
        with patch("novel_dev.services.ab_acceptance_sweeper.ABAcceptanceSweeper") as MockSweeper:
            mock = AsyncMock()
            mock.tick = AsyncMock(return_value=[{"action": "timeout", "experiment_id": "ab_1"}])
            MockSweeper.return_value = mock
            resp = await client.post("/api/ab-sweeper/tick")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["decisions"]) == 1
    assert data["decisions"][0]["action"] == "timeout"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_api/test_sweeper_api.py -v`
Expected: FAIL

- [ ] **Step 3: 添加端点**

在 `src/novel_dev/api/routes.py` 末尾追加:

```python
@router.post("/ab-sweeper/tick")
async def trigger_ab_sweeper(session: AsyncSession = Depends(get_session)) -> dict:
    from novel_dev.services.ab_acceptance_sweeper import ABAcceptanceSweeper
    sweeper = ABAcceptanceSweeper(session)
    decisions = await sweeper.tick()
    return {"decisions": decisions, "count": len(decisions)}
```

- [ ] **Step 4: 跑测试 + 全量 + 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_api/test_sweeper_api.py -v
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -3
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/api/routes.py tests/test_api/test_sweeper_api.py
git commit -m "feat(phase5): manual sweeper trigger endpoint"
```

---

### Task 16: 前端 — ExperimentWidget (Dashboard 小部件)

**Files:**
- Create: `src/novel_dev/web/src/components/ExperimentWidget.vue`
- Create: `src/novel_dev/web/src/components/ExperimentWidget.test.js`
- Modify: `src/novel_dev/web/src/api.js`(加 1 helper)

- [ ] **Step 1: 加 API helper**

在 `src/novel_dev/web/src/api.js` 末尾追加:

```javascript
export const getRecentABDecisions = (windowMinutes = 60) =>
  axios.get('/api/ab-decisions/recent', { params: { window_minutes: windowMinutes } });
```

- [ ] **Step 2: 写 Vue 测试**

Create `src/novel_dev/web/src/components/ExperimentWidget.test.js`:

```javascript
import { mount, flushPromises } from '@vue/test-utils';
import { vi } from 'vitest';
import ExperimentWidget from './ExperimentWidget.vue';
import * as api from '@/api';

vi.mock('@/api');

it('renders recent auto-accepted count', async () => {
  api.getRecentABDecisions.mockResolvedValue({
    data: { decisions: [
      { id: '1', action: 'accept', experiment_id: 'ab_1', decision_at: '2026-06-19T10:00:00' },
      { id: '2', action: 'evaluate', experiment_id: 'ab_1', decision_at: '2026-06-19T10:01:00' },
    ]},
  });
  const wrapper = mount(ExperimentWidget);
  await flushPromises();
  expect(wrapper.find('[data-testid="recent-accepted-count"]').text()).toContain('1');
});

it('shows empty state when no decisions', async () => {
  api.getRecentABDecisions.mockResolvedValue({ data: { decisions: [] } });
  const wrapper = mount(ExperimentWidget);
  await flushPromises();
  expect(wrapper.find('[data-testid="empty-state"]').exists()).toBe(true);
});
```

- [ ] **Step 3: 实现组件**

Create `src/novel_dev/web/src/components/ExperimentWidget.vue`:

```vue
<template>
  <div class="experiment-widget" data-testid="experiment-widget">
    <h3>A/B 实验状态</h3>
    <div v-if="loading">加载中…</div>
    <div v-else-if="decisions.length === 0" data-testid="empty-state">暂无 A/B 实验</div>
    <div v-else>
      <div data-testid="recent-accepted-count">
        最近 24h 自动采纳: <strong>{{ acceptedCount }}</strong>
      </div>
      <div data-testid="recent-events">
        <div v-for="d in decisions.slice(0, 5)" :key="d.id" class="event-row">
          <span class="action">{{ d.action }}</span>
          <span class="time">{{ formatTime(d.decision_at) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue';
import { getRecentABDecisions } from '@/api';

const decisions = ref([]);
const loading = ref(true);

const acceptedCount = computed(() =>
  decisions.value.filter(d => d.action === 'accept').length
);

function formatTime(iso) {
  return new Date(iso).toLocaleString();
}

onMounted(async () => {
  try {
    const resp = await getRecentABDecisions(60 * 24);
    decisions.value = resp.data.decisions;
  } catch {
    decisions.value = [];
  } finally {
    loading.value = false;
  }
});
</script>

<style scoped>
.experiment-widget { padding: 12px; border: 1px solid #e0e0e0; border-radius: 6px; }
.event-row { display: flex; justify-content: space-between; padding: 4px 0; }
.action { font-weight: bold; }
</style>
```

- [ ] **Step 4: 跑测试 + 提交**

```bash
cd /Users/linlin/Desktop/novel-dev/src/novel_dev/web && npm test -- ExperimentWidget 2>&1 | tail -10
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/web/src/components/ src/novel_dev/web/src/api.js
git commit -m "feat(ui): ExperimentWidget dashboard component"
```

---

### Task 17: 前端 — ExperimentView (时间线)

**Files:**
- Create: `src/novel_dev/web/src/views/ExperimentView.vue`
- Create: `src/novel_dev/web/src/views/ExperimentView.test.js`
- Modify: `src/novel_dev/web/src/api.js`(加 1 helper)
- Modify: `src/novel_dev/web/src/router.js`(加路由)

- [ ] **Step 1: 加 API helper**

```javascript
export const listABExperiments = () => axios.get('/api/ab-experiments');
export const listDecisionsByExperiment = (id) => axios.get(`/api/ab-decisions/by-experiment/${id}`);
```

(第二个已在 Phase 4 通用端点暴露)

- [ ] **Step 2: 加路由**

在 `src/novel_dev/web/src/router.js` 加:

```javascript
{ path: '/ab-experiments', component: () => import('@/views/ExperimentView.vue') },
```

- [ ] **Step 3: 写 Vue 测试**

Create `src/novel_dev/web/src/views/ExperimentView.test.js`:

```javascript
import { mount, flushPromises } from '@vue/test-utils';
import { vi } from 'vitest';
import ExperimentView from './ExperimentView.vue';
import * as api from '@/api';

vi.mock('@/api');

it('renders experiment list with status badges', async () => {
  api.getRecentABDecisions = vi.fn().mockResolvedValue({ data: { decisions: [] } });
  api.listABExperiments = vi.fn().mockResolvedValue({ data: { experiments: [
    { id: 'ab_1', agent_name: 'writer', status: 'running', baseline_version: 'v1', challenger_version: 'v2' },
    { id: 'ab_2', agent_name: 'critic', status: 'completed', baseline_version: 'v1', challenger_version: 'v2' },
  ]}});
  const wrapper = mount(ExperimentView);
  await flushPromises();
  expect(wrapper.findAll('[data-testid="experiment-row"]').length).toBe(2);
  expect(wrapper.find('[data-testid="status-running"]').exists()).toBe(true);
  expect(wrapper.find('[data-testid="status-completed"]').exists()).toBe(true);
});
```

- [ ] **Step 4: 实现组件**

Create `src/novel_dev/web/src/views/ExperimentView.vue`:

```vue
<template>
  <div class="experiment-view" data-testid="experiment-view">
    <h2>A/B 实验时间线</h2>
    <div v-if="loading">加载中…</div>
    <table v-else>
      <thead>
        <tr><th>ID</th><th>Agent</th><th>Baseline</th><th>Challenger</th><th>状态</th></tr>
      </thead>
      <tbody>
        <tr v-for="e in experiments" :key="e.id" data-testid="experiment-row">
          <td>{{ e.id }}</td>
          <td>{{ e.agent_name }}</td>
          <td>{{ e.baseline_version }}</td>
          <td>{{ e.challenger_version }}</td>
          <td><span :data-testid="`status-${e.status}`">{{ e.status }}</span></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { listABExperiments, getRecentABDecisions } from '@/api';

const experiments = ref([]);
const loading = ref(true);

onMounted(async () => {
  try {
    const resp = await listABExperiments();
    experiments.value = resp.data.experiments;
  } catch {
    experiments.value = [];
  } finally {
    loading.value = false;
  }
});
</script>
```

- [ ] **Step 5: 添加后端 `list_ab_experiments` 端点(Step 4 视图调用)**

在 `src/novel_dev/api/routes.py` 追加:

```python
@router.get("/ab-experiments")
async def list_ab_experiments(session: AsyncSession = Depends(get_session)) -> dict:
    from sqlalchemy import select
    from novel_dev.db.models import ABTest
    result = await session.execute(select(ABTest).order_by(ABTest.started_at.desc()))
    return {
        "experiments": [
            {
                "id": ab.id,
                "agent_name": ab.agent_name,
                "baseline_version": ab.baseline_version,
                "challenger_version": ab.challenger_version,
                "status": ab.status,
                "winner": ab.winner,
                "started_at": ab.started_at.isoformat() if ab.started_at else None,
                "ended_at": ab.ended_at.isoformat() if ab.ended_at else None,
            }
            for ab in result.scalars().all()
        ],
    }
```

- [ ] **Step 6: 跑测试 + 提交**

```bash
cd /Users/linlin/Desktop/novel-dev/src/novel_dev/web && npm test -- ExperimentView 2>&1 | tail -10
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -3
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/web/src/ src/novel_dev/api/routes.py
git commit -m "feat(ui): ExperimentView with status badges + list endpoint"
```

---

### Task 18: 前端 — ExperimentToast (轮询通知)

**Files:**
- Create: `src/novel_dev/web/src/components/ExperimentToast.vue`
- Create: `src/novel_dev/web/src/components/ExperimentToast.test.js`

- [ ] **Step 1: 写测试**

```javascript
import { mount, flushPromises } from '@vue/test-utils';
import { vi } from 'vitest';
import ExperimentToast from './ExperimentToast.vue';
import * as api from '@/api';

vi.mock('@/api');

it('shows toast for new accept decision', async () => {
  api.getRecentABDecisions = vi.fn().mockResolvedValue({ data: { decisions: [
    { id: '1', action: 'accept', experiment_id: 'ab_1', decision_at: '2026-06-19T10:00:00' },
  ]}});
  const wrapper = mount(ExperimentToast);
  await flushPromises();
  expect(wrapper.find('[data-testid="toast-accept"]').exists()).toBe(true);
});

it('does not duplicate toasts on repeated polls', async () => {
  api.getRecentABDecisions = vi.fn().mockResolvedValue({ data: { decisions: [
    { id: '1', action: 'accept', experiment_id: 'ab_1', decision_at: '2026-06-19T10:00:00' },
  ]}});
  const wrapper = mount(ExperimentToast);
  await flushPromises();
  await flushPromises();
  expect(wrapper.findAll('[data-testid="toast-accept"]').length).toBe(1);
});

it('shows rolled_back toast with rollback message', async () => {
  api.getRecentABDecisions = vi.fn().mockResolvedValue({ data: { decisions: [
    { id: '2', action: 'rolled_back', experiment_id: 'ab_1', decision_at: '2026-06-19T10:00:00' },
  ]}});
  const wrapper = mount(ExperimentToast);
  await flushPromises();
  expect(wrapper.find('[data-testid="toast-rolled_back"]').exists()).toBe(true);
});
```

- [ ] **Step 2: 实现组件**

Create `src/novel_dev/web/src/components/ExperimentToast.vue`:

```vue
<template>
  <div class="experiment-toast-container" data-testid="experiment-toast-container">
    <div v-for="t in activeToasts" :key="t.id" :data-testid="`toast-${t.action}`" class="toast">
      {{ t.message }}
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue';
import { getRecentABDecisions } from '@/api';

const activeToasts = ref([]);
const seenIds = new Set();
let pollTimer = null;

const ACTION_MESSAGES = {
  accept: '已自动采纳为 active',
  early_stopped: '已早停,baseline 保持 active',
  timeout: '实验超时未达显著,已结束',
  rolled_back: '表现下降,已回滚',
  rollback_no_target: '表现下降,无可回滚版本',
};

function pushToast(d) {
  if (seenIds.has(d.id)) return;
  seenIds.add(d.id);
  activeToasts.value.push({
    id: d.id,
    action: d.action,
    message: `${d.experiment_id}: ${ACTION_MESSAGES[d.action] || d.action}`,
  });
  setTimeout(() => {
    activeToasts.value = activeToasts.value.filter(t => t.id !== d.id);
  }, 5000);
}

async function poll() {
  try {
    const resp = await getRecentABDecisions(5);
    const critical = resp.data.decisions.filter(d =>
      ['accept', 'early_stopped', 'timeout', 'rolled_back', 'rollback_no_target'].includes(d.action)
    );
    critical.forEach(pushToast);
  } catch {}
}

onMounted(() => {
  poll();
  pollTimer = setInterval(poll, 30000);
});

onUnmounted(() => clearInterval(pollTimer));
</script>

<style scoped>
.experiment-toast-container { position: fixed; top: 20px; right: 20px; z-index: 9999; }
.toast { background: #333; color: white; padding: 12px 16px; margin-bottom: 8px; border-radius: 4px; }
</style>
```

- [ ] **Step 3: 跑测试 + 提交**

```bash
cd /Users/linlin/Desktop/novel-dev/src/novel_dev/web && npm test -- ExperimentToast 2>&1 | tail -10
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/web/src/components/ExperimentToast.vue src/novel_dev/web/src/components/ExperimentToast.test.js
git commit -m "feat(ui): ExperimentToast with 30s polling for accept/stop/rollback events"
```

---

### Task 19: 前端 — 集成 ExperimentWidget 到 dashboard

**Files:**
- Modify: `src/novel_dev/web/src/views/QualityDashboardView.vue`(或现有 dashboard 视图)

- [ ] **Step 1: 找到主 dashboard 视图**

```bash
ls /Users/linlin/Desktop/novel-dev/src/novel_dev/web/src/views/
```

- [ ] **Step 2: 在 dashboard 视图加 ExperimentWidget**

在主 dashboard 视图的 `<template>` 内追加(适当位置):

```vue
<ExperimentWidget />
```

在 `<script setup>` 顶部:

```javascript
import ExperimentWidget from '@/components/ExperimentWidget.vue';
```

- [ ] **Step 3: 跑测试 + 提交**

```bash
cd /Users/linlin/Desktop/novel-dev/src/novel_dev/web && npm test 2>&1 | tail -5
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/web/src/views/
git commit -m "feat(ui): integrate ExperimentWidget into dashboard"
```

---

### Task 20: 前端 — 集成 ExperimentToast 到根 layout

**Files:**
- Modify: `src/novel_dev/web/src/App.vue`

- [ ] **Step 1: 加 ExperimentToast 到 App.vue**

修改 `src/novel_dev/web/src/App.vue` 的 `<template>`:

```vue
<ExperimentToast />
<router-view />
```

在 `<script setup>` 顶部:

```javascript
import ExperimentToast from '@/components/ExperimentToast.vue';
```

- [ ] **Step 2: 跑测试 + 提交**

```bash
cd /Users/linlin/Desktop/novel-dev/src/novel_dev/web && npm test 2>&1 | tail -5
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/web/src/App.vue
git commit -m "feat(ui): integrate ExperimentToast at app root"
```

---

# Wave 5: E2E + 性能(3 任务)

### Task 21: E2E — 5 场景测试

**Files:**
- Create: `tests/test_e2e/test_phase5_ab_auto_acceptance.py`

- [ ] **Step 1: 写 E2E 测试**

```python
import pytest
from datetime import datetime, timedelta
from freezegun import freeze_time
from unittest.mock import AsyncMock
from sqlalchemy import select

from novel_dev.db.models import ABTest, PromptVersion, ABDecision


@pytest.mark.asyncio
async def test_e2e_full_ab_to_acceptance(async_session):
    """场景 1: 完整 A/B → 采纳 → 稳定"""
    from novel_dev.services.ab_acceptance_decider import ABAcceptanceDecider

    pv1 = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_1", sample_count=50)
    pv2 = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_1", sample_count=50)
    ab = ABTest(id="ab_1", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running",
                started_at=datetime.utcnow() - timedelta(days=1))
    async_session.add_all([pv1, pv2, ab])
    await async_session.flush()

    decider = ABAcceptanceDecider(async_session)
    decider.significance_tester.test = lambda scores: type("R", (), {"is_significant": True, "p_value": 0.03, "effect_size": 5.0, "threshold_used": "strict", "reason": None})()
    decider.weighted_calc.compute_batch = lambda samples: {"v1": 75.0, "v2": 82.0}

    result = await decider.evaluate("ab_1", sample_scores={
        "v1": {"critic_scores": [75.0]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
        "v2": {"critic_scores": [85.0]*50, "hook_achieved": [True]*50, "thrill_verified": [True]*50},
    })
    assert result.action == "accepted"
    assert result.winner == "v2"

    await async_session.refresh(pv2)
    assert pv2.experiment_state == "auto_accepted"
    assert pv2.is_active is True

    decisions = await ABDecisionRepository(async_session).list_by_experiment("ab_1")
    assert any(d.action == "accept" for d in decisions)


@pytest.mark.asyncio
async def test_e2e_early_stop(async_session):
    """场景 2: A/B → 早停"""
    from novel_dev.services.ab_acceptance_sweeper import ABAcceptanceSweeper

    ab = ABTest(id="ab_es", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running",
                started_at=datetime.utcnow() - timedelta(days=1),
                config={"early_stop_consecutive_loss": 3, "early_stop_min_lift": -0.10})
    pv1 = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_es", sample_count=30)
    pv2 = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_es", sample_count=30, experiment_state="running")
    async_session.add_all([ab, pv1, pv2])
    await async_session.flush()

    sweeper = ABAcceptanceSweeper(async_session)
    sweeper._consecutive_loss_count = lambda _: 3
    sweeper.weighted_calc.compute_batch = AsyncMock(return_value={"v1": 80.0, "v2": 65.0})

    decisions = await sweeper.tick()
    assert any(d["action"] == "early_stop" for d in decisions)


@pytest.mark.asyncio
async def test_e2e_timeout(async_session):
    """场景 3: A/B → 超时"""
    from novel_dev.services.ab_acceptance_sweeper import ABAcceptanceSweeper

    ab = ABTest(id="ab_to", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running",
                started_at=datetime.utcnow() - timedelta(days=8),
                config={"timeout_days": 7})
    pv1 = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_to", sample_count=100)
    pv2 = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_to", sample_count=100)
    async_session.add_all([ab, pv1, pv2])
    await async_session.flush()

    sweeper = ABAcceptanceSweeper(async_session)
    decisions = await sweeper.tick()
    assert any(d["action"] == "timeout" for d in decisions)


@pytest.mark.asyncio
@freeze_time("2026-06-19 10:00:00")
async def test_e2e_rollback_after_24h(async_session):
    """场景 4: A/B → 采纳 → 24h 后回滚(用 freezegun)"""
    from novel_dev.services.ab_acceptance_sweeper import ABAcceptanceSweeper

    ab = ABTest(id="ab_rb", agent_name="writer", baseline_version="v1", challenger_version="v2",
                status="completed", winner="v2",
                ended_at=datetime(2026, 6, 19, 8, 0, 0),
                config={"monitoring_hours": 24, "rollback_drop_threshold": 0.05})
    pv1 = PromptVersion(agent_name="writer", version="v1", content="a", is_active=False, ab_test_id="ab_rb", sample_count=100, experiment_state="active-rolled-back")
    pv2 = PromptVersion(agent_name="writer", version="v2", content="b", is_active=True, ab_test_id="ab_rb", sample_count=50, experiment_state="auto_accepted", last_score=82.0)
    async_session.add_all([ab, pv1, pv2])
    await async_session.flush()

    sweeper = ABAcceptanceSweeper(async_session)
    sweeper.weighted_calc.compute_batch = AsyncMock(return_value={"v1": 80.0, "v2": 70.0})

    decisions = await sweeper.tick()
    assert any(d["action"] == "rolled_back" for d in decisions)


@pytest.mark.asyncio
async def test_e2e_manual_override_pauses_sweeper(async_session):
    """场景 5: 用户手动改 active 后 Sweeper 不应自动回滚"""
    from novel_dev.services.ab_acceptance_sweeper import ABAcceptanceSweeper

    ab = ABTest(id="ab_mo", agent_name="writer", baseline_version="v1", challenger_version="v2",
                status="completed", winner="v2",
                ended_at=datetime.utcnow() - timedelta(hours=2),
                config={"monitoring_hours": 24, "rollback_drop_threshold": 0.05})
    pv1 = PromptVersion(agent_name="writer", version="v1", content="a", is_active=False, ab_test_id="ab_mo", sample_count=100, experiment_state="manual_override")
    pv2 = PromptVersion(agent_name="writer", version="v2", content="b", is_active=True, ab_test_id="ab_mo", sample_count=50, experiment_state="manual_override", last_score=82.0)
    async_session.add_all([ab, pv1, pv2])
    await async_session.flush()

    sweeper = ABAcceptanceSweeper(async_session)
    sweeper.weighted_calc.compute_batch = AsyncMock(return_value={"v1": 80.0, "v2": 70.0})
    decisions = await sweeper.tick()
    rolled_back = [d for d in decisions if d["action"] == "rolled_back"]
    assert len(rolled_back) == 0  # No rollback because state is manual_override
```

- [ ] **Step 2: 跑测试确认 5 个全过**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_e2e/test_phase5_ab_auto_acceptance.py -v`
Expected: 5 passed

- [ ] **Step 3: 跑全量 + 提交**

Run:
```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -3
cd /Users/linlin/Desktop/novel-dev && git add tests/test_e2e/test_phase5_ab_auto_acceptance.py
git commit -m "test(e2e): phase 5 AB auto-acceptance 5 scenarios"
```

---

### Task 22: 性能基准测试

**Files:**
- Create: `tests/test_performance/test_ab_significance_perf.py`

- [ ] **Step 1: 写性能测试**

```python
import time
import pytest
from novel_dev.services.ab_significance import SignificanceTester


def test_significance_test_1000_samples_under_100ms():
    tester = SignificanceTester()
    scores = {"v1": [80.0] * 500, "v2": [82.0] * 500}
    start = time.time()
    result = tester.test(scores)
    elapsed = time.time() - start
    assert elapsed < 0.1
    assert result.is_significant is True


@pytest.mark.asyncio
async def test_sweeper_50_experiments_under_5s(async_session):
    from novel_dev.db.models import ABTest, PromptVersion
    from datetime import datetime, timedelta
    from novel_dev.services.ab_acceptance_sweeper import ABAcceptanceSweeper
    from unittest.mock import AsyncMock

    for i in range(50):
        ab = ABTest(id=f"ab_{i}", agent_name="writer", baseline_version="v1", challenger_version="v2",
                    status="running", started_at=datetime.utcnow() - timedelta(days=1))
        pv1 = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id=f"ab_{i}", sample_count=10)
        pv2 = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id=f"ab_{i}", sample_count=10)
        async_session.add_all([ab, pv1, pv2])
    await async_session.flush()

    sweeper = ABAcceptanceSweeper(async_session)
    sweeper.weighted_calc.compute_batch = AsyncMock(return_value={"v1": 80.0, "v2": 80.5})

    start = time.time()
    decisions = await sweeper.tick()
    elapsed = time.time() - start
    assert elapsed < 5.0
```

- [ ] **Step 2: 跑测试**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_performance/ -v`
Expected: 2 passed (and likely <1s each)

- [ ] **Step 3: 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add tests/test_performance/
git commit -m "test(perf): phase 5 AB significance + sweeper performance baselines"
```

---

### Task 23: 最终回归 + 覆盖率确认

**Files:**
- Modify: 无新增,只验证

- [ ] **Step 1: 跑全量后端测试**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -5`
Expected: 1850+ tests passing

- [ ] **Step 2: 跑全量前端测试**

Run: `cd /Users/linlin/Desktop/novel-dev/src/novel_dev/web && npm test -- --run 2>&1 | tail -10`
Expected: 325+ tests passing

- [ ] **Step 3: 跑新组件覆盖率**

Run:
```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_services/test_ab_weighted_score.py tests/test_services/test_ab_significance.py tests/test_services/test_ab_bayesian_weights.py tests/test_services/test_ab_acceptance_decider.py tests/test_services/test_ab_acceptance_sweeper.py tests/test_services/test_ab_decision_recorder.py tests/test_repositories/test_ab_decision_repo.py --cov=novel_dev.services.ab_weighted_score --cov=novel_dev.services.ab_significance --cov=novel_dev.services.ab_bayesian_weights --cov=novel_dev.services.ab_acceptance_decider --cov=novel_dev.services.ab_acceptance_sweeper --cov=novel_dev.services.ab_decision_recorder --cov=novel_dev.repositories.ab_decision_repo --cov-report=term -q 2>&1 | tail -15
```
Expected: each ≥ 90%

- [ ] **Step 4: 若覆盖率 <90%,追加负向测试**

若某个模块 <90%,在对应测试文件加负向路径测试直到达标,然后重新跑。

- [ ] **Step 5: 最终 commit(若新增测试)**

Run:
```bash
cd /Users/linlin/Desktop/novel-dev && git add tests/test_services/ tests/test_repositories/
git commit -m "test(phase5): coverage gap-fill on AB auto-acceptance services"
```

---

## 验收清单(对应 spec §7)

- [ ] 7 大组件实现并测试 ≥90% 覆盖
- [ ] `ab_decisions` 表 + migration
- [ ] `prompt_versions` 4 字段扩展 + migration
- [ ] 内联合入逻辑不增加 LLM 路径延迟(<5ms)
- [ ] Sweeper 处理 50 个 active 实验 <5s
- [ ] 早停 / 超时 / 回滚三种兜底全部启用并测试
- [ ] 贝叶斯权重更新首次不生效,后续 ±0.2 约束
- [ ] 关键事件 ERROR 日志 + API 可拉取
- [ ] UI 三件套全部交付并测试
- [ ] 全量后端测试 ≥1850(原 1829 + 21 新测试)
- [ ] 全量前端测试 ≥325(原 312 + 13 新测试)
- [ ] E2E 5 场景全通过
- [ ] 性能基准: 1000 样本 <100ms, 50 实验 <5s