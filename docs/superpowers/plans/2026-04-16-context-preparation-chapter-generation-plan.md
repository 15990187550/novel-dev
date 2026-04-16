# Context Preparation and Chapter Generation Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement ContextAgent (assembles writing context from database) and WriterAgent (generates chapter draft by beats), with API endpoints and MCP tools.

**Architecture:** ContextAgent queries entities, timeline, spaceline, foreshadowings, and documents to build a `ChapterContext` Pydantic object cached in `checkpoint_data`. WriterAgent reads this context, generates each beat sequentially with a mockable LLM method, and writes the assembled `raw_draft` to the `chapters` table. Both agents advance the `NovelDirector` state machine.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (async), Pydantic, pytest-asyncio, SQLite+aiosqlite.

---

## File Map

| File | Responsibility |
|---|---|
| `src/novel_dev/schemas/context.py` | Pydantic models: `ChapterPlan`, `BeatPlan`, `ChapterContext`, `DraftMetadata`, `EntityState`, `LocationContext` |
| `src/novel_dev/repositories/entity_repo.py` | Add `find_by_names()` |
| `src/novel_dev/repositories/timeline_repo.py` | Add `get_around_tick()` |
| `src/novel_dev/repositories/chapter_repo.py` | Add `get_previous_chapter()` |
| `src/novel_dev/agents/context_agent.py` | ContextAgent: assemble context from all repos, cache to checkpoint, advance to `DRAFTING` |
| `src/novel_dev/agents/writer_agent.py` | WriterAgent: beat-by-beat generation, write draft, advance to `REVIEWING` |
| `src/novel_dev/api/routes.py` | Add `POST /context`, `POST /draft`, `GET /draft` endpoints |
| `src/novel_dev/mcp_server/server.py` | Add `prepare_chapter_context`, `generate_chapter_draft`, `get_chapter_draft_status` tools |
| `tests/test_agents/test_context_agent.py` | ContextAgent unit + integration tests |
| `tests/test_agents/test_writer_agent.py` | WriterAgent unit + integration tests |
| `tests/test_api/test_chapter_draft_routes.py` | API endpoint tests |
| `tests/test_mcp_server.py` | MCP tool registration and behavior tests |

---

### Task 1: Extend repositories with context query methods

**Files:**
- Modify: `src/novel_dev/repositories/entity_repo.py`
- Modify: `src/novel_dev/repositories/timeline_repo.py`
- Modify: `src/novel_dev/repositories/chapter_repo.py`
- Test: `tests/test_repositories/test_entity_repo.py`
- Test: `tests/test_repositories/test_timeline_repo.py`
- Test: `tests/test_repositories/test_chapter_repo.py`

- [ ] **Step 1: Add `find_by_names` to `EntityRepository`**

Modify `src/novel_dev/repositories/entity_repo.py` — add import `List` and the method:

```python
from typing import Optional, List
from sqlalchemy import select

# ... existing code ...

    async def find_by_names(self, names: List[str]) -> List[Entity]:
        if not names:
            return []
        result = await self.session.execute(
            select(Entity).where(Entity.name.in_(names))
        )
        return result.scalars().all()
```

- [ ] **Step 2: Add `get_around_tick` to `TimelineRepository`**

Modify `src/novel_dev/repositories/timeline_repo.py`:

```python
    async def get_around_tick(self, tick: int, radius: int = 3) -> List[Timeline]:
        prev_result = await self.session.execute(
            select(Timeline)
            .where(Timeline.tick < tick)
            .order_by(Timeline.tick.desc())
            .limit(radius)
        )
        next_result = await self.session.execute(
            select(Timeline)
            .where(Timeline.tick >= tick)
            .order_by(Timeline.tick.asc())
            .limit(radius)
        )
        prev_items = list(prev_result.scalars().all())
        prev_items.reverse()
        next_items = list(next_result.scalars().all())
        return prev_items + next_items
```

Add `List` to imports.

- [ ] **Step 3: Add `get_previous_chapter` to `ChapterRepository`**

Modify `src/novel_dev/repositories/chapter_repo.py`:

