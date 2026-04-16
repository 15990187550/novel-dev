import os
import asyncio


class MarkdownSync:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir

    def _chapter_path(self, novel_id: str, volume_id: str, chapter_id: str) -> str:
        dir_path = os.path.join(self.base_dir, novel_id, volume_id)
        os.makedirs(dir_path, exist_ok=True)
        return os.path.join(dir_path, f"{chapter_id}.md")

    async def write_chapter(self, novel_id: str, volume_id: str, chapter_id: str, content: str) -> str:
        path = self._chapter_path(novel_id, volume_id, chapter_id)
        await asyncio.to_thread(self._sync_write, path, content)
        return path

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

    def _sync_write(self, path: str, content: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    async def read_chapter(self, novel_id: str, volume_id: str, chapter_id: str) -> str:
        path = self._chapter_path(novel_id, volume_id, chapter_id)
        return await asyncio.to_thread(self._sync_read, path)

    def _sync_read(self, path: str) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
