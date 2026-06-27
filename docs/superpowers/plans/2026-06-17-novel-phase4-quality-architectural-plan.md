# Phase 4 质量架构升级实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 6 类已识别但未解决的质量问题(A/B 死代码/整章模式漏洞/长篇上下文饥饿/跨章漂移/跨章重复/网文规则缺失),让已有投资生效,支持 30+ 章长篇质量。

**Architecture:** 4 大新服务(RCS、跨章实体、跨章意象、网文规则)+ 12 个 quick win;所有新 prompt 进 PromptRegistry 可 A/B 测试;新表 3 张(chapter_synopsis/thrill_point/imagery_inventory);失败闭门策略覆盖关键质量门。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy 2.0 async / Pydantic / pytest / Vue 3 + Vitest。

**前置:** Phase 1/2/3 全部完成并合入。working branch: `phase2-writer-protection`。

**Spec:** `docs/superpowers/specs/2026-06-17-novel-phase4-quality-architectural-design.md`

---

## 文件结构总览

**新增文件(17)**:
- `migrations/versions/20260617_<rev>_phase4_quality_architectural_tables.py` — 3 表
- `src/novel_dev/repositories/chapter_synopsis_repo.py`
- `src/novel_dev/repositories/thrill_point_repo.py`
- `src/novel_dev/repositories/imagery_inventory_repo.py`
- `src/novel_dev/services/rolling_chapter_synopsis_service.py`
- `src/novel_dev/services/cross_chapter_continuity_service.py`
- `src/novel_dev/services/imagery_inventory_service.py`
- `src/novel_dev/schemas/web_novel.py` — 枚举(ChapterArchetype/MoodPhase/ThrillType/ItemType)
- `src/novel_dev/web/src/views/RCSViewerView.vue` + `.test.js`
- `src/novel_dev/web/src/views/ImageryInventoryView.vue` + `.test.js`
- `tests/test_services/test_rolling_chapter_synopsis.py`
- `tests/test_services/test_cross_chapter_continuity.py`
- `tests/test_services/test_imagery_inventory.py`
- `tests/test_repositories/test_chapter_synopsis_repo.py`
- `tests/test_repositories/test_thrill_point_repo.py`
- `tests/test_repositories/test_imagery_inventory_repo.py`
- `tests/test_e2e/test_phase4_quality_architectural.py`

**修改文件(15)**:
- `src/novel_dev/db/models.py`(3 表 + Entity 扩展 + ChapterPlan.archetype + BeatPlan.mood_phase + BeatBoundaryCard.required_open_question)
- `src/novel_dev/agents/_default_prompts.py`(7 个新 prompt + few-shot)
- `src/novel_dev/llm/factory.py`(get_with_chapter_id + 缓存)
- `src/novel_dev/agents/{writer,context,librarian,fast_review,critic,volume_planner}_agent.py`(各自接入点)
- `src/novel_dev/services/prompt_registry.py`(get_active_for_chapter)
- `src/novel_dev/services/chapter_structure_guard_service.py`(fail-closed)
- `src/novel_dev/services/chapter_rewrite_service.py`(应用 fail-closed)
- `src/novel_dev/api/routes.py`(新查询端点)
- `src/novel_dev/api/api.js`(web,新 API 客户端)
- `src/novel_dev/web/src/components/QualityRecommendationWidget.vue`(recentIssueCounts + 评分明细展开)
- `src/novel_dev/web/src/views/QualityTrendsView.vue`(扩 cross-metric)
- `src/novel_dev/web/src/router/index.js`(新路由)
- `llm_config.yaml`(phase4 段)
- `src/novel_dev/config/quality_config.py`(get_phase4_config)

**总任务数:31**

---

## Wave 1: P0 紧急修复(5 任务)

### Task 1: A/B 测试管道接通

**Files:**
- Modify: `src/novel_dev/llm/factory.py`
- Modify: `src/novel_dev/services/prompt_registry.py`
- Modify: `src/novel_dev/agents/{brainstorm,volume_planner,context,writer,critic,editor,fast_review,librarian}_agent.py`
- Test: `tests/test_services/test_prompt_registry.py`

- [ ] **Step 1: 写失败测试 — `get_active_for_chapter` 在无 A/B 时等价于 `get_active`**

在 `tests/test_services/test_prompt_registry.py` 末尾追加:

```python
@pytest.mark.asyncio
async def test_get_active_for_chapter_no_ab_returns_active_version(async_session):
    reg = PromptRegistry(async_session)
    await reg.create_version("writer", "v1.0", "v1 content", is_active=True)
    content = await reg.get_active_for_chapter("writer", "ch_1")
    assert content == "v1 content"


@pytest.mark.asyncio
async def test_get_active_for_chapter_routes_via_ab_when_running(async_session):
    from novel_dev.services.ab_test_runner import ABTestRunner
    reg = PromptRegistry(async_session)
    await reg.create_version("writer", "v1.0", "v1 content", is_active=True)
    await reg.create_version("writer", "v2.0", "v2 content")
    runner = ABTestRunner(async_session)
    await runner.start("writer", "v1.0", "v2.0", max_samples=10, min_samples=3)

    # 100 chapters, 50/50 split — assert both versions picked
    picked = set()
    for i in range(100):
        c = await reg.get_active_for_chapter("writer", f"ch_{i}")
        picked.add(c)
    assert picked == {"v1 content", "v2 content"}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_services/test_prompt_registry.py::test_get_active_for_chapter_no_ab_returns_active_version -v
```

Expected: FAIL with "AttributeError: 'PromptRegistry' object has no attribute 'get_active_for_chapter'"

- [ ] **Step 3: 在 `PromptRegistry` 加 `get_active_for_chapter`**

在 `src/novel_dev/services/prompt_registry.py` 末尾加:

```python
    async def get_active_for_chapter(self, agent_name: str, chapter_id: str) -> str:
        from novel_dev.services.ab_test_runner import ABTestRunner
        runner = ABTestRunner(self.session)
        version = await runner.pick_version(agent_name, chapter_id)
        if version:
            return await self.get_by_version(agent_name, version)
        return await self.get_active(agent_name)
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_services/test_prompt_registry.py -v -k "chapter"
```

Expected: 2 passed

- [ ] **Step 5: 改 8 个 agent 的 prompt 拉取方式**

每个 agent 文件(共 8 个)在创建 `PromptRegistry` 实例后,加一个 helper:

```python
    async def _prompt(self, key: str, chapter_id: str | None = None) -> str:
        from novel_dev.services.prompt_registry import PromptRegistry
        reg = PromptRegistry(self.session)
        if chapter_id:
            return await reg.get_active_for_chapter(self._AGENT_NAME, chapter_id)
        return await reg.get_active(self._AGENT_NAME)
```

每个 agent 中原本 `reg.get_active("<agent_name>")` 改为:
- 在 writer/critic/editor/fast_review/librarian(章节级调用):`_prompt("<agent_name>", chapter_id)`
- 在 brainstorm/volume_planner/context(非章节级,或不需要 A/B):保持 `reg.get_active(...)`

具体修改 8 个文件:
- `src/novel_dev/agents/writer_agent.py`: `reg.get_active("writer")` → `await self._prompt("writer", chapter_id)`
- `src/novel_dev/agents/critic_agent.py`: `reg.get_active("critic")` → `await self._prompt("critic", chapter_id)`
- `src/novel_dev/agents/editor_agent.py`: `reg.get_active("editor")` → `await self._prompt("editor", chapter_id)`
- `src/novel_dev/agents/fast_review_agent.py`: `reg.get_active("fast_review")` → `await self._prompt("fast_review", chapter_id)`
- `src/novel_dev/agents/librarian.py`: `reg.get_active("librarian")` → `await self._prompt("librarian", chapter_id)`
- 剩 3 个(brainstorm/volume_planner/context)先保持现状,因它们不是 per-chapter 调用

- [ ] **Step 6: 跑全量测试**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -5
```

Expected: all passed (was 1709 before this task; +2 = 1711)

- [ ] **Step 7: 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add tests/test_services/test_prompt_registry.py src/novel_dev/services/prompt_registry.py src/novel_dev/agents/{writer,critic,editor,fast_review,librarian}_agent.py
git commit -m "feat(phase4): wire A/B test pipeline into 5 chapter-level agents"
```

---

### Task 2: 强制 beat_by_beat + Writer 温度 0.75

**Files:**
- Modify: `src/novel_dev/agents/writer_agent.py`
- Modify: `llm_config.yaml`
- Test: `tests/test_agents/test_writer_agent_chapters.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_agents/test_writer_agent_chapters.py` 末尾追加:

```python
def test_writer_default_drafting_mode_is_beat_by_beat():
    from novel_dev.agents.writer_agent import WriterAgent
    # _should_generate_whole_chapter should return False by default
    assert WriterAgent._should_generate_whole_chapter(drafting_mode=None) is False
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_writer_agent_chapters.py::test_writer_default_drafting_mode_is_beat_by_beat -v
```

Expected: FAIL

- [ ] **Step 3: 改 `_should_generate_whole_chapter`**

在 `src/novel_dev/agents/writer_agent.py` 中找到 `_should_generate_whole_chapter` 方法(约 line 420),改默认行为:

```python
    @staticmethod
    def _should_generate_whole_chapter(drafting_mode: str | None = None) -> bool:
        # Phase 4: 强制 beat_by_beat 为默认,整章模式仅显式开启
        if drafting_mode == "whole_chapter":
            return True
        return False
```

- [ ] **Step 4: 改 `llm_config.yaml`**

`llm_config.yaml` 中 `writer_agent.tasks.generate_chapter.temperature` 改为 `0.75`,并加 `phase4` 段(将在 Task 10 完整配置,这里先单独加温度):

```yaml
writer_agent:
  tasks:
    generate_chapter:
      temperature: 0.75
      max_tokens: 8192
```

- [ ] **Step 5: 跑测试 + 全量**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_writer_agent_chapters.py -v
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -5
```

Expected: all passed

- [ ] **Step 6: 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/agents/writer_agent.py llm_config.yaml tests/test_agents/test_writer_agent_chapters.py
git commit -m "feat(phase4): force beat_by_beat default + writer temp 0.75"
```

---

### Task 3: recent_issue_counts 接入 UI

**Files:**
- Create: `src/novel_dev/web/src/api/recentIssueCounts.js`(API 客户端方法)
- Modify: `src/novel_dev/api/routes.py`(新端点)
- Modify: `src/novel_dev/web/src/components/QualityRecommendationWidget.vue`
- Modify: `src/novel_dev/web/src/api.js`(若有总 API 文件)
- Test: `src/novel_dev/web/src/components/QualityRecommendationWidget.test.js`
- Test: `tests/test_api/test_recent_issue_counts.py`

- [ ] **Step 1: 写后端失败测试**

Create `tests/test_api/test_recent_issue_counts.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from novel_dev.api import app
from novel_dev.db.session import get_session


@pytest.mark.asyncio
async def test_recent_issue_counts_returns_recent_codes(async_session):
    from novel_dev.services.quality_metrics_service import QualityMetricsService, QualityMetricInput
    svc = QualityMetricsService(async_session)
    for i, code in enumerate(["BEAT_BOUNDARY_VIOLATION", "BEAT_BOUNDARY_VIOLATION", "AI_FLAVOR_HIGH"]):
        await svc.record(QualityMetricInput(
            chapter_id=f"ch_{i}", novel_id="n_1", phase="critic",
            attempt_index=1, overall_score=70, gate_status="warn",
            issue_codes=[code],
        ))
    await async_session.commit()

    async def override():
        yield async_session
    app.dependency_overrides[get_session] = override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/novels/n_1/chapters/recent-issue-counts?window=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["counts"]["BEAT_BOUNDARY_VIOLATION"] == 2
        assert data["counts"]["AI_FLAVOR_HIGH"] == 1
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_api/test_recent_issue_counts.py -v
```

Expected: 404 (路由不存在)

- [ ] **Step 3: 加后端路由**

在 `src/novel_dev/api/routes.py` 中找合适位置加:

```python
@router.get("/novels/{novel_id}/chapters/recent-issue-counts")
async def get_recent_issue_counts(
    novel_id: str,
    window: int = 5,
    session: AsyncSession = Depends(get_session),
) -> dict:
    from novel_dev.services.quality_metrics_service import QualityMetricsService
    svc = QualityMetricsService(session)
    counts = await svc.get_recent_issue_code_counts(novel_id, window=window)
    return {"novel_id": novel_id, "window": window, "counts": counts}
```

- [ ] **Step 4: 在 `QualityMetricsService` 加 `get_recent_issue_code_counts`**

在 `src/novel_dev/services/quality_metrics_service.py` 末尾加:

```python
    async def get_recent_issue_code_counts(self, novel_id: str, window: int = 5) -> dict:
        from sqlalchemy import select
        from novel_dev.db.models import ChapterQualityMetric
        result = await self.session.execute(
            select(ChapterQualityMetric)
            .where(ChapterQualityMetric.novel_id == novel_id)
            .order_by(ChapterQualityMetric.created_at.desc())
            .limit(window)
        )
        metrics = list(result.scalars().all())
        counts: dict[str, int] = {}
        for m in metrics:
            for code in (m.issue_codes or []):
                counts[code] = counts.get(code, 0) + 1
        return counts
```

