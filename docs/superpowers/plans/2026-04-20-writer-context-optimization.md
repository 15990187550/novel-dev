# WriterAgent 上下文优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor WriterAgent's prompt from an uncontrolled single-message dump (~20000+ chars) to a structured multi-message architecture (~5500 chars) with per-beat retrieval, narrative relay batons, and system/user message separation.

**Architecture:** Three-layer prompts (system rules / narrative context / per-beat retrieval) + NarrativeRelay for inter-beat state transfer + dynamic embedding search per beat.

**Tech Stack:** Python 3.11, Pydantic, SQLAlchemy async, existing LLM drivers (all support multi-message)

---

## File Map

| File | Responsibility |
|------|----------------|
| `src/novel_dev/schemas/context.py` | Add `NarrativeRelay` schema |
| `src/novel_dev/agents/writer_agent.py` | Restructure prompt building; add relay generation |
| `src/novel_dev/agents/context_agent.py` | Truncate worldview/entity state |
| `src/novel_dev/repositories/document_repo.py` | Increase content_preview to 600 chars |
| `src/novel_dev/repositories/chapter_repo.py` | Increase content_preview to 600 chars |
| `llm_config.yaml` | Add generate_relay task config |
| `tests/test_agents/test_writer_agent_chapters.py` | Update for multi-message prompts |
| `tests/test_agents/test_writer_context.py` | New: test prompt building methods |
| `tests/conftest.py` | Add generate_relay mock |

---

### Task 1: Add NarrativeRelay Schema + LLM Config

**Files:**
- Modify: `src/novel_dev/schemas/context.py`
- Modify: `llm_config.yaml`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Add NarrativeRelay to schemas/context.py**

Add after the `LocationContext` class in `src/novel_dev/schemas/context.py`:

```python
class NarrativeRelay(BaseModel):
    """Beat 写完后生成的叙事状态快照，传递给后续 beat。"""
    scene_state: str
    emotional_tone: str
    new_info_revealed: str
    open_threads: str
    next_beat_hook: str
```

- [ ] **Step 2: Add generate_relay task to llm_config.yaml**

Add under `writer_agent.tasks` in `llm_config.yaml`:

```yaml
    generate_relay:
      temperature: 0.2
      provider: anthropic
      model: claude-haiku-4-5-20251001
      timeout: 15
```

- [ ] **Step 3: Add generate_relay mock to conftest.py**

In `tests/conftest.py`, inside the `mock_get` function, add a new elif branch before the final `else`:

```python
        elif agent == "WriterAgent" and task == "generate_relay":
            mock_client.acomplete.return_value = LLMResponse(
                text='{"scene_state":"场景状态","emotional_tone":"紧张","new_info_revealed":"新信息","open_threads":"悬念","next_beat_hook":"钩子"}'
            )
```

- [ ] **Step 4: Verify tests still pass**

Run: `PYTHONPATH=src python3.11 -m pytest tests/ -q`
Expected: All existing tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/schemas/context.py llm_config.yaml tests/conftest.py
git commit -m "feat: add NarrativeRelay schema and generate_relay LLM config"
```

---

### Task 2: Increase content_preview Length

**Files:**
- Modify: `src/novel_dev/repositories/document_repo.py`
- Modify: `src/novel_dev/repositories/chapter_repo.py`

- [ ] **Step 1: Update document_repo.py content_preview**

In `src/novel_dev/repositories/document_repo.py`, in the `similarity_search` method, change both occurrences of `[:200]` to `[:600]`:

PostgreSQL branch (~line 76):
```python
content_preview=(row.content or "")[:600],
```

SQLite branch (find the equivalent line):
```python
content_preview=(doc.content or "")[:600],
```

- [ ] **Step 2: Update chapter_repo.py content_preview**

In `src/novel_dev/repositories/chapter_repo.py`, in the `similarity_search` method, change both occurrences of `[:200]` to `[:600]`:

PostgreSQL branch (~line 111):
```python
content_preview=(row.polished_text or row.raw_draft or "")[:600],
```

SQLite branch (find the equivalent line):
```python
content_preview=(ch.polished_text or ch.raw_draft or "")[:600],
```

- [ ] **Step 3: Verify tests still pass**

Run: `PYTHONPATH=src python3.11 -m pytest tests/ -q`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/novel_dev/repositories/document_repo.py src/novel_dev/repositories/chapter_repo.py
git commit -m "feat: increase similarity search content_preview from 200 to 600 chars"
```

