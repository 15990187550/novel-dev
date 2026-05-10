import pytest

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.services.novel_deletion_service import NovelDeletionService


@pytest.mark.asyncio
async def test_delete_novel_removes_external_novel_package(async_session, tmp_path):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_delete_storage",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={"novel_title": "Delete Me"},
    )
    novel_dir = tmp_path / "novels" / "n_delete_storage"
    novel_dir.mkdir(parents=True)
    artifact = novel_dir / "artifact.md"
    artifact.write_text("content", encoding="utf-8")

    deleted = await NovelDeletionService(async_session, str(tmp_path)).delete_novel(
        "n_delete_storage"
    )

    assert deleted is True
    assert not novel_dir.exists()
