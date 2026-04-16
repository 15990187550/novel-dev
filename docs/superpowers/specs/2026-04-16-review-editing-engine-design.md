# Review and Editing Engine Design

## Goal

Implement the automatic review and editing pipeline for generated chapter drafts, consisting of `CriticAgent` (scoring and feedback), `EditorAgent` (beat-level polishing), and `FastReviewAgent` (lightweight final quality check). The subsystem is fully automated, driven by `NovelDirector.advance()`, with score thresholds, red-line guards, and a max retry limit.

## Architecture

```
REVIEWING ──► CriticAgent ──┬─► [overall < 70 or red line failed] ──► DRAFTING (with critique_feedback)
                            │
                            └─► [overall >= 70] ──► EDITING

EDITING ──► EditorAgent ──► beat-level polish ──► FAST_REVIEWING

FAST_REVIEWING ──► FastReviewAgent ──► pass ──► LIBRARIAN
```

`NovelDirector.advance(novel_id)` triggers the agent corresponding to the current phase. Each agent reads from and writes to the database via repositories, advancing the state machine on success or handling rollback on failure.

## Pydantic Schemas

**File:** `src/novel_dev/schemas/review.py`

```python
class DimensionScore(BaseModel):
    name: str
    score: int  # 0-100
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

## CriticAgent

**File:** `src/novel_dev/agents/critic_agent.py`

### Responsibilities
1. Read `chapter.raw_draft` and `checkpoint_data["chapter_context"]`.
2. Produce a `ScoreResult` with 5 dimensions.
3. Persist scores to `chapter.score_overall`, `score_breakdown`, `review_feedback`.
4. Write per-beat dimension scores into `checkpoint_data["beat_scores"]` (list of dicts, one per beat, with dimension names and scores).
5. Write a concise `critique_feedback` dict into `checkpoint_data` for WriterAgent to consume on rewrite.
6. Decide pass/fail and advance/rollback via `NovelDirector`.

### Scoring Rules

| Dimension | Weight | Red Line |
|-----------|--------|----------|
| `plot_tension` | 1.0 | — |
| `characterization` | 1.0 | — |
| `readability` | 1.0 | — |
| `consistency` | 1.2 | **< 30 → auto rollback** |
| `humanity` | 1.2 | **< 40 → auto rollback** |

- `overall` = weighted average of the 5 dimension scores.
- `overall >= 85` → pass directly to `EDITING`.
- `70 <= overall < 85` → pass to `EDITING`; EditorAgent targets dimensions < 70.
- `overall < 70` or any red line failed → rollback to `DRAFTING`.

### Retry Guard
- `checkpoint_data["draft_attempt_count"]` increments on each rollback from `REVIEWING` to `DRAFTING`.
- If `draft_attempt_count >= 3` and the chapter still fails, raise `RuntimeError("Max draft attempts exceeded")` and remain in `REVIEWING`.

## EditorAgent

**File:** `src/novel_dev/agents/editor_agent.py`

### Responsibilities
1. Read `chapter.raw_draft` and `checkpoint_data["beat_scores"]`.
2. Use `checkpoint_data["chapter_context"]` to locate beats.
3. For each beat, apply a polish strategy if any dimension in that beat's score is < 70.
4. Concatenate polished beats into `chapter.polished_text`.
5. Update chapter status to `edited` and advance state to `FAST_REVIEWING`.

### Beat-Level Polish Strategy Mapping

| Low Dimension | Polish Strategy |
|---------------|-----------------|
| `readability` | Split long sentences, remove redundancy, improve rhythm |
| `humanity` | Soundscape rewrite, remove templates, add sensory detail |
| `consistency` | Cross-check `worldview_summary` and `active_entities`, fix lore conflicts |
| `plot_tension` | Intensify conflict, remove deflating sentences |
| `characterization` | Replace exposition with action/psychology |

Beats with no low dimensions are copied unchanged.

## FastReviewAgent

**File:** `src/novel_dev/agents/fast_review_agent.py`

### Responsibilities
1. Compare `raw_draft` vs `polished_text`.
2. Produce a `FastReviewReport` via cheap, deterministic checks.
3. Persist `fast_review_score` and `fast_review_feedback` to the chapter.
4. On pass, advance to `LIBRARIAN`. On fail, rollback to `EDITING` with notes.

### Checks
- `word_count_ok`: `len(polished_text)` is within ±10% of `target_word_count`.
- `consistency_fixed`: No lore keywords from `review_feedback` appear unchanged.
- `ai_flavor_reduced`: Template phrase count (e.g., "突然", "竟然") is lower in polished vs raw.
- `beat_cohesion_ok`: Paragraph transitions do not repeat the same opening word 3+ times in a row.

## NovelDirector.advance()

**File:** `src/novel_dev/agents/director.py`

Add `advance(novel_id: str) -> NovelState`:

```python
async def advance(self, novel_id: str) -> NovelState:
    state = await self.resume(novel_id)
    current = Phase(state.current_phase)

    if current == Phase.REVIEWING:
        return await self._run_critic(state)
    elif current == Phase.EDITING:
        return await self._run_editor(state)
    elif current == Phase.FAST_REVIEWING:
        return await self._run_fast_review(state)
    else:
        raise ValueError(f"Cannot auto-advance from {current}")