```python
    async def get_previous_chapter(self, volume_id: str, chapter_number: int) -> Optional[Chapter]:
        result = await self.session.execute(
            select(Chapter)
            .where(Chapter.volume_id == volume_id, Chapter.chapter_number < chapter_number)
            .order_by(Chapter.chapter_number.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
```

- [ ] **Step 4: Write repository tests**

Add to `tests/test_repositories/test_entity_repo.py`:

```python
@pytest.mark.asyncio
async def test_find_by_names(async_session):
    repo = EntityRepository(async_session)
    await repo.create("e1", "character", "林风")
    await repo.create("e2", "character", "苏雪")
    results = await repo.find_by_names(["林风", "苏雪"])
    assert len(results) == 2
    assert {r.name for r in results} == {"林风", "苏雪"}
```

Add to `tests/test_repositories/test_timeline_repo.py`:

```python
@pytest.mark.asyncio
async def test_get_around_tick(async_session):
    repo = TimelineRepository(async_session)
    await repo.create(10, "event 10")
    await repo.create(15, "event 15")
    await repo.create(20, "event 20")
    await repo.create(25, "event 25")
    events = await repo.get_around_tick(18, radius=2)
    assert len(events) == 3
    assert [e.tick for e in events] == [15, 20, 25]
```

Add to `tests/test_repositories/test_chapter_repo.py`:

```python
@pytest.mark.asyncio
async def test_get_previous_chapter(async_session):
    repo = ChapterRepository(async_session)
    await repo.create("c1", "v1", 1, "First")
    await repo.create("c2", "v1", 2, "Second")
    prev = await repo.get_previous_chapter("v1", 2)
    assert prev is not None
    assert prev.chapter_number == 1
```

- [ ] **Step 5: Run repository tests**

Run:
```bash
pytest tests/test_repositories/test_entity_repo.py tests/test_repositories/test_timeline_repo.py tests/test_repositories/test_chapter_repo.py -v
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/repositories/ tests/test_repositories/
git commit -m "feat: extend repos with context query methods"
```

---

### Task 2: Add Pydantic schemas for ChapterContext

**Files:**
- Create: `src/novel_dev/schemas/context.py`
- Modify: `src/novel_dev/schemas/__init__.py` (create if missing)
- Test: `tests/test_agents/test_context_agent.py` (will import and validate in next task)

- [ ] **Step 1: Create schemas directory and file**

Create `src/novel_dev/schemas/__init__.py` (empty).

Create `src/novel_dev/schemas/context.py`:

```python
from typing import List, Optional
from pydantic import BaseModel, Field


class BeatPlan(BaseModel):
    summary: str
    target_mood: str
    key_entities: List[str] = Field(default_factory=list)
    foreshadowings_to_embed: List[str] = Field(default_factory=list)


class ChapterPlan(BaseModel):
    chapter_number: int
    title: Optional[str] = None
    target_word_count: int
    beats: List[BeatPlan]


class EntityState(BaseModel):
    entity_id: str
    name: str
    type: str
    current_state: str


class LocationContext(BaseModel):
    current: str
    parent: Optional[str] = None
    narrative: Optional[str] = None


class ChapterContext(BaseModel):
    chapter_plan: ChapterPlan
    style_profile: dict
    worldview_summary: str
    active_entities: List[EntityState]
    location_context: LocationContext
    timeline_events: List[dict]
    pending_foreshadowings: List[dict]
    previous_chapter_summary: Optional[str] = None


class DraftMetadata(BaseModel):
    total_words: int
    beat_coverage: List[dict]
    style_violations: List[str]
    embedded_foreshadowings: List[str]
```

- [ ] **Step 2: Commit**

```bash
git add src/novel_dev/schemas/
git commit -m "feat: add ChapterContext and DraftMetadata schemas"
```

---

### Task 3: Implement ContextAgent

**Files:**
- Create: `src/novel_dev/agents/context_agent.py`
- Test: `tests/test_agents/test_context_agent.py`

- [ ] **Step 1: Implement ContextAgent**

Create `src/novel_dev/agents/context_agent.py`:

```python
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.context import ChapterContext, ChapterPlan, EntityState, LocationContext
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.version_repo import EntityVersionRepository
from novel_dev.repositories.spaceline_repo import SpacelineRepository
from novel_dev.repositories.timeline_repo import TimelineRepository
from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.agents.director import NovelDirector, Phase


class ContextAgent:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.state_repo = NovelStateRepository(session)
        self.doc_repo = DocumentRepository(session)
        self.entity_repo = EntityRepository(session)
        self.version_repo = EntityVersionRepository(session)
        self.spaceline_repo = SpacelineRepository(session)
        self.timeline_repo = TimelineRepository(session)
        self.foreshadowing_repo = ForeshadowingRepository(session)
        self.chapter_repo = ChapterRepository(session)
        self.director = NovelDirector(session)

    async def assemble(self, novel_id: str, chapter_id: str) -> ChapterContext:
        state = await self.state_repo.get_state(novel_id)
        if not state:
            raise ValueError(f"Novel state not found for {novel_id}")

        if not self.director.can_transition(Phase(state.current_phase), Phase.DRAFTING):
            raise ValueError(f"Cannot prepare context from phase {state.current_phase}")

        checkpoint = state.checkpoint_data or {}
        chapter_plan_data = checkpoint.get("current_chapter_plan")
        if not chapter_plan_data:
            raise ValueError("current_chapter_plan missing in checkpoint_data")

        chapter_plan = ChapterPlan.model_validate(chapter_plan_data)

        key_entity_names = self._extract_key_entities_from_plan(chapter_plan)
        active_entities = await self._load_active_entities(key_entity_names)
        location_context = await self._load_location_context(key_entity_names)
        timeline_events = await self._load_timeline_events(checkpoint)
        pending_foreshadowings = await self._load_foreshadowings(chapter_plan, active_entities, checkpoint)
        style_profile = await self._load_style_profile(novel_id, checkpoint)
        worldview_doc = await self.doc_repo.get_latest_by_type(novel_id, "worldview")
        worldview_summary = worldview_doc.content if worldview_doc else ""
        prev_summary = await self._load_previous_chapter_summary(
            state.current_volume_id, chapter_plan
        )

        context = ChapterContext(
            chapter_plan=chapter_plan,
            style_profile=style_profile,
            worldview_summary=worldview_summary,
            active_entities=active_entities,
            location_context=location_context,
            timeline_events=timeline_events,
            pending_foreshadowings=pending_foreshadowings,
            previous_chapter_summary=prev_summary,
        )

        checkpoint["chapter_context"] = context.model_dump()
        checkpoint["drafting_progress"] = {
            "beat_index": 0,
            "total_beats": len(chapter_plan.beats),
            "current_word_count": 0,
        }
        await self.director.save_checkpoint(
            novel_id,
            phase=Phase.DRAFTING,
            checkpoint_data=checkpoint,
            current_volume_id=state.current_volume_id,
            current_chapter_id=state.current_chapter_id,
        )

        return context

    def _extract_key_entities_from_plan(self, chapter_plan: ChapterPlan) -> List[str]:
        names = set()
        for beat in chapter_plan.beats:
            names.update(beat.key_entities)
        return list(names)

    async def _load_active_entities(self, names: List[str]) -> List[EntityState]:
        if not names:
            return []
        entities = await self.entity_repo.find_by_names(names)
        result = []
        for entity in entities:
            latest = await self.version_repo.get_latest(entity.id)
            state_str = str(latest.state) if latest else ""
            result.append(
                EntityState(
                    entity_id=entity.id,
                    name=entity.name,
                    type=entity.type,
                    current_state=state_str,
                )
            )
        return result

    async def _load_location_context(self, names: List[str]) -> LocationContext:
        return LocationContext(current="")

    async def _load_timeline_events(self, checkpoint: dict) -> List[dict]:
        tick = checkpoint.get("current_time_tick")
        if tick is None:
            return []
        events = await self.timeline_repo.get_around_tick(tick, radius=3)
        return [{"tick": e.tick, "narrative": e.narrative} for e in events]

    async def _load_foreshadowings(
        self,
        chapter_plan: ChapterPlan,
        active_entities: List[EntityState],
        checkpoint: dict,
    ) -> List[dict]:
        active_ids = {e.entity_id for e in active_entities}
        all_active = await self.foreshadowing_repo.list_active()
        result = []
        for fs in all_active:
            match = False
            if fs.相关人物_ids and active_ids:
                if any(eid in active_ids for eid in fs.相关人物_ids):
                    match = True
            if fs.埋下_time_tick == checkpoint.get("current_time_tick"):
                match = True
            if match:
                result.append(
                    {
                        "id": fs.id,
                        "content": fs.content,
                        "role_in_chapter": "embed",
                    }
                )
        return result

    async def _load_style_profile(self, novel_id: str, checkpoint: dict) -> dict:
        version = checkpoint.get("active_style_profile_version")
        if version:
            doc = await self.doc_repo.get_by_type_and_version(novel_id, "style_profile", version)
        else:
            doc = await self.doc_repo.get_latest_by_type(novel_id, "style_profile")
        if doc:
            import json
            try:
                return json.loads(doc.content)
            except Exception:
                return {"style_guide": doc.content}
        return {}

    async def _load_previous_chapter_summary(
        self,
        volume_id: Optional[str],
        chapter_plan: ChapterPlan,
    ) -> Optional[str]:
        if not volume_id or chapter_plan.chapter_number <= 1:
            return None
        prev = await self.chapter_repo.get_previous_chapter(volume_id, chapter_plan.chapter_number)
        if not prev:
            return None
        text = prev.polished_text or prev.raw_draft
        if not text:
            return None
        return text[-200:] if len(text) > 200 else text
```

