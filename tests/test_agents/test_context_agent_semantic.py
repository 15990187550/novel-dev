import pytest
from unittest.mock import AsyncMock

from novel_dev.agents.context_agent import ContextAgent
from novel_dev.schemas.similar_document import SimilarDocument
from novel_dev.db.models import NovelState


@pytest.mark.asyncio
async def test_assemble_with_embedding_service_includes_relevant_docs(async_session, mock_llm_factory):
    state = NovelState(
        novel_id="n1", current_phase="context_preparation",
        checkpoint_data={
            "current_chapter_plan": {
                "chapter_number": 1, "title": "第一章", "target_word_count": 3000,
                "beats": [{"summary": "主角进入学院", "target_mood": "好奇", "key_entities": ["主角"]}],
            },
            "current_time_tick": 1,
        },
    )
    async_session.add(state)
    await async_session.flush()

    mock_emb_svc = AsyncMock()
    mock_emb_svc.search_similar = AsyncMock(return_value=[
        SimilarDocument(doc_id="doc_s1", doc_type="setting", title="星辰学院",
            content_preview="位于大陆中央的魔法学院", similarity_score=0.95),
    ])

    agent = ContextAgent(async_session, embedding_service=mock_emb_svc)
    context = await agent.assemble("n1", "ch1")

    assert len(context.relevant_documents) == 1
    assert context.relevant_documents[0].doc_id == "doc_s1"
    mock_emb_svc.search_similar.assert_awaited_once()


@pytest.mark.asyncio
async def test_assemble_without_embedding_service_has_empty_relevant_docs(async_session, mock_llm_factory):
    state = NovelState(
        novel_id="n1", current_phase="context_preparation",
        checkpoint_data={
            "current_chapter_plan": {
                "chapter_number": 1, "title": "第一章", "target_word_count": 3000,
                "beats": [{"summary": "主角进入学院", "target_mood": "好奇", "key_entities": ["主角"]}],
            },
            "current_time_tick": 1,
        },
    )
    async_session.add(state)
    await async_session.flush()

    agent = ContextAgent(async_session)
    context = await agent.assemble("n1", "ch1")
    assert context.relevant_documents == []
