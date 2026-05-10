import os
import pytest
import tempfile

from novel_dev.services.export_service import ExportService
from novel_dev.repositories.chapter_repo import ChapterRepository


@pytest.fixture
async def svc(async_session):
    with tempfile.TemporaryDirectory() as tmpdir:
        yield ExportService(async_session, tmpdir)


@pytest.mark.asyncio
async def test_export_volume_filters_archived(async_session, svc):
    await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1", novel_id="n1")
    await ChapterRepository(async_session).create("c2", "v1", 2, "Ch2", novel_id="n1")
    await ChapterRepository(async_session).update_text("c1", polished_text="p1")
    await ChapterRepository(async_session).update_text("c2", polished_text="p2")
    await ChapterRepository(async_session).update_status("c1", "archived")

    path = await svc.export_volume("n1", "v1", format="md")
    assert path.endswith(os.path.join("novels", "n1", "exports", "v1", "volume.md"))
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "# Ch1" in content
    assert "p1" in content
    assert "p2" not in content


@pytest.mark.asyncio
async def test_export_volume_filters_shared_volume_id_by_novel(async_session, svc):
    await ChapterRepository(async_session).create(
        "c_shared_n1", "shared", 1, "Novel One", novel_id="n1"
    )
    await ChapterRepository(async_session).update_text("c_shared_n1", polished_text="only n1")
    await ChapterRepository(async_session).update_status("c_shared_n1", "archived")

    await ChapterRepository(async_session).create(
        "c_shared_n2", "shared", 2, "Novel Two", novel_id="n2"
    )
    await ChapterRepository(async_session).update_text("c_shared_n2", polished_text="leak n2")
    await ChapterRepository(async_session).update_status("c_shared_n2", "archived")

    path = await svc.export_volume("n1", "shared", format="md")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "only n1" in content
    assert "leak n2" not in content


@pytest.mark.asyncio
async def test_export_novel_aggregates_volumes(async_session, svc):
    await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1", novel_id="n1")
    await ChapterRepository(async_session).update_text("c1", polished_text="p1")
    await ChapterRepository(async_session).update_status("c1", "archived")

    path = await svc.export_novel("n1", format="md")
    assert path.endswith(os.path.join("novels", "n1", "exports", "novel.md"))
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "## Volume v1" in content
    assert "# Ch1" in content
    assert "p1" in content


@pytest.mark.asyncio
async def test_export_novel_filters_chapters_by_novel(async_session, svc):
    await ChapterRepository(async_session).create("c1", "v1", 1, "Novel One", novel_id="n1")
    await ChapterRepository(async_session).update_text("c1", polished_text="only n1")
    await ChapterRepository(async_session).update_status("c1", "archived")

    await ChapterRepository(async_session).create("c2", "v2", 1, "Novel Two", novel_id="n2")
    await ChapterRepository(async_session).update_text("c2", polished_text="should not leak")
    await ChapterRepository(async_session).update_status("c2", "archived")

    path = await svc.export_novel("n1", format="md")
    assert path.endswith(os.path.join("novels", "n1", "exports", "novel.md"))
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "only n1" in content
    assert "should not leak" not in content
    assert "## Volume v1" in content
    assert "## Volume v2" not in content


@pytest.mark.asyncio
async def test_export_novel_filters_shared_volume_id_by_novel(async_session, svc):
    await ChapterRepository(async_session).create(
        "c_shared_n1", "shared", 1, "Novel One", novel_id="n1"
    )
    await ChapterRepository(async_session).update_text("c_shared_n1", polished_text="only n1")
    await ChapterRepository(async_session).update_status("c_shared_n1", "archived")

    await ChapterRepository(async_session).create(
        "c_shared_n2", "shared", 2, "Novel Two", novel_id="n2"
    )
    await ChapterRepository(async_session).update_text("c_shared_n2", polished_text="leak n2")
    await ChapterRepository(async_session).update_status("c_shared_n2", "archived")

    path = await svc.export_novel("n1", format="md")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "only n1" in content
    assert "leak n2" not in content


@pytest.mark.asyncio
async def test_export_unsupported_format_raises(svc):
    with pytest.raises(ValueError, match="Unsupported format: pdf"):
        await svc.export_volume("n1", "v1", format="pdf")
    with pytest.raises(ValueError, match="Unsupported format: pdf"):
        await svc.export_novel("n1", format="pdf")


@pytest.mark.asyncio
async def test_export_txt_format(async_session, svc):
    await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1", novel_id="n1")
    await ChapterRepository(async_session).update_text("c1", polished_text="p1")
    await ChapterRepository(async_session).update_status("c1", "archived")

    path = await svc.export_volume("n1", "v1", format="txt")
    assert path.endswith(os.path.join("novels", "n1", "exports", "v1", "volume.txt"))
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "# Ch1" in content
    assert "p1" in content

    path2 = await svc.export_novel("n1", format="txt")
    assert path2.endswith(os.path.join("novels", "n1", "exports", "novel.txt"))
    with open(path2, "r", encoding="utf-8") as f:
        content2 = f.read()
    assert "## Volume v1" in content2
    assert "# Ch1" in content2


@pytest.mark.asyncio
async def test_export_volume_empty_archived_skips(async_session, svc):
    await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1")
    await ChapterRepository(async_session).update_text("c1", polished_text="p1")

    path = await svc.export_volume("n1", "v1", format="md")
    assert path.endswith(os.path.join("novels", "n1", "exports", "v1", "volume.md"))
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    assert content == ""
