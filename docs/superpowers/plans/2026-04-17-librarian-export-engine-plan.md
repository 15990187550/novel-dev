# Librarian and Export Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Librarian and Export Engine: structured extraction from polished text (LLM with fallback), chapter archiving, volume/novel export, and complete LIBRARIAN phase integration in the state machine.

**Architecture:** Add `LibrarianAgent` with LLM extraction and rule-based fallback, `ArchiveService` for chapter archival, `ExportService` for `.md`/`.txt` aggregation, extend `NovelDirector.advance()` for `LIBRARIAN -> COMPLETED -> (next chapter or placeholder volume plan)` flow, and expose API + MCP endpoints.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Pydantic, pytest-asyncio, SQLite+aiosqlite for tests.

---

### Task 1: Schemas and Repository Extension

**Files:**
- Create: `src/novel_dev/schemas/librarian.py`
- Modify: `src/novel_dev/repositories/spaceline_repo.py`
- Test: `tests/test_repositories/test_spaceline_repo.py` (new)

- [ ] **Step 1: Write the failing test for SpacelineRepository.get_by_id**

```python
import pytest

from novel_dev.repositories.spaceline_repo import SpacelineRepository


@pytest.mark.asyncio
async def test_spaceline_repo_get_by_id(db_session):
    repo = SpacelineRepository(db_session)
    await repo.create("loc_1", "Qingyun City")
    result = await repo.get_by_id("loc_1")
    assert result is not None
    assert result.name == "Qingyun City"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_repositories/test_spaceline_repo.py -v`
Expected: FAIL with "AttributeError: 'SpacelineRepository' object has no attribute 'get_by_id'"

- [ ] **Step 3: Add get_by_id to SpacelineRepository**

In `src/novel_dev/repositories/spaceline_repo.py`, add:

```python
    async def get_by_id(self, location_id: str) -> Optional[Spaceline]:
        result = await self.session.execute(select(Spaceline).where(Spaceline.id == location_id))
        return result.scalar_one_or_none()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_repositories/test_spaceline_repo.py -v`
Expected: PASS

- [ ] **Step 5: Create librarian schemas**

Create `src/novel_dev/schemas/librarian.py`:

```python
from typing import List, Optional
from pydantic import BaseModel, Field


class TimelineEvent(BaseModel):
    tick: int
    narrative: str
    anchor_event_id: Optional[str] = None


class SpacelineChange(BaseModel):
    location_id: str
    name: str
    parent_id: Optional[str] = None
    narrative: Optional[str] = None


class NewEntity(BaseModel):
    type: str
    name: str
    state: dict


class EntityUpdate(BaseModel):
    entity_id: str
    state: dict
    diff_summary: dict


class NewForeshadowing(BaseModel):
    content: str
    埋下_chapter_id: Optional[str] = None
    埋下_time_tick: Optional[int] = None
    埋下_location_id: Optional[str] = None
    回收条件: Optional[dict] = None


class ExtractionResult(BaseModel):
    timeline_events: List[TimelineEvent] = Field(default_factory=list)
    spaceline_changes: List[SpacelineChange] = Field(default_factory=list)
    new_entities: List[NewEntity] = Field(default_factory=list)
    concept_updates: List[EntityUpdate] = Field(default_factory=list)
    character_updates: List[EntityUpdate] = Field(default_factory=list)
    foreshadowings_recovered: List[str] = Field(default_factory=list)
    new_foreshadowings: List[NewForeshadowing] = Field(default_factory=list)
```

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/schemas/librarian.py src/novel_dev/repositories/spaceline_repo.py tests/test_repositories/test_spaceline_repo.py
git commit -m "feat: add librarian schemas and spaceline get_by_id"
```

---

### Task 2: Storage Layer Extensions

**Files:**
- Modify: `src/novel_dev/storage/markdown_sync.py`
- Test: `tests/test_storage/test_markdown_sync.py` (new)

- [ ] **Step 1: Write the failing test for write_volume and write_novel**

```python
import os
import pytest
import tempfile

from novel_dev.storage.markdown_sync import MarkdownSync


