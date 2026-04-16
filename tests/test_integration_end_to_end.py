import uuid
import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router, get_session
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.schemas.context import ChapterPlan, BeatPlan, ChapterContext, LocationContext
from novel_dev.schemas.outline import SynopsisData
from novel_dev.services.export_service import ExportService
from novel_dev.config import Settings

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_end_to_end_pipeline_single_chapter(async_session, tmp_path):
    """Full pipeline: upload -> brainstorm -> volume plan -> context -> draft -> review -> edit -> fast review -> librarian -> export."""

    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    try:
        suffix = uuid.uuid4().hex[:8]
        novel_id = f"n_e2e_{suffix}"

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Upload worldview document (format must match SettingExtractorAgent)
            upload_resp = await client.post(
                f"/api/novels/{novel_id}/documents/upload",
                json={
                    "filename": "worldview.txt",
                    "content": (
                        "世界观：天玄大陆，万族林立。\n"
                        "修炼体系：炼气、筑基、金丹。\n"
                        "势力：青云宗是正道魁首，魔道横行。\n"
                        "主角林风，青云宗外门弟子，性格坚韧隐忍，目标为父报仇。\n"
                        "重要物品：残缺玉佩，上古魔宗信物，揭示主角身世。\n"
                        "剧情梗概：林风因家族被灭门，拜入青云宗修炼报仇。"
                    ),
                },
            )
            assert upload_resp.status_code == 200
            pending_id = upload_resp.json()["id"]

            # 2. Approve pending document
            approve_resp = await client.post(
                f"/api/novels/{novel_id}/documents/pending/approve",
                json={"pending_id": pending_id},
            )
            assert approve_resp.status_code == 200

            # 3. Brainstorm -> get synopsis
            brainstorm_resp = await client.post(f"/api/novels/{novel_id}/brainstorm")
            print("brainstorm error:", brainstorm_resp.status_code, brainstorm_resp.json())
            assert brainstorm_resp.status_code == 200
            assert brainstorm_resp.json()["title"] == "天玄纪元"

            synopsis_resp = await client.get(f"/api/novels/{novel_id}/synopsis")
            assert synopsis_resp.status_code == 200

            # 4. Volume plan
            # Inject synopsis_data into checkpoint for volume planner
            director = NovelDirector(session=async_session)
            state = await director.resume(novel_id)
            checkpoint = dict(state.checkpoint_data or {})
            checkpoint["synopsis_data"] = SynopsisData(
                title="天玄纪元",
                logline="主角在修炼世界中崛起",
                core_conflict="个人复仇与天下大义",
                estimated_volumes=1,
                estimated_total_chapters=1,
                estimated_total_words=3000,
            ).model_dump()
            await director.save_checkpoint(
                novel_id,
                phase=Phase.VOLUME_PLANNING,
                checkpoint_data=checkpoint,
                volume_id=None,
                chapter_id=None,
            )
            await async_session.commit()

            volume_plan_resp = await client.post(f"/api/novels/{novel_id}/volume_plan")
            assert volume_plan_resp.status_code == 200
            volume_id = volume_plan_resp.json()["volume_id"]
            chapter_id = volume_plan_resp.json()["chapters"][0]["chapter_id"]

            # Create chapter record so WriterAgent can update it
            await ChapterRepository(async_session).create(
                chapter_id, volume_id, 1, "第一章"
            )
            await async_session.commit()

            # Verify state transitioned to CONTEXT_PREPARATION
            state_resp = await client.get(f"/api/novels/{novel_id}/state")
            assert state_resp.json()["current_phase"] == Phase.CONTEXT_PREPARATION.value

            # 5. Prepare chapter context
            context_resp = await client.post(
                f"/api/novels/{novel_id}/chapters/{chapter_id}/context"
            )
            assert context_resp.status_code == 200

            # 6. Generate chapter draft
            # Need to ensure checkpoint has chapter_context
            state = await director.resume(novel_id)
            cp = dict(state.checkpoint_data or {})
            chapter_plan = ChapterPlan(
                chapter_number=1,
                title="第一章",
                target_word_count=50,
                beats=[BeatPlan(summary="主角在青云宗后山意外觉醒体内隐藏的上古血脉，周身灵气狂暴涌动，引发天地异象", target_mood="tense")],
            )
            cp["chapter_context"] = ChapterContext(
                chapter_plan=chapter_plan,
                style_profile={},
                worldview_summary="天玄大陆",
                active_entities=[],
                location_context=LocationContext(current="青云宗"),
                timeline_events=[],
                pending_foreshadowings=[],
            ).model_dump()
            await director.save_checkpoint(
                novel_id,
                phase=Phase.DRAFTING,
                checkpoint_data=cp,
                volume_id=volume_id,
                chapter_id=chapter_id,
            )
            await async_session.commit()

            draft_resp = await client.post(
                f"/api/novels/{novel_id}/chapters/{chapter_id}/draft"
            )
            assert draft_resp.status_code == 200
            assert draft_resp.json()["total_words"] > 0

            # 7. Advance to reviewing
            await director.save_checkpoint(
                novel_id,
                phase=Phase.REVIEWING,
                checkpoint_data=cp,
                volume_id=volume_id,
                chapter_id=chapter_id,
            )
            await async_session.commit()

            advance_review = await client.post(f"/api/novels/{novel_id}/advance")
            assert advance_review.status_code == 200
            assert advance_review.json()["current_phase"] == Phase.EDITING.value

            # 8. Advance to fast reviewing
            advance_edit = await client.post(f"/api/novels/{novel_id}/advance")
            assert advance_edit.status_code == 200
            assert advance_edit.json()["current_phase"] == Phase.FAST_REVIEWING.value

            # 9. Advance to librarian
            advance_fast = await client.post(f"/api/novels/{novel_id}/advance")
            assert advance_fast.status_code == 200
            assert advance_fast.json()["current_phase"] == Phase.LIBRARIAN.value

            # 10. Run librarian (archive + continue)
            with patch(
                "novel_dev.agents.librarian.LibrarianAgent._call_llm",
                new_callable=AsyncMock,
                return_value='{}',
            ):
                librarian_resp = await client.post(f"/api/novels/{novel_id}/librarian")
            assert librarian_resp.status_code == 200
            # Single chapter volume -> continues to VOLUME_PLANNING for next volume
            assert librarian_resp.json()["current_phase"] == Phase.VOLUME_PLANNING.value

            # 11. Verify chapter is archived
            ch = await ChapterRepository(async_session).get_by_id(chapter_id)
            assert ch.status == "archived"

            # 12. Export novel
            export_resp = await client.post(f"/api/novels/{novel_id}/export?format=md")
            assert export_resp.status_code == 200
            assert "exported_path" in export_resp.json()

            # 13. Get archive stats
            stats_resp = await client.get(f"/api/novels/{novel_id}/archive_stats")
            assert stats_resp.status_code == 200
            assert stats_resp.json()["archived_chapter_count"] == 1
            assert stats_resp.json()["total_word_count"] > 0

    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_end_to_end_pipeline_multi_chapter(async_session, tmp_path):
    """Pipeline with 2 chapters in same volume to test chapter continuation."""

    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    try:
        suffix = uuid.uuid4().hex[:8]
        novel_id = f"n_e2e_multi_{suffix}"
        director = NovelDirector(session=async_session)

        # Setup volume plan with 2 chapters
        chapter_1_id = f"c1_{suffix}"
        chapter_2_id = f"c2_{suffix}"
        volume_id = f"v_{suffix}"

        volume_plan = {
            "volume_id": volume_id,
            "volume_number": 1,
            "title": "第一卷",
            "total_chapters": 2,
            "chapters": [
                {
                    "chapter_id": chapter_1_id,
                    "chapter_number": 1,
                    "title": "第一章",
                    "summary": "觉醒",
                },
                {
                    "chapter_id": chapter_2_id,
                    "chapter_number": 2,
                    "title": "第二章",
                    "summary": "突破",
                },
            ],
        }

        chapter_plan_1 = ChapterPlan(
            chapter_number=1,
            title="第一章",
            target_word_count=3000,
            beats=[BeatPlan(summary="觉醒", target_mood="tense")],
        )

        context_1 = ChapterContext(
            chapter_plan=chapter_plan_1,
            style_profile={},
            worldview_summary="天玄大陆",
            active_entities=[],
            location_context=LocationContext(current="青云宗"),
            timeline_events=[],
            pending_foreshadowings=[],
        )

        await director.save_checkpoint(
            novel_id,
            phase=Phase.LIBRARIAN,
            checkpoint_data={
                "current_volume_plan": volume_plan,
                "chapter_context": context_1.model_dump(),
            },
            volume_id=volume_id,
            chapter_id=chapter_1_id,
        )
        await ChapterRepository(async_session).create(chapter_1_id, volume_id, 1, "第一章")
        await ChapterRepository(async_session).update_text(chapter_1_id, polished_text="第一章内容")
        await async_session.commit()

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Run librarian on chapter 1
            with patch(
                "novel_dev.agents.librarian.LibrarianAgent._call_llm",
                new_callable=AsyncMock,
                return_value='{}',
            ):
                resp_1 = await client.post(f"/api/novels/{novel_id}/librarian")
            assert resp_1.status_code == 200
            # Should continue to CONTEXT_PREPARATION for chapter 2
            assert resp_1.json()["current_phase"] == Phase.CONTEXT_PREPARATION.value

            # Verify current chapter moved to chapter 2
            state = await director.resume(novel_id)
            assert state.current_chapter_id == chapter_2_id

            # Prepare context and draft for chapter 2
            chapter_plan_2 = ChapterPlan(
                chapter_number=2,
                title="第二章",
                target_word_count=3000,
                beats=[BeatPlan(summary="突破", target_mood="epic")],
            )
            context_2 = ChapterContext(
                chapter_plan=chapter_plan_2,
                style_profile={},
                worldview_summary="天玄大陆",
                active_entities=[],
                location_context=LocationContext(current="青云宗"),
                timeline_events=[],
                pending_foreshadowings=[],
            )
            cp = dict(state.checkpoint_data or {})
            cp["chapter_context"] = context_2.model_dump()
            await director.save_checkpoint(
                novel_id,
                phase=Phase.DRAFTING,
                checkpoint_data=cp,
                volume_id=volume_id,
                chapter_id=chapter_2_id,
            )
            await ChapterRepository(async_session).create(chapter_2_id, volume_id, 2, "第二章")
            await ChapterRepository(async_session).update_text(chapter_2_id, raw_draft="突破内容")
            await async_session.commit()

            draft_resp = await client.post(
                f"/api/novels/{novel_id}/chapters/{chapter_2_id}/draft"
            )
            assert draft_resp.status_code == 200

            # Move through review -> edit -> fast review -> librarian
            await director.save_checkpoint(
                novel_id,
                phase=Phase.REVIEWING,
                checkpoint_data=cp,
                volume_id=volume_id,
                chapter_id=chapter_2_id,
            )
            await async_session.commit()

            await client.post(f"/api/novels/{novel_id}/advance")  # -> EDITING
            await client.post(f"/api/novels/{novel_id}/advance")  # -> FAST_REVIEWING
            await client.post(f"/api/novels/{novel_id}/advance")  # -> LIBRARIAN

            # Polish chapter 2 so librarian can archive it
            await ChapterRepository(async_session).update_text(chapter_2_id, polished_text="第二章精修")
            await async_session.commit()

            with patch(
                "novel_dev.agents.librarian.LibrarianAgent._call_llm",
                new_callable=AsyncMock,
                return_value='{}',
            ):
                resp_2 = await client.post(f"/api/novels/{novel_id}/librarian")
            assert resp_2.status_code == 200
            # Last chapter -> volume completed -> VOLUME_PLANNING
            assert resp_2.json()["current_phase"] == Phase.VOLUME_PLANNING.value

            # Verify both chapters archived
            ch1 = await ChapterRepository(async_session).get_by_id(chapter_1_id)
            ch2 = await ChapterRepository(async_session).get_by_id(chapter_2_id)
            assert ch1.status == "archived"
            assert ch2.status == "archived"

            # Export
            export_resp = await client.post(f"/api/novels/{novel_id}/export?format=md")
            assert export_resp.status_code == 200

            # Stats
            stats_resp = await client.get(f"/api/novels/{novel_id}/archive_stats")
            assert stats_resp.json()["archived_chapter_count"] == 2

    finally:
        app.dependency_overrides.clear()
