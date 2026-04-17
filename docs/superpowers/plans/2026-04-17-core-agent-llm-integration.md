# Core Agent LLM Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hardcoded placeholders in VolumePlannerAgent, WriterAgent, CriticAgent, EditorAgent, and FastReviewAgent with real LLM calls via `llm_factory`.

**Architecture:** Each agent follows the BrainstormAgent pattern: build a `ChatMessage` list, call `llm_factory.get(agent_name, task=...).acomplete()`, and parse the JSON response with Pydantic. Synchronous helper methods become `async`. Corresponding tests switch from testing hardcoded logic to mocking `llm_factory` with `AsyncMock` + `LLMResponse`.

**Tech Stack:** Python 3.11+, FastMCP-compatible LLM factory, Pydantic, pytest-asyncio, SQLAlchemy 2.0 async.

---

## File Map

| File | Responsibility |
|---|---|
| `src/novel_dev/agents/volume_planner.py` | LLM-based `_generate_score` and `_revise_volume_plan` |
| `src/novel_dev/agents/writer_agent.py` | LLM-based `_generate_beat` and `_rewrite_angle` |
| `src/novel_dev/agents/critic_agent.py` | LLM-based `_generate_score` and `_generate_beat_scores` |
| `src/novel_dev/agents/editor_agent.py` | LLM-based `_rewrite_beat` |
| `src/novel_dev/agents/fast_review_agent.py` | LLM-based consistency/cohesion check |
| `tests/test_agents/test_volume_planner.py` | Mock-based tests for VolumePlannerAgent |
| `tests/test_agents/test_writer_agent.py` | Mock-based tests for WriterAgent |
| `tests/test_agents/test_critic_agent.py` | Mock-based tests for CriticAgent |
| `tests/test_agents/test_editor_agent.py` | Mock-based tests for EditorAgent |
| `tests/test_agents/test_fast_review_agent.py` | Mock-based tests for FastReviewAgent |

---

### Task 1: VolumePlannerAgent LLM Integration

**Files:**
- Modify: `src/novel_dev/agents/volume_planner.py`
- Test: `tests/test_agents/test_volume_planner.py`

- [ ] **Step 1: Update test to mock LLM for success path**

Replace the body of `tests/test_agents/test_volume_planner.py::test_plan_volume_success` with:

```python
import json
from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.volume_planner import VolumePlannerAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.outline import SynopsisData, VolumeScoreResult, VolumePlan
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.llm.models import LLMResponse


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

    score_result = VolumeScoreResult(
        overall=88,
        outline_fidelity=88,
        character_plot_alignment=88,
        hook_distribution=88,
        foreshadowing_management=88,
        chapter_hooks=88,
        page_turning=88,
        summary_feedback="good",
    )
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text=score_result.model_dump_json())

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = VolumePlannerAgent(async_session)
        plan = await agent.plan("n_plan", volume_number=1)

    assert plan.volume_id == "vol_1"
    assert len(plan.chapters) == 3

    state = await director.resume("n_plan")
    assert state.current_phase == Phase.CONTEXT_PREPARATION.value
    assert "current_volume_plan" in state.checkpoint_data
    assert "current_chapter_plan" in state.checkpoint_data

    docs = await DocumentRepository(async_session).get_by_type("n_plan", "volume_plan")
    assert len(docs) == 1
    assert docs[0].doc_type == "volume_plan"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_volume_planner.py::test_plan_volume_success -v`
Expected: FAIL (llm_factory not yet imported/patched correctly in agent)

- [ ] **Step 3: Implement LLM-based `_generate_score` and `_revise_volume_plan` in VolumePlannerAgent**

Modify `src/novel_dev/agents/volume_planner.py`:

Add imports at top:
```python
from novel_dev.llm import llm_factory
from novel_dev.llm.models import ChatMessage
```

Change `_generate_score` to:
```python
    async def _generate_score(self, plan: VolumePlan) -> VolumeScoreResult:
        prompt = (
            "你是一个小说分卷规划评审专家。请根据以下 VolumePlan JSON 进行多维度评分，"
            "返回严格符合 VolumeScoreResult Schema 的 JSON。"
            f"\n\n{plan.model_dump_json()}"
        )
        client = llm_factory.get("VolumePlannerAgent", task="score_volume_plan")
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        return VolumeScoreResult.model_validate_json(response.text)
```

