import pytest
from pydantic import ValidationError

from novel_dev.agents.setting_workbench_agent import (
    SettingBatchDraft,
    SettingClarificationDecision,
    SettingWorkbenchAgent,
    normalize_setting_batch_payload,
)


def test_setting_clarification_decision_accepts_ready_payload():
    decision = SettingClarificationDecision.model_validate(
        {
            "status": "ready",
            "assistant_message": "信息足够，可以生成待审核设定。",
            "target_categories": ["功法", "势力"],
            "conversation_summary": "用户确认玄幻升级流和宗门冲突。",
        }
    )

    assert decision.status == "ready"
    assert decision.target_categories == ["功法", "势力"]


def test_setting_batch_draft_counts_setting_cards_entities_and_relationships():
    draft = SettingBatchDraft.model_validate(
        {
            "summary": "新增 1 张设定卡片，1 个实体，1 个关系变更",
            "changes": [
                {
                    "target_type": "setting_card",
                    "operation": "create",
                    "after_snapshot": {"title": "修炼体系", "content": "九境。"},
                },
                {
                    "target_type": "entity",
                    "operation": "create",
                    "after_snapshot": {"type": "item", "name": "道种", "state": {}},
                },
                {
                    "target_type": "relationship",
                    "operation": "create",
                    "after_snapshot": {
                        "source_id": "ent_luzhao",
                        "target_id": "ent_seed",
                        "relation_type": "持有",
                    },
                },
            ],
        }
    )

    assert draft.summary.startswith("新增 1 张")
    assert len(draft.changes) == 3
    prompt = SettingWorkbenchAgent.build_generation_prompt(
        title="关系补全",
        target_categories=["关系"],
        messages=[{"role": "user", "content": "陆照持有道种"}],
    )

    assert "relationship create 必须提供 after_snapshot.source_id、target_id、relation_type" in prompt
    assert "同一批次中 entity create 的 after_snapshot.id" in prompt
    assert "稳定临时 id" not in prompt
    assert "source_ref" not in prompt
    assert "target_ref" not in prompt


def test_generation_prompt_prefers_existing_source_coverage_doc_ids():
    prompt = SettingWorkbenchAgent.build_generation_prompt(
        title="外部宇宙对标",
        target_categories=["setting"],
        messages=[{"role": "user", "content": "生成阳神对标一世之尊境界映射。"}],
        current_setting_context={
            "source_coverage": {
                "required": True,
                "domains": [
                    {
                        "name": "阳神",
                        "status": "covered",
                        "matched_doc_ids": ["doc_yangshen_realm"],
                    }
                ],
                "missing_domains": [],
            }
        },
    )

    assert "source_coverage 已提供 matched_doc_ids" in prompt
    assert "优先用这些 doc_id 调用 get_novel_document_full" in prompt


def test_generation_prompt_guides_realm_mapping_by_source_world_groups():
    prompt = SettingWorkbenchAgent.build_generation_prompt(
        title="外部宇宙统一对标",
        target_categories=["setting"],
        messages=[{"role": "user", "content": "生成阳神、完美世界对标一世之尊境界映射。"}],
    )

    assert "按来源作品分组" in prompt
    assert "每组从低到高排列" in prompt


def test_setting_generation_prompt_includes_genre_setting_rules():
    prompt = SettingWorkbenchAgent.build_generation_prompt(
        title="类型设定",
        target_categories=["setting"],
        messages=[{"role": "user", "content": "生成基础设定。"}],
        genre_prompt_block="明确力量体系、世界秩序、资源稀缺性。",
    )

    assert "## 类型模板约束" in prompt
    assert "明确力量体系" in prompt
    assert "世界秩序" in prompt
    assert "资源稀缺性" in prompt


def test_generation_prompt_guides_conflict_hints_and_cross_work_people_shape():
    prompt = SettingWorkbenchAgent.build_generation_prompt(
        title="跨作品联动",
        target_categories=["plot"],
        messages=[{"role": "user", "content": "生成跨作品联动剧情框架。"}],
    )

    assert "conflict_hints 每项使用对象" in prompt
    assert "原世界+人物" in prompt


def test_setting_batch_draft_rejects_empty_changes():
    with pytest.raises(ValidationError):
        SettingBatchDraft.model_validate({"summary": "没有变更", "changes": []})


def test_setting_batch_draft_rejects_relationship_ref_fields_even_with_ids():
    with pytest.raises(ValidationError, match="must not use ref fields"):
        SettingBatchDraft.model_validate(
            {
                "summary": "混用了名称引用",
                "changes": [
                    {
                        "target_type": "relationship",
                        "operation": "create",
                        "after_snapshot": {
                            "source_id": "ent_luzhao",
                            "target_id": "ent_seed",
                            "source_ref": "陆照",
                            "relation_type": "持有",
                        },
                    },
                ],
            }
        )


