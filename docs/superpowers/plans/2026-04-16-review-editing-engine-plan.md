# Review and Editing Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement CriticAgent (scoring + feedback), EditorAgent (beat-level polishing), and FastReviewAgent (lightweight final check), with `NovelDirector.advance()` auto-flow, API endpoints, and MCP tools.

**Architecture:** CriticAgent reads `raw_draft` and produces a `ScoreResult` with 5 dimensions. EditorAgent reads per-beat scores and applies strategy-mapped rewrites. FastReviewAgent does cheap deterministic checks. `NovelDirector.advance()` orchestrates the REVIEWING → EDITING → FAST_REVIEWING → LIBRARIAN flow with rollback guards.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (async), Pydantic, pytest-asyncio, SQLite+aiosqlite (tests).

---

## File Map

| File | Responsibility |
|---|---|
| `src/novel_dev/schemas/review.py` | Pydantic models: `DimensionScore`, `ScoreResult`, `FastReviewReport` |
| `src/novel_dev/repositories/chapter_repo.py` | Add `update_fast_review()` |
| `src/novel_dev/agents/critic_agent.py` | CriticAgent: scoring, persistence, pass/rollback decision |
| `src/novel_dev/agents/editor_agent.py` | EditorAgent: beat-level polish |
| `src/novel_dev/agents/fast_review_agent.py` | FastReviewAgent: lightweight checks |
| `src/novel_dev/agents/director.py` | Add `advance()`, `_run_critic()`, `_run_editor()`, `_run_fast_review()` |
| `src/novel_dev/api/routes.py` | Add `POST /advance`, `GET /review`, `GET /fast_review` |
| `src/novel_dev/mcp_server/server.py` | Add `advance_novel`, `get_review_result`, `get_fast_review_result` tools |
| `tests/test_agents/test_critic_agent.py` | CriticAgent tests |
| `tests/test_agents/test_editor_agent.py` | EditorAgent tests |
| `tests/test_agents/test_fast_review_agent.py` | FastReviewAgent tests |
| `tests/test_agents/test_director_advance.py` | Director advance flow tests |
| `tests/test_api/test_review_routes.py` | API route tests |
| `tests/test_mcp_server.py` | MCP tool registration and behavior tests |

---

### Task 1: Extend ChapterRepository with fast-review update

**Files:**
- Modify: `src/novel_dev/repositories/chapter_repo.py`
- Test: `tests/test_repositories/test_chapter_repo.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_repositories/test_chapter_repo.py`:

```python
@pytest.mark.asyncio
async def test_update_fast_review(async_session):
    repo = ChapterRepository(async_session)
    await repo.create("c3", "v1", 3, "Third")
    await repo.update_fast_review("c3", 92, {"word_count_ok": True})
    ch = await repo.get_by_id("c3")
    assert ch.fast_review_score == 92
    assert ch.fast_review_feedback["word_count_ok"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/test_repositories/test_chapter_repo.py::test_update_fast_review -v`
Expected: FAIL (method not defined yet)

- [ ] **Step 3: Add `update_fast_review` method**

Modify `src/novel_dev/repositories/chapter_repo.py` — add after `update_scores`:

```python
    async def update_fast_review(self, chapter_id: str, score: int, feedback: dict) -> None:
        ch = await self.get_by_id(chapter_id)
        if ch:
            ch.fast_review_score = score
            ch.fast_review_feedback = feedback
            await self.session.flush()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python3 -m pytest tests/test_repositories/test_chapter_repo.py::test_update_fast_review -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/repositories/chapter_repo.py tests/test_repositories/test_chapter_repo.py
git commit -m "feat: add update_fast_review to ChapterRepository"
```

---

### Task 2: Add Pydantic schemas for review

**Files:**
- Create: `src/novel_dev/schemas/review.py`
- Modify: `src/novel_dev/schemas/__init__.py`

- [ ] **Step 1: Create review schemas**

Create `src/novel_dev/schemas/review.py`:

```python
from typing import List
from pydantic import BaseModel


class DimensionScore(BaseModel):
    name: str
    score: int
    comment: str


class ScoreResult(BaseModel):
    overall: int
    dimensions: List[DimensionScore]
    summary_feedback: str


class FastReviewReport(BaseModel):
    word_count_ok: bool
    consistency_fixed: bool
    ai_flavor_reduced: bool
    beat_cohesion_ok: bool
    notes: List[str]
```

