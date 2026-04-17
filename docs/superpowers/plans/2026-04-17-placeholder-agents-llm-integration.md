# Placeholder Agents LLM Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将项目中剩余的启发式/正则/硬编码 agent 替换为 LLM 驱动，并引入两步 RAG 场景上下文构建。

**Architecture：** 新增 `_llm_helpers.py` 提供 `call_and_parse()` 共享函数；5 个 agent 统一调用 LLM；ContextAgent 采用"分析需求→按需查库→生成场景"的两步 RAG 模式。

**Tech Stack：** Python 3.11+, FastMCP, Pydantic, pytest-asyncio, tenacity

---

## File Map

| File | Responsibility |
|---|---|
| `src/novel_dev/agents/_llm_helpers.py` | 新增：`call_and_parse()` 共享函数 |
| `src/novel_dev/agents/setting_extractor.py` | LLM 驱动的 `extract()`，删除旧正则方法 |
| `src/novel_dev/agents/style_profiler.py` | LLM 驱动的 `profile()`，删除旧统计方法 |
| `src/novel_dev/agents/file_classifier.py` | LLM 驱动的 `classify()`（async），删除关键词常量 |
| `src/novel_dev/agents/context_agent.py` | 两步 RAG：`_analyze_context_needs()` + `_load_location_context()` |
| `src/novel_dev/agents/volume_planner.py` | LLM 驱动的 `_generate_volume_plan()`（async） |
| `src/novel_dev/repositories/timeline_repo.py` | 新增：`list_between()` |
| `src/novel_dev/services/extraction_service.py` | `classifier.classify()` 前加 `await` |
| `llm_config.yaml` | 新增 4 个 agent 配置 |
| `tests/test_agents/test_setting_extractor.py` | mock LLM 测试 |
| `tests/test_agents/test_style_profiler.py` | mock LLM 测试 |
| `tests/test_agents/test_file_classifier.py` | mock LLM + async 测试 |
| `tests/test_repositories/test_timeline_repo.py` | 新增：`list_between()` 测试 |

---

### Task 1: Shared Helper `_llm_helpers.py`

**Files:**
- Create: `src/novel_dev/agents/_llm_helpers.py`
- Test: `tests/test_agents/test_llm_helpers.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_agents/test_llm_helpers.py`:

```python
from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents._llm_helpers import call_and_parse
from novel_dev.llm.models import LLMResponse


@pytest.mark.asyncio
async def test_call_and_parse_success():
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text='{"key": "value"}')

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await call_and_parse(
            "TestAgent", "test_task", "prompt",
            lambda text: {"key": "value"}, max_retries=3
        )

    assert result == {"key": "value"}


@pytest.mark.asyncio
async def test_call_and_parse_retry_on_validation_error():
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text="invalid json"),
        LLMResponse(text='{"key": "value"}'),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await call_and_parse(
            "TestAgent", "test_task", "prompt",
            lambda text: {"key": "value"}, max_retries=3
        )

    assert result == {"key": "value"}
    assert mock_client.acomplete.call_count == 2


@pytest.mark.asyncio
async def test_call_and_parse_raises_after_max_retries():
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="invalid json")

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        with pytest.raises(RuntimeError, match="LLM parse failed after 3 retries"):
            await call_and_parse(
                "TestAgent", "test_task", "prompt",
                lambda text: {"key": "value"}, max_retries=3
            )

    assert mock_client.acomplete.call_count == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_llm_helpers.py -v`
Expected: FAIL (`ModuleNotFoundError: novel_dev.agents._llm_helpers`)

- [ ] **Step 3: Implement `_llm_helpers.py`**

Create `src/novel_dev/agents/_llm_helpers.py`:

```python
import asyncio
from typing import Callable, TypeVar

from novel_dev.llm import llm_factory
from novel_dev.llm.models import ChatMessage
from pydantic import ValidationError
import json

T = TypeVar("T")


async def call_and_parse(
    agent_name: str,
    task: str,
    prompt: str,
    parser: Callable[[str], T],
    max_retries: int = 3,
) -> T:
    client = llm_factory.get(agent_name, task=task)
    last_error = None
    for attempt in range(max_retries):
        try:
            response = await client.acomplete([ChatMessage(role="user", content=prompt)])
            return parser(response.text)
        except (ValidationError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < max_retries - 1:
                await asyncio.sleep(1 * (attempt + 1))
    raise RuntimeError(
        f"LLM parse failed after {max_retries} retries for {agent_name}/{task}: {last_error}"
    ) from last_error
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_llm_helpers.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/_llm_helpers.py tests/test_agents/test_llm_helpers.py
git commit -m "feat(agents): add call_and_parse shared helper with retry"
```

---

### Task 2: SettingExtractorAgent

**Files:**
- Modify: `src/novel_dev/agents/setting_extractor.py`
- Test: `tests/test_agents/test_setting_extractor.py`

- [ ] **Step 1: Write the failing test**

Replace the body of `tests/test_agents/test_setting_extractor.py`:

```python
from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.setting_extractor import SettingExtractorAgent, ExtractedSetting
from novel_dev.llm.models import LLMResponse


@pytest.mark.asyncio
async def test_extract_success():
    extracted = ExtractedSetting(
        worldview="天玄大陆",
        power_system="炼气筑基金丹",
        factions="青云宗",
        character_profiles=[
            {"name": "林风", "identity": "弟子", "personality": "坚韧", "goal": "报仇"}
        ],
        important_items=[
            {"name": "玉佩", "description": "信物", "significance": "身世"}
        ],
        plot_synopsis="林风拜入青云宗",
    )
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text=extracted.model_dump_json())

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = SettingExtractorAgent()
        result = await agent.extract("任意文本")

    assert result.worldview == "天玄大陆"
    assert len(result.character_profiles) == 1
    assert result.character_profiles[0].name == "林风"


@pytest.mark.asyncio
async def test_extract_retry_then_success():
    extracted = ExtractedSetting(worldview="大陆")
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text="invalid"),
        LLMResponse(text=extracted.model_dump_json()),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = SettingExtractorAgent()
        result = await agent.extract("任意文本")

    assert result.worldview == "大陆"
    assert mock_client.acomplete.call_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_setting_extractor.py::test_extract_success -v`
Expected: FAIL (`_llm_helpers.llm_factory` not yet patched correctly in agent, or old methods still exist)

- [ ] **Step 3: Implement LLM-based `extract()`**

Modify `src/novel_dev/agents/setting_extractor.py`:

```python
from typing import List, Optional
from pydantic import BaseModel

from novel_dev.agents._llm_helpers import call_and_parse


class CharacterProfile(BaseModel):
    name: str
    identity: str = ""
    personality: str = ""
    goal: str = ""


class ImportantItem(BaseModel):
    name: str
    description: str = ""
    significance: str = ""


class ExtractedSetting(BaseModel):
    worldview: str = ""
    power_system: str = ""
    factions: str = ""
    character_profiles: List[CharacterProfile] = []
    important_items: List[ImportantItem] = []
    plot_synopsis: str = ""


class SettingExtractorAgent:
    async def extract(self, text: str) -> ExtractedSetting:
        MAX_CHARS = 24000
        truncated = text[:MAX_CHARS]
        prompt = (
            "你是一位小说设定提取专家。请从以下设定文档中提取结构化信息，"
            "返回严格符合 ExtractedSetting Schema 的 JSON：\n"
            "1. worldview: 世界观概述\n"
            "2. power_system: 修炼/力量体系\n"
            "3. factions: 势力/宗门分布\n"
            "4. character_profiles: 人物列表（每人含 name, identity, personality, goal）\n"
            "5. important_items: 重要物品列表（每件含 name, description, significance）\n"
            "6. plot_synopsis: 剧情梗概\n\n"
            f"文档内容：\n\n{truncated}"
        )
        return await call_and_parse(
            "SettingExtractorAgent", "extract_setting", prompt,
            ExtractedSetting.model_validate_json, max_retries=3
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_setting_extractor.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/setting_extractor.py tests/test_agents/test_setting_extractor.py
git commit -m "feat(setting_extractor): replace regex with llm-driven extraction"
```

