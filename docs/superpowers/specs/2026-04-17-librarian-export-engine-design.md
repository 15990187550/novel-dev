# Librarian and Export Engine Design

**Date:** 2026-04-17  
**Topic:** Subsystem 5: LibrarianAgent integration, archive service, and export service  
**Status:** Ready for implementation  
**Dependencies:** Core data layer, Setting & Style Engine, Context Preparation & Chapter Generation Engine, Review & Editing Engine

---

## 1. Goal

Implement the final subsystem of the automatic novel writing pipeline. This subsystem is responsible for:

1. **`LibrarianAgent`**: Extract structured world-state changes from polished chapter text using LLM, with rule-based heuristic fallback, and persist them to the database.
2. **`ArchiveService`**: Mark chapters as `archived`, update novel-level statistics (total word count, archived chapter count), and persist polished text to Markdown.
3. **`ExportService`**: Aggregate archived chapters by volume or novel into `.md` and `.txt` files.
4. **`NovelDirector` integration**: Complete the `LIBRARIAN` phase in `advance()`, handle chapter-to-chapter transition within a volume, and generate a placeholder volume plan when the current volume is complete.

---

## 2. Architecture

```
FAST_REVIEWING passed
    │
    ▼
┌─────────────────────────────────────────────┐
│ NovelDirector._run_librarian()              │
│  1. Validate chapter.polished_text exists   │
│  2. LibrarianAgent.extract()                │
│     • LLM-driven structured extraction      │
│     • On failure: fallback to heuristic     │
│  3. LibrarianAgent.persist()                │
│     • timeline, spaceline, entities         │
│     • entity_versions, foreshadowings       │
│  4. ArchiveService.archive()                │
│     • status = archived                     │
│     • update checkpoint stats               │
│     • write Markdown                        │
│  5. save_checkpoint(COMPLETED)              │
└─────────────────────────────────────────────┘
    │
    ▼
COMPLETED
    │
    ▼
NovelDirector._continue_to_next_chapter()
    ├── Same volume has next chapter
    │   └── → CONTEXT_PREPARATION
    ├── Current volume is complete
    │   └── Generate placeholder volume plan
    │   └── → VOLUME_PLANNING (for future subsystem)
    └── On error: remain in LIBRARIAN
```

---

## 3. LibrarianAgent

### 3.1 Responsibilities

1. Load current world context from database: `entities`, `spaceline`, `timeline`, `foreshadowings`.
2. Call LLM with a strict JSON prompt to extract changes from `polished_text`.
3. If LLM call fails (timeout, parse error, malformed JSON), fall back to rule-based heuristic extraction.
4. Return a structured `ExtractionResult` (do **not** write to DB inside the agent).
5. Provide a `persist()` method that `NovelDirector` calls to write changes via repositories/services.

### 3.2 Schema

**File:** `src/novel_dev/schemas/librarian.py`

```python
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
    foreshadowings_recovered: List[str] = Field(default_factory=list)  # IDs
    new_foreshadowings: List[NewForeshadowing] = Field(default_factory=list)
```

### 3.3 LLM Extraction

```python
async def extract(
    self,
    novel_id: str,
    chapter_id: str,
    polished_text: str,
) -> ExtractionResult:
    context = await self._load_context(novel_id, chapter_id)
    prompt = self._build_prompt(polished_text, context)
    response = await self._call_llm(prompt)
    return ExtractionResult.model_validate_json(response)
```

**Prompt requirements:**
- Provide `active_entities`, `spaceline`, `timeline`, `pending_foreshadowings` as JSON context.
- Instruct the model to return ONLY JSON matching `ExtractionResult` schema.
- Rules: no hallucination, state changes must be concrete key-value pairs, recovered foreshadowings must reference existing IDs.

### 3.4 Fallback Heuristic Extraction

```python
def fallback_extract(self, polished_text: str, checkpoint_data: dict) -> ExtractionResult:
    """Rule-based extraction when LLM fails."""
```