```

- `_run_critic`: invokes `CriticAgent`, handles pass/rollback/retry-guard.
- `_run_editor`: invokes `EditorAgent`, advances to `FAST_REVIEWING`.
- `_run_fast_review`: invokes `FastReviewAgent`, advances to `LIBRARIAN` or rolls back to `EDITING`.

## API Endpoints

**File:** `src/novel_dev/api/routes.py`

- `POST /api/novels/{novel_id}/advance`
  - Calls `NovelDirector.advance(novel_id)`.
  - Returns the updated `novel_state`.
- `GET /api/novels/{novel_id}/review`
  - Returns the current chapter's `score_overall`, `score_breakdown`, `review_feedback`.

## MCP Tools

**File:** `src/novel_dev/mcp_server/server.py`

- `advance_novel(novel_id: str) -> dict`
- `get_review_result(novel_id: str) -> dict`
- `get_fast_review_result(novel_id: str) -> dict`

## Testing Strategy

- `tests/test_agents/test_critic_agent.py`
  - Pass (overall >= 85)
  - Marginal pass (70 <= overall < 85)
  - Fail and rollback (overall < 70)
  - Red-line rollback (`consistency` < 30 or `humanity` < 40)
  - Retry guard (3 failures → exception)
- `tests/test_agents/test_editor_agent.py`
  - Full polish flow
  - High-score beats preserved
  - Low-score beats rewritten
  - Polished text persisted and status updated
- `tests/test_agents/test_fast_review_agent.py`
  - Pass to `LIBRARIAN`
  - Fail back to `EDITING`
- `tests/test_agents/test_director_advance.py`
  - End-to-end auto-advance through REVIEWING → EDITING → FAST_REVIEWING → LIBRARIAN
  - Rollback loop capped at 3
- `tests/test_api/test_review_routes.py`
  - POST /advance, GET /review
- `tests/test_mcp_server.py`
  - Tool registration and behavior for the 3 new MCP tools

## Files

| File | Responsibility |
|------|----------------|
| `src/novel_dev/schemas/review.py` | `ScoreResult`, `FastReviewReport`, `DimensionScore` |
| `src/novel_dev/agents/critic_agent.py` | CriticAgent implementation |
| `src/novel_dev/agents/editor_agent.py` | EditorAgent implementation |
| `src/novel_dev/agents/fast_review_agent.py` | FastReviewAgent implementation |
| `src/novel_dev/agents/director.py` | Add `advance()` and private runner methods |
| `src/novel_dev/api/routes.py` | Add `/advance` and `/review` endpoints |
| `src/novel_dev/mcp_server/server.py` | Add 3 MCP tools |
| `tests/test_agents/test_critic_agent.py` | CriticAgent tests |
| `tests/test_agents/test_editor_agent.py` | EditorAgent tests |
| `tests/test_agents/test_fast_review_agent.py` | FastReviewAgent tests |
| `tests/test_agents/test_director_advance.py` | Director advance flow tests |
| `tests/test_api/test_review_routes.py` | API route tests |
| `tests/test_mcp_server.py` | MCP tool tests (updated) |
