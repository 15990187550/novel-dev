from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.storage.markdown_sync import MarkdownSync


class ArchiveService:
    def __init__(self, session: AsyncSession, markdown_base_dir: str):
        self.session = session
        self.chapter_repo = ChapterRepository(session)
        self.state_repo = NovelStateRepository(session)
        self.sync = MarkdownSync(markdown_base_dir)

    async def archive(self, novel_id: str, chapter_id: str) -> dict:
        result = await self.archive_chapter_only(novel_id, chapter_id)

        state = await self.state_repo.get_state(novel_id)
        stats = dict(state.checkpoint_data.get("archive_stats", {}))
        stats["total_word_count"] = stats.get("total_word_count", 0) + result["word_count"]
        stats["archived_chapter_count"] = stats.get("archived_chapter_count", 0) + 1
        stats["avg_word_count"] = stats["total_word_count"] // max(stats["archived_chapter_count"], 1)

        checkpoint_data = dict(state.checkpoint_data)
        checkpoint_data["archive_stats"] = stats

        await self.state_repo.save_checkpoint(
            novel_id,
            current_phase=state.current_phase,
            checkpoint_data=checkpoint_data,
            current_volume_id=state.current_volume_id,
            current_chapter_id=state.current_chapter_id,
        )

        return result

    async def archive_chapter_only(self, novel_id: str, chapter_id: str) -> dict:
        ch = await self.chapter_repo.get_by_id(chapter_id)
        if not ch or not ch.polished_text:
            raise ValueError("Chapter has no polished text to archive")
        if getattr(ch, "quality_status", "unchecked") == "block":
            raise ValueError("Chapter quality gate blocked archive")
        if ch.status == "archived":
            raise ValueError("Chapter is already archived")

        chapter_word_count = len(ch.polished_text)
        path_md = await self.sync.write_chapter(novel_id, ch.volume_id, chapter_id, ch.polished_text)

        await self.chapter_repo.update_status(chapter_id, "archived")

        return {
            "word_count": chapter_word_count,
            "path_md": path_md,
        }