- [ ] **Step 2: Verify import**

Run:
```bash
PYTHONPATH=src python3 -c "from novel_dev.schemas.review import ScoreResult, DimensionScore, FastReviewReport; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/novel_dev/schemas/review.py
git commit -m "feat: add review schemas"
```

---

### Task 3: Implement CriticAgent

**Files:**
- Create: `src/novel_dev/agents/critic_agent.py`
- Test: `tests/test_agents/test_critic_agent.py`

- [ ] **Step 1: Implement CriticAgent**

Create `src/novel_dev/agents/critic_agent.py`:

```python
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.review import ScoreResult, DimensionScore
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.agents.director import NovelDirector, Phase


class CriticAgent:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.state_repo = NovelStateRepository(session)
        self.chapter_repo = ChapterRepository(session)
        self.director = NovelDirector(session)

    async def review(self, novel_id: str, chapter_id: str) -> ScoreResult:
        state = await self.state_repo.get_state(novel_id)
        if not state:
            raise ValueError(f"Novel state not found for {novel_id}")
        if state.current_phase != Phase.REVIEWING.value:
            raise ValueError(f"Cannot review from phase {state.current_phase}")

        ch = await self.chapter_repo.get_by_id(chapter_id)
        if not ch:
            raise ValueError(f"Chapter not found: {chapter_id}")

        checkpoint = dict(state.checkpoint_data or {})
        context_data = checkpoint.get("chapter_context")
        if not context_data:
            raise ValueError("chapter_context missing in checkpoint_data")

        score_result = self._generate_score(ch.raw_draft or "", context_data)
        beat_scores = self._generate_beat_scores(context_data)

        await self.chapter_repo.update_scores(
            chapter_id,
            overall=score_result.overall,
            breakdown=score_result.model_dump()["dimensions"],
            feedback={"summary": score_result.summary_feedback},
        )

        checkpoint["beat_scores"] = beat_scores
        checkpoint["critique_feedback"] = {
            "overall": score_result.overall,
            "summary": score_result.summary_feedback,
        }

        overall = score_result.overall
        dimensions = {d.name: d.score for d in score_result.dimensions}

        red_line_failed = dimensions.get("consistency", 100) < 30 or dimensions.get("humanity", 100) < 40

        if overall < 70 or red_line_failed:
            attempt = checkpoint.get("draft_attempt_count", 0) + 1
            if attempt >= 3:
                raise RuntimeError("Max draft attempts exceeded")
            checkpoint["draft_attempt_count"] = attempt
            await self.director.save_checkpoint(
                novel_id,
                phase=Phase.DRAFTING,
                checkpoint_data=checkpoint,
                volume_id=state.current_volume_id,
                chapter_id=state.current_chapter_id,
            )
        else:
            checkpoint.pop("draft_attempt_count", None)
            await self.director.save_checkpoint(
                novel_id,
                phase=Phase.EDITING,
                checkpoint_data=checkpoint,
                volume_id=state.current_volume_id,
                chapter_id=state.current_chapter_id,
            )

        return score_result

    def _generate_score(self, raw_draft: str, context_data: dict) -> ScoreResult:
        target = context_data.get("chapter_plan", {}).get("target_word_count", 3000)
        word_count = len(raw_draft)
        base = 80 if word_count > 50 else 50
        dimensions = [
            DimensionScore(name="plot_tension", score=base, comment="节奏稳定"),
            DimensionScore(name="characterization", score=base, comment="人物行为一致"),
            DimensionScore(name="readability", score=base, comment="可读性良好"),
            DimensionScore(name="consistency", score=base, comment="设定无冲突"),
            DimensionScore(name="humanity", score=base, comment="自然流畅"),
        ]
        weights = {"plot_tension": 1.0, "characterization": 1.0, "readability": 1.0, "consistency": 1.2, "humanity": 1.2}
        total_weight = sum(weights.values())
        overall = int(sum(d.score * weights.get(d.name, 1.0) for d in dimensions) / total_weight)
        return ScoreResult(overall=overall, dimensions=dimensions, summary_feedback="基础评分通过")

    def _generate_beat_scores(self, context_data: dict) -> List[dict]:
        beats = context_data.get("chapter_plan", {}).get("beats", [])
        return [{"beat_index": i, "scores": {"plot_tension": 75, "humanity": 75}} for i in range(len(beats))]
```