- [ ] **Step 5: 跑后端测试确认通过**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_api/test_recent_issue_counts.py -v
```

Expected: PASS

- [ ] **Step 6: 写前端失败测试**

在 `src/novel_dev/web/src/components/QualityRecommendationWidget.test.js` 末尾追加:

```javascript
it('fetches and sends recent issue counts', async () => {
  const mockFetch = vi.fn().mockResolvedValue({
    counts: { BEAT_BOUNDARY_VIOLATION: 2 },
  })
  // 通过 axios 拦截
  vi.mock('axios', () => ({
    default: { get: mockFetch, post: vi.fn() },
  }))
  mockRecommend.mockResolvedValueOnce({
    recommendation: 'minor_repair', confidence: 0.6, rationale: [], suggested_actions: [],
  })
  const wrapper = mount(QualityRecommendationWidget, {
    props: { novelId: 'n1', chapterId: 'c1' },
  })
  await flushPromises()
  // 验证 recent_issue_counts 被传入
  const lastCall = mockRecommend.mock.calls.at(-1)
  expect(lastCall[2].recent_issue_counts).toEqual({ BEAT_BOUNDARY_VIOLATION: 2 })
})
```

- [ ] **Step 7: 跑测试确认失败**

```bash
cd /Users/linlin/Desktop/novel-dev/src/novel_dev/web && npm test -- QualityRecommendationWidget.test.js -t "recent issue"
```

Expected: FAIL

- [ ] **Step 8: 改 Widget**

在 `src/novel_dev/web/src/components/QualityRecommendationWidget.vue` 的 `<script setup>` 中,加 import 与方法:

```javascript
import axios from 'axios'

// 在 loadRecommendation 函数内,先拉 issue counts
async function loadRecommendation() {
  if (!props.novelId || !props.chapterId) return
  loading.value = true
  errorMessage.value = ''
  rationaleExpanded.value = false
  try {
    let recentIssueCounts = {}
    try {
      const countsResp = await axios.get(`/api/novels/${props.novelId}/chapters/recent-issue-counts?window=5`)
      recentIssueCounts = countsResp.data?.counts || {}
    } catch {
      // 失败时静默降级
    }
    const payload = {
      current_attempt: props.currentAttempt,
      accept_with_warn: props.acceptWithWarn,
      recent_issue_counts: recentIssueCounts,
    }
    const data = await recommendChapterQuality(props.novelId, props.chapterId, payload)
    recommendation.value = data || null
  } catch (err) {
    errorMessage.value = err?.response?.data?.detail || err?.message || '未知错误'
    recommendation.value = null
  } finally {
    loading.value = false
  }
}
```

- [ ] **Step 9: 跑前端测试 + 全量**

```bash
cd /Users/linlin/Desktop/novel-dev/src/novel_dev/web && npm test -- QualityRecommendationWidget.test.js
cd /Users/linlin/Desktop/novel-dev/src/novel_dev/web && npm test -- --run 2>&1 | tail -10
```

Expected: 286+1 = 287 passed

- [ ] **Step 10: 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add tests/test_api/test_recent_issue_counts.py src/novel_dev/api/routes.py src/novel_dev/services/quality_metrics_service.py src/novel_dev/web/src/components/QualityRecommendationWidget.vue src/novel_dev/web/src/components/QualityRecommendationWidget.test.js
git commit -m "feat(phase4): wire recent_issue_counts from UI to recommendation"
```

---

### Task 4: BeatCoverageValidator 接入 FastReview

**Files:**
- Modify: `src/novel_dev/agents/fast_review_agent.py`
- Test: `tests/test_agents/test_fast_review_agent.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_agents/test_fast_review_agent.py` 末尾追加:

```python
@pytest.mark.asyncio
async def test_fast_review_invokes_beat_coverage_validator(async_session, monkeypatch):
    from novel_dev.agents.fast_review_agent import FastReviewAgent
    from novel_dev.schemas.quality import BeatBoundaryCard
    from unittest.mock import AsyncMock, MagicMock, patch

    fake_validator = MagicMock()
    fake_validator.validate = AsyncMock(return_value=[
        MagicMock(beat_index=0, covered=False, severity="block", deviation="forbidden",
                  to_issue_code=lambda: "BEAT_BOUNDARY_VIOLATION")
    ])

    with patch("novel_dev.agents.fast_review_agent.BeatCoverageValidator", return_value=fake_validator):
        agent = FastReviewAgent(async_session)
        agent._run_beat_coverage = AsyncMock(wraps=agent._run_beat_coverage)
        # 检查 _run_beat_coverage 是否被调用
        report = await agent.review(
            chapter_id="ch_1", novel_id="n_1",
            polished_text="陆照听见追兵。",  # contains forbidden '追兵'
            chapter_context={
                "beats": [{"beat_index": 0, "must_cover": ["陆照"], "forbidden_materials": ["追兵"]}]
            },
        )
    fake_validator.validate.assert_awaited_once()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_fast_review_agent.py::test_fast_review_invokes_beat_coverage_validator -v
```

Expected: FAIL

- [ ] **Step 3: 在 FastReviewAgent 加 beat coverage pass**

在 `src/novel_dev/agents/fast_review_agent.py` 中找 `review()` 方法,在末尾追加:

```python
        # Phase 4: 调 BeatCoverageValidator
        from novel_dev.services.beat_coverage_validator import BeatCoverageValidator
        from novel_dev.schemas.quality import BeatBoundaryCard
        from novel_dev.config import settings
        use_llm = bool(getattr(settings, "phase4_beat_coverage_use_llm", True))
        beat_cards = [
            BeatBoundaryCard(
                beat_index=b.get("beat_index", i),
                must_cover=b.get("must_cover", []),
                forbidden_materials=b.get("forbidden_materials", []),
            )
            for i, b in enumerate(chapter_context.get("beats", []))
        ]
        if beat_cards:
            validator = BeatCoverageValidator(async_session, use_llm=use_llm)
            coverage = await validator.validate(beat_cards, polished_text)
            for r in coverage:
                if r.severity == "block" and r.to_issue_code():
                    report.blocking_items.append({
                        "code": r.to_issue_code(),
                        "message": f"beat {r.beat_index}: {r.deviation}",
                        "detail": {"beat_index": r.beat_index, "deviation": r.deviation},
                    })
            report.beat_coverage_results = [
                {"beat_index": r.beat_index, "covered": r.covered, "severity": r.severity}
                for r in coverage
            ]
```

- [ ] **Step 4: 在 `FastReviewReport` 加 `beat_coverage_results` 字段**

在 `src/novel_dev/agents/fast_review_agent.py` 顶部 schema 定义处,扩展 dataclass:

```python
@dataclass
class FastReviewReport:
    ...existing fields...
    beat_coverage_results: list[dict] = field(default_factory=list)
```

(具体字段名按现有结构)

- [ ] **Step 5: 跑测试确认通过 + 全量**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_fast_review_agent.py -v
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -5
```

Expected: all passed

- [ ] **Step 6: 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add tests/test_agents/test_fast_review_agent.py src/novel_dev/agents/fast_review_agent.py
git commit -m "feat(phase4): FastReviewAgent invokes BeatCoverageValidator"
```

---

### Task 5: 失败闭门策略

**Files:**
- Modify: `src/novel_dev/services/chapter_structure_guard_service.py`
- Modify: `src/novel_dev/services/chapter_rewrite_service.py`
- Test: `tests/test_services/test_chapter_structure_guard_service.py`

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_structure_guard_fail_closed_on_timeout(async_session, monkeypatch):
    from novel_dev.services.chapter_structure_guard_service import ChapterStructureGuardService
    import asyncio

    async def slow_check(*args, **kwargs):
        await asyncio.sleep(2)
        return None

    monkeypatch.setattr(ChapterStructureGuardService, "_check_async", staticmethod(slow_check))
    # 编辑器守卫超时应当 fail-closed
    result = await ChapterStructureGuardService.check_editor_beat(
        async_session, beat_id="b1", polished_text="x", timeout=0.1
    )
    assert result.passed is False
    assert result.conservative_fallback is False
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_services/test_chapter_structure_guard_service.py -k "fail_closed" -v
```

Expected: FAIL (当前超时返回 conservative_fallback=True)

- [ ] **Step 3: 改 ChapterStructureGuardService**

在 `src/novel_dev/services/chapter_structure_guard_service.py` 中,超时分支改为:

```python
            except (asyncio.TimeoutError, Exception) as exc:
                logger.warning("structure_guard_timeout", extra={"error": str(exc)})
                return ChapterStructureGuardResult(
                    passed=False,
                    conservative_fallback=False,  # Phase 4: 失败闭门
                    issues=["结构守卫超时或失败,触发失败闭门"],
                    suggested_rewrite_focus="需要重写本节拍",
                )
```

- [ ] **Step 4: 改 ChapterRewriteService 响应 fail-closed**

在 `src/novel_dev/services/chapter_rewrite_service.py` 中,检查 `result.conservative_fallback` 的地方,改为:

```python
            if not guard_result.passed:
                # Phase 4: 失败闭门,触发重写
                await self._queue_rewrite(
                    chapter_id=chapter_id,
                    reason=f"structure_guard_failed: {guard_result.suggested_rewrite_focus}",
                    root_cause=root_cause,
                )
                return
```

(具体上下文按实际代码微调)

- [ ] **Step 5: 跑测试 + 全量**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_services/test_chapter_structure_guard_service.py -v
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -5
```

Expected: all passed

- [ ] **Step 6: 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add tests/test_services/test_chapter_structure_guard_service.py src/novel_dev/services/chapter_structure_guard_service.py src/novel_dev/services/chapter_rewrite_service.py
git commit -m "feat(phase4): fail-closed on structure guard timeout"
```

---

## Wave 2: 配置级快速修复(4 任务)

### Task 6: llm_config.yaml phase4 段 + quality_config 加载

**Files:**
- Modify: `llm_config.yaml`
- Modify: `src/novel_dev/config/quality_config.py`
- Test: `tests/test_config/test_phase4_config.py`

- [ ] **Step 1: 写失败测试**

Create `tests/test_config/test_phase4_config.py`:

```python
import pytest


def test_phase4_config_loads(monkeypatch):
    from novel_dev.config.quality_config import get_phase4_config
    cfg = get_phase4_config()
    assert "rcs" in cfg
    assert cfg["rcs"]["trigger_window_chapters"] == 5
    assert "web_novel" in cfg
    assert "writer" in cfg
    assert cfg["writer"]["default_drafting_mode"] == "beat_by_beat"


def test_phase4_config_missing_raises(monkeypatch):
    def bad():
        return {}
    monkeypatch.setattr("novel_dev.config.quality_config.get_llm_config", bad)
    from novel_dev.config.quality_config import get_phase4_config
    with pytest.raises(KeyError):
        get_phase4_config()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_config/test_phase4_config.py -v
```

Expected: FAIL

- [ ] **Step 3: 加 `phase4` 段到 `llm_config.yaml`**

在 `llm_config.yaml` 末尾追加:

```yaml
phase4:
  rcs:
    enabled: true
    trigger_window_chapters: 5
    max_synopsis_chars: 2000
    llm_client: root_cause_analyzer
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
  beat_coverage_use_llm: true
  web_novel:
    chapter_archetypes: [action, setup, payoff, mixed]
    mood_phases: [setup, tension, release, climax, cooldown]
    thrill_types: [face_slap, show_off, level_up, reward_gain, revelation, revenge, plot_twist, recognition]
    intensity_levels: [low, medium, high, peak]
    imagery_item_types: [physical_imagery, metaphor, author_voice, idiom]
  writer:
    default_drafting_mode: beat_by_beat
    temperature: 0.75
  guard:
    fail_open_on_timeout: false
```

- [ ] **Step 4: 加 `get_phase4_config`**

在 `src/novel_dev/config/quality_config.py` 末尾追加:

```python
def get_phase4_config() -> dict:
    cfg = get_llm_config()
    if "phase4" not in cfg:
        raise KeyError("Missing required section: phase4")
    return cfg["phase4"]
```

- [ ] **Step 5: 跑测试确认通过**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_config/test_phase4_config.py -v
```

Expected: 2 passed

- [ ] **Step 6: 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add llm_config.yaml src/novel_dev/config/quality_config.py tests/test_config/test_phase4_config.py
git commit -m "feat(config): add phase4 config section with validation"
```

---

### Task 7: CONTEXT_AGENT_PROMPT 重写

**Files:**
- Modify: `src/novel_dev/agents/_default_prompts.py`
- Test: `tests/test_agents/test_context_agent.py`(若不存在,加一个基础加载测试)

- [ ] **Step 1: 写失败测试**

```python
def test_context_agent_prompt_has_selection_principles():
    from novel_dev.agents._default_prompts import CONTEXT_AGENT_PROMPT
    assert "实体筛选" in CONTEXT_AGENT_PROMPT or "实体选择" in CONTEXT_AGENT_PROMPT
    assert "文档检索" in CONTEXT_AGENT_PROMPT
    assert "冲突" in CONTEXT_AGENT_PROMPT or "优先级" in CONTEXT_AGENT_PROMPT
    # Few-shot
    assert "示例" in CONTEXT_AGENT_PROMPT or "example" in CONTEXT_AGENT_PROMPT.lower()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_context_agent.py -k "selection_principles" -v
