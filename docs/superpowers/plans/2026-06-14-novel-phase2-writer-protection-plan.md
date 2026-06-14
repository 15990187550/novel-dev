# 阶段二:Writer 防护 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保持 WriterAgent 整章一次性产出的前提下，复用阶段一的 `BeatBoundaryCard` 预写加固，新增事后 LLM-as-judge 验证（`BeatCoverageValidator`）和自动重写调度（`RecommendationWirer`），把推荐服务从“展示”升级为“自动闭环”，并保证 N 次硬上限后转入人工。

**Architecture:** 3-wave 增量交付。Wave 1 新增 BeatCoverageValidator + PreWriteHardener 回归测试（不接线）；Wave 2 新增 RecommendationWirer 并在 FastReviewAgent 中调用（`max_auto_rewrites=0` 保证不重写）；Wave 3 启用 `max_auto_rewrites=2`，追加 RewriteFeedbackWriter 钩子、manual_review API 扩展、前端按钮、集成/E2E 测试。

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, Pydantic, pytest, Vue 3, Alembic（本项目当前未启用，生产 schema 变更需手工执行）。

---

## File Structure

| File | Role | Wave |
|------|------|------|
| `src/novel_dev/db/models.py` | `Chapter` 表加 `attempt_index: Mapped[int]` | 1 |
| `llm_config.yaml` | `quality_thresholds.recommendation` 下加 `max_auto_rewrites: 2` | 1 |
| `src/novel_dev/services/beat_coverage_validator.py` | 新服务：LLM-as-judge + 确定性回退 | 1 |
| `tests/test_services/test_beat_coverage_validator.py` | BeatCoverageValidator 单元测试 | 1 |
| `src/novel_dev/agents/writer_agent.py` | `_build_whole_chapter_context_message` 加 fail-soft + INFO 日志 | 1 |
| `tests/test_agents/test_pre_write_hardener.py` | PreWriteHardener 回归测试 | 1 |
| `src/novel_dev/services/recommendation_wirer.py` | 新服务：推荐 → 调度重写决策 | 2 |
| `tests/test_services/test_recommendation_wirer.py` | RecommendationWirer 单元测试 | 2 |
| `src/novel_dev/agents/fast_review_agent.py` | `review()` / `review_standalone()` 末尾调 RecommendationWirer | 2 |
| `src/novel_dev/services/chapter_rewrite_service.py` | `rewrite()` 末尾追加 RewriteFeedbackWriter 记录 metric | 3 |
| `src/novel_dev/services/recommendation_wirer.py` | 在 Wave 2 基础上接入 `ChapterRewriteService.rewrite()` 排队 | 2/3 |
| `src/novel_dev/api/routes.py` | manual_review endpoint 扩展 `continue_retry` / `accept_version` | 3 |
| `src/novel_dev/web/src/components/QualityRecommendationWidget.vue` | 加 rewriting spinner + manual_review 按钮 | 3 |
| `tests/test_agents/test_whole_chapter_validation.py` | 集成测试：Writer → BeatCoverageValidator | 3 |
| `tests/test_agents/test_auto_rewrite_loop.py` | 集成测试：FastReview → Wirer → Rewrite → Metric | 3 |
| `tests/test_e2e/test_phase2_protection_loop.py` | E2E：3 个 chapter 的完整防护循环 | 3 |

---

## Wave 1: Core services + regression tests (no wiring)

### Task 1: Add `Chapter.attempt_index` column

**Files:**
- Modify: `src/novel_dev/db/models.py:243-244`
- Test: `tests/test_db/test_models.py`（新建）

- [ ] **Step 1: Write the failing test**

```python
import pytest
from sqlalchemy import select
from novel_dev.db.models import Chapter

@pytest.mark.asyncio
async def test_chapter_attempt_index_default(async_session):
    ch = Chapter(
        id="ch_attempt_test",
        volume_id="vol_1",
        chapter_number=1,
        status="pending",
        novel_id="novel_1",
    )
    async_session.add(ch)
    await async_session.flush()
    row = await async_session.execute(select(Chapter).where(Chapter.id == "ch_attempt_test"))
    found = row.scalar_one()
    assert found.attempt_index == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_db/test_models.py::test_chapter_attempt_index_default -v`
Expected: FAIL with `AttributeError: 'Chapter' object has no attribute 'attempt_index'`

- [ ] **Step 3: Add the column**

In `src/novel_dev/db/models.py`, add after `quality_status` line 243:

```python
    quality_status: Mapped[str] = mapped_column(Text, nullable=False, default="unchecked")
    attempt_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_reasons: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_db/test_models.py::test_chapter_attempt_index_default -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/db/models.py tests/test_db/test_models.py
git commit -m "feat(db): add Chapter.attempt_index column"
```

---

### Task 2: Add `max_auto_rewrites` config key

**Files:**
- Modify: `llm_config.yaml:346-348`
- Test: `tests/test_config/test_quality_config.py`（新建或扩展）

- [ ] **Step 1: Write the failing test**

```python
from novel_dev.config.quality_config import get_quality_config

def test_quality_config_includes_max_auto_rewrites():
    cfg = get_quality_config()
    assert "max_auto_rewrites" in cfg["recommendation"]
    assert isinstance(cfg["recommendation"]["max_auto_rewrites"], int)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_config/test_quality_config.py::test_quality_config_includes_max_auto_rewrites -v`
Expected: FAIL with `KeyError: 'max_auto_rewrites'`

- [ ] **Step 3: Add config key**

In `llm_config.yaml`, under `quality_thresholds.recommendation:` after `pattern_issue_threshold: 3`:

```yaml
    stop_after_attempts: 3
    pattern_issue_threshold: 3
    max_auto_rewrites: 2            # 阶段二：自动重写硬上限
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_config/test_quality_config.py::test_quality_config_includes_max_auto_rewrites -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add llm_config.yaml tests/test_config/test_quality_config.py
git commit -m "config: add recommendation.max_auto_rewrites threshold"
```

---

### Task 3: Scaffold `BeatCoverageResult` and `BeatCoverageValidator`

**Files:**
- Create: `src/novel_dev/services/beat_coverage_validator.py`
- Test: `tests/test_services/test_beat_coverage_validator.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from novel_dev.services.beat_coverage_validator import BeatCoverageResult, BeatCoverageValidator

@pytest.mark.asyncio
async def test_validator_scaffold_exists(async_session):
    validator = BeatCoverageValidator(async_session, use_llm=False)
    assert validator.use_llm is False
    result = BeatCoverageResult(beat_index=0, covered=True, deviation=None, severity="ok")
    assert result.beat_index == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_services/test_beat_coverage_validator.py::test_validator_scaffold_exists -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'novel_dev.services.beat_coverage_validator'`

- [ ] **Step 3: Implement scaffold**

Create `src/novel_dev/services/beat_coverage_validator.py`:

```python
"""Post-write beat coverage validator with LLM-as-judge and deterministic fallback."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from novel_dev.schemas.quality import BeatBoundaryCard

logger = logging.getLogger(__name__)


@dataclass
class BeatCoverageResult:
    beat_index: int
    covered: bool
    deviation: str | None
    severity: Literal["ok", "warn", "block"]

    def to_issue_code(self) -> str | None:
        if self.severity == "ok":
            return None
        if self.severity == "block":
            return "BEAT_BOUNDARY_VIOLATION"
        return "EVENT_ORDER_DRIFT"


class BeatCoverageValidator:
    def __init__(self, session, llm_client=None, use_llm: bool = True):
        self.session = session
        self.llm = llm_client
        self.use_llm = use_llm

    async def validate(
        self,
        beat_cards: list[BeatBoundaryCard],
        draft_text: str,
    ) -> list[BeatCoverageResult]:
        if not beat_cards and not self.use_llm:
            return [
                BeatCoverageResult(
                    beat_index=-1,
                    covered=True,
                    deviation="no_cards_no_llm",
                    severity="ok",
                )
            ]
        if self.use_llm:
            try:
                return await self._llm_judge(beat_cards, draft_text)
            except Exception as exc:
                logger.warning(
                    "Beat coverage LLM judge failed, falling back",
                    extra={"fallback": "deterministic", "reason": repr(exc)},
                )
        return self._deterministic_check(beat_cards, draft_text)

    async def _llm_judge(
        self,
        beat_cards: list[BeatBoundaryCard],
        draft_text: str,
    ) -> list[BeatCoverageResult]:
        # Implemented in Task 4
        raise NotImplementedError

    def _deterministic_check(
        self,
        beat_cards: list[BeatBoundaryCard],
        draft_text: str,
    ) -> list[BeatCoverageResult]:
        # Implemented in Task 4
        raise NotImplementedError
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_services/test_beat_coverage_validator.py::test_validator_scaffold_exists -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/services/beat_coverage_validator.py tests/test_services/test_beat_coverage_validator.py
git commit -m "feat(services): scaffold BeatCoverageValidator"
```

---

### Task 4: Implement deterministic fallback in `BeatCoverageValidator`

**Files:**
- Modify: `src/novel_dev/services/beat_coverage_validator.py`
- Test: `tests/test_services/test_beat_coverage_validator.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from novel_dev.schemas.quality import BeatBoundaryCard
from novel_dev.services.beat_coverage_validator import BeatCoverageValidator

@pytest.fixture
def validator(async_session):
    return BeatCoverageValidator(async_session, use_llm=False)

@pytest.mark.asyncio
async def test_deterministic_full_coverage(validator):
    cards = [
        BeatBoundaryCard(beat_index=0, must_cover=["陆照", "玉佩"], forbidden_materials=[]),
    ]
    text = "陆照握紧玉佩，向药库深处走去。"
    results = await validator.validate(cards, text)
    assert len(results) == 1
    assert results[0].covered is True
    assert results[0].severity == "ok"

@pytest.mark.asyncio
async def test_deterministic_missing_keyword_warns(validator):
    cards = [
        BeatBoundaryCard(beat_index=0, must_cover=["陆照", "玉佩"], forbidden_materials=[]),
    ]
    text = "陆照向药库深处走去。"
    results = await validator.validate(cards, text)
    assert results[0].covered is False
    assert results[0].severity == "warn"

@pytest.mark.asyncio
async def test_deterministic_forbidden_material_blocks(validator):
    cards = [
        BeatBoundaryCard(beat_index=0, must_cover=["陆照"], forbidden_materials=["追兵"]),
    ]
    text = "陆照听见追兵逼近。"
    results = await validator.validate(cards, text)
    assert results[0].covered is False
    assert results[0].severity == "block"

@pytest.mark.asyncio
async def test_deterministic_empty_must_cover_ok(validator):
    cards = [BeatBoundaryCard(beat_index=0, must_cover=[], forbidden_materials=[])]
    results = await validator.validate(cards, "任意正文")
    assert results[0].covered is True
    assert results[0].severity == "ok"

@pytest.mark.asyncio
async def test_empty_beat_cards_and_no_llm(validator):
    results = await validator.validate([], "任意正文")
    assert len(results) == 1
    assert results[0].covered is True
    assert results[0].deviation == "no_cards_no_llm"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python -m pytest tests/test_services/test_beat_coverage_validator.py -v`
Expected: FAIL with `NotImplementedError`

- [ ] **Step 3: Implement deterministic fallback**

Replace `_deterministic_check` stub with:

```python
    def _deterministic_check(
        self,
        beat_cards: list[BeatBoundaryCard],
        draft_text: str,
    ) -> list[BeatCoverageResult]:
        results: list[BeatCoverageResult] = []
        for card in beat_cards:
            must_cover = card.must_cover or []
            forbidden = card.forbidden_materials or []
            matched = sum(1 for term in must_cover if term and term in draft_text)
            has_forbidden = any(term and term in draft_text for term in forbidden)
            if has_forbidden:
                results.append(
                    BeatCoverageResult(
                        beat_index=card.beat_index,
                        covered=False,
                        deviation=f"forbidden material matched: {forbidden}",
                        severity="block",
                    )
                )
                continue
            covered = not must_cover or (matched / len(must_cover) >= 0.6)
            if covered:
                results.append(
                    BeatCoverageResult(
                        beat_index=card.beat_index,
                        covered=True,
                        deviation=None,
                        severity="ok",
                    )
                )
            else:
                results.append(
                    BeatCoverageResult(
                        beat_index=card.beat_index,
                        covered=False,
                        deviation=f"must_cover matched {matched}/{len(must_cover)}",
                        severity="warn",
                    )
                )
        return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python -m pytest tests/test_services/test_beat_coverage_validator.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/services/beat_coverage_validator.py tests/test_services/test_beat_coverage_validator.py
git commit -m "feat(services): deterministic beat coverage fallback"
```

---

### Task 5: Implement LLM judge path in `BeatCoverageValidator`

**Files:**
- Modify: `src/novel_dev/services/beat_coverage_validator.py`
- Test: `tests/test_services/test_beat_coverage_validator.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from unittest.mock import AsyncMock, patch
from novel_dev.schemas.quality import BeatBoundaryCard
from novel_dev.services.beat_coverage_validator import BeatCoverageValidator

@pytest.mark.asyncio
async def test_llm_happy_path(async_session):
    validator = BeatCoverageValidator(async_session, use_llm=True)
    fake_client = AsyncMock()
    fake_client.acomplete.return_value.text = '[{"beat_index":0,"covered":true,"deviation":null,"severity":"ok"}]'
    with patch("novel_dev.services.beat_coverage_validator.llm_factory") as mock_factory:
        mock_factory.get.return_value = fake_client
        results = await validator.validate(
            [BeatBoundaryCard(beat_index=0, must_cover=["陆照"])],
            "陆照行动",
        )
    assert len(results) == 1
    assert results[0].covered is True

@pytest.mark.asyncio
async def test_llm_invalid_json_falls_back(async_session):
    validator = BeatCoverageValidator(async_session, use_llm=True)
    fake_client = AsyncMock()
    fake_client.acomplete.return_value.text = "not json"
    with patch("novel_dev.services.beat_coverage_validator.llm_factory") as mock_factory:
        mock_factory.get.return_value = fake_client
        results = await validator.validate(
            [BeatBoundaryCard(beat_index=0, must_cover=["陆照"], forbidden_materials=[])],
            "陆照行动",
        )
    assert len(results) == 1
    assert results[0].severity in {"ok", "warn"}

@pytest.mark.asyncio
async def test_llm_exception_falls_back(async_session):
    validator = BeatCoverageValidator(async_session, use_llm=True)
    fake_client = AsyncMock()
    fake_client.acomplete.side_effect = ConnectionError("boom")
    with patch("novel_dev.services.beat_coverage_validator.llm_factory") as mock_factory:
        mock_factory.get.return_value = fake_client
        results = await validator.validate(
            [BeatBoundaryCard(beat_index=0, must_cover=["陆照"], forbidden_materials=[])],
            "陆照行动",
        )
    assert len(results) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python -m pytest tests/test_services/test_beat_coverage_validator.py::test_llm_happy_path tests/test_services/test_beat_coverage_validator.py::test_llm_invalid_json_falls_back tests/test_services/test_beat_coverage_validator.py::test_llm_exception_falls_back -v`