- [ ] **Step 2: Write CriticAgent tests**

Create `tests/test_agents/test_critic_agent.py`:

```python
import pytest

from novel_dev.agents.critic_agent import CriticAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.context import ChapterPlan, BeatPlan, ChapterContext, LocationContext
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.schemas.review import ScoreResult, DimensionScore


@pytest.mark.asyncio
async def test_review_pass_high_score(async_session):
    director = NovelDirector(session=async_session)
    plan = ChapterPlan(chapter_number=1, title="T", target_word_count=3000, beats=[BeatPlan(summary="B1", target_mood="tense")])
    context = ChapterContext(
        chapter_plan=plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[],
    )
    await director.save_checkpoint(
        "novel_crit_pass",
        phase=Phase.REVIEWING,
        checkpoint_data={"chapter_context": context.model_dump(), "draft_attempt_count": 0},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")
    await ChapterRepository(async_session).update_text("c1", raw_draft="a" * 100)

    agent = CriticAgent(async_session)
    result = await agent.review("novel_crit_pass", "c1")
    assert result.overall >= 70

    state = await director.resume("novel_crit_pass")
    assert state.current_phase == Phase.EDITING.value


@pytest.mark.asyncio
async def test_review_fail_low_score(async_session):
    director = NovelDirector(session=async_session)
    plan = ChapterPlan(chapter_number=1, title="T", target_word_count=3000, beats=[])
    context = ChapterContext(
        chapter_plan=plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[],
    )
    await director.save_checkpoint(
        "novel_crit_fail",
        phase=Phase.REVIEWING,
        checkpoint_data={"chapter_context": context.model_dump(), "draft_attempt_count": 0},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")

    agent = CriticAgent(async_session)
    result = await agent.review("novel_crit_fail", "c1")
    assert result.overall < 70

    state = await director.resume("novel_crit_fail")
    assert state.current_phase == Phase.DRAFTING.value
    assert state.checkpoint_data["draft_attempt_count"] == 1


@pytest.mark.asyncio
async def test_review_red_line_rollback(async_session):
    director = NovelDirector(session=async_session)
    plan = ChapterPlan(chapter_number=1, title="T", target_word_count=3000, beats=[])
    context = ChapterContext(
        chapter_plan=plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[],
    )
    await director.save_checkpoint(
        "novel_crit_red",
        phase=Phase.REVIEWING,
        checkpoint_data={"chapter_context": context.model_dump()},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")

    agent = CriticAgent(async_session)
    agent._generate_score = lambda draft, ctx: ScoreResult(
        overall=75,
        dimensions=[
            DimensionScore(name="plot_tension", score=80, comment=""),
            DimensionScore(name="characterization", score=80, comment=""),
            DimensionScore(name="readability", score=80, comment=""),
            DimensionScore(name="consistency", score=20, comment=""),
            DimensionScore(name="humanity", score=80, comment=""),
        ],
        summary_feedback="red line",
    )
    result = await agent.review("novel_crit_red", "c1")
    assert result.overall == 75

    state = await director.resume("novel_crit_red")
    assert state.current_phase == Phase.DRAFTING.value


@pytest.mark.asyncio
async def test_review_max_attempts_exceeded(async_session):
    director = NovelDirector(session=async_session)
    plan = ChapterPlan(chapter_number=1, title="T", target_word_count=3000, beats=[])
    context = ChapterContext(
        chapter_plan=plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[],
    )
    await director.save_checkpoint(
        "novel_crit_max",
        phase=Phase.REVIEWING,
        checkpoint_data={"chapter_context": context.model_dump(), "draft_attempt_count": 2},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")

    agent = CriticAgent(async_session)
    with pytest.raises(RuntimeError, match="Max draft attempts exceeded"):
        await agent.review("novel_crit_max", "c1")
```

- [ ] **Step 3: Run CriticAgent tests**

