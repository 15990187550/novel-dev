from novel_dev.services.story_contract_service import StoryContractService


def test_story_contract_extracts_cross_stage_contract_fields():
    snapshot = {
        "checkpoint": {
            "synopsis_data": {
                "core_conflict": "林照追查家族覆灭真相，对抗血煞盟。",
                "volume_outlines": [
                    {
                        "volume_number": 1,
                        "main_goal": "找到父亲玉佩里的第一条线索",
                        "main_conflict": "林照被血煞盟追索",
                    }
                ],
            }
        },
        "setting_review_changes": [
            {
                "object_type": "setting_card",
                "after_snapshot": {
                    "doc_type": "plot",
                    "title": "第一章启动事件",
                    "content": "第一章让林照在祠堂找到父亲留下的玉佩，确认家族覆灭另有隐情。",
                },
            },
            {
                "object_type": "entity",
                "after_snapshot": {
                    "type": "character",
                    "name": "林照",
                    "current_state": "主角，目标是追查家族覆灭真相。",
                },
            },
        ],
    }

    contract = StoryContractService.build_from_snapshot(snapshot)

    assert contract["protagonist_goal"] == "追查家族覆灭真相"
    assert "血煞盟" in contract["core_conflict"]
    assert "父亲留下的玉佩" in contract["first_chapter_goal"]
    assert "父亲" in contract["must_carry_forward"]
    assert "线索" in contract["must_carry_forward"]


def test_story_contract_warns_when_first_chapter_goal_drifts_from_volume_plan():
    snapshot = {
        "setting_review_changes": [
            {
                "object_type": "setting_card",
                "after_snapshot": {
                    "doc_type": "plot",
                    "title": "第一章启动事件",
                    "content": "第一章应让林照在祠堂找到父亲玉佩，借此进入家族覆灭真相。",
                },
            }
        ],
        "checkpoint": {
            "current_volume_plan": {
                "chapters": [
                    {
                        "chapter_number": 1,
                        "summary": "林照在后山发现兄长遗物与残图玉简，被迫逃离巡逻队。",
                    }
                ]
            }
        },
    }

    contract = StoryContractService.build_from_snapshot(snapshot)
    quality = StoryContractService.evaluate_cross_stage_quality(snapshot, contract)

    assert quality["passed"] is True
    assert quality["warnings"][0]["code"] == "first_chapter_goal_drift"
    assert quality["warnings"][0]["source_stage"] == "volume_plan"
    assert "父亲" in quality["warnings"][0]["evidence"]


def test_story_contract_attributes_editor_plan_external_warnings():
    snapshot = {
        "checkpoint": {
            "editor_guard_warnings": [
                {
                    "beat_index": 0,
                    "issues": ["新增计划外物证：银线袖口"],
                    "introduced_plan_external_fact": True,
                    "suggested_rewrite_focus": "移除银线袖口，回到玉佩线索",
                }
            ]
        }
    }

    quality = StoryContractService.evaluate_cross_stage_quality(
        snapshot,
        StoryContractService.build_from_snapshot(snapshot),
    )

    assert quality["warnings"][0]["code"] == "editor_plan_external_fact"
    assert quality["warnings"][0]["source_stage"] == "editing"
    assert "银线袖口" in quality["warnings"][0]["evidence"]