Change `_revise_volume_plan` to:
```python
    async def _revise_volume_plan(self, plan: VolumePlan, feedback: str) -> VolumePlan:
        prompt = (
            "你是一个小说分卷规划专家。请根据以下 VolumePlan 和评审反馈进行修正，"
            "返回严格符合 VolumePlan Schema 的 JSON。"
            f"\n\nVolumePlan:\n{plan.model_dump_json()}"
            f"\n\n反馈：{feedback}"
        )
        client = llm_factory.get("VolumePlannerAgent", task="revise_volume_plan")
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        return VolumePlan.model_validate_json(response.text)
```

In the `plan` method, change the loop body to await the now-async methods:
```python
        attempt = checkpoint.get("volume_plan_attempt_count", 0)
        while True:
            score = await self._generate_score(volume_plan)
            if score.overall >= 85:
                break
            attempt += 1
            checkpoint["volume_plan_attempt_count"] = attempt
            if attempt >= 3:
                await self.director.save_checkpoint(
                    novel_id,
                    phase=Phase.VOLUME_PLANNING,
                    checkpoint_data=checkpoint,
                    volume_id=state.current_volume_id,
                    chapter_id=state.current_chapter_id,
                )
                raise RuntimeError("Max volume plan attempts exceeded")
            volume_plan = await self._revise_volume_plan(volume_plan, score.summary_feedback)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_volume_planner.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/volume_planner.py tests/test_agents/test_volume_planner.py
git commit -m "feat(volume_planner): replace placeholders with LLM calls"
```

---

### Task 2: WriterAgent LLM Integration

**Files:**
- Modify: `src/novel_dev/agents/writer_agent.py`
- Test: `tests/test_agents/test_writer_agent.py`

- [ ] **Step 1: Update test to mock LLM**

Replace the body of `tests/test_agents/test_writer_agent.py` with:

```python
from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.writer_agent import WriterAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.context import ChapterContext, ChapterPlan, BeatPlan, EntityState, LocationContext
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.llm.models import LLMResponse


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

    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text="开场节拍生成的正文内容，字数足够多。"),
        LLMResponse(text="冲突节拍生成的正文内容，字数足够多。"),
    ]

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
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

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_writer_agent.py::test_write_draft_success -v`
Expected: FAIL (agent doesn't import llm_factory yet)

- [ ] **Step 3: Implement LLM-based beat generation**

Modify `src/novel_dev/agents/writer_agent.py`:

Add imports:
```python
from novel_dev.llm import llm_factory
from novel_dev.llm.models import ChatMessage
```

Change `_generate_beat` to:
```python
    async def _generate_beat(self, beat: BeatPlan, context: ChapterContext, previous_text: str) -> str:
        prompt = (
            "你是一位小说创作助手。请根据以下节拍计划和上下文，生成该节拍的正文。"
            "要求：只返回正文内容，不添加解释。\n\n"
            f"### 节拍计划\n{beat.model_dump_json()}\n\n"
            f"### 章节上下文\n{context.model_dump_json()}\n\n"
            f"### 已写文本\n{previous_text}\n\n"
            "请生成正文："
        )
        client = llm_factory.get("WriterAgent", task="generate_beat")
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        return response.text.strip()
```

Change `_rewrite_angle` to:
```python
    async def _rewrite_angle(self, beat: BeatPlan, original_text: str, context: ChapterContext) -> str:
        prompt = (
            "你是一位小说创作助手。当前节拍过短，请扩写并保持与上下文的连贯。"
            "只返回扩写后的正文，不添加解释。\n\n"
            f"### 节拍计划\n{beat.model_dump_json()}\n\n"
            f"### 章节上下文\n{context.model_dump_json()}\n\n"
            f"### 当前过短文本\n{original_text}\n\n"
            "请扩写："
        )
        client = llm_factory.get("WriterAgent", task="rewrite_beat")
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        return response.text.strip()
```

No caller changes needed because `_generate_beat` and `_rewrite_angle` were already awaited in `write()`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_writer_agent.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/writer_agent.py tests/test_agents/test_writer_agent.py
git commit -m "feat(writer_agent): replace placeholders with LLM calls"
```

---

### Task 3: CriticAgent LLM Integration

**Files:**
- Modify: `src/novel_dev/agents/critic_agent.py`
- Test: `tests/test_agents/test_critic_agent.py`

- [ ] **Step 1: Update test to mock LLM**

Replace the body of `tests/test_agents/test_critic_agent.py` with:

```python
from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.critic_agent import CriticAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.context import ChapterPlan, BeatPlan, ChapterContext, LocationContext
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.schemas.review import ScoreResult, DimensionScore
from novel_dev.llm.models import LLMResponse


def _make_context():
    plan = ChapterPlan(chapter_number=1, title="T", target_word_count=3000, beats=[BeatPlan(summary="B1", target_mood="tense")])
    return ChapterContext(
        chapter_plan=plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[],
    )


@pytest.mark.asyncio
async def test_review_pass_high_score(async_session):
    director = NovelDirector(session=async_session)
    context = _make_context()
    await director.save_checkpoint(
        "novel_crit_pass",
        phase=Phase.REVIEWING,
        checkpoint_data={"chapter_context": context.model_dump(), "draft_attempt_count": 0},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")
    await ChapterRepository(async_session).update_text("c1", raw_draft="a" * 100)

    score_result = ScoreResult(
        overall=88,
        dimensions=[
            DimensionScore(name="plot_tension", score=85, comment="节奏稳定"),
            DimensionScore(name="characterization", score=85, comment="人物行为一致"),
            DimensionScore(name="readability", score=85, comment="可读性良好"),
            DimensionScore(name="consistency", score=85, comment="设定无冲突"),
            DimensionScore(name="humanity", score=85, comment="自然流畅"),
        ],
        summary_feedback="整体良好",
    )
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=score_result.model_dump_json()),
        LLMResponse(text='[{"beat_index": 0, "scores": {"plot_tension": 80, "humanity": 80}}]'),
    ]

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = CriticAgent(async_session)
        result = await agent.review("novel_crit_pass", "c1")

    assert result.overall >= 70

    ch = await ChapterRepository(async_session).get_by_id("c1")
    assert ch.score_breakdown == {
        d.name: {"score": d.score, "comment": d.comment} for d in result.dimensions
    }

    state = await director.resume("novel_crit_pass")
    assert state.current_phase == Phase.EDITING.value


@pytest.mark.asyncio
async def test_review_fail_low_score(async_session):
    director = NovelDirector(session=async_session)
    context = _make_context()
    await director.save_checkpoint(
        "novel_crit_fail",
        phase=Phase.REVIEWING,
        checkpoint_data={"chapter_context": context.model_dump(), "draft_attempt_count": 0},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")

    score_result = ScoreResult(
        overall=55,
        dimensions=[
            DimensionScore(name="plot_tension", score=50, comment="节奏拖沓"),
            DimensionScore(name="characterization", score=50, comment="扁平"),
            DimensionScore(name="readability", score=50, comment="晦涩"),
            DimensionScore(name="consistency", score=60, comment="有小冲突"),
            DimensionScore(name="humanity", score=60, comment="稍生硬"),
        ],
        summary_feedback="需要重写",
    )
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=score_result.model_dump_json()),
        LLMResponse(text='[{"beat_index": 0, "scores": {"plot_tension": 50, "humanity": 50}}]'),
    ]

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = CriticAgent(async_session)
        result = await agent.review("novel_crit_fail", "c1")

    assert result.overall < 70

    state = await director.resume("novel_crit_fail")
    assert state.current_phase == Phase.DRAFTING.value
    assert state.checkpoint_data["draft_attempt_count"] == 1


