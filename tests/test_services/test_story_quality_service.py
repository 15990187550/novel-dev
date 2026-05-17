from novel_dev.schemas.context import BeatPlan, ChapterPlan
from novel_dev.schemas.outline import CharacterArc, PlotMilestone, SynopsisData, VolumeBeat
from novel_dev.services.story_quality_service import StoryQualityService
from novel_dev.agents.setting_workbench_agent import SettingBatchChangeDraft, SettingBatchDraft, SettingWorkbenchAgent
from novel_dev.services.setting_workbench_service import SettingWorkbenchService


def test_setting_quality_blocks_missing_executable_story_foundations():
    report = StoryQualityService.evaluate_setting_payload(
        {
            "worldview": "天玄大陆，宗门林立。",
            "character_profiles": [{"name": "陆照"}],
            "power_system": "",
            "plot_synopsis": "",
        }
    )

    assert report.passed is False
    assert "power_system" in report.missing_sections
    assert any("核心冲突" in issue for issue in report.weaknesses)
    assert any("主角目标" in suggestion for suggestion in report.repair_suggestions)


def test_synopsis_quality_blocks_abstract_conflict_and_missing_volume_promise():
    synopsis = SynopsisData(
        title="天玄纪",
        logline="少年在乱世中成长。",
        core_conflict="正邪对立",
        themes=["成长"],
        character_arcs=[CharacterArc(name="陆照", arc_summary="成长", key_turning_points=["入门"])],
        milestones=[PlotMilestone(act="一", summary="修炼", climax_event="突破")],
        estimated_volumes=1,
        estimated_total_chapters=3,
        estimated_total_words=9000,
        volume_outlines=[],
    )

    report = StoryQualityService.evaluate_synopsis(synopsis)

    assert report.passed is False
    assert report.conflict_score < 75
    assert report.writability_score < 75
    assert any("具体对抗" in issue for issue in report.blocking_issues)


def test_synopsis_quality_accepts_three_milestones_with_four_structural_turns():
    synopsis = SynopsisData(
        title="青云烬",
        logline="林照为查明家族覆灭真相，在青云宗内鬼追杀下争夺父亲留下的禁术证据。",
        core_conflict="林照 vs 渗透青云宗高层的神秘结社，为争夺家族血书与禁术真相生死对抗。",
        themes=["复仇", "信任", "代价"],
        character_arcs=[
            CharacterArc(
                name="林照",
                arc_summary="从隐忍求生到主动揭开宗门阴谋。",
                key_turning_points=["家族覆灭后隐忍", "与沈青衣结盟", "被迫暴露实力", "放弃邪物血脉"],
            ),
            CharacterArc(
                name="沈青衣",
                arc_summary="从独自查案到押上身份保护林照。",
                key_turning_points=["暗中查旧案", "与林照互换线索", "宗门大比护他", "共同离开废墟"],
            ),
        ],
        milestones=[
            PlotMilestone(
                act="第一幕·灰烬重生",
                summary="家族覆灭后，林照失去修为沦为外门废柴；他与沈青衣结盟追查线索，并在第一波刺杀中获得关键证据。",
                climax_event="林照在祖宅密室发现父亲血书，确认青云宗长老涉案，又触发陷阱被黑衣人围杀，被迫逃入禁地。",
            ),
            PlotMilestone(
                act="第二幕·暗流涌动",
                summary="林照在禁地获得残缺上古功法，实力暴涨但反噬埋下隐患；宗门大比中他被迫暴露实力，引发高层追捕。",
                climax_event="上古功法失控反噬，沈青衣当众护他，谢渊拔剑指向林照，临时联盟破裂。",
            ),
            PlotMilestone(
                act="第三幕·灰烬审判",
                summary="幕后结社浮出水面，林照得知身世与千年前封印邪物有关，必须在接受血脉力量和以凡人之躯反抗之间选择。",
                climax_event="林照闯入祖师堂揭开结社阴谋，放弃融合邪物血脉，以父亲禁器击碎阵眼，青云宗根基崩塌。",
            ),
        ],
        estimated_volumes=1,
        estimated_total_chapters=1,
        estimated_total_words=3000,
        volume_outlines=[
            {
                "volume_number": 1,
                "title": "灰烬",
                "summary": "林照在青云宗内追查家族覆灭真相。",
                "narrative_role": "首卷",
                "main_goal": "拿到第一部关键证据",
                "main_conflict": "林照 vs 青云宗内鬼",
                "start_state": "失去修为",
                "end_state": "获得证据",
                "climax": "祖师堂揭露阴谋",
                "hook_to_next": "天穹裂痕出现",
                "target_chapter_range": "1-1",
            }
        ],
    )

    report = StoryQualityService.evaluate_synopsis(synopsis)

    assert report.structure_score == 85
    assert report.passed is True
    assert not any("里程碑不足" in issue or "结构转折不足" in issue for issue in report.warning_issues)


