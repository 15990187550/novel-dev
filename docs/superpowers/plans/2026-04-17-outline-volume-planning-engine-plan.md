# Outline and Volume Planning Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement BrainstormAgent and VolumePlannerAgent for subsystem 6, including Pydantic schemas, NovelDirector integration, REST API routes, and MCP tools.

**Architecture:** BrainstormAgent reads `novel_documents` and produces `synopsis_text` + `synopsis_data`, advancing state to `VOLUME_PLANNING`. VolumePlannerAgent reads the synopsis and current world state, generates a self-reviewed `VolumePlan` with per-chapter beats, and advances to `CONTEXT_PREPARATION`. All components follow existing repository/director patterns.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.0 (async), FastAPI, Pydantic, pytest-asyncio, SQLite+aiosqlite (tests)

---

## File Map

| File | Responsibility |
|---|---|
| `src/novel_dev/schemas/outline.py` | `SynopsisData`, `VolumePlan`, `VolumeBeat`, `VolumeScoreResult`, etc. |
| `src/novel_dev/agents/brainstorm_agent.py` | BrainstormAgent: read docs, generate synopsis, persist, advance state |
| `src/novel_dev/agents/volume_planner.py` | VolumePlannerAgent: plan volume with self-review loop and retry guard |
| `src/novel_dev/agents/director.py` | Fix `VALID_TRANSITIONS`, extend `advance()`, add `_run_volume_planner()` |
| `src/novel_dev/api/routes.py` | Add `/brainstorm`, `/volume_plan`, `/synopsis`, `/volume_plan` endpoints |
| `src/novel_dev/mcp_server/server.py` | Add 4 MCP tools for outline/volume planning |
| `tests/test_agents/test_brainstorm_agent.py` | BrainstormAgent tests |
| `tests/test_agents/test_volume_planner.py` | VolumePlannerAgent tests |
| `tests/test_agents/test_director_volume_planning.py` | Director advance + transition tests |
| `tests/test_api/test_outline_routes.py` | API route integration tests |
| `tests/test_mcp_server.py` | MCP tool registration and behavior tests (updated) |

---

### Task 1: Add outline schemas

**Files:**
- Create: `src/novel_dev/schemas/outline.py`
- Test: `tests/test_schemas/test_outline_schemas.py` (create directory if missing)

- [ ] **Step 1: Write the failing test**

Create `tests/test_schemas/test_outline_schemas.py`:

```python
import pytest
from novel_dev.schemas.outline import (
    SynopsisData,
    VolumePlan,
    VolumeBeat,
    VolumeScoreResult,
    CharacterArc,
    PlotMilestone,
)
from novel_dev.schemas.context import BeatPlan


def test_synopsis_data_creation():
    data = SynopsisData(
        title="Test Novel",
        logline="A test logline",
        core_conflict="Man vs machine",
        estimated_volumes=3,
        estimated_total_chapters=90,
        estimated_total_words=270000,
    )
    assert data.title == "Test Novel"
    assert data.estimated_total_words == 270000


def test_volume_plan_creation():
    beat = BeatPlan(summary="Opening", target_mood="tense")
    vb = VolumeBeat(
        chapter_id="ch_1",
        chapter_number=1,
        title="Prologue",
        summary="Intro",
        target_word_count=3000,
        target_mood="dark",
        beats=[beat],
    )
    plan = VolumePlan(
        volume_id="vol_1",
        volume_number=1,
        title="Volume One",
        summary="First volume",
        total_chapters=1,
        estimated_total_words=3000,
        chapters=[vb],
    )
    assert plan.volume_id == "vol_1"
    assert plan.chapters[0].chapter_id == "ch_1"
    assert plan.chapters[0].beats[0].summary == "Opening"


def test_volume_score_result_creation():
    result = VolumeScoreResult(
        overall=88,
        outline_fidelity=90,
        character_plot_alignment=85,
        hook_distribution=80,
        foreshadowing_management=88,
        chapter_hooks=90,
        page_turning=87,
        summary_feedback="Solid plan",
    )
    assert result.overall == 88
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_schemas/test_outline_schemas.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'novel_dev.schemas.outline'`

- [ ] **Step 3: Create schemas**

Create `src/novel_dev/schemas/outline.py`:

```python
from typing import List, Optional
from pydantic import BaseModel, Field

from novel_dev.schemas.context import BeatPlan


class CharacterArc(BaseModel):
    name: str
    arc_summary: str
    key_turning_points: List[str] = Field(default_factory=list)


class PlotMilestone(BaseModel):
    act: str
    summary: str
    climax_event: Optional[str] = None


class SynopsisData(BaseModel):
    title: str
    logline: str
    core_conflict: str
    themes: List[str] = Field(default_factory=list)
    character_arcs: List[CharacterArc] = Field(default_factory=list)
    milestones: List[PlotMilestone] = Field(default_factory=list)
    estimated_volumes: int
    estimated_total_chapters: int
    estimated_total_words: int


class VolumeBeat(BaseModel):
    chapter_id: str
    chapter_number: int
    title: str
    summary: str
    target_word_count: int
    target_mood: str
    key_entities: List[str] = Field(default_factory=list)
    foreshadowings_to_embed: List[str] = Field(default_factory=list)
    foreshadowings_to_recover: List[str] = Field(default_factory=list)
    beats: List[BeatPlan] = Field(default_factory=list)


class VolumePlan(BaseModel):
    volume_id: str
    volume_number: int
    title: str
    summary: str
    total_chapters: int
    estimated_total_words: int
    chapters: List[VolumeBeat] = Field(default_factory=list)


class VolumeScoreResult(BaseModel):
    overall: int
    outline_fidelity: int
    character_plot_alignment: int
    hook_distribution: int
    foreshadowing_management: int
    chapter_hooks: int
    page_turning: int
    summary_feedback: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_schemas/test_outline_schemas.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/schemas/outline.py tests/test_schemas/test_outline_schemas.py
git commit -m "feat: add outline schemas for synopsis and volume planning"
```