---

### Task 3: StyleProfilerAgent

**Files:**
- Modify: `src/novel_dev/agents/style_profiler.py`
- Test: `tests/test_agents/test_style_profiler.py`

- [ ] **Step 1: Write the failing test**

Replace the body of `tests/test_agents/test_style_profiler.py`:

```python
from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.style_profiler import StyleProfilerAgent, StyleProfile
from novel_dev.llm.models import LLMResponse


@pytest.mark.asyncio
async def test_profile_success():
    profile = StyleProfile(
        style_guide="节奏快，第三人称有限视角",
        style_config={
            "sentence_patterns": {"avg_length": 25, "complexity": "moderate"},
            "dialogue_style": {"direct_speech_ratio": 0.3},
            "rhetoric_devices": ["比喻", "排比"],
            "pacing": "fast",
            "vocabulary_preferences": ["剑", "血", "杀"],
            "perspective": "limited",
            "tone": "intense",
            "evolution_notes": "",
        },
    )
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text=profile.model_dump_json())

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = StyleProfilerAgent()
        result = await agent.profile("测试文本")

    assert result.style_guide != ""
    assert result.style_config.perspective == "limited"
    assert result.style_config.tone == "intense"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_style_profiler.py::test_profile_success -v`
Expected: FAIL

- [ ] **Step 3: Implement LLM-based `profile()`**

Replace the body of `src/novel_dev/agents/style_profiler.py`:

```python
from typing import List
from pydantic import BaseModel

from novel_dev.agents._llm_helpers import call_and_parse


class StyleConfig(BaseModel):
    sentence_patterns: dict = {}
    dialogue_style: dict = {}
    rhetoric_devices: list = []
    pacing: str = ""
    vocabulary_preferences: List[str] = []
    perspective: str = ""
    tone: str = ""
    evolution_notes: str = ""


class StyleProfile(BaseModel):
    style_guide: str
    style_config: StyleConfig


class StyleProfilerAgent:
    async def profile(self, text: str) -> StyleProfile:
        MAX_CHARS = 24000
        sampled = text[:MAX_CHARS]
        prompt = (
            "你是一位文学风格分析师。请分析以下小说文本的写作风格，"
            "返回严格符合 StyleProfile Schema 的 JSON：\n"
            "1. style_guide: 一段自然语言风格描述（100字以内）\n"
            "2. style_config:\n"
            "   - sentence_patterns: 句式特点（如 avg_length、complexity）\n"
            "   - dialogue_style: 对话风格（如 direct_speech_ratio、dialogue_tag_style）\n"
            "   - rhetoric_devices: 常用修辞手法\n"
            "   - pacing: 叙事节奏（fast/moderate/slow）\n"
            "   - vocabulary_preferences: 高频或特色词汇列表（5-10个）\n"
            "   - perspective: 叙事视角（first_person/limited/omniscient）\n"
            "   - tone: 整体基调（intense/dark/hopeful/romantic 等）\n"
            "   - evolution_notes: 风格演变迹象\n\n"
            f"文本样本：\n\n{sampled}"
        )
        return await call_and_parse(
            "StyleProfilerAgent", "profile_style", prompt,
            StyleProfile.model_validate_json, max_retries=3
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_style_profiler.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/style_profiler.py tests/test_agents/test_style_profiler.py
git commit -m "feat(style_profiler): replace heuristics with llm-driven analysis"
```

---

### Task 4: FileClassifier

**Files:**
- Modify: `src/novel_dev/agents/file_classifier.py`
- Test: `tests/test_agents/test_file_classifier.py`
- Modify: `src/novel_dev/services/extraction_service.py` (add await)

- [ ] **Step 1: Write the failing test**

Replace the body of `tests/test_agents/test_file_classifier.py`:

```python
from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.file_classifier import FileClassifier, FileClassificationResult
from novel_dev.llm.models import LLMResponse


@pytest.mark.asyncio
async def test_classify_setting():
    result = FileClassificationResult(file_type="setting", confidence=0.95, reason="设定文档")
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text=result.model_dump_json())

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        classifier = FileClassifier()
        classification = await classifier.classify("setting.txt", "世界观内容")

    assert classification.file_type == "setting"
    assert classification.confidence == 0.95
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_file_classifier.py::test_classify_setting -v`
Expected: FAIL (`classify` is not async)

- [ ] **Step 3: Implement LLM-based `classify()`**

Replace the body of `src/novel_dev/agents/file_classifier.py`:

```python
from typing import Literal
from pydantic import BaseModel

from novel_dev.agents._llm_helpers import call_and_parse


class FileClassificationResult(BaseModel):
    file_type: Literal["setting", "style_sample"]
    confidence: float
    reason: str


class FileClassifier:
    async def classify(self, filename: str, content_preview: str) -> FileClassificationResult:
        MAX_CHARS = 3000
        prompt = (
            "你是一位文件分类专家。请根据文件名和内容片段，判断这是小说设定文档还是风格样本。"
            "返回严格符合 FileClassificationResult Schema 的 JSON：\n"
            "file_type: 'setting' 或 'style_sample'\n"
            "confidence: 0.0-1.0 的置信度\n"
            "reason: 分类理由（简短）\n\n"
            f"文件名：{filename}\n"
            f"内容片段：\n{content_preview[:MAX_CHARS]}"
        )
        return await call_and_parse(
            "FileClassifier", "classify_file", prompt,
            FileClassificationResult.model_validate_json, max_retries=3
        )
```

- [ ] **Step 4: Add `await` in ExtractionService**

Modify `src/novel_dev/services/extraction_service.py` line 30:

```python
# 改前
classification = self.classifier.classify(filename, content)

# 改后
classification = await self.classifier.classify(filename, content)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_file_classifier.py -v`
Expected: PASS (1 test)

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_services/ -v` (如果有 extraction_service 测试)
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/agents/file_classifier.py tests/test_agents/test_file_classifier.py src/novel_dev/services/extraction_service.py
git commit -m "feat(file_classifier): replace keyword matching with llm-driven classification"
```

---

### Task 5: TimelineRepository.list_between

**Files:**
- Modify: `src/novel_dev/repositories/timeline_repo.py`
- Test: `tests/test_repositories/test_timeline_repo.py` (确认或新增)

- [ ] **Step 1: Write the failing test**

确认 `tests/test_repositories/test_timeline_repo.py` 是否存在。如果不存在，创建它并添加：

```python
import pytest


@pytest.mark.asyncio
async def test_list_between(async_session):
    from novel_dev.repositories.timeline_repo import TimelineRepository

    repo = TimelineRepository(async_session)
    await repo.create(tick=1, narrative="事件1", novel_id="n_test")
    await repo.create(tick=3, narrative="事件3", novel_id="n_test")
    await repo.create(tick=5, narrative="事件5", novel_id="n_test")

    result = await repo.list_between(2, 4, novel_id="n_test")
    assert len(result) == 1
    assert result[0].tick == 3
    assert result[0].narrative == "事件3"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_timeline_repo.py::test_list_between -v`
Expected: FAIL (`list_between` method not found)

- [ ] **Step 3: Implement `list_between()`**

Add to `src/novel_dev/repositories/timeline_repo.py`:

```python
    async def list_between(
        self, start: int, end: int, novel_id: Optional[str] = None
    ) -> List[Timeline]:
        stmt = select(Timeline).where(Timeline.tick >= start, Timeline.tick <= end)
        if novel_id is not None:
            stmt = stmt.where(Timeline.novel_id == novel_id)
        result = await self.session.execute(stmt.order_by(Timeline.tick.asc()))
        return list(result.scalars().all())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_timeline_repo.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/repositories/timeline_repo.py tests/test_repositories/test_timeline_repo.py
git commit -m "feat(timeline_repo): add list_between query method"
```