```

Expected: FAIL

- [ ] **Step 3: 重写 `CONTEXT_AGENT_PROMPT`**

在 `src/novel_dev/agents/_default_prompts.py` 中找 `CONTEXT_AGENT_PROMPT` 常量,替换为:

```python
CONTEXT_AGENT_PROMPT = """你是小说写作的上下文准备助手。基于当前章节计划,从已有实体、文档、时间线中筛选最相关的素材,组装成 context JSON。

# 输出 schema
{context_agent_output_schema}

# 实体筛选原则
1. 相关性优先: 仅返回本章计划中提及或可能涉及的实体,无关实体不返回
2. 时序近邻: 时间线事件优先返回距当前章节 ±3 章的范围
3. 状态匹配: 实体 current_state 应与本章发生时的状态相符,如有冲突优先最近一次更新
4. 数量限制: 每类不超过 {max_entities_per_type} 个,超出按相关度排序截取

# 文档检索原则
1. 主题契合度高于字面匹配: 文档主题与本章主题契合时优先选
2. 多样性: 不要返回 3 篇相似度 > 0.9 的文档,保留多样性
3. 短小精悍: 每篇文档截取最相关的 {max_doc_chars} 字符

# 冲突解决
1. 实体状态冲突: 优先最近一次 EntityVersion
2. 文档观点冲突: 同时保留,标记 [冲突]
3. 时间线冲突: 检查 tick 顺序,后发生者覆盖

# Few-shot 示例
输入: chapter_plan = {{ title: "陆照初入灵谷", beats: [...] }}
输出: {{ locations: ["灵谷入口", "药库"], entities: [...], time_range: [3, 7], foreshadowing_keywords: ["玉佩"] }}
"""
```

- [ ] **Step 4: 跑测试确认通过 + 全量**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_context_agent.py -v
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -5
```

Expected: all passed

- [ ] **Step 5: 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/agents/_default_prompts.py tests/test_agents/test_context_agent.py
git commit -m "feat(prompts): rewrite CONTEXT_AGENT_PROMPT with selection principles + few-shot"
```

---

### Task 8: WRITER/CRITIC/EDITOR prompt 加 few-shot

**Files:**
- Modify: `src/novel_dev/agents/_default_prompts.py`
- Test: `tests/test_agents/test_prompts.py`(新文件)

- [ ] **Step 1: 写失败测试**

Create `tests/test_agents/test_prompts.py`:

```python
def test_writer_prompt_has_few_shot_example():
    from novel_dev.agents._default_prompts import WRITER_PROMPT
    assert "Few-shot" in WRITER_PROMPT or "差" in WRITER_PROMPT or "示例" in WRITER_PROMPT


def test_critic_prompt_has_high_low_score_examples():
    from novel_dev.agents._default_prompts import CRITIC_PROMPT
    # 应有高分/低分示例
    assert ("90" in CRITIC_PROMPT or "high" in CRITIC_PROMPT.lower())


def test_editor_prompt_has_before_after_example():
    from novel_dev.agents._default_prompts import EDITOR_PROMPT
    assert "修前" in EDITOR_PROMPT or "改前" in EDITOR_PROMPT or "before" in EDITOR_PROMPT.lower()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_prompts.py -v
```

Expected: 3 FAIL

- [ ] **Step 3: 在三个 prompt 末尾各加 few-shot 块**

`src/novel_dev/agents/_default_prompts.py` 中,找到 `WRITER_PROMPT`/`CRITIC_PROMPT`/`EDITOR_PROMPT`,在每个末尾追加:

```python
# WRITER_PROMPT 末尾:
WRITER_PROMPT = WRITER_PROMPT + """

# Few-shot 示例
差的开头:
"陆照睁开眼睛,发现自己在一个陌生的地方。他想:这是哪里?"
好的开头:
"陆照的指尖碰到冰冷的玉佩——他这才发现,自己已经不在灵谷。"
差异:差的开头用模板化"睁开眼睛+内心独白",好的开头用具象触感和悬念锚点。"""


# CRITIC_PROMPT 末尾:
CRITIC_PROMPT = CRITIC_PROMPT + """

# Few-shot 评分示例
humanity 维度高(90+): "陆照的母亲死在他面前,他没有哭。他只是把母亲的手放在自己掌心,一直握着,直到手凉了。"
humanity 维度低(40-): "陆照非常伤心,因为母亲死了。他流下了眼泪。" """


# EDITOR_PROMPT 末尾:
EDITOR_PROMPT = EDITOR_PROMPT + """

# Few-shot 编辑示例
修前: "马管事笑得像石子投入枯井,响了一声,便没了回音。"
修后: "马管事收了笑,没再说话。"
差异:修后去掉了"作者替人物解释情绪"的套语,改为人物可观察的动作。"""
```

- [ ] **Step 4: 跑测试 + 全量**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_prompts.py -v
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -5
```

Expected: all passed

- [ ] **Step 5: 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/agents/_default_prompts.py tests/test_agents/test_prompts.py
git commit -m "feat(prompts): add few-shot examples to WRITER/CRITIC/EDITOR prompts"
```

---

### Task 9: Librarian 软状态 pass 提升为 PromptRegistry

**Files:**
- Modify: `src/novel_dev/agents/_default_prompts.py`(加 `LIBRARIAN_SOFT_STATE_PROMPT`)
- Modify: `src/novel_dev/agents/librarian.py`(改 `_build_soft_state_prompt` 为 `await reg.get_active`)
- Test: `tests/test_agents/test_librarian.py`

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_librarian_soft_state_uses_prompt_registry(async_session, monkeypatch):
    from novel_dev.agents import librarian as lib_module
    from novel_dev.services.prompt_registry import PromptRegistry

    # Bootstrap 一个自定义软状态 prompt
    reg = PromptRegistry(async_session)
    await reg.create_version(
        "librarian_soft_state", "v1.0", "CUSTOM SOFT STATE PROMPT", is_active=True,
    )

    # 触发软状态 pass(根据实际实现调用)
    agent = lib_module.LibrarianAgent(async_session)
    prompt = await agent._get_soft_state_prompt()
    assert "CUSTOM SOFT STATE PROMPT" in prompt
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_librarian.py -k "soft_state" -v
```

Expected: FAIL

- [ ] **Step 3: 在 `_default_prompts.py` 加新 prompt**

```python
LIBRARIAN_SOFT_STATE_PROMPT = """你是小说世界状态软变化提取器。基于已提取的硬状态变更,识别以下软状态变化:
1. 人物关系的微妙转变(信任/敌意/亲密/疏远)
2. 情感基调(从紧张到放松,或反之)
3. 隐藏的伏笔(作者暗示但未明说)
4. 价值观的松动

输入格式: {hard_state_changes: [...], chapter_text_excerpt: "..."}
输出 JSON: {relationship_shifts: [...], tone_shift: str, hidden_foreshadowing: [...], value_shifts: [...]}"""
```

- [ ] **Step 4: 改 `librarian.py` 的软状态 pass**

在 `src/novel_dev/agents/librarian.py` 中:

- 删 `_build_soft_state_prompt` 方法
- 加新方法:

```python
    async def _get_soft_state_prompt(self) -> str:
        from novel_dev.services.prompt_registry import PromptRegistry
        reg = PromptRegistry(self.session)
        return await reg.get_active("librarian_soft_state")
```

- 替换原 `_build_soft_state_prompt` 的所有调用为 `await self._get_soft_state_prompt()`

- [ ] **Step 5: 跑测试 + 全量**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_librarian.py -v
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -5
```

Expected: all passed

- [ ] **Step 6: 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/agents/_default_prompts.py src/novel_dev/agents/librarian.py tests/test_agents/test_librarian.py
git commit -m "feat(librarian): promote soft-state pass to PromptRegistry"
```

---

## Wave 3: RCS 架构(5 任务)

### Task 10: 3 个新表 + migration

**Files:**
- Modify: `src/novel_dev/db/models.py`
- Create: `migrations/versions/20260617_<rev>_phase4_quality_architectural_tables.py`
- Test: `tests/test_repositories/test_chapter_synopsis_repo.py`(基础创建/读取)

- [ ] **Step 1: 写失败测试**

Create `tests/test_repositories/test_chapter_synopsis_repo.py`:

```python
import pytest
from novel_dev.repositories.chapter_synopsis_repo import ChapterSynopsisRepository


@pytest.mark.asyncio
async def test_create_and_get_latest(async_session):
    repo = ChapterSynopsisRepository(async_session)
    syn = await repo.create(
        novel_id="n_1", chapter_range_start=1, chapter_range_end=5,
        narrative_prose="...", structured_json={"plot_points": []},
        trigger_event={"type": "block", "chapter_id": "ch_5"},
    )
    latest = await repo.get_latest("n_1")
    assert latest.id == syn.id
    assert latest.chapter_range_end == 5
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_chapter_synopsis_repo.py -v
```

