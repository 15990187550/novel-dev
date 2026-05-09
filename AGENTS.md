# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Common Commands

All Python commands require `PYTHONPATH=src` because the package is `novel_dev` under `src/`.

```bash
# Run the FastAPI server
PYTHONPATH=src python3.11 -m uvicorn novel_dev.api:app --reload

# Run the MCP server
PYTHONPATH=src python3.11 -m novel_dev.mcp_server

# Run tests
PYTHONPATH=src python3.11 -m pytest tests/ -q

# Run a single test
PYTHONPATH=src python3.11 -m pytest tests/path/to/test.py::test_name -v

# Install in editable mode
pip install -e ".[dev]"

# Database migrations (Alembic)
alembic upgrade head
alembic revision --autogenerate -m "description"
```

## Architecture Overview

This is an AI-driven novel writing pipeline. It uses a multi-agent system where each agent is an LLM-driven Python class. A `NovelDirector` orchestrates phase transitions.

### Pipeline Phases

The 9 phases, in order, controlled by `NovelDirector` (`src/novel_dev/agents/director.py`):

1. **brainstorming** — `BrainstormAgent` generates a synopsis from uploaded setting documents
2. **volume_planning** — `VolumePlannerAgent` generates a volume plan with self-scoring/revision loop
3. **context_preparation** — `ContextAgent` assembles chapter context (entities, timeline, foreshadowings)
4. **drafting** — `WriterAgent` writes chapter draft beat-by-beat
5. **reviewing** — `CriticAgent` scores the chapter on 5 dimensions
6. **editing** — `EditorAgent` polishes low-scoring beats
7. **fast_reviewing** — `FastReviewAgent` checks consistency and cohesion
8. **librarian** — `LibrarianAgent` extracts world-state updates; `ArchiveService` writes to Markdown
9. **completed** — Pipeline loops back to `context_preparation` for the next chapter, or `volume_planning` for the next volume

Phase transitions are explicit: API `POST /api/novels/{id}/advance` calls `director.advance()`, which validates prerequisites and runs the appropriate agent.

### LLM Abstraction

`LLMFactory` (`src/novel_dev/llm/factory.py`) is a global singleton (imported as `llm_factory` from `novel_dev.llm`). It reads `llm_config.yaml` and provides per-agent, per-task LLM clients with automatic fallback chains.

Key pattern:
```python
from novel_dev.llm import llm_factory
from novel_dev.llm.models import ChatMessage

client = llm_factory.get("AgentName", task="task_name")
config = llm_factory._resolve_config("AgentName", "task_name")
response = await client.acomplete([ChatMessage(role="user", content=prompt)], config)
```

**Critical:** `acomplete()` receives two positional arguments: `(messages, config)`. Any mock of `acomplete` in tests must accept both.

The `call_and_parse()` helper (`src/novel_dev/agents/_llm_helpers.py`) wraps this pattern: it calls the LLM, strips markdown code blocks, extracts the first JSON object, and runs a parser function. If parsing fails, it retries up to `max_retries` with exponential backoff.

### Database

SQLAlchemy 2.0 async with `asyncpg` for PostgreSQL. Models use `Mapped`/`mapped_column` declarative style. Key tables:

- `novel_state` — single row per novel; `checkpoint_data` (JSON) holds the entire working state (synopsis, volume plan, chapter plan, scores, etc.)
- `chapters` — per-chapter draft/polished text and scores
- `entities` / `entity_versions` — versioned world-state entities (characters, items, etc.)
- `entity_relationships` — directed graph between entities
- `timeline` / `spaceline` — temporal and spatial narrative structure
- `foreshadowings` —伏笔 tracking with 埋下/回收 lifecycle
- `novel_documents` — uploaded setting/style documents with vector embeddings
- `pending_extractions` — intermediate extraction results awaiting user approval

`VectorCompat` (`src/novel_dev/db/models.py`) is a compatibility type that uses `pgvector.Vector` on PostgreSQL and falls back to `JSON` on SQLite.

**Important:** Writes require explicit `await session.commit()`. The `get_session()` dependency in API routes yields a session but does NOT commit automatically.

### Testing

Tests use a shared SQLite file DB (`test_novel_dev.db`) so the global engine (used by MCP server and non-overridden API routes) connects to the same database. See `tests/conftest.py`.

The `mock_llm_factory` fixture (autouse) globally mocks `llm_factory.get()` and `llm_factory.get_embedder()`. When writing new tests that mock LLM calls, either rely on this fixture or patch `novel_dev.llm.llm_factory`.

### Services and Repositories

- **Repositories** (`src/novel_dev/repositories/`) — thin async data access layers over SQLAlchemy
- **Services** (`src/novel_dev/services/`) — business logic: `EmbeddingService`, `EntityService`, `ExtractionService`, `ArchiveService`, `ExportService`
- **Agents** (`src/novel_dev/agents/`) — LLM-driven workflow steps; each agent typically instantiates its own repositories

`EmbeddingService` is instantiated per-request (not a singleton) because it needs a session and an embedder. The same pattern applies to most services.

### API Structure

FastAPI with a single router in `src/novel_dev/api/routes.py`. The `__init__.py` mounts static files from `src/novel_dev/web/` (a Vue 3 SPA single-file `index.html`).

Key endpoints:
- `POST /api/novels/{id}/documents/upload` — upload setting/style documents
- `POST /api/novels/{id}/brainstorm` — generate synopsis
- `POST /api/novels/{id}/volume_plan` — generate volume plan
- `POST /api/novels/{id}/chapters/{cid}/context` — prepare chapter context
- `POST /api/novels/{id}/chapters/{cid}/draft` — write chapter draft
- `POST /api/novels/{id}/advance` — advance pipeline phase
- `POST /api/novels/{id}/librarian` — run librarian manually

### Configuration

`llm_config.yaml` at repo root defines per-agent LLM settings. Environment variables are loaded from `.env` via `pydantic-settings`. Required env vars for production: `DATABASE_URL`, `MOONSHOT_API_KEY`, `MINIMAX_API_KEY`.

### Key Conventions

- All agent names are PascalCase in code (e.g. `VolumePlannerAgent`) but snake_case in `llm_config.yaml` (e.g. `volume_planner_agent`). `LLMFactory._normalize_agent_name()` handles the conversion.
- Word count for CJK text is computed by stripping whitespace and counting characters (`len(text.replace(" ", "").replace("\n", ""))`).
- The EditorAgent uses CJK bigram overlap (35% threshold) as a hallucination guard when rewriting beats.
- VolumePlannerAgent has a self-scoring loop: it generates a plan, scores it, and revises if `overall < 85`, up to 3 attempts.
- Fallback volume plans (when LLM parsing fails) must have at least 3 beats so the writer can reach target word count.
