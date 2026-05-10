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
                        "canonical_profile": {"identity_role": "青云宗外门弟子"},
                        "current_state": {},
                    },
                }
            ]
        },
    )

    assert result.status == "block"
    assert result.blocking_items[0]["code"] == "canonical_identity_drift"