---

### Task 3: Truncate Context in ContextAgent

**Files:**
- Modify: `src/novel_dev/agents/context_agent.py`

- [ ] **Step 1: Truncate worldview_summary to 2000 chars**

In `src/novel_dev/agents/context_agent.py`, in the `assemble` method (~line 82), change:

```python
worldview_summary = worldview_doc.content if worldview_doc else ""
```

to:

```python
worldview_summary = (worldview_doc.content or "")[:2000] if worldview_doc else ""
```

- [ ] **Step 2: Truncate entity current_state to 300 chars**

In `_load_active_entities` (~line 157), change:

```python
state_str = str(latest.state) if latest else ""
```

to:

```python
state_str = str(latest.state)[:300] if latest else ""
```

- [ ] **Step 3: Verify tests still pass**

Run: `PYTHONPATH=src python3.11 -m pytest tests/ -q`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/novel_dev/agents/context_agent.py
git commit -m "feat: truncate worldview (2000) and entity state (300) in ContextAgent"
```

---

### Task 4: Refactor WriterAgent Prompt Building

This is the core task. Replace the single `_build_beat_prompt` method with three separate builders.

**Files:**
- Modify: `src/novel_dev/agents/writer_agent.py`
- Create: `tests/test_agents/test_writer_context.py`

- [ ] **Step 1: Write tests for new prompt builders**

Create `tests/test_agents/test_writer_context.py`:

```python
import pytest
from novel_dev.agents.writer_agent import WriterAgent
from novel_dev.schemas.context import (
    ChapterContext, ChapterPlan, BeatPlan, LocationContext,
    EntityState, NarrativeRelay,
)


def _make_context(**overrides):
    defaults = dict(
        chapter_plan=ChapterPlan(
            chapter_number=1, title="Test", target_word_count=2000,
            beats=[BeatPlan(summary="开场", target_mood="压抑")],
        ),
        style_profile={"style_guide": "简洁有力"},
        worldview_summary="测试世界观",
        active_entities=[],
        location_context=LocationContext(current="默认"),
        timeline_events=[],
        pending_foreshadowings=[],
    )
    defaults.update(overrides)
    return ChapterContext(**defaults)


class TestBuildSystemPrompt:
    def test_contains_style_and_rules(self):
        ctx = _make_context()
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._build_system_prompt(ctx, is_last=False)
        assert "风格" in result or "style" in result.lower()
        assert "禁用词" in result
        assert "show" in result.lower() or "显示不说" in result

    def test_no_worldview_or_entities(self):
        ctx = _make_context(worldview_summary="这是一段很长的世界观描述" * 100)
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._build_system_prompt(ctx, is_last=False)
        assert "世界观描述" not in result

    def test_last_beat_has_hook_clause(self):
        ctx = _make_context()
        agent = WriterAgent.__new__(WriterAgent)
        result_last = agent._build_system_prompt(ctx, is_last=True)
        result_mid = agent._build_system_prompt(ctx, is_last=False)
        assert "章末钩子" in result_last
        assert "章末钩子" not in result_mid


class TestBuildContextMessage:
    def test_includes_chapter_plan(self):
        ctx = _make_context()
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._build_context_message(
            ctx.chapter_plan.beats[0], ctx, [], "", 0, 1, False
        )
        assert "Test" in result
        assert "开场" in result

    def test_includes_relay_history(self):
        ctx = _make_context()
        relay = NarrativeRelay(
            scene_state="秦风在山洞中",
            emotional_tone="紧张",
            new_info_revealed="发现密道",
            open_threads="密道通向哪里",
            next_beat_hook="火把快灭了",
        )
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._build_context_message(
            ctx.chapter_plan.beats[0], ctx, [relay], "", 1, 3, False
        )
        assert "秦风在山洞中" in result
        assert "火把快灭了" in result

    def test_includes_last_beat_text(self):
        ctx = _make_context()
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._build_context_message(
            ctx.chapter_plan.beats[0], ctx, [], "上一段正文内容", 1, 3, False
        )
        assert "上一段正文内容" in result

    def test_no_full_context_dump(self):
        ctx = _make_context(worldview_summary="很长的世界观" * 200)
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._build_context_message(
            ctx.chapter_plan.beats[0], ctx, [], "", 0, 1, False
        )
        assert "很长的世界观" not in result
        assert len(result) < 5000