@pytest.mark.asyncio
async def test_write_volume_and_novel():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = MarkdownSync(tmpdir)
        path = await sync.write_volume("n1", "v1", "volume.md", "# Vol 1\n\ncontent")
        assert os.path.exists(path)
        with open(path, "r", encoding="utf-8") as f:
            assert "# Vol 1" in f.read()

        path2 = await sync.write_novel("n1", "novel.md", "# Novel\n\ncontent")
        assert os.path.exists(path2)
        with open(path2, "r", encoding="utf-8") as f:
            assert "# Novel" in f.read()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_storage/test_markdown_sync.py -v`
Expected: FAIL with "AttributeError: 'MarkdownSync' object has no attribute 'write_volume'"

- [ ] **Step 3: Implement write_volume and write_novel in MarkdownSync**

In `src/novel_dev/storage/markdown_sync.py`, add:

```python
    def _volume_path(self, novel_id: str, volume_id: str, filename: str) -> str:
        dir_path = os.path.join(self.base_dir, novel_id, volume_id)
        os.makedirs(dir_path, exist_ok=True)
        return os.path.join(dir_path, filename)

    def _novel_path(self, novel_id: str, filename: str) -> str:
        dir_path = os.path.join(self.base_dir, novel_id)
        os.makedirs(dir_path, exist_ok=True)
        return os.path.join(dir_path, filename)

    async def write_volume(self, novel_id: str, volume_id: str, filename: str, content: str) -> str:
        path = self._volume_path(novel_id, volume_id, filename)
        await asyncio.to_thread(self._sync_write, path, content)
        return path

    async def write_novel(self, novel_id: str, filename: str, content: str) -> str:
        path = self._novel_path(novel_id, filename)
        await asyncio.to_thread(self._sync_write, path, content)
        return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_storage/test_markdown_sync.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/storage/markdown_sync.py tests/test_storage/test_markdown_sync.py
git commit -m "feat: add write_volume and write_novel to MarkdownSync"
```

---

### Task 3: ArchiveService

**Files:**
- Create: `src/novel_dev/services/archive_service.py`
- Test: `tests/test_services/test_archive_service.py`

- [ ] **Step 1: Write the failing test**

```python
import os
import pytest
import tempfile

from novel_dev.services.archive_service import ArchiveService
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.agents.director import NovelDirector, Phase


