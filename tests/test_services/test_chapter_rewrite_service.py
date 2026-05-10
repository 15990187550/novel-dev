from types import SimpleNamespace

import pytest

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.services.chapter_rewrite_service import (
    ChapterRewriteService,
    REWRITE_STAGE_EDIT_FAST_REVIEW,
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


@pytest.mark.asyncio
async def test_rewrite_retries_editor_with_continuity_rewrite_plan(async_session, monkeypatch):
    chapter_plan = {
        "chapter_id": "c_rewrite_continuity",
        "chapter_number": 1,
        "title": "Continuity Rewrite",
        "target_word_count": 20,
        "beats": [{"summary": "林照处理黑水城尸身异常", "target_mood": "tense"}],
    }
    checkpoint = {
        "current_volume_plan": {"volume_id": "v_rewrite_continuity", "chapters": [chapter_plan]},
        "chapter_context": {
            "chapter_plan": chapter_plan,
            "active_entities": [
                {"name": "林照", "type": "character", "current_state": "已死亡，尸身留在黑水城"}
            ],
        },
    }
    await NovelDirector(async_session).save_checkpoint(
        "n_rewrite_continuity",
        Phase.FAST_REVIEWING,
        checkpoint,
        volume_id="v_rewrite_continuity",
        chapter_id="c_rewrite_continuity",
    )
    repo = ChapterRepository(async_session)
    await repo.create(
        "c_rewrite_continuity",
        "v_rewrite_continuity",
        1,
        "Continuity Rewrite",
        novel_id="n_rewrite_continuity",
    )
    await repo.update_text(
        "c_rewrite_continuity",
        raw_draft="林照忽然醒来，开口说出隐藏多年的真相。",
        polished_text="林照忽然醒来，开口说出隐藏多年的真相。",
    )
    await repo.update_status("c_rewrite_continuity", "edited")
    await async_session.commit()

    editor_checkpoints = []

    async def fake_polish(self, novel_id, chapter_id, rewrite_checkpoint):
        editor_checkpoints.append(dict(rewrite_checkpoint))
        text = (
            "林照的尸身没有醒来，留在黑水城寒榻上。"
            if len(editor_checkpoints) > 1
            else "林照忽然醒来，开口说出隐藏多年的真相。"
        )
        await ChapterRepository(async_session).update_text(
            chapter_id,
            polished_text=text,
        )
        await ChapterRepository(async_session).update_status(chapter_id, "edited")
        return text

    review_calls = 0

    async def fake_review(self, novel_id, chapter_id, rewrite_checkpoint):
        nonlocal review_calls
        review_calls += 1
        if review_calls == 1:
            rewrite_checkpoint["continuity_audit"] = {
                "status": "block",
                "blocking_items": [{
                    "code": "dead_entity_acted",
                    "message": "林照 当前状态为死亡/尸身，但成稿写成了可行动角色。",
                    "detail": {"entity": "林照", "current_state": "已死亡，尸身留在黑水城"},
                }],
                "warning_items": [],
                "summary": "连续性审计发现硬冲突，停止归档和世界状态入库。",
            }
            rewrite_checkpoint["quality_gate"] = {"status": "block", "blocking_items": [{"code": "continuity_audit"}]}
        else:
            rewrite_checkpoint["continuity_audit"] = {"status": "pass", "blocking_items": [], "warning_items": []}
            rewrite_checkpoint["quality_gate"] = {"status": "pass", "blocking_items": [], "warning_items": []}
        return SimpleNamespace(
            word_count_ok=True,
            consistency_fixed=True,
            ai_flavor_reduced=True,
            beat_cohesion_ok=True,
            language_style_ok=True,
            model_dump=lambda: {"notes": []},
        )

    class FakeLibrarian:
        def __init__(self, session, embedding_service):
            pass

        async def extract(self, novel_id, chapter_id, polished_text):
            return SimpleNamespace()

        async def persist(self, extraction, chapter_id, novel_id):
            return None

    class FakeArchiveService:
        def __init__(self, session, data_dir):
            pass

        async def archive_chapter_only(self, novel_id, chapter_id):
            return {"path": "continuity.md"}

    monkeypatch.setattr("novel_dev.services.chapter_rewrite_service.EditorAgent.polish_standalone", fake_polish)
    monkeypatch.setattr("novel_dev.services.chapter_rewrite_service.FastReviewAgent.review_standalone", fake_review)
    monkeypatch.setattr("novel_dev.services.chapter_rewrite_service.LibrarianAgent", FakeLibrarian)
    monkeypatch.setattr("novel_dev.services.chapter_rewrite_service.ArchiveService", FakeArchiveService)

    result = await ChapterRewriteService(async_session).rewrite(
        "n_rewrite_continuity",
        "c_rewrite_continuity",
        resume_from_stage=REWRITE_STAGE_EDIT_FAST_REVIEW,
        resume_checkpoint=checkpoint,
    )

    assert result.status == "succeeded"
    assert review_calls == 2
    assert editor_checkpoints[1]["continuity_rewrite_plan"]["source"] == "continuity_audit"
    assert editor_checkpoints[1]["continuity_rewrite_plan"]["rewrite_all"] is True
    assert editor_checkpoints[1]["continuity_rewrite_plan"]["global_issues"][0]["code"] == "dead_entity_acted"