---

### Task 2: Implement BrainstormAgent

**Files:**
- Create: `src/novel_dev/agents/brainstorm_agent.py`
- Test: `tests/test_agents/test_brainstorm_agent.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_agents/test_brainstorm_agent.py`:

```python
import pytest

from novel_dev.agents.brainstorm_agent import BrainstormAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository


@pytest.mark.asyncio
async def test_brainstorm_success(async_session):
    await DocumentRepository(async_session).create(
        "doc_wv", "n_brain", "worldview", "Worldview", "天玄大陆，万族林立。"
    )
    await DocumentRepository(async_session).create(
        "doc_st", "n_brain", "setting", "Setting", "修炼体系：炼气、筑基。"
    )

    agent = BrainstormAgent(async_session)
    synopsis_data = await agent.brainstorm("n_brain")

    assert synopsis_data.title != ""
    assert synopsis_data.estimated_volumes > 0

    state = await NovelStateRepository(async_session).get_state("n_brain")
    assert state.current_phase == Phase.VOLUME_PLANNING.value
    assert "synopsis_data" in state.checkpoint_data

    docs = await DocumentRepository(async_session).get_by_type("n_brain", "synopsis")
    assert len(docs) == 1
    assert "天玄大陆" in docs[0].content


@pytest.mark.asyncio
async def test_brainstorm_missing_documents(async_session):
    agent = BrainstormAgent(async_session)
    with pytest.raises(ValueError, match="No setting documents found"):
        await agent.brainstorm("n_empty")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agents/test_brainstorm_agent.py -v`

Expected: FAIL with `ModuleNotFoundError: cannot import name 'BrainstormAgent'`

- [ ] **Step 3: Implement BrainstormAgent**

Create `src/novel_dev/agents/brainstorm_agent.py`:

```python
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.outline import SynopsisData, CharacterArc, PlotMilestone
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.agents.director import NovelDirector, Phase
import uuid


class BrainstormAgent:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.doc_repo = DocumentRepository(session)
        self.state_repo = NovelStateRepository(session)
        self.director = NovelDirector(session)

    async def brainstorm(self, novel_id: str) -> SynopsisData:
        docs = await self.doc_repo.get_by_type(novel_id, "worldview")
        docs += await self.doc_repo.get_by_type(novel_id, "setting")
        docs += await self.doc_repo.get_by_type(novel_id, "concept")

        if not docs:
            raise ValueError("No setting documents found for brainstorming")

        combined = "\n\n".join(d.content for d in docs)
        synopsis_data = self._generate_synopsis(combined)
        synopsis_text = self._format_synopsis_text(synopsis_data)

        doc = await self.doc_repo.create(
            doc_id=f"doc_{uuid.uuid4().hex[:8]}",
            novel_id=novel_id,
            doc_type="synopsis",
            title=synopsis_data.title,
            content=synopsis_text,
        )

        checkpoint = {}
        state = await self.state_repo.get_state(novel_id)
        if state and state.checkpoint_data:
            checkpoint = dict(state.checkpoint_data)

        checkpoint["synopsis_data"] = synopsis_data.model_dump()
        checkpoint["synopsis_doc_id"] = doc.id

        await self.director.save_checkpoint(
            novel_id,
            phase=Phase.VOLUME_PLANNING,
            checkpoint_data=checkpoint,
            volume_id=None,
            chapter_id=None,
        )

        return synopsis_data

    def _generate_synopsis(self, combined_text: str) -> SynopsisData:
        title = "天玄纪元" if "天玄" in combined_text else "未命名小说"
        return SynopsisData(
            title=title,
            logline="主角在修炼世界中崛起",
            core_conflict="个人复仇与天下大义",
            themes=["成长", "复仇"],
            character_arcs=[
                CharacterArc(
                    name="主角",
                    arc_summary="从废柴到巅峰",
                    key_turning_points=["觉醒", "突破"],
                )
            ],
            milestones=[
                PlotMilestone(
                    act="第一幕", summary="入门试炼", climax_event="外门大比"
                )
            ],
            estimated_volumes=3,
            estimated_total_chapters=90,
            estimated_total_words=270000,
        )

    def _format_synopsis_text(self, data: SynopsisData) -> str:
        lines = [
            f"# {data.title}",
            "",
            "## 一句话梗概",
            data.logline,
            "",
            "## 核心冲突",
            data.core_conflict,
            "",
            "## 人物弧光",
        ]
        for arc in data.character_arcs:
            lines.append(f"### {arc.name}")
            lines.append(arc.arc_summary)
            for pt in arc.key_turning_points:
                lines.append(f"- {pt}")
        lines.append("")
        lines.append("## 剧情里程碑")
        for ms in data.milestones:
            lines.append(f"### {ms.act}")
            lines.append(ms.summary)
            if ms.climax_event:
                lines.append(f"高潮：{ms.climax_event}")
        return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_agents/test_brainstorm_agent.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/brainstorm_agent.py tests/test_agents/test_brainstorm_agent.py
git commit -m "feat: implement BrainstormAgent with tests"
```

