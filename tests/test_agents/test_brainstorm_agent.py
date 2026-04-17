import json
from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.brainstorm_agent import BrainstormAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.llm.models import ChatMessage, LLMResponse
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.schemas.outline import SynopsisData, CharacterArc, PlotMilestone


@pytest.mark.asyncio
async def test_brainstorm_success(async_session):
    await DocumentRepository(async_session).create(
        "doc_wv", "n_brain", "worldview", "Worldview", "天玄大陆，万族林立。"
    )
    await DocumentRepository(async_session).create(
        "doc_st", "n_brain", "setting", "Setting", "修炼体系：炼气、筑基。"
    )

    mock_synopsis = SynopsisData(
        title="天玄纪元",
        logline="主角在修炼世界中崛起",
        core_conflict="个人复仇与天下大义",
        themes=["成长", "复仇"],
        character_arcs=[
            CharacterArc(
                name="主角",
                arc_summary="从废柴到巅峰",
                key_turning_points=["觉醒", "突破"],
            )
        ],
        milestones=[
            PlotMilestone(
                act="第一幕", summary="入门试炼", climax_event="外门大比"
            )
        ],
        estimated_volumes=3,
        estimated_total_chapters=90,
        estimated_total_words=270000,
    )
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text=mock_synopsis.model_dump_json())

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = BrainstormAgent(async_session)
        synopsis_data = await agent.brainstorm("n_brain")

    assert synopsis_data.title == "天玄纪元"
    assert synopsis_data.estimated_volumes == 3

    state = await NovelStateRepository(async_session).get_state("n_brain")
    assert state.current_phase == Phase.VOLUME_PLANNING.value
    assert "synopsis_data" in state.checkpoint_data
    assert state.checkpoint_data["synopsis_doc_id"] is not None

    docs = await DocumentRepository(async_session).get_by_type("n_brain", "synopsis")
    assert len(docs) == 1
    assert "天玄大陆" in docs[0].content


@pytest.mark.asyncio
async def test_brainstorm_missing_documents(async_session):
    agent = BrainstormAgent(async_session)
    with pytest.raises(ValueError, match="No source documents found"):
        await agent.brainstorm("n_empty")


@pytest.mark.asyncio
async def test_brainstorm_uses_llm_factory(async_session):
    await DocumentRepository(async_session).create(
        "doc_wv2", "n_brain2", "worldview", "Worldview", "天玄大陆。"
    )

    synopsis_json = SynopsisData(
        title="天玄纪元",
        logline="主角崛起",
        core_conflict="复仇",
        themes=["成长"],
        character_arcs=[],
        milestones=[],
        estimated_volumes=3,
        estimated_total_chapters=90,
        estimated_total_words=270000,
    ).model_dump_json()

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text=synopsis_json)

    with patch("novel_dev.llm.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = BrainstormAgent(async_session)
        result = await agent.brainstorm("n_brain2")

    assert result.title == "天玄纪元"
    mock_factory.get.assert_called_once_with("BrainstormAgent", task="generate_synopsis")
    call_args = mock_client.acomplete.call_args[0][0]
    assert any(isinstance(m, ChatMessage) and m.role == "system" for m in call_args)
