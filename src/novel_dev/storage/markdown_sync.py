import os
import asyncio
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
            return self._display_path(self.storage_paths.archive_chapter_path(novel_id, volume_id, chapter_id))

        dir_path = os.path.join(self.base_dir, novel_id, volume_id)
        os.makedirs(dir_path, exist_ok=True)
        return os.path.join(dir_path, f"{chapter_id}.md")

    async def write_chapter(self, novel_id: str, volume_id: str, chapter_id: str, content: str) -> str:
        path = self._chapter_path(novel_id, volume_id, chapter_id)
        await asyncio.to_thread(self._sync_write, path, content)
        return path

    def _volume_path(self, novel_id: str, volume_id: str, filename: str) -> str:
        if self.storage_paths is not None:
            return self._display_path(
                self.storage_paths.export_volume_path(novel_id, volume_id, self._file_format(filename))
            )

        dir_path = os.path.join(self.base_dir, novel_id, volume_id)
        os.makedirs(dir_path, exist_ok=True)
        return os.path.join(dir_path, filename)

    def _novel_path(self, novel_id: str, filename: str) -> str:
        if self.storage_paths is not None:
            return self._display_path(self.storage_paths.export_novel_path(novel_id, self._file_format(filename)))

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

    def _sync_write(self, path: str, content: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def _file_format(self, filename: str) -> str:
        suffix = Path(filename).suffix
        return suffix[1:] if suffix else filename

    def _display_path(self, path: Path) -> str:
        path_str = str(path)
        if path_str.startswith("/private/var/"):
            return path_str[len("/private") :]
        return path_str

    async def read_chapter(self, novel_id: str, volume_id: str, chapter_id: str) -> str:
        path = self._chapter_path(novel_id, volume_id, chapter_id)
        return await asyncio.to_thread(self._sync_read, path)

    def _sync_read(self, path: str) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