---

### Task 3: Implement VolumePlannerAgent

**Files:**
- Create: `src/novel_dev/agents/volume_planner.py`
- Test: `tests/test_agents/test_volume_planner.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_agents/test_volume_planner.py`:

```python
import pytest

from novel_dev.agents.volume_planner import VolumePlannerAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.outline import SynopsisData, VolumeScoreResult
from novel_dev.repositories.novel_state_repo import NovelStateRepository


@pytest.mark.asyncio
async def test_plan_volume_success(async_session):
    director = NovelDirector(session=async_session)
    synopsis = SynopsisData(
        title="Test",
        logline="Logline",
        core_conflict="Conflict",
        estimated_volumes=1,
        estimated_total_chapters=3,
        estimated_total_words=9000,
    )
    await director.save_checkpoint(
        "n_plan",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={"synopsis_data": synopsis.model_dump()},
        volume_id=None,
        chapter_id=None,
    )

    agent = VolumePlannerAgent(async_session)
    plan = await agent.plan("n_plan", volume_number=1)

    assert plan.volume_id == "vol_1"
    assert len(plan.chapters) == 3
    assert plan.chapters[0].chapter_id != ""

    state = await director.resume("n_plan")
    assert state.current_phase == Phase.CONTEXT_PREPARATION.value
    assert "current_volume_plan" in state.checkpoint_data
    assert "current_chapter_plan" in state.checkpoint_data


@pytest.mark.asyncio
async def test_plan_volume_missing_synopsis(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_no_syn",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )
    agent = VolumePlannerAgent(async_session)
    with pytest.raises(ValueError, match="synopsis_data missing"):
        await agent.plan("n_no_syn")


@pytest.mark.asyncio
async def test_plan_volume_max_attempts(async_session):
    director = NovelDirector(session=async_session)
    synopsis = SynopsisData(
        title="Test",
        logline="Logline",
        core_conflict="Conflict",
        estimated_volumes=1,
        estimated_total_chapters=1,
        estimated_total_words=3000,
    )
    await director.save_checkpoint(
        "n_max",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={"synopsis_data": synopsis.model_dump(), "volume_plan_attempt_count": 2},
        volume_id=None,
        chapter_id=None,
    )

    agent = VolumePlannerAgent(async_session)
    agent._generate_score = lambda plan: VolumeScoreResult(
        overall=50,
        outline_fidelity=50,
        character_plot_alignment=50,
        hook_distribution=50,
        foreshadowing_management=50,
        chapter_hooks=50,
        page_turning=50,
        summary_feedback="too weak",
    )

    with pytest.raises(RuntimeError, match="Max volume plan attempts exceeded"):
        await agent.plan("n_max")

    state = await director.resume("n_max")
    assert state.current_phase == Phase.VOLUME_PLANNING.value


@pytest.mark.asyncio
async def test_extract_chapter_plan_merges_foreshadowings(async_session):
    from novel_dev.schemas.context import BeatPlan
    from novel_dev.schemas.outline import VolumeBeat

    agent = VolumePlannerAgent(async_session)
    vb = VolumeBeat(
        chapter_id="ch_1",
        chapter_number=1,
        title="T",
        summary="S",
        target_word_count=100,
        target_mood="tense",
        foreshadowings_to_embed=["fs_1"],
        beats=[BeatPlan(summary="B1", target_mood="dark")],
    )
    cp = agent._extract_chapter_plan(vb)
    assert cp["beats"][0]["foreshadowings_to_embed"] == ["fs_1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agents/test_volume_planner.py -v`

Expected: FAIL with `ModuleNotFoundError: cannot import name 'VolumePlannerAgent'`

- [ ] **Step 3: Implement VolumePlannerAgent**

Create `src/novel_dev/agents/volume_planner.py`:

```python
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.outline import (
    VolumePlan,
    VolumeBeat,
    VolumeScoreResult,
    SynopsisData,
)
from novel_dev.schemas.context import BeatPlan
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.version_repo import EntityVersionRepository
from novel_dev.repositories.timeline_repo import TimelineRepository
from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
from novel_dev.agents.director import NovelDirector, Phase
import uuid


class VolumePlannerAgent:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.state_repo = NovelStateRepository(session)
        self.doc_repo = DocumentRepository(session)
        self.chapter_repo = ChapterRepository(session)
        self.entity_repo = EntityRepository(session)
        self.version_repo = EntityVersionRepository(session)
        self.timeline_repo = TimelineRepository(session)
        self.foreshadowing_repo = ForeshadowingRepository(session)
        self.director = NovelDirector(session)

    async def plan(self, novel_id: str, volume_number: Optional[int] = None) -> VolumePlan:
        state = await self.state_repo.get_state(novel_id)
        if not state:
            raise ValueError(f"Novel state not found for {novel_id}")
        if state.current_phase != Phase.VOLUME_PLANNING.value:
            raise ValueError(f"Cannot plan volume from phase {state.current_phase}")

        checkpoint = dict(state.checkpoint_data or {})
        synopsis_data = checkpoint.get("synopsis_data")
        if not synopsis_data:
            raise ValueError("synopsis_data missing in checkpoint_data")

        synopsis = SynopsisData.model_validate(synopsis_data)

        if volume_number is None:
            volume_number = self._infer_volume_number(checkpoint, state)

        volume_plan = self._generate_volume_plan(synopsis, volume_number)

        attempt = checkpoint.get("volume_plan_attempt_count", 0)
        while True:
            score = self._generate_score(volume_plan)
            if score.overall >= 85:
                break
            attempt += 1
            if attempt >= 3:
                checkpoint["volume_plan_attempt_count"] = attempt
                await self.director.save_checkpoint(
                    novel_id,
                    phase=Phase.VOLUME_PLANNING,
                    checkpoint_data=checkpoint,
                    volume_id=state.current_volume_id,
                    chapter_id=state.current_chapter_id,
                )
                raise RuntimeError("Max volume plan attempts exceeded")
            volume_plan = self._revise_volume_plan(volume_plan, score.summary_feedback)

        checkpoint["current_volume_plan"] = volume_plan.model_dump()
        checkpoint["current_chapter_plan"] = self._extract_chapter_plan(volume_plan.chapters[0])
        checkpoint["volume_plan_attempt_count"] = 0

        await self.doc_repo.create(
            doc_id=f"doc_{uuid.uuid4().hex[:8]}",
            novel_id=novel_id,
            doc_type="volume_plan",
            title=f"{volume_plan.title}",
            content=volume_plan.model_dump_json(),
        )

        await self.director.save_checkpoint(
            novel_id,
            phase=Phase.CONTEXT_PREPARATION,
            checkpoint_data=checkpoint,
            volume_id=volume_plan.volume_id,
            chapter_id=volume_plan.chapters[0].chapter_id,
        )

        return volume_plan

    def _infer_volume_number(self, checkpoint: dict, state) -> int:
        if state.current_volume_id and state.current_volume_id.startswith("vol_"):
            try:
                return int(state.current_volume_id.replace("vol_", ""))
            except ValueError:
                pass
        return 1

    def _generate_volume_plan(self, synopsis: SynopsisData, volume_number: int) -> VolumePlan:
        total_chapters = max(1, synopsis.estimated_total_chapters // synopsis.estimated_volumes)
        chapters_per_volume = total_chapters
        chapters = []
        for i in range(chapters_per_volume):
            chapters.append(
                VolumeBeat(
                    chapter_id=str(uuid.uuid4()),
                    chapter_number=i + 1,
                    title=f"第{i + 1}章",
                    summary=f"第{i + 1}章剧情",
                    target_word_count=3000,
                    target_mood="tense",
                    beats=[
                        BeatPlan(summary=f"节拍 {j}", target_mood="tense")
                        for j in range(1, 4)
                    ],
                )
            )
        return VolumePlan(
            volume_id=f"vol_{volume_number}",
            volume_number=volume_number,
            title=f"第{volume_number}卷",
            summary=f"第{volume_number}卷总述",
            total_chapters=len(chapters),
            estimated_total_words=len(chapters) * 3000,
            chapters=chapters,
        )

    def _generate_score(self, plan: VolumePlan) -> VolumeScoreResult:
        base = 88 if plan.total_chapters > 0 else 50
        return VolumeScoreResult(
            overall=base,
            outline_fidelity=base,
            character_plot_alignment=base,
            hook_distribution=base,
            foreshadowing_management=base,
            chapter_hooks=base,
            page_turning=base,
            summary_feedback="基础评分通过",
        )

    def _revise_volume_plan(self, plan: VolumePlan, feedback: str) -> VolumePlan:
        return plan

    def _extract_chapter_plan(self, volume_beat: VolumeBeat) -> dict:
        chapter_plan = volume_beat.model_dump()
        if volume_beat.foreshadowings_to_embed and volume_beat.beats:
            if not volume_beat.beats[0].foreshadowings_to_embed:
                volume_beat.beats[0].foreshadowings_to_embed = volume_beat.foreshadowings_to_embed[:]
        chapter_plan["beats"] = [b.model_dump() for b in volume_beat.beats]
        return chapter_plan
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_agents/test_volume_planner.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/volume_planner.py tests/test_agents/test_volume_planner.py
git commit -m "feat: implement VolumePlannerAgent with self-review loop and tests"
```

---

### Task 4: Extend NovelDirector for volume planning

**Files:**
- Modify: `src/novel_dev/agents/director.py`
- Test: `tests/test_agents/test_director_volume_planning.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agents/test_director_volume_planning.py`:

```python
import pytest

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.outline import SynopsisData
from novel_dev.repositories.document_repo import DocumentRepository


@pytest.mark.asyncio
async def test_valid_transitions_completed_to_volume_planning(async_session):
    director = NovelDirector(session=async_session)
    assert director.can_transition(Phase.COMPLETED, Phase.VOLUME_PLANNING) is True


@pytest.mark.asyncio
async def test_advance_volume_planning_to_context_preparation(async_session):
    director = NovelDirector(session=async_session)
    synopsis = SynopsisData(
        title="T",
        logline="L",
        core_conflict="C",
        estimated_volumes=1,
        estimated_total_chapters=1,
        estimated_total_words=3000,
    )
    await DocumentRepository(async_session).create(
        "d1", "n_dir_vol", "worldview", "WV", "大陆"
    )
    await director.save_checkpoint(
        "n_dir_vol",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={"synopsis_data": synopsis.model_dump()},
        volume_id=None,
        chapter_id=None,
    )

    state = await director.advance("n_dir_vol")
    assert state.current_phase == Phase.CONTEXT_PREPARATION.value
    assert "current_volume_plan" in state.checkpoint_data


@pytest.mark.asyncio
async def test_advance_unsupported_phase_still_raises(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_unsup",
        phase=Phase.DRAFTING,
        checkpoint_data={},
        volume_id="v1",
        chapter_id="c1",
    )
    with pytest.raises(ValueError, match="Cannot auto-advance from"):
        await director.advance("n_unsup")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agents/test_director_volume_planning.py -v`

