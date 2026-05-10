from pathlib import Path


class StoragePaths:
    """Build paths for the external novel data directory layout."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()

    @property
    def db_dir(self) -> Path:
        return self._within_root("db")

    @property
    def logs_dir(self) -> Path:
        return self._within_root("logs")

    def novel_dir(self, novel_id: str) -> Path:
        return self._within_root("novels", self._safe_identifier(novel_id))

    def archive_dir(self, novel_id: str) -> Path:
        return self._ensure_within_root(self.novel_dir(novel_id) / "archive")

    def archive_chapter_path(self, novel_id: str, volume_id: str, chapter_id: str) -> Path:
        return self._ensure_within_root(
            self.archive_dir(novel_id)
            / self._safe_identifier(volume_id)
            / f"{self._safe_identifier(chapter_id)}.md"
        )

    def exports_dir(self, novel_id: str) -> Path:
        return self._ensure_within_root(self.novel_dir(novel_id) / "exports")

    def export_volume_path(self, novel_id: str, volume_id: str, file_format: str) -> Path:
        return self._ensure_within_root(
            self.exports_dir(novel_id)
            / self._safe_identifier(volume_id)
            / f"volume.{self._safe_identifier(file_format)}"
        )

    def export_novel_path(self, novel_id: str, file_format: str) -> Path:
        return self._ensure_within_root(
            self.exports_dir(novel_id) / f"novel.{self._safe_identifier(file_format)}"
        )

    def uploads_dir(self, novel_id: str) -> Path:
        return self._ensure_within_root(self.novel_dir(novel_id) / "uploads")

    def snapshots_dir(self, novel_id: str) -> Path:
        return self._ensure_within_root(self.novel_dir(novel_id) / "snapshots")

    def _within_root(self, *parts: str) -> Path:
        return self._ensure_within_root(self.data_dir.joinpath(*parts))

    def _ensure_within_root(self, path: Path) -> Path:
        resolved_path = path.resolve()
        try:
            resolved_path.relative_to(self.data_dir)
        except ValueError as exc:
            raise ValueError(f"Storage path escapes data root: {path}") from exc
        return resolved_path

    @staticmethod
    def _safe_identifier(value: str) -> str:
        identifier = str(value)
        if identifier in {"", ".", ".."} or "/" in identifier or "\\" in identifier:
            raise ValueError(f"Unsafe storage identifier: {identifier!r}")
        return identifier