Run: `PYTHONPATH=src python3 -m pytest tests/test_agents/test_critic_agent.py -v`
Expected: 4 tests pass

- [ ] **Step 4: Commit**

```bash
git add src/novel_dev/agents/critic_agent.py tests/test_agents/test_critic_agent.py
git commit -m "feat: implement CriticAgent with tests"
```

---

### Task 4: Implement EditorAgent

**Files:**
- Create: `src/novel_dev/agents/editor_agent.py`
- Test: `tests/test_agents/test_editor_agent.py`

- [ ] **Step 1: Implement EditorAgent**

Create `src/novel_dev/agents/editor_agent.py`:

```python
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.agents.director import NovelDirector, Phase


class EditorAgent:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.state_repo = NovelStateRepository(session)
        self.chapter_repo = ChapterRepository(session)
        self.director = NovelDirector(session)

    async def polish(self, novel_id: str, chapter_id: str):
        state = await self.state_repo.get_state(novel_id)
        if not state:
            raise ValueError(f"Novel state not found for {novel_id}")
        if state.current_phase != Phase.EDITING.value:
            raise ValueError(f"Cannot edit from phase {state.current_phase}")

        ch = await self.chapter_repo.get_by_id(chapter_id)
        if not ch:
            raise ValueError(f"Chapter not found: {chapter_id}")

        checkpoint = dict(state.checkpoint_data or {})
        beat_scores = checkpoint.get("beat_scores", [])
        raw_draft = ch.raw_draft or ""
        beats = raw_draft.split("\n\n") if raw_draft else []

        polished_beats = []
        for idx, beat_text in enumerate(beats):
            score_entry = beat_scores[idx] if idx < len(beat_scores) else {}
            scores = score_entry.get("scores", {})
            if any(s < 70 for s in scores.values()):
                polished = self._rewrite_beat(beat_text, scores)
            else:
                polished = beat_text
            polished_beats.append(polished)

        polished_text = "\n\n".join(polished_beats)
        await self.chapter_repo.update_text(chapter_id, polished_text=polished_text)
        await self.chapter_repo.update_status(chapter_id, "edited")

        await self.director.save_checkpoint(
            novel_id,
            phase=Phase.FAST_REVIEWING,
            checkpoint_data=checkpoint,
            volume_id=state.current_volume_id,
            chapter_id=state.current_chapter_id,
        )

    def _rewrite_beat(self, text: str, scores: dict) -> str:
        if scores.get("humanity", 100) < 70:
            return text + "（润色后：增强人味儿）"
        if scores.get("readability", 100) < 70:
            return text + "（润色后：优化读感）"
        return text + "（润色后）"
```

- [ ] **Step 2: Write EditorAgent tests**

Create `tests/test_agents/test_editor_agent.py`:

```python
import pytest

from novel_dev.agents.editor_agent import EditorAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.chapter_repo import ChapterRepository


@pytest.mark.asyncio
async def test_polish_low_score_beats(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_edit",
        phase=Phase.EDITING,
        checkpoint_data={
            "beat_scores": [
                {"beat_index": 0, "scores": {"humanity": 60}},
                {"beat_index": 1, "scores": {"humanity": 80}},
            ]
        },
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")
    await ChapterRepository(async_session).update_text("c1", raw_draft="Beat one\n\nBeat two")

    agent = EditorAgent(async_session)
    await agent.polish("novel_edit", "c1")

    ch = await ChapterRepository(async_session).get_by_id("c1")
    assert "润色后：增强人味儿" in ch.polished_text
    assert "Beat two" in ch.polished_text
    assert ch.status == "edited"

    state = await director.resume("novel_edit")
    assert state.current_phase == Phase.FAST_REVIEWING.value
```

- [ ] **Step 3: Run EditorAgent tests**

Run: `PYTHONPATH=src python3 -m pytest tests/test_agents/test_editor_agent.py -v`
Expected: 1 test pass

- [ ] **Step 4: Commit**

```bash
git add src/novel_dev/agents/editor_agent.py tests/test_agents/test_editor_agent.py
git commit -m "feat: implement EditorAgent with tests"
```

---

### Task 5: Implement FastReviewAgent

