import os
import pytest
import shutil
import tempfile

from novel_dev.storage.markdown_sync import MarkdownSync
from novel_dev.storage.paths import StoragePaths


@pytest.mark.asyncio
async def test_write_and_read_chapter():
    sync = MarkdownSync(base_dir="/tmp/test_novel_output")
    await sync.write_chapter("novel_1", "vol_1", "ch_1", "Chapter 1 text")
    content = await sync.read_chapter("novel_1", "vol_1", "ch_1")
    assert content == "Chapter 1 text"
    # cleanup
    shutil.rmtree("/tmp/test_novel_output", ignore_errors=True)


@pytest.mark.asyncio
async def test_write_volume_and_novel():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = MarkdownSync(tmpdir)
        path = await sync.write_volume("n1", "v1", "volume.md", "# Vol 1\n\ncontent")
        assert os.path.exists(path)
        with open(path, "r", encoding="utf-8") as f:
            assert f.read() == "# Vol 1\n\ncontent"

        path2 = await sync.write_novel("n1", "novel.md", "# Novel\n\ncontent")
        assert os.path.exists(path2)
        with open(path2, "r", encoding="utf-8") as f:
            assert f.read() == "# Novel\n\ncontent"


@pytest.mark.asyncio
async def test_write_chapter_uses_external_archive_layout():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = MarkdownSync(storage_paths=StoragePaths(tmpdir))

        path = await sync.write_chapter("novel_1", "vol_1", "ch_1", "Chapter 1 text")

        assert path == os.path.join(tmpdir, "novels", "novel_1", "archive", "vol_1", "ch_1.md")
        with open(path, "r", encoding="utf-8") as f:
            assert f.read() == "Chapter 1 text"
        assert await sync.read_chapter("novel_1", "vol_1", "ch_1") == "Chapter 1 text"


@pytest.mark.asyncio
async def test_write_exports_use_external_exports_layout():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = MarkdownSync(storage_paths=StoragePaths(tmpdir))

        volume_path = await sync.write_volume("novel_1", "vol_1", "volume.md", "# Vol")
        novel_path = await sync.write_novel("novel_1", "novel.txt", "# Novel")

        assert volume_path == os.path.join(tmpdir, "novels", "novel_1", "exports", "vol_1", "volume.md")
        assert novel_path == os.path.join(tmpdir, "novels", "novel_1", "exports", "novel.txt")