def test_synopsis_quality_blocks_when_structural_turns_are_not_recognizable():
    synopsis = SynopsisData(
        title="天玄纪",
        logline="陆照想在宗门里修炼成长，但旧敌阻止他进入内门。",
        core_conflict="陆照 vs 旧敌，为争夺内门资格持续对抗。",
        themes=["成长"],
        character_arcs=[
            CharacterArc(
                name="陆照",
                arc_summary="从外门弟子成长为内门弟子。",
                key_turning_points=["入门", "修炼", "成长"],
            )
        ],
        milestones=[
            PlotMilestone(act="第一幕", summary="陆照开始修炼，认识宗门环境。", climax_event="陆照完成一次修炼。"),
            PlotMilestone(act="第二幕", summary="陆照继续修炼，实力逐步提高。", climax_event="陆照参加普通比试。"),
            PlotMilestone(act="第三幕", summary="陆照继续成长，准备进入内门。", climax_event="陆照获得新的修炼机会。"),
        ],
        estimated_volumes=1,
        estimated_total_chapters=3,
        estimated_total_words=9000,
        volume_outlines=[
            {
                "volume_number": 1,
                "title": "入门",
                "summary": "陆照在宗门修炼成长。",
                "narrative_role": "首卷",
                "main_goal": "进入内门",
                "main_conflict": "陆照 vs 旧敌",
                "start_state": "外门弟子",
                "end_state": "内门弟子",
                "climax": "比试",
                "hook_to_next": "新的修炼机会",
                "target_chapter_range": "1-3",
            }
        ],
    )

    report = StoryQualityService.evaluate_synopsis(synopsis)

    assert report.passed is False
    assert report.structure_score == 60
    assert any("结构转折不足" in issue for issue in report.warning_issues)
    assert any("改变主角处境" in suggestion for suggestion in report.repair_suggestions)


def test_chapter_writability_requires_conflict_choice_and_hook():
    chapter = VolumeBeat(
        chapter_id="ch_1",
        chapter_number=1,
        title="第一章",
        summary="陆照醒来，了解世界。",
        target_word_count=3000,
        target_mood="平静",
        key_entities=["陆照"],
        beats=[
            BeatPlan(summary="陆照醒来，了解世界。", target_mood="平静", key_entities=["陆照"]),
        ],
    )

    report = StoryQualityService.evaluate_chapter_writability(chapter)

    assert report.passed is False
    assert report.weak_beats == [0]
    assert any("阻力" in issue or "选择" in issue for issue in report.blocking_issues)


def test_chapter_writability_blocks_repeated_generic_repair_constraints():
    generic = "陆照必须在继续行动与保全自身之间做出选择，阻力当场升级，失败代价是失去关键线索并暴露处境，结尾留下新的危险信号。"
    chapter = VolumeBeat(
        chapter_id="ch_generic",
        chapter_number=1,
        title="模板章",
        summary="陆照入门。",
        target_word_count=2000,
        target_mood="紧张",
        key_entities=["陆照"],
        beats=[
            BeatPlan(summary=f"陆照通过入门考核；{generic}", target_mood="紧张", key_entities=["陆照"]),
            BeatPlan(summary=f"陆照被分到杂役处；{generic}", target_mood="压迫", key_entities=["陆照"]),
        ],
    )

    report = StoryQualityService.evaluate_chapter_writability(chapter)

    assert report.passed is False
    assert report.weak_beats == [0, 1]
    assert any("重复使用通用硬约束" in issue for issue in report.blocking_issues)


