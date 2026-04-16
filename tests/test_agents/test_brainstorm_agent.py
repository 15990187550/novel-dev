import pytest

from novel_dev.agents.brainstorm_agent import BrainstormAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository


@pytest.mark.asyncio
async def test_brainstorm_success(async_session):
    await DocumentRepository(async_session).create(
        "doc_wv", "n_brain", "worldview", "Worldview", "天玄大陆，万族林立。"
    )
    await DocumentRepository(async_session).create(
        "doc_st", "n_brain", "setting", "Setting", "修炼体系：炼气、筑基。"
    )

    agent = BrainstormAgent(async_session)
    synopsis_data = await agent.brainstorm("n_brain")

    assert synopsis_data.title != ""
    assert synopsis_data.estimated_volumes > 0

    state = await NovelStateRepository(async_session).get_state("n_brain")
    assert state.current_phase == Phase.VOLUME_PLANNING.value
    assert "synopsis_data" in state.checkpoint_data

    docs = await DocumentRepository(async_session).get_by_type("n_brain", "synopsis")
    assert len(docs) == 1
    assert "天玄大陆" in docs[0].content


@pytest.mark.asyncio
async def test_brainstorm_missing_documents(async_session):
    agent = BrainstormAgent(async_session)
    with pytest.raises(ValueError, match="No setting documents found"):
        await agent.brainstorm("n_empty")