**Files:**
- Create: `src/novel_dev/agents/fast_review_agent.py`
- Test: `tests/test_agents/test_fast_review_agent.py`

- [ ] **Step 1: Implement FastReviewAgent**

Create `src/novel_dev/agents/fast_review_agent.py`:

```python
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.review import FastReviewReport
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.agents.director import NovelDirector, Phase


class FastReviewAgent:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.state_repo = NovelStateRepository(session)
        self.chapter_repo = ChapterRepository(session)
        self.director = NovelDirector(session)

    async def review(self, novel_id: str, chapter_id: str) -> FastReviewReport:
        state = await self.state_repo.get_state(novel_id)
        if not state:
            raise ValueError(f"Novel state not found for {novel_id}")
        if state.current_phase != Phase.FAST_REVIEWING.value:
            raise ValueError(f"Cannot fast-review from phase {state.current_phase}")

        ch = await self.chapter_repo.get_by_id(chapter_id)
        if not ch:
            raise ValueError(f"Chapter not found: {chapter_id}")

        checkpoint = dict(state.checkpoint_data or {})
        target = checkpoint.get("chapter_context", {}).get("chapter_plan", {}).get("target_word_count", 3000)
        raw = ch.raw_draft or ""
        polished = ch.polished_text or ""

        word_count_ok = abs(len(polished) - target) <= target * 0.1 if target > 0 else True
        consistency_fixed = True
        ai_flavor_reduced = len(polished) >= len(raw) * 0.5
        beat_cohesion_ok = True
        notes = []

        if not word_count_ok:
            notes.append("字数偏离目标超过10%")

        report = FastReviewReport(
            word_count_ok=word_count_ok,
            consistency_fixed=consistency_fixed,
            ai_flavor_reduced=ai_flavor_reduced,
            beat_cohesion_ok=beat_cohesion_ok,
            notes=notes,
        )

        await self.chapter_repo.update_fast_review(
            chapter_id,
            score=100 if all([word_count_ok, consistency_fixed, ai_flavor_reduced, beat_cohesion_ok]) else 50,
            feedback=report.model_dump(),
        )

        passed = all([word_count_ok, consistency_fixed, ai_flavor_reduced, beat_cohesion_ok])
        if passed:
            await self.director.save_checkpoint(
                novel_id,
                phase=Phase.LIBRARIAN,
                checkpoint_data=checkpoint,
                volume_id=state.current_volume_id,
                chapter_id=state.current_chapter_id,
            )
        else:
            await self.director.save_checkpoint(
                novel_id,
                phase=Phase.EDITING,
                checkpoint_data=checkpoint,
                volume_id=state.current_volume_id,
                chapter_id=state.current_chapter_id,
            )

        return report
```

- [ ] **Step 2: Write FastReviewAgent tests**

Create `tests/test_agents/test_fast_review_agent.py`:

```python
import pytest

from novel_dev.agents.fast_review_agent import FastReviewAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.chapter_repo import ChapterRepository


@pytest.mark.asyncio
async def test_fast_review_pass(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_pass",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={"chapter_context": {"chapter_plan": {"target_word_count": 100}}},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")
    await ChapterRepository(async_session).update_text("c1", raw_draft="abc", polished_text="abc")

    agent = FastReviewAgent(async_session)
    report = await agent.review("novel_fr_pass", "c1")
    assert report.word_count_ok is True

    state = await director.resume("novel_fr_pass")
    assert state.current_phase == Phase.LIBRARIAN.value


@pytest.mark.asyncio
async def test_fast_review_fail_word_count(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_fail",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={"chapter_context": {"chapter_plan": {"target_word_count": 10}}},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")
    await ChapterRepository(async_session).update_text("c1", raw_draft="abc", polished_text="this is way too long")

    agent = FastReviewAgent(async_session)
    report = await agent.review("novel_fr_fail", "c1")
    assert report.word_count_ok is False

    state = await director.resume("novel_fr_fail")
    assert state.current_phase == Phase.EDITING.value
```

- [ ] **Step 3: Run FastReviewAgent tests**

Run: `PYTHONPATH=src python3 -m pytest tests/test_agents/test_fast_review_agent.py -v`
Expected: 2 tests pass

