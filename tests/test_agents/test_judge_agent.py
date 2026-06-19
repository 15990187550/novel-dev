import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from novel_dev.db.models import JudgePromptVersion
from novel_dev.config.ab_judge_config import JudgeConfig
from novel_dev.llm.models import ChatMessage
from novel_dev.agents.judge_agent import JudgeAgent, JudgeParseError, NoActiveVersionError


def _mock_llm_response(content: str):
    return ChatMessage(role="assistant", content=content)


@pytest.mark.asyncio
async def test_judge_sample_returns_three_dimensions_and_rationale(async_session):
    pv = JudgePromptVersion(
        version="v1", agent_name="judge_agent", prompt_text="stub {chapter_text}",
        is_active=True, experiment_state="active",
    )
    async_session.add(pv)
    await async_session.flush()

    config = JudgeConfig()
    agent = JudgeAgent(async_session, config)

    fake_response = _mock_llm_response(
        json.dumps({"口吻": 7.5, "叙事连贯": 8.0, "风格调性": 6.5, "理由": "口吻自然"})
    )
    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(return_value=fake_response)
        mock_factory.get.return_value = mock_client
        result = await agent.judge_sample("这是章节内容", version_id=None)

    assert result.scores == {"口吻": 7.5, "叙事连贯": 8.0, "风格调性": 6.5}
    assert result.rationale == "口吻自然"
    assert result.tie_breaker == pytest.approx((7.5 + 8.0 + 6.5) / 3)


@pytest.mark.asyncio
async def test_judge_sample_strips_markdown_fence(async_session):
    pv = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="x {chapter_text}", is_active=True)
    async_session.add(pv)
    await async_session.flush()

    config = JudgeConfig()
    agent = JudgeAgent(async_session, config)
    fenced = "```json\n" + json.dumps({"口吻": 8.0, "叙事连贯": 8.0, "风格调性": 8.0, "理由": "ok"}) + "\n```"
    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(return_value=_mock_llm_response(fenced))
        mock_factory.get.return_value = mock_client
        result = await agent.judge_sample("章节", version_id=None)
    assert result.scores["口吻"] == 8.0


@pytest.mark.asyncio
async def test_judge_sample_raises_on_missing_dimension(async_session):
    pv = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="x {chapter_text}", is_active=True)
    async_session.add(pv)
    await async_session.flush()

    agent = JudgeAgent(async_session, JudgeConfig())
    bad = json.dumps({"口吻": 7.0, "叙事连贯": 8.0})  # 缺风格调性
    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(return_value=_mock_llm_response(bad))
        mock_factory.get.return_value = mock_client
        with pytest.raises(JudgeParseError):
            await agent.judge_sample("章节", version_id=None)


@pytest.mark.asyncio
async def test_judge_sample_raises_on_out_of_range(async_session):
    pv = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="x {chapter_text}", is_active=True)
    async_session.add(pv)
    await async_session.flush()

    agent = JudgeAgent(async_session, JudgeConfig())
    bad = json.dumps({"口吻": 11.0, "叙事连贯": 8.0, "风格调性": 6.5, "理由": "x"})
    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(return_value=_mock_llm_response(bad))
        mock_factory.get.return_value = mock_client
        with pytest.raises(JudgeParseError):
            await agent.judge_sample("章节", version_id=None)


@pytest.mark.asyncio
async def test_judge_sample_raises_on_non_json(async_session):
    pv = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="x {chapter_text}", is_active=True)
    async_session.add(pv)
    await async_session.flush()

    agent = JudgeAgent(async_session, JudgeConfig())
    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(return_value=_mock_llm_response("我无法打分"))
        mock_factory.get.return_value = mock_client
        with pytest.raises(JudgeParseError):
            await agent.judge_sample("章节", version_id=None)


@pytest.mark.asyncio
async def test_judge_sample_raises_on_empty_chapter():
    agent = JudgeAgent(None, JudgeConfig())
    with pytest.raises(ValueError):
        await agent.judge_sample("", version_id=None)
    with pytest.raises(ValueError):
        await agent.judge_sample("   ", version_id=None)


@pytest.mark.asyncio
async def test_judge_sample_raises_when_no_active_version(async_session):
    # no PVs in DB
    agent = JudgeAgent(async_session, JudgeConfig())
    with pytest.raises(NoActiveVersionError):
        await agent.judge_sample("章节", version_id=None)


@pytest.mark.asyncio
async def test_judge_sample_uses_specific_version_id_when_given(async_session):
    pv_inactive = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="A {chapter_text}", is_active=False)
    pv_target = JudgePromptVersion(version="v2", agent_name="judge_agent", prompt_text="B {chapter_text}", is_active=True)
    async_session.add_all([pv_inactive, pv_target])
    await async_session.flush()

    agent = JudgeAgent(async_session, JudgeConfig())
    fake = _mock_llm_response(json.dumps({"口吻": 9.0, "叙事连贯": 9.0, "风格调性": 9.0, "理由": "v2"}))
    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(return_value=fake)
        mock_factory.get.return_value = mock_client
        result = await agent.judge_sample("章节", version_id=pv_inactive.id)
    assert result.scores["口吻"] == 9.0


@pytest.mark.asyncio
async def test_judge_sample_truncates_long_rationale(async_session):
    pv = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="x {chapter_text}", is_active=True)
    async_session.add(pv)
    await async_session.flush()

    config = JudgeConfig(max_rationale_chars=20)
    agent = JudgeAgent(async_session, config)
    long_rationale = "a" * 100
    fake = _mock_llm_response(json.dumps({"口吻": 7.0, "叙事连贯": 7.0, "风格调性": 7.0, "理由": long_rationale}))
    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(return_value=fake)
        mock_factory.get.return_value = mock_client
        result = await agent.judge_sample("章节", version_id=None)
    assert len(result.rationale) == 20


@pytest.mark.asyncio
async def test_judge_sample_writes_call_log(async_session):
    pv = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="x {chapter_text}", is_active=True)
    async_session.add(pv)
    await async_session.flush()

    agent = JudgeAgent(async_session, JudgeConfig())
    fake = _mock_llm_response(json.dumps({"口吻": 7.0, "叙事连贯": 7.0, "风格调性": 7.0, "理由": "ok"}))
    with patch("novel_dev.agents.judge_agent.llm_factory") as mock_factory:
        mock_client = MagicMock()
        mock_client.acomplete = AsyncMock(return_value=fake)
        mock_factory.get.return_value = mock_client
        result = await agent.judge_sample("章节", version_id=None, experiment_id="exp_1")
    assert result.call_log_id is not None