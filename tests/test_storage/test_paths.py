from pathlib import Path

import pytest

from novel_dev.storage.paths import StoragePaths


def test_storage_paths_resolve_external_layout(tmp_path):
    paths = StoragePaths(tmp_path)

    assert paths.data_dir == tmp_path.resolve()
    assert paths.db_dir == tmp_path.resolve() / "db"
    assert paths.logs_dir == tmp_path.resolve() / "logs"
    assert paths.novel_dir("novel_1") == tmp_path.resolve() / "novels" / "novel_1"
    assert paths.archive_chapter_path("novel_1", "vol_1", "ch_1") == (
        tmp_path.resolve() / "novels" / "novel_1" / "archive" / "vol_1" / "ch_1.md"
    )
    assert paths.export_volume_path("novel_1", "vol_1", "md") == (
        tmp_path.resolve() / "novels" / "novel_1" / "exports" / "vol_1" / "volume.md"
    )
    assert paths.export_novel_path("novel_1", "txt") == (
        tmp_path.resolve() / "novels" / "novel_1" / "exports" / "novel.txt"
    )
    assert paths.uploads_dir("novel_1") == tmp_path.resolve() / "novels" / "novel_1" / "uploads"
    assert paths.snapshots_dir("novel_1") == tmp_path.resolve() / "novels" / "novel_1" / "snapshots"


@pytest.mark.parametrize("bad", ["", "../x", "a/b", "a\\b", ".", ".."])
def test_storage_paths_reject_unsafe_identifiers(tmp_path, bad):
    paths = StoragePaths(tmp_path)

    with pytest.raises(ValueError, match="Unsafe storage identifier"):
        paths.novel_dir(bad)


def test_storage_paths_expand_user(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))

    paths = StoragePaths("~/NovelDevData")

    assert paths.data_dir == (fake_home / "NovelDevData").resolve()
