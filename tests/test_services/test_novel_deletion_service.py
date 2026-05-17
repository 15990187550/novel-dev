import pytest
from types import SimpleNamespace

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.db.models import NovelState
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


@pytest.mark.asyncio
async def test_delete_novel_deletes_generation_jobs(tmp_path):
    class FakeSession:
        def __init__(self):
            self.statements = []
            self.committed = False

        async def get(self, model, primary_key):
            if model is NovelState and primary_key == "n_delete_jobs":
                return SimpleNamespace(novel_id=primary_key)
            return None

        async def execute(self, statement):
            self.statements.append(str(statement))
            return None

        async def commit(self):
            self.committed = True

    session = FakeSession()

    deleted = await NovelDeletionService(session, str(tmp_path)).delete_novel("n_delete_jobs")

    assert deleted is True
    assert session.committed is True
    assert any("DELETE FROM generation_jobs" in stmt for stmt in session.statements)