---

### Task 6: ContextAgent (Two-Step RAG)

**Files:**
- Modify: `src/novel_dev/agents/context_agent.py`
- Test: `tests/test_agents/test_context_agent.py` (确认或新增)

- [ ] **Step 1: Write the failing test**

确认 `tests/test_agents/test_context_agent.py` 是否存在。如果不存在，创建它并添加：

```python
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from novel_dev.agents.context_agent import ContextAgent
from novel_dev.schemas.context import ChapterPlan, BeatPlan, LocationContext
from novel_dev.llm.models import LLMResponse


@pytest.mark.asyncio
async def test_load_location_context(async_session):
    from novel_dev.repositories.spaceline_repo import SpacelineRepository
    from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
    from novel_dev.repositories.timeline_repo import TimelineRepository

    # 预设数据
    sp_repo = SpacelineRepository(async_session)
    await sp_repo.create(location_id="loc1", name="青云宗", novel_id="n_test")

    fs_repo = ForeshadowingRepository(async_session)
    await fs_repo.create(
        id="fs1", content="玉佩发光", 埋下_time_tick=1,
        相关人物_ids=[], novel_id="n_test"
    )

    tl_repo = TimelineRepository(async_session)
    await tl_repo.create(tick=1, narrative="入门测试", novel_id="n_test")

    # mock LLM 两次调用
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text='{"locations": ["青云宗"], "entities": ["林风"], "time_range": {"start_tick": -1, "end_tick": 1}, "foreshadowing_keywords": ["玉佩"]}'),
        LLMResponse(text='{"current": "青云宗大殿", "parent": "青云宗", "narrative": "晨光透过雕花窗棂，洒落在青石地面上..."}'),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = ContextAgent(async_session)
        plan = ChapterPlan(
            chapter_number=1, title="测试", target_word_count=3000,
            beats=[BeatPlan(summary="开场", target_mood="tense", key_entities=["林风"])]
        )
        result = await agent._load_location_context(plan, "n_test")

    assert result.current == "青云宗大殿"
    assert "晨光" in result.narrative
    assert mock_client.acomplete.call_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_context_agent.py::test_load_location_context -v`
Expected: FAIL (`_analyze_context_needs` / `_load_location_context` signature mismatch)

- [ ] **Step 3: Implement two-step RAG**

Replace `src/novel_dev/agents/context_agent.py`:

```python
import json
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.agents._llm_helpers import call_and_parse
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

        checkpoint = dict(state.checkpoint_data or {})
        chapter_plan_data = checkpoint.get("current_chapter_plan")
        if not chapter_plan_data:
            raise ValueError("current_chapter_plan missing in checkpoint_data")

        chapter_plan = ChapterPlan.model_validate(chapter_plan_data)

        key_entity_names = self._extract_key_entities_from_plan(chapter_plan)
        active_entities = await self._load_active_entities(key_entity_names, novel_id)
        location_context = await self._load_location_context(chapter_plan, novel_id)
        timeline_events = await self._load_timeline_events(checkpoint, novel_id)
        pending_foreshadowings = await self._load_foreshadowings(chapter_plan, active_entities, checkpoint, novel_id)
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
            volume_id=state.current_volume_id,
            chapter_id=state.current_chapter_id,
        )

        return context

    def _extract_key_entities_from_plan(self, chapter_plan: ChapterPlan) -> List[str]:
        names = set()
        for beat in chapter_plan.beats:
            names.update(beat.key_entities)
        return list(names)

    async def _load_active_entities(self, names: List[str], novel_id: str) -> List[EntityState]:
        if not names:
            return []
        entities = await self.entity_repo.find_by_names(names, novel_id=novel_id)
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

    async def _analyze_context_needs(self, chapter_plan: ChapterPlan, novel_id: str) -> dict:
        prompt = (
            "你是一位小说场景分析师。请根据以下章节计划，分析写这一章需要哪些上下文信息。\n"
            "返回严格 JSON：\n"
            "{\n"
            '  "locations": ["地点名1"],\n'
            '  "entities": ["实体名1"],\n'
            '  "time_range": {"start_tick": -3, "end_tick": 2},\n'
            '  "foreshadowing_keywords": ["关键词1"]\n'
            "}\n\n"
            "说明：\n"
            "- locations: 场景涉及的主要地点\n"
            "- entities: 需要知道最新状态的关键人物/物品（超出章节计划已有实体）\n"
            "- time_range: 相对于 current_tick 的时间范围\n"
            "- foreshadowing_keywords: 用于筛选相关伏笔的关键词\n\n"
            f"章节计划：\n{chapter_plan.model_dump_json()}"
        )
        return await call_and_parse(
            "ContextAgent", "analyze_context_needs", prompt,
            json.loads, max_retries=3
        )

    async def _load_location_context(
        self, chapter_plan: ChapterPlan, novel_id: str
    ) -> LocationContext:
        needs = await self._analyze_context_needs(chapter_plan, novel_id)

        location_names = needs.get("locations", [])
        locations = []
        if location_names:
            all_locs = await self.spaceline_repo.list_by_novel(novel_id)
            locations = [loc for loc in all_locs if loc.name in location_names]

        entity_names = list(set(
            needs.get("entities", []) + self._extract_key_entities_from_plan(chapter_plan)
        ))
        entity_states = []
        if entity_names:
            entities = await self.entity_repo.find_by_names(entity_names, novel_id=novel_id)
            for entity in entities:
                latest = await self.version_repo.get_latest(entity.id)
                entity_states.append({
                    "name": entity.name,
                    "type": entity.type,
                    "state": str(latest.state) if latest else "",
                })

        state = await self.state_repo.get_state(novel_id)
        current_tick = state.checkpoint_data.get("current_time_tick") if state else None
        timeline_events = []
        if current_tick is not None:
            time_range = needs.get("time_range", {})
            start = current_tick + time_range.get("start_tick", -2)
            end = current_tick + time_range.get("end_tick", 2)
            events = await self.timeline_repo.list_between(start, end, novel_id)
            timeline_events = [{"tick": e.tick, "narrative": e.narrative} for e in events]

        keywords = needs.get("foreshadowing_keywords", [])
        all_foreshadowings = await self.foreshadowing_repo.list_active(novel_id=novel_id)
        pending_fs = [
            {"id": fs.id, "content": fs.content}
            for fs in all_foreshadowings
            if any(kw in fs.content for kw in keywords) or not keywords
        ]

        prompt = (
            "你是一位导演，正在为下一幕戏撰写场景说明。请根据以下所有信息，"
            "写一段 200-300 字的场景镜头描述。这段文字将被直接交给小说家作为写作参考，"
            "所以请用具体、可感知的细节，不要抽象概括。必须包含：\n"
            "- 空间环境（地点、光线、声音、气味、天气等感官细节）\n"
            "- 时间状态（时辰、季节、时间推移感）\n"
            "- 在场人物（谁在场、他们在做什么、彼此的空间关系）\n"
            "- 物品线索（场景中有什么道具、伏笔物品、环境线索）\n"
            "- 情绪基调（压抑、紧张、欢快等，用氛围描写传达）\n"
            "- 与上一场景的衔接\n"
            "返回严格 JSON 格式：\n"
            "{\n"
            '  "current": "当前主要地点名称",\n'
            '  "parent": "上级地点/区域（如有）",\n'
            '  "narrative": "完整的场景镜头描述（200-300字）"\n'
            "}\n\n"
            f"地点：{[loc.model_dump() for loc in locations]}\n"
            f"实体状态：{entity_states}\n"
            f"近期时间线：{timeline_events}\n"
            f"待回收伏笔：{pending_fs}\n"
        )
        return await call_and_parse(
            "ContextAgent", "build_scene_context", prompt,
            LocationContext.model_validate_json, max_retries=3
        )

    async def _load_timeline_events(self, checkpoint: dict, novel_id: str) -> List[dict]:
        tick = checkpoint.get("current_time_tick")
        if tick is None:
            return []
        events = await self.timeline_repo.get_around_tick(tick, radius=3, novel_id=novel_id)
        return [{"tick": e.tick, "narrative": e.narrative} for e in events]

    async def _load_foreshadowings(
        self,
        chapter_plan: ChapterPlan,
        active_entities: List[EntityState],
        checkpoint: dict,
        novel_id: str,
    ) -> List[dict]:
        active_ids = {e.entity_id for e in active_entities}
        all_active = await self.foreshadowing_repo.list_active(novel_id=novel_id)
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_context_agent.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/context_agent.py tests/test_agents/test_context_agent.py
git commit -m "feat(context_agent): two-step rag for scene context with llm"
```