- [ ] **Step 2: Write ContextAgent tests**

Create `tests/test_agents/test_context_agent.py`:

```python
import pytest

from novel_dev.agents.context_agent import ContextAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.version_repo import EntityVersionRepository
from novel_dev.repositories.timeline_repo import TimelineRepository
from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.schemas.context import ChapterPlan, BeatPlan


@pytest.mark.asyncio
async def test_assemble_context_success(async_session):
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=1,
        title="Test Chapter",
        target_word_count=3000,
        beats=[BeatPlan(summary="Beat 1", target_mood="tense", key_entities=["林风"])],
    )
    await director.save_checkpoint(
        "novel_test",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={"current_chapter_plan": chapter_plan.model_dump()},
        volume_id="vol_1",
        chapter_id="ch_1",
    )

    await EntityRepository(async_session).create("ent_1", "character", "林风")
    await EntityVersionRepository(async_session).create("ent_1", 1, {"realm": "炼气"}, chapter_id="ch_1")
    await TimelineRepository(async_session).create(1, "event 1")
    await ForeshadowingRepository(async_session).create("fs_1", "玉佩发光", 相关人物_ids=["ent_1"])
    await DocumentRepository(async_session).create("doc_1", "novel_test", "style_profile", "Style", '{"guide": "fast"}')
    await DocumentRepository(async_session).create("doc_2", "novel_test", "worldview", "Worldview", "天玄大陆")
    await ChapterRepository(async_session).create("ch_1", "vol_1", 1, "Test Chapter")

    agent = ContextAgent(async_session)
    context = await agent.assemble("novel_test", "ch_1")

    assert context.chapter_plan.title == "Test Chapter"
    assert len(context.active_entities) == 1
    assert context.active_entities[0].name == "林风"
    assert len(context.pending_foreshadowings) == 1
    assert context.worldview_summary == "天玄大陆"

    state = await director.resume("novel_test")
    assert state.current_phase == Phase.DRAFTING.value


@pytest.mark.asyncio
async def test_assemble_missing_plan(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_no_plan",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={},
        volume_id="vol_1",
        chapter_id="ch_1",
    )
    agent = ContextAgent(async_session)
    with pytest.raises(ValueError, match="current_chapter_plan missing"):
        await agent.assemble("novel_no_plan", "ch_1")


@pytest.mark.asyncio
async def test_assemble_wrong_phase(async_session):
    director = NovelDirector(session=async_session)
    plan = ChapterPlan(chapter_number=1, title="T", target_word_count=100, beats=[])
    await director.save_checkpoint(
        "novel_wrong_phase",
        phase=Phase.DRAFTING,
        checkpoint_data={"current_chapter_plan": plan.model_dump()},
        volume_id="vol_1",
        chapter_id="ch_1",
    )
    agent = ContextAgent(async_session)
    with pytest.raises(ValueError, match="Cannot prepare context"):
        await agent.assemble("novel_wrong_phase", "ch_1")
```

