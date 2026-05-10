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
    polished_text = " polished "
    await ChapterRepository(async_session).update_text("c1", polished_text=polished_text)

    with tempfile.TemporaryDirectory() as tmpdir:
        svc = ArchiveService(async_session, tmpdir)
        result = await svc.archive("n_archive", "c1")

        assert result["word_count"] == 10
        assert os.path.exists(result["path_md"])
        assert result["path_md"].endswith(
            os.path.join("novels", "n_archive", "archive", "v1", "c1.md")
        )
        with open(result["path_md"], "r", encoding="utf-8") as f:
            assert f.read() == polished_text

    ch = await ChapterRepository(async_session).get_by_id("c1")
    assert ch.status == "archived"
    state = await NovelStateRepository(async_session).get_state("n_archive")
    stats = state.checkpoint_data["archive_stats"]
    assert stats["total_word_count"] == 10
    assert stats["archived_chapter_count"] == 1


@pytest.mark.asyncio
async def test_archive_service_double_archive_raises(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_archive_double",
        phase=Phase.LIBRARIAN,
        checkpoint_data={},
        volume_id="v1",
        chapter_id="c_double",
    )
    await ChapterRepository(async_session).create("c_double", "v1", 1, "Test")
    await ChapterRepository(async_session).update_text("c_double", polished_text="text")

    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        svc = ArchiveService(async_session, tmpdir)
        await svc.archive("n_archive_double", "c_double")
        with pytest.raises(ValueError, match="already archived"):
            await svc.archive("n_archive_double", "c_double")
