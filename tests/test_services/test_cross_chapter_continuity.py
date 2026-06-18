import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from novel_dev.services.cross_chapter_continuity_service import (
    CrossChapterContinuityService,
    DriftIssue,
)


@pytest.mark.asyncio
async def test_build_pre_write_constraints_returns_formatted_text(async_session):
    from novel_dev.db.models import Entity, EntityVersion

    e = Entity(id="e_zhujue_a", type="character", name="主角A")
    async_session.add(e)
    await async_session.flush()
    ev = EntityVersion(
        entity_id="e_zhujue_a",
        version=1,
        state={"power_level": 0, "identity_role": "师兄"},
    )
    async_session.add(ev)
    await async_session.flush()

    svc = CrossChapterContinuityService(async_session)
    text = await svc.build_pre_write_constraints("n_1", ["e_zhujue_a"])
    assert "主角A" in text
    assert "实力 = 0" in text
    assert "师兄" in text


@pytest.mark.asyncio
async def test_build_pre_write_constraints_picks_latest_version_per_entity(async_session):
    from novel_dev.db.models import Entity, EntityVersion

    e = Entity(id="e_zhujue_b", type="character", name="主角B")
    async_session.add(e)
    await async_session.flush()
    async_session.add(EntityVersion(
        entity_id="e_zhujue_b", version=1,
        state={"power_level": 0, "identity_role": "外门弟子"},
    ))
    async_session.add(EntityVersion(
        entity_id="e_zhujue_b", version=2,
        state={"power_level": 5, "identity_role": "内门弟子"},
    ))
    await async_session.flush()

    svc = CrossChapterContinuityService(async_session)
    text = await svc.build_pre_write_constraints("n_1", ["e_zhujue_b"])
    assert "实力 = 5" in text
    assert "内门弟子" in text
    # Should not contain the stale version 1 values
    assert "实力 = 0" not in text
    assert "外门弟子" not in text


@pytest.mark.asyncio
async def test_build_pre_write_constraints_returns_empty_for_empty_ids(async_session):
    svc = CrossChapterContinuityService(async_session)
    assert await svc.build_pre_write_constraints("n_1", []) == ""
    assert await svc.build_pre_write_constraints("n_1", ["nonexistent_id"]) == ""


@pytest.mark.asyncio
async def test_detect_drift_calls_llm_and_parses(async_session, monkeypatch):
    from novel_dev.llm import llm_factory

    fake_response = MagicMock()
    fake_response.text = json.dumps([
        {
            "entity_name": "主角A",
            "drift_type": "name_drift",
            "severity": "block",
            "evidence_quote": "主角B听见追兵",
            "suggested_fix": "统一为主角A",
        }
    ])
    fake_client = AsyncMock()
    fake_client.acomplete = AsyncMock(return_value=fake_response)
    monkeypatch.setattr(llm_factory, "get", lambda *a, **kw: fake_client)

    svc = CrossChapterContinuityService(async_session)
    drifts = await svc.detect_drift("n_1", "ch_5", "主角B听见追兵。", ["e_zhujue_a"])
    assert len(drifts) == 1
    assert drifts[0].entity_name == "主角A"
    assert drifts[0].drift_type == "name_drift"
    assert drifts[0].severity == "block"
    assert drifts[0].evidence_quote == "主角B听见追兵"


@pytest.mark.asyncio
async def test_detect_drift_returns_empty_for_no_entities(async_session):
    svc = CrossChapterContinuityService(async_session)
    drifts = await svc.detect_drift("n_1", "ch_5", "某段文本。", [])
    assert drifts == []


@pytest.mark.asyncio
async def test_detect_drift_returns_empty_when_llm_returns_invalid_json(async_session, monkeypatch):
    from novel_dev.llm import llm_factory

    fake_response = MagicMock()
    fake_response.text = "not valid json at all"
    fake_client = AsyncMock()
    fake_client.acomplete = AsyncMock(return_value=fake_response)
    monkeypatch.setattr(llm_factory, "get", lambda *a, **kw: fake_client)

    svc = CrossChapterContinuityService(async_session)
    drifts = await svc.detect_drift("n_1", "ch_5", "某段文本。", ["e_zhujue_a"])
    assert drifts == []


@pytest.mark.asyncio
async def test_detect_drift_parses_code_fenced_json(async_session, monkeypatch):
    from novel_dev.llm import llm_factory

    fake_response = MagicMock()
    fake_response.text = (
        "```json\n"
        + json.dumps([
            {
                "entity_name": "主角A",
                "drift_type": "state_jump",
                "severity": "warn",
                "evidence_quote": "凡人突然筑基",
                "suggested_fix": "补一段突破描写",
            }
        ])
        + "\n```"
    )
    fake_client = AsyncMock()
    fake_client.acomplete = AsyncMock(return_value=fake_response)
    monkeypatch.setattr(llm_factory, "get", lambda *a, **kw: fake_client)

    svc = CrossChapterContinuityService(async_session)
    drifts = await svc.detect_drift("n_1", "ch_5", "凡人突然筑基。", ["e_zhujue_a"])
    assert len(drifts) == 1
    assert drifts[0].drift_type == "state_jump"
    assert drifts[0].severity == "warn"


def test_drift_issue_dataclass_defaults():
    issue = DriftIssue(
        entity_name="主角A",
        drift_type="identity_drift",
        severity="block",
        evidence_quote="师兄→师弟",
        suggested_fix="统一身份称谓",
    )
    assert issue.entity_name == "主角A"
    assert issue.drift_type == "identity_drift"
    assert issue.severity == "block"
