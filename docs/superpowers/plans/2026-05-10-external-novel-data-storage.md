# External Novel Data Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move new novel archive, export, and deletion filesystem operations out of the repository and under `NOVEL_DEV_DATA_DIR`.

**Architecture:** Add a focused storage-path abstraction under `src/novel_dev/storage/` and route archive, export, chapter export, and deletion through it. Keep the database authoritative and keep all existing API response shapes, but make returned file paths point to the external data root.

**Tech Stack:** Python 3.11, Pydantic Settings, FastAPI, SQLAlchemy async, pytest, existing `MarkdownSync` file writer.

---

## File Map

- Create `src/novel_dev/storage/paths.py`: owns external data-root expansion, per-novel directory layout, and identifier safety checks.
- Modify `src/novel_dev/storage/markdown_sync.py`: keep legacy behavior but add storage-aware archive/export writes.
- Modify `src/novel_dev/config.py`: add `data_dir` with default `~/NovelDevData`.
- Modify `src/novel_dev/services/archive_service.py`: accept `data_dir`, use storage-aware `MarkdownSync`.
- Modify `src/novel_dev/services/export_service.py`: accept `data_dir`, write exports under `exports/`.
- Modify `src/novel_dev/services/novel_deletion_service.py`: accept `data_dir`, delete `novels/<novel_id>`.
- Modify `src/novel_dev/api/routes.py`: pass `settings.data_dir` to the affected services and chapter export route.
- Modify `src/novel_dev/agents/director.py`: pass `settings.data_dir` to `ArchiveService`.
- Modify `src/novel_dev/services/chapter_rewrite_service.py`: pass `settings.data_dir` to `ArchiveService`.
- Create `tests/test_storage/test_paths.py`: test path layout and traversal rejection.
- Modify `tests/test_storage/test_markdown_sync.py`: test new external archive/export layout while preserving legacy behavior.
- Modify `tests/test_config.py`: test `NOVEL_DEV_DATA_DIR`.
- Modify `tests/test_services/test_archive_service.py`, `tests/test_services/test_export_service.py`, and add deletion coverage if not already present.

## Task 1: Storage Paths

**Files:**
- Create: `src/novel_dev/storage/paths.py`
- Test: `tests/test_storage/test_paths.py`

- [ ] **Step 1: Write failing storage path tests**

Create `tests/test_storage/test_paths.py`:

```python
from pathlib import Path

import pytest

from novel_dev.storage.paths import StoragePaths


def test_storage_paths_resolve_external_layout(tmp_path):
    paths = StoragePaths(tmp_path)

    assert paths.data_dir == tmp_path.resolve()
    assert paths.db_dir == tmp_path.resolve() / "db"
    assert paths.logs_dir == tmp_path.resolve() / "logs"
    assert paths.novel_dir("novel_1") == tmp_path.resolve() / "novels" / "novel_1"
    assert paths.archive_chapter_path("novel_1", "vol_1", "ch_1") == (
        tmp_path.resolve() / "novels" / "novel_1" / "archive" / "vol_1" / "ch_1.md"
    )
    assert paths.export_volume_path("novel_1", "vol_1", "md") == (
        tmp_path.resolve() / "novels" / "novel_1" / "exports" / "vol_1" / "volume.md"
    )
    assert paths.export_novel_path("novel_1", "txt") == (
        tmp_path.resolve() / "novels" / "novel_1" / "exports" / "novel.txt"
    )
    assert paths.uploads_dir("novel_1") == tmp_path.resolve() / "novels" / "novel_1" / "uploads"
    assert paths.snapshots_dir("novel_1") == tmp_path.resolve() / "novels" / "novel_1" / "snapshots"


@pytest.mark.parametrize("bad", ["", "../x", "a/b", "a\\b", ".", ".."])
def test_storage_paths_reject_unsafe_identifiers(tmp_path, bad):
    paths = StoragePaths(tmp_path)

    with pytest.raises(ValueError, match="Unsafe storage identifier"):
        paths.novel_dir(bad)


def test_storage_paths_expand_user(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))

    paths = StoragePaths("~/NovelDevData")

    assert paths.data_dir == (fake_home / "NovelDevData").resolve()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_storage/test_paths.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'novel_dev.storage.paths'`.

- [ ] **Step 3: Implement `StoragePaths`**

Create `src/novel_dev/storage/paths.py`:

```python
from pathlib import Path


class StoragePaths:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir).expanduser().resolve()

    @property
    def db_dir(self) -> Path:
        return self.data_dir / "db"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    def novel_dir(self, novel_id: str) -> Path:
        return self._inside_root(self.data_dir / "novels" / self._safe_part(novel_id))

    def archive_dir(self, novel_id: str) -> Path:
        return self.novel_dir(novel_id) / "archive"

    def archive_chapter_path(self, novel_id: str, volume_id: str, chapter_id: str) -> Path:
        return self._inside_root(
            self.archive_dir(novel_id)
            / self._safe_part(volume_id)
            / f"{self._safe_part(chapter_id)}.md"
        )

    def exports_dir(self, novel_id: str) -> Path:
        return self.novel_dir(novel_id) / "exports"

    def export_volume_path(self, novel_id: str, volume_id: str, file_format: str) -> Path:
        return self._inside_root(
            self.exports_dir(novel_id)
            / self._safe_part(volume_id)
            / f"volume.{self._safe_part(file_format)}"
        )

    def export_novel_path(self, novel_id: str, file_format: str) -> Path:
        return self._inside_root(self.exports_dir(novel_id) / f"novel.{self._safe_part(file_format)}")

    def uploads_dir(self, novel_id: str) -> Path:
        return self.novel_dir(novel_id) / "uploads"

    def snapshots_dir(self, novel_id: str) -> Path:
        return self.novel_dir(novel_id) / "snapshots"

    def _safe_part(self, value: str) -> str:
        value = str(value or "").strip()
        if value in {"", ".", ".."} or "/" in value or "\\" in value:
            raise ValueError(f"Unsafe storage identifier: {value!r}")
        return value

    def _inside_root(self, path: Path) -> Path:
        resolved = path.resolve()
        if resolved != self.data_dir and self.data_dir not in resolved.parents:
            raise ValueError(f"Resolved storage path escapes data root: {resolved}")
        return resolved
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_storage/test_paths.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/novel_dev/storage/paths.py tests/test_storage/test_paths.py
git commit -m "feat: add external storage paths"
```

## Task 2: Configuration

**Files:**
- Modify: `src/novel_dev/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing config tests**

Replace `tests/test_config.py` with:

```python
def test_database_url_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
    from novel_dev.config import Settings

    settings = Settings()

    assert settings.database_url == "postgresql+asyncpg://test:test@localhost/test"


def test_data_dir_default():
    from novel_dev.config import Settings

    settings = Settings()

    assert settings.data_dir == "~/NovelDevData"


def test_data_dir_from_env(monkeypatch):
    monkeypatch.setenv("NOVEL_DEV_DATA_DIR", "/tmp/novel-dev-data")
    from novel_dev.config import Settings

    settings = Settings()

    assert settings.data_dir == "/tmp/novel-dev-data"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_config.py -q
```

Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'data_dir'`.

- [ ] **Step 3: Add `data_dir` setting**

Modify `src/novel_dev/config.py`:

```python
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    database_url: str = "postgresql+asyncpg://localhost/novel_dev"
    data_dir: str = "~/NovelDevData"
    markdown_output_dir: str = "./novel_output"
    llm_config_path: str = "./llm_config.yaml"
    llm_user_agent: str = "novel-dev/1.0"
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    moonshot_api_key: Optional[str] = None
    minimax_api_key: Optional[str] = None
    zhipu_api_key: Optional[str] = None
    config_admin_token: Optional[str] = None


settings = Settings()
```

- [ ] **Step 4: Run config tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_config.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/novel_dev/config.py tests/test_config.py
git commit -m "feat: add external data dir setting"
```

## Task 3: Markdown Sync External Layout

**Files:**
- Modify: `src/novel_dev/storage/markdown_sync.py`
- Modify: `tests/test_storage/test_markdown_sync.py`

- [ ] **Step 1: Write failing markdown sync tests**

Append to `tests/test_storage/test_markdown_sync.py`:

```python
from novel_dev.storage.paths import StoragePaths


@pytest.mark.asyncio
async def test_write_chapter_uses_external_archive_layout():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = MarkdownSync(storage_paths=StoragePaths(tmpdir))

        path = await sync.write_chapter("novel_1", "vol_1", "ch_1", "Chapter 1 text")

        assert path == os.path.join(tmpdir, "novels", "novel_1", "archive", "vol_1", "ch_1.md")
        with open(path, "r", encoding="utf-8") as f:
            assert f.read() == "Chapter 1 text"


