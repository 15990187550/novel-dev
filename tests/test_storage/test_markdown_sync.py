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
        storage_paths = StoragePaths(tmpdir)
        sync = MarkdownSync(storage_paths=storage_paths)

        path = await sync.write_chapter("novel_1", "vol_1", "ch_1", "Chapter 1 text")

        assert path == str(storage_paths.archive_chapter_path("novel_1", "vol_1", "ch_1"))
        with open(path, "r", encoding="utf-8") as f:
            assert f.read() == "Chapter 1 text"
        assert await sync.read_chapter("novel_1", "vol_1", "ch_1") == "Chapter 1 text"


@pytest.mark.asyncio
async def test_write_exports_use_external_exports_layout():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_paths = StoragePaths(tmpdir)
        sync = MarkdownSync(storage_paths=storage_paths)

        volume_path = await sync.write_volume("novel_1", "vol_1", "volume.md", "# Vol")
        novel_path = await sync.write_novel("novel_1", "novel.txt", "# Novel")

        assert volume_path == str(storage_paths.export_volume_path("novel_1", "vol_1", "md"))
        assert novel_path == str(storage_paths.export_novel_path("novel_1", "txt"))


@pytest.mark.asyncio
async def test_suffixless_volume_export_defaults_to_markdown():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_paths = StoragePaths(tmpdir)
        sync = MarkdownSync(storage_paths=storage_paths)

        path = await sync.write_volume("n", "v", "volume", "x")

        assert path == str(storage_paths.export_volume_path("n", "v", "md"))
        assert path.endswith(os.path.join("novels", "n", "exports", "v", "volume.md"))


def test_constructor_rejects_base_dir_and_storage_paths():
    with tempfile.TemporaryDirectory() as tmpdir:
        with pytest.raises(ValueError, match="either base_dir or storage_paths"):
            MarkdownSync(base_dir=tmpdir, storage_paths=StoragePaths(tmpdir))