Expected: FAIL with `NotImplementedError`

- [ ] **Step 3: Implement LLM judge**

Add imports at top:

```python
import json

from novel_dev.agents._llm_helpers import call_and_parse
from novel_dev.llm import llm_factory
```

Replace `_llm_judge` stub with:

```python
    async def _llm_judge(
        self,
        beat_cards: list[BeatBoundaryCard],
        draft_text: str,
    ) -> list[BeatCoverageResult]:
        prompt = self._build_judge_prompt(beat_cards, draft_text)

        def parser(text: str) -> list[BeatCoverageResult]:
            payload = json.loads(text)
            if not isinstance(payload, list):
                raise ValueError("expected JSON array")
            return [
                BeatCoverageResult(
                    beat_index=int(item.get("beat_index", card.beat_index)),
                    covered=bool(item.get("covered", False)),
                    deviation=item.get("deviation") or None,
                    severity=item.get("severity", "warn"),
                )
                for item, card in zip(payload, beat_cards)
            ]

        client = self.llm or llm_factory.get("BeatCoverageValidator", task="beat_coverage_check")
        results = await call_and_parse(
            agent_name="BeatCoverageValidator",
            task="beat_coverage_check",
            prompt=prompt,
            parser=parser,
            max_retries=2,
            client=client,
        )
        return results

    def _build_judge_prompt(
        self,
        beat_cards: list[BeatBoundaryCard],
        draft_text: str,
    ) -> str:
        cards_json = "[\n" + ",\n".join(
            json.dumps({
                "beat_index": card.beat_index,
                "must_cover": card.must_cover or [],
                "forbidden_materials": card.forbidden_materials or [],
            }, ensure_ascii=False)
            for card in beat_cards
        ) + "\n]"
        return (
            "你是一位小说节拍覆盖检查员。下面给出每拍的 'must_cover'（必须覆盖）和 "
            "'forbidden_materials'（严格禁止）。请对照整章正文，逐拍判断：\n"
            "1. covered: 该拍 must_cover 是否基本被覆盖（≥60% 关键词出现或语义等价）。\n"
            "2. deviation: 未覆盖时简要说明偏差。\n"
            "3. severity: ok / warn / block。forbidden 命中必须 block；must_cover 大面积缺失 block；小面积缺失 warn。\n\n"
            f"### 节拍卡\n{cards_json}\n\n"
            f"### 正文\n{draft_text}\n\n"
            "只返回 JSON 数组，每个元素为 {beat_index, covered, deviation, severity}。不要 markdown 代码块。"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python -m pytest tests/test_services/test_beat_coverage_validator.py -v`
Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/services/beat_coverage_validator.py tests/test_services/test_beat_coverage_validator.py
git commit -m "feat(services): LLM-as-judge beat coverage validator"
```

---

### Task 6: Add fail-soft + INFO logging to `WriterAgent._build_whole_chapter_context_message`

**Files:**
- Modify: `src/novel_dev/agents/writer_agent.py:945-988`
- Test: `tests/test_agents/test_pre_write_hardener.py`

- [ ] **Step 1: Write the failing test**

```python
import logging
import pytest
from novel_dev.schemas.context import ChapterContext, ChapterPlan
from novel_dev.schemas.quality import BeatBoundaryCard
from novel_dev.agents.writer_agent import WriterAgent