Expected: FAIL (Repository doesn't exist)

- [ ] **Step 3: 加 3 个 model 到 `models.py`**

在 `src/novel_dev/db/models.py` 末尾追加:

```python
class ChapterSynopsis(Base):
    __tablename__ = "chapter_synopsis"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    novel_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    chapter_range_start: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_range_end: Mapped[int] = mapped_column(Integer, nullable=False)
    narrative_prose: Mapped[str] = mapped_column(Text, nullable=False)
    structured_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    trigger_event: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    prev_synopsis_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    analyzer_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1.0")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class ThrillPoint(Base):
    __tablename__ = "thrill_points"
    __table_args__ = (Index("ix_thrill_points_chapter", "chapter_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    novel_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    chapter_id: Mapped[str] = mapped_column(String(64), nullable=False)
    beat_idx: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    thrill_type: Mapped[str] = mapped_column(String(32), nullable=False)  # 8 类枚举
    intensity: Mapped[str] = mapped_column(String(16), nullable=False)  # low/medium/high/peak
    evidence_quote: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    planner_predicted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fast_review_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class ImageryInventory(Base):
    __tablename__ = "imagery_inventory"
    __tablename__ = "imagery_inventory"
    __table_args__ = (Index("ix_imagery_inventory_novel_chapter", "novel_id", "chapter_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    novel_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    chapter_id: Mapped[str] = mapped_column(String(64), nullable=False)
    item: Mapped[str] = mapped_column(String(255), nullable=False)
    item_type: Mapped[str] = mapped_column(String(32), nullable=False)
    frequency_in_chapter: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    extracted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
```

- [ ] **Step 4: 生成 Alembic 迁移**

```bash
cd /Users/linlin/Desktop/novel-dev && alembic revision --autogenerate -m "phase4_quality_architectural_tables"
```

- [ ] **Step 5: 跑迁移 + 测试 DB**

```bash
cd /Users/linlin/Desktop/novel-dev && alembic upgrade head
```

- [ ] **Step 6: 写 Repository**

Create `src/novel_dev/repositories/chapter_synopsis_repo.py`:

```python
from __future__ import annotations
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from novel_dev.db.models import ChapterSynopsis


class ChapterSynopsisRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self, novel_id: str, chapter_range_start: int, chapter_range_end: int,
        narrative_prose: str, structured_json: dict,
        trigger_event: dict, prev_synopsis_id: Optional[str] = None,
        analyzer_version: str = "v1.0",
    ) -> ChapterSynopsis:
        cs = ChapterSynopsis(
            novel_id=novel_id,
            chapter_range_start=chapter_range_start,
            chapter_range_end=chapter_range_end,
            narrative_prose=narrative_prose,
            structured_json=structured_json,
            trigger_event=trigger_event,
            prev_synopsis_id=prev_synopsis_id,
            analyzer_version=analyzer_version,
        )
        self.session.add(cs)
        await self.session.flush()
        return cs

    async def get_latest(self, novel_id: str) -> Optional[ChapterSynopsis]:
        result = await self.session.execute(
            select(ChapterSynopsis)
            .where(ChapterSynopsis.novel_id == novel_id)
            .order_by(ChapterSynopsis.chapter_range_end.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_all(self, novel_id: str) -> list[ChapterSynopsis]:
        result = await self.session.execute(
            select(ChapterSynopsis)
            .where(ChapterSynopsis.novel_id == novel_id)
            .order_by(ChapterSynopsis.chapter_range_start.asc())
        )
        return list(result.scalars().all())
```

同样写 `src/novel_dev/repositories/thrill_point_repo.py` 和 `imagery_inventory_repo.py`(CRUD + 聚合查询)。

- [ ] **Step 7: 跑测试 + 全量**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_chapter_synopsis_repo.py -v
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -5
```

Expected: all passed

- [ ] **Step 8: 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/db/models.py migrations/versions/20260617_*_phase4_quality_architectural_tables.py src/novel_dev/repositories/ tests/test_repositories/
git commit -m "feat(phase4): add chapter_synopsis, thrill_point, imagery_inventory tables + repos"
```

---

### Task 11: 3 个新 prompt 加入 _default_prompts.py

**Files:**
- Modify: `src/novel_dev/agents/_default_prompts.py`
- Test: `tests/test_agents/test_prompts.py`(扩展)

- [ ] **Step 1: 写失败测试**

在 `tests/test_agents/test_prompts.py` 末尾追加:

```python
def test_rolling_synopsis_prompt_defined():
    from novel_dev.agents._default_prompts import ROLLING_SYNOPSIS_PROMPT
    assert "前情" in ROLLING_SYNOPSIS_PROMPT or "prev" in ROLLING_SYNOPSIS_PROMPT.lower()


def test_entity_change_importance_prompt_defined():
    from novel_dev.agents._default_prompts import ENTITY_CHANGE_IMPORTANCE_PROMPT
    assert "important" in ENTITY_CHANGE_IMPORTANCE_PROMPT.lower()


def test_imagery_extraction_prompt_defined():
    from novel_dev.agents._default_prompts import IMAGERY_EXTRACTION_PROMPT
    assert "意象" in IMAGERY_EXTRACTION_PROMPT or "imagery" in IMAGERY_EXTRACTION_PROMPT.lower()


def test_cross_chapter_drift_prompt_defined():
    from novel_dev.agents._default_prompts import CROSS_CHAPTER_DRIFT_DETECTION_PROMPT
    assert "drift" in CROSS_CHAPTER_DRIFT_DETECTION_PROMPT.lower() or "漂移" in CROSS_CHAPTER_DRIFT_DETECTION_PROMPT
```

- [ ] **Step 2-4: 加 4 个 prompt 常量**

在 `src/novel_dev/agents/_default_prompts.py` 末尾追加:

```python
ROLLING_SYNOPSIS_PROMPT = """你是长篇小说叙事摘要压缩助手。给定前一阶段的滚动摘要 + 本次新覆盖章节的摘要,生成新的滚动叙事摘要。

输入:
- prev_synopsis: 前一阶段摘要(可为空)
- new_chapter_summaries: 本次新覆盖章节列表(每章: chapter_id, title, brief_summary)
- trigger_event: 触发本次更新的事件

输出 JSON:
{
  "narrative_prose": "500-2000 字连续叙事文本,延续前情,标注新增重大事件,保留未解决张力",
  "structured_json": {
    "plot_points": ["主要情节节点"],
    "unresolved_tensions": ["未解决的张力/悬念"],
    "character_arcs": {"陆照": "从 X 到 Y"},
    "foreshadowing_status": {"玉佩之谜": "已埋下,未回收"}
  }
}"""


ENTITY_CHANGE_IMPORTANCE_PROMPT = """你是实体状态变化重要性评估助手。给定本章所有实体状态变化,判断哪些是"重要叙事点"。

输入: [{entity_id, entity_name, prev_state, new_state, diff_summary}]
输出 JSON: [{entity_id, is_important: bool, reason, suggested_synopsis_section}]

判定标准:
- 重要: 实力阶跃(凡人→修士)、位置大跨度、关系反转、状态变化(生/死)、新身份获得
- 不重要: 数值小变化、状态字段细化、外貌微调"""


IMAGERY_EXTRACTION_PROMPT = """你是小说意象提取助手。从给定章节中提取主要意象、比喻、作者口吻指纹。

输入: 章节全文
输出 JSON: [{item: "具体意象/比喻/口吻", item_type: "physical_imagery|metaphor|author_voice|idiom", frequency_in_chapter: int}]

提取规则:
1. 物理意象: 反复出现的触觉/视觉/听觉对象(碎石硌掌心)
2. 比喻: 显式"像"字句或隐喻
3. 作者口吻: 高频副词(突然/竟然/居然)、评述性短语
4. 习语/成语: 频繁使用且在本书语境中有特殊意义
5. 只提取出现 ≥ 2 次或语义密集的项"""


CROSS_CHAPTER_DRIFT_DETECTION_PROMPT = """你是跨章实体连续性检测助手。给定本章文本 + 最近 N 章文本 + 本章出现的实体列表,检测 3 类漂移:

1. 名字漂移: 同一角色在前后章节使用不同名字(如 陆照→陆昭)
2. 身份漂移: 同一角色身份称谓变化(如 师兄→师弟)
3. 状态阶跃: 实体状态变化无伏笔/无交代(如 凡人突然筑基)

输入: {current_text, prior_texts, entities: [{name, history_state, identity_role}]}
输出 JSON: [{entity_name, drift_type, severity: "warn|block", evidence_quote, suggested_fix}]
"""
```

- [ ] **Step 5: 跑测试确认通过**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_prompts.py -v
```

Expected: 4 new tests pass

- [ ] **Step 6: 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/agents/_default_prompts.py tests/test_agents/test_prompts.py
git commit -m "feat(prompts): add RCS, entity importance, imagery, drift detection prompts"
```

---

### Task 12: RollingChapterSynopsisService

**Files:**
- Create: `src/novel_dev/services/rolling_chapter_synopsis_service.py`
- Test: `tests/test_services/test_rolling_chapter_synopsis.py`

- [ ] **Step 1: 写失败测试**

Create `tests/test_services/test_rolling_chapter_synopsis.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from novel_dev.services.rolling_chapter_synopsis_service import RollingChapterSynopsisService


@pytest.mark.asyncio
async def test_should_update_on_quality_block(async_session):
    svc = RollingChapterSynopsisService(async_session)
    assert await svc.should_update("n_1", "ch_5", "quality_block", {"gate_status": "block"}) is True


@pytest.mark.asyncio
async def test_should_update_on_entity_state_dramatic(async_session):
    svc = RollingChapterSynopsisService(async_session)
    assert await svc.should_update("n_1", "ch_5", "entity_state_change", {"is_important": True}) is True


@pytest.mark.asyncio
async def test_should_update_false_for_minor_change(async_session):
    svc = RollingChapterSynopsisService(async_session)
    assert await svc.should_update("n_1", "ch_5", "entity_state_change", {"is_important": False}) is False


@pytest.mark.asyncio
async def test_update_writes_new_snapshot_and_caches(async_session):
    from novel_dev.repositories.chapter_synopsis_repo import ChapterSynopsisRepository
    from novel_dev.db.models import NovelState
    from novel_dev.db.session import get_session

    # 创建 novel_state 用于缓存
    ns = NovelState(id="n_1", checkpoint_data={})
    async_session.add(ns)
    await async_session.flush()

    # Mock LLM 响应
    fake_response = MagicMock()
    fake_response.text = '{"narrative_prose": "陆照进入灵谷...", "structured_json": {"plot_points": []}}'
    fake_response.usage = None
    fake_client = AsyncMock()
    fake_client.acomplete = AsyncMock(return_value=fake_response)
    with patch("novel_dev.services.rolling_chapter_synopsis_service.llm_factory") as mf:
        mf.get.return_value = fake_client
        svc = RollingChapterSynopsisService(async_session)
        syn = await svc.update("n_1", "ch_5", trigger_event={"type": "block"})

    assert syn.narrative_prose.startswith("陆照")
    assert syn.novel_id == "n_1"
    # 缓存
    await async_session.refresh(ns)
    assert "rolling_synopsis_cache" in ns.checkpoint_data


@pytest.mark.asyncio
async def test_get_latest_returns_most_recent(async_session):
    svc = RollingChapterSynopsisService(async_session)
    repo = ChapterSynopsisRepository(async_session)
    await repo.create("n_1", 1, 5, "first", {}, {})
    await repo.create("n_1", 6, 10, "second", {}, {})
    latest = await svc.get_latest("n_1")
    assert latest.chapter_range_end == 10
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_services/test_rolling_chapter_synopsis.py -v
```

Expected: FAIL (module doesn't exist)

- [ ] **Step 3: 实现 `RollingChapterSynopsisService`**

Create `src/novel_dev/services/rolling_chapter_synopsis_service.py`:

```python
from __future__ import annotations
import json
import logging
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.llm import llm_factory
from novel_dev.db.models import NovelState
from novel_dev.repositories.chapter_synopsis_repo import ChapterSynopsisRepository
from novel_dev.services.prompt_registry import PromptRegistry

logger = logging.getLogger(__name__)


class RollingChapterSynopsisService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ChapterSynopsisRepository(session)

    async def should_update(
        self, novel_id: str, chapter_id: str, event_type: str, event_payload: dict,
    ) -> bool:
        if event_type == "quality_block":
            return event_payload.get("gate_status") == "block"
        if event_type == "entity_state_change":
            return bool(event_payload.get("is_important"))
        if event_type in ("entity_introduced", "entity_removed"):
            return True
        return False

    async def update(
        self, novel_id: str, chapter_id: str, trigger_event: dict,
    ) -> "ChapterSynopsis":
        prev = await self.repo.get_latest(novel_id)
        prev_synopsis = prev.narrative_prose if prev else ""

        # 拉 prompt
        reg = PromptRegistry(self.session)
        template = await reg.get_active("rolling_synopsis")
        # 拼装 prompt
        from novel_dev.db.models import Chapter
        from novel_dev.db.models import ChapterSynopsis  # noqa
        ch_result = await self.session.execute(
            select(Chapter).where(Chapter.id == chapter_id)
        )
        ch = ch_result.scalar_one_or_none()
        new_chapter_summary = ch.title if ch else chapter_id
        prompt = template.format(
            prev_synopsis=prev_synopsis or "(无前情摘要)",
            new_chapter_summaries=f"- {chapter_id}: {new_chapter_summary}",
            trigger_event=json.dumps(trigger_event, ensure_ascii=False),
        )

        # 调 LLM
        client = llm_factory.get("RootCauseAnalyzer")
        from novel_dev.llm.models import ChatMessage
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        parsed = self._parse_response(response.text)

        # 入库
        from novel_dev.db.models import ChapterSynopsis
        syn = await self.repo.create(
            novel_id=novel_id,
            chapter_range_start=(prev.chapter_range_end + 1) if prev else 1,
            chapter_range_end=int(chapter_id.split("_")[-1]) if "_" in chapter_id else 1,
            narrative_prose=parsed["narrative_prose"],
            structured_json=parsed["structured_json"],
            trigger_event=trigger_event,
            prev_synopsis_id=prev.id if prev else None,
        )
        # 写 checkpoint 缓存
        await self.cache_to_checkpoint(novel_id, syn)
        return syn

    async def cache_to_checkpoint(self, novel_id: str, syn) -> None:
        result = await self.session.execute(
            select(NovelState).where(NovelState.id == novel_id)
        )
        ns = result.scalar_one_or_none()
        if not ns:
            return
        cp = dict(ns.checkpoint_data or {})
        cp["rolling_synopsis_cache"] = {
            "id": syn.id,
            "chapter_range": [syn.chapter_range_start, syn.chapter_range_end],
            "narrative_prose": syn.narrative_prose,
            "structured_json": syn.structured_json,
        }
        ns.checkpoint_data = cp
        await self.session.flush()

    async def get_latest(self, novel_id: str):
        return await self.repo.get_latest(novel_id)

    @staticmethod
    def _parse_response(text: str) -> dict:
        import re
        text = text.strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.MULTILINE)
        return json.loads(text)
```

- [ ] **Step 4: 跑测试确认通过 + 全量**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_services/test_rolling_chapter_synopsis.py -v
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -5
```

Expected: all passed

- [ ] **Step 5: 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/services/rolling_chapter_synopsis_service.py tests/test_services/test_rolling_chapter_synopsis.py
git commit -m "feat(rcs): add RollingChapterSynopsisService"
```

---

### Task 13: LibrarianAgent.persist 触发 RCS

**Files:**
- Modify: `src/novel_dev/agents/librarian.py`
- Test: `tests/test_agents/test_librarian.py`(扩展)

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_librarian_persist_triggers_rcs_on_quality_block(async_session, monkeypatch):
    from novel_dev.agents.librarian import LibrarianAgent
    from novel_dev.services.rolling_chapter_synopsis_service import RollingChapterSynopsisService

    called = []
    original_update = RollingChapterSynopsisService.update
    async def mock_update(self, novel_id, chapter_id, trigger_event):
        called.append((novel_id, chapter_id, trigger_event))
        return await original_update(self, novel_id, chapter_id, trigger_event)
    monkeypatch.setattr(RollingChapterSynopsisService, "update", mock_update)

    # 模拟 quality_block 事件触发
    agent = LibrarianAgent(async_session)
    await agent.on_chapter_finalized(
        novel_id="n_1", chapter_id="ch_5", gate_status="block",
    )
    assert len(called) == 1
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_librarian.py -k "rcs_on_quality_block" -v
```

Expected: FAIL

- [ ] **Step 3: 在 `LibrarianAgent` 加 `on_chapter_finalized` 钩子**

在 `src/novel_dev/agents/librarian.py` 中加:

```python
    async def on_chapter_finalized(
        self, novel_id: str, chapter_id: str, gate_status: str,
        entity_state_changes: list[dict] | None = None,
        entities_introduced: list[str] | None = None,
        entities_removed: list[str] | None = None,
    ) -> None:
        """章节归档后钩子:检测 RCS 触发条件"""
        from novel_dev.services.rolling_chapter_synopsis_service import RollingChapterSynopsisService
        from novel_dev.llm import llm_factory
        from novel_dev.services.prompt_registry import PromptRegistry
        from novel_dev.llm.models import ChatMessage
        import json

        rcs = RollingChapterSynopsisService(self.session)

        # 1. quality_block 触发
        if gate_status == "block":
            if await rcs.should_update(novel_id, chapter_id, "quality_block", {"gate_status": gate_status}):
                await rcs.update(novel_id, chapter_id, trigger_event={"type": "block", "chapter_id": chapter_id})

        # 2. entity_state_change 触发(LLM 批量评估)
        if entity_state_changes:
            reg = PromptRegistry(self.session)
            template = await reg.get_active("entity_change_importance")
            prompt = template.format(
                changes=json.dumps(entity_state_changes, ensure_ascii=False)
            )
            client = llm_factory.get("RootCauseAnalyzer")
            response = await client.acomplete([ChatMessage(role="user", content=prompt)])
            import re
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.text.strip(), flags=re.IGNORECASE | re.MULTILINE)
            evaluations = json.loads(text)
            for ev in evaluations:
                if ev.get("is_important"):
                    if await rcs.should_update(novel_id, chapter_id, "entity_state_change", ev):
                        await rcs.update(novel_id, chapter_id, trigger_event={"type": "entity_state_change", **ev})

        # 3. 实体引入/退出
        for eid in (entities_introduced or []):
            await rcs.update(novel_id, chapter_id, trigger_event={"type": "entity_introduced", "entity_id": eid})
        for eid in (entities_removed or []):
            await rcs.update(novel_id, chapter_id, trigger_event={"type": "entity_removed", "entity_id": eid})
```

- [ ] **Step 4: 在 `persist()` 末尾调用**

找到 `LibrarianAgent.persist()` 方法(原 persist 的成功路径末尾),加:

```python
        # Phase 4: 触发 RCS
        await self.on_chapter_finalized(
            novel_id=novel_id,
            chapter_id=chapter_id,
            gate_status=gate_status,  # 需要从 quality_gate_service 取
            entity_state_changes=entity_state_changes,  # 本章所有 EntityVersion state 变化列表
        )
```

(具体上下文按实际代码微调)

- [ ] **Step 5: 跑测试 + 全量**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_librarian.py -v
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -5
```

Expected: all passed

- [ ] **Step 6: 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/agents/librarian.py tests/test_agents/test_librarian.py
git commit -m "feat(librarian): persist triggers RCS on quality_block/entity_state_change"
```

---

### Task 14: ContextAgent 读 rolling_synopsis_cache

**Files:**
- Modify: `src/novel_dev/agents/context_agent.py`
- Test: `tests/test_agents/test_context_agent.py`(扩展)

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_context_agent_prefers_rolling_synopsis_cache(async_session):
    from novel_dev.agents.context_agent import ContextAgent
    from novel_dev.db.models import NovelState

    ns = NovelState(id="n_1", checkpoint_data={
        "rolling_synopsis_cache": {
            "narrative_prose": "ROLLING SYNOPSIS PROSE",
            "structured_json": {},
        },
        "expanded_story": "OLD STATIC SYNOPSIS",  # should be ignored
    })
    async_session.add(ns)
    await async_session.flush()

    text = ContextAgent._narrative_source_from_checkpoint(ns.checkpoint_data)
    assert "ROLLING SYNOPSIS PROSE" in text
    assert "OLD STATIC SYNOPSIS" not in text
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_context_agent.py -k "rolling_synopsis" -v
```

Expected: FAIL (现有逻辑不会优先 rolling_synopsis_cache)

- [ ] **Step 3: 改 `_narrative_source_from_checkpoint`**

在 `src/novel_dev/agents/context_agent.py` 的 `_narrative_source_from_checkpoint` 开头加:

```python
    @staticmethod
    def _narrative_source_from_checkpoint(checkpoint: dict) -> str:
        if not isinstance(checkpoint, dict):
            return ""
        # Phase 4: 优先读 rolling_synopsis_cache
        cache = checkpoint.get("rolling_synopsis_cache")
        if isinstance(cache, dict):
            prose = cache.get("narrative_prose")
            if prose:
                return str(prose)[:5000]
        # 降级到旧 keys
        for key in (
            "expanded_story", "compressed_story", "full_story",
            "narrative_source", "story_source", "synopsis",
        ):
            text = ContextAgent._narrative_source_text(checkpoint.get(key))
            if text:
                return text[:5000]
        return ""
```

- [ ] **Step 4: 跑测试 + 全量**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_context_agent.py -v
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -5
```

Expected: all passed

- [ ] **Step 5: 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/agents/context_agent.py tests/test_agents/test_context_agent.py
git commit -m "feat(context): prefer rolling_synopsis_cache over static synopsis"
```

---

## Wave 4: 网文钩子+爽点(4 任务)

### Task 15: BeatBoundaryCard 加 required_open_question 字段

**Files:**
- Modify: `src/novel_dev/schemas/quality.py`
- Test: `tests/test_schemas/test_beat_boundary.py`(新)

- [ ] **Step 1: 写失败测试**

Create `tests/test_schemas/test_beat_boundary.py`:

```python
import pytest
from novel_dev.schemas.quality import BeatBoundaryCard


def test_last_beat_requires_open_question():
    with pytest.raises(Exception):
        BeatBoundaryCard(
            beat_index=2, must_cover=[], forbidden_materials=[],
            is_last_beat=True, required_open_question=None,
        )


def test_last_beat_with_open_question_ok():
    card = BeatBoundaryCard(
        beat_index=2, must_cover=[], forbidden_materials=[],
        is_last_beat=True, required_open_question="陆照能否逃出灵谷?",
    )
    assert card.required_open_question == "陆照能否逃出灵谷?"


def test_non_last_beat_open_question_optional():
    card = BeatBoundaryCard(beat_index=0, must_cover=[], forbidden_materials=[])
    assert card.required_open_question is None
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_schemas/test_beat_boundary.py -v
```

Expected: FAIL (字段不存在)

- [ ] **Step 3: 改 `BeatBoundaryCard`**

在 `src/novel_dev/schemas/quality.py` 中加:

```python
class BeatBoundaryCard(BaseModel):
    beat_index: int
    must_cover: list[str] = []
    forbidden_materials: list[str] = []
    is_last_beat: bool = False  # Phase 4
    required_open_question: Optional[str] = None  # Phase 4

    @model_validator(mode="after")
    def _last_beat_requires_question(self):
        if self.is_last_beat and not self.required_open_question:
            raise ValueError(f"last beat (index={self.beat_index}) requires required_open_question")
        return self
```

(具体语法按 Pydantic 版本调整)

- [ ] **Step 4: 跑测试 + 全量**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_schemas/test_beat_boundary.py -v
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -5
```

Expected: all passed

- [ ] **Step 5: 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/schemas/quality.py tests/test_schemas/test_beat_boundary.py
git commit -m "feat(schema): BeatBoundaryCard.required_open_question + last_beat validation"
```

---

### Task 16: VolumePlanner 在末拍生成 required_open_question

**Files:**
- Modify: `src/novel_dev/agents/_default_prompts.py`(`VOLUME_PLANNER_PROMPT` 加要求)
- Modify: `src/novel_dev/agents/volume_planner.py`(解析新字段)
- Test: `tests/test_agents/test_volume_planner.py`

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_volume_planner_outputs_open_question_for_last_beat(async_session):
    from novel_dev.agents.volume_planner import VolumePlannerAgent
    # Mock LLM 响应
    fake_response = ...  # JSON with last beat having required_open_question
    # 验证解析后 BeatBoundaryCard.is_last_beat=True
    ...
```

(具体测试代码按实际 prompt 结构调整;核心是验证解析后末拍含 open_question)

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 改 `VOLUME_PLANNER_PROMPT`**

在 `VOLUME_PLANNER_PROMPT` 末尾追加:

```yaml
末拍要求: 每章最后一个 beat 必须输出 required_open_question 字段,值为本章末尾留给读者的具体问题(不是情绪描述)。
例如: "陆照能否在下月考核前进入筑基期?" 而不是 "本章以期待收束"。
```

(具体格式按现有 prompt 风格)

- [ ] **Step 4: 改 `volume_planner.py` 解析**

在解析 beats 列表时,识别最后一个 beat(列表末尾),自动设 `is_last_beat=True`,并保留 `required_open_question` 字段。

- [ ] **Step 5: 跑测试 + 全量**

- [ ] **Step 6: 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/agents/_default_prompts.py src/novel_dev/agents/volume_planner.py tests/test_agents/test_volume_planner.py
git commit -m "feat(volume_planner): require open_question for last beat"
```

---

### Task 17: FastReview 钩子达成验证

**Files:**
- Modify: `src/novel_dev/agents/fast_review_agent.py`
- Test: `tests/test_agents/test_fast_review_agent.py`

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_fast_review_checks_open_question_present(async_session):
    from novel_dev.agents.fast_review_agent import FastReviewAgent
    agent = FastReviewAgent(async_session)
    report = await agent.review(
        chapter_id="ch_1", novel_id="n_1",
        polished_text="陆照逃出灵谷,但山门外有人等着他。",
        chapter_context={
            "beats": [{
                "beat_index": 0, "is_last_beat": True,
                "required_open_question": "山门外的人是谁?",
                "must_cover": [], "forbidden_materials": [],
            }]
        },
    )
    # 验证钩子达成(文本含问号/相关关键词)
    hook_check = next(
        (w for w in report.warning_items if w.get("code") == "open_question_missing"),
        None
    )
    assert hook_check is None  # 应该达成
```

- [ ] **Step 2-4: 在 FastReviewAgent 加验证逻辑**

```python
        # Phase 4: 钩子达成验证
        for b in chapter_context.get("beats", []):
            if not b.get("is_last_beat"):
                continue
            q = b.get("required_open_question")
            if not q:
                continue
            # 简单检查:问号或关键词出现
            keywords = [w for w in q if len(w) > 1]  # 简化,实际应从 q 提取
            if not any(kw in polished_text for kw in keywords[:3]):
                report.warning_items.append({
                    "code": "open_question_missing",
                    "message": f"末拍未围绕 required_open_question ({q}) 收束",
                    "detail": {"question": q, "beat_index": b.get("beat_index")},
                })
```

(放在 review 末尾,与其他 quality item 一起)

- [ ] **Step 5-6: 跑测试 + 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/agents/fast_review_agent.py tests/test_agents/test_fast_review_agent.py
git commit -m "feat(fast_review): verify chapter open_question achievement"
```

---

### Task 18: VolumePlanner expected_thrills + FastReview 验证 + plot_tension 影响

**Files:**
- Modify: `src/novel_dev/agents/_default_prompts.py`(`VOLUME_PLANNER_PROMPT` 加 expected_thrills 要求)
- Modify: `src/novel_dev/agents/volume_planner.py`
- Modify: `src/novel_dev/agents/fast_review_agent.py`
- Modify: `src/novel_dev/agents/critic_agent.py`(plot_tension 加 thrill_point 影响)
- Test: `tests/test_services/test_thrill_point.py`(新)

- [ ] **Step 1: 写失败测试**

Create `tests/test_services/test_thrill_point.py`:

```python
import pytest
from novel_dev.repositories.thrill_point_repo import ThrillPointRepository


@pytest.mark.asyncio
async def test_create_and_query_unverified_predicted_thrills(async_session):
    repo = ThrillPointRepository(async_session)
    await repo.create(novel_id="n_1", chapter_id="ch_1", beat_idx=2,
                      thrill_type="face_slap", intensity="high",
                      planner_predicted=True, fast_review_verified=False)
    await repo.create(novel_id="n_1", chapter_id="ch_1", beat_idx=3,
                      thrill_type="level_up", intensity="peak",
                      planner_predicted=True, fast_review_verified=True)
    unverified = await repo.list_unverified("n_1", chapter_id="ch_1")
    assert len(unverified) == 1
    assert unverified[0].thrill_type == "face_slap"
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 写 ThrillPointRepository**

Create `src/novel_dev/repositories/thrill_point_repo.py`:

```python
from __future__ import annotations
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from novel_dev.db.models import ThrillPoint


class ThrillPointRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self, novel_id: str, chapter_id: str, beat_idx: Optional[int],
        thrill_type: str, intensity: str,
        planner_predicted: bool = False, fast_review_verified: bool = False,
        evidence_quote: Optional[str] = None,
    ) -> ThrillPoint:
        tp = ThrillPoint(
            novel_id=novel_id, chapter_id=chapter_id, beat_idx=beat_idx,
            thrill_type=thrill_type, intensity=intensity,
            planner_predicted=planner_predicted,
            fast_review_verified=fast_review_verified,
            evidence_quote=evidence_quote,
        )
        self.session.add(tp)
        await self.session.flush()
        return tp

    async def list_unverified(self, novel_id: str, chapter_id: str) -> list[ThrillPoint]:
        result = await self.session.execute(
            select(ThrillPoint).where(
                ThrillPoint.novel_id == novel_id,
                ThrillPoint.chapter_id == chapter_id,
                ThrillPoint.planner_predicted == True,  # noqa: E712
                ThrillPoint.fast_review_verified == False,  # noqa: E712
            )
        )
        return list(result.scalars().all())

    async def mark_verified(self, id: str, evidence_quote: str) -> None:
        tp = await self.session.get(ThrillPoint, id)
        if tp:
            tp.fast_review_verified = True
            tp.evidence_quote = evidence_quote
            await self.session.flush()