**Fallback rules:**
- **Timeline**: Regex scan for Chinese time phrases (`三天后`, `一个月后`) → map to `tick += N`.
- **Spaceline**: Detect `来到/抵达/进入` + location name → create/update node.
- **New entities**: Compare capitalized proper nouns (or known Chinese name patterns) against `active_entities`.
- **Character updates**: Detect verbs like `突破`, `受伤`, `获得` co-occurring with known character names.
- **Foreshadowings**: String similarity match against pending foreshadowings for recovery; detect `谜团/未解/悬念` patterns for new ones.

### 3.5 Persist Logic

```python
async def persist(self, extraction: ExtractionResult, chapter_id: str) -> None:
    # Timeline
    for event in extraction.timeline_events:
        await self.timeline_repo.create(event.tick, event.narrative, event.anchor_event_id)

    # Spaceline (add get_by_id to repository if missing)
    for change in extraction.spaceline_changes:
        node = await self.spaceline_repo.get_by_id(change.location_id)
        if node:
            node.name = change.name
            node.parent_id = change.parent_id
            node.narrative = change.narrative or node.narrative
            await self.session.flush()
        else:
            await self.spaceline_repo.create(change.location_id, change.name, change.parent_id, change.narrative)

    # New entities + initial version
    import uuid
    for entity in extraction.new_entities:
        eid = str(uuid.uuid4())
        await self.entity_service.create_entity(eid, entity.type, entity.name)
        await self.entity_service.update_state(eid, entity.state, diff_summary={"created": True})

    # Concept/Character updates → append version
    for update in extraction.concept_updates + extraction.character_updates:
        await self.entity_service.update_state(update.entity_id, update.state, diff_summary=update.diff_summary)

    # Foreshadowings recovered
    for fs_id in extraction.foreshadowings_recovered:
        await self.foreshadowing_repo.mark_recovered(fs_id, chapter_id=chapter_id)

    # New foreshadowings
    import uuid
    for fs in extraction.new_foreshadowings:
        fs_id = str(uuid.uuid4())
        await self.foreshadowing_repo.create(
            fs_id=fs_id,
            content=fs.content,
            埋下_chapter_id=fs.埋下_chapter_id,
            埋下_time_tick=fs.埋下_time_tick,
            埋下_location_id=fs.埋下_location_id,
            回收条件=fs.回收条件,
        )
```

---

## 4. ArchiveService

**File:** `src/novel_dev/services/archive_service.py`

```python
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

        # Mark archived
        await self.chapter_repo.update_status(chapter_id, "archived")

        # Update checkpoint stats
        state = await self.state_repo.get_state(novel_id)
        stats = state.checkpoint_data.get("archive_stats", {})
        chapter_word_count = len(ch.polished_text)
        stats["total_word_count"] = stats.get("total_word_count", 0) + chapter_word_count
        stats["archived_chapter_count"] = stats.get("archived_chapter_count", 0) + 1
        avg = stats["total_word_count"] / max(stats["archived_chapter_count"], 1)
        stats["avg_word_count"] = int(avg)
        state.checkpoint_data["archive_stats"] = stats

        await self.state_repo.save_checkpoint(
            novel_id,
            current_phase=state.current_phase,
            checkpoint_data=state.checkpoint_data,
            current_volume_id=state.current_volume_id,
            current_chapter_id=state.current_chapter_id,
        )

        # Write Markdown
        path_md = await self.sync.write_chapter(novel_id, ch.volume_id, chapter_id, ch.polished_text)

        return {
            "word_count": chapter_word_count,
            "path_md": path_md,
        }
```

---

## 5. ExportService

**File:** `src/novel_dev/services/export_service.py`

```python
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
        from sqlalchemy import select, distinct
        from novel_dev.db.models import Chapter
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

---

## 6. NovelDirector Integration

### 6.1 Valid Transitions Update

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

### 6.2 advance() Extension

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

### 6.3 _run_librarian()

```python
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
```

### 6.4 _continue_to_next_chapter()

```python
async def _continue_to_next_chapter(self, novel_id: str) -> NovelState:
    state = await self.resume(novel_id)
    checkpoint = dict(state.checkpoint_data or {})

    volume_plan = checkpoint.get("current_volume_plan", {})
    chapters = volume_plan.get("chapters", [])
    current_chapter_id = state.current_chapter_id

    # 1. Next chapter in same volume
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

    # 2. Volume complete → placeholder volume plan
    import uuid
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