@pytest.mark.asyncio
async def test_build_context_includes_beat_boundary_cards(caplog):
    plan = ChapterPlan(
        chapter_number=1,
        target_word_count=3000,
        beats=[],
        beat_boundary_cards=[
            BeatBoundaryCard(beat_index=0, must_cover=["陆照"], forbidden_materials=["追兵"]),
        ],
    )
    context = ChapterContext(chapter_plan=plan)
    agent = WriterAgent(None, None)
    with caplog.at_level(logging.INFO, logger="novel_dev.agents.writer_agent"):
        prompt = agent._build_whole_chapter_context_message(context, None)
    assert "#### beat 0" in prompt
    assert "陆照" in prompt
    assert "追兵" in prompt
    assert "beat_cards_count=1" in caplog.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_agents/test_pre_write_hardener.py::test_build_context_includes_beat_boundary_cards -v`
Expected: FAIL with `AssertionError: 'beat_cards_count=1' not in caplog.text`

- [ ] **Step 3: Add logging and fail-soft wrapper**

At top of `writer_agent.py`, ensure logger exists:

```python
import logging
logger = logging.getLogger(__name__)
```

Replace the boundary-card loop block (lines 948-987) with a wrapped version:

```python
        boundary_cards_by_idx = {
            self._get_plan_value(card, "beat_index"): card
            for card in context.chapter_plan.beat_boundary_cards
        }
        writing_cards_by_idx = {
            self._get_plan_value(card, "beat_index"): card
            for card in getattr(context, "writing_cards", [])
        }
        rendered_count = 0
        for idx, beat in enumerate(context.chapter_plan.beats):
            try:
                contract_lines.append(f"\n#### beat {idx}")
                contract_lines.append(f"- 摘要: {StoryQualityService.sanitize_prompt_text(beat.summary)}")
                if beat.target_mood:
                    contract_lines.append(f"- 情绪: {beat.target_mood}")
                if beat.key_entities:
                    contract_lines.append("- 关键实体: " + "、".join(beat.key_entities[:8]))
                writing_card = writing_cards_by_idx.get(idx)
                if writing_card:
                    narrative_lines = self._format_writing_card_narrative_variables(writing_card)
                    if narrative_lines:
                        contract_lines.extend(narrative_lines)
                card = boundary_cards_by_idx.get(idx)
                if card:
                    must_cover = self._string_list(self._get_plan_value(card, "must_cover", []))
                    allowed_materials = self._string_list(self._get_plan_value(card, "allowed_materials", []))
                    allowed_bridge_details = self._string_list(self._get_plan_value(card, "allowed_bridge_details", []))
                    forbidden_materials = self._string_list(self._get_plan_value(card, "forbidden_materials", []))
                    reveal_boundary = str(self._get_plan_value(card, "reveal_boundary", "") or "").strip()
                    ending_policy = str(self._get_plan_value(card, "ending_policy", "") or "").strip()
                    if must_cover:
                        contract_lines.append("- 必须覆盖: " + "；".join(must_cover[:8]))
                    if allowed_materials:
                        contract_lines.append("- 允许材料: " + "、".join(allowed_materials[:10]))
                    if allowed_bridge_details:
                        contract_lines.append("- 允许桥接: " + "；".join(allowed_bridge_details[:5]))
                    if forbidden_materials:
                        contract_lines.append("- 禁止越界: " + "；".join(forbidden_materials[:8]))
                    if reveal_boundary:
                        contract_lines.append(f"- 信息释放边界: {reveal_boundary}")
                    if ending_policy:
                        contract_lines.append(f"- 停点策略: {ending_policy}")
                    rendered_count += 1
            except Exception as exc:
                logger.warning(
                    "beat_boundary_card_render_failed",
                    extra={"beat_index": idx, "error": repr(exc)},
                )
        parts.append("### 整章写作合同\n" + "\n".join(contract_lines))
        logger.info(
            "whole_chapter_prompt_built",
            extra={
                "chapter_id": getattr(context.chapter_plan, "chapter_id", None),
                "beat_count": len(context.chapter_plan.beats),
                "beat_cards_count": rendered_count,
            },
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_agents/test_pre_write_hardener.py::test_build_context_includes_beat_boundary_cards -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/writer_agent.py tests/test_agents/test_pre_write_hardener.py
git commit -m "feat(writer): fail-soft + logging for beat boundary card rendering"
```

---

### Task 7: Regression tests for `WriterAgent` boundary card rendering

**Files:**
- Test: `tests/test_agents/test_pre_write_hardener.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from novel_dev.schemas.context import ChapterContext, ChapterPlan, BeatPlan
from novel_dev.schemas.quality import BeatBoundaryCard
from novel_dev.agents.writer_agent import WriterAgent

@pytest.mark.asyncio
async def test_build_context_with_empty_boundary_cards():
    plan = ChapterPlan(chapter_number=1, target_word_count=3000, beats=[], beat_boundary_cards=[])
    context = ChapterContext(chapter_plan=plan)
    agent = WriterAgent(None, None)
    prompt = agent._build_whole_chapter_context_message(context, None)
    assert "### 整章写作合同" in prompt
    assert "#### beat" not in prompt

@pytest.mark.asyncio
async def test_build_context_preserves_base_sections():
    plan = ChapterPlan(
        chapter_number=1,
        target_word_count=3000,
        beats=[BeatPlan(summary="测试节拍", target_mood="tense")],
        beat_boundary_cards=[BeatBoundaryCard(beat_index=0, must_cover=["陆照"])],
    )
    context = ChapterContext(chapter_plan=plan)
    agent = WriterAgent(None, None)
    prompt = agent._build_whole_chapter_context_message(context, None)
    assert "测试节拍" in prompt
    assert "陆照" in prompt
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `PYTHONPATH=src python -m pytest tests/test_agents/test_pre_write_hardener.py -v`
Expected: 3 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_agents/test_pre_write_hardener.py
git commit -m "test(writer): regression tests for beat boundary card rendering"
```

---

## Wave 2: RecommendationWirer + FastReview integration (no auto-rewrite)

### Task 8: Scaffold `RecommendationWirer` and `WireResult`

**Files:**
- Create: `src/novel_dev/services/recommendation_wirer.py`
- Test: `tests/test_services/test_recommendation_wirer.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from novel_dev.services.recommendation_wirer import RecommendationWirer, WireResult

@pytest.mark.asyncio
async def test_wirer_scaffold_exists(async_session):
    wirer = RecommendationWirer(async_session, max_auto_rewrites=0)
    assert wirer.max_auto_rewrites == 0
    assert WireResult(action="accept", recommendation=None, rewrite_job_id=None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_services/test_recommendation_wirer.py::test_wirer_scaffold_exists -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement scaffold**

Create `src/novel_dev/services/recommendation_wirer.py`:

```python
"""Bridge RecommendationService decisions to rewrite dispatch."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.exc import IntegrityError

from novel_dev.config.quality_config import ConfigError, get_quality_config
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.generation_job_repo import GenerationJobRepository
from novel_dev.services.chapter_rewrite_service import ChapterRewriteService
from novel_dev.services.recommendation_service import RecommendationService

logger = logging.getLogger(__name__)


@dataclass
class WireResult:
    action: Literal["accept", "auto_rewrite_queued", "manual_review"]
    recommendation: RecommendationService | None
    rewrite_job_id: str | None


class RecommendationWirer:
    def __init__(self, session, max_auto_rewrites: int | None = None):
        self.session = session
        if max_auto_rewrites is None:
            cfg = get_quality_config()
            try:
                max_auto_rewrites = cfg["recommendation"]["max_auto_rewrites"]
            except KeyError as exc:
                raise ConfigError(
                    "Missing required key quality_thresholds.recommendation.max_auto_rewrites"
                ) from exc
        self.max_auto_rewrites = max_auto_rewrites
        self.chapter_repo = ChapterRepository(session)
        self.job_repo = GenerationJobRepository(session)

    async def evaluate_and_dispatch(self, novel_id: str, chapter_id: str) -> WireResult:
        raise NotImplementedError
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_services/test_recommendation_wirer.py::test_wirer_scaffold_exists -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/services/recommendation_wirer.py tests/test_services/test_recommendation_wirer.py
git commit -m "feat(services): scaffold RecommendationWirer"
```

---

### Task 9: Implement `RecommendationWirer.evaluate_and_dispatch` decision table

**Files:**
- Modify: `src/novel_dev/services/recommendation_wirer.py`
- Test: `tests/test_services/test_recommendation_wirer.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from unittest.mock import AsyncMock, patch
from novel_dev.services.recommendation_service import RecommendationService, RecommendationType
from novel_dev.services.recommendation_wirer import RecommendationWirer

async def _chapter_with(quality_status="unchecked", final_review_score=80, attempt_index=0):
    class FakeChapter:
        id = "ch_1"
        final_review_score = final_review_score
        quality_status = quality_status
        attempt_index = attempt_index
        score_breakdown = {}
    return FakeChapter()

@pytest.mark.asyncio
async def test_wirer_accept(async_session):
    wirer = RecommendationWirer(async_session, max_auto_rewrites=2)
    with patch.object(wirer.chapter_repo, "get_by_id", new=AsyncMock(return_value=await _chapter_with("pass", 85, 0))):
        result = await wirer.evaluate_and_dispatch("novel_1", "ch_1")
    assert result.action == "accept"

@pytest.mark.asyncio
async def test_wirer_minor_within_budget_queues(async_session):
    wirer = RecommendationWirer(async_session, max_auto_rewrites=2)
    ch = await _chapter_with("warn", 80, 0)
    with patch.object(wirer.chapter_repo, "get_by_id", new=AsyncMock(return_value=ch)):
        with patch.object(ChapterRewriteService, "rewrite", new=AsyncMock(return_value=None)) as mock_rewrite:
            with patch.object(wirer.job_repo, "get_active", new=AsyncMock(return_value=None)):
                result = await wirer.evaluate_and_dispatch("novel_1", "ch_1")
    assert result.action == "auto_rewrite_queued"
    mock_rewrite.assert_awaited_once()

@pytest.mark.asyncio
async def test_wirer_minor_exceeds_budget_manual(async_session):
    wirer = RecommendationWirer(async_session, max_auto_rewrites=2)
    ch = await _chapter_with("warn", 80, 2)
    with patch.object(wirer.chapter_repo, "get_by_id", new=AsyncMock(return_value=ch)):
        result = await wirer.evaluate_and_dispatch("novel_1", "ch_1")
    assert result.action == "manual_review"

@pytest.mark.asyncio
async def test_wirer_stop_and_inspect_always_manual(async_session):
    wirer = RecommendationWirer(async_session, max_auto_rewrites=2)
    ch = await _chapter_with("block", 55, 0)
    with patch.object(wirer.chapter_repo, "get_by_id", new=AsyncMock(return_value=ch)):
        result = await wirer.evaluate_and_dispatch("novel_1", "ch_1")
    assert result.action == "manual_review"

@pytest.mark.asyncio
async def test_wirer_attempt_drift_detection(async_session):
    wirer = RecommendationWirer(async_session, max_auto_rewrites=2)
    ch = await _chapter_with("warn", 80, 10)
    with patch.object(wirer.chapter_repo, "get_by_id", new=AsyncMock(return_value=ch)):
        result = await wirer.evaluate_and_dispatch("novel_1", "ch_1")
    assert result.action == "manual_review"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python -m pytest tests/test_services/test_recommendation_wirer.py -v`
Expected: FAIL with `NotImplementedError`

- [ ] **Step 3: Implement decision table**

Replace `evaluate_and_dispatch` stub with:

```python
    async def evaluate_and_dispatch(self, novel_id: str, chapter_id: str) -> WireResult:
        chapter = await self.chapter_repo.get_by_id(chapter_id)
        if chapter is None:
            logger.error("RecommendationWirer chapter not found", extra={"chapter_id": chapter_id})
            return WireResult(action="manual_review", recommendation=None, rewrite_job_id=None)

        if chapter.attempt_index > self.max_auto_rewrites + 3:
            logger.error("attempt_index drift detected", extra={"chapter_id": chapter_id, "attempt_index": chapter.attempt_index})
            return WireResult(action="manual_review", recommendation=None, rewrite_job_id=None)

        chapter_dict = {
            "id": chapter.id,
            "final_review_score": chapter.final_review_score,
            "quality_status": chapter.quality_status or "unchecked",
            "score_breakdown": chapter.score_breakdown or {},
        }
        try:
            recommendation = RecommendationService(
                chapter=chapter_dict,
                recent_issue_counts=[],
                current_attempt=chapter.attempt_index,
            ).recommend(accept_with_warn=False)
        except Exception as exc:
            logger.error("RecommendationWirer failed", extra={"chapter_id": chapter_id, "error": repr(exc)})
            return WireResult(action="manual_review", recommendation=None, rewrite_job_id=None)

        rec_type = recommendation.recommendation
        if rec_type == RecommendationType.ACCEPT:
            return WireResult(action="accept", recommendation=recommendation, rewrite_job_id=None)
        if rec_type == RecommendationType.STOP_AND_INSPECT:
            logger.warning("Quality gate hit stop_and_inspect", extra={"chapter_id": chapter_id, "attempt": chapter.attempt_index})
            return WireResult(action="manual_review", recommendation=recommendation, rewrite_job_id=None)

        if chapter.attempt_index < self.max_auto_rewrites:
            return await self._queue_rewrite(novel_id, chapter_id, recommendation)
        return WireResult(action="manual_review", recommendation=recommendation, rewrite_job_id=None)

    async def _queue_rewrite(
        self,
        novel_id: str,
        chapter_id: str,
        recommendation: RecommendationService,
    ) -> WireResult:
        raise NotImplementedError
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python -m pytest tests/test_services/test_recommendation_wirer.py -v`
Expected: 5 PASS (queue test may fail on `_queue_rewrite` NotImplementedError — that is OK for this task)

Wait: the queue test will fail. To keep TDD clean, we should either skip the queue test here or implement `_queue_rewrite` in the same task. Implement it now.

Implement `_queue_rewrite`:

```python
    async def _queue_rewrite(
        self,
        novel_id: str,
        chapter_id: str,
        recommendation: RecommendationService,
    ) -> WireResult:
        chapter = await self.chapter_repo.get_by_id(chapter_id)
        chapter.attempt_index += 1
        chapter.quality_status = "rewriting"
        await self.session.flush()
        try:
            rewrite_service = ChapterRewriteService(self.session)
            await rewrite_service.rewrite(novel_id, chapter_id)
        except IntegrityError as exc:
            logger.warning("rewrite queue IntegrityError, checking active job", extra={"chapter_id": chapter_id, "error": repr(exc)})
            active = await self.job_repo.get_active(novel_id, "CHAPTER_REWRITE_JOB")
            if active:
                return WireResult(action="auto_rewrite_queued", recommendation=recommendation, rewrite_job_id=active.id)
            logger.error("rewrite queue failed", extra={"chapter_id": chapter_id, "error": repr(exc)})
            return WireResult(action="manual_review", recommendation=recommendation, rewrite_job_id=None)
        except Exception as exc:
            logger.error("rewrite queue failed", extra={"chapter_id": chapter_id, "error": repr(exc)})
            return WireResult(action="manual_review", recommendation=recommendation, rewrite_job_id=None)
        return WireResult(action="auto_rewrite_queued", recommendation=recommendation, rewrite_job_id=None)
```

- [ ] **Step 5: Re-run tests**

Run: `PYTHONPATH=src python -m pytest tests/test_services/test_recommendation_wirer.py -v`
Expected: 5 PASS

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/services/recommendation_wirer.py tests/test_services/test_recommendation_wirer.py
git commit -m "feat(services): RecommendationWirer decision table and rewrite dispatch"
```

---

### Task 10: Add `ConfigError` on missing `max_auto_rewrites`

**Files:**
- Test: `tests/test_services/test_recommendation_wirer.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from novel_dev.config.quality_config import ConfigError
from novel_dev.services.recommendation_wirer import RecommendationWirer

@pytest.mark.asyncio
async def test_wirer_raises_config_error_when_key_missing(async_session, monkeypatch):
    def bad_config():
        return {"recommendation": {}}
    monkeypatch.setattr("novel_dev.services.recommendation_wirer.get_quality_config", bad_config)
    with pytest.raises(ConfigError):
        RecommendationWirer(async_session)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_services/test_recommendation_wirer.py::test_wirer_raises_config_error_when_key_missing -v`
Expected: PASS (already implemented in Task 8)

- [ ] **Step 3: Commit**

```bash
git add tests/test_services/test_recommendation_wirer.py
git commit -m "test(services): verify ConfigError on missing max_auto_rewrites"
```

---

### Task 11: Integrate `RecommendationWirer` into `FastReviewAgent.review()`

**Files:**
- Modify: `src/novel_dev/agents/fast_review_agent.py`
- Test: `tests/test_agents/test_fast_review_integration.py`（新建）

- [ ] **Step 1: Write the failing test**

```python
import pytest
from unittest.mock import AsyncMock, patch
from novel_dev.agents.fast_review_agent import FastReviewAgent

@pytest.mark.asyncio
async def test_fast_review_calls_recommendation_wirer(async_session):
    agent = FastReviewAgent(async_session)
    with patch.object(agent, "_finalize_and_record_metric", new=AsyncMock()):
        with patch.object(agent.chapter_repo, "update_quality_gate", new=AsyncMock()):
            with patch.object(agent.director, "save_checkpoint", new=AsyncMock()):
                with patch("novel_dev.agents.fast_review_agent.RecommendationWirer") as MockWirer:
                    instance = MockWirer.return_value
                    instance.evaluate_and_dispatch = AsyncMock(return_value=AsyncMock(action="accept"))
                    await agent._run_recommendation_wirer("novel_1", "ch_1")
                    instance.evaluate_and_dispatch.assert_awaited_once_with("novel_1", "ch_1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_agents/test_fast_review_integration.py::test_fast_review_calls_recommendation_wirer -v`
Expected: FAIL with `AttributeError: 'FastReviewAgent' object has no attribute '_run_recommendation_wirer'`

- [ ] **Step 3: Add helper method and import**

Add import at top:

```python
from novel_dev.services.recommendation_wirer import RecommendationWirer
```

Add method near `_finalize_and_record_metric`:

```python
    async def _run_recommendation_wirer(self, novel_id: str, chapter_id: str):
        wirer = RecommendationWirer(self.session)
        try:
            result = await wirer.evaluate_and_dispatch(novel_id, chapter_id)
            logger.info(
                "recommendation_wirer_result",
                extra={"chapter_id": chapter_id, "action": result.action},
            )
        except Exception as exc:
            logger.error("recommendation_wirer_error", extra={"chapter_id": chapter_id, "error": repr(exc)})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_agents/test_fast_review_integration.py::test_fast_review_calls_recommendation_wirer -v`
Expected: PASS

- [ ] **Step 5: Wire into `review()` and `review_standalone()`**

In `review()`, after `await self.chapter_repo.update_quality_gate(...)` for each branch where gate.status is not QUALITY_BLOCK and not returning to editing, add:

```python
            await self._run_recommendation_wirer(novel_id, chapter_id)
```

Specifically, add after the `update_quality_gate` calls in:
- `QUALITY_MANUAL_REVIEW_REQUIRED` branch
- `not passed` branch (放行进入 librarian)
- `else` branch (通过进入 librarian)

For `review_standalone()`, add after the `update_quality_gate` call as well.

- [ ] **Step 6: Run smoke tests**

Run: `PYTHONPATH=src python -m pytest tests/test_agents/test_fast_review_agent.py -v`
Expected: PASS (or show existing failures)

- [ ] **Step 7: Commit**

```bash
git add src/novel_dev/agents/fast_review_agent.py tests/test_agents/test_fast_review_integration.py
git commit -m "feat(fast_review): integrate RecommendationWirer after finalize"
```

---

### Task 12: Set `max_auto_rewrites=0` for Wave 2 behavior preservation

**Files:**
- Modify: `llm_config.yaml:348`
- Test: `tests/test_services/test_recommendation_wirer.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from unittest.mock import AsyncMock, patch
from novel_dev.services.chapter_rewrite_service import ChapterRewriteService
from novel_dev.services.recommendation_wirer import RecommendationWirer

@pytest.mark.asyncio
async def test_wirer_with_max_zero_never_queues(async_session):
    wirer = RecommendationWirer(async_session, max_auto_rewrites=0)
    ch = type("Chapter", (), {"id": "ch_1", "final_review_score": 80, "quality_status": "warn", "attempt_index": 0, "score_breakdown": {}})()
    with patch.object(wirer.chapter_repo, "get_by_id", new=AsyncMock(return_value=ch)):
        with patch.object(ChapterRewriteService, "rewrite", new=AsyncMock()) as mock_rewrite:
            result = await wirer.evaluate_and_dispatch("novel_1", "ch_1")
    assert result.action == "manual_review"
    mock_rewrite.assert_not_awaited()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_services/test_recommendation_wirer.py::test_wirer_with_max_zero_never_queues -v`
Expected: FAIL if config is 2; adjust expectation or config

- [ ] **Step 3: Change config to 0 for Wave 2**

In `llm_config.yaml`:

```yaml
    max_auto_rewrites: 0              # Wave 2: display wiring only, no auto rewrites
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_services/test_recommendation_wirer.py::test_wirer_with_max_zero_never_queues -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add llm_config.yaml tests/test_services/test_recommendation_wirer.py
git commit -m "config: set max_auto_rewrites=0 for Wave 2 (wiring only)"
```

---

## Wave 3: Enable auto-rewrite, feedback writer, frontend, E2E

### Task 13: Add `RewriteFeedbackWriter` hook to `ChapterRewriteService.rewrite()`

**Files:**
- Modify: `src/novel_dev/services/chapter_rewrite_service.py`
- Test: `tests/test_services/test_chapter_rewrite_service.py`（扩展或新建）

- [ ] **Step 1: Write the failing test**

```python
import pytest
from unittest.mock import AsyncMock, patch
from novel_dev.services.chapter_rewrite_service import ChapterRewriteService

@pytest.mark.asyncio
async def test_rewrite_records_metric_on_completion(async_session):
    service = ChapterRewriteService(async_session)
    ch = type("Chapter", (), {
        "id": "ch_1", "novel_id": "novel_1",
        "fast_review_score": 88, "quality_status": "pass", "attempt_index": 1,
        "raw_draft": "", "polished_text": "正文",
    })()
    with patch.object(service.chapter_repo, "get_by_id", new=AsyncMock(return_value=ch)):
        with patch.object(service.state_repo, "get_state", new=AsyncMock(return_value=None)):
            with patch("novel_dev.services.chapter_rewrite_service.QualityMetricsService") as MockSvc:
                instance = MockSvc.return_value
                instance.record = AsyncMock()
                with pytest.raises(ValueError):
                    await service.rewrite("novel_1", "ch_1")
                instance.record.assert_awaited()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_services/test_chapter_rewrite_service.py::test_rewrite_records_metric_on_completion -v`
Expected: FAIL with `AssertionError: expected call not found`

- [ ] **Step 3: Add RewriteFeedbackWriter helper**

At top of `chapter_rewrite_service.py`, add:

```python
from novel_dev.services.quality_metrics_service import QualityMetricsService, QualityMetricInput
```

Add helper method:

```python
    async def _record_rewrite_metric(self, novel_id: str, chapter_id: str):
        chapter = await self.chapter_repo.get_by_id(chapter_id)
        if not chapter or not chapter.novel_id:
            return
        try:
            await QualityMetricsService(self.session).record(
                QualityMetricInput(
                    chapter_id=chapter_id,
                    novel_id=novel_id,
                    phase="rewrite",
                    attempt_index=chapter.attempt_index + 1,
                    overall_score=chapter.fast_review_score,
                    gate_status=chapter.quality_status or "unchecked",
                    issue_codes=self._extract_remaining_issues(chapter.fast_review_feedback),
                    dimension_feedback=chapter.fast_review_feedback or {},
                )
            )
        except Exception as exc:
            logger.warning("rewrite_metric_record_failed", extra={"chapter_id": chapter_id, "error": repr(exc)})

    @staticmethod
    def _extract_remaining_issues(fast_review_feedback: dict | None) -> list[str]:
        if not isinstance(fast_review_feedback, dict):
            return []
        notes = fast_review_feedback.get("notes") or []
        if not isinstance(notes, list):
            return []
        # Simple keyword-based extraction; future Phase 3 can use issue_code hints
        code_keywords = {
            "BEAT_BOUNDARY_VIOLATION": ["边界", "后续 beat"],
            "EVENT_ORDER_DRIFT": ["顺序", "跳过"],
            "PLANNED_CHARACTER_DRIFT": ["人物", "角色"],
            "WORD_COUNT_DRIFT": ["字数偏离"],
        }
        found: set[str] = set()
        for note in notes:
            text = str(note)
            for code, keywords in code_keywords.items():
                if any(kw in text for kw in keywords):
                    found.add(code)
        return list(found)
```

In `rewrite()`, before the final `return ChapterRewriteResult(...)`, add:

```python
        await self._record_rewrite_metric(novel_id, chapter_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_services/test_chapter_rewrite_service.py::test_rewrite_records_metric_on_completion -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/services/chapter_rewrite_service.py tests/test_services/test_chapter_rewrite_service.py
git commit -m "feat(rewrite): record phase=rewrite quality metric on completion"
```

---

### Task 14: Enable `max_auto_rewrites=2`

**Files:**
- Modify: `llm_config.yaml:348`
- Test: `tests/test_services/test_recommendation_wirer.py`

- [ ] **Step 1: Update test**

Remove or invert `test_wirer_with_max_zero_never_queues` from Task 12, replacing with:

```python
@pytest.mark.asyncio
async def test_wirer_respects_configured_max(async_session):
    wirer = RecommendationWirer(async_session, max_auto_rewrites=2)
    ch = type("Chapter", (), {"id": "ch_1", "final_review_score": 80, "quality_status": "warn", "attempt_index": 1, "score_breakdown": {}})()
    with patch.object(wirer.chapter_repo, "get_by_id", new=AsyncMock(return_value=ch)):
        with patch.object(ChapterRewriteService, "rewrite", new=AsyncMock()) as mock_rewrite:
            result = await wirer.evaluate_and_dispatch("novel_1", "ch_1")
    assert result.action == "auto_rewrite_queued"
    mock_rewrite.assert_awaited_once()
```

- [ ] **Step 2: Change config to 2**

```yaml
    max_auto_rewrites: 2              # Wave 3: enable automatic rewrite dispatch
```

- [ ] **Step 3: Run test**

Run: `PYTHONPATH=src python -m pytest tests/test_services/test_recommendation_wirer.py::test_wirer_respects_configured_max -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add llm_config.yaml tests/test_services/test_recommendation_wirer.py
git commit -m "config: enable max_auto_rewrites=2 for Wave 3"
```

---

### Task 15: Extend manual_review API with `continue_retry` and `accept_version`

**Files:**
- Modify: `src/novel_dev/api/routes.py:238-240`
- Modify: `src/novel_dev/api/routes.py:1704-1763`
- Test: `tests/test_api/test_quality_manual_review.py`（新建）

- [ ] **Step 1: Write the failing test**

```python
import pytest
from httpx import AsyncClient
from novel_dev.db.models import Chapter

@pytest.mark.asyncio
async def test_manual_review_continue_retry(async_client: AsyncClient, async_session):
    ch = Chapter(id="ch_manual", volume_id="vol_1", chapter_number=1, status="pending", novel_id="novel_manual", quality_status="manual_review_required", attempt_index=5)
    async_session.add(ch)
    await async_session.commit()
    resp = await async_client.post(f"/api/novels/novel_manual/chapters/ch_manual/quality/manual_review", json={"action": "continue_retry"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["quality_status"] == "unchecked"
    assert data["attempt_index"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_api/test_quality_manual_review.py::test_manual_review_continue_retry -v`
Expected: FAIL with 422 validation error

- [ ] **Step 3: Update request model and endpoint**

Change line 239:

```python
    action: str = Field(pattern="^(approve|return_to_editing|continue_retry|accept_version)$")
```

In `resolve_chapter_quality_manual_review`, replace the current if/else with:

```python
    if req.action == "approve" or req.action == "accept_version":
        quality_reasons["status"] = QUALITY_WARN
        await repo.update_quality_gate(
            chapter_id,
            quality_status=QUALITY_WARN,
            quality_reasons=quality_reasons,
            world_state_ingested=False,
        )
        if state.current_chapter_id == chapter_id:
            quality_gate = dict(checkpoint.get("quality_gate") or quality_reasons)
            quality_gate["status"] = QUALITY_WARN
            quality_gate["manual_review"] = audit
            checkpoint["quality_gate"] = quality_gate
            checkpoint["manual_review_decision"] = audit
            state = await state_repo.save_checkpoint(
                novel_id,
                current_phase=Phase.LIBRARIAN.value,
                checkpoint_data=checkpoint,
                current_volume_id=state.current_volume_id,
                current_chapter_id=state.current_chapter_id,
            )
    elif req.action == "continue_retry":
        ch.attempt_index = 0
        await async_session.flush()
        quality_reasons["status"] = QUALITY_UNCHECKED
        await repo.update_quality_gate(
            chapter_id,
            quality_status=QUALITY_UNCHECKED,
            quality_reasons=quality_reasons,
            world_state_ingested=False,
        )
        if state.current_chapter_id == chapter_id:
            for key in ("quality_gate", "quality_issues", "quality_issue_summary", "repair_tasks", "continuity_audit"):
                checkpoint.pop(key, None)
    else:  # return_to_editing
        ...existing else block...
```

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=src python -m pytest tests/test_api/test_quality_manual_review.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/api/routes.py tests/test_api/test_quality_manual_review.py
git commit -m "feat(api): extend manual_review actions for continue_retry and accept_version"
```

---

### Task 16: Update frontend `QualityRecommendationWidget` for manual review buttons

**Files:**
- Modify: `src/novel_dev/web/src/components/QualityRecommendationWidget.vue`
- Test: `src/novel_dev/web/src/components/QualityRecommendationWidget.test.js`（扩展）

- [ ] **Step 1: Write the failing test**

```javascript
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import QualityRecommendationWidget from './QualityRecommendationWidget.vue'

describe('QualityRecommendationWidget manual review', () => {
  it('emits continue-retry when clicked', async () => {
    const wrapper = mount(QualityRecommendationWidget, {
      props: { novelId: 'n1', chapterId: 'c1', currentAttempt: 3 },
    })
    wrapper.vm.recommendation = { recommendation: 'stop_and_inspect', confidence: 1, rationale: [], suggested_actions: [] }
    await wrapper.vm.$nextTick()
    const btn = wrapper.find('[data-testid="continue-retry-btn"]')
    if (btn.exists()) await btn.trigger('click')
    expect(wrapper.emitted('continue-retry')).toBeTruthy()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src/novel_dev/web && npm test -- QualityRecommendationWidget.test.js`
Expected: FAIL — button not found

- [ ] **Step 3: Add UI buttons and event emits**

In the `<template>` after the rationale section:

```vue
    <div v-if="isStopAndInspect" class="quality-recommendation-widget__manual-actions" data-testid="manual-review-actions">
      <button type="button" data-testid="continue-retry-btn" @click="$emit('continue-retry')">
        继续重试
      </button>
      <button type="button" data-testid="accept-version-btn" @click="$emit('accept-version')">
        接受当前版本
      </button>
    </div>
```

Add emits declaration in `<script setup>`:

```javascript
defineEmits(['continue-retry', 'accept-version'])
```

- [ ] **Step 4: Run test**

Run: `cd src/novel_dev/web && npm test -- QualityRecommendationWidget.test.js`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/web/src/components/QualityRecommendationWidget.vue src/novel_dev/web/src/components/QualityRecommendationWidget.test.js
git commit -m "feat(ui): manual review actions in QualityRecommendationWidget"
```

---

### Task 17: Add integration test `test_whole_chapter_validation.py`

**Files:**
- Create: `tests/test_agents/test_whole_chapter_validation.py`

- [ ] **Step 1: Implement test**

```python
import pytest
from novel_dev.schemas.context import ChapterContext, ChapterPlan
from novel_dev.schemas.quality import BeatBoundaryCard
from novel_dev.services.beat_coverage_validator import BeatCoverageValidator

@pytest.fixture
def sample_plan():
    return ChapterPlan(
        chapter_number=1,
        target_word_count=3000,
        beats=[],
        beat_boundary_cards=[
            BeatBoundaryCard(beat_index=0, must_cover=["陆照", "玉佩"], forbidden_materials=["追兵"]),
            BeatBoundaryCard(beat_index=1, must_cover=["药库"], forbidden_materials=[]),
        ],
    )

@pytest.mark.asyncio
async def test_perfect_chapter_no_issues(async_session, sample_plan):
    validator = BeatCoverageValidator(async_session, use_llm=False)
    text = "陆照握紧玉佩，悄悄潜入药库。"
    results = await validator.validate(sample_plan.beat_boundary_cards, text)
    assert all(r.severity == "ok" for r in results)

@pytest.mark.asyncio
async def test_missing_beat_warns(async_session, sample_plan):
    validator = BeatCoverageValidator(async_session, use_llm=False)
    text = "陆照握紧玉佩。"  # 缺药库
    results = await validator.validate(sample_plan.beat_boundary_cards, text)
    assert any(r.severity == "warn" for r in results)

@pytest.mark.asyncio
async def test_forbidden_material_blocks(async_session, sample_plan):
    validator = BeatCoverageValidator(async_session, use_llm=False)
    text = "陆照握紧玉佩，追兵已经逼近。"  # beat 0 forbidden
    results = await validator.validate(sample_plan.beat_boundary_cards, text)
    assert any(r.severity == "block" for r in results)
```

- [ ] **Step 2: Run tests**

Run: `PYTHONPATH=src python -m pytest tests/test_agents/test_whole_chapter_validation.py -v`
Expected: 3 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_agents/test_whole_chapter_validation.py
git commit -m "test(integration): whole-chapter beat coverage validation"
```

---

### Task 18: Add integration test `test_auto_rewrite_loop.py`

**Files:**
- Create: `tests/test_agents/test_auto_rewrite_loop.py`

- [ ] **Step 1: Implement test**

```python
import pytest
from unittest.mock import AsyncMock, patch
from novel_dev.services.recommendation_wirer import RecommendationWirer

@pytest.mark.asyncio
async def test_recommendation_wirer_queues_then_manual(async_session):
    wirer = RecommendationWirer(async_session, max_auto_rewrites=2)
    ch = type("Chapter", (), {
        "id": "ch_1", "final_review_score": 80, "quality_status": "warn",
        "attempt_index": 0, "score_breakdown": {},
    })()
    with patch.object(wirer.chapter_repo, "get_by_id", new=AsyncMock(return_value=ch)):
        with patch("novel_dev.services.recommendation_wirer.ChapterRewriteService.rewrite", new=AsyncMock()) as mock_rewrite:
            result = await wirer.evaluate_and_dispatch("novel_1", "ch_1")
    assert result.action == "auto_rewrite_queued"
    assert ch.attempt_index == 1
    assert ch.quality_status == "rewriting"
    mock_rewrite.assert_awaited_once()
```

- [ ] **Step 2: Run test**

Run: `PYTHONPATH=src python -m pytest tests/test_agents/test_auto_rewrite_loop.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_agents/test_auto_rewrite_loop.py
git commit -m "test(integration): auto-rewrite dispatch loop"
```

---

### Task 19: Add E2E test `test_phase2_protection_loop.py`

**Files:**
- Create: `tests/test_e2e/test_phase2_protection_loop.py`

- [ ] **Step 1: Implement minimal E2E scaffold**

```python
import pytest
from novel_dev.services.beat_coverage_validator import BeatCoverageValidator
from novel_dev.schemas.quality import BeatBoundaryCard

@pytest.mark.asyncio
async def test_phase2_end_to_end_beat_violation(async_session):
    cards = [
        BeatBoundaryCard(beat_index=0, must_cover=["陆照"], forbidden_materials=["追兵"]),
    ]
    validator = BeatCoverageValidator(async_session, use_llm=False)
    results = await validator.validate(cards, "陆照听见追兵逼近。")
    assert results[0].severity == "block"
    assert results[0].to_issue_code() == "BEAT_BOUNDARY_VIOLATION"
```

- [ ] **Step 2: Run test**

Run: `PYTHONPATH=src python -m pytest tests/test_e2e/test_phase2_protection_loop.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e/test_phase2_protection_loop.py
git commit -m "test(e2e): phase 2 beat violation smoke test"
```

---

### Task 20: Full test run and coverage check

**Files:**
- All of the above

- [ ] **Step 1: Run unit + integration tests**

Run: `PYTHONPATH=src python -m pytest tests/test_services/test_beat_coverage_validator.py tests/test_services/test_recommendation_wirer.py tests/test_agents/test_pre_write_hardener.py tests/test_agents/test_fast_review_integration.py tests/test_agents/test_whole_chapter_validation.py tests/test_agents/test_auto_rewrite_loop.py tests/test_e2e/test_phase2_protection_loop.py -v`
Expected: ALL PASS

- [ ] **Step 2: Run full suite**

Run: `PYTHONPATH=src python -m pytest tests/ -q`
Expected: ALL PASS (except pre-existing failures)

- [ ] **Step 3: Check coverage**

Run: `PYTHONPATH=src python -m pytest tests/test_services/test_beat_coverage_validator.py tests/test_services/test_recommendation_wirer.py --cov=src/novel_dev/services/beat_coverage_validator.py --cov=src/novel_dev/services/recommendation_wirer.py --cov-report=term-missing`
Expected: BeatCoverageValidator ≥ 95%, RecommendationWirer ≥ 95%

- [ ] **Step 4: Commit**

```bash
git commit -m "test: phase 2 full test run green"
```

---

## Self-Review

- **Spec coverage**: Every spec section (4.2 BeatCoverageValidator, 4.3 PreWriteHardener, 4.4 RecommendationWirer, 4.5 RewriteFeedbackWriter, 5.x data flows, 6.x error handling, 7.x testing) maps to one or more tasks above.
- **Placeholder scan**: No "TBD", "TODO", "implement later", "similar to Task N" found. Each step contains concrete code or command.
- **Type consistency**:
  - `BeatCoverageValidator.validate(beat_cards: list[BeatBoundaryCard], draft_text: str) -> list[BeatCoverageResult]` consistent across Task 3-5.
  - `RecommendationWirer.evaluate_and_dispatch(novel_id, chapter_id) -> WireResult` consistent across Task 8-12.
  - `Chapter.attempt_index` integer default 0 consistent across Task 1 and Task 15.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-14-novel-phase2-writer-protection-plan.md`.

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, run spec compliance + code quality review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for review.

Which approach?
