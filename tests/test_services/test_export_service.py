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


# ---------------------------------------------------------------------------
# Task 19: coverage for failure modes identified in
# docs/superpowers/notes/2026-06-14-export-failure-diagnosis.md
#
# These tests document CURRENT behavior. The empty-chapter tests are
# "intentional test of current behavior" — per diagnosis Fix #3 the
# service SHOULD raise ValueError("No archived chapters to export...")
# instead of writing an empty file, but that production fix is out of
# scope for this task. The assertions will fail (or change) once that
# follow-up lands; the comment in each test flags the gap.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_volume_with_zero_archived_chapters(async_session, svc):
    """Currently writes an empty file.

    TODO: per diagnosis Fix #3, should raise ValueError. The production
    fix is NOT in scope for Task 19.
    """
    # Volume v1 exists but has no chapters at all
    path = await svc.export_volume("n1", "v1", format="md")
    assert path.endswith(os.path.join("novels", "n1", "exports", "v1", "volume.md"))
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    # Current behavior: empty file is written.
    assert content == ""


@pytest.mark.asyncio
async def test_export_volume_with_chapters_but_none_archived(async_session, svc):
    """Currently writes an empty file because the archived-status filter
    matches nothing.

    TODO: per diagnosis Fix #3, should raise ValueError.
    """
    await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1", novel_id="n1")
    await ChapterRepository(async_session).update_text("c1", polished_text="p1")
    # Note: status is left as default (not "archived")

    path = await svc.export_volume("n1", "v1", format="md")
    assert path.endswith(os.path.join("novels", "n1", "exports", "v1", "volume.md"))
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    assert content == ""


@pytest.mark.asyncio
async def test_export_novel_with_zero_archived_chapters(async_session, svc):
    """Currently writes an empty file.

    TODO: per diagnosis Fix #3, should raise ValueError.
    """
    # Novel n1 has no volumes with archived chapters.
    path = await svc.export_novel("n1", format="md")
    assert path.endswith(os.path.join("novels", "n1", "exports", "novel.md"))
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    # Current behavior: empty file is written.
    assert content == ""


@pytest.mark.asyncio
async def test_export_novel_with_chapters_but_none_archived(async_session, svc):
    """Currently writes an empty file.

    TODO: per diagnosis Fix #3, should raise ValueError.
    """
    await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1", novel_id="n1")
    await ChapterRepository(async_session).update_text("c1", polished_text="p1")
    # No chapter is marked "archived"

    path = await svc.export_novel("n1", format="md")
    assert path.endswith(os.path.join("novels", "n1", "exports", "novel.md"))
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    assert content == ""


@pytest.mark.asyncio
async def test_export_volume_unsupported_format_raises(async_session, svc):
    """export_volume(format="pdf") must raise ValueError("Unsupported format: pdf")."""
    # One archived chapter to ensure the failure is on the format check,
    # not on the empty-chapter path.
    await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1", novel_id="n1")
    await ChapterRepository(async_session).update_text("c1", polished_text="p1")
    await ChapterRepository(async_session).update_status("c1", "archived")

    with pytest.raises(ValueError, match="Unsupported format: pdf"):
        await svc.export_volume("n1", "v1", format="pdf")


@pytest.mark.asyncio
async def test_export_volume_unsupported_format_html_raises(async_session, svc):
    """export_volume(format="html") must raise ValueError."""
    await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1", novel_id="n1")
    await ChapterRepository(async_session).update_text("c1", polished_text="p1")
    await ChapterRepository(async_session).update_status("c1", "archived")

    with pytest.raises(ValueError, match="Unsupported format: html"):
        await svc.export_volume("n1", "v1", format="html")


@pytest.mark.asyncio
async def test_export_novel_unsupported_format_raises(async_session, svc):
    """export_novel(format="html") must raise ValueError("Unsupported format: html")."""
    await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1", novel_id="n1")
    await ChapterRepository(async_session).update_text("c1", polished_text="p1")
    await ChapterRepository(async_session).update_status("c1", "archived")

    with pytest.raises(ValueError, match="Unsupported format: html"):
        await svc.export_novel("n1", format="html")


@pytest.mark.asyncio
async def test_export_novel_unsupported_format_pdf_raises(async_session, svc):
    """export_novel(format="pdf") must raise ValueError."""
    await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1", novel_id="n1")
    await ChapterRepository(async_session).update_text("c1", polished_text="p1")
    await ChapterRepository(async_session).update_status("c1", "archived")

    with pytest.raises(ValueError, match="Unsupported format: pdf"):
        await svc.export_novel("n1", format="pdf")


@pytest.mark.asyncio
async def test_export_volume_storage_failure_propagates(async_session, svc, monkeypatch):
    """If MarkdownSync.write_volume raises (disk full, permission denied, etc.),
    the exception must propagate cleanly — not be swallowed.
    """
    await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1", novel_id="n1")
    await ChapterRepository(async_session).update_text("c1", polished_text="p1")
    await ChapterRepository(async_session).update_status("c1", "archived")

    async def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(svc.sync, "write_volume", boom)

    with pytest.raises(OSError, match="disk full"):
        await svc.export_volume("n1", "v1", format="md")


@pytest.mark.asyncio
async def test_export_novel_storage_failure_propagates(async_session, svc, monkeypatch):
    """If MarkdownSync.write_novel raises, the exception must propagate."""
    await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1", novel_id="n1")
    await ChapterRepository(async_session).update_text("c1", polished_text="p1")
    await ChapterRepository(async_session).update_status("c1", "archived")

    async def boom(*args, **kwargs):
        raise PermissionError("permission denied")

    monkeypatch.setattr(svc.sync, "write_novel", boom)

    with pytest.raises(PermissionError, match="permission denied"):
        await svc.export_novel("n1", format="md")


@pytest.mark.asyncio
async def test_export_volume_handles_chapter_with_none_polished_text(async_session, svc):
    """Document current behavior when an archived chapter has polished_text=None.

    The render path formats the title and {ch.polished_text} directly, so a
    None polished_text becomes the string "None" in the output. This is a
    latent bug worth a follow-up (skip chapter or write empty content).
    """
    await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1", novel_id="n1")
    # Intentionally do NOT call update_text — polished_text stays None
    await ChapterRepository(async_session).update_status("c1", "archived")

    path = await svc.export_volume("n1", "v1", format="md")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Current behavior: title is rendered, and the literal string "None"
    # appears in place of polished_text.
    assert "# Ch1" in content
    assert "None" in content