---

### Task 7: VolumePlannerAgent._generate_volume_plan

**Files:**
- Modify: `src/novel_dev/agents/volume_planner.py`
- Test: `tests/test_agents/test_volume_planner.py`

- [ ] **Step 1: Update test to mock initial generation**

在 `tests/test_agents/test_volume_planner.py` 的 `test_plan_volume_success` 中，`VolumePlannerAgent` 构造函数后的 `with patch` 块内，`mock_factory.get.return_value = mock_client` 之前添加：

```python
    # Mock initial generation
    initial_plan = VolumePlan(
        volume_id="vol_1",
        volume_number=1,
        title="第一卷",
        summary="卷总述",
        total_chapters=3,
        estimated_total_words=9000,
        chapters=[
            VolumeBeat(
                chapter_id="ch_1",
                chapter_number=1,
                title="第一章",
                summary="第一章剧情",
                target_word_count=3000,
                target_mood="tense",
                beats=[BeatPlan(summary="节拍1", target_mood="tense")],
            ),
            VolumeBeat(
                chapter_id="ch_2",
                chapter_number=2,
                title="第二章",
                summary="第二章剧情",
                target_word_count=3000,
                target_mood="tense",
                beats=[BeatPlan(summary="节拍2", target_mood="tense")],
            ),
            VolumeBeat(
                chapter_id="ch_3",
                chapter_number=3,
                title="第三章",
                summary="第三章剧情",
                target_word_count=3000,
                target_mood="tense",
                beats=[BeatPlan(summary="节拍3", target_mood="tense")],
            ),
        ],
    )
```

然后把 `mock_client.acomplete.return_value = LLMResponse(text=score_result.model_dump_json())` 改为：

```python
    mock_client.acomplete.side_effect = [
        LLMResponse(text=initial_plan.model_dump_json()),
        LLMResponse(text=score_result.model_dump_json()),
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_volume_planner.py::test_plan_volume_success -v`
Expected: FAIL (`_generate_volume_plan` is not async)

- [ ] **Step 3: Implement LLM-based `_generate_volume_plan()`**

Modify `src/novel_dev/agents/volume_planner.py`:

Replace `_generate_volume_plan` method:

```python
    async def _generate_volume_plan(
        self, synopsis: SynopsisData, volume_number: int
    ) -> VolumePlan:
        MAX_CHARS = 12000
        truncated_synopsis = synopsis.model_dump_json()[:MAX_CHARS]

        prompt = (
            "你是一位小说分卷规划专家。请根据以下大纲数据，"
            "生成一个完整的分卷规划 VolumePlan，返回严格符合 VolumePlan Schema 的 JSON。\n"
            "要求：\n"
            "1. 每章必须有有意义的标题和摘要，不能是'第X章'这种占位符\n"
            "2. 每章拆分为 2-4 个节拍（beats），每个节拍有明确的情节推进\n"
            "3. 章节之间要有连贯性，伏笔要合理分布\n"
            "4. 估算字数要合理\n\n"
            f"大纲数据：\n{truncated_synopsis}\n\n"
            f"当前卷号：{volume_number}"
        )
        return await call_and_parse(
            "VolumePlannerAgent", "generate_volume_plan", prompt,
            VolumePlan.model_validate_json, max_retries=3
        )
```

