import pytest
from pydantic import ValidationError

from novel_dev.agents.setting_workbench_agent import (
    SettingBatchDraft,
    SettingClarificationDecision,
    SettingWorkbenchAgent,
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
