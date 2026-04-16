import os
import pytest
import tempfile

from novel_dev.services.archive_service import ArchiveService
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.agents.director import NovelDirector, Phase


@pytest.mark.asyncio
async def test_archive_service(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_archive",
        phase=Phase.LIBRARIAN,
        checkpoint_data={},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test Chapter")
    await ChapterRepository(async_session).update_text("c1", polished_text=" polished ")

    with tempfile.TemporaryDirectory() as tmpdir:
        svc = ArchiveService(async_session, tmpdir)
        result = await svc.archive("n_archive", "c1")

        assert result["word_count"] == 10
        assert os.path.exists(result["path_md"])

    ch = await ChapterRepository(async_session).get_by_id("c1")
    assert ch.status == "archived"
    state = await NovelStateRepository(async_session).get_state("n_archive")
    stats = state.checkpoint_data["archive_stats"]
    assert stats["total_word_count"] == 10
    assert stats["archived_chapter_count"] == 1