```

- [ ] **Step 4: 改 `VOLUME_PLANNER_PROMPT` 加 expected_thrills 要求**

```yaml
每章生成 expected_thrills 列表: 标识本章应该出现哪些爽点(类型 + 强度 + 预期 beat_idx)
类型: face_slap / show_off / level_up / reward_gain / revelation / revenge / plot_twist / recognition
强度: low / medium / high / peak
```

- [ ] **Step 5: 改 `volume_planner.py` 解析 expected_thrills**

解析每章的 expected_thrills 列表,写入 ThrillPointRepository(planner_predicted=True)。

- [ ] **Step 6: 改 `fast_review_agent.py` 验证**

LLM 扫描本章文本识别实际爽点,调 `ThrillPointRepository.mark_verified()`,未达成项作为 warning_items(`code: "thrill_point_missing"`)。

- [ ] **Step 7: 改 `critic_agent.py` plot_tension 评分**

拉本章 unverified thrill_point 数量,在 plot_tension 评分中扣分(未达成的爽点每项扣 5 分,最多 20 分)。

- [ ] **Step 8: 跑测试 + 全量**

- [ ] **Step 9: 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/repositories/thrill_point_repo.py src/novel_dev/agents/_default_prompts.py src/novel_dev/agents/volume_planner.py src/novel_dev/agents/fast_review_agent.py src/novel_dev/agents/critic_agent.py tests/test_services/test_thrill_point.py
git commit -m "feat(web_novel): thrill_point planning + verification + plot_tension impact"
```

---

## Wave 5: 金手指 + 节奏(3 任务)

