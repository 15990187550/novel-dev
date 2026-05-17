from novel_dev.services.continuity_audit_service import ContinuityAuditService


def test_continuity_audit_blocks_canonical_identity_drift():
    result = ContinuityAuditService.audit_chapter(
        "林照以魔门圣子的身份踏入大殿，众人皆向他行礼。",
        {
            "active_entities": [
                {
                    "name": "林照",
                    "type": "character",
                    "current_state": "固定档案: identity_role=青云宗外门弟子",
                    "memory_snapshot": {
                        "canonical_profile": {
                            "identity_role": "青云宗外门弟子",
                            "forbidden_aliases": ["魔门圣子"],
                        },
                        "current_state": {},
                    },
                }
            ]
        },
    )

    assert result.status == "block"
    assert result.blocking_items[0]["code"] == "canonical_identity_drift"


def test_continuity_audit_merges_forbidden_alias_sources_and_string_values():
    result = ContinuityAuditService.audit_chapter(
        "林照以错误身份丙踏入大殿，众人皆向他行礼。",
        {
            "active_entities": [
                {
                    "name": "林照",
                    "type": "character",
                    "current_state": "固定档案: identity_role=身份甲",
                    "forbidden_aliases": ["错误身份甲"],
                    "memory_snapshot": {
                        "forbidden_aliases": "错误身份乙",
                        "canonical_profile": {
                            "identity_role": "身份甲",
                            "forbidden_aliases": ["错误身份丙"],
                        },
                    },
                }
            ]
        },
    )

    assert result.status == "block"
    assert result.blocking_items[0]["detail"]["matched_text"] == "错误身份丙"