class TestFallbackRetrieval:
    def test_matches_by_key_entities(self):
        ctx = _make_context(active_entities=[
            EntityState(entity_id="e1", name="秦风", type="character", current_state="武功高强的剑客"),
            EntityState(entity_id="e2", name="玉佩", type="item", current_state="古老的传家之宝"),
        ])
        beat = BeatPlan(summary="秦风拿起玉佩", target_mood="压抑", key_entities=["秦风"])
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._fallback_retrieval(beat, ctx)
        assert "秦风" in result
        assert "玉佩" not in result

    def test_empty_when_no_match(self):
        ctx = _make_context(active_entities=[
            EntityState(entity_id="e1", name="秦风", type="character", current_state="剑客"),
        ])
        beat = BeatPlan(summary="开场", target_mood="压抑", key_entities=["柳月"])
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._fallback_retrieval(beat, ctx)
        assert result == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_writer_context.py -v`
Expected: FAIL — `_build_system_prompt`, `_build_context_message`, `_fallback_retrieval` don't exist yet.

- [ ] **Step 3: Implement _build_system_prompt**

In `src/novel_dev/agents/writer_agent.py`, add the method (keeping existing `_build_style_guide_block` and `_build_writing_rules_block`):

```python
    def _build_system_prompt(self, context: ChapterContext, is_last: bool) -> str:
        """Layer 1: Rules. Goes in system message for highest LLM priority."""
        parts = [
            "你是一位追求沉浸感与可读性的中文小说家。按以下约束生成正文。只返回正文，不添加解释。",
            self._build_style_guide_block(context),
            self._build_writing_rules_block(is_last),
        ]
        return "\n\n".join(p for p in parts if p)
```

- [ ] **Step 4: Implement _build_context_message**

Add to `WriterAgent`:

```python
    def _build_context_message(
        self, beat: BeatPlan, context: ChapterContext,
        relay_history: list, last_beat_text: str,
        idx: int, total: int, is_last: bool,
    ) -> str:
        """Layer 2: Narrative context. Chapter plan + relays + recent beat text."""
        from novel_dev.schemas.context import NarrativeRelay
        parts = []

        if context.previous_chapter_summary:
            parts.append(f"### 前情回顾\n{context.previous_chapter_summary}")

        plan_lines = [f"本章：{context.chapter_plan.title}（共{total}个节拍）"]
        for i, b in enumerate(context.chapter_plan.beats):
            marker = "→ " if i == idx else "  "
            plan_lines.append(f"{marker}节拍{i+1}: {b.summary}")
        parts.append("### 章节计划\n" + "\n".join(plan_lines))

        if relay_history:
            relay_text = "\n".join(
                f"[节拍{i+1}] {r.scene_state} | {r.emotional_tone} | 钩子: {r.next_beat_hook}"
                for i, r in enumerate(relay_history)
            )
            parts.append(f"### 已完成节拍状态\n{relay_text}")

        if last_beat_text:
            parts.append(f"### 紧邻上文（承接风格与情感）\n{last_beat_text}")

        position = f"（第{idx+1}/{total}个节拍{'|章末节拍' if is_last else ''}）"
        parts.append(f"### 当前节拍{position}\n{beat.model_dump_json()}")

        return "\n\n".join(parts)
