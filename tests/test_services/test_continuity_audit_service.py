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


def test_continuity_audit_blocks_dead_character_acting():
    result = ContinuityAuditService.audit_chapter(
        "林照醒来后开口，向殿中众人说出黑水城真相。",
        {
            "active_entities": [
                {"name": "林照", "type": "character", "current_state": "已死亡，尸身留在黑水城"}
            ]
        },
    )

    assert result.status == "block"
    assert result.blocking_items[0]["code"] == "dead_entity_acted"


def test_continuity_audit_ignores_death_terms_outside_entity_condition():
    result = ContinuityAuditService.audit_chapter(
        "林照走来，抬手出手拦住追兵。",
        {
            "active_entities": [
                {
                    "name": "林照",
                    "type": "character",
                    "current_state": (
                        "固定档案: name=林照\n"
                        "当前状态: identity=正统修行者；personality=因拒绝捷径而树敌过多。；"
                        "goal=避免家人死亡的旧事重演；"
                        "ability=投影死亡不影响本体。"
                    ),
                }
            ]
        },
    )

    assert result.status == "pass"
