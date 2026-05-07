from novel_dev.testing.quality import (
    QualityFinding,
    validate_chapter,
    validate_cross_stage_consistency,
    validate_outline,
    validate_settings,
)


def test_validate_settings_accepts_complete_material():
    settings = {
        "worldview": "天玄大陆，宗门与王朝并立。",
        "characters": [{"name": "林照", "goal": "查明家族覆灭真相"}],
        "factions": [{"name": "青云宗", "role": "正道宗门"}],
        "locations": [{"name": "青云山", "role": "修行起点"}],
        "rules": ["修为分为炼气、筑基、金丹"],
        "core_conflicts": ["林照与灭门真凶的冲突"],
    }

    findings = validate_settings(settings)

    assert findings == []


def test_validate_settings_reports_missing_required_sections():
    findings = validate_settings({"worldview": "天玄大陆"})

    assert QualityFinding(
        code="SETTINGS_MISSING_CHARACTERS",
        severity="high",
        message="Settings must include at least one character.",
    ) in findings
    assert any(item.code == "SETTINGS_MISSING_CORE_CONFLICTS" for item in findings)


def test_validate_outline_requires_executable_chapters():
    outline = {
        "main_line": "林照查明真相",
        "conflicts": ["宗门试炼"],
        "character_motivations": ["为家族复仇"],
        "chapters": [{"title": "第一章", "beats": ["觉醒血脉"]}],
    }

    assert validate_outline(outline) == []

    findings = validate_outline({"main_line": "林照查明真相", "chapters": []})
    assert any(item.code == "OUTLINE_MISSING_CHAPTERS" for item in findings)


def test_validate_chapter_requires_beat_coverage_and_length():
    chapter = "第一章\n林照在青云山觉醒血脉。随后他拒绝退缩，决定参加宗门试炼。"
    findings = validate_chapter(
        chapter,
        required_beats=["觉醒血脉", "参加宗门试炼"],
        minimum_chars=20,
    )

    assert findings == []

    bad = validate_chapter("第一章\n林照醒来。", ["觉醒血脉", "参加宗门试炼"], 20)
    assert any(item.code == "CHAPTER_TOO_SHORT" for item in bad)
    assert any(item.code == "CHAPTER_MISSING_BEAT" for item in bad)


def test_validate_cross_stage_consistency_flags_undefined_terms():
    findings = validate_cross_stage_consistency(
        allowed_terms={"林照", "青云宗", "青云山"},
        generated_text="林照在青云山遇到玄火盟长老。",
        watched_terms={"玄火盟", "血海殿"},
    )

    assert findings == [
        QualityFinding(
            code="CROSS_STAGE_UNDEFINED_TERM",
            severity="high",
            message="Generated text references undefined term: 玄火盟",
        )
    ]
