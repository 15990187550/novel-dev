import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from novel_dev.services.root_cause_analyzer import RootCauseAnalyzer, RootCauseResult


@pytest.mark.asyncio
async def test_analyze_happy_path(async_session):
    analyzer = RootCauseAnalyzer(async_session)
    analyzer.prompt_registry = AsyncMock()
    analyzer.prompt_registry.get_active = AsyncMock(return_value="Analyze: {chapter_text} {score_breakdown} {issue_codes} {beat_cards}")
    analyzer.llm_client = AsyncMock()
    fake_response = MagicMock()
    fake_response.text = json.dumps({
        "summary": "beat 2 越界",
        "suggested_actions": [{"action": "重写", "target": "beat:2", "severity": "high"}],
        "confidence": 0.85,
    }, ensure_ascii=False)
    fake_response.usage = None
    fake_response.finish_reason = None
    analyzer.llm_client.acomplete = AsyncMock(return_value=fake_response)

    result = await analyzer.analyze(
        novel_id="n_1", chapter_id="ch_1",
        chapter_text="陆照听见追兵...",
        score_breakdown={"narrative": 75, "character": 60},
        issue_codes=["BEAT_BOUNDARY_VIOLATION", "AI_FLAVOR_HIGH"],
        beat_boundary_cards=[],
    )
    assert result.summary == "beat 2 越界"
    assert result.confidence == 0.85


@pytest.mark.asyncio
async def test_analyze_truncates_long_text(async_session):
    analyzer = RootCauseAnalyzer(async_session)
    analyzer.prompt_registry = AsyncMock()

    async def fake_get_active(name):
        return "Prompt: {chapter_text} {score_breakdown} {issue_codes} {beat_cards}"
    analyzer.prompt_registry.get_active = fake_get_active
    analyzer.llm_client = AsyncMock()
    fake_response = MagicMock()
    fake_response.text = '{"summary": "x", "suggested_actions": [], "confidence": 0.5}'
    fake_response.usage = None
    fake_response.finish_reason = None
    analyzer.llm_client.acomplete = AsyncMock(return_value=fake_response)

    long_text = "x" * 10000
    await analyzer.analyze("n_1", "ch_1", long_text, {}, [], [])
    call_args = analyzer.llm_client.acomplete.call_args
    messages = call_args[0][0]
    content = messages[0].content
    assert "x" * 5001 not in content


@pytest.mark.asyncio
async def test_analyze_llm_failure_soft_degrades(async_session):
    analyzer = RootCauseAnalyzer(async_session)
    analyzer.prompt_registry = AsyncMock()
    analyzer.prompt_registry.get_active = AsyncMock(return_value="x")
    analyzer.llm_client = AsyncMock()
    analyzer.llm_client.acomplete = AsyncMock(side_effect=ConnectionError("boom"))

    result = await analyzer.analyze("n_1", "ch_1", "text", {}, [], [])
    assert result.summary == "[分析失败,请人工]"
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_analyze_invalid_json_soft_degrades(async_session):
    analyzer = RootCauseAnalyzer(async_session)
    analyzer.prompt_registry = AsyncMock()
    analyzer.prompt_registry.get_active = AsyncMock(return_value="x")
    analyzer.llm_client = AsyncMock()
    fake_response = MagicMock()
    fake_response.text = "not json"
    fake_response.usage = None
    fake_response.finish_reason = None
    analyzer.llm_client.acomplete = AsyncMock(return_value=fake_response)

    result = await analyzer.analyze("n_1", "ch_1", "text", {}, [], [])
    assert result.summary == "[分析失败,请人工]"
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_analyze_persists_result(async_session):
    analyzer = RootCauseAnalyzer(async_session)
    analyzer.prompt_registry = AsyncMock()
    analyzer.prompt_registry.get_active = AsyncMock(return_value="x")
    analyzer.llm_client = AsyncMock()
    fake_response = MagicMock()
    fake_response.text = json.dumps({
        "summary": "ok", "suggested_actions": [], "confidence": 0.7,
    })
    fake_response.usage = None
    fake_response.finish_reason = None
    analyzer.llm_client.acomplete = AsyncMock(return_value=fake_response)

    await analyzer.analyze("n_1", "ch_1", "text", {}, [], [])
    from novel_dev.repositories.root_cause_repo import RootCauseRepository
    latest = await RootCauseRepository(async_session).get_latest_for_chapter("ch_1")
    assert latest is not None
    assert latest.summary == "ok"


@pytest.mark.asyncio
async def test_get_llm_client_uses_injected(async_session):
    fake = AsyncMock()
    analyzer = RootCauseAnalyzer(async_session, llm_client=fake)
    client = await analyzer._get_llm_client()
    assert client is fake


@pytest.mark.asyncio
async def test_analyze_soft_degrades_when_prompt_load_fails(async_session):
    analyzer = RootCauseAnalyzer(async_session)
    analyzer.prompt_registry = AsyncMock()
    analyzer.prompt_registry.get_active = AsyncMock(side_effect=RuntimeError("db down"))
    result = await analyzer.analyze("n_1", "ch_1", "text", {}, [], [])
    assert result.summary == "[分析失败,请人工]"
    assert result.confidence == 0.0


def test_format_beat_cards_empty():
    from novel_dev.services.root_cause_analyzer import RootCauseAnalyzer
    out = RootCauseAnalyzer.__new__(RootCauseAnalyzer)._format_beat_cards([])
    assert out == "(none)"


def test_format_beat_cards_formats_list():
    from novel_dev.services.root_cause_analyzer import RootCauseAnalyzer
    from novel_dev.schemas.quality import BeatBoundaryCard
    cards = [
        BeatBoundaryCard(beat_index=1, must_cover=["陆照"], forbidden_materials=["追兵"]),
        BeatBoundaryCard(beat_index=2, must_cover=[], forbidden_materials=[]),
    ]
    out = RootCauseAnalyzer.__new__(RootCauseAnalyzer)._format_beat_cards(cards)
    assert "beat 1: must_cover=[陆照], forbidden=[追兵]" in out
    assert "beat 2: must_cover=[(no must_cover)], forbidden=[(no forbidden)]" in out