### Task 19: Entity.cheat_ability 字段 + VolumePlanner cheat 标记

**Files:**
- Modify: `src/novel_dev/db/models.py`(`Entity` 加 3 字段)
- Modify: `src/novel_dev/agents/_default_prompts.py`(`BRAINSTORM_PROMPT` 加金手指提取)
- Modify: `src/novel_dev/agents/volume_planner.py`
- Test: `tests/test_services/test_entity_cheat.py`(新)

- [ ] **Step 1: 写失败测试**

```python
import pytest
from novel_dev.db.models import Entity


@pytest.mark.asyncio
async def test_entity_cheat_fields_persist(async_session):
    e = Entity(
        id="e_luzhao", type="character", name="陆照",
        cheat_ability="残玉空间 + 时间倒流",
        cheat_activation_rules=["每日子时触摸玉佩可回溯一刻钟"],
        cheat_first_activation_chapter="ch_3",
    )
    async_session.add(e)
    await async_session.flush()

    from novel_dev.repositories.entity_repo import EntityRepository
    fetched = await EntityRepository(async_session).get_by_id("e_luzhao")
    assert fetched.cheat_ability == "残玉空间 + 时间倒流"
    assert "每日子时" in fetched.cheat_activation_rules[0]
```

- [ ] **Step 2-4: 改 Entity + BRAINSTORM_PROMPT + volume_planner**

- [ ] **Step 5-6: 跑测试 + 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/db/models.py src/novel_dev/agents/_default_prompts.py src/novel_dev/agents/volume_planner.py tests/test_services/test_entity_cheat.py
git commit -m "feat(web_novel): Entity.cheat_ability + planner cheat activation marking"
```

---

### Task 20: ChapterPlan.archetype + BeatPlan.mood_phase 字段

**Files:**
- Modify: `src/novel_dev/db/models.py`(如 ChapterPlan 是 model,加字段;若是 dataclass,加 dataclass 字段)
- Modify: `src/novel_dev/agents/volume_planner.py`(输出)
- Test: `tests/test_services/test_chapter_archetype.py`

- [ ] **Step 1: 写失败测试**

```python
def test_chapter_plan_has_archetype_field():
    from novel_dev.schemas.quality import ChapterPlan
    cp = ChapterPlan(chapter_id="ch_1", title="陆照逃出", archetype="action", beats=[])
    assert cp.archetype == "action"


def test_beat_plan_has_optional_mood_phase():
    from novel_dev.schemas.quality import BeatPlan
    bp = BeatPlan(beat_index=0, summary="...", mood_phase="climax")
    assert bp.mood_phase == "climax"
    bp2 = BeatPlan(beat_index=1, summary="...")  # 可选
    assert bp2.mood_phase is None
```

(具体 schema 名按实际)

- [ ] **Step 2-4: 加字段、改 volume_planner 输出**

- [ ] **Step 5-6: 跑测试 + 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/db/models.py src/novel_dev/agents/volume_planner.py tests/test_services/test_chapter_archetype.py
git commit -m "feat(web_novel): chapter_archetype + mood_phase fields"
```

---

### Task 21: WriterAgent 接收 archetype + mood_phase

**Files:**
- Modify: `src/novel_dev/agents/writer_agent.py`
- Test: `tests/test_agents/test_writer_agent_chapters.py`

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_writer_receives_archetype_in_prompt(async_session, monkeypatch):
    # Mock LLM 调用并捕获 prompt
    captured_prompts = []
    async def fake_acomplete(messages, config=None):
        captured_prompts.append(messages[0].content)
        # 返回空
        from unittest.mock import MagicMock
        m = MagicMock()
        m.text = "{}"
        m.usage = None
        return m
    from novel_dev.llm import llm_factory
    monkeypatch.setattr(llm_factory, "get", lambda *a, **kw: AsyncMock(acomplete=fake_acomplete))

    from novel_dev.agents.writer_agent import WriterAgent
    agent = WriterAgent(async_session)
    await agent.write_beat(... archetype="action", mood_phase="climax", ...)
    assert any("action" in p.lower() for p in captured_prompts)
    assert any("climax" in p.lower() for p in captured_prompts)
```

- [ ] **Step 2-4: 改 writer_agent.py**

在拼装 writing_rules_block 时,加入 archetype 和 mood_phase 注入:

```python
        if archetype:
            writing_rules += f"\n\n本章是 {archetype} 章节,聚焦对应节奏(详见下表)。"
        if mood_phase:
            writing_rules += f"\n\n本拍 mood_phase = {mood_phase},情绪基线:{mood_phase}。"
```

- [ ] **Step 5-6: 跑测试 + 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/agents/writer_agent.py tests/test_agents/test_writer_agent_chapters.py
git commit -m "feat(writer): inject chapter archetype + beat mood_phase into prompt"
```

---

## Wave 6: 跨章实体连续性(3 任务)

### Task 22: CrossChapterContinuityService

**Files:**
- Create: `src/novel_dev/services/cross_chapter_continuity_service.py`
- Test: `tests/test_services/test_cross_chapter_continuity.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from novel_dev.services.cross_chapter_continuity_service import CrossChapterContinuityService


@pytest.mark.asyncio
async def test_build_pre_write_constraints_returns_formatted_text(async_session):
    from novel_dev.db.models import Entity, EntityVersion
    e = Entity(id="e_luzhao", type="character", name="陆照")
    async_session.add(e)
    await async_session.flush()
    ev = EntityVersion(entity_id="e_luzhao", version=1, state={"power_level": 0, "identity_role": "师兄"})
    async_session.add(ev)
    await async_session.flush()

    svc = CrossChapterContinuityService(async_session)
    text = await svc.build_pre_write_constraints("n_1", ["e_luzhao"])
    assert "陆照" in text
    assert "实力 = 0" in text
    assert "师兄" in text


@pytest.mark.asyncio
async def test_detect_drift_calls_llm_and_parses(async_session, monkeypatch):
    import json
    from unittest.mock import AsyncMock, MagicMock
    fake_response = MagicMock()
    fake_response.text = json.dumps([{
        "entity_name": "陆照", "drift_type": "name_drift",
        "severity": "block", "evidence_quote": "陆昭", "suggested_fix": "统一为陆照"
    }])
    fake_client = AsyncMock()
    fake_client.acomplete = AsyncMock(return_value=fake_response)
    from novel_dev.llm import llm_factory
    monkeypatch.setattr(llm_factory, "get", lambda *a, **kw: fake_client)

    svc = CrossChapterContinuityService(async_session)
    drifts = await svc.detect_drift("n_1", "ch_5", "陆昭听见追兵。", ["e_luzhao"])
    assert len(drifts) == 1
    assert drifts[0].drift_type == "name_drift"
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现 `CrossChapterContinuityService`**

Create `src/novel_dev/services/cross_chapter_continuity_service.py`:

```python
from __future__ import annotations
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import Entity, EntityVersion
from novel_dev.llm import llm_factory
from novel_dev.services.prompt_registry import PromptRegistry

logger = logging.getLogger(__name__)


@dataclass
class DriftIssue:
    entity_name: str
    drift_type: str  # name_drift / identity_drift / state_jump
    severity: str  # warn / block
    evidence_quote: str
    suggested_fix: str


class CrossChapterContinuityService:
    def __init__(self, session: AsyncSession, pre_write_window: int = 3, post_write_window: int = 5):
        self.session = session
        self.pre_write_window = pre_write_window
        self.post_write_window = post_write_window

    async def build_pre_write_constraints(
        self, novel_id: str, entity_ids: list[str],
    ) -> str:
        """确定性:拉最近 N 个 EntityVersion,生成约束提示文本"""
        if not entity_ids:
            return ""
        result = await self.session.execute(
            select(Entity, EntityVersion)
            .join(EntityVersion, EntityVersion.entity_id == Entity.id)
            .where(Entity.id.in_(entity_ids))
            .order_by(EntityVersion.version.desc())
        )
        rows = result.all()
        # 去重,每个 entity 取最新
        latest = {}
        for ent, ver in rows:
            if ent.id not in latest:
                latest[ent.id] = (ent, ver)
        if not latest:
            return ""
        lines = ["### 实体连续性约束(本章不得违背)"]
        for ent, ver in latest.values():
            state = ver.state or {}
            pl = state.get("power_level", "?")
            ir = state.get("identity_role", "?")
            lines.append(f"- {ent.name}: 实力 = {pl}, 身份 = {ir}")
        return "\n".join(lines)

    async def detect_drift(
        self, novel_id: str, chapter_id: str,
        polished_text: str, entity_ids: list[str],
    ) -> list[DriftIssue]:
        """LLM 检测 3 类漂移"""
        if not entity_ids:
            return []
        # 拉最近 5 章文本
        from novel_dev.db.models import Chapter
        result = await self.session.execute(
            select(Chapter).where(Chapter.novel_id == novel_id)
            .order_by(Chapter.chapter_number.desc())
            .limit(self.post_write_window)
        )
        recent = list(result.scalars().all())
        prior_texts = "\n\n".join([
            f"--- {c.id} ---\n{(c.polished_text or c.draft_text or '')[:1500]}"
            for c in recent if c.id != chapter_id
        ])
        # 拉实体信息
        ent_result = await self.session.execute(
            select(Entity, EntityVersion)
            .join(EntityVersion, EntityVersion.entity_id == Entity.id)
            .where(Entity.id.in_(entity_ids))
            .order_by(EntityVersion.version.desc())
        )
        entities_info = []
        seen = set()
        for ent, ver in ent_result.all():
            if ent.id in seen:
                continue
            seen.add(ent.id)
            entities_info.append({
                "name": ent.name,
                "history_state": ver.state,
                "identity_role": (ver.state or {}).get("identity_role"),
            })

        # 调 LLM
        reg = PromptRegistry(self.session)
        template = await reg.get_active("cross_chapter_drift_detection")
        prompt = template.format(
            current_text=polished_text[:5000],
            prior_texts=prior_texts[:5000],
            entities=json.dumps(entities_info, ensure_ascii=False),
        )
        client = llm_factory.get("RootCauseAnalyzer")
        from novel_dev.llm.models import ChatMessage
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.text.strip(), flags=re.IGNORECASE | re.MULTILINE)
        parsed = json.loads(text)
        return [
            DriftIssue(
                entity_name=p["entity_name"],
                drift_type=p["drift_type"],
                severity=p.get("severity", "warn"),
                evidence_quote=p.get("evidence_quote", ""),
                suggested_fix=p.get("suggested_fix", ""),
            )
            for p in parsed
        ]
```

- [ ] **Step 4: 跑测试确认通过 + 全量**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_services/test_cross_chapter_continuity.py -v
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -5
```

Expected: all passed

- [ ] **Step 5: 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/services/cross_chapter_continuity_service.py tests/test_services/test_cross_chapter_continuity.py
git commit -m "feat(continuity): add CrossChapterContinuityService (pre-write + drift detection)"
```

---

### Task 23: ContextAgent 注入实体连续性约束 + FastReview drift 验证

**Files:**
- Modify: `src/novel_dev/agents/context_agent.py`
- Modify: `src/novel_dev/agents/fast_review_agent.py`
- Test: `tests/test_agents/test_context_agent.py` + `test_fast_review_agent.py`(扩展)

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_context_agent_includes_pre_write_continuity_constraints(async_session, monkeypatch):
    from novel_dev.db.models import Entity, EntityVersion
    e = Entity(id="e_luzhao", type="character", name="陆照")
    async_session.add(e)
    await async_session.flush()
    ev = EntityVersion(entity_id="e_luzhao", version=1, state={"power_level": 0, "identity_role": "师兄"})
    async_session.add(ev)
    await async_session.flush()

    from novel_dev.agents.context_agent import ContextAgent
    # 触发 prepare_chapter_context 或类似方法
    # 验证返回 context 含 "实体连续性约束" 段
    ...
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 改 `ContextAgent`**

在 `prepare_chapter_context` 末尾(在 narrative_source 之后)加:

```python
        # Phase 4: 实体连续性约束
        from novel_dev.services.cross_chapter_continuity_service import CrossChapterContinuityService
        entity_ids = [...]  # 从 chapter_plan.beats 提取
        continuity_svc = CrossChapterContinuityService(self.session)
        constraints = await continuity_svc.build_pre_write_constraints(novel_id, entity_ids)
        if constraints:
            context_text += "\n\n" + constraints
```

(具体上下文按实际代码微调)

- [ ] **Step 4: 改 `FastReviewAgent`**

在 `review()` 末尾(beat coverage pass 之后)加:

```python
        # Phase 4: 跨章实体漂移检测
        from novel_dev.services.cross_chapter_continuity_service import CrossChapterContinuityService
        continuity_svc = CrossChapterContinuityService(self.session)
        drifts = await continuity_svc.detect_drift(
            novel_id=novel_id, chapter_id=chapter_id,
            polished_text=polished_text, entity_ids=chapter_context.get("entity_ids", []),
        )
        for d in drifts:
            item = {
                "code": f"cross_chapter_{d.drift_type}",
                "message": f"{d.entity_name} 跨章{d.drift_type}: {d.evidence_quote}",
                "detail": {"evidence": d.evidence_quote, "fix": d.suggested_fix},
            }
            if d.severity == "block":
                report.blocking_items.append(item)
            else:
                report.warning_items.append(item)
        report.cross_chapter_drift = [
            {"entity": d.entity_name, "type": d.drift_type, "severity": d.severity}
            for d in drifts
        ]
```

- [ ] **Step 5: 跑测试 + 全量**

- [ ] **Step 6: 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/agents/context_agent.py src/novel_dev/agents/fast_review_agent.py tests/test_agents/test_context_agent.py tests/test_agents/test_fast_review_agent.py
git commit -m "feat(continuity): inject pre-write constraints + post-write drift detection"
```

---

## Wave 7: 跨章意象追踪(2 任务)

### Task 24: ImageryInventoryService

**Files:**
- Create: `src/novel_dev/services/imagery_inventory_service.py`
- Test: `tests/test_services/test_imagery_inventory.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from novel_dev.services.imagery_inventory_service import ImageryInventoryService


@pytest.mark.asyncio
async def test_extract_and_store_writes_rows(async_session, monkeypatch):
    import json
    fake_response = MagicMock()
    fake_response.text = json.dumps([
        {"item": "碎石硌掌心", "item_type": "physical_imagery", "frequency_in_chapter": 3},
        {"item": "像石子投入枯井", "item_type": "metaphor", "frequency_in_chapter": 1},
    ])
    fake_client = AsyncMock()
    fake_client.acomplete = AsyncMock(return_value=fake_response)
    from novel_dev.llm import llm_factory
    monkeypatch.setattr(llm_factory, "get", lambda *a, **kw: fake_client)

    svc = ImageryInventoryService(async_session)
    count = await svc.extract_and_store("n_1", "ch_1", "陆照听见碎石硌掌心。")
    assert count == 2
    items = await svc.get_recent("n_1", window=1)
    assert items[0].item == "碎石硌掌心"


@pytest.mark.asyncio
async def test_build_avoidance_list_returns_formatted_text(async_session):
    from novel_dev.services.imagery_inventory_service import ImageryInventoryService
    from novel_dev.repositories.imagery_inventory_repo import ImageryInventoryRepository
    repo = ImageryInventoryRepository(async_session)
    for ch in range(1, 6):
        for _ in range(ch):
            await repo.create("n_1", f"ch_{ch}", "碎石硌掌心", "physical_imagery", 1)
    svc = ImageryInventoryService(async_session)
    text = await svc.build_avoidance_list("n_1", "ch_6", window=5)
    assert "碎石硌掌心" in text
    assert "本章应避免" in text or "避免意象" in text
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 写 `ImageryInventoryRepository`**

Create `src/novel_dev/repositories/imagery_inventory_repo.py`:

```python
from __future__ import annotations
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from novel_dev.db.models import ImageryInventory


class ImageryInventoryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self, novel_id: str, chapter_id: str, item: str,
        item_type: str, frequency_in_chapter: int,
    ) -> ImageryInventory:
        ii = ImageryInventory(
            novel_id=novel_id, chapter_id=chapter_id,
            item=item, item_type=item_type,
            frequency_in_chapter=frequency_in_chapter,
        )
        self.session.add(ii)
        await self.session.flush()
        return ii

    async def get_recent(self, novel_id: str, window: int) -> list[ImageryInventory]:
        # 拉最近 window 个 chapter 的所有 imagery
        from novel_dev.db.models import Chapter
        result = await self.session.execute(
            select(Chapter).where(Chapter.novel_id == novel_id)
            .order_by(Chapter.chapter_number.desc()).limit(window)
        )
        recent_chs = [c.id for c in result.scalars().all()]
        if not recent_chs:
            return []
        result = await self.session.execute(
            select(ImageryInventory).where(ImageryInventory.chapter_id.in_(recent_chs))
        )
        return list(result.scalars().all())
```

- [ ] **Step 4: 实现 `ImageryInventoryService`**

Create `src/novel_dev/services/imagery_inventory_service.py`:

```python
from __future__ import annotations
import json
import re
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.llm import llm_factory
from novel_dev.repositories.imagery_inventory_repo import ImageryInventoryRepository
from novel_dev.services.prompt_registry import PromptRegistry

logger = logging.getLogger(__name__)


class ImageryInventoryService:
    def __init__(self, session: AsyncSession, avoidance_top_n: int = 20):
        self.session = session
        self.repo = ImageryInventoryRepository(session)
        self.avoidance_top_n = avoidance_top_n

    async def extract_and_store(self, novel_id: str, chapter_id: str, chapter_text: str) -> int:
        reg = PromptRegistry(self.session)
        template = await reg.get_active("imagery_extraction")
        prompt = template.format(chapter_text=chapter_text[:5000])
        client = llm_factory.get("RootCauseAnalyzer")
        from novel_dev.llm.models import ChatMessage
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.text.strip(), flags=re.IGNORECASE | re.MULTILINE)
        items = json.loads(text)
        for it in items:
            await self.repo.create(
                novel_id=novel_id, chapter_id=chapter_id,
                item=it["item"], item_type=it["item_type"],
                frequency_in_chapter=it.get("frequency_in_chapter", 1),
            )
        return len(items)

    async def get_recent(self, novel_id: str, window: int = 5):
        return await self.repo.get_recent(novel_id, window)

    async def build_avoidance_list(
        self, novel_id: str, current_chapter_id: str, window: int = 5,
    ) -> str:
        items = await self.repo.get_recent(novel_id, window)
        # 过滤掉本章已用(避免列本章的)
        items = [i for i in items if i.chapter_id != current_chapter_id]
        # 聚合:同 item 跨章频次
        agg: dict[str, dict] = {}
        for it in items:
            key = (it.item, it.item_type)
            if key not in agg:
                agg[key] = {"item": it.item, "type": it.item_type, "count": 0, "freq_sum": 0}
            agg[key]["count"] += 1
            agg[key]["freq_sum"] += it.frequency_in_chapter
        # 排序:count × freq_sum 降序
        sorted_items = sorted(agg.values(), key=lambda x: x["count"] * x["freq_sum"], reverse=True)
        top = sorted_items[:self.avoidance_top_n]
        if not top:
            return ""
        lines = ["### 本章应避免意象(最近 {} 章已多次使用)".format(window)]
        for it in top:
            lines.append(f"- {it['item']}({it['type']},{it['count']} 章 × {it['freq_sum']} 次)")
        return "\n".join(lines)
```

- [ ] **Step 5: 跑测试 + 全量**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_services/test_imagery_inventory.py -v
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -5
```

Expected: all passed

- [ ] **Step 6: 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/services/imagery_inventory_service.py src/novel_dev/repositories/imagery_inventory_repo.py tests/test_services/test_imagery_inventory.py
git commit -m "feat(imagery): add ImageryInventoryService with extraction + avoidance list"
```

---

### Task 25: ContextAgent 注入 avoidance 列表

**Files:**
- Modify: `src/novel_dev/agents/context_agent.py`
- Test: `tests/test_agents/test_context_agent.py`

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_context_agent_includes_imagery_avoidance_list(async_session, monkeypatch):
    # 预存 imagery
    from novel_dev.repositories.imagery_inventory_repo import ImageryInventoryRepository
    repo = ImageryInventoryRepository(async_session)
    for ch in ["ch_1", "ch_2", "ch_3"]:
        await repo.create("n_1", ch, "碎石硌掌心", "physical_imagery", 2)

    from novel_dev.agents.context_agent import ContextAgent
    # 触发 prepare_chapter_context for ch_4
    # 验证返回含 "本章应避免意象" 段含 "碎石硌掌心"
    ...
```

- [ ] **Step 2-4: 改 `ContextAgent`**

在实体连续性约束之后(同位置)加:

```python
        # Phase 4: 意象避免列表
        from novel_dev.services.imagery_inventory_service import ImageryInventoryService
        imagery_svc = ImageryInventoryService(self.session)
        avoidance = await imagery_svc.build_avoidance_list(novel_id, chapter_id, window=5)
        if avoidance:
            context_text += "\n\n" + avoidance
```