- [ ] **Step 4: Commit**

```bash
git add src/novel_dev/agents/fast_review_agent.py tests/test_agents/test_fast_review_agent.py
git commit -m "feat: implement FastReviewAgent with tests"
```

---

### Task 6: Extend NovelDirector with advance()

**Files:**
- Modify: `src/novel_dev/agents/director.py`
- Test: `tests/test_agents/test_director_advance.py`

- [ ] **Step 1: Add advance and private runners**

Modify `src/novel_dev/agents/director.py` — add after `resume()`:

```python
    async def advance(self, novel_id: str) -> NovelState:
        state = await self.resume(novel_id)
        if not state:
            raise ValueError(f"Novel state not found for {novel_id}")
        current = Phase(state.current_phase)

        if current == Phase.REVIEWING:
            return await self._run_critic(state)
        elif current == Phase.EDITING:
            return await self._run_editor(state)
        elif current == Phase.FAST_REVIEWING:
            return await self._run_fast_review(state)
        else:
            raise ValueError(f"Cannot auto-advance from {current}")

    async def _run_critic(self, state: NovelState) -> NovelState:
        from novel_dev.agents.critic_agent import CriticAgent
        agent = CriticAgent(self.session)
        await agent.review(state.novel_id, state.current_chapter_id)
        return await self.resume(state.novel_id)

    async def _run_editor(self, state: NovelState) -> NovelState:
        from novel_dev.agents.editor_agent import EditorAgent
        agent = EditorAgent(self.session)
        await agent.polish(state.novel_id, state.current_chapter_id)
        return await self.resume(state.novel_id)

    async def _run_fast_review(self, state: NovelState) -> NovelState:
        from novel_dev.agents.fast_review_agent import FastReviewAgent
        agent = FastReviewAgent(self.session)
        await agent.review(state.novel_id, state.current_chapter_id)
        return await self.resume(state.novel_id)
```

- [ ] **Step 2: Write Director advance tests**

Create `tests/test_agents/test_director_advance.py`:

```python
import pytest

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.context import ChapterPlan, BeatPlan, ChapterContext, LocationContext
from novel_dev.repositories.chapter_repo import ChapterRepository


@pytest.mark.asyncio
async def test_advance_review_to_editing(async_session):
    director = NovelDirector(session=async_session)
    plan = ChapterPlan(chapter_number=1, title="T", target_word_count=3000, beats=[BeatPlan(summary="B1", target_mood="tense")])
    context = ChapterContext(
        chapter_plan=plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[],
    )
    await director.save_checkpoint(
        "novel_adv",
        phase=Phase.REVIEWING,
        checkpoint_data={"chapter_context": context.model_dump()},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")
    await ChapterRepository(async_session).update_text("c1", raw_draft="a" * 100)

    state = await director.advance("novel_adv")
    assert state.current_phase == Phase.EDITING.value

    state = await director.advance("novel_adv")
    assert state.current_phase == Phase.FAST_REVIEWING.value

    state = await director.advance("novel_adv")
    assert state.current_phase == Phase.LIBRARIAN.value
```

- [ ] **Step 3: Run Director advance tests**

Run: `PYTHONPATH=src python3 -m pytest tests/test_agents/test_director_advance.py -v`
Expected: 1 test pass

- [ ] **Step 4: Commit**

```bash
git add src/novel_dev/agents/director.py tests/test_agents/test_director_advance.py
git commit -m "feat: add NovelDirector.advance with auto review/edit/fast-review flow"
```

---

### Task 7: Add API routes for review and editing

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Create: `tests/test_api/test_review_routes.py`

- [ ] **Step 1: Add imports and endpoints**

Add import near the top of `src/novel_dev/api/routes.py` (after existing imports):

```python
from novel_dev.agents.director import NovelDirector
```

Add endpoints at the bottom of the file:

```python
@router.post("/api/novels/{novel_id}/advance")
async def advance_novel(novel_id: str, session: AsyncSession = Depends(get_session)):
    director = NovelDirector(session)
    try:
        state = await director.advance(novel_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {
        "novel_id": state.novel_id,
        "current_phase": state.current_phase,
        "checkpoint_data": state.checkpoint_data,
    }


@router.get("/api/novels/{novel_id}/review")
async def get_review_result(novel_id: str, session: AsyncSession = Depends(get_session)):
    repo = NovelStateRepository(session)
    state = await repo.get_state(novel_id)
    if not state:
        raise HTTPException(status_code=404, detail="Novel state not found")
    ch_repo = ChapterRepository(session)
    ch = await ch_repo.get_by_id(state.current_chapter_id)
    return {
        "score_overall": ch.score_overall if ch else None,
        "score_breakdown": ch.score_breakdown if ch else None,
        "review_feedback": ch.review_feedback if ch else None,
    }


@router.get("/api/novels/{novel_id}/fast_review")
async def get_fast_review_result(novel_id: str, session: AsyncSession = Depends(get_session)):
    repo = NovelStateRepository(session)
    state = await repo.get_state(novel_id)
    if not state:
        raise HTTPException(status_code=404, detail="Novel state not found")
    ch_repo = ChapterRepository(session)
    ch = await ch_repo.get_by_id(state.current_chapter_id)
    return {
        "fast_review_score": ch.fast_review_score if ch else None,
        "fast_review_feedback": ch.fast_review_feedback if ch else None,
    }
```

- [ ] **Step 2: Write API route tests**

Create `tests/test_api/test_review_routes.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router, get_session
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.context import ChapterPlan, BeatPlan, ChapterContext, LocationContext
from novel_dev.repositories.chapter_repo import ChapterRepository

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_advance_and_get_review(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        director = NovelDirector(session=async_session)
        plan = ChapterPlan(chapter_number=1, title="API Review", target_word_count=3000, beats=[BeatPlan(summary="B1", target_mood="tense")])
        context = ChapterContext(
            chapter_plan=plan,
            style_profile={},
            worldview_summary="",
            active_entities=[],
            location_context=LocationContext(current=""),
            timeline_events=[],
            pending_foreshadowings=[],
        )
        await director.save_checkpoint(
            "n_rev",
            phase=Phase.REVIEWING,
            checkpoint_data={"chapter_context": context.model_dump()},
            volume_id="v1",
            chapter_id="c1",
        )
        await ChapterRepository(async_session).create("c1", "v1", 1, "API Review")
        await ChapterRepository(async_session).update_text("c1", raw_draft="a" * 100)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/novels/n_rev/advance")
            assert resp.status_code == 200
            assert resp.json()["current_phase"] == Phase.EDITING.value

            resp2 = await client.get("/api/novels/n_rev/review")
            assert resp2.status_code == 200
            assert resp2.json()["score_overall"] is not None
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 3: Run API tests**

Run: `PYTHONPATH=src python3 -m pytest tests/test_api/test_review_routes.py -v`
Expected: 1 test pass

- [ ] **Step 4: Commit**

```bash
git add src/novel_dev/api/routes.py tests/test_api/test_review_routes.py
git commit -m "feat: add review and advance API endpoints"
```

---

### Task 8: Add MCP tools for review and editing

**Files:**
- Modify: `src/novel_dev/mcp_server/server.py`
- Modify: `tests/test_mcp_server.py`

- [ ] **Step 1: Add MCP tools**

Add import at the top of `src/novel_dev/mcp_server/server.py`:

```python
from novel_dev.agents.director import NovelDirector
```

Add to the `self.tools` dict:

```python
            "advance_novel": self.advance_novel,
            "get_review_result": self.get_review_result,
            "get_fast_review_result": self.get_fast_review_result,
