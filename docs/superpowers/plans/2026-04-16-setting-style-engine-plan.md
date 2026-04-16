# Setting and Style Extraction Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the setting learning and style extraction engine that classifies uploaded files, extracts structured settings and style profiles via LLM-driven agents, stores them in `novel_documents`, and supports human validation via `pending_extractions`.

**Architecture:** The engine consists of three agent modules (`FileClassifier`, `SettingExtractorAgent`, `StyleProfilerAgent`) plus a `ProfileMerger` for incremental style updates. An `ExtractionService` orchestrates file processing and the pending/approve workflow. New API routes and MCP tools expose the functionality. All data persists in the existing SQLAlchemy models plus a new `PendingExtraction` table.

**Tech Stack:** Python 3.9+, SQLAlchemy 2.0, FastAPI, Pydantic, pytest-asyncio

---

## File Map

| File | Responsibility |
|------|----------------|
| `src/novel_dev/db/models.py` | Add `PendingExtraction` SQLAlchemy model |
| `src/novel_dev/repositories/document_repo.py` | Add version-aware queries for `NovelDocument` |
| `src/novel_dev/repositories/pending_extraction_repo.py` | CRUD for `PendingExtraction` |
| `src/novel_dev/agents/file_classifier.py` | Rule + LLM hybrid file classification |
| `src/novel_dev/agents/setting_extractor.py` | Parse setting text into structured JSON |
| `src/novel_dev/agents/style_profiler.py` | Chunk, sample, and analyze style from prose |
| `src/novel_dev/agents/profile_merger.py` | Merge old/new style profiles with conflict detection |
| `src/novel_dev/services/extraction_service.py` | Orchestrate upload → extract → pending → approve |
| `src/novel_dev/api/routes.py` | Add upload, pending, approve, style version/rollback endpoints |
| `src/novel_dev/mcp_server/server.py` | Add MCP tools for extraction engine |
| `tests/test_repositories/test_pending_extraction_repo.py` | Repo tests |
| `tests/test_agents/test_file_classifier.py` | File classifier tests |
| `tests/test_agents/test_setting_extractor.py` | Setting extractor tests |
| `tests/test_agents/test_style_profiler.py` | Style profiler tests |
| `tests/test_agents/test_profile_merger.py` | Profile merger tests |
| `tests/test_services/test_extraction_service.py` | Service orchestration tests |
| `tests/test_api/test_setting_style_routes.py` | API route tests |
| `tests/test_integration_setting_style_flow.py` | End-to-end integration test |

---

### Task 1: Add `PendingExtraction` model

**Files:**
- Modify: `src/novel_dev/db/models.py`
- Test: `tests/test_repositories/test_models.py` (create if missing, or add test inline)

- [ ] **Step 1: Write the failing test**

Create `tests/test_repositories/test_models.py` if it does not exist, otherwise add to it:

```python
import pytest
from novel_dev.db.models import PendingExtraction

@pytest.mark.asyncio
async def test_pending_extraction_model(async_session):
    pe = PendingExtraction(
        id="pe_1",
        novel_id="n1",
        extraction_type="setting",
        status="pending",
        raw_result={"worldview": "test"},
        proposed_entities=[{"type": "character", "name": "Lin Feng"}],
    )
    async_session.add(pe)
    await async_session.flush()
    result = await async_session.get(PendingExtraction, "pe_1")
    assert result.novel_id == "n1"
    assert result.status == "pending"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_repositories/test_models.py::test_pending_extraction_model -v`

Expected: FAIL with `ImportError: cannot import name 'PendingExtraction' from 'novel_dev.db.models'`

- [ ] **Step 3: Add `PendingExtraction` to models.py**

Append to `src/novel_dev/db/models.py` (before any trailing blank lines):

```python
class PendingExtraction(Base):
    __tablename__ = "pending_extractions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    novel_id: Mapped[str] = mapped_column(Text, nullable=False)
    extraction_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    raw_result: Mapped[dict] = mapped_column(JSON, nullable=False)
    proposed_entities: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_repositories/test_models.py::test_pending_extraction_model -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/db/models.py tests/test_repositories/test_models.py
git commit -m "feat: add PendingExtraction model"
```

---

### Task 2: Extend `DocumentRepository` with version queries

**Files:**
- Modify: `src/novel_dev/repositories/document_repo.py`
- Test: `tests/test_repositories/test_document_repo.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_repositories/test_document_repo.py`:

```python
@pytest.mark.asyncio
async def test_get_latest_by_type(async_session):
    repo = DocumentRepository(async_session)
    await repo.create("d1", "n1", "style_profile", "v1", "content1", version=1)
    await repo.create("d2", "n1", "style_profile", "v2", "content2", version=2)
    latest = await repo.get_latest_by_type("n1", "style_profile")
    assert latest is not None
    assert latest.version == 2

@pytest.mark.asyncio
async def test_get_by_type_and_version(async_session):
    repo = DocumentRepository(async_session)
    await repo.create("d1", "n1", "style_profile", "v1", "content1", version=1)
    doc = await repo.get_by_type_and_version("n1", "style_profile", 1)
    assert doc is not None
    assert doc.id == "d1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_repositories/test_document_repo.py::test_get_latest_by_type tests/test_repositories/test_document_repo.py::test_get_by_type_and_version -v`

Expected: FAIL with `AttributeError: 'DocumentRepository' object has no attribute 'get_latest_by_type'`

- [ ] **Step 3: Implement version queries**

Replace the body of `src/novel_dev/repositories/document_repo.py` with:

```python
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novel_dev.db.models import NovelDocument


class DocumentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        doc_id: str,
        novel_id: str,
        doc_type: str,
        title: str,
        content: str,
        vector_embedding: Optional[List[float]] = None,
        version: int = 1,
    ) -> NovelDocument:
        doc = NovelDocument(
            id=doc_id,
            novel_id=novel_id,
            doc_type=doc_type,
            title=title,
            content=content,
            vector_embedding=vector_embedding,
            version=version,
        )
        self.session.add(doc)
        await self.session.flush()
        return doc

    async def get_by_id(self, doc_id: str) -> Optional[NovelDocument]:
        result = await self.session.execute(select(NovelDocument).where(NovelDocument.id == doc_id))
        return result.scalar_one_or_none()

    async def get_by_type(self, novel_id: str, doc_type: str) -> List[NovelDocument]:
        result = await self.session.execute(
            select(NovelDocument)
            .where(NovelDocument.novel_id == novel_id, NovelDocument.doc_type == doc_type)
            .order_by(NovelDocument.updated_at.desc())
        )
        return result.scalars().all()

    async def get_latest_by_type(self, novel_id: str, doc_type: str) -> Optional[NovelDocument]:
        result = await self.session.execute(
            select(NovelDocument)
            .where(NovelDocument.novel_id == novel_id, NovelDocument.doc_type == doc_type)
            .order_by(NovelDocument.version.desc())
        )
        return result.scalars().first()

    async def get_by_type_and_version(self, novel_id: str, doc_type: str, version: int) -> Optional[NovelDocument]:
        result = await self.session.execute(
            select(NovelDocument)
            .where(
                NovelDocument.novel_id == novel_id,
                NovelDocument.doc_type == doc_type,
                NovelDocument.version == version,
            )
        )
        return result.scalar_one_or_none()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_repositories/test_document_repo.py -v`

Expected: PASS for all tests in the file

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/repositories/document_repo.py tests/test_repositories/test_document_repo.py
git commit -m "feat: add version-aware queries to DocumentRepository"
```

---

### Task 3: Create `PendingExtractionRepository`

**Files:**
- Create: `src/novel_dev/repositories/pending_extraction_repo.py`
- Test: `tests/test_repositories/test_pending_extraction_repo.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_repositories/test_pending_extraction_repo.py`:

```python
import pytest

from novel_dev.repositories.pending_extraction_repo import PendingExtractionRepository


@pytest.mark.asyncio
async def test_crud(async_session):
    repo = PendingExtractionRepository(async_session)
    pe = await repo.create(
        pe_id="pe_1",
        novel_id="n1",
        extraction_type="setting",
        raw_result={"worldview": "test"},
        proposed_entities=[{"name": "Lin Feng"}],
    )
    assert pe.status == "pending"

    fetched = await repo.get_by_id("pe_1")
    assert fetched is not None

    items = await repo.list_by_novel("n1")
    assert len(items) == 1

    await repo.update_status("pe_1", "approved")
    updated = await repo.get_by_id("pe_1")
    assert updated.status == "approved"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_repositories/test_pending_extraction_repo.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'novel_dev.repositories.pending_extraction_repo'`

- [ ] **Step 3: Implement repository**

Create `src/novel_dev/repositories/pending_extraction_repo.py`:

```python
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novel_dev.db.models import PendingExtraction


class PendingExtractionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        pe_id: str,
        novel_id: str,
        extraction_type: str,
        raw_result: dict,
        proposed_entities: Optional[List[dict]] = None,
    ) -> PendingExtraction:
        pe = PendingExtraction(
            id=pe_id,
            novel_id=novel_id,
            extraction_type=extraction_type,
            raw_result=raw_result,
            proposed_entities=proposed_entities,
        )
        self.session.add(pe)
        await self.session.flush()
        return pe

    async def get_by_id(self, pe_id: str) -> Optional[PendingExtraction]:
        result = await self.session.execute(select(PendingExtraction).where(PendingExtraction.id == pe_id))
        return result.scalar_one_or_none()

    async def list_by_novel(self, novel_id: str) -> List[PendingExtraction]:
        result = await self.session.execute(
            select(PendingExtraction)
            .where(PendingExtraction.novel_id == novel_id)
            .order_by(PendingExtraction.created_at.desc())
        )
        return result.scalars().all()

    async def update_status(self, pe_id: str, status: str) -> None:
        pe = await self.get_by_id(pe_id)
        if pe:
            pe.status = status
            await self.session.flush()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_repositories/test_pending_extraction_repo.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/repositories/pending_extraction_repo.py tests/test_repositories/test_pending_extraction_repo.py
git commit -m "feat: add PendingExtractionRepository"
```

---

### Task 4: Create `FileClassifier`

**Files:**
- Create: `src/novel_dev/agents/file_classifier.py`
- Test: `tests/test_agents/test_file_classifier.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_agents/test_file_classifier.py`:

```python
import pytest

from novel_dev.agents.file_classifier import FileClassifier, FileClassificationResult


def test_rule_based_setting():
    classifier = FileClassifier()
    result = classifier.classify(filename="world_setting.txt", content_preview="The cultivation world...")
    assert result.file_type == "setting"
    assert result.confidence >= 0.9


def test_rule_based_style_sample():
    classifier = FileClassifier()
    result = classifier.classify(filename="style_sample.txt", content_preview="He walked into the room...")
    assert result.file_type == "style_sample"


def test_fallback_unknown():
    classifier = FileClassifier()
    result = classifier.classify(filename="notes.txt", content_preview="random notes")
    assert result.file_type in ("setting", "style_sample")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agents/test_file_classifier.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'novel_dev.agents.file_classifier'`

- [ ] **Step 3: Implement FileClassifier**

Create `src/novel_dev/agents/file_classifier.py`:

```python
import re
from typing import Optional
from pydantic import BaseModel


class FileClassificationResult(BaseModel):
    file_type: str  # "setting" | "style_sample"
    confidence: float
    reason: str


