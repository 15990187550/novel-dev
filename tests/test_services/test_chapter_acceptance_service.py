from novel_dev.services.chapter_acceptance_service import ChapterAcceptanceService


def test_chapter_acceptance_gate_marks_local_issues_as_repairable():
    result = ChapterAcceptanceService.assess(
        content="林照收起残信。他终于意识到麻烦来了。",
        quality_issues=[
            {
                "code": "hook_strength",
                "severity": "warn",
                "evidence": ["残信出现后没有形成可见牵引。"],
                "suggestion": "改成既有残信带来的当场后果。",
            }
        ],
        target_word_count=1200,
    )

    assert result.status == "repairable"
    assert result.continue_policy == "repair_once"
    assert result.repair_directives
    assert result.repair_directives[0]["mode"] == "patch"
    assert result.repair_directives[0]["target"] == "ending"
    assert "残信" in result.repair_directives[0]["instruction"]


def test_chapter_acceptance_gate_pauses_on_blocking_continuity_issue():
    result = ChapterAcceptanceService.assess(
        content="林照走进祠堂。",
        quality_issues=[
            {
                "code": "continuity_audit",
                "severity": "block",
                "message": "上一章角色已经离场，本章仍让他行动。",
            }
        ],
    )

    assert result.status == "manual_review_required"
    assert result.continue_policy == "pause"
    assert result.blocking_issues[0]["category"] == "continuity"


def test_chapter_acceptance_repair_anchor_comes_from_issue_evidence_not_fixed_story_terms():
    result = ChapterAcceptanceService.assess(
        content="程野按住铜扣。门外的脚步忽然停了。",
        quality_issues=[
            {
                "code": "hook_strength",
                "severity": "warn",
                "evidence": ["铜扣出现后没有形成新的风险余波。"],
                "suggestion": "用原文已有物件带出的声音和门外反应形成停点。",
            }
        ],
    )

    instruction = result.repair_directives[0]["instruction"]
    assert "铜扣" in instruction
    assert "残信" not in instruction


def test_chapter_acceptance_does_not_guess_anchor_from_generic_suggestion_or_content():
    result = ChapterAcceptanceService.assess(
        content="程野按住铜扣。门外的脚步忽然停了。",
        quality_issues=[
            {
                "code": "hook_strength",
                "severity": "warn",
                "suggestion": "用原文已有物件带出的声音和门外反应形成停点。",
            }
        ],
    )

    instruction = result.repair_directives[0]["instruction"]
    assert "优先使用原文已有素材：" not in instruction
    assert "铜扣" not in instruction