```

- [ ] **Step 5: Implement _fallback_retrieval**

Add to `WriterAgent`:

```python
    def _fallback_retrieval(self, beat: BeatPlan, context: ChapterContext) -> str:
        """No EmbeddingService fallback: match by key_entities names."""
        beat_entities = set(beat.key_entities)
        matched = [e for e in context.active_entities if e.name in beat_entities]
        if not matched:
            return ""
        text = "\n".join(f"- [{e.type}] {e.name}: {e.current_state[:300]}" for e in matched)
        return f"### 相关角色\n{text}"
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_writer_context.py -v`
Expected: All 8 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/novel_dev/agents/writer_agent.py tests/test_agents/test_writer_context.py
git commit -m "feat: add structured prompt builders for WriterAgent"
```

---

### Task 5: Implement Per-beat Retrieval + Relay Generation

**Files:**
- Modify: `src/novel_dev/agents/writer_agent.py`

- [ ] **Step 1: Add _build_retrieval_message method**

Add to `WriterAgent`:

```python
    async def _build_retrieval_message(
        self, beat: BeatPlan, context: ChapterContext, novel_id: str,
    ) -> str:
        """Layer 3: Per-beat semantic retrieval for entities/docs/foreshadowings."""
        if not self.embedding_service:
            return self._fallback_retrieval(beat, context)

        query = f"{beat.summary} {' '.join(beat.key_entities)}"
        parts = []

        try:
            entities = await self.embedding_service.search_similar_entities(
                novel_id=novel_id, query_text=query, limit=3
            )
            if entities:
                entity_text = "\n".join(
                    f"- [{e.doc_type}] {e.title}: {e.content_preview}" for e in entities
                )
                parts.append(f"### 相关角色/物品\n{entity_text}")
        except Exception:
            pass

        try:
            docs = await self.embedding_service.search_similar(
                novel_id=novel_id, query_text=query, limit=2
            )
            if docs:
                doc_text = "\n".join(
                    f"- [{d.doc_type}] {d.title}: {d.content_preview}" for d in docs
                )
                parts.append(f"### 相关设定\n{doc_text}")
        except Exception:
            pass

        beat_entities = set(beat.key_entities)
        relevant_fs = [
            fs for fs in context.pending_foreshadowings
            if beat_entities & set(fs.get("related_entity_names", []))
        ]
        if relevant_fs:
            fs_text = "\n".join(
                f"- {fs['content']}（需自然嵌入，不要点破）" for fs in relevant_fs[:3]
            )
            parts.append(f"### 待嵌入伏笔\n{fs_text}")

        return "\n\n".join(parts) if parts else self._fallback_retrieval(beat, context)
```

- [ ] **Step 2: Add _generate_relay method**

Add to `WriterAgent`:

```python
    async def _generate_relay(self, beat_text: str, beat: BeatPlan) -> "NarrativeRelay":
        """Generate narrative state snapshot after a beat is written."""
        from novel_dev.schemas.context import NarrativeRelay
        from novel_dev.agents._llm_helpers import call_and_parse
        prompt = (
            "你是一位叙事分析师。请阅读以下小说节拍正文，提取当前叙事状态。\n"
            "返回严格 JSON：\n"
            '{"scene_state":"...","emotional_tone":"...","new_info_revealed":"...","open_threads":"...","next_beat_hook":"..."}\n\n'
            f"节拍计划: {beat.summary}\n\n"
            f"正文:\n{beat_text[:2000]}\n\n"
            "JSON:"
        )
        return await call_and_parse(
            "WriterAgent", "generate_relay", prompt,
            NarrativeRelay.model_validate_json, max_retries=2,
        )
```

- [ ] **Step 3: Verify tests still pass**

Run: `PYTHONPATH=src python3.11 -m pytest tests/ -q`
Expected: All tests pass (new methods added, nothing removed yet).

- [ ] **Step 4: Commit**

```bash
git add src/novel_dev/agents/writer_agent.py
git commit -m "feat: add per-beat retrieval and narrative relay generation"
```

---

### Task 6: Rewire _generate_beat and write() to Use New Architecture

**Files:**
- Modify: `src/novel_dev/agents/writer_agent.py`
- Modify: `tests/test_agents/test_writer_agent_chapters.py`

- [ ] **Step 1: Rewrite _generate_beat to use multi-message**