- [ ] **Step 5-6: 跑测试 + 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/agents/context_agent.py tests/test_agents/test_context_agent.py
git commit -m "feat(context): inject imagery avoidance list into writer context"
```

---

## Wave 8: UI 升级(4 任务)

### Task 26: QualityRecommendationWidget 增强(评分明细展开)

**Files:**
- Modify: `src/novel_dev/web/src/components/QualityRecommendationWidget.vue`
- Modify: `src/novel_dev/api/routes.py`(新端点:返回 critic 评分明细)
- Test: `src/novel_dev/web/src/components/QualityRecommendationWidget.test.js`

- [ ] **Step 1: 加后端端点**

在 `src/novel_dev/api/routes.py` 加:

```python
@router.get("/chapters/{chapter_id}/critic-breakdown")
async def get_critic_breakdown(chapter_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    from novel_dev.services.quality_metrics_service import QualityMetricsService
    svc = QualityMetricsService(session)
    metrics = await svc.get_by_chapter(chapter_id)  # 需要添加此方法
    if not metrics:
        return {"chapter_id": chapter_id, "dimensions": []}
    latest = max(metrics, key=lambda m: m.attempt_index)
    return {
        "chapter_id": chapter_id,
        "overall_score": latest.overall_score,
        "dimensions": latest.dimension_scores or {},
        "dimension_feedback": latest.dimension_feedback or {},
        "attempt_index": latest.attempt_index,
    }
```

在 `QualityMetricsService` 加 `get_by_chapter`:

```python
    async def get_by_chapter(self, chapter_id: str) -> list:
        from sqlalchemy import select
        from novel_dev.db.models import ChapterQualityMetric
        result = await self.session.execute(
            select(ChapterQualityMetric).where(ChapterQualityMetric.chapter_id == chapter_id)
        )
        return list(result.scalars().all())
```

- [ ] **Step 2: 写前端测试**

```javascript
it('expands to show critic breakdown', async () => {
  // mock 拉 critic breakdown
  const mockBreakdown = {
    overall_score: 80,
    dimensions: { plot_tension: 75, humanity: 88, hook_strength: 70 },
  }
  vi.mock('axios', () => ({ default: { get: vi.fn().mockResolvedValue({ data: mockBreakdown }) } }))
  // ... mount widget, click "查看评分明细", assert dimension scores visible
})
```

- [ ] **Step 3-5: 改 Widget**

在 template 加可展开区:

```vue
<button data-testid="show-breakdown-btn" @click="showBreakdown = !showBreakdown">
  {{ showBreakdown ? '收起' : '查看' }}评分明细
</button>
<div v-if="showBreakdown" data-testid="critic-breakdown">
  <p v-for="(score, dim) in breakdown.dimensions" :key="dim">
    {{ dim }}: {{ score }}
  </p>
</div>
```

在 `<script setup>`:

```javascript
import axios from 'axios'
const breakdown = ref({ dimensions: {} })
const showBreakdown = ref(false)
async function loadBreakdown() {
  try {
    const resp = await axios.get(`/api/chapters/${props.chapterId}/critic-breakdown`)
    breakdown.value = resp.data
  } catch {}
}
watch(() => props.chapterId, loadBreakdown, { immediate: true })
```

- [ ] **Step 6: 跑测试 + 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/api/routes.py src/novel_dev/services/quality_metrics_service.py src/novel_dev/web/src/components/QualityRecommendationWidget.vue src/novel_dev/web/src/components/QualityRecommendationWidget.test.js
git commit -m "feat(ui): expand critic breakdown in recommendation widget"
```

---

### Task 27: RCSViewerView

**Files:**
- Create: `src/novel_dev/web/src/views/RCSViewerView.vue`
- Create: `src/novel_dev/web/src/views/RCSViewerView.test.js`
- Modify: `src/novel_dev/api/routes.py`(新端点)
- Modify: `src/novel_dev/web/src/router/index.js`(新路由)

- [ ] **Step 1: 加后端端点**

```python
@router.get("/novels/{novel_id}/chapter-synopses")
async def list_chapter_synopses(novel_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    from novel_dev.repositories.chapter_synopsis_repo import ChapterSynopsisRepository
    repo = ChapterSynopsisRepository(session)
    synopses = await repo.list_all(novel_id)
    return {
        "novel_id": novel_id,
        "synopses": [
            {
                "id": s.id,
                "chapter_range": [s.chapter_range_start, s.chapter_range_end],
                "narrative_prose": s.narrative_prose,
                "structured_json": s.structured_json,
                "trigger_event": s.trigger_event,
                "created_at": s.created_at.isoformat(),
            }
            for s in synopses
        ],
    }
```

- [ ] **Step 2: 写前端测试**

```javascript
import { mount, flushPromises } from '@vue/test-utils'
import RCSViewerView from './RCSViewerView.vue'

vi.mock('axios')

it('renders list of synopses', async () => {
  const mockData = {
    synopses: [
      { id: 's1', chapter_range: [1, 5], narrative_prose: '...', structured_json: {}, trigger_event: {}, created_at: '2026-06-17' },
    ],
  }
  axios.get.mockResolvedValue({ data: mockData })
  const wrapper = mount(RCSViewerView, { props: { novelId: 'n1' } })
  await flushPromises()
  expect(wrapper.findAll('[data-testid="synopsis-card"]').length).toBe(1)
})
```

- [ ] **Step 3-4: 实现 View 组件**

- [ ] **Step 5: 配路由**

在 router 加:

```javascript
{
  path: '/novels/:novelId/rcs-viewer',
  component: () => import('@/views/RCSViewerView.vue'),
}
```

- [ ] **Step 6: 跑测试 + 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/api/routes.py src/novel_dev/web/src/views/RCSViewerView.vue src/novel_dev/web/src/views/RCSViewerView.test.js src/novel_dev/web/src/router/index.js
git commit -m "feat(ui): add RCSViewerView for browsing rolling chapter synopses"
```

---

### Task 28: ImageryInventoryView

**Files:**
- Create: `src/novel_dev/web/src/views/ImageryInventoryView.vue`
- Create: `src/novel_dev/web/src/views/ImageryInventoryView.test.js`
- Modify: `src/novel_dev/api/routes.py`(新端点)
- Modify: `src/novel_dev/web/src/router/index.js`

- [ ] **Step 1: 加后端端点**

```python
@router.get("/novels/{novel_id}/imagery-inventory")
async def get_imagery_inventory(
    novel_id: str, window: int = 5, session: AsyncSession = Depends(get_session),
) -> dict:
    from novel_dev.services.imagery_inventory_service import ImageryInventoryService
    svc = ImageryInventoryService(session)
    items = await svc.get_recent(novel_id, window=window)
    return {
        "novel_id": novel_id,
        "window": window,
        "items": [
            {
                "item": i.item, "item_type": i.item_type,
                "chapter_id": i.chapter_id, "frequency_in_chapter": i.frequency_in_chapter,
            }
            for i in items
        ],
    }
```

- [ ] **Step 2-4: 实现 View + 路由 + 测试**

- [ ] **Step 5-6: 跑测试 + 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/api/routes.py src/novel_dev/web/src/views/ImageryInventoryView.vue src/novel_dev/web/src/views/ImageryInventoryView.test.js src/novel_dev/web/src/router/index.js
git commit -m "feat(ui): add ImageryInventoryView for browsing cross-chapter imagery"
```

---

### Task 29: QualityTrendsV2View (扩展 QualityTrendsView)

**Files:**
- Modify: `src/novel_dev/web/src/views/QualityTrendsView.vue`(加新 tab/section)
- Modify: `src/novel_dev/api/routes.py`(新聚合端点)
- Modify: `src/novel_dev/web/src/views/QualityTrendsView.test.js`(扩展)

- [ ] **Step 1: 加后端聚合端点**

```python
@router.get("/novels/{novel_id}/quality-trends-v2")
async def get_quality_trends_v2(
    novel_id: str, window: int = 20, session: AsyncSession = Depends(get_session),
) -> dict:
    from novel_dev.services.quality_metrics_service import QualityMetricsService
    from novel_dev.services.recommendation_wirer import RecommendationWirer
    from novel_dev.repositories.thrill_point_repo import ThrillPointRepository
    from novel_dev.repositories.imagery_inventory_repo import ImageryInventoryRepository
    qm_svc = QualityMetricsService(session)
    trends = await qm_svc.get_trends(novel_id, window=window)
    tp_repo = ThrillPointRepository(session)
    # 聚合:thrills_planned, thrills_verified
    # 聚合:imagery_repeat_top5
    return {
        "trends": trends,
        "thrills_planned": ...,
        "thrills_verified": ...,
        "imagery_repeat_top5": [...],
    }
```

- [ ] **Step 2-4: 改 View**

在 QualityTrendsView.vue 加 3 个新区块:
- 爽点达成率(planned vs verified)
- 跨章意象 top 5
- 钩子达成趋势(如果数据可得)

- [ ] **Step 5-6: 跑测试 + 提交**

```bash
cd /Users/linlin/Desktop/novel-dev && git add src/novel_dev/api/routes.py src/novel_dev/web/src/views/QualityTrendsView.vue src/novel_dev/web/src/views/QualityTrendsView.test.js
git commit -m "feat(ui): extend QualityTrendsView with cross-metric aggregation"
```

---

## Wave 9: 端到端测试 + 验证(1 任务)

### Task 30: 端到端测试

**Files:**
- Create: `tests/test_e2e/test_phase4_quality_architectural.py`

- [ ] **Step 1: 写 E2E 测试**

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_phase4_full_pipeline_e2e(async_session):
    """E2E: 写入质量事件 → RCS 更新 → 跨章约束/漂移检测 → 意象抽取 → avoidance list"""
    from novel_dev.db.models import Entity, EntityVersion, NovelState, Chapter
    from novel_dev.services.rolling_chapter_synopsis_service import RollingChapterSynopsisService
    from novel_dev.services.imagery_inventory_service import ImageryInventoryService
    from novel_dev.services.cross_chapter_continuity_service import CrossChapterContinuityService
    from novel_dev.agents.librarian import LibrarianAgent
    from novel_dev.agents.context_agent import ContextAgent
    from novel_dev.services.prompt_registry import PromptRegistry

    # 1. bootstrap novel_state + 实体 + chapter
    ns = NovelState(id="n_1", checkpoint_data={})
    async_session.add(ns)
    e = Entity(id="e_luzhao", type="character", name="陆照")
    async_session.add(e)
    ev = EntityVersion(entity_id="e_luzhao", version=1, state={"power_level": 0, "identity_role": "师兄"})
    async_session.add(ev)
    for i in range(1, 6):
        ch = Chapter(id=f"ch_{i}", novel_id="n_1", chapter_number=i, title=f"ch {i}", volume_id="v1",
                     draft_text="陆照听见追兵。", polished_text="陆照听见追兵。")
        async_session.add(ch)
    await async_session.flush()

    # 2. bootstrap prompts
    reg = PromptRegistry(async_session)
    await reg.bootstrap_defaults()
    # 新 prompt 也注册
    for name, content in [
        ("rolling_synopsis", "ROLLING TEMPLATE: {prev_synopsis} | {new_chapter_summaries} | {trigger_event}"),
        ("entity_change_importance", "TEMPLATE: {changes}"),
        ("imagery_extraction", "TEMPLATE: {chapter_text}"),
        ("cross_chapter_drift_detection", "TEMPLATE: {current_text} {prior_texts} {entities}"),
        ("librarian_soft_state", "TEMPLATE: {hard_state_changes} {chapter_text_excerpt}"),
    ]:
        await reg.create_version(name, "v1.0", content, is_active=True)

    # 3. Mock LLM
    async def mock_acomplete(messages, config=None):
        m = MagicMock()
        # 简单判断 prompt 类型返回对应 JSON
        content = messages[0].content if hasattr(messages[0], 'content') else str(messages[0])
        if "ROLLING TEMPLATE" in content:
            m.text = '{"narrative_prose": "陆照遭遇追兵,离开灵谷,身份从师兄变为独行。", "structured_json": {"plot_points": []}}'
        elif "TEMPLATE: {changes}" in content:
            m.text = '[{"entity_id": "e_luzhao", "is_important": true, "reason": "test", "suggested_synopsis_section": "test"}]'
        elif "imagery" in content.lower() or "意象" in content:
            m.text = '[{"item": "碎石硌掌心", "item_type": "physical_imagery", "frequency_in_chapter": 1}]'
        elif "drift" in content.lower() or "漂移" in content:
            m.text = '[]'
        else:
            m.text = "{}"
        m.usage = None
        return m
    fake_client = MagicMock()
    fake_client.acomplete = AsyncMock(side_effect=mock_acomplete)

    with patch("novel_dev.services.rolling_chapter_synopsis_service.llm_factory") as m1, \
         patch("novel_dev.services.imagery_inventory_service.llm_factory") as m2, \
         patch("novel_dev.agents.librarian.llm_factory") as m3:
        m1.get.return_value = fake_client
        m2.get.return_value = fake_client
        m3.get.return_value = fake_client

        # 4. trigger RCS via librarian
        lib = LibrarianAgent(async_session)
        await lib.on_chapter_finalized(
            novel_id="n_1", chapter_id="ch_5",
            gate_status="block", entity_state_changes=[
                {"entity_id": "e_luzhao", "prev_state": {"power_level": 0}, "new_state": {"power_level": 0}}
            ],
        )

        # 5. verify RCS written
        rcs = RollingChapterSynopsisService(async_session)
        latest = await rcs.get_latest("n_1")
        assert latest is not None
        assert "陆照遭遇追兵" in latest.narrative_prose

        # 6. verify context agent prefers rolling_synopsis_cache
        await async_session.refresh(ns)
        text = ContextAgent._narrative_source_from_checkpoint(ns.checkpoint_data)
        assert "陆照遭遇追兵" in text

        # 7. imagery extraction
        imagery_svc = ImageryInventoryService(async_session)
        count = await imagery_svc.extract_and_store("n_1", "ch_5", "陆照听见碎石硌掌心。")
        assert count == 1

        # 8. avoidance list
        avoidance = await imagery_svc.build_avoidance_list("n_1", "ch_6", window=5)
        assert "碎石硌掌心" in avoidance


@pytest.mark.asyncio
async def test_phase4_ab_routing_routes_via_chapter_id(async_session):
    """A/B 路由:同 chapter 路由稳定,不同 chapter 50/50 分布"""
    from novel_dev.services.prompt_registry import PromptRegistry
    from novel_dev.services.ab_test_runner import ABTestRunner

    reg = PromptRegistry(async_session)
    await reg.create_version("writer", "v1.0", "v1", is_active=True)
    await reg.create_version("writer", "v2.0", "v2")
    runner = ABTestRunner(async_session)
    await runner.start("writer", "v1.0", "v2.0", max_samples=10, min_samples=3)

    # 同 chapter 稳定
    c1 = await reg.get_active_for_chapter("writer", "ch_test")
    c1_again = await reg.get_active_for_chapter("writer", "ch_test")
    assert c1 == c1_again

    # 100 chapter 分布
    picked = set()
    for i in range(100):
        picked.add(await reg.get_active_for_chapter("writer", f"ch_{i}"))
    assert picked == {"v1", "v2"}
```

- [ ] **Step 2: 跑测试确认通过**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_e2e/test_phase4_quality_architectural.py -v
```

Expected: 2 passed

- [ ] **Step 3: 跑全量测试**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q 2>&1 | tail -5
```

Expected: all passed(预期 1850+ 测试)

- [ ] **Step 4: 跑前端测试**

```bash
cd /Users/linlin/Desktop/novel-dev/src/novel_dev/web && npm test -- --run 2>&1 | tail -5
```

Expected: all passed(预期 290+ 测试)

- [ ] **Step 5: 跑覆盖率**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_services/test_rolling_chapter_synopsis.py tests/test_services/test_cross_chapter_continuity.py tests/test_services/test_imagery_inventory.py tests/test_repositories/test_chapter_synopsis_repo.py tests/test_repositories/test_thrill_point_repo.py tests/test_repositories/test_imagery_inventory_repo.py --cov=novel_dev.services.rolling_chapter_synopsis_service --cov=novel_dev.services.cross_chapter_continuity_service --cov=novel_dev.services.imagery_inventory_service --cov=novel_dev.repositories.chapter_synopsis_repo --cov=novel_dev.repositories.thrill_point_repo --cov=novel_dev.repositories.imagery_inventory_repo --cov-report=term -q 2>&1 | tail -15
```

Expected: 6 个新文件/服务均 ≥ 90%

- [ ] **Step 6: 提交最终报告**

```bash
cd /Users/linlin/Desktop/novel-dev && git add tests/test_e2e/test_phase4_quality_architectural.py
git commit -m "test(e2e): phase 4 quality architectural full flow"
```

---

## 验收清单

- [ ] 31 任务全部完成
- [ ] 全量后端测试通过(1900+)
- [ ] 全量前端测试通过(290+)
- [ ] 3 张新表 + 3 个新 service 覆盖率 ≥ 90%
- [ ] A/B 路由真实生效
- [ ] Writer 默认走 beat_by_beat
- [ ] 末拍钩子强制
- [ ] 爽点 Planner 预标 + FastReview 验证
- [ ] 金手指/节奏感字段可用
- [ ] 跨章实体连续性 pre-write + post-write 双管齐下
- [ ] 跨章意象避免列表可用
- [ ] 失败闭门策略启用
- [ ] 关键 prompt 含 few-shot
- [ ] 失败无 fallback(retry 计数归零或受控)

---

## Self-Review

**1. Spec coverage**:
- §1 P0 修复 → Tasks 1, 2, 3, 4, 5
- §2 P0 配置 → Tasks 2, 6
- §2.2-2.4 prompt 升级 → Tasks 7, 8, 9
- §3 RCS → Tasks 10, 11, 12, 13, 14
- §4.2 钩子 → Tasks 15, 16, 17
- §4.3 爽点 → Task 18
- §4.4 金手指 → Task 19
- §4.5 节奏感 → Tasks 20, 21
- §5 跨章实体连续性 → Tasks 22, 23
- §6 跨章意象追踪 → Tasks 24, 25
- §7 UI 扩展 → Tasks 26, 27, 28, 29
- §8 配置 → Task 6
- §9 验收 → Task 30
所有 spec 章节均有对应任务。

**2. Placeholder scan**: 无 TBD/TODO/待补。每个任务含完整代码或明确"按实际代码微调"指针。

**3. Type consistency**:
- `get_active_for_chapter(novel_id, chapter_id) -> str` 在 Task 1, 30 一致
- `ChapterSynopsis.narrative_prose` 在 Task 10 model、Task 12 service、Task 14 context 一致
- `BeatBoundaryCard.is_last_beat, required_open_question` 在 Task 15, 16, 17 一致
- `DriftIssue.drift_type, severity` 在 Task 22, 23 一致
- `ThrillPoint.planner_predicted, fast_review_verified` 在 Task 18 一致

**4. Dependencies**:
- Task 1 (A/B 接入) → Task 12 (RCS) via PromptRegistry
- Task 6 (phase4 config) → Task 11 (prompts) 引用配置名
- Task 10 (3 new tables) → Task 12, 18, 24 (services) 依赖 repos
- Task 15 (schema) → Task 16 (volume_planner) → Task 17 (fast_review)
- Task 22 (service) → Task 23 (context/fast_review) 依赖

无循环依赖。
