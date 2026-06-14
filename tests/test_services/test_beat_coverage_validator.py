import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from novel_dev.schemas.quality import BeatBoundaryCard
from novel_dev.services.beat_coverage_validator import BeatCoverageValidator


@pytest.fixture
def validator(async_session):
    return BeatCoverageValidator(async_session, use_llm=False)


@pytest.mark.asyncio
async def test_deterministic_full_coverage(validator):
    cards = [
        BeatBoundaryCard(beat_index=0, must_cover=["陆照", "玉佩"], forbidden_materials=[]),
    ]
    text = "陆照握紧玉佩，向药库深处走去。"
    results = await validator.validate(cards, text)
    assert len(results) == 1
    assert results[0].covered is True
    assert results[0].severity == "ok"


@pytest.mark.asyncio
async def test_deterministic_missing_keyword_warns(validator):
    cards = [
        BeatBoundaryCard(beat_index=0, must_cover=["陆照", "玉佩"], forbidden_materials=[]),
    ]
    text = "陆照向药库深处走去。"
    results = await validator.validate(cards, text)
    assert results[0].covered is False
    assert results[0].severity == "warn"


@pytest.mark.asyncio
async def test_deterministic_forbidden_material_blocks(validator):
    cards = [
        BeatBoundaryCard(beat_index=0, must_cover=["陆照"], forbidden_materials=["追兵"]),
    ]
    text = "陆照听见追兵逼近。"
    results = await validator.validate(cards, text)
    assert results[0].covered is False
    assert results[0].severity == "block"


@pytest.mark.asyncio
async def test_deterministic_empty_must_cover_ok(validator):
    cards = [BeatBoundaryCard(beat_index=0, must_cover=[], forbidden_materials=[])]
    results = await validator.validate(cards, "任意正文")
    assert results[0].covered is True
    assert results[0].severity == "ok"


@pytest.mark.asyncio
async def test_empty_beat_cards_and_no_llm(validator):
    results = await validator.validate([], "任意正文")
    assert len(results) == 1
    assert results[0].covered is True
    assert results[0].deviation == "no_cards_no_llm"


@pytest.mark.asyncio
async def test_llm_happy_path(async_session):
    validator = BeatCoverageValidator(async_session, use_llm=True)
    fake_response = MagicMock()
    fake_response.text = '[{"beat_index":0,"covered":true,"deviation":null,"severity":"ok"}]'
    fake_response.usage = None
    fake_response.finish_reason = None
    fake_client = AsyncMock()
    fake_client.acomplete = AsyncMock(return_value=fake_response)
    with patch("novel_dev.services.beat_coverage_validator.llm_factory") as mock_factory:
        mock_factory.get.return_value = fake_client
        results = await validator.validate(
            [BeatBoundaryCard(beat_index=0, must_cover=["陆照"])],
            "陆照行动",
        )
    assert len(results) == 1
    assert results[0].covered is True


@pytest.mark.asyncio
async def test_llm_invalid_json_falls_back(async_session):
    validator = BeatCoverageValidator(async_session, use_llm=True)
    fake_response = MagicMock()
    fake_response.text = "not json"
    fake_response.usage = None
    fake_response.finish_reason = None
    fake_client = AsyncMock()
    fake_client.acomplete = AsyncMock(return_value=fake_response)
    with patch("novel_dev.services.beat_coverage_validator.llm_factory") as mock_factory:
        mock_factory.get.return_value = fake_client
        results = await validator.validate(
            [BeatBoundaryCard(beat_index=0, must_cover=["陆照"], forbidden_materials=[])],
            "陆照行动",
        )
    assert len(results) == 1
    assert results[0].covered is True
    assert results[0].severity == "ok"


@pytest.mark.asyncio
async def test_llm_exception_falls_back(async_session):
    validator = BeatCoverageValidator(async_session, use_llm=True)
    fake_client = AsyncMock()
    fake_client.acomplete = AsyncMock(side_effect=ConnectionError("boom"))
    with patch("novel_dev.services.beat_coverage_validator.llm_factory") as mock_factory:
        mock_factory.get.return_value = fake_client
        results = await validator.validate(
            [BeatBoundaryCard(beat_index=0, must_cover=["陆照"], forbidden_materials=[])],
            "陆照行动",
        )
    assert len(results) == 1
    assert results[0].covered is True
    assert results[0].severity == "ok"


@pytest.mark.asyncio
async def test_warn_severity_to_issue_code():
    from novel_dev.services.beat_coverage_validator import BeatCoverageResult

    result = BeatCoverageResult(beat_index=0, covered=False, deviation="missing", severity="warn")
    assert result.to_issue_code() == "EVENT_ORDER_DRIFT"


@pytest.mark.asyncio
async def test_ok_severity_to_issue_code_returns_none():
    from novel_dev.services.beat_coverage_validator import BeatCoverageResult

    result = BeatCoverageResult(beat_index=0, covered=True, deviation=None, severity="ok")
    assert result.to_issue_code() is None


@pytest.mark.asyncio
async def test_block_severity_to_issue_code():
    from novel_dev.services.beat_coverage_validator import BeatCoverageResult

    result = BeatCoverageResult(beat_index=0, covered=False, deviation="forbidden", severity="block")
    assert result.to_issue_code() == "BEAT_BOUNDARY_VIOLATION"


@pytest.mark.asyncio
async def test_llm_non_array_payload_falls_back(async_session):
    validator = BeatCoverageValidator(async_session, use_llm=True)
    fake_response = MagicMock()
    fake_response.text = '{"beat_index":0,"covered":true}'
    fake_response.usage = None
    fake_response.finish_reason = None
    fake_client = AsyncMock()
    fake_client.acomplete = AsyncMock(return_value=fake_response)
    with patch("novel_dev.services.beat_coverage_validator.llm_factory") as mock_factory:
        mock_factory.get.return_value = fake_client
        results = await validator.validate(
            [BeatBoundaryCard(beat_index=0, must_cover=["陆照"], forbidden_materials=[])],
            "陆照行动",
        )
    assert len(results) == 1
    assert results[0].covered is True
    assert results[0].severity == "ok"