def test_build_writing_cards_from_executable_chapter_plan():
    plan = ChapterPlan(
        chapter_number=1,
        title="第一章",
        target_word_count=2000,
        beats=[
            BeatPlan(
                summary="陆照为救妹妹潜入药库，却被执事发现；他必须在交出玉佩和暴露身世之间选择，结尾听见追兵逼近。",
                target_mood="紧张",
                key_entities=["陆照", "执事"],
                foreshadowings_to_embed=["玉佩发热"],
            ),
            BeatPlan(
                summary="陆照利用玉佩残光脱身，但发现妹妹病情恶化，决定参加宗门试炼换药。",
                target_mood="压迫",
                key_entities=["陆照"],
            ),
        ],
    )

    cards = StoryQualityService.build_writing_cards(plan)

    assert len(cards) == 2
    assert cards[0].beat_index == 0
    assert "陆照" in cards[0].required_entities
    assert cards[0].conflict
    assert cards[0].ending_hook
    assert cards[0].stake
    assert cards[0].allowed_bridge_details
    assert cards[0].required_payoffs
    assert cards[0].reader_takeaway
    assert "陆照利用玉佩残光脱身" in cards[0].forbidden_future_events
    assert cards[0].target_word_count == 1000
    assert cards[0].source_summary == plan.beats[0].summary
    assert cards[0].readability_contract
    assert cards[0].causal_links
    assert all(len(item) <= 83 for item in cards[0].required_facts)
    assert not any(item == plan.beats[0].summary for item in cards[0].required_facts)


def test_build_writing_cards_extracts_last_beat_payoff_and_reader_hook():
    plan = ChapterPlan(
        chapter_number=1,
        title="试炼惊变",
        target_word_count=1800,
        beats=[
            BeatPlan(
                summary="林照在外门试炼中被狼群围住，必须权衡是否暴露隐藏实力。",
                target_mood="紧张",
                key_entities=["林照"],
            ),
            BeatPlan(
                summary="监视者倒下后，林照搜查遗物发现密函，意识到宗门内应已经盯上他，新的危险信号逼近。",
                target_mood="压迫",
                key_entities=["林照", "监视者"],
                foreshadowings_to_embed=["密函露出林家覆灭线索"],
            ),
        ],
    )

    cards = StoryQualityService.build_writing_cards(plan)

    last = cards[-1]
    assert any("密函" in item for item in last.required_payoffs)
    assert any("危险信号" in item or "内应" in item for item in last.required_payoffs)
    assert "读者" in last.reader_takeaway
    assert "密函" in last.ending_hook


def test_setting_workbench_builds_quality_report_from_generated_draft():
    draft = SettingBatchDraft(
        summary="生成基础设定",
        changes=[
            SettingBatchChangeDraft(
                target_type="setting_card",
                operation="create",
                after_snapshot={
                    "doc_type": "worldview",
                    "title": "世界观",
                    "content": "天玄大陆，宗门林立。",
                },
            )
        ],
    )

    report = SettingWorkbenchService._evaluate_generated_setting_quality(draft)

    assert report.passed is False
    assert "power_system" in report.missing_sections
    assert any("核心冲突" in issue for issue in report.weaknesses)


def test_setting_workbench_quality_accepts_chinese_doc_types_and_string_entity_state():
    draft = SettingBatchDraft(
        summary="生成最小可用设定",
        changes=[
            SettingBatchChangeDraft(
                target_type="setting_card",
                operation="create",
                after_snapshot={
                    "doc_type": "修炼规则",
                    "title": "青云宗修炼体系",
                    "content": "炼气到筑基需要资源、阶段边界和失败代价。",
                },
            ),
            SettingBatchChangeDraft(
                target_type="setting_card",
                operation="create",
                after_snapshot={
                    "doc_type": "核心冲突",
                    "title": "林照调查与玄火盟阻挠",
                    "content": "林照调查家族覆灭真相，玄火盟爪牙试图阻挠并争夺线索。",
                },
            ),
            SettingBatchChangeDraft(
                target_type="entity",
                operation="create",
                after_snapshot={
                    "type": "人物",
                    "name": "林照",
                    "state": "青云宗外门弟子，当前目标是查明家族覆灭真相，必须避开玄火盟眼线。",
                },
            ),
            SettingBatchChangeDraft(
                target_type="setting_card",
                operation="create",
                after_snapshot={
                    "doc_type": "世界观",
                    "title": "世界观",
                    "content": "青云宗统治周边山门，宗门、家族与隐秘势力共同塑造修行秩序。",
                },
            ),
        ],
    )

    report = SettingWorkbenchService._evaluate_generated_setting_quality(draft)

    assert report.passed is True
    assert report.missing_sections == []
    assert report.weaknesses == []


def test_setting_workbench_completes_missing_story_foundation_weaknesses():
    draft = SettingBatchDraft(
        summary="生成基础设定",
        changes=[
            SettingBatchChangeDraft(
                target_type="setting_card",
                operation="create",
                after_snapshot={
                    "doc_type": "worldview",
                    "title": "世界观",
                    "content": "青云宗外门和内门等级森严。",
                },
            ),
            SettingBatchChangeDraft(
                target_type="setting_card",
                operation="create",
                after_snapshot={
                    "doc_type": "power_system",
                    "title": "修炼体系",
                    "content": "炼气到筑基需要资源和失败代价。",
                },
            ),
        ],
    )
    report = SettingWorkbenchService._evaluate_generated_setting_quality(draft)
    session = type("Session", (), {
        "title": "最小验收设定",
        "conversation_summary": "林照出身青云宗外门，目标是查明家族覆灭真相。",
        "target_categories": [],
    })()
    service = SettingWorkbenchService.__new__(SettingWorkbenchService)

    completed = service._complete_generated_setting_draft(
        draft,
        report,
        setting_session=session,
        messages=[{"role": "user", "content": "对立势力包括玄火盟或血海殿，第一章要拿到第一条真相线索。"}],
        current_setting_context={"documents": []},
    )

    completed_report = SettingWorkbenchService._evaluate_generated_setting_quality(completed)
    snapshots = [change.after_snapshot for change in completed.changes]
    titles = [item.get("title") for item in snapshots]
    assert "主角目标与当前动机" in titles
    assert "核心冲突与阻力来源" in titles
    assert completed_report.passed is True


def test_setting_generation_prompt_requires_quality_foundation_contract():
    prompt = SettingWorkbenchAgent.build_generation_prompt(
        title="最小验收设定",
        target_categories=[],
        messages=[{"role": "user", "content": "生成东方玄幻短篇测试小说设定。"}],
    )

    assert "doc_type 使用规范值" in prompt
    assert "worldview" in prompt
    assert "power_system" in prompt
    assert "core_conflict" in prompt
    assert "entity.after_snapshot.state 优先输出结构化对象" in prompt


def test_setting_workbench_completes_missing_worldview_for_target_category():
    draft = SettingBatchDraft(
        summary="生成角色设定",
        changes=[
            SettingBatchChangeDraft(
                target_type="setting_card",
                operation="create",
                after_snapshot={
                    "doc_type": "setting",
                    "title": "修炼体系",
                    "content": "修炼需要资源、阶段边界和失败代价。",
                },
            )
        ],
    )
    report = SettingWorkbenchService._evaluate_generated_setting_quality(draft)
    session = type("Session", (), {
        "title": "世界观补全",
        "conversation_summary": "青云宗外门弟子追查灭门真相。",
        "target_categories": ["worldview"],
    })()
    service = SettingWorkbenchService.__new__(SettingWorkbenchService)

    completed = service._complete_generated_setting_draft(
        draft,
        report,
        setting_session=session,
        messages=[{"role": "user", "content": "青云宗、林家遗孤、莫怀山压迫。"}],
        current_setting_context={"documents": []},
    )

    snapshots = [change.after_snapshot for change in completed.changes]
    assert any(item.get("doc_type") == "worldview" and item.get("content") for item in snapshots)
    assert len(completed.changes) == 2