Add `await` in `plan()` method line 54:

```python
# 改前
volume_plan = self._generate_volume_plan(synopsis, volume_number)

# 改后
volume_plan = await self._generate_volume_plan(synopsis, volume_number)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_volume_planner.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/volume_planner.py tests/test_agents/test_volume_planner.py
git commit -m "feat(volume_planner): llm-driven initial volume plan generation"
```

---

### Task 8: llm_config.yaml

**Files:**
- Modify: `llm_config.yaml`

- [ ] **Step 1: Add agent configurations**

在 `llm_config.yaml` 的 `agents:` 下添加：

```yaml
  setting_extractor_agent:
    provider: openai_compatible
    model: kimi-k2.5
    base_url: https://api.moonshot.cn/v1
    timeout: 60
    fallback:
      provider: anthropic
      model: claude-sonnet-4-6
      timeout: 60

  style_profiler_agent:
    provider: openai_compatible
    model: kimi-k2.5
    base_url: https://api.moonshot.cn/v1
    timeout: 60
    fallback:
      provider: anthropic
      model: claude-sonnet-4-6
      timeout: 60

  file_classifier:
    provider: openai_compatible
    model: kimi-k2.5
    base_url: https://api.moonshot.cn/v1
    timeout: 30
    fallback:
      provider: anthropic
      model: claude-haiku-4-5-20251001
      timeout: 30

  context_agent:
    provider: openai_compatible
    model: kimi-k2.5
    base_url: https://api.moonshot.cn/v1
    timeout: 30
    fallback:
      provider: anthropic
      model: claude-haiku-4-5-20251001
      timeout: 30

  volume_planner_agent:
    tasks:
      generate_volume_plan:
        timeout: 120
        retries: 3
```

- [ ] **Step 2: Validate config**

Run: `PYTHONPATH=src python3.11 -c "from novel_dev.llm.factory import LLMFactory; from novel_dev.config import Settings; f = LLMFactory(Settings()); f.get('SettingExtractorAgent', 'extract_setting'); f.get('StyleProfilerAgent', 'profile_style'); f.get('FileClassifier', 'classify_file'); f.get('ContextAgent', 'analyze_context_needs'); f.get('ContextAgent', 'build_scene_context'); f.get('VolumePlannerAgent', 'generate_volume_plan'); print('Config OK')"`
Expected: `Config OK`

- [ ] **Step 3: Commit**

```bash
git add llm_config.yaml
git commit -m "config(llm): add placeholder agent configurations with fallback"
```

---

### Task 9: Final Full Test Run

**Files:**
- All existing tests

- [ ] **Step 1: Run the entire test suite**

Run: `PYTHONPATH=src python3.11 -m pytest tests/ -q --tb=short`
Expected: 203+ passed (or more, depending on new tests), 0 failed

- [ ] **Step 2: Commit if any lingering changes**

```bash
git status
# If clean, nothing to do
```

---

## Self-Review

1. **Spec coverage：**
   - `_llm_helpers.py` → Task 1
   - `SettingExtractorAgent` → Task 2
   - `StyleProfilerAgent` → Task 3
   - `FileClassifier` → Task 4
   - `TimelineRepository.list_between` → Task 5
   - `ContextAgent` two-step RAG → Task 6
   - `VolumePlannerAgent` → Task 7
   - `llm_config.yaml` → Task 8

2. **Placeholder scan：** 所有步骤包含完整代码、完整命令、预期输出，无 TBD。

3. **Type consistency：**
   - `FileClassifier.classify()` 从 `def` → `async def`
   - `VolumePlannerAgent._generate_volume_plan()` 从 `def` → `async def`
   - `ContextAgent._load_location_context()` 参数从 `names, novel_id` → `chapter_plan, novel_id`
   - 调用方均已标注 `await` 改动