@pytest.mark.asyncio
async def test_review_red_line_rollback(async_session):
    director = NovelDirector(session=async_session)
    context = _make_context()
    await director.save_checkpoint(
        "novel_crit_red",
        phase=Phase.REVIEWING,
        checkpoint_data={"chapter_context": context.model_dump()},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")

    score_result = ScoreResult(
        overall=75,
        dimensions=[
            DimensionScore(name="plot_tension", score=80, comment=""),
            DimensionScore(name="characterization", score=80, comment=""),
            DimensionScore(name="readability", score=80, comment=""),
            DimensionScore(name="consistency", score=20, comment="严重冲突"),
            DimensionScore(name="humanity", score=80, comment=""),
        ],
        summary_feedback="red line",
    )
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=score_result.model_dump_json()),
        LLMResponse(text='[{"beat_index": 0, "scores": {"plot_tension": 80, "humanity": 80}}]'),
    ]

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = CriticAgent(async_session)
        result = await agent.review("novel_crit_red", "c1")

    assert result.overall == 75

    state = await director.resume("novel_crit_red")
    assert state.current_phase == Phase.DRAFTING.value


@pytest.mark.asyncio
async def test_review_max_attempts_exceeded(async_session):
    director = NovelDirector(session=async_session)
    context = _make_context()
    await director.save_checkpoint(
        "novel_crit_max",
        phase=Phase.REVIEWING,
        checkpoint_data={"chapter_context": context.model_dump(), "draft_attempt_count": 2},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")

    score_result = ScoreResult(
        overall=55,
        dimensions=[DimensionScore(name="plot_tension", score=50, comment="") for _ in range(5)],
        summary_feedback="差",
    )
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=score_result.model_dump_json()),
        LLMResponse(text='[]'),
    ]

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = CriticAgent(async_session)
        with pytest.raises(RuntimeError, match="Max draft attempts exceeded"):
            await agent.review("novel_crit_max", "c1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_critic_agent.py::test_review_pass_high_score -v`
Expected: FAIL (agent doesn't use llm_factory yet)

- [ ] **Step 3: Implement LLM-based scoring**

Modify `src/novel_dev/agents/critic_agent.py`:

Add imports:
```python
from novel_dev.llm import llm_factory
from novel_dev.llm.models import ChatMessage
```

Change `_generate_score` to async with LLM:
```python
    async def _generate_score(self, raw_draft: str, context_data: dict) -> ScoreResult:
        prompt = (
            "你是一位小说评审专家。请根据以下章节草稿和章节上下文，"
            "从 plot_tension、characterization、readability、consistency、humanity "
            "五个维度进行评分（0-100），并给出 overall 和 summary_feedback。"
            "返回严格符合 ScoreResult Schema 的 JSON。\n\n"
            f"### 章节上下文\n{json.dumps(context_data, ensure_ascii=False)}\n\n"
            f"### 草稿\n{raw_draft}\n\n"
            "请评分："
        )
        client = llm_factory.get("CriticAgent", task="score_chapter")
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        return ScoreResult.model_validate_json(response.text)
```

Add `import json` at top of file if not already present.

Change `_generate_beat_scores` to async with LLM:
```python
    async def _generate_beat_scores(self, context_data: dict) -> List[dict]:
        beats = context_data.get("chapter_plan", {}).get("beats", [])
        if not beats:
            return []
        prompt = (
            "你是一位小说评审专家。请根据以下节拍列表和章节上下文，"
            "为每个节拍给出 plot_tension 和 humanity 评分。"
            "返回 JSON 数组，每个元素格式为："
            '{"beat_index": 0, "scores": {"plot_tension": 75, "humanity": 75}}'
            f"\n\n章节上下文：\n{json.dumps(context_data, ensure_ascii=False)}"
            "\n\n请评分："
        )
        client = llm_factory.get("CriticAgent", task="score_beats")
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        return json.loads(response.text)
```

In the `review` method, add `await` to the two calls:
```python
        score_result = await self._generate_score(ch.raw_draft or "", context_data)
        beat_scores = await self._generate_beat_scores(context_data)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_critic_agent.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/critic_agent.py tests/test_agents/test_critic_agent.py
git commit -m "feat(critic_agent): replace placeholders with LLM calls"
```

---

### Task 4: EditorAgent LLM Integration

**Files:**
- Modify: `src/novel_dev/agents/editor_agent.py`
- Test: `tests/test_agents/test_editor_agent.py`

- [ ] **Step 1: Update test to mock LLM**

Replace the body of `tests/test_agents/test_editor_agent.py` with:

```python
from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.editor_agent import EditorAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.llm.models import LLMResponse


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

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="润色后的 Beat one")

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = EditorAgent(async_session)
        await agent.polish("novel_edit", "c1")

    ch = await ChapterRepository(async_session).get_by_id("c1")
    assert "润色后的 Beat one" in ch.polished_text
    assert "Beat two" in ch.polished_text
    assert ch.status == "edited"

    state = await director.resume("novel_edit")
    assert state.current_phase == Phase.FAST_REVIEWING.value


@pytest.mark.asyncio
async def test_polish_preserves_high_readability(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_edit_high_readability",
        phase=Phase.EDITING,
        checkpoint_data={
            "beat_scores": [
                {"beat_index": 0, "scores": {"readability": 80}},
            ]
        },
        volume_id="v1",
        chapter_id="c2",
    )
    await ChapterRepository(async_session).create("c2", "v1", 2, "Test")
    await ChapterRepository(async_session).update_text("c2", raw_draft="A readable beat")

    agent = EditorAgent(async_session)
    await agent.polish("novel_edit_high_readability", "c2")

    ch = await ChapterRepository(async_session).get_by_id("c2")
    assert ch.polished_text == "A readable beat"
    assert ch.status == "edited"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_editor_agent.py::test_polish_low_score_beats -v`
Expected: FAIL (agent doesn't import llm_factory yet)

- [ ] **Step 3: Implement LLM-based rewrite**

Modify `src/novel_dev/agents/editor_agent.py`:

Add imports:
```python
from novel_dev.llm import llm_factory
from novel_dev.llm.models import ChatMessage
```

Change `_rewrite_beat` to async with LLM:
```python
    async def _rewrite_beat(self, text: str, scores: dict) -> str:
        low_dims = [k for k, v in scores.items() if v < 70]
        prompt = (
            "你是一位小说编辑。请根据以下低分维度对文本进行润色重写，"
            "只返回重写后的正文，不添加解释。\n\n"
            f"低分维度：{', '.join(low_dims)}\n\n"
            f"原文：\n{text}\n\n"
            "重写："
        )
        client = llm_factory.get("EditorAgent", task="polish_beat")
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        return response.text.strip()
```

In the `polish` method, add `await`:
```python
                polished = await self._rewrite_beat(beat_text, scores)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_editor_agent.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/editor_agent.py tests/test_agents/test_editor_agent.py
git commit -m "feat(editor_agent): replace placeholders with LLM calls"
```

---

### Task 5: FastReviewAgent LLM Integration

**Files:**
- Modify: `src/novel_dev/agents/fast_review_agent.py`
- Test: `tests/test_agents/test_fast_review_agent.py`

- [ ] **Step 1: Update test to mock LLM**

Replace the body of `tests/test_agents/test_fast_review_agent.py` with:

```python
import json
from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.fast_review_agent import FastReviewAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.llm.models import LLMResponse


@pytest.mark.asyncio
async def test_fast_review_pass(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_pass",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={"chapter_context": {"chapter_plan": {"target_word_count": 3}}},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")
    await ChapterRepository(async_session).update_text("c1", raw_draft="abc", polished_text="abc")

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(
        text=json.dumps({"consistency_fixed": True, "beat_cohesion_ok": True, "notes": []})
    )

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = FastReviewAgent(async_session)
        report = await agent.review("novel_fr_pass", "c1")

    assert report.word_count_ok is True
    assert report.ai_flavor_reduced is True
    assert report.beat_cohesion_ok is True
    assert report.consistency_fixed is True
    assert report.notes == []

    state = await director.resume("novel_fr_pass")
    assert state.current_phase == Phase.LIBRARIAN.value


@pytest.mark.asyncio
async def test_fast_review_fail_ai_flavor(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_fail_flavor",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={"chapter_context": {"chapter_plan": {"target_word_count": 1000}}},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")
    await ChapterRepository(async_session).update_text(
        "c1",
        raw_draft="a very long raw draft with many characters",
        polished_text="short",
    )

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(
        text=json.dumps({"consistency_fixed": True, "beat_cohesion_ok": True, "notes": []})
    )

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = FastReviewAgent(async_session)
        report = await agent.review("novel_fr_fail_flavor", "c1")

    assert report.ai_flavor_reduced is False

    state = await director.resume("novel_fr_fail_flavor")
    assert state.current_phase == Phase.EDITING.value


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

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(
        text=json.dumps({"consistency_fixed": True, "beat_cohesion_ok": True, "notes": []})
    )

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = FastReviewAgent(async_session)
        report = await agent.review("novel_fr_fail", "c1")

    assert report.word_count_ok is False
    assert "字数偏离目标超过10%" in report.notes

    state = await director.resume("novel_fr_fail")
    assert state.current_phase == Phase.EDITING.value
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_fast_review_agent.py::test_fast_review_pass -v`
Expected: FAIL (agent doesn't import llm_factory yet)

- [ ] **Step 3: Implement LLM-based consistency/cohesion check**

Modify `src/novel_dev/agents/fast_review_agent.py`:

Add imports:
```python
import json
from novel_dev.llm import llm_factory
from novel_dev.llm.models import ChatMessage
```

Add new method `_llm_check_consistency_and_cohesion`:
```python
    async def _llm_check_consistency_and_cohesion(
        self, polished: str, raw: str, chapter_context: dict
    ) -> dict:
        prompt = (
            "你是一位小说质量检查员。请根据以下精修文本、原始草稿和章节上下文，"
            "检查两点并返回严格 JSON：\n"
            "1. consistency_fixed: 精修文本是否修复了与设定/上下文的不一致\n"
            "2. beat_cohesion_ok: 节拍之间是否连贯\n"
            '3. notes: 问题列表（字符串数组）\n\n'
            f"### 章节上下文\n{json.dumps(chapter_context, ensure_ascii=False)}\n\n"
            f"### 原始草稿\n{raw}\n\n"
            f"### 精修文本\n{polished}\n\n"
            "请返回 JSON："
        )
        client = llm_factory.get("FastReviewAgent", task="fast_review_check")
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        return json.loads(response.text)
```

In the `review` method, replace the hardcoded `consistency_fixed` and `beat_cohesion_ok` with the LLM call:
```python
        word_count_ok = abs(len(polished) - target) <= target * 0.1 if target > 0 else True
        ai_flavor_reduced = len(polished) >= len(raw) * 0.5 if raw else len(polished) > 0

        chapter_context = checkpoint.get("chapter_context", {})
        llm_result = await self._llm_check_consistency_and_cohesion(polished, raw, chapter_context)
        consistency_fixed = llm_result.get("consistency_fixed", True)
        beat_cohesion_ok = llm_result.get("beat_cohesion_ok", True)
        notes = llm_result.get("notes", [])

        if not word_count_ok:
            notes.append("字数偏离目标超过10%")
```

Remove the old `notes = []` and hardcoded `consistency_fixed = True` / `beat_cohesion_ok = True` lines.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_fast_review_agent.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/fast_review_agent.py tests/test_agents/test_fast_review_agent.py
git commit -m "feat(fast_review_agent): replace placeholders with LLM calls"
```

---

### Task 6: Final Full Test Run

**Files:**
- All existing tests

- [ ] **Step 1: Run the entire test suite**

Run: `PYTHONPATH=src python3.11 -m pytest tests/ -q --tb=short`
Expected: 203 passed (or more), 0 failed

- [ ] **Step 2: Commit if any lingering changes**

```bash
git status
# If clean, nothing to do
```

---

## Self-Review Checklist

1. **Spec coverage:**
   - VolumePlannerAgent LLM scoring + revision → Task 1
   - WriterAgent LLM beat generation + rewrite → Task 2
   - CriticAgent LLM chapter scoring + beat scoring → Task 3
   - EditorAgent LLM polish → Task 4
   - FastReviewAgent LLM consistency/cohesion → Task 5

2. **Placeholder scan:** All steps contain exact code, exact commands, expected outputs.

3. **Type consistency:**
   - `_generate_score` in VolumePlannerAgent returns `VolumeScoreResult`
   - `_revise_volume_plan` returns `VolumePlan`
   - `_generate_score` in CriticAgent returns `ScoreResult`
   - `_generate_beat_scores` returns `List[dict]`
   - All formerly-sync helpers are now `async` and properly awaited by callers.
