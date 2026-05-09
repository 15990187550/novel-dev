from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, distinct

from novel_dev.db.models import Chapter
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.storage.markdown_sync import MarkdownSync


class ExportService:
    def __init__(self, session: AsyncSession, markdown_base_dir: str):
        self.session = session
        self.chapter_repo = ChapterRepository(session)
        self.sync = MarkdownSync(markdown_base_dir)

    def _render_chapters(self, chapters) -> str:
        lines = []
        for ch in chapters:
            title = ch.title or f"第{ch.chapter_number}章"
            lines.append(f"# {title}\n\n{ch.polished_text}")
        return "\n\n".join(lines)

    async def export_volume(self, novel_id: str, volume_id: str, format: str = "md") -> str:
        if format not in ("md", "txt"):
            raise ValueError(f"Unsupported format: {format}")
        chapters = await self.chapter_repo.list_by_volume(volume_id)
        archived = [ch for ch in chapters if ch.status == "archived"]
        content = self._render_chapters(archived)
        return await self.sync.write_volume(novel_id, volume_id, f"volume.{format}", content)

    async def export_novel(self, novel_id: str, format: str = "md") -> str:
        if format not in ("md", "txt"):
            raise ValueError(f"Unsupported format: {format}")
        result = await self.session.execute(
            select(distinct(Chapter.volume_id)).where(
                Chapter.novel_id == novel_id,
                Chapter.volume_id.isnot(None),
            )
        )
        volume_ids = result.scalars().all()

        parts = []
        for vid in sorted(volume_ids):
            chapters = await self.chapter_repo.list_by_volume(vid)
            archived = [ch for ch in chapters if ch.status == "archived"]
            if not archived:
                continue
            rendered = self._render_chapters(archived)
            parts.append(f"## Volume {vid}\n\n{rendered}")

        content = "\n\n---\n\n".join(parts)
        return await self.sync.write_novel(novel_id, f"novel.{format}", content)