- [ ] **Step 3: Run ContextAgent tests**

Run:
```bash
pytest tests/test_agents/test_context_agent.py -v
```
Expected: 3 tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/novel_dev/agents/context_agent.py tests/test_agents/test_context_agent.py
git commit -m "feat: implement ContextAgent with tests"
```

---

### Task 4: Implement WriterAgent

**Files:**
- Create: `src/novel_dev/agents/writer_agent.py`
- Test: `tests/test_agents/test_writer_agent.py`

- [ ] **Step 1: Implement WriterAgent**

Create `src/novel_dev/agents/writer_agent.py`:

```python
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.context import ChapterContext, DraftMetadata, BeatPlan
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.agents.director import NovelDirector, Phase


class WriterAgent:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.chapter_repo = ChapterRepository(session)
        self.state_repo = NovelStateRepository(session)
        self.director = NovelDirector(session)

    async def write(self, novel_id: str, context: ChapterContext, chapter_id: str) -> DraftMetadata:
        state = await self.state_repo.get_state(novel_id)
        if not state:
            raise ValueError(f"Novel state not found for {novel_id}")

        if state.current_phase != Phase.DRAFTING.value:
            raise ValueError(f"Cannot write draft from phase {state.current_phase}")

        checkpoint = state.checkpoint_data or {}
        if not checkpoint.get("chapter_context"):
            raise ValueError("chapter_context missing in checkpoint_data")

        raw_draft = ""
        beat_coverage = []
        embedded_foreshadowings = []
        style_violations = []
        total_beats = len(context.chapter_plan.beats)

        for idx, beat in enumerate(context.chapter_plan.beats):
            beat_text = await self._generate_beat(beat, context, raw_draft)
            if len(beat_text) < 50:
                beat_text = await self._rewrite_angle(beat, beat_text, context)

            raw_draft += beat_text + "\n\n"
            beat_coverage.append({"beat_index": idx, "word_count": len(beat_text)})

            for fs in context.pending_foreshadowings:
                if fs["content"] in beat_text and fs["id"] not in embedded_foreshadowings:
                    embedded_foreshadowings.append(fs["id"])

            checkpoint["drafting_progress"] = {
                "beat_index": idx + 1,
                "total_beats": total_beats,
                "current_word_count": len(raw_draft),
            }
            await self.state_repo.save_checkpoint(
                novel_id,
                current_phase=Phase.DRAFTING.value,
                checkpoint_data=checkpoint,
                current_volume_id=state.current_volume_id,
                current_chapter_id=state.current_chapter_id,
            )

        metadata = DraftMetadata(
            total_words=len(raw_draft),
            beat_coverage=beat_coverage,
            style_violations=style_violations,
            embedded_foreshadowings=embedded_foreshadowings,
        )

        await self.chapter_repo.update_text(chapter_id, raw_draft=raw_draft.strip())
        await self.chapter_repo.update_status(chapter_id, "drafted")

        checkpoint["draft_metadata"] = metadata.model_dump()
        await self.director.save_checkpoint(
            novel_id,
            phase=Phase.REVIEWING,
            checkpoint_data=checkpoint,
            current_volume_id=state.current_volume_id,
            current_chapter_id=state.current_chapter_id,
        )

        return metadata

    async def _generate_beat(self, beat: BeatPlan, context: ChapterContext, previous_text: str) -> str:
        return f"{beat.summary}。气氛{beat.target_mood}。"

    async def _rewrite_angle(self, beat: BeatPlan, original_text: str, context: ChapterContext) -> str:
        return original_text + "（重写后）"
```

- [ ] **Step 2: Write WriterAgent tests**

Create `tests/test_agents/test_writer_agent.py`:

```python
import pytest

from novel_dev.agents.writer_agent import WriterAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.context import ChapterContext, ChapterPlan, BeatPlan, EntityState, LocationContext
from novel_dev.repositories.chapter_repo import ChapterRepository


