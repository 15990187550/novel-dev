import os
import pytest
import shutil

from novel_dev.storage.markdown_sync import MarkdownSync


@pytest.mark.asyncio
async def test_write_and_read_chapter():
    sync = MarkdownSync(base_dir="/tmp/test_novel_output")
    await sync.write_chapter("novel_1", "vol_1", "ch_1", "Chapter 1 text")
    content = await sync.read_chapter("novel_1", "vol_1", "ch_1")
    assert content == "Chapter 1 text"
    # cleanup
    shutil.rmtree("/tmp/test_novel_output", ignore_errors=True)
