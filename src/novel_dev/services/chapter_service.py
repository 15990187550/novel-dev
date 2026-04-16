from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.storage.markdown_sync import MarkdownSync


class ChapterService:
    def __init__(self, session: AsyncSession, markdown_base_dir: str):
        self.repo = ChapterRepository(session)
        self.sync = MarkdownSync(markdown_base_dir)

    async def create(self, chapter_id: str, volume_id: str, chapter_number: int, title: Optional[str] = None):
        return await self.repo.create(chapter_id, volume_id, chapter_number, title)

    async def get(self, chapter_id: str):
        return await self.repo.get_by_id(chapter_id)

    async def complete_chapter(self, novel_id: str, chapter_id: str, volume_id: str, raw_draft: str, polished_text: str) -> None:
        await self.repo.update_text(chapter_id, raw_draft=raw_draft, polished_text=polished_text)
        await self.repo.update_status(chapter_id, "completed")
        await self.sync.write_chapter(novel_id, volume_id, chapter_id, polished_text)