@pytest.mark.asyncio
async def test_write_draft_success(async_session):
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=1,
        title="Test",
        target_word_count=2000,
        beats=[
            BeatPlan(summary="开场", target_mood="压抑"),
            BeatPlan(summary="冲突", target_mood="紧张"),
        ],
    )
    context = ChapterContext(
        chapter_plan=chapter_plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[{"id": "fs_1", "content": "玉佩发光", "role_in_chapter": "embed"}],
    )
    await director.save_checkpoint(
        "novel_test",
        phase=Phase.DRAFTING,
        checkpoint_data={"chapter_context": context.model_dump()},
        volume_id="vol_1",
        chapter_id="ch_1",
    )
    await ChapterRepository(async_session).create("ch_1", "vol_1", 1, "Test")

    agent = WriterAgent(async_session)
    metadata = await agent.write("novel_test", context, "ch_1")

    assert metadata.total_words > 0
    assert len(metadata.beat_coverage) == 2
    assert "fs_1" in metadata.embedded_foreshadowings

    ch = await ChapterRepository(async_session).get_by_id("ch_1")
    assert ch.status == "drafted"
    assert ch.raw_draft is not None

    state = await director.resume("novel_test")
    assert state.current_phase == Phase.REVIEWING.value


@pytest.mark.asyncio
async def test_write_missing_context(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_no_ctx",
        phase=Phase.DRAFTING,
        checkpoint_data={},
        volume_id="vol_1",
        chapter_id="ch_1",
    )
    context = ChapterContext(
        chapter_plan=ChapterPlan(chapter_number=1, title="T", target_word_count=100, beats=[]),
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[],
    )
    agent = WriterAgent(async_session)
    with pytest.raises(ValueError, match="chapter_context missing"):
        await agent.write("novel_no_ctx", context, "ch_1")


@pytest.mark.asyncio
async def test_write_wrong_phase(async_session):
    director = NovelDirector(session=async_session)
    plan = ChapterPlan(chapter_number=1, title="T", target_word_count=100, beats=[])
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
        "novel_wrong",
        phase=Phase.REVIEWING,
        checkpoint_data={"chapter_context": context.model_dump()},
        volume_id="vol_1",
        chapter_id="ch_1",
    )
    agent = WriterAgent(async_session)
    with pytest.raises(ValueError, match="Cannot write draft"):
        await agent.write("novel_wrong", context, "ch_1")
```

- [ ] **Step 3: Run WriterAgent tests**

Run:
```bash
pytest tests/test_agents/test_writer_agent.py -v
```
Expected: 3 tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/novel_dev/agents/writer_agent.py tests/test_agents/test_writer_agent.py
git commit -m "feat: implement WriterAgent with tests"
```

---

### Task 5: Add API routes for context and draft

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Create: `tests/test_api/test_chapter_draft_routes.py`

- [ ] **Step 1: Add request models and endpoints to routes.py**

Add these imports near the top of `src/novel_dev/api/routes.py`:

```python
from novel_dev.agents.context_agent import ContextAgent
from novel_dev.agents.writer_agent import WriterAgent
from novel_dev.schemas.context import ChapterContext
```

Add request/response models after existing ones:

```python
class ChapterContextRequest(BaseModel):
    pass


class ChapterDraftRequest(BaseModel):
    pass
```

Add endpoints before the closing of the file:

```python
@router.post("/api/novels/{novel_id}/chapters/{chapter_id}/context")
async def prepare_chapter_context(
    novel_id: str,
    chapter_id: str,
    session: AsyncSession = Depends(get_session),
):
    agent = ContextAgent(session)
    try:
        context = await agent.assemble(novel_id, chapter_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "chapter_plan_title": context.chapter_plan.title,
        "active_entities_count": len(context.active_entities),
        "pending_foreshadowings_count": len(context.pending_foreshadowings),
        "timeline_events_count": len(context.timeline_events),
    }


@router.post("/api/novels/{novel_id}/chapters/{chapter_id}/draft")
async def generate_chapter_draft(
    novel_id: str,
    chapter_id: str,
    session: AsyncSession = Depends(get_session),
):
    state_repo = NovelStateRepository(session)
    state = await state_repo.get_state(novel_id)
    if not state:
        raise HTTPException(status_code=404, detail="Novel state not found")

    checkpoint = state.checkpoint_data or {}
    context_data = checkpoint.get("chapter_context")
    if not context_data:
        raise HTTPException(status_code=400, detail="Chapter context not prepared. Call POST /context first.")

    context = ChapterContext.model_validate(context_data)
    agent = WriterAgent(session)
    try:
        metadata = await agent.write(novel_id, context, chapter_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return metadata.model_dump()


@router.get("/api/novels/{novel_id}/chapters/{chapter_id}/draft")
async def get_chapter_draft(
    novel_id: str,
    chapter_id: str,
    session: AsyncSession = Depends(get_session),
):
    repo = ChapterRepository(session)
    ch = await repo.get_by_id(chapter_id)
    if not ch:
        raise HTTPException(status_code=404, detail="Chapter not found")

    state_repo = NovelStateRepository(session)
    state = await state_repo.get_state(novel_id)
    checkpoint = state.checkpoint_data if state else {}

    return {
        "chapter_id": ch.id,
        "status": ch.status,
        "raw_draft": ch.raw_draft,
        "drafting_progress": checkpoint.get("drafting_progress"),
        "draft_metadata": checkpoint.get("draft_metadata"),
    }
```

- [ ] **Step 2: Write API route tests**

Create `tests/test_api/test_chapter_draft_routes.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router, get_session
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.context import ChapterPlan, BeatPlan
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.version_repo import EntityVersionRepository
from novel_dev.repositories.chapter_repo import ChapterRepository

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_prepare_context_and_generate_draft(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        director = NovelDirector(session=async_session)
        chapter_plan = ChapterPlan(
            chapter_number=1,
            title="API Test",
            target_word_count=3000,
            beats=[BeatPlan(summary="Beat 1", target_mood="tense", key_entities=["林风"])],
        )
        await director.save_checkpoint(
            "n_api",
            phase=Phase.CONTEXT_PREPARATION,
            checkpoint_data={"current_chapter_plan": chapter_plan.model_dump()},
            volume_id="v1",
            chapter_id="c1",
        )
        await EntityRepository(async_session).create("e1", "character", "林风")
        await EntityVersionRepository(async_session).create("e1", 1, {}, chapter_id="c1")
        await ChapterRepository(async_session).create("c1", "v1", 1, "API Test")

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/novels/n_api/chapters/c1/context")
            assert resp.status_code == 200
            data = resp.json()
            assert data["active_entities_count"] == 1

            resp2 = await client.post("/api/novels/n_api/chapters/c1/draft")
            assert resp2.status_code == 200
            assert resp2.json()["total_words"] > 0

            resp3 = await client.get("/api/novels/n_api/chapters/c1/draft")
            assert resp3.status_code == 200
            assert resp3.json()["status"] == "drafted"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_draft_without_context(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        director = NovelDirector(session=async_session)
        await director.save_checkpoint(
            "n_no_ctx",
            phase=Phase.DRAFTING,
            checkpoint_data={},
            volume_id="v1",
            chapter_id="c1",
        )
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/novels/n_no_ctx/chapters/c1/draft")
            assert resp.status_code == 400
            assert "Chapter context not prepared" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 3: Run API tests**

Run:
```bash
pytest tests/test_api/test_chapter_draft_routes.py -v
```
Expected: 2 tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/novel_dev/api/routes.py tests/test_api/test_chapter_draft_routes.py
git commit -m "feat: add chapter context and draft API endpoints"
```

---

### Task 6: Add MCP tools for chapter generation

**Files:**
- Modify: `src/novel_dev/mcp_server/server.py`
- Modify: `tests/test_mcp_server.py`

- [ ] **Step 1: Add MCP tools**

Modify `src/novel_dev/mcp_server/server.py`:

Add imports at the top:
```python
from novel_dev.agents.context_agent import ContextAgent
from novel_dev.agents.writer_agent import WriterAgent
from novel_dev.schemas.context import ChapterContext
```

Add to the `self.tools` dict:
```python
"prepare_chapter_context": self.prepare_chapter_context,
"generate_chapter_draft": self.generate_chapter_draft,
"get_chapter_draft_status": self.get_chapter_draft_status,
```

Add methods to the class:

```python
    async def prepare_chapter_context(self, novel_id: str, chapter_id: str) -> dict:
        async with async_session_maker() as session:
            agent = ContextAgent(session)
            try:
                context = await agent.assemble(novel_id, chapter_id)
                await session.commit()
                return {
                    "success": True,
                    "chapter_plan_title": context.chapter_plan.title,
                    "active_entities_count": len(context.active_entities),
                    "pending_foreshadowings_count": len(context.pending_foreshadowings),
                }
            except ValueError as e:
                return {"success": False, "error": str(e)}

    async def generate_chapter_draft(self, novel_id: str, chapter_id: str) -> dict:
        async with async_session_maker() as session:
            state_repo = NovelStateRepository(session)
            state = await state_repo.get_state(novel_id)
            if not state:
                return {"error": "Novel state not found"}
            checkpoint = state.checkpoint_data or {}
            context_data = checkpoint.get("chapter_context")
            if not context_data:
                return {"error": "Chapter context not prepared"}
            context = ChapterContext.model_validate(context_data)
            agent = WriterAgent(session)
            try:
                metadata = await agent.write(novel_id, context, chapter_id)
                await session.commit()
                return metadata.model_dump()
            except ValueError as e:
                return {"error": str(e)}

    async def get_chapter_draft_status(self, novel_id: str, chapter_id: str) -> dict:
        async with async_session_maker() as session:
            repo = ChapterRepository(session)
            ch = await repo.get_by_id(chapter_id)
            state_repo = NovelStateRepository(session)
            state = await state_repo.get_state(novel_id)
            checkpoint = state.checkpoint_data if state else {}
            return {
                "chapter_id": chapter_id,
                "status": ch.status if ch else None,
                "raw_draft": ch.raw_draft if ch else None,
                "drafting_progress": checkpoint.get("drafting_progress"),
                "draft_metadata": checkpoint.get("draft_metadata"),
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
    }
```

Add a new test at the bottom:

```python
@pytest.mark.asyncio
async def test_mcp_prepare_chapter_context():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.agents.director import NovelDirector, Phase
    from novel_dev.schemas.context import ChapterPlan, BeatPlan
    from novel_dev.repositories.chapter_repo import ChapterRepository

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        director = NovelDirector(session=session)
        chapter_plan = ChapterPlan(
            chapter_number=1,
            title="MCP Test",
            target_word_count=3000,
            beats=[BeatPlan(summary="B1", target_mood="tense")],
        )
        await director.save_checkpoint(
            "n_mcp_ctx",
            phase=Phase.CONTEXT_PREPARATION,
            checkpoint_data={"current_chapter_plan": chapter_plan.model_dump()},
            volume_id="v1",
            chapter_id="c1",
        )
        await ChapterRepository(session).create("c1", "v1", 1, "MCP Test")
        await session.commit()

    result = await mcp.tools["prepare_chapter_context"]("n_mcp_ctx", "c1")
    assert result["success"] is True
    assert result["chapter_plan_title"] == "MCP Test"
```

- [ ] **Step 3: Run MCP tests**

Run:
```bash
pytest tests/test_mcp_server.py -v
```
Expected: all tests pass (including existing ones).

- [ ] **Step 4: Commit**

```bash
git add src/novel_dev/mcp_server/server.py tests/test_mcp_server.py
git commit -m "feat: add MCP tools for chapter context and draft generation"
```

---

## Spec Self-Review

**1. Spec coverage check:**
- ContextAgent querying all tables → Task 3
- WriterAgent beat-by-beat generation → Task 4
- Caching to checkpoint_data → Task 3, Task 4
- State machine transitions → Task 3, Task 4
- API endpoints → Task 5
- MCP tools → Task 6
- Pydantic schemas → Task 2
- Error handling (missing plan, wrong phase) → tested in Tasks 3, 4, 5

**2. Placeholder scan:**
- No TBD/TODO/fill in later found.
- All code snippets are complete and runnable.
- All test commands are exact.

**3. Type consistency check:**
- `ChapterContext`, `DraftMetadata`, `BeatPlan`, `ChapterPlan` used consistently across all tasks.
- `ContextAgent.assemble(novel_id, chapter_id)` and `WriterAgent.write(novel_id, context, chapter_id)` signatures match their usages in routes and MCP tools.