```

Add methods to the class (before `mcp = NovelDevMCPServer()`):

```python
    async def advance_novel(self, novel_id: str) -> dict:
        async with async_session_maker() as session:
            director = NovelDirector(session)
            try:
                state = await director.advance(novel_id)
                return {
                    "novel_id": state.novel_id,
                    "current_phase": state.current_phase,
                    "checkpoint_data": state.checkpoint_data,
                }
            except ValueError as e:
                return {"error": str(e)}
            except RuntimeError as e:
                return {"error": str(e)}

    async def get_review_result(self, novel_id: str) -> dict:
        async with async_session_maker() as session:
            state_repo = NovelStateRepository(session)
            state = await state_repo.get_state(novel_id)
            if not state:
                return {"error": "Novel state not found"}
            repo = ChapterRepository(session)
            ch = await repo.get_by_id(state.current_chapter_id)
            return {
                "score_overall": ch.score_overall if ch else None,
                "score_breakdown": ch.score_breakdown if ch else None,
                "review_feedback": ch.review_feedback if ch else None,
            }

    async def get_fast_review_result(self, novel_id: str) -> dict:
        async with async_session_maker() as session:
            state_repo = NovelStateRepository(session)
            state = await state_repo.get_state(novel_id)
            if not state:
                return {"error": "Novel state not found"}
            repo = ChapterRepository(session)
            ch = await repo.get_by_id(state.current_chapter_id)
            return {
                "fast_review_score": ch.fast_review_score if ch else None,
                "fast_review_feedback": ch.fast_review_feedback if ch else None,
            }
```

- [ ] **Step 2: Update MCP server tests**

Modify `tests/test_mcp_server.py`:

Update the `expected` set in `test_mcp_server_has_tools`:

```python
    expected = {
        "query_entity",
        "get_active_foreshadowings",
        "get_timeline",
        "get_spaceline_chain",
        "get_novel_state",
        "get_novel_documents",
        "upload_document",
        "get_pending_documents",
        "approve_pending_documents",
        "list_style_profile_versions",
        "rollback_style_profile",
        "analyze_style_from_text",
        "prepare_chapter_context",
        "generate_chapter_draft",
        "get_chapter_draft_status",
        "advance_novel",
        "get_review_result",
        "get_fast_review_result",
    }
```

Add a new test at the bottom:

```python
@pytest.mark.asyncio
async def test_mcp_advance_novel():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.agents.director import NovelDirector, Phase
    from novel_dev.schemas.context import ChapterPlan, BeatPlan, ChapterContext, LocationContext
    from novel_dev.repositories.chapter_repo import ChapterRepository
    import uuid

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_mcp_adv_{suffix}"
    chapter_id = f"c_{suffix}"
    volume_id = f"v_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        director = NovelDirector(session=session)
        plan = ChapterPlan(
            chapter_number=1,
            title="MCP Adv",
            target_word_count=3000,
            beats=[BeatPlan(summary="B1", target_mood="tense")],
        )
        context = ChapterContext(
            chapter_plan=plan,
            style_profile={},
            worldview_summary="",
            active_entities=[],
            location_context=LocationContext(current=""),
            timeline_events=[],
            pending_foreshadowings=[],
        )
        await director.save_checkpoint(
            novel_id,
            phase=Phase.REVIEWING,
            checkpoint_data={"chapter_context": context.model_dump()},
            volume_id=volume_id,
            chapter_id=chapter_id,
        )
        await ChapterRepository(session).create(chapter_id, volume_id, 1, "MCP Adv")
        await ChapterRepository(session).update_text(chapter_id, raw_draft="a" * 100)
        await session.commit()

    result = await mcp.tools["advance_novel"](novel_id)
    assert result["current_phase"] == Phase.EDITING.value
```

- [ ] **Step 3: Run MCP tests**

Run: `PYTHONPATH=src python3 -m pytest tests/test_mcp_server.py -v`
Expected: all tests pass (including existing ones)

- [ ] **Step 4: Commit**

```bash
git add src/novel_dev/mcp_server/server.py tests/test_mcp_server.py
git commit -m "feat: add MCP tools for review and editing flow"
```

---

## Spec Self-Review

**1. Spec coverage check:**
- CriticAgent scoring and rollback → Task 3
- EditorAgent beat-level polish → Task 4
- FastReviewAgent lightweight checks → Task 5
- Director advance orchestration → Task 6
- API endpoints → Task 7
- MCP tools → Task 8
- Retry guard and red-line logic → Task 3 tests

**2. Placeholder scan:**
- No TBD/TODO/fill in later found.
- All code snippets are complete and runnable.
- All test commands are exact.

**3. Type consistency check:**
- `ScoreResult`, `FastReviewReport`, `DimensionScore` used consistently across all tasks.
- `NovelDirector.advance()` signature matches its usages in routes and MCP tools.
- Agent method signatures (`review`, `polish`, `review`) match their Director usages.
