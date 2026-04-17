from unittest.mock import AsyncMock

import pytest

from novel_dev.agents.context_agent import ContextAgent
from novel_dev.schemas.context import ChapterPlan, BeatPlan
from novel_dev.schemas.similar_document import SimilarDocument
from novel_dev.agents.director import NovelDirector, Phase


@pytest.mark.asyncio
async def test_similar_chapters_populated_via_embedding_service(async_session):
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=2,
        title="测试章节",
        target_word_count=3000,
        beats=[BeatPlan(summary="开场", target_mood="tense", key_entities=["林风"])],
    )
    await director.save_checkpoint(
        "n_test_ctx",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={"current_chapter_plan": chapter_plan.model_dump()},
        volume_id="vol_1",
        chapter_id="ch_2",
    )

    mock_embedding = AsyncMock()
    mock_embedding.search_similar_chapters.return_value = [
        SimilarDocument(
            doc_id="ch_1",
            doc_type="chapter",
            title="第一章",
            content_preview="第一章内容预览",
            similarity_score=0.88,
        )
    ]

    agent = ContextAgent(async_session, embedding_service=mock_embedding)
    context = await agent.assemble("n_test_ctx", "ch_2")

    assert len(context.similar_chapters) == 1
    assert context.similar_chapters[0].doc_id == "ch_1"
    assert context.similar_chapters[0].title == "第一章"
    mock_embedding.search_similar_chapters.assert_awaited_once_with(
        novel_id="n_test_ctx", query_text="测试章节\n开场", limit=2
    )


@pytest.mark.asyncio
async def test_similar_chapters_empty_when_no_embedding_service(async_session):
    director = NovelDirector(session=async_session)
    chapter_plan = ChapterPlan(
        chapter_number=1,
        title="首章",
        target_word_count=3000,
        beats=[BeatPlan(summary="开场", target_mood="tense")],
    )
    await director.save_checkpoint(
        "n_test_no_emb",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={"current_chapter_plan": chapter_plan.model_dump()},
        volume_id="vol_1",
        chapter_id="ch_1",
    )

    agent = ContextAgent(async_session, embedding_service=None)
    context = await agent.assemble("n_test_no_emb", "ch_1")

    assert context.similar_chapters == []
