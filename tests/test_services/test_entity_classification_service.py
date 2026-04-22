import pytest
from unittest.mock import AsyncMock

from novel_dev.services.entity_classification_service import EntityClassificationService


@pytest.mark.asyncio
async def test_classification_service_marks_other_as_needs_review(async_session):
    svc = EntityClassificationService(async_session)
    result = await svc.classify(
        novel_id="n1",
        entity_type="other",
        entity_name="无名概念",
        latest_state={"description": "一种模糊设定"},
        relationships=[],
    )

    assert result.system_category == "其他"
    assert result.system_needs_review is True
    assert result.classification_status == "needs_review"
    assert result.system_group_slug == "other"
    assert result.classification_confidence == 0.45


@pytest.mark.asyncio
async def test_classification_service_returns_auto_for_positive_match(async_session):
    svc = EntityClassificationService(async_session)
    result = await svc.classify(
        novel_id="n1",
        entity_type="faction",
        entity_name="青云宗",
        latest_state={"description": "一个宗门势力"},
        relationships=[],
    )

    assert result.system_category == "势力"
    assert result.system_needs_review is False
    assert result.classification_status == "auto"


@pytest.mark.asyncio
async def test_classification_service_uses_llm_for_character_group(async_session):
    svc = EntityClassificationService(async_session)
    result = await svc.classify(
        novel_id="n1",
        entity_type="character",
        entity_name="陆照",
        latest_state={"identity": "主角", "goal": "登临绝巅"},
        relationships=[],
    )

    assert result.system_category == "人物"
    assert result.system_group_name == "主角阵营"
    assert result.system_group_slug == "主角阵营"
    assert result.system_needs_review is False
    assert result.classification_status == "auto"


@pytest.mark.asyncio
async def test_classification_service_falls_back_to_rules_when_llm_unavailable(async_session):
    svc = EntityClassificationService(async_session)
    svc.classifier_agent.classify = AsyncMock(side_effect=RuntimeError("llm unavailable"))

    result = await svc.classify(
        novel_id="n1",
        entity_type="item",
        entity_name="昆仑镜",
        latest_state={"description": "上古镜类至宝"},
        relationships=[],
    )

    assert result.system_category == "法宝神兵"
    assert result.system_group_name == "镜类法宝"
    assert result.system_needs_review is False
