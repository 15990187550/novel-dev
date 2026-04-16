import os
import pytest
import tempfile

from novel_dev.services.export_service import ExportService
from novel_dev.repositories.chapter_repo import ChapterRepository


@pytest.mark.asyncio
async def test_export_volume_and_novel(async_session):
    await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1")
    await ChapterRepository(async_session).create("c2", "v1", 2, "Ch2")
    await ChapterRepository(async_session).update_text("c1", polished_text="p1")
    await ChapterRepository(async_session).update_text("c2", polished_text="p2")
    await ChapterRepository(async_session).update_status("c1", "archived")

    with tempfile.TemporaryDirectory() as tmpdir:
        svc = ExportService(async_session, tmpdir)
        path = await svc.export_volume("n1", "v1", format="md")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "p1" in content
        assert "p2" not in content  # not archived

        path2 = await svc.export_novel("n1", format="md")
        with open(path2, "r", encoding="utf-8") as f:
            content2 = f.read()
        assert "p1" in content2
        assert "p2" not in content2

        with pytest.raises(ValueError):
            await svc.export_novel("n1", format="pdf")
