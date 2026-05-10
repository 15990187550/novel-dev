from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, distinct

from novel_dev.db.models import Chapter
from novel_dev.storage.markdown_sync import MarkdownSync
from novel_dev.storage.paths import StoragePaths


class ExportService:
    def __init__(self, session: AsyncSession, data_dir: str):
        self.session = session
        self.sync = MarkdownSync(storage_paths=StoragePaths(data_dir))

    def _render_chapters(self, chapters) -> str:
        lines = []
        for ch in chapters:
            title = ch.title or f"第{ch.chapter_number}章"
            lines.append(f"# {title}\n\n{ch.polished_text}")
        return "\n\n".join(lines)

    async def _list_archived_chapters_for_volume(self, novel_id: str, volume_id: str) -> list[Chapter]:
        result = await self.session.execute(
            select(Chapter)
            .where(
                Chapter.novel_id == novel_id,
                Chapter.volume_id == volume_id,
                Chapter.status == "archived",
            )
            .order_by(Chapter.chapter_number)
        )
        return result.scalars().all()

    async def export_volume(self, novel_id: str, volume_id: str, format: str = "md") -> str:
        if format not in ("md", "txt"):
            raise ValueError(f"Unsupported format: {format}")
        chapters = await self._list_archived_chapters_for_volume(novel_id, volume_id)
        content = self._render_chapters(chapters)
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
            chapters = await self._list_archived_chapters_for_volume(novel_id, vid)
            if not chapters:
                continue
            rendered = self._render_chapters(chapters)
            parts.append(f"## Volume {vid}\n\n{rendered}")

        content = "\n\n---\n\n".join(parts)
        return await self.sync.write_novel(novel_id, f"novel.{format}", content)