Replace the existing `_generate_beat` method in `src/novel_dev/agents/writer_agent.py`:

```python
    async def _generate_beat(
        self,
        beat: BeatPlan,
        context: ChapterContext,
        relay_history: list,
        last_beat_text: str,
        idx: int = 0,
        total: int = 1,
        is_last: bool = False,
        novel_id: str = "",
    ) -> str:
        system_prompt = self._build_system_prompt(context, is_last)
        context_msg = self._build_context_message(
            beat, context, relay_history, last_beat_text, idx, total, is_last
        )
        retrieval_msg = await self._build_retrieval_message(beat, context, novel_id)

        user_content = context_msg
        if retrieval_msg:
            user_content += "\n\n" + retrieval_msg
        user_content += "\n\n请直接输出本节拍正文："

        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=user_content),
        ]

        from novel_dev.llm import llm_factory
        client = llm_factory.get("WriterAgent", task="generate_beat")
        config = llm_factory._resolve_config("WriterAgent", "generate_beat")
        response = await client.acomplete(messages, config)
        inner = _strip_anchors(response.text)
        return f"<!--BEAT:{idx}-->\n{inner}\n<!--/BEAT:{idx}-->"
```

- [ ] **Step 2: Rewrite write() main loop**

Replace the `for idx, beat in enumerate(...)` loop inside `write()`:

```python
        relay_history = []
        inner_beats: List[str] = []

        for idx, beat in enumerate(context.chapter_plan.beats):
            is_last = (idx == total_beats - 1)
            last_beat_text = inner_beats[-1] if inner_beats else ""

            beat_text = await self._generate_beat(
                beat, context, relay_history, last_beat_text,
                idx, total_beats, is_last, novel_id,
            )
            inner = _strip_anchors(beat_text)
            if len(inner) < 50:
                inner = await self._rewrite_angle(beat, inner, context)
                beat_text = f"<!--BEAT:{idx}-->\n{inner}\n<!--/BEAT:{idx}-->"

            inner_beats.append(inner)
            raw_draft += beat_text + "\n\n"
            beat_coverage.append({"beat_index": idx, "word_count": len(inner)})

            # Generate narrative relay baton
            try:
                from novel_dev.schemas.context import NarrativeRelay
                relay = await self._generate_relay(inner, beat)
                relay_history.append(relay)
            except Exception:
                from novel_dev.schemas.context import NarrativeRelay
                relay_history.append(NarrativeRelay(
                    scene_state=beat.summary,
                    emotional_tone=beat.target_mood,
                    new_info_revealed="",
                    open_threads="",
                    next_beat_hook="",
                ))

            for fs in context.pending_foreshadowings:
                if fs["content"] in inner and fs["id"] not in embedded_foreshadowings:
                    embedded_foreshadowings.append(fs["id"])

            checkpoint["drafting_progress"] = {
                "beat_index": idx + 1,
                "total_beats": total_beats,
                "current_word_count": len(raw_draft),
            }
            checkpoint["relay_history"] = [r.model_dump() for r in relay_history]
            await self.state_repo.save_checkpoint(
                novel_id,
                current_phase=Phase.DRAFTING.value,
                checkpoint_data=checkpoint,
                current_volume_id=state.current_volume_id,
                current_chapter_id=state.current_chapter_id,
            )
```

Also remove the now-unused methods: `_build_beat_prompt` and `_build_previous_context`.

- [ ] **Step 3: Update test_writer_agent_chapters.py**

The existing tests capture prompts via `messages[0].content`. With multi-message, the system prompt is `messages[0].content` and user prompt is `messages[1].content`. Update the assertions:

In `test_similar_chapters_block_appears_in_prompt`, the similar chapters are no longer injected via ContextAgent into the prompt — they're retrieved per-beat. Since the mock won't have embedding_service, the fallback retrieval is used. Remove assertions about `参考章节（保持风格一致性）` and instead verify the multi-message structure.

Replace the assertion block at the end of both tests:

```python
    # In test_similar_chapters_block_appears_in_prompt:
    assert len(captured_prompts) >= 1
    # With multi-message, captured_prompts contains the user message content
    # Similar chapters are now per-beat retrieved, not in context dump
    prompt = captured_prompts[0]
    assert "当前节拍" in prompt  # verify new prompt structure

    # In test_empty_similar_chapters_omits_block:
    assert len(captured_prompts) >= 1
    prompt = captured_prompts[0]
    assert "当前节拍" in prompt
```

- [ ] **Step 4: Run all tests**

Run: `PYTHONPATH=src python3.11 -m pytest tests/ -q`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/writer_agent.py tests/test_agents/test_writer_agent_chapters.py
git commit -m "feat: rewire WriterAgent to use multi-message prompts with relay batons"
```

---

### Task 7: Clean Up Removed Code + Final Verification

**Files:**
- Modify: `src/novel_dev/agents/writer_agent.py` (remove dead code)

- [ ] **Step 1: Remove dead methods**

Remove these methods from `writer_agent.py` if they are no longer called:
- `_build_beat_prompt` (replaced by `_build_system_prompt` + `_build_context_message` + `_build_retrieval_message`)
- `_build_previous_context` (replaced by relay_history)
- `_build_relevant_docs_text` (replaced by per-beat retrieval)
- `_build_related_entities_text` (replaced by per-beat retrieval)
- `_build_similar_chapters_text` (replaced by per-beat retrieval)
- `_build_previous_summary_block` (inlined into `_build_context_message`)
- `_RECENT_BEATS_FULL_TEXT` class variable (no longer used)

Keep: `_build_style_guide_block`, `_build_writing_rules_block` (still used by `_build_system_prompt`).

- [ ] **Step 2: Run full test suite**

Run: `PYTHONPATH=src python3.11 -m pytest tests/ -q`
Expected: All tests pass.

- [ ] **Step 3: Verify prompt size**

Add a quick manual verification script (don't commit):

```python
# Quick check: print prompt sizes
from novel_dev.schemas.context import *
ctx = ChapterContext(
    chapter_plan=ChapterPlan(chapter_number=1, title="测试", target_word_count=3000,
        beats=[BeatPlan(summary=f"节拍{i}", target_mood="紧张") for i in range(5)]),
    style_profile={"style_guide": "简洁有力" * 50},
    worldview_summary="世界观" * 500,
    active_entities=[EntityState(entity_id=f"e{i}", name=f"角色{i}", type="character", current_state="状态" * 100) for i in range(10)],
    location_context=LocationContext(current="默认"),
    timeline_events=[],
    pending_foreshadowings=[],
)
agent = WriterAgent.__new__(WriterAgent)
sys = agent._build_system_prompt(ctx, False)
ctxmsg = agent._build_context_message(ctx.chapter_plan.beats[0], ctx, [], "", 0, 5, False)
print(f"System prompt: {len(sys)} chars")
print(f"Context message: {len(ctxmsg)} chars")
# Expected: system ~1500, context ~1000-2000
```

- [ ] **Step 4: Commit**

```bash
git add src/novel_dev/agents/writer_agent.py
git commit -m "refactor: remove dead prompt building code from WriterAgent"
```

---

## Spec Coverage Review

| Spec Requirement | Task |
|---|---|
| NarrativeRelay schema | Task 1 |
| LLM config for generate_relay | Task 1 |
| content_preview 200→600 | Task 2 |
| worldview_summary truncation (2000) | Task 3 |
| entity state truncation (300) | Task 3 |
| _build_system_prompt (Layer 1) | Task 4 |
| _build_context_message (Layer 2) | Task 4 |
| _fallback_retrieval | Task 4 |
| _build_retrieval_message (Layer 3) | Task 5 |
| _generate_relay | Task 5 |
| Multi-message _generate_beat | Task 6 |
| write() with relay_history | Task 6 |
| relay_history in checkpoint | Task 6 |
| Remove dead code | Task 7 |
| Test updates | Tasks 4, 6 |

**No gaps.**

**Placeholder scan:** All steps have concrete code. No TBD/TODO.

**Type consistency:** `NarrativeRelay` used consistently across schema, conftest mock, _generate_relay, write() loop, and _build_context_message.