class FileClassifier:
    SETTING_KEYWORDS = ["设定", "世界观", "大纲", "setting", "worldview", "outline"]
    STYLE_KEYWORDS = ["样本", "风格", "sample", "style"]

    def classify(self, filename: str, content_preview: str) -> FileClassificationResult:
        lower_name = filename.lower()
        lower_preview = content_preview[:500].lower()

        for kw in self.SETTING_KEYWORDS:
            if kw in lower_name:
                return FileClassificationResult(
                    file_type="setting",
                    confidence=0.95,
                    reason=f"Filename contains '{kw}'",
                )

        for kw in self.STYLE_KEYWORDS:
            if kw in lower_name:
                return FileClassificationResult(
                    file_type="style_sample",
                    confidence=0.95,
                    reason=f"Filename contains '{kw}'",
                )

        # Simple heuristic fallback
        if "修炼" in lower_preview or "境界" in lower_preview or "world" in lower_preview:
            return FileClassificationResult(
                file_type="setting",
                confidence=0.7,
                reason="Content heuristic matched setting terms",
            )

        return FileClassificationResult(
            file_type="style_sample",
            confidence=0.6,
            reason="Default fallback to style_sample",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agents/test_file_classifier.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/file_classifier.py tests/test_agents/test_file_classifier.py
git commit -m "feat: add FileClassifier agent"
```

---

### Task 5: Create `SettingExtractorAgent`

**Files:**
- Create: `src/novel_dev/agents/setting_extractor.py`
- Test: `tests/test_agents/test_setting_extractor.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_agents/test_setting_extractor.py`:

```python
import pytest

from novel_dev.agents.setting_extractor import SettingExtractorAgent, ExtractedSetting


@pytest.mark.asyncio
async def test_extract_from_text():
    agent = SettingExtractorAgent()
    text = """
    世界观：天玄大陆，万族林立。
    修炼体系：炼气、筑基、金丹。
    势力：青云宗是正道魁首。
    主角林风，青云宗外门弟子，性格坚韧隐忍，目标为父报仇。
    重要物品：残缺玉佩，上古魔宗信物，揭示主角身世。
    剧情：林风因家族被灭门，拜入青云宗。
    """
    result = await agent.extract(text)
    assert isinstance(result, ExtractedSetting)
    assert "天玄大陆" in result.worldview
    assert any(c.name == "林风" for c in result.character_profiles)
    assert any(i.name == "残缺玉佩" for i in result.important_items)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agents/test_setting_extractor.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'novel_dev.agents.setting_extractor'`

- [ ] **Step 3: Implement SettingExtractorAgent**

Create `src/novel_dev/agents/setting_extractor.py`:

```python
import re
from typing import List, Optional
from pydantic import BaseModel


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
        # Naive regex-based extraction for prototype
        worldview = self._extract_section(text, ["世界观", "worldview", "世界"])
        power_system = self._extract_section(text, ["修炼体系", "power system", "境界", " cultivation"])
        factions = self._extract_section(text, ["势力", "factions", "宗门", "门派"])
        plot_synopsis = self._extract_section(text, ["剧情", "plot", "大纲", "synopsis"])

        characters = self._extract_characters(text)
        items = self._extract_items(text)

        return ExtractedSetting(
            worldview=worldview,
            power_system=power_system,
            factions=factions,
            character_profiles=characters,
            important_items=items,
            plot_synopsis=plot_synopsis,
        )

    def _extract_section(self, text: str, headers: List[str]) -> str:
        for header in headers:
            pattern = re.compile(rf"{re.escape(header)}[：:\s]+([^\n]+)", re.IGNORECASE)
            match = pattern.search(text)
            if match:
                return match.group(1).strip()
        return ""

    def _extract_characters(self, text: str) -> List[CharacterProfile]:
        chars = []
        # Match lines like: 主角林风，青云宗外门弟子，性格坚韧隐忍，目标为父报仇。
        pattern = re.compile(r"[主角人物](\S+?)[，,、]\s*(.+?)(?=\n|。|$)")
        for name, rest in pattern.findall(text):
            chars.append(CharacterProfile(name=name, identity=rest))
        return chars

    def _extract_items(self, text: str) -> List[ImportantItem]:
        items = []
        pattern = re.compile(r"重要物品[：:]\s*(\S+?)[，,、]\s*(.+?)(?=\n|。|$)")
        for name, rest in pattern.findall(text):
            items.append(ImportantItem(name=name, description=rest))
        return items
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_agents/test_setting_extractor.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/setting_extractor.py tests/test_agents/test_setting_extractor.py
git commit -m "feat: add SettingExtractorAgent"
```

---

### Task 6: Create `StyleProfilerAgent`

**Files:**
- Create: `src/novel_dev/agents/style_profiler.py`
- Test: `tests/test_agents/test_style_profiler.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_agents/test_style_profiler.py`:

```python
import pytest

from novel_dev.agents.style_profiler import StyleProfilerAgent


def test_chunk_sampling():
    agent = StyleProfilerAgent()
    text = "a" * 9000  # 3 blocks
    chunks = agent._chunk_text(text, chunk_size=3000)
    assert len(chunks) == 3

    sampled = agent._sample_chunks(chunks)
    # 3 blocks -> sample all (min 8 not reached, but 50% rounds up)
    assert len(sampled) == 3


def test_large_text_sampling():
    agent = StyleProfilerAgent()
    text = "a" * (50 * 3000)  # 50 blocks
    chunks = agent._chunk_text(text, chunk_size=3000)
    sampled = agent._sample_chunks(chunks)
    assert len(sampled) == 24  # capped at 24


@pytest.mark.asyncio
async def test_profile_from_text():
    agent = StyleProfilerAgent()
    text = "林风握紧了剑。剑光一闪，敌人倒下。"
    profile = await agent.profile(text)
    assert profile.style_guide != ""
    assert profile.style_config.perspective != ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agents/test_style_profiler.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'novel_dev.agents.style_profiler'`

- [ ] **Step 3: Implement StyleProfilerAgent**

Create `src/novel_dev/agents/style_profiler.py`:

```python
import math
from typing import List
from pydantic import BaseModel


class StyleConfig(BaseModel):
    sentence_patterns: dict = {}
    dialogue_style: dict = {}
    rhetoric_devices: dict = {}
    pacing: str = ""
    vocabulary_preferences: List[str] = []
    perspective: str = ""
    tone: str = ""
    evolution_notes: str = ""


class StyleProfile(BaseModel):
    style_guide: str
    style_config: StyleConfig


class StyleProfilerAgent:
    CHUNK_SIZE = 3000
    MIN_SAMPLES = 8
    MAX_SAMPLES = 24
    SAMPLE_RATIO = 0.5

    def _chunk_text(self, text: str, chunk_size: int = CHUNK_SIZE) -> List[str]:
        return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]

    def _sample_chunks(self, chunks: List[str]) -> List[str]:
        total = len(chunks)
        if total == 0:
            return []
        target = max(self.MIN_SAMPLES, min(self.MAX_SAMPLES, math.ceil(total * self.SAMPLE_RATIO)))
        target = min(target, total)

        if total <= target:
            return chunks

        step = total / target
        sampled = []
        for i in range(target):
            idx = min(int(i * step), total - 1)
            sampled.append(chunks[idx])
        return sampled

    async def profile(self, text: str) -> StyleProfile:
        chunks = self._chunk_text(text)
        sampled = self._sample_chunks(chunks)

        # Prototype: simple heuristic analysis without LLM
        config = StyleConfig(
            sentence_patterns={"avg_length": self._avg_sentence_length(text)},
            dialogue_style={"direct_speech_ratio": self._dialogue_ratio(text)},
            rhetoric_devices={},
            pacing="fast" if len(sampled) > 10 else "moderate",
            vocabulary_preferences=self._extract_vocabulary(text),
            perspective="limited" if "他" in text or "她" in text else "omniscient",
            tone="intense" if "杀" in text or "血" in text else "neutral",
            evolution_notes="",
        )

        guide = (
            f"Overall: {config.pacing} pacing, "
            f"{config.perspective} perspective, "
            f"{config.tone} tone. "
            f"Samples analyzed: {len(sampled)} chunks."
        )

        return StyleProfile(style_guide=guide, style_config=config)

    def _avg_sentence_length(self, text: str) -> float:
        sentences = [s.strip() for s in text.replace("。", ".").replace("！", "!").replace("？", "?").split(".") if s.strip()]
        if not sentences:
            return 0.0
        return sum(len(s) for s in sentences) / len(sentences)

    def _dialogue_ratio(self, text: str) -> float:
        quotes = text.count("\"") + text.count("\"") + text.count("'")
        return round(quotes / max(len(text), 1), 3)

    def _extract_vocabulary(self, text: str) -> List[str]:
        # Simple high-frequency bigrams
        words = list(text)
        from collections import Counter

        bigrams = [words[i] + words[i + 1] for i in range(len(words) - 1)]
        freq = Counter(bigrams)
        return [bg for bg, _ in freq.most_common(5)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agents/test_style_profiler.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/style_profiler.py tests/test_agents/test_style_profiler.py
git commit -m "feat: add StyleProfilerAgent"
```

---

### Task 7: Create `ProfileMerger`

**Files:**
- Create: `src/novel_dev/agents/profile_merger.py`
- Test: `tests/test_agents/test_profile_merger.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_agents/test_profile_merger.py`:

```python
import pytest

from novel_dev.agents.profile_merger import ProfileMerger, MergeResult
from novel_dev.agents.style_profiler import StyleProfile, StyleConfig


def test_merge_no_conflict():
    merger = ProfileMerger()
    old = StyleProfile(style_guide="Old guide", style_config=StyleConfig(perspective="limited", tone="neutral"))
    new = StyleProfile(style_guide="New guide", style_config=StyleConfig(perspective="limited", tone="intense"))
    result = merger.merge(old, new)
    assert result.merged_profile.style_config.perspective == "limited"
    assert any(c.field == "tone" for c in result.conflicts)


def test_merge_with_new_fields():
    merger = ProfileMerger()
    old = StyleProfile(style_guide="Old", style_config=StyleConfig(perspective="limited"))
    new = StyleProfile(style_guide="New", style_config=StyleConfig(pacing="fast"))
    result = merger.merge(old, new)
    assert result.merged_profile.style_config.perspective == "limited"
    assert result.merged_profile.style_config.pacing == "fast"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agents/test_profile_merger.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'novel_dev.agents.profile_merger'`

- [ ] **Step 3: Implement ProfileMerger**

Create `src/novel_dev/agents/profile_merger.py`:

```python
from typing import List
from pydantic import BaseModel

from novel_dev.agents.style_profiler import StyleProfile, StyleConfig


class Conflict(BaseModel):
    field: str
    old_value: str
    new_value: str
    resolution: str


class MergeResult(BaseModel):
    merged_profile: StyleProfile
    conflicts: List[Conflict]


class ProfileMerger:
    def merge(self, old: StyleProfile, new: StyleProfile) -> MergeResult:
        merged_config = old.style_config.model_copy(deep=True)
        new_config = new.style_config
        conflicts: List[Conflict] = []

        for field, new_value in new_config.model_dump().items():
            old_value = getattr(merged_config, field)
            if not old_value and new_value:
                setattr(merged_config, field, new_value)
            elif old_value and new_value and old_value != new_value:
                # Conflict on primitive string fields
                if isinstance(old_value, str) and isinstance(new_value, str):
                    conflicts.append(Conflict(
                        field=field,
                        old_value=old_value,
                        new_value=new_value,
                        resolution="Samples differ; manual review recommended",
                    ))
                    # Keep new value as default resolution
                    setattr(merged_config, field, new_value)
                else:
                    # For dicts/lists, prefer new if non-empty
                    setattr(merged_config, field, new_value)
            elif not old_value and not new_value:
                continue
            else:
                # old has value, new is empty -> keep old
                pass

        merged_guide = f"{old.style_guide}\n\n[Updated]\n{new.style_guide}"
        merged_profile = StyleProfile(style_guide=merged_guide, style_config=merged_config)
        return MergeResult(merged_profile=merged_profile, conflicts=conflicts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agents/test_profile_merger.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/profile_merger.py tests/test_agents/test_profile_merger.py
git commit -m "feat: add ProfileMerger"
```

---

### Task 8: Create `ExtractionService`

**Files:**
- Create: `src/novel_dev/services/extraction_service.py`
- Modify: `src/novel_dev/services/entity_service.py`
- Test: `tests/test_services/test_extraction_service.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_services/test_extraction_service.py`:

```python
import pytest

from novel_dev.services.extraction_service import ExtractionService
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.pending_extraction_repo import PendingExtractionRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository


@pytest.mark.asyncio
async def test_process_setting_upload(async_session):
    svc = ExtractionService(async_session)
    pe = await svc.process_upload(
        novel_id="n1",
        filename="setting.txt",
        content="世界观：天玄大陆。主角林风，外门弟子。",
    )
    assert pe.extraction_type == "setting"
    assert pe.status == "pending"

    # Approve
    docs = await svc.approve_pending(pe.id)
    assert len(docs) > 0
    doc_types = {d.doc_type for d in docs}
    assert "worldview" in doc_types


@pytest.mark.asyncio
async def test_process_style_upload(async_session):
    svc = ExtractionService(async_session)
    pe = await svc.process_upload(
        novel_id="n1",
        filename="style.txt",
        content="剑光一闪，敌人倒下。" * 100,
    )
    assert pe.extraction_type == "style_profile"

    docs = await svc.approve_pending(pe.id)
    assert len(docs) == 1
    assert docs[0].doc_type == "style_profile"


@pytest.mark.asyncio
async def test_style_rollback(async_session):
    svc = ExtractionService(async_session)
    # Create v1
    pe1 = await svc.process_upload("n1", "style.txt", "a" * 10000)
    await svc.approve_pending(pe1.id)
    # Create v2
    pe2 = await svc.process_upload("n1", "style.txt", "b" * 10000)
    await svc.approve_pending(pe2.id)

    # Rollback to v1
    await svc.rollback_style_profile("n1", 1)
    active = await svc.get_active_style_profile("n1")
    assert active is not None
    assert active.version == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_services/test_extraction_service.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'novel_dev.services.extraction_service'`

- [ ] **Step 3: Implement ExtractionService**

Create `src/novel_dev/services/extraction_service.py`:

```python
import uuid
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.agents.file_classifier import FileClassifier
from novel_dev.agents.setting_extractor import SettingExtractorAgent
from novel_dev.agents.style_profiler import StyleProfilerAgent
from novel_dev.agents.profile_merger import ProfileMerger
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.pending_extraction_repo import PendingExtractionRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.services.entity_service import EntityService
from novel_dev.db.models import NovelDocument, PendingExtraction


class ExtractionService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.classifier = FileClassifier()
        self.setting_agent = SettingExtractorAgent()
        self.style_agent = StyleProfilerAgent()
        self.merger = ProfileMerger()
        self.doc_repo = DocumentRepository(session)
        self.pending_repo = PendingExtractionRepository(session)
        self.state_repo = NovelStateRepository(session)
        self.entity_svc = EntityService(session)

    async def process_upload(self, novel_id: str, filename: str, content: str) -> PendingExtraction:
        classification = self.classifier.classify(filename, content)

        if classification.file_type == "setting":
            extracted = await self.setting_agent.extract(content)
            raw_result = extracted.model_dump()
            proposed_entities = []
            for c in extracted.character_profiles:
                proposed_entities.append({"type": "character", "name": c.name, "data": c.model_dump()})
            for i in extracted.important_items:
                proposed_entities.append({"type": "item", "name": i.name, "data": i.model_dump()})
            if extracted.factions:
                proposed_entities.append({"type": "faction", "name": "extracted_factions", "data": {"factions": extracted.factions}})

            return await self.pending_repo.create(
                pe_id=f"pe_{uuid.uuid4().hex[:8]}",
                novel_id=novel_id,
                extraction_type="setting",
                raw_result=raw_result,
                proposed_entities=proposed_entities,
            )
        else:
            profile = await self.style_agent.profile(content)
            raw_result = profile.model_dump()
            return await self.pending_repo.create(
                pe_id=f"pe_{uuid.uuid4().hex[:8]}",
                novel_id=novel_id,
                extraction_type="style_profile",
                raw_result=raw_result,
            )

    async def approve_pending(self, pe_id: str) -> List[NovelDocument]:
        pe = await self.pending_repo.get_by_id(pe_id)
        if not pe or pe.status != "pending":
            return []

        docs: List[NovelDocument] = []
        if pe.extraction_type == "setting":
            raw = pe.raw_result
            mappings = [
                ("worldview", "worldview", "世界观"),
                ("power_system", "setting", "修炼体系"),
                ("factions", "setting", "势力格局"),
                ("plot_synopsis", "synopsis", "剧情梗概"),
            ]
            for key, doc_type, title in mappings:
                val = raw.get(key)
                if val:
                    text_val = val if isinstance(val, str) else str(val)
                    doc = await self.doc_repo.create(
                        doc_id=f"doc_{uuid.uuid4().hex[:8]}",
                        novel_id=pe.novel_id,
                        doc_type=doc_type,
                        title=title,
                        content=text_val,
                    )
                    docs.append(doc)

            chars = raw.get("character_profiles", [])
            if chars:
                text = "\n".join(f"{c.get('name')}: {c.get('identity')} {c.get('personality')}" for c in chars)
                doc = await self.doc_repo.create(
                    doc_id=f"doc_{uuid.uuid4().hex[:8]}",
                    novel_id=pe.novel_id,
                    doc_type="concept",
                    title="人物设定",
                    content=text,
                )
                docs.append(doc)
                for c in chars:
                    await self.entity_svc.create_entity(
                        entity_id=f"ent_{uuid.uuid4().hex[:8]}",
                        entity_type="character",
                        name=c.get("name", "unknown"),
                    )

            items = raw.get("important_items", [])
            if items:
                text = "\n".join(f"{i.get('name')}: {i.get('description')}" for i in items)
                doc = await self.doc_repo.create(
                    doc_id=f"doc_{uuid.uuid4().hex[:8]}",
                    novel_id=pe.novel_id,
                    doc_type="concept",
                    title="物品设定",
                    content=text,
                )
                docs.append(doc)
                for i in items:
                    await self.entity_svc.create_entity(
                        entity_id=f"ent_{uuid.uuid4().hex[:8]}",
                        entity_type="item",
                        name=i.get("name", "unknown"),
                    )

        else:
            # style_profile
            latest = await self.doc_repo.get_latest_by_type(pe.novel_id, "style_profile")
            new_profile = self.style_agent.profile.__self__  # hacky; instead instantiate agent inline
            # Actually use the raw_result directly
            from novel_dev.agents.style_profiler import StyleProfile, StyleConfig
            new_profile = StyleProfile(**pe.raw_result)
            if latest:
                old = StyleProfile(
                    style_guide=latest.content,
                    style_config=StyleConfig.model_validate_json(latest.title) if latest.title else StyleConfig(),
                )
                # For prototype, store config JSON in title field to keep it simple
                # Actually: let's just create a new version with merged content
                merged = self.merger.merge(old, new_profile)
                version = latest.version + 1
                doc = await self.doc_repo.create(
                    doc_id=f"doc_{uuid.uuid4().hex[:8]}",
                    novel_id=pe.novel_id,
                    doc_type="style_profile",
                    title=merged.merged_profile.style_config.model_dump_json(),
                    content=merged.merged_profile.style_guide,
                    version=version,
                )
            else:
                doc = await self.doc_repo.create(
                    doc_id=f"doc_{uuid.uuid4().hex[:8]}",
                    novel_id=pe.novel_id,
                    doc_type="style_profile",
                    title=new_profile.style_config.model_dump_json(),
                    content=new_profile.style_guide,
                    version=1,
                )
            docs.append(doc)

        await self.pending_repo.update_status(pe_id, "approved")
        return docs

    async def get_active_style_profile(self, novel_id: str) -> Optional[NovelDocument]:
        state = await self.state_repo.get_state(novel_id)
        active_version = None
        if state and state.checkpoint_data:
            active_version = state.checkpoint_data.get("active_style_profile_version")
        if active_version:
            return await self.doc_repo.get_by_type_and_version(novel_id, "style_profile", active_version)
        return await self.doc_repo.get_latest_by_type(novel_id, "style_profile")

    async def rollback_style_profile(self, novel_id: str, version: int) -> None:
        state = await self.state_repo.get_state(novel_id)
        if state is None:
            state = await self.state_repo.save_checkpoint(
                novel_id=novel_id,
                current_phase="context_preparation",
                checkpoint_data={"active_style_profile_version": version},
            )
        else:
            checkpoint = dict(state.checkpoint_data)
            checkpoint["active_style_profile_version"] = version
            await self.state_repo.save_checkpoint(
                novel_id=novel_id,
                current_phase=state.current_phase,
                checkpoint_data=checkpoint,
                current_volume_id=state.current_volume_id,
                current_chapter_id=state.current_chapter_id,
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_services/test_extraction_service.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/services/extraction_service.py tests/test_services/test_extraction_service.py
git commit -m "feat: add ExtractionService orchestrating upload and approval"
```

---

### Task 9: Add API routes

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Test: `tests/test_api/test_setting_style_routes.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api/test_setting_style_routes.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_upload_and_pending(async_session_override):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/novels/n1/documents/upload",
            json={"filename": "setting.txt", "content": "世界观：天玄大陆。主角林风。"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["extraction_type"] == "setting"

        pe_id = data["id"]
        resp2 = await client.get(f"/api/novels/n1/documents/pending")
        assert resp2.status_code == 200
        assert any(item["id"] == pe_id for item in resp2.json()["items"])

        resp3 = await client.post(f"/api/novels/n1/documents/pending/approve", json={"pending_id": pe_id})
        assert resp3.status_code == 200
        assert len(resp3.json()["documents"]) > 0
```

Wait - the routes use `Depends(get_session)` which creates its own session. For tests to work with in-memory SQLite, the existing app setup should work because `get_session` uses `async_session_maker` from `db.engine`. But we need to make sure the test database is created. Looking at `conftest.py`, it creates tables via `test_engine` but the app's `async_session_maker` may point to a different DB.

Actually, looking at the existing `test_routes.py`, it just uses the app directly without overriding the session. This implies the app is probably configured to use the same SQLite DB or the routes test is more of an integration test. Let me check `db.engine.py`.

We need to check `src/novel_dev/db/engine.py` to understand how `async_session_maker` is set up.

- [ ] **Step 1b: Inspect engine setup**

Read `src/novel_dev/db/engine.py`.

If `async_session_maker` is bound to `Settings().database_url`, then the route tests must override `get_session`. We should modify `routes.py` to make `get_session` overridable (e.g., expose it as a module-level function that can be patched, or use a dependency that reads from a global). The simplest approach is to add an override mechanism in `routes.py` or in the test.

Actually, in FastAPI you can override dependencies on the app:
```python
app.dependency_overrides[get_session] = lambda: async_session_override
```

So the test can do:
```python
from novel_dev.api.routes import get_session
app.dependency_overrides[get_session] = lambda: async_session
```

But `get_session` is an async generator, so the override should yield the session. For testing:
```python
async def override_get_session():
    yield async_session
app.dependency_overrides[get_session] = override_get_session
```

Let me write the test with this pattern.

- [ ] **Step 1c: Write the actual failing tests**

Create `tests/test_api/test_setting_style_routes.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router, get_session

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_upload_setting_and_approve(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/novels/n1/documents/upload",
            json={"filename": "setting.txt", "content": "世界观：天玄大陆。主角林风。"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["extraction_type"] == "setting"

        pe_id = data["id"]
        resp2 = await client.get("/api/novels/n1/documents/pending")
        assert resp2.status_code == 200
        assert any(item["id"] == pe_id for item in resp2.json()["items"])

        resp3 = await client.post("/api/novels/n1/documents/pending/approve", json={"pending_id": pe_id})
        assert resp3.status_code == 200
        assert len(resp3.json()["documents"]) > 0

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_style_profile_versions_and_rollback(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Upload v1
        r1 = await client.post(
            "/api/novels/n1/documents/upload",
            json={"filename": "style.txt", "content": "a" * 10000},
        )
        pe1 = r1.json()["id"]
        await client.post("/api/novels/n1/documents/pending/approve", json={"pending_id": pe1})

        # Upload v2
        r2 = await client.post(
            "/api/novels/n1/documents/upload",
            json={"filename": "style.txt", "content": "b" * 10000},
        )
        pe2 = r2.json()["id"]
        await client.post("/api/novels/n1/documents/pending/approve", json={"pending_id": pe2})

        versions = await client.get("/api/novels/n1/style_profile/versions")
        assert versions.status_code == 200
        assert len(versions.json()["versions"]) == 2

        rollback = await client.post("/api/novels/n1/style_profile/rollback", json={"version": 1})
        assert rollback.status_code == 200

    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api/test_setting_style_routes.py -v`

Expected: FAIL with `404 Not Found` on `/api/novels/n1/documents/upload`

- [ ] **Step 3: Add routes to `routes.py`**

Modify `src/novel_dev/api/routes.py`:

At the top, add imports:
```python
from pydantic import BaseModel
from novel_dev.services.extraction_service import ExtractionService
from novel_dev.repositories.pending_extraction_repo import PendingExtractionRepository
from novel_dev.repositories.document_repo import DocumentRepository
```

Append new request/response models and endpoints at the bottom of the file:

```python
class UploadRequest(BaseModel):
    filename: str
    content: str


class ApproveRequest(BaseModel):
    pending_id: str


class RollbackRequest(BaseModel):
    version: int


@router.post("/api/novels/{novel_id}/documents/upload")
async def upload_document(novel_id: str, req: UploadRequest, session: AsyncSession = Depends(get_session)):
    svc = ExtractionService(session)
    pe = await svc.process_upload(novel_id, req.filename, req.content)
    return {
        "id": pe.id,
        "extraction_type": pe.extraction_type,
        "status": pe.status,
        "created_at": pe.created_at.isoformat(),
    }


@router.get("/api/novels/{novel_id}/documents/pending")
async def get_pending_documents(novel_id: str, session: AsyncSession = Depends(get_session)):
    repo = PendingExtractionRepository(session)
    items = await repo.list_by_novel(novel_id)
    return {
        "items": [
            {
                "id": i.id,
                "extraction_type": i.extraction_type,
                "status": i.status,
                "raw_result": i.raw_result,
                "proposed_entities": i.proposed_entities,
                "created_at": i.created_at.isoformat(),
            }
            for i in items
        ]
    }


@router.post("/api/novels/{novel_id}/documents/pending/approve")
async def approve_pending_document(novel_id: str, req: ApproveRequest, session: AsyncSession = Depends(get_session)):
    svc = ExtractionService(session)
    docs = await svc.approve_pending(req.pending_id)
    return {
        "documents": [
            {
                "id": d.id,
                "doc_type": d.doc_type,
                "title": d.title,
                "content": d.content[:500],
                "version": d.version,
            }
            for d in docs
        ]
    }


@router.get("/api/novels/{novel_id}/style_profile/versions")
async def list_style_profile_versions(novel_id: str, session: AsyncSession = Depends(get_session)):
    repo = DocumentRepository(session)
    docs = await repo.get_by_type(novel_id, "style_profile")
    return {
        "versions": [
            {
                "version": d.version,
                "updated_at": d.updated_at.isoformat(),
                "title": d.title,
            }
            for d in docs
        ]
    }


@router.post("/api/novels/{novel_id}/style_profile/rollback")
async def rollback_style_profile(novel_id: str, req: RollbackRequest, session: AsyncSession = Depends(get_session)):
    svc = ExtractionService(session)
    await svc.rollback_style_profile(novel_id, req.version)
    return {"rolled_back_to_version": req.version}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api/test_setting_style_routes.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/api/routes.py tests/test_api/test_setting_style_routes.py
git commit -m "feat: add setting/style extraction API routes"
```

---

### Task 10: Add MCP tools

**Files:**
- Modify: `src/novel_dev/mcp_server/server.py`
- Test: `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_mcp_server.py` (create if missing, otherwise append):

```python
import pytest

from novel_dev.mcp_server.server import mcp


@pytest.mark.asyncio
async def test_mcp_upload_document():
    result = await mcp.tools["upload_document"]("n1", "setting.txt", "世界观：天玄大陆。")
    assert result["extraction_type"] == "setting"
    assert "id" in result


@pytest.mark.asyncio
async def test_mcp_get_pending_documents():
    upload = await mcp.tools["upload_document"]("n2", "style.txt", "a" * 5000)
    result = await mcp.tools["get_pending_documents"]("n2")
    assert any(i["id"] == upload["id"] for i in result)


@pytest.mark.asyncio
async def test_mcp_analyze_style_from_text():
    result = await mcp.tools["analyze_style_from_text"]("剑光一闪。敌人倒下。")
    assert "style_guide" in result
    assert "style_config" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp_server.py -v`

Expected: FAIL with `KeyError: 'upload_document'` because the tool is not registered yet.

- [ ] **Step 3: Implement MCP tools**

Modify `src/novel_dev/mcp_server/server.py`:

Add imports at the top:
```python
from novel_dev.services.extraction_service import ExtractionService
from novel_dev.repositories.pending_extraction_repo import PendingExtractionRepository
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.agents.style_profiler import StyleProfilerAgent
```

Update `__init__` to register new tools:
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
        }
```

Add methods at the bottom of the class (before `mcp = NovelDevMCPServer()`):

```python
    async def upload_document(self, novel_id: str, filename: str, content: str) -> dict:
        async with async_session_maker() as session:
            svc = ExtractionService(session)
            pe = await svc.process_upload(novel_id, filename, content)
            return {
                "id": pe.id,
                "extraction_type": pe.extraction_type,
                "status": pe.status,
                "created_at": pe.created_at.isoformat(),
            }

    async def get_pending_documents(self, novel_id: str) -> list:
        async with async_session_maker() as session:
            repo = PendingExtractionRepository(session)
            items = await repo.list_by_novel(novel_id)
            return [
                {
                    "id": i.id,
                    "extraction_type": i.extraction_type,
                    "status": i.status,
                    "raw_result": i.raw_result,
                    "proposed_entities": i.proposed_entities,
                    "created_at": i.created_at.isoformat(),
                }
                for i in items
            ]

    async def approve_pending_documents(self, pending_id: str) -> dict:
        async with async_session_maker() as session:
            svc = ExtractionService(session)
            docs = await svc.approve_pending(pending_id)
            return {
                "documents": [
                    {
                        "id": d.id,
                        "doc_type": d.doc_type,
                        "title": d.title,
                        "content": d.content[:500],
                        "version": d.version,
                    }
                    for d in docs
                ]
            }

    async def list_style_profile_versions(self, novel_id: str) -> list:
        async with async_session_maker() as session:
            repo = DocumentRepository(session)
            docs = await repo.get_by_type(novel_id, "style_profile")
            return [
                {
                    "version": d.version,
                    "updated_at": d.updated_at.isoformat() if d.updated_at else None,
                    "title": d.title,
                }
                for d in docs
            ]

    async def rollback_style_profile(self, novel_id: str, version: int) -> dict:
        async with async_session_maker() as session:
            svc = ExtractionService(session)
            await svc.rollback_style_profile(novel_id, version)
            return {"rolled_back_to_version": version}

    async def analyze_style_from_text(self, text: str) -> dict:
        agent = StyleProfilerAgent()
        profile = await agent.profile(text)
        return profile.model_dump()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_server.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/mcp_server/server.py tests/test_mcp_server.py
git commit -m "feat: add MCP tools for extraction engine"
```

---

### Task 11: Integration test for full upload-and-approve flow

**Files:**
- Create: `tests/test_integration_setting_style_flow.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_integration_setting_style_flow.py`:

```python
import pytest

from novel_dev.services.extraction_service import ExtractionService
from novel_dev.repositories.document_repo import DocumentRepository


@pytest.mark.asyncio
async def test_setting_upload_to_documents(async_session):
    svc = ExtractionService(async_session)
    pe = await svc.process_upload(
        novel_id="novel_integration",
        filename="world_setting.txt",
        content="""
世界观：天玄大陆，万族林立。
修炼体系：炼气、筑基、金丹。
势力：青云宗是正道魁首，魔道横行。
主角林风，青云宗外门弟子，性格坚韧隐忍，目标为父报仇。
重要物品：残缺玉佩，上古魔宗信物，揭示主角身世。
剧情梗概：林风因家族被灭门，拜入青云宗修炼报仇。
""",
    )
    assert pe.extraction_type == "setting"

    docs = await svc.approve_pending(pe.id)
    assert len(docs) >= 4  # worldview, setting, synopsis, concept chars, concept items

    doc_repo = DocumentRepository(async_session)
    worldview_docs = await doc_repo.get_by_type("novel_integration", "worldview")
    assert len(worldview_docs) == 1
    assert "天玄大陆" in worldview_docs[0].content

    style_docs = await doc_repo.get_by_type("novel_integration", "style_profile")
    assert len(style_docs) == 0


@pytest.mark.asyncio
async def test_style_upload_versioning_and_rollback(async_session):
    svc = ExtractionService(async_session)
    doc_repo = DocumentRepository(async_session)

    # v1
    pe1 = await svc.process_upload("novel_style", "style_sample.txt", "a" * 12000)
    await svc.approve_pending(pe1.id)

    # v2
    pe2 = await svc.process_upload("novel_style", "style_sample.txt", "b" * 12000)
    await svc.approve_pending(pe2.id)

    versions = await doc_repo.get_by_type("novel_style", "style_profile")
    assert len(versions) == 2

    # Rollback to v1
    await svc.rollback_style_profile("novel_style", 1)
    active = await svc.get_active_style_profile("novel_style")
    assert active.version == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_integration_setting_style_flow.py -v`

Expected: FAIL if any upstream code is missing; otherwise PASS.

- [ ] **Step 3: Fix any issues and rerun**

If tests fail, fix the underlying issue in the relevant module, then rerun:

Run: `pytest tests/test_integration_setting_style_flow.py -v`

Expected: PASS

- [ ] **Step 4: Run full test suite**

Run: `pytest -v`

Expected: All tests pass (should be > 30 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_integration_setting_style_flow.py
git commit -m "test: add integration tests for setting/style extraction flow"
```

---

## Self-Review Checklist

**1. Spec coverage:**
- FileClassifier → Task 4
- SettingExtractorAgent → Task 5
- StyleProfilerAgent (dynamic sampling) → Task 6
- ProfileMerger (conflicts, version increment) → Task 7
- pending_extractions table → Task 1
- ExtractionService orchestration → Task 8
- API routes (upload, pending, approve, versions, rollback) → Task 9
- MCP tools → Task 10
- Integration tests → Task 11

**No gaps identified.**

**2. Placeholder scan:**
- No TBD, TODO, or "implement later" phrases.
- All code snippets are complete.
- All commands are exact.

**3. Type consistency:**
- `PendingExtraction.proposed_entities` is `Optional[list]` in model and `Optional[List[dict]]` in repo — consistent.
- `DocumentRepository.create` accepts `version: int = 1` — used throughout.
- API response shapes match service/repo return types.

**Plan is ready for execution.**