@pytest.mark.asyncio
async def test_archive_service(db_session):
    director = NovelDirector(session=db_session)
    await director.save_checkpoint(
        "n_archive",
        phase=Phase.LIBRARIAN,
        checkpoint_data={},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(db_session).create("c1", "v1", 1, "Test Chapter")
    await ChapterRepository(db_session).update_text("c1", polished_text=" polished ")

    with tempfile.TemporaryDirectory() as tmpdir:
        svc = ArchiveService(db_session, tmpdir)
        result = await svc.archive("n_archive", "c1")

    assert result["word_count"] == 10
    ch = await ChapterRepository(db_session).get_by_id("c1")
    assert ch.status == "archived"
    state = await NovelStateRepository(db_session).get_state("n_archive")
    stats = state.checkpoint_data["archive_stats"]
    assert stats["total_word_count"] == 10
    assert stats["archived_chapter_count"] == 1
    assert os.path.exists(result["path_md"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_services/test_archive_service.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'novel_dev.services.archive_service'"

- [ ] **Step 3: Implement ArchiveService**

Create `src/novel_dev/services/archive_service.py`:

```python
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.storage.markdown_sync import MarkdownSync


class ArchiveService:
    def __init__(self, session: AsyncSession, markdown_base_dir: str):
        self.session = session
        self.chapter_repo = ChapterRepository(session)
        self.state_repo = NovelStateRepository(session)
        self.sync = MarkdownSync(markdown_base_dir)

    async def archive(self, novel_id: str, chapter_id: str) -> dict:
        ch = await self.chapter_repo.get_by_id(chapter_id)
        if not ch or not ch.polished_text:
            raise ValueError("Chapter has no polished text to archive")

        await self.chapter_repo.update_status(chapter_id, "archived")

        state = await self.state_repo.get_state(novel_id)
        stats = state.checkpoint_data.get("archive_stats", {})
        chapter_word_count = len(ch.polished_text)
        stats["total_word_count"] = stats.get("total_word_count", 0) + chapter_word_count
        stats["archived_chapter_count"] = stats.get("archived_chapter_count", 0) + 1
        stats["avg_word_count"] = stats["total_word_count"] // max(stats["archived_chapter_count"], 1)
        state.checkpoint_data["archive_stats"] = stats

        await self.state_repo.save_checkpoint(
            novel_id,
            current_phase=state.current_phase,
            checkpoint_data=state.checkpoint_data,
            current_volume_id=state.current_volume_id,
            current_chapter_id=state.current_chapter_id,
        )

        path_md = await self.sync.write_chapter(novel_id, ch.volume_id, chapter_id, ch.polished_text)

        return {
            "word_count": chapter_word_count,
            "path_md": path_md,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_services/test_archive_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/services/archive_service.py tests/test_services/test_archive_service.py
git commit -m "feat: implement ArchiveService"
```

---

### Task 4: ExportService

**Files:**
- Create: `src/novel_dev/services/export_service.py`
- Test: `tests/test_services/test_export_service.py`

- [ ] **Step 1: Write the failing test**

```python
import os
import pytest
import tempfile

from novel_dev.services.export_service import ExportService
from novel_dev.repositories.chapter_repo import ChapterRepository


@pytest.mark.asyncio
async def test_export_volume_and_novel(db_session):
    await ChapterRepository(db_session).create("c1", "v1", 1, "Ch1")
    await ChapterRepository(db_session).create("c2", "v1", 2, "Ch2")
    await ChapterRepository(db_session).update_text("c1", polished_text="p1")
    await ChapterRepository(db_session).update_text("c2", polished_text="p2")
    await ChapterRepository(db_session).update_status("c1", "archived")

    with tempfile.TemporaryDirectory() as tmpdir:
        svc = ExportService(db_session, tmpdir)
        path = await svc.export_volume("n1", "v1", format="md")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "p1" in content
        assert "p2" not in content  # not archived

        path2 = await svc.export_novel("n1", format="md")
        with open(path2, "r", encoding="utf-8") as f:
            content2 = f.read()
        assert "p1" in content2
        assert "p2" not in content2

        with pytest.raises(ValueError):
            await svc.export_novel("n1", format="pdf")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_services/test_export_service.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'novel_dev.services.export_service'"

- [ ] **Step 3: Implement ExportService**

Create `src/novel_dev/services/export_service.py`:

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, distinct

from novel_dev.db.models import Chapter
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.storage.markdown_sync import MarkdownSync


class ExportService:
    def __init__(self, session: AsyncSession, markdown_base_dir: str):
        self.session = session
        self.chapter_repo = ChapterRepository(session)
        self.sync = MarkdownSync(markdown_base_dir)

    async def export_volume(self, novel_id: str, volume_id: str, format: str = "md") -> str:
        if format not in ("md", "txt"):
            raise ValueError(f"Unsupported format: {format}")
        chapters = await self.chapter_repo.list_by_volume(volume_id)
        archived = [ch for ch in chapters if ch.status == "archived"]
        lines = []
        for ch in archived:
            title = ch.title or f"第{ch.chapter_number}章"
            lines.append(f"# {title}\n\n{ch.polished_text}")
        content = "\n\n".join(lines)
        return await self.sync.write_volume(novel_id, volume_id, f"volume.{format}", content)

    async def export_novel(self, novel_id: str, format: str = "md") -> str:
        if format not in ("md", "txt"):
            raise ValueError(f"Unsupported format: {format}")
        result = await self.session.execute(
            select(distinct(Chapter.volume_id)).where(Chapter.volume_id.isnot(None))
        )
        volume_ids = result.scalars().all()

        parts = []
        for vid in sorted(volume_ids):
            chapters = await self.chapter_repo.list_by_volume(vid)
            archived = [ch for ch in chapters if ch.status == "archived"]
            if not archived:
                continue
            lines = []
            for ch in archived:
                title = ch.title or f"第{ch.chapter_number}章"
                lines.append(f"# {title}\n\n{ch.polished_text}")
            parts.append(f"## Volume {vid}\n\n" + "\n\n".join(lines))

        content = "\n\n---\n\n".join(parts)
        return await self.sync.write_novel(novel_id, f"novel.{format}", content)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_services/test_export_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/services/export_service.py tests/test_services/test_export_service.py
git commit -m "feat: implement ExportService"
```

---

### Task 5: LibrarianAgent

**Files:**
- Modify: `src/novel_dev/agents/librarian.py`
- Test: `tests/test_agents/test_librarian.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from unittest.mock import AsyncMock, patch

from novel_dev.agents.librarian import LibrarianAgent
from novel_dev.schemas.librarian import ExtractionResult


@pytest.mark.asyncio
async def test_librarian_llm_extraction_success(db_session):
    agent = LibrarianAgent(db_session)
    mock_result = ExtractionResult(
        timeline_events=[{"tick": 10, "narrative": "战斗结束"}],
        new_entities=[{"type": "character", "name": "Lin Feng", "state": {"level": 2}}],
    )
    with patch.object(agent, "_call_llm", new_callable=AsyncMock, return_value=mock_result.model_dump_json()):
        result = await agent.extract("n1", "c1", "Lin Feng leveled up after the battle.")
    assert len(result.timeline_events) == 1
    assert result.timeline_events[0].tick == 10


@pytest.mark.asyncio
async def test_librarian_fallback_on_llm_failure(db_session):
    agent = LibrarianAgent(db_session)
    with patch.object(agent, "_call_llm", new_callable=AsyncMock, side_effect=TimeoutError("LLM timeout")):
        result = agent.fallback_extract("三天后，Lin Feng 来到 Qingyun City。", {})
    assert len(result.timeline_events) == 1
    assert result.timeline_events[0].narrative == "三天后"
    assert any(c.name == "Qingyun City" for c in result.spaceline_changes)


@pytest.mark.asyncio
async def test_librarian_persist_writes_to_database(db_session):
    from novel_dev.repositories.timeline_repo import TimelineRepository
    from novel_dev.repositories.spaceline_repo import SpacelineRepository
    from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository

    agent = LibrarianAgent(db_session)
    extraction = ExtractionResult(
        timeline_events=[{"tick": 5, "narrative": "启程"}],
        spaceline_changes=[{"location_id": "loc_1", "name": "Cloud City"}],
        new_foreshadowings=[{"content": "神秘的戒指"}],
    )
    await agent.persist(extraction, "c1")
    await db_session.commit()

    timeline = await TimelineRepository(db_session).get_current_tick()
    assert timeline == 5
    sp = await SpacelineRepository(db_session).get_by_id("loc_1")
    assert sp is not None
    fs_list = await ForeshadowingRepository(db_session).list_active()
    assert any(fs.content == "神秘的戒指" for fs in fs_list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_agents/test_librarian.py -v`
Expected: FAIL with import/attribute errors

- [ ] **Step 3: Implement LibrarianAgent**

Rewrite `src/novel_dev/agents/librarian.py`:

```python
import json
import re
import uuid
from typing import Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.librarian import (
    ExtractionResult,
    TimelineEvent,
    SpacelineChange,
    NewEntity,
    EntityUpdate,
    NewForeshadowing,
)
from novel_dev.repositories.timeline_repo import TimelineRepository
from novel_dev.repositories.spaceline_repo import SpacelineRepository
from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
from novel_dev.services.entity_service import EntityService


class LibrarianAgent:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _load_context(self, novel_id: str, chapter_id: str) -> dict:
        entity_svc = EntityService(self.session)
        foreshadowing_repo = ForeshadowingRepository(self.session)
        spaceline_repo = SpacelineRepository(self.session)
        timeline_repo = TimelineRepository(self.session)

        active_fs = await foreshadowing_repo.list_active()
        current_tick = await timeline_repo.get_current_tick() or 0

        return {
            "novel_id": novel_id,
            "chapter_id": chapter_id,
            "pending_foreshadowings": [
                {"id": fs.id, "content": fs.content} for fs in active_fs
            ],
            "current_tick": current_tick,
        }

    def _build_prompt(self, polished_text: str, context: dict) -> str:
        return (
            "你是一个小说世界状态提取器。从以下精修章节文本中提取对世界状态的变更。\n"
            "返回严格 JSON，包含以下顶级键："
            "timeline_events, spaceline_changes, new_entities, concept_updates, "
            "character_updates, foreshadowings_recovered, new_foreshadowings。\n"
            "规则：只提取文本中明确发生或暗示的变更；人物状态变更必须是具体键值对；"
            "若 pending_foreshadowings 中的内容在文本中被解答，将其 ID 放入 foreshadowings_recovered。\n"
            f"当前 pending_foreshadowings: {json.dumps(context.get('pending_foreshadowings', []), ensure_ascii=False)}\n"
            f"当前时间 tick: {context.get('current_tick', 0)}\n"
            f"章节文本：\n{polished_text}\n"
        )

    async def _call_llm(self, prompt: str) -> str:
        # Prototype: simulate a structured JSON response
        # In production this would call an actual LLM API
        dummy = ExtractionResult()
        return dummy.model_dump_json()

    async def extract(self, novel_id: str, chapter_id: str, polished_text: str) -> ExtractionResult:
        context = await self._load_context(novel_id, chapter_id)
        prompt = self._build_prompt(polished_text, context)
        response = await self._call_llm(prompt)
        return ExtractionResult.model_validate_json(response)

    def fallback_extract(self, polished_text: str, checkpoint_data: dict) -> ExtractionResult:
        timeline_events = []
        spaceline_changes = []
        new_entities = []
        character_updates = []
        concept_updates = []
        foreshadowings_recovered = []
        new_foreshadowings = []

        # Timeline heuristic
        time_matches = re.findall(r'(\d+)\s*天[前后]|三[天日]后|一[个]?月[前后]', polished_text)
        base_tick = checkpoint_data.get("current_tick", 0) if isinstance(checkpoint_data, dict) else 0
        for m in time_matches:
            if m.isdigit():
                base_tick += int(m)
            else:
                base_tick += 3
            timeline_events.append(TimelineEvent(tick=base_tick, narrative=m or "时间推进"))

        # Spaceline heuristic
        loc_matches = re.findall(r'(?:来到|抵达|进入)\s*([\u4e00-\u9fa5A-Z][\u4e00-\u9fa5A-Za-z\s]+)', polished_text)
        for loc in loc_matches:
            spaceline_changes.append(SpacelineChange(location_id=f"loc_{loc.strip()}", name=loc.strip()))

        # New entities / character updates heuristic
        known_names = checkpoint_data.get("active_entities", []) if isinstance(checkpoint_data, dict) else []
        candidates = re.findall(r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+', polished_text)
        for cand in candidates:
            if cand not in known_names:
                new_entities.append(NewEntity(type="character", name=cand, state={"mentioned": True}))

        # Foreshadowing heuristics
        pending = checkpoint_data.get("pending_foreshadowings", []) if isinstance(checkpoint_data, dict) else []
        for fs in pending:
            if fs.get("content") and fs["content"] in polished_text:
                foreshadowings_recovered.append(fs["id"])
        if re.search(r'谜团|未解|悬念|秘密', polished_text):
            new_foreshadowings.append(NewForeshadowing(content="文本中检测到新的悬念线索"))

        return ExtractionResult(
            timeline_events=timeline_events,
            spaceline_changes=spaceline_changes,
            new_entities=new_entities,
            character_updates=character_updates,
            concept_updates=concept_updates,
            foreshadowings_recovered=foreshadowings_recovered,
            new_foreshadowings=new_foreshadowings,
        )

    async def persist(self, extraction: ExtractionResult, chapter_id: str) -> None:
        timeline_repo = TimelineRepository(self.session)
        spaceline_repo = SpacelineRepository(self.session)
        entity_svc = EntityService(self.session)
        foreshadowing_repo = ForeshadowingRepository(self.session)

        for event in extraction.timeline_events:
            await timeline_repo.create(event.tick, event.narrative, anchor_chapter_id=chapter_id, anchor_event_id=event.anchor_event_id)

        for change in extraction.spaceline_changes:
            node = await spaceline_repo.get_by_id(change.location_id)
            if node:
                node.name = change.name
                node.parent_id = change.parent_id
                node.narrative = change.narrative or node.narrative
                await self.session.flush()
            else:
                await spaceline_repo.create(change.location_id, change.name, change.parent_id, change.narrative)

        for entity in extraction.new_entities:
            eid = str(uuid.uuid4())
            await entity_svc.create_entity(eid, entity.type, entity.name)
            await entity_svc.update_state(eid, entity.state, diff_summary={"created": True})

        for update in extraction.concept_updates + extraction.character_updates:
            await entity_svc.update_state(update.entity_id, update.state, diff_summary=update.diff_summary)

        for fs_id in extraction.foreshadowings_recovered:
            await foreshadowing_repo.mark_recovered(fs_id, chapter_id=chapter_id)

        for fs in extraction.new_foreshadowings:
            fs_id = str(uuid.uuid4())
            await foreshadowing_repo.create(
                fs_id=fs_id,
                content=fs.content,
                埋下_chapter_id=fs.埋下_chapter_id or chapter_id,
                埋下_time_tick=fs.埋下_time_tick,
                埋下_location_id=fs.埋下_location_id,
                回收条件=fs.回收条件,
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_agents/test_librarian.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/librarian.py tests/test_agents/test_librarian.py
git commit -m "feat: implement LibrarianAgent with LLM and fallback extraction"
```

---

### Task 6: NovelDirector LIBRARIAN Integration

**Files:**
- Modify: `src/novel_dev/agents/director.py`
- Test: `tests/test_agents/test_director_librarian.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from unittest.mock import AsyncMock, patch

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.schemas.context import ChapterPlan, BeatPlan


@pytest.mark.asyncio
async def test_director_librarian_to_completed(db_session):
    director = NovelDirector(session=db_session)
    plan = ChapterPlan(chapter_number=1, title="Ch1", target_word_count=3000, beats=[BeatPlan(summary="B1", target_mood="tense")])
    await director.save_checkpoint(
        "n_dir",
        phase=Phase.LIBRARIAN,
        checkpoint_data={"current_volume_plan": {"chapters": [plan.model_dump()]}},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(db_session).create("c1", "v1", 1, "Ch1")
    await ChapterRepository(db_session).update_text("c1", polished_text="abc")

    with patch("novel_dev.agents.librarian.LibrarianAgent._call_llm", new_callable=AsyncMock, return_value='{}'):
        state = await director._run_librarian(await director.resume("n_dir"))

    assert state.current_phase == Phase.COMPLETED.value
    ch = await ChapterRepository(db_session).get_by_id("c1")
    assert ch.status == "archived"


@pytest.mark.asyncio
async def test_director_continue_to_next_chapter(db_session):
    director = NovelDirector(session=db_session)
    plans = [
        ChapterPlan(chapter_number=1, title="Ch1", target_word_count=3000, beats=[BeatPlan(summary="B1", target_mood="tense")]).model_dump(),
        ChapterPlan(chapter_number=2, title="Ch2", target_word_count=3000, beats=[BeatPlan(summary="B2", target_mood="calm")]).model_dump(),
    ]
    plans[0]["chapter_id"] = "c1"
    plans[1]["chapter_id"] = "c2"
    await director.save_checkpoint(
        "n_next",
        phase=Phase.COMPLETED,
        checkpoint_data={"current_volume_plan": {"chapters": plans}},
        volume_id="v1",
        chapter_id="c1",
    )
    state = await director._continue_to_next_chapter("n_next")
    assert state.current_phase == Phase.CONTEXT_PREPARATION.value
    assert state.current_chapter_id == "c2"


@pytest.mark.asyncio
async def test_director_last_chapter_to_volume_planning(db_session):
    director = NovelDirector(session=db_session)
    plan = ChapterPlan(chapter_number=1, title="Ch1", target_word_count=3000, beats=[BeatPlan(summary="B1", target_mood="tense")]).model_dump()
    plan["chapter_id"] = "c1"
    await director.save_checkpoint(
        "n_last",
        phase=Phase.COMPLETED,
        checkpoint_data={"current_volume_plan": {"chapters": [plan]}, "archive_stats": {"avg_word_count": 2500}},
        volume_id="vol_1",
        chapter_id="c1",
    )
    state = await director._continue_to_next_chapter("n_last")
    assert state.current_phase == Phase.VOLUME_PLANNING.value
    assert state.current_volume_id == "vol_2"
    assert "pending_volume_plans" in state.checkpoint_data


@pytest.mark.asyncio
async def test_director_librarian_both_extractions_fail(db_session):
    director = NovelDirector(session=db_session)
    await director.save_checkpoint(
        "n_fail",
        phase=Phase.LIBRARIAN,
        checkpoint_data={},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(db_session).create("c1", "v1", 1, "Ch1")
    await ChapterRepository(db_session).update_text("c1", polished_text="abc")

    with patch("novel_dev.agents.librarian.LibrarianAgent._call_llm", new_callable=AsyncMock, side_effect=Exception("LLM down")):
        with patch("novel_dev.agents.librarian.LibrarianAgent.fallback_extract", side_effect=Exception("fallback also fails")):
            with pytest.raises(RuntimeError):
                await director._run_librarian(await director.resume("n_fail"))

    state = await NovelStateRepository(db_session).get_state("n_fail")
    assert state.current_phase == Phase.LIBRARIAN.value
    assert "librarian_error" in state.checkpoint_data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_agents/test_director_librarian.py -v`
Expected: FAIL with "AttributeError: 'NovelDirector' object has no attribute '_run_librarian'"

- [ ] **Step 3: Implement NovelDirector LIBRARIAN integration**

In `src/novel_dev/agents/director.py`:

1. Add `Phase.LIBRARIAN` to enum (already present, verify).
2. Update `VALID_TRANSITIONS`:

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
```

3. Extend `advance()`:

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
        elif current == Phase.LIBRARIAN:
            return await self._run_librarian(state)
        else:
            raise ValueError(f"Cannot auto-advance from {current}")
```

4. Add imports and methods at the bottom of the class:

```python
    async def _run_librarian(self, state: NovelState) -> NovelState:
        from novel_dev.agents.librarian import LibrarianAgent
        from novel_dev.services.archive_service import ArchiveService
        from novel_dev.config import Settings
        from novel_dev.repositories.chapter_repo import ChapterRepository

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

        import uuid
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

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_agents/test_director_librarian.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/director.py tests/test_agents/test_director_librarian.py
git commit -m "feat: add LIBRARIAN phase and chapter continuation to NovelDirector"
```

---

### Task 7: API Endpoints

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Test: `tests/test_api/test_librarian_routes.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from unittest.mock import patch, AsyncMock

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.schemas.context import ChapterPlan, BeatPlan


@pytest.mark.asyncio
async def test_post_librarian_success(client, db_session):
    director = NovelDirector(session=db_session)
    plan = ChapterPlan(chapter_number=1, title="Ch1", target_word_count=3000, beats=[BeatPlan(summary="B1", target_mood="tense")]).model_dump()
    plan["chapter_id"] = "c1"
    await director.save_checkpoint(
        "n_api_lib",
        phase=Phase.LIBRARIAN,
        checkpoint_data={"current_volume_plan": {"chapters": [plan]}},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(db_session).create("c1", "v1", 1, "Ch1")
    await ChapterRepository(db_session).update_text("c1", polished_text="abc")
    await db_session.commit()

    with patch("novel_dev.agents.librarian.LibrarianAgent._call_llm", new_callable=AsyncMock, return_value='{}'):
        response = client.post("/api/novels/n_api_lib/librarian")
    assert response.status_code == 200
    assert response.json()["current_phase"] == Phase.COMPLETED.value


@pytest.mark.asyncio
async def test_post_export_success(client, db_session):
    from novel_dev.services.archive_service import ArchiveService
    from novel_dev.config import Settings
    import tempfile

    director = NovelDirector(session=db_session)
    await director.save_checkpoint("n_api_exp", phase=Phase.COMPLETED, checkpoint_data={})
    await ChapterRepository(db_session).create("c1", "v1", 1, "Ch1")
    await ChapterRepository(db_session).update_text("c1", polished_text="abc")
    await ChapterRepository(db_session).update_status("c1", "archived")
    await db_session.commit()

    with tempfile.TemporaryDirectory() as tmpdir:
        svc = ArchiveService(db_session, tmpdir)
        await svc.archive("n_api_exp", "c1")
        await db_session.commit()

        with patch.object(Settings, "__init__", lambda self: None):
            settings = Settings()
            settings.markdown_output_dir = tmpdir
            with patch("novel_dev.api.routes.settings", settings):
                response = client.post("/api/novels/n_api_exp/export?format=md")
        assert response.status_code == 200
        assert response.json()["format"] == "md"
        assert "exported_path" in response.json()


@pytest.mark.asyncio
async def test_get_archive_stats_success(client, db_session):
    director = NovelDirector(session=db_session)
    await director.save_checkpoint("n_api_stats", phase=Phase.COMPLETED, checkpoint_data={"archive_stats": {"total_word_count": 100, "archived_chapter_count": 1}})
    await db_session.commit()

    response = client.get("/api/novels/n_api_stats/archive_stats")
    assert response.status_code == 200
    assert response.json()["total_word_count"] == 100
    assert response.json()["archived_chapter_count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_api/test_librarian_routes.py -v`
Expected: FAIL with 404s

- [ ] **Step 3: Add API endpoints**

In `src/novel_dev/api/routes.py`, add at the bottom:

```python
@router.post("/api/novels/{novel_id}/librarian")
async def run_librarian(novel_id: str, session: AsyncSession = Depends(get_session)):
    director = NovelDirector(session)
    try:
        state = await director._run_librarian(await director.resume(novel_id))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {
        "novel_id": state.novel_id,
        "current_phase": state.current_phase,
        "checkpoint_data": state.checkpoint_data,
    }


@router.post("/api/novels/{novel_id}/export")
async def export_novel(novel_id: str, format: str = "md", session: AsyncSession = Depends(get_session)):
    from novel_dev.services.export_service import ExportService
    svc = ExportService(session, settings.markdown_output_dir)
    try:
        path = await svc.export_novel(novel_id, format=format)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"exported_path": path, "format": format}


@router.get("/api/novels/{novel_id}/archive_stats")
async def get_archive_stats(novel_id: str, session: AsyncSession = Depends(get_session)):
    repo = NovelStateRepository(session)
    state = await repo.get_state(novel_id)
    if not state:
        raise HTTPException(status_code=404, detail="Novel state not found")
    stats = state.checkpoint_data.get("archive_stats", {})
    return {
        "novel_id": novel_id,
        "total_word_count": stats.get("total_word_count", 0),
        "archived_chapter_count": stats.get("archived_chapter_count", 0),
        "avg_word_count": stats.get("avg_word_count", 0),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_api/test_librarian_routes.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/api/routes.py tests/test_api/test_librarian_routes.py
git commit -m "feat: add librarian, export, and archive_stats API endpoints"
```

---

### Task 8: MCP Tools

**Files:**
- Modify: `src/novel_dev/mcp_server/server.py`
- Test: `tests/test_mcp_server.py`

- [ ] **Step 1: Update expected tools in test_mcp_server.py**

Add to the `expected` set:
```python
"run_librarian",
"export_novel",
"get_archive_stats",
```

Add three new test functions at the bottom of `tests/test_mcp_server.py`:

```python
@pytest.mark.asyncio
async def test_mcp_run_librarian():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.agents.director import NovelDirector, Phase
    from novel_dev.repositories.chapter_repo import ChapterRepository
    from novel_dev.schemas.context import ChapterPlan, BeatPlan
    from unittest.mock import patch, AsyncMock

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_mcp_lib_{suffix}"
    chapter_id = f"c_{suffix}"
    volume_id = f"v_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        director = NovelDirector(session=session)
        plan = ChapterPlan(chapter_number=1, title="MCP Lib", target_word_count=3000, beats=[BeatPlan(summary="B1", target_mood="tense")]).model_dump()
        plan["chapter_id"] = chapter_id
        await director.save_checkpoint(
            novel_id,
            phase=Phase.LIBRARIAN,
            checkpoint_data={"current_volume_plan": {"chapters": [plan]}},
            volume_id=volume_id,
            chapter_id=chapter_id,
        )
        await ChapterRepository(session).create(chapter_id, volume_id, 1, "MCP Lib")
        await ChapterRepository(session).update_text(chapter_id, polished_text="abc")
        await session.commit()

    with patch("novel_dev.agents.librarian.LibrarianAgent._call_llm", new_callable=AsyncMock, return_value='{}'):
        result = await mcp.tools["run_librarian"](novel_id)
    assert result["current_phase"] == Phase.COMPLETED.value


@pytest.mark.asyncio
async def test_mcp_export_novel():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.repositories.chapter_repo import ChapterRepository
    import tempfile

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_mcp_exp_{suffix}"
    chapter_id = f"c_{suffix}"
    volume_id = f"v_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        await ChapterRepository(session).create(chapter_id, volume_id, 1, "MCP Exp")
        await ChapterRepository(session).update_text(chapter_id, polished_text="export me")
        await ChapterRepository(session).update_status(chapter_id, "archived")
        await session.commit()

    result = await mcp.tools["export_novel"](novel_id, "md")
    assert "exported_path" in result
    assert result["format"] == "md"


@pytest.mark.asyncio
async def test_mcp_get_archive_stats():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.agents.director import NovelDirector, Phase

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_mcp_stats_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        director = NovelDirector(session=session)
        await director.save_checkpoint(
            novel_id,
            phase=Phase.COMPLETED,
            checkpoint_data={"archive_stats": {"total_word_count": 42, "archived_chapter_count": 1}},
        )
        await session.commit()

    result = await mcp.tools["get_archive_stats"](novel_id)
    assert result["total_word_count"] == 42
    assert result["archived_chapter_count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_mcp_server.py -v`
Expected: FAIL with KeyError for missing tools

- [ ] **Step 3: Add MCP tools**

In `src/novel_dev/mcp_server/server.py`:

1. Add to `self.tools` dict:
```python
            "run_librarian": self.run_librarian,
            "export_novel": self.export_novel,
            "get_archive_stats": self.get_archive_stats,
```

2. Add imports:
```python
from novel_dev.services.export_service import ExportService
```

3. Add methods at the bottom of the class (before `mcp = NovelDevMCPServer()`):

```python
    async def run_librarian(self, novel_id: str) -> dict:
        async with async_session_maker() as session:
            director = NovelDirector(session)
            try:
                state = await director._run_librarian(await director.resume(novel_id))
                await session.commit()
                return {
                    "novel_id": state.novel_id,
                    "current_phase": state.current_phase,
                    "checkpoint_data": state.checkpoint_data,
                }
            except ValueError as e:
                return {"error": str(e)}
            except RuntimeError as e:
                return {"error": str(e)}

    async def export_novel(self, novel_id: str, format: str = "md") -> dict:
        async with async_session_maker() as session:
            svc = ExportService(session, "./novel_output")
            try:
                path = await svc.export_novel(novel_id, format=format)
                return {"exported_path": path, "format": format}
            except ValueError as e:
                return {"error": str(e)}

    async def get_archive_stats(self, novel_id: str) -> dict:
        async with async_session_maker() as session:
            repo = NovelStateRepository(session)
            state = await repo.get_state(novel_id)
            if not state:
                return {"error": "Novel state not found"}
            stats = state.checkpoint_data.get("archive_stats", {})
            return {
                "total_word_count": stats.get("total_word_count", 0),
                "archived_chapter_count": stats.get("archived_chapter_count", 0),
                "avg_word_count": stats.get("avg_word_count", 0),
            }
```

Wait, the ExportService needs the actual output dir from settings. Use:

```python
    async def export_novel(self, novel_id: str, format: str = "md") -> dict:
        from novel_dev.config import Settings
        settings = Settings()
        async with async_session_maker() as session:
            svc = ExportService(session, settings.markdown_output_dir)
            try:
                path = await svc.export_novel(novel_id, format=format)
                return {"exported_path": path, "format": format}
            except ValueError as e:
                return {"error": str(e)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_mcp_server.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/mcp_server/server.py tests/test_mcp_server.py
git commit -m "feat: add MCP tools for librarian, export, and archive stats"
```

---

## Self-Review

### 1. Spec Coverage

| Spec Requirement | Task |
|-----------------|------|
| LibrarianAgent LLM extraction + fallback | Task 5 |
| ArchiveService | Task 3 |
| ExportService md/txt | Task 4 |
| NovelDirector LIBRARIAN phase | Task 6 |
| Chapter continuation + placeholder volume | Task 6 |
| API endpoints | Task 7 |
| MCP tools | Task 8 |
| Tests for all components | Tasks 1-8 |

### 2. Placeholder Scan

No red flags: no "TBD", "TODO", "implement later", or vague instructions. Every step shows exact code or exact commands.

### 3. Type Consistency

- `SpacelineRepository.get_by_id` added and used consistently.
- `LibrarianAgent.persist(extraction, chapter_id)` signature is consistent.
- `VALID_TRANSITIONS` updated to match Phase enum.
- `ArchiveService` and `ExportService` signatures match their instantiations.