@pytest.mark.asyncio
async def test_write_exports_use_external_exports_layout():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = MarkdownSync(storage_paths=StoragePaths(tmpdir))

        volume_path = await sync.write_volume("novel_1", "vol_1", "volume.md", "# Vol")
        novel_path = await sync.write_novel("novel_1", "novel.txt", "# Novel")

        assert volume_path == os.path.join(tmpdir, "novels", "novel_1", "exports", "vol_1", "volume.md")
        assert novel_path == os.path.join(tmpdir, "novels", "novel_1", "exports", "novel.txt")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_storage/test_markdown_sync.py -q
```

Expected: FAIL with `TypeError: MarkdownSync.__init__() got an unexpected keyword argument 'storage_paths'`.

- [ ] **Step 3: Update `MarkdownSync`**

Replace `src/novel_dev/storage/markdown_sync.py` with:

```python
import asyncio
import os
from pathlib import Path

from novel_dev.storage.paths import StoragePaths


class MarkdownSync:
    def __init__(self, base_dir: str | None = None, storage_paths: StoragePaths | None = None):
        if base_dir is None and storage_paths is None:
            raise ValueError("MarkdownSync requires base_dir or storage_paths")
        self.base_dir = base_dir
        self.storage_paths = storage_paths

    def _chapter_path(self, novel_id: str, volume_id: str, chapter_id: str) -> str:
        if self.storage_paths is not None:
            path = self.storage_paths.archive_chapter_path(novel_id, volume_id, chapter_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            return str(path)
        dir_path = os.path.join(str(self.base_dir), novel_id, volume_id)
        os.makedirs(dir_path, exist_ok=True)
        return os.path.join(dir_path, f"{chapter_id}.md")

    async def write_chapter(self, novel_id: str, volume_id: str, chapter_id: str, content: str) -> str:
        path = self._chapter_path(novel_id, volume_id, chapter_id)
        await asyncio.to_thread(self._sync_write, path, content)
        return path

    def _volume_path(self, novel_id: str, volume_id: str, filename: str) -> str:
        if self.storage_paths is not None:
            suffix = Path(filename).suffix.lstrip(".") or "md"
            path = self.storage_paths.export_volume_path(novel_id, volume_id, suffix)
            path.parent.mkdir(parents=True, exist_ok=True)
            return str(path)
        dir_path = os.path.join(str(self.base_dir), novel_id, volume_id)
        os.makedirs(dir_path, exist_ok=True)
        return os.path.join(dir_path, filename)

    def _novel_path(self, novel_id: str, filename: str) -> str:
        if self.storage_paths is not None:
            suffix = Path(filename).suffix.lstrip(".") or "md"
            path = self.storage_paths.export_novel_path(novel_id, suffix)
            path.parent.mkdir(parents=True, exist_ok=True)
            return str(path)
        dir_path = os.path.join(str(self.base_dir), novel_id)
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

    def _sync_write(self, path: str, content: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    async def read_chapter(self, novel_id: str, volume_id: str, chapter_id: str) -> str:
        path = self._chapter_path(novel_id, volume_id, chapter_id)
        return await asyncio.to_thread(self._sync_read, path)

    def _sync_read(self, path: str) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
```

- [ ] **Step 4: Run storage tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_storage/test_paths.py tests/test_storage/test_markdown_sync.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/novel_dev/storage/markdown_sync.py tests/test_storage/test_markdown_sync.py
git commit -m "feat: route markdown sync through external storage"
```

## Task 4: Archive, Export, and Delete Services

**Files:**
- Modify: `src/novel_dev/services/archive_service.py`
- Modify: `src/novel_dev/services/export_service.py`
- Modify: `src/novel_dev/services/novel_deletion_service.py`
- Modify: `tests/test_services/test_archive_service.py`
- Modify: `tests/test_services/test_export_service.py`
- Modify or create: `tests/test_services/test_novel_deletion_service.py`

- [ ] **Step 1: Update archive service tests for external layout**

In `tests/test_services/test_archive_service.py`, inside `test_archive_service`, after `result = await svc.archive("n_archive", "c1")`, add:

```python
        assert result["path_md"].endswith(
            os.path.join("novels", "n_archive", "archive", "v1", "c1.md")
        )
```

The existing assertions for file existence, file content, chapter status, and `archive_stats` remain.

- [ ] **Step 2: Update export service tests for external layout**

In `tests/test_services/test_export_service.py`, add path assertions in the existing tests:

```python
    assert path.endswith(os.path.join("novels", "n1", "exports", "v1", "volume.md"))
```

in `test_export_volume_filters_archived`.

Add:

```python
    assert path.endswith(os.path.join("novels", "n1", "exports", "novel.md"))
```

in `test_export_novel_aggregates_volumes`.

For `test_export_txt_format`, change the existing path suffix assertions to:

```python
    assert path.endswith(os.path.join("novels", "n1", "exports", "v1", "volume.txt"))
    assert path2.endswith(os.path.join("novels", "n1", "exports", "novel.txt"))
```

Ensure the file imports include:

```python
import os
```

- [ ] **Step 3: Add or update deletion service test**

If `tests/test_services/test_novel_deletion_service.py` does not exist, create it with:

```python
from pathlib import Path

import pytest

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.services.novel_deletion_service import NovelDeletionService


@pytest.mark.asyncio
async def test_delete_novel_removes_external_novel_package(async_session, tmp_path):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_delete_storage",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={"novel_title": "Delete Me"},
    )
    novel_dir = tmp_path / "novels" / "n_delete_storage"
    novel_dir.mkdir(parents=True)
    artifact = novel_dir / "artifact.md"
    artifact.write_text("content", encoding="utf-8")

    deleted = await NovelDeletionService(async_session, str(tmp_path)).delete_novel("n_delete_storage")

    assert deleted is True
    assert not novel_dir.exists()
```

If the file already exists, add this test unchanged.

- [ ] **Step 4: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_services/test_archive_service.py tests/test_services/test_export_service.py tests/test_services/test_novel_deletion_service.py -q
```

Expected: FAIL because services still pass raw `markdown_output_dir` into legacy paths.

- [ ] **Step 5: Update services**

Replace the constructors and sync setup in `src/novel_dev/services/archive_service.py` with:

```python
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.storage.markdown_sync import MarkdownSync
from novel_dev.storage.paths import StoragePaths


class ArchiveService:
    def __init__(self, session: AsyncSession, data_dir: str):
        self.session = session
        self.chapter_repo = ChapterRepository(session)
        self.state_repo = NovelStateRepository(session)
        self.sync = MarkdownSync(storage_paths=StoragePaths(data_dir))
```

Keep the rest of `ArchiveService` unchanged.

Replace the constructor in `src/novel_dev/services/export_service.py` with:

```python
class ExportService:
    def __init__(self, session: AsyncSession, data_dir: str):
        self.session = session
        self.chapter_repo = ChapterRepository(session)
        self.sync = MarkdownSync(storage_paths=StoragePaths(data_dir))
```

Add this import in the same file:

```python
from novel_dev.storage.paths import StoragePaths
```

In `src/novel_dev/services/novel_deletion_service.py`, replace the constructor and final filesystem removal with:

```python
from novel_dev.storage.paths import StoragePaths


class NovelDeletionService:
    def __init__(self, session: AsyncSession, data_dir: str):
        self.session = session
        self.storage_paths = StoragePaths(data_dir)
```

and:

```python
        shutil.rmtree(self.storage_paths.novel_dir(novel_id), ignore_errors=True)
        return True
```

Keep the database deletion sequence unchanged.

- [ ] **Step 6: Run service tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_services/test_archive_service.py tests/test_services/test_export_service.py tests/test_services/test_novel_deletion_service.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/novel_dev/services/archive_service.py src/novel_dev/services/export_service.py src/novel_dev/services/novel_deletion_service.py tests/test_services/test_archive_service.py tests/test_services/test_export_service.py tests/test_services/test_novel_deletion_service.py
git commit -m "feat: store novel artifacts outside repo"
```

## Task 5: API and Agent Call Sites

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Modify: `src/novel_dev/agents/director.py`
- Modify: `src/novel_dev/services/chapter_rewrite_service.py`
- Test: existing API/service tests affected by archive, export, deletion, chapter rewrite

- [ ] **Step 1: Find all remaining old setting call sites**

Run:

```bash
rg -n "settings\\.markdown_output_dir|ArchiveService\\(|ExportService\\(|NovelDeletionService\\(|MarkdownSync\\(" src/novel_dev tests
```

Expected: shows remaining production call sites in `routes.py`, `director.py`, and `chapter_rewrite_service.py`, plus legacy storage tests that intentionally still use `MarkdownSync(base_dir=...)`.

- [ ] **Step 2: Update API route imports and direct chapter export**

In `src/novel_dev/api/routes.py`, add:

```python
from novel_dev.storage.paths import StoragePaths
```

For `export_chapter`, replace:

```python
    sync = MarkdownSync(settings.markdown_output_dir)
```

with:

```python
    sync = MarkdownSync(storage_paths=StoragePaths(settings.data_dir))
```

For `delete_novel`, replace:

```python
    deleted = await NovelDeletionService(session, settings.markdown_output_dir).delete_novel(novel_id)
```

with:

```python
    deleted = await NovelDeletionService(session, settings.data_dir).delete_novel(novel_id)
```

For `export_volume` and `export_novel`, replace:

```python
    svc = ExportService(session, settings.markdown_output_dir)
```

with:

```python
    svc = ExportService(session, settings.data_dir)
```

- [ ] **Step 3: Update director archive call**

In `src/novel_dev/agents/director.py`, replace:

```python
        archive_svc = ArchiveService(self.session, settings.markdown_output_dir)
```

with:

```python
        archive_svc = ArchiveService(self.session, settings.data_dir)
```

- [ ] **Step 4: Update chapter rewrite archive call**

In `src/novel_dev/services/chapter_rewrite_service.py`, replace:

```python
            archive_result = await ArchiveService(self.session, settings.markdown_output_dir).archive_chapter_only(
```

with:

```python
            archive_result = await ArchiveService(self.session, settings.data_dir).archive_chapter_only(
```

- [ ] **Step 5: Run targeted API/service tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_api/test_librarian_routes.py tests/test_api/test_routes.py tests/test_api/test_chapter_draft_routes.py tests/test_services/test_chapter_rewrite_service.py -q
```

Expected: PASS. If `tests/test_services/test_chapter_rewrite_service.py` does not exist, run the first three test files and the grep command from Step 1 again.

- [ ] **Step 6: Confirm old production call sites are gone**

Run:

```bash
rg -n "settings\\.markdown_output_dir" src/novel_dev
```

Expected: no production usages for archive, export, delete, or chapter export. A remaining setting definition in `config.py` is allowed only if the grep includes that file.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/novel_dev/api/routes.py src/novel_dev/agents/director.py src/novel_dev/services/chapter_rewrite_service.py
git commit -m "feat: use data dir for novel artifact routes"
```

## Task 6: Full Verification

**Files:**
- No source edits expected unless verification finds a regression.

- [ ] **Step 1: Run focused storage and service suite**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_config.py tests/test_storage tests/test_services/test_archive_service.py tests/test_services/test_export_service.py tests/test_services/test_novel_deletion_service.py -q
```

Expected: PASS.

- [ ] **Step 2: Run related API suite**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_api/test_librarian_routes.py tests/test_api/test_routes.py tests/test_api/test_chapter_draft_routes.py -q
```

Expected: PASS.

- [ ] **Step 3: Run broader regression suite if time permits**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/ -q
```

Expected: PASS. If unrelated existing failures appear, capture the failing test names and error summaries without changing unrelated files.

- [ ] **Step 4: Inspect working tree**

Run:

```bash
git status --short
```

Expected: only pre-existing unrelated user changes remain, or a clean tree if this work is the only active change set.

## Self-Review

Spec coverage:

- `NOVEL_DEV_DATA_DIR` and default `~/NovelDevData`: Task 2.
- Per-novel package layout under `novels/<novel_id>`: Task 1 and Task 3.
- Archive path under `archive/<volume_id>/<chapter_id>.md`: Task 1, Task 3, Task 4.
- Export paths under `exports/`: Task 1, Task 3, Task 4.
- Delete `novels/<novel_id>` only: Task 4.
- Keep old database behavior and API response shapes: Task 4 and Task 5 preserve service return keys and database writes.
- Do not migrate old `./novel_output`: no task adds migration or legacy scanning.
- Path safety checks: Task 1.
- Tests use temporary data roots: Tasks 1 through 4.

Placeholder scan:

- The plan contains no incomplete sections, absent file paths, or unspecified implementation steps.

Type consistency:

- `StoragePaths` is imported from `novel_dev.storage.paths`.
- `MarkdownSync(storage_paths=StoragePaths(...))` is the storage-aware constructor form used by services and routes.
- `ArchiveService`, `ExportService`, and `NovelDeletionService` accept `data_dir: str`.
