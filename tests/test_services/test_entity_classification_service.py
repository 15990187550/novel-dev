import pytest
from unittest.mock import AsyncMock

from novel_dev.agents.entity_classifier import EntityClassificationBatchItem, EntityClassificationBatchResult
from novel_dev.llm.exceptions import LLMTimeoutError
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


@pytest.mark.asyncio
async def test_local_rules_classify_import_entities_without_llm(async_session):
    svc = EntityClassificationService(async_session)
    svc.classifier_agent.classify = AsyncMock(side_effect=AssertionError("LLM should not be called"))

    cases = [
        (
            "character",
            "张小凡/鬼厉",
            {"identity": "主角，青云门弟子"},
            "人物",
            "主角阵营",
        ),
        (
            "faction",
            "青云门",
            {"description": "正道宗门，主角师门"},
            "势力",
            "宗门",
        ),
        (
            "item",
            "太极玄清道",
            {"description": "青云门根本功法，主角主修"},
            "功法",
            "主修",
        ),
        (
            "item",
            "噬魂棒",
            {"description": "主角随身常用法宝"},
            "法宝神兵",
            "常用",
        ),
        (
            "item",
            "大还丹",
            {"description": "疗伤丹药，可快速复元"},
            "天材地宝",
            "疗伤",
        ),
        (
            "location",
            "大竹峰",
            {"description": "青云山门下支脉地点"},
            "其他",
            "地点",
        ),
    ]

    for entity_type, entity_name, latest_state, category, group_name in cases:
        result = await svc.classify(
            novel_id="n1",
            entity_type=entity_type,
            entity_name=entity_name,
            latest_state=latest_state,
            relationships=[],
            use_llm=False,
        )

        assert result.system_category == category
        assert result.system_group_name == group_name
        assert result.system_needs_review is False
        assert result.classification_status == "auto"


@pytest.mark.asyncio
async def test_local_rules_prefer_skill_over_treasure_for_item_names(async_session):
    svc = EntityClassificationService(async_session)
    svc.classifier_agent.classify = AsyncMock(side_effect=AssertionError("LLM should not be called"))

    result = await svc.classify(
        novel_id="n1",
        entity_type="item",
        entity_name="青云剑诀",
        latest_state={"description": "剑道传承法诀"},
        relationships=[],
        use_llm=False,
    )

    assert result.system_category == "功法"
    assert result.system_group_name == "剑道传承"


@pytest.mark.asyncio
async def test_batch_classification_retries_timeout_before_rule_fallback(async_session):
    svc = EntityClassificationService(async_session)
    svc.classifier_agent.classify_batch = AsyncMock(
        side_effect=[
            LLMTimeoutError("Request timed out"),
            EntityClassificationBatchResult(
                items=[
                    EntityClassificationBatchItem(
                        index=0,
                        category="人物",
                        group_name="反派",
                        confidence=0.91,
                        reason="retry succeeded",
                    )
                ]
            ),
        ]
    )

    results = await svc.classify_batch(
        "n1",
        [
            {
                "entity_type": "character",
                "entity_name": "木冰眉",
                "latest_state": {"identity": "反派"},
                "relationships": [],
            }
        ],
    )

    assert svc.classifier_agent.classify_batch.await_count == 2
    assert results[0].system_category == "人物"
    assert results[0].system_group_name == "反派"
    assert results[0].classification_reason["reason"] == "llm_batch_classification"
