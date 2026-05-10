from types import SimpleNamespace

import pytest

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.services.chapter_rewrite_service import (
    ChapterRewriteService,
    REWRITE_STAGE_LIBRARIAN_ARCHIVE,
)


@pytest.mark.asyncio
async def test_rewrite_archive_stage_uses_data_dir(async_session, tmp_path, monkeypatch):
    captured = {}

    class FakeArchiveService:
        def __init__(self, session, data_dir):
            captured["session"] = session
            captured["data_dir"] = data_dir

        async def archive_chapter_only(self, novel_id, chapter_id):
            captured["novel_id"] = novel_id
            captured["chapter_id"] = chapter_id
            return {"path": "fake.md"}

    chapter_plan = {
        "chapter_id": "c_rewrite",
        "chapter_number": 1,
        "title": "Rewrite",
        "target_word_count": 3000,
        "beats": [{"summary": "Beat", "target_mood": "tense"}],
    }
    await NovelDirector(async_session).save_checkpoint(
        "n_rewrite",
        Phase.DRAFTING,
        {"current_volume_plan": {"volume_id": "v_rewrite", "chapters": [chapter_plan]}},
        volume_id="v_rewrite",
        chapter_id="c_rewrite",
    )
    repo = ChapterRepository(async_session)
    await repo.create("c_rewrite", "v_rewrite", 1, "Rewrite", novel_id="n_rewrite")
    await repo.update_text("c_rewrite", raw_draft="raw", polished_text="polished")
    await repo.update_status("c_rewrite", "edited")
    await async_session.commit()

    async def has_librarian_artifacts(self, novel_id, chapter_id):
        return True

    monkeypatch.setattr(
        "novel_dev.services.chapter_rewrite_service.settings",
        SimpleNamespace(data_dir=str(tmp_path)),
    )
    monkeypatch.setattr(
        "novel_dev.services.chapter_rewrite_service.ArchiveService",
        FakeArchiveService,
    )
    monkeypatch.setattr(
        ChapterRewriteService,
        "_has_librarian_artifacts",
        has_librarian_artifacts,
    )

    result = await ChapterRewriteService(async_session).rewrite(
        "n_rewrite",
        "c_rewrite",
        resume_from_stage=REWRITE_STAGE_LIBRARIAN_ARCHIVE,
    )

    assert result.archive == {"path": "fake.md"}
    assert captured == {
        "session": async_session,
        "data_dir": str(tmp_path),
        "novel_id": "n_rewrite",
        "chapter_id": "c_rewrite",
    }