def test_setting_batch_draft_rejects_top_level_relationship_source_ref():
    with pytest.raises(ValidationError, match="must not use ref fields"):
        SettingBatchDraft.model_validate(
            {
                "summary": "混用了顶层名称引用",
                "changes": [
                    {
                        "target_type": "relationship",
                        "operation": "create",
                        "source_ref": "陆照",
                        "after_snapshot": {
                            "source_id": "ent_luzhao",
                            "target_id": "ent_seed",
                            "relation_type": "持有",
                        },
                    },
                ],
            }
        )


def test_normalize_setting_batch_payload_accepts_common_field_drift():
    payload = {
        "result": {
            "summary": "模型用分组字段返回",
            "cards": [
                {
                    "action": "新增",
                    "doc_type": "世界观",
                    "标题": "北境世界观",
                    "正文": "北境由雪庭统治。",
                    "source_docs": "doc_world",
                    "conflict_hints": "需要用户确认雪庭统治边界。",
                }
            ],
            "entities": [
                {
                    "op": "add",
                    "entity_type": "faction",
                    "name": "雪庭",
                    "attributes": "北境统治势力",
                }
            ],
        }
    }

    draft = SettingBatchDraft.model_validate(normalize_setting_batch_payload(payload, None))

    assert draft.summary == "模型用分组字段返回"
    assert [change.target_type for change in draft.changes] == ["setting_card", "entity"]
    card_snapshot = draft.changes[0].after_snapshot
    assert card_snapshot["doc_type"] == "worldview"
    assert card_snapshot["title"] == "北境世界观"
    assert card_snapshot["content"] == "北境由雪庭统治。"
    assert card_snapshot["source_doc_ids"] == ["doc_world"]
    assert draft.changes[0].operation == "create"
    assert draft.changes[0].conflict_hints == [
        {"type": "llm_note", "message": "需要用户确认雪庭统治边界。"}
    ]
    assert draft.changes[1].after_snapshot["state"] == {"description": "北境统治势力"}


def test_normalize_setting_batch_payload_preserves_unsafe_relationship_refs_for_rejection():
    payload = {
        "changes": [
            {
                "kind": "关系",
                "action": "新增",
                "after": {
                    "source_name": "陆照",
                    "target_name": "道种",
                    "relation": "持有",
                },
            }
        ]
    }

    normalized = normalize_setting_batch_payload(payload, None)

    with pytest.raises(ValidationError, match="source_id, target_id, and relation_type"):
        SettingBatchDraft.model_validate(normalized)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            [
                {
                    "kind": "entity",
                    "action": "new",
                    "entity_type": "character",
                    "name": "陆照",
                    "profile": {"goal": "寻找道种"},
                }
            ],
            {
                "target_type": "entity",
                "operation": "create",
                "snapshot": {"type": "character", "name": "陆照", "state": {"goal": "寻找道种"}},
            },
        ),
        (
            {
                "payload": {
                    "changes": '[{"kind":"文档","op":"modify","id":"doc_old","category":"核心冲突","name":"主线冲突","body":"陆照与雪庭争夺道种。","evidence_doc_ids":[{"doc_id":"doc_conflict"}]}]'
                }
            },
            {
                "target_type": "setting_card",
                "operation": "update",
                "target_id": "doc_old",
                "snapshot": {
                    "doc_type": "core_conflict",
                    "title": "主线冲突",
                    "content": "陆照与雪庭争夺道种。",
                    "source_doc_ids": ["doc_conflict"],
                },
            },
        ),
        (
            {
                "output": {
                    "records": [
                        {
                            "target": "setting",
                            "action": "archive",
                            "id": "doc_noise",
                            "after": {"archive_reason": "已被整合"},
                        }
                    ]
                }
            },
            {
                "target_type": "setting_card",
                "operation": "delete",
                "target_id": "doc_noise",
                "snapshot": {"doc_type": "setting", "archive_reason": "已被整合"},
            },
        ),
    ],
)
def test_normalize_setting_batch_payload_accepts_multiple_drift_shapes(payload, expected):
    draft = SettingBatchDraft.model_validate(normalize_setting_batch_payload(payload, None))

    change = draft.changes[0]
    assert change.target_type == expected["target_type"]
    assert change.operation == expected["operation"]
    if expected.get("target_id"):
        assert change.target_id == expected["target_id"]
    for key, value in expected["snapshot"].items():
        assert change.after_snapshot[key] == value
