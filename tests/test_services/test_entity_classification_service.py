import pytest

from novel_dev.services.entity_classification_service import EntityClassificationService


@pytest.mark.asyncio
async def test_classification_service_marks_other_as_needs_review(async_session):
    svc = EntityClassificationService(async_session)
    result = await svc.classify(
        novel_id="n1",
        entity_name="无名概念",
        latest_state={"description": "一种模糊设定"},
        relationships=[],
    )

    assert result.system_category == "其他"
    assert result.system_needs_review is True
    assert result.classification_status == "needs_review"
    assert result.system_group_slug == "other"
    assert result.classification_confidence == 0.2


@pytest.mark.asyncio
async def test_classification_service_returns_auto_for_positive_match(async_session):
    svc = EntityClassificationService(async_session)
    result = await svc.classify(
        novel_id="n1",
        entity_name="青云宗",
        latest_state={"description": "一个宗门势力"},
        relationships=[],
    )

    assert result.system_category == "势力"
    assert result.system_needs_review is False
    assert result.classification_status == "auto"