---

## 7. API Endpoints

**File:** `src/novel_dev/api/routes.py`

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
    from novel_dev.config import Settings
    settings = Settings()
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

---

## 8. MCP Tools

**File:** `src/novel_dev/mcp_server/server.py`

- `run_librarian(novel_id: str) -> dict`
- `export_novel(novel_id: str, format: str = "md") -> dict`
- `get_archive_stats(novel_id: str) -> dict`

All mutation tools must call `await session.commit()` before returning.

---

## 9. Testing Strategy

### 9.1 Agent Tests

**`tests/test_agents/test_librarian.py`**
- `test_llm_extraction_success`: mock LLM response, validate `ExtractionResult` fields.
- `test_llm_extraction_fallback_to_heuristic`: simulate LLM failure, assert fallback returns valid result.
- `test_persist_writes_to_database`: use test database, verify rows in `timeline`, `entities`, `foreshadowings` after `persist()`.

### 9.2 Service Tests

**`tests/test_services/test_archive_service.py`**
- `test_archive_updates_status_and_stats`: chapter status becomes `archived`, `archive_stats` updated in `novel_state.checkpoint_data`.
- `test_archive_writes_markdown`: Markdown file exists with correct content.

**`tests/test_services/test_export_service.py`**
- `test_export_volume_aggregates_archived_chapters`: only `archived` chapters included.
- `test_export_novel_skips_unarchived_chapters`: pending/edited chapters excluded.
- `test_export_unsupported_format_raises`: `ValueError` for `format="pdf"`.

### 9.3 Director Tests

**`tests/test_agents/test_director_librarian.py`**
- `test_librarian_phase_advances_to_completed`: end-to-end `LIBRARIAN -> COMPLETED` with DB assertions.
- `test_librarian_auto_continues_to_next_chapter`: `COMPLETED -> CONTEXT_PREPARATION` when next chapter exists.
- `test_librarian_last_chapter_goes_to_volume_planning`: placeholder volume plan created, state is `VOLUME_PLANNING`.
- `test_librarian_llm_failure_fallback_and_success`: LLM fails, fallback succeeds, flow completes.
- `test_librarian_both_extractions_fail`: `RuntimeError`, state remains `LIBRARIAN`, `librarian_error` in checkpoint.

### 9.4 API Tests

**`tests/test_api/test_librarian_routes.py`**
- `test_post_librarian_success`: `POST /librarian` returns updated state.
- `test_post_export_success`: `POST /export` returns file path.
- `test_get_archive_stats_success`: stats reflect archived chapters.

### 9.5 MCP Tests

Update **`tests/test_mcp_server.py`**:
- Tool registration count includes 3 new tools.
- `test_mcp_run_librarian` integration test.
- `test_mcp_export_novel` integration test.
- `test_mcp_get_archive_stats` integration test.

---

## 10. Files

| File | Responsibility |
|------|----------------|
| `src/novel_dev/schemas/librarian.py` | `ExtractionResult`, `TimelineEvent`, `NewEntity`, etc. |
| `src/novel_dev/agents/librarian.py` | `LibrarianAgent` with LLM + fallback extraction + persist |
| `src/novel_dev/services/archive_service.py` | `ArchiveService` |
| `src/novel_dev/services/export_service.py` | `ExportService` |
| `src/novel_dev/agents/director.py` | Add `_run_librarian`, `_continue_to_next_chapter`, `advance` extension |
| `src/novel_dev/storage/markdown_sync.py` | Add `write_volume`, `write_novel` |
| `src/novel_dev/api/routes.py` | Add `/librarian`, `/export`, `/archive_stats` endpoints |
| `src/novel_dev/mcp_server/server.py` | Add 3 MCP tools |
| `tests/test_agents/test_librarian.py` | LibrarianAgent tests |
| `tests/test_services/test_archive_service.py` | ArchiveService tests |
| `tests/test_services/test_export_service.py` | ExportService tests |
| `tests/test_agents/test_director_librarian.py` | Director LIBRARIAN flow tests |
| `tests/test_api/test_librarian_routes.py` | API route tests |
| `tests/test_mcp_server.py` | MCP tool tests (updated) |