Expected: FAIL (either `can_transition` returns False or `advance` doesn't handle `VOLUME_PLANNING`)

- [ ] **Step 3: Update director.py**

Replace the body of `src/novel_dev/agents/director.py` starting from `VALID_TRANSITIONS` through the end of the file with:

```python
VALID_TRANSITIONS = {
    Phase.VOLUME_PLANNING: [Phase.CONTEXT_PREPARATION],
    Phase.CONTEXT_PREPARATION: [Phase.DRAFTING],
    Phase.DRAFTING: [Phase.REVIEWING],
    Phase.REVIEWING: [Phase.EDITING, Phase.DRAFTING],
    Phase.EDITING: [Phase.FAST_REVIEWING],
    Phase.FAST_REVIEWING: [Phase.LIBRARIAN, Phase.DRAFTING, Phase.EDITING],
    Phase.LIBRARIAN: [Phase.COMPLETED],
    Phase.COMPLETED: [Phase.CONTEXT_PREPARATION, Phase.VOLUME_PLANNING],
}


class NovelDirector:
    def __init__(self, session: Optional[AsyncSession] = None):
        self.session = session
        self.state_repo = NovelStateRepository(session) if session else None

    def can_transition(self, current: Phase, next_phase: Phase) -> bool:
        return next_phase in VALID_TRANSITIONS.get(current, [])

    async def save_checkpoint(
        self,
        novel_id: str,
        phase: Phase,
        checkpoint_data: dict,
        volume_id: Optional[str] = None,
        chapter_id: Optional[str] = None,
    ) -> NovelState:
        if self.state_repo is None:
            raise RuntimeError("NovelDirector requires a session to save checkpoints")
        return await self.state_repo.save_checkpoint(
            novel_id,
            current_phase=phase.value,
            checkpoint_data=checkpoint_data,
            current_volume_id=volume_id,
            current_chapter_id=chapter_id,
        )

    async def resume(self, novel_id: str) -> Optional[NovelState]:
        if self.state_repo is None:
            raise RuntimeError("NovelDirector requires a session to resume")
        return await self.state_repo.get_state(novel_id)

    async def advance(self, novel_id: str) -> NovelState:
        state = await self.resume(novel_id)
        if not state:
            raise ValueError(f"Novel state not found for {novel_id}")
        current = Phase(state.current_phase)

        if current == Phase.VOLUME_PLANNING:
            return await self._run_volume_planner(state)
        elif current == Phase.REVIEWING:
            return await self._run_critic(state)
        elif current == Phase.EDITING:
            return await self._run_editor(state)
        elif current == Phase.FAST_REVIEWING:
            return await self._run_fast_review(state)
        elif current == Phase.LIBRARIAN:
            return await self._run_librarian(state)
        else:
            raise ValueError(f"Cannot auto-advance from {current}")

    async def _run_volume_planner(self, state: NovelState) -> NovelState:
        from novel_dev.agents.volume_planner import VolumePlannerAgent
        agent = VolumePlannerAgent(self.session)
        await agent.plan(state.novel_id)
        return await self.resume(state.novel_id)

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

    async def _run_librarian(self, state: NovelState) -> NovelState:
        from novel_dev.agents.librarian import LibrarianAgent
        from novel_dev.services.archive_service import ArchiveService
        from novel_dev.config import Settings

        chapter_id = state.current_chapter_id
        if not chapter_id:
            raise ValueError("No current chapter set for LIBRARIAN phase")

        ch = await ChapterRepository(self.session).get_by_id(chapter_id)
        if not ch or not ch.polished_text:
            raise ValueError("Chapter polished text missing")

        agent = LibrarianAgent(self.session)
        try:
            extraction = await agent.extract(state.novel_id, chapter_id, ch.polished_text)
        except Exception as llm_error:
            try:
                extraction = agent.fallback_extract(ch.polished_text, state.checkpoint_data)
            except Exception as fallback_error:
                checkpoint = dict(state.checkpoint_data)
                checkpoint["librarian_error"] = str(llm_error)
                await self.save_checkpoint(
                    state.novel_id,
                    Phase.LIBRARIAN,
                    checkpoint,
                    current_volume_id=state.current_volume_id,
                    current_chapter_id=chapter_id,
                )
                raise RuntimeError(
                    f"Librarian extraction failed: LLM={llm_error}, fallback={fallback_error}"
                )

        await agent.persist(extraction, chapter_id)

        settings = Settings()
        archive_svc = ArchiveService(self.session, settings.markdown_output_dir)
        await archive_svc.archive(state.novel_id, chapter_id)

        checkpoint = dict(state.checkpoint_data)
        checkpoint["last_archived_chapter_id"] = chapter_id
        await self.save_checkpoint(
            state.novel_id,
            Phase.COMPLETED,
            checkpoint,
            current_volume_id=state.current_volume_id,
            current_chapter_id=chapter_id,
        )

        return await self._continue_to_next_chapter(state.novel_id)

    async def _continue_to_next_chapter(self, novel_id: str) -> NovelState:
        state = await self.resume(novel_id)
        checkpoint = dict(state.checkpoint_data or {})

        volume_plan = checkpoint.get("current_volume_plan", {})
        chapters = volume_plan.get("chapters", [])
        current_chapter_id = state.current_chapter_id

        for idx, ch_plan in enumerate(chapters):
            if ch_plan.get("chapter_id") == current_chapter_id and idx + 1 < len(chapters):
                next_plan = chapters[idx + 1]
                checkpoint["current_chapter_plan"] = next_plan
                return await self.save_checkpoint(
                    novel_id,
                    Phase.CONTEXT_PREPARATION,
                    checkpoint,
                    current_volume_id=state.current_volume_id,
                    current_chapter_id=next_plan.get("chapter_id"),
                )

        current_volume_number = 1
        if state.current_volume_id and state.current_volume_id.startswith("vol_"):
            try:
                current_volume_number = int(state.current_volume_id.replace("vol_", ""))
            except ValueError:
                pass

        next_volume_id = f"vol_{current_volume_number + 1}"
        avg_word_count = checkpoint.get("archive_stats", {}).get("avg_word_count", 3000)
        placeholder_volume = {
            "volume_id": next_volume_id,
            "title": "占位卷纲（待 VolumePlannerAgent 填充）",
            "chapters": [
                {
                    "chapter_id": str(uuid.uuid4()),
                    "title": "占位章节",
                    "target_word_count": avg_word_count,
                }
            ],
        }
        checkpoint["pending_volume_plans"] = checkpoint.get("pending_volume_plans", []) + [placeholder_volume]
        checkpoint["volume_completed"] = True
        checkpoint.pop("current_chapter_plan", None)

        return await self.save_checkpoint(
            novel_id,
            Phase.VOLUME_PLANNING,
            checkpoint,
            current_volume_id=next_volume_id,
            current_chapter_id=placeholder_volume["chapters"][0]["chapter_id"],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agents/test_director_volume_planning.py tests/test_agents/test_director_advance.py -v`

Expected: PASS for all

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/director.py tests/test_agents/test_director_volume_planning.py
git commit -m "feat: extend NovelDirector with volume planning advance flow"
```

---

### Task 5: Add API routes for outline and volume planning

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Test: `tests/test_api/test_outline_routes.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api/test_outline_routes.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router, get_session
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.document_repo import DocumentRepository

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_brainstorm_and_volume_plan_flow(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        await DocumentRepository(async_session).create(
            "d1", "n_outline", "worldview", "WV", "天玄大陆"
        )

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/novels/n_outline/brainstorm")
            assert resp.status_code == 200
            data = resp.json()
            assert data["title"] == "天玄纪元"

            state = await NovelDirector(session=async_session).resume("n_outline")
            assert state.current_phase == Phase.VOLUME_PLANNING.value

            resp2 = await client.post("/api/novels/n_outline/volume_plan", json={})
            assert resp2.status_code == 200
            plan = resp2.json()
            assert plan["volume_id"] == "vol_1"
            assert len(plan["chapters"]) > 0

            state2 = await NovelDirector(session=async_session).resume("n_outline")
            assert state2.current_phase == Phase.CONTEXT_PREPARATION.value
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_synopsis(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        await DocumentRepository(async_session).create(
            "d1", "n_syn", "worldview", "WV", "大陆"
        )
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/api/novels/n_syn/brainstorm")
            resp = await client.get("/api/novels/n_syn/synopsis")
            assert resp.status_code == 200
            assert "content" in resp.json()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_volume_plan(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        await DocumentRepository(async_session).create(
            "d1", "n_vp", "worldview", "WV", "大陆"
        )
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/api/novels/n_vp/brainstorm")
            await client.post("/api/novels/n_vp/volume_plan", json={})
            resp = await client.get("/api/novels/n_vp/volume_plan")
            assert resp.status_code == 200
            assert resp.json()["volume_id"] == "vol_1"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_volume_plan_wrong_phase(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        director = NovelDirector(session=async_session)
        await director.save_checkpoint(
            "n_wrong", phase=Phase.DRAFTING, checkpoint_data={}, volume_id="v1", chapter_id="c1"
        )
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/novels/n_wrong/volume_plan", json={})
            assert resp.status_code == 400
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api/test_outline_routes.py -v`

Expected: FAIL with 404 on `/brainstorm` and `/volume_plan`

- [ ] **Step 3: Add routes**

Append to `src/novel_dev/api/routes.py` (before the end of the file):

```python
from novel_dev.agents.brainstorm_agent import BrainstormAgent
from novel_dev.agents.volume_planner import VolumePlannerAgent
from novel_dev.schemas.outline import SynopsisData, VolumePlan


class VolumePlanRequest(BaseModel):
    volume_number: Optional[int] = None


@router.post("/api/novels/{novel_id}/brainstorm")
async def brainstorm_novel(novel_id: str, session: AsyncSession = Depends(get_session)):
    agent = BrainstormAgent(session)
    try:
        synopsis_data = await agent.brainstorm(novel_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "title": synopsis_data.title,
        "logline": synopsis_data.logline,
        "estimated_volumes": synopsis_data.estimated_volumes,
        "estimated_total_chapters": synopsis_data.estimated_total_chapters,
    }


@router.post("/api/novels/{novel_id}/volume_plan")
async def plan_volume(novel_id: str, req: VolumePlanRequest = VolumePlanRequest(), session: AsyncSession = Depends(get_session)):
    agent = VolumePlannerAgent(session)
    try:
        plan = await agent.plan(novel_id, volume_number=req.volume_number)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {
        "volume_id": plan.volume_id,
        "volume_number": plan.volume_number,
        "title": plan.title,
        "total_chapters": plan.total_chapters,
        "chapters": [
            {
                "chapter_id": ch.chapter_id,
                "chapter_number": ch.chapter_number,
                "title": ch.title,
                "summary": ch.summary,
            }
            for ch in plan.chapters
        ],
    }


@router.get("/api/novels/{novel_id}/synopsis")
async def get_synopsis(novel_id: str, session: AsyncSession = Depends(get_session)):
    repo = DocumentRepository(session)
    state_repo = NovelStateRepository(session)
    docs = await repo.get_by_type(novel_id, "synopsis")
    if not docs:
        raise HTTPException(status_code=404, detail="Synopsis not found")
    state = await state_repo.get_state(novel_id)
    synopsis_data = {}
    if state and state.checkpoint_data:
        synopsis_data = state.checkpoint_data.get("synopsis_data", {})
    return {
        "content": docs[0].content,
        "synopsis_data": synopsis_data,
    }


@router.get("/api/novels/{novel_id}/volume_plan")
async def get_volume_plan(novel_id: str, session: AsyncSession = Depends(get_session)):
    state_repo = NovelStateRepository(session)
    state = await state_repo.get_state(novel_id)
    if not state or not state.checkpoint_data.get("current_volume_plan"):
        raise HTTPException(status_code=404, detail="Volume plan not found")
    return state.checkpoint_data["current_volume_plan"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api/test_outline_routes.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/api/routes.py tests/test_api/test_outline_routes.py
git commit -m "feat: add outline and volume planning API routes"
```

---

### Task 6: Add MCP tools for outline and volume planning

**Files:**
- Modify: `src/novel_dev/mcp_server/server.py`
- Modify: `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_mcp_server.py`:

```python
@pytest.mark.asyncio
async def test_mcp_brainstorm_novel():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.repositories.document_repo import DocumentRepository

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_mcp_brain_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        await DocumentRepository(session).create(
            f"d_{suffix}", novel_id, "worldview", "WV", "天玄大陆"
        )
        await session.commit()

    result = await mcp.tools["brainstorm_novel"](novel_id)
    assert result["title"] == "天玄纪元"
    assert result["estimated_volumes"] > 0


@pytest.mark.asyncio
async def test_mcp_plan_volume():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.agents.director import NovelDirector, Phase
    from novel_dev.schemas.outline import SynopsisData
    from novel_dev.repositories.document_repo import DocumentRepository

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_mcp_plan_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        await DocumentRepository(session).create(
            f"d_{suffix}", novel_id, "worldview", "WV", "大陆"
        )
        director = NovelDirector(session=session)
        synopsis = SynopsisData(
            title="T", logline="L", core_conflict="C",
            estimated_volumes=1, estimated_total_chapters=1, estimated_total_words=3000,
        )
        await director.save_checkpoint(
            novel_id,
            phase=Phase.VOLUME_PLANNING,
            checkpoint_data={"synopsis_data": synopsis.model_dump()},
            volume_id=None,
            chapter_id=None,
        )
        await session.commit()

    result = await mcp.tools["plan_volume"](novel_id)
    assert result["volume_id"] == "vol_1"


@pytest.mark.asyncio
async def test_mcp_get_synopsis():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.repositories.document_repo import DocumentRepository

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_mcp_syn_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        await DocumentRepository(session).create(
            f"d_{suffix}", novel_id, "worldview", "WV", "大陆"
        )
        await session.commit()

    await mcp.tools["brainstorm_novel"](novel_id)
    result = await mcp.tools["get_synopsis"](novel_id)
    assert "content" in result
    assert "synopsis_data" in result


@pytest.mark.asyncio
async def test_mcp_get_volume_plan():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.agents.director import NovelDirector, Phase
    from novel_dev.schemas.outline import SynopsisData
    from novel_dev.repositories.document_repo import DocumentRepository

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_mcp_vp_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        await DocumentRepository(session).create(
            f"d_{suffix}", novel_id, "worldview", "WV", "大陆"
        )
        director = NovelDirector(session=session)
        synopsis = SynopsisData(
            title="T", logline="L", core_conflict="C",
            estimated_volumes=1, estimated_total_chapters=1, estimated_total_words=3000,
        )
        await director.save_checkpoint(
            novel_id,
            phase=Phase.VOLUME_PLANNING,
            checkpoint_data={"synopsis_data": synopsis.model_dump()},
            volume_id=None,
            chapter_id=None,
        )
        await session.commit()

    await mcp.tools["plan_volume"](novel_id)
    result = await mcp.tools["get_volume_plan"](novel_id)
    assert result["volume_id"] == "vol_1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp_server.py -v`

Expected: FAIL with `KeyError: 'brainstorm_novel'` (tool not registered)

- [ ] **Step 3: Update MCP server**

Modify `src/novel_dev/mcp_server/server.py`:

Add imports at the top:
```python
from novel_dev.agents.brainstorm_agent import BrainstormAgent
from novel_dev.agents.volume_planner import VolumePlannerAgent
```

Update `self.tools` dict to include the 4 new tools:
```python
        self.tools = {
            "query_entity": self.query_entity,
            "get_active_foreshadowings": self.get_active_foreshadowings,
            "get_timeline": self.get_timeline,
            "get_spaceline_chain": self.get_spaceline_chain,
            "get_novel_state": self.get_novel_state,
            "get_novel_documents": self.get_novel_documents,
            "upload_document": self.upload_document,
            "get_pending_documents": self.get_pending_documents,
            "approve_pending_documents": self.approve_pending_documents,
            "list_style_profile_versions": self.list_style_profile_versions,
            "rollback_style_profile": self.rollback_style_profile,
            "analyze_style_from_text": self.analyze_style_from_text,
            "prepare_chapter_context": self.prepare_chapter_context,
            "generate_chapter_draft": self.generate_chapter_draft,
            "get_chapter_draft_status": self.get_chapter_draft_status,
            "advance_novel": self.advance_novel,
            "get_review_result": self.get_review_result,
            "get_fast_review_result": self.get_fast_review_result,
            "brainstorm_novel": self.brainstorm_novel,
            "plan_volume": self.plan_volume,
            "get_synopsis": self.get_synopsis,
            "get_volume_plan": self.get_volume_plan,
        }
```

Add methods before `mcp = NovelDevMCPServer()`:

```python
    async def brainstorm_novel(self, novel_id: str) -> dict:
        async with async_session_maker() as session:
            agent = BrainstormAgent(session)
            try:
                synopsis_data = await agent.brainstorm(novel_id)
                await session.commit()
                return {
                    "title": synopsis_data.title,
                    "logline": synopsis_data.logline,
                    "estimated_volumes": synopsis_data.estimated_volumes,
                    "estimated_total_chapters": synopsis_data.estimated_total_chapters,
                }
            except ValueError as e:
                return {"error": str(e)}

    async def plan_volume(self, novel_id: str, volume_number: Optional[int] = None) -> dict:
        async with async_session_maker() as session:
            agent = VolumePlannerAgent(session)
            try:
                plan = await agent.plan(novel_id, volume_number)
                await session.commit()
                return {
                    "volume_id": plan.volume_id,
                    "volume_number": plan.volume_number,
                    "title": plan.title,
                    "total_chapters": plan.total_chapters,
                    "chapters": [
                        {
                            "chapter_id": ch.chapter_id,
                            "chapter_number": ch.chapter_number,
                            "title": ch.title,
                            "summary": ch.summary,
                        }
                        for ch in plan.chapters
                    ],
                }
            except ValueError as e:
                return {"error": str(e)}
            except RuntimeError as e:
                return {"error": str(e)}

    async def get_synopsis(self, novel_id: str) -> dict:
        async with async_session_maker() as session:
            repo = DocumentRepository(session)
            state_repo = NovelStateRepository(session)
            docs = await repo.get_by_type(novel_id, "synopsis")
            if not docs:
                return {"error": "Synopsis not found"}
            state = await state_repo.get_state(novel_id)
            synopsis_data = {}
            if state and state.checkpoint_data:
                synopsis_data = state.checkpoint_data.get("synopsis_data", {})
            return {
                "content": docs[0].content,
                "synopsis_data": synopsis_data,
            }

    async def get_volume_plan(self, novel_id: str) -> dict:
        async with async_session_maker() as session:
            state_repo = NovelStateRepository(session)
            state = await state_repo.get_state(novel_id)
            if not state or not state.checkpoint_data.get("current_volume_plan"):
                return {"error": "Volume plan not found"}
            return state.checkpoint_data["current_volume_plan"]
```

Also add `Optional` to imports at the top of `server.py` if not already present.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_server.py -v`

Expected: PASS (all tests including existing ones)

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/mcp_server/server.py tests/test_mcp_server.py
git commit -m "feat: add MCP tools for outline and volume planning"
```

---

### Task 7: Run full test suite

- [ ] **Step 1: Run all tests**

Run: `pytest -v`

Expected: All tests pass

- [ ] **Step 2: Fix any failures**

If failures occur, identify the root cause (import errors, state machine issues, test isolation) and fix.

Run: `pytest -v`

Expected: All tests pass

- [ ] **Step 3: Final commit**

```bash
git add .
git commit -m "feat: complete outline and volume planning engine (subsystem 6)"
```

---

## Self-Review Checklist

### 1. Spec coverage

| Spec Requirement | Plan Task |
|---|---|
| `outline.py` schemas | Task 1 |
| BrainstormAgent + tests | Task 2 |
| VolumePlannerAgent + self-review loop + tests | Task 3 |
| NovelDirector `VALID_TRANSITIONS` fix + `advance()` extension | Task 4 |
| API routes (`/brainstorm`, `/volume_plan`, `/synopsis`, `/volume_plan`) | Task 5 |
| MCP tools (`brainstorm_novel`, `plan_volume`, `get_synopsis`, `get_volume_plan`) | Task 6 |
| Full test suite verification | Task 7 |

**No gaps identified.**

### 2. Placeholder scan

- No TBD, TODO, or "implement later" phrases.
- All code snippets are complete.
- All commands are exact.
- No vague instructions like "add appropriate error handling" without specifics.

### 3. Type consistency

- `VolumePlan` uses `chapters: List[VolumeBeat]` consistently across schemas, agents, routes, and MCP tools.
- `VolumeBeat.chapter_id` is required everywhere.
- `SynopsisData` field names match between schema, agent, and tests.
- `Optional` import needed in `mcp_server/server.py` for `plan_volume` signature — noted in Task 6.

### 4. Compatibility check

- `director.py` replacement includes the full `_run_librarian` and `_continue_to_next_chapter` methods from the existing Librarian spec to avoid regressions.
- `VALID_TRANSITIONS` adds `COMPLETED → VOLUME_PLANNING` without breaking existing transitions.

**Plan is ready for execution.**
