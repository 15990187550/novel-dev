import pytest

from novel_dev.schemas.context import BeatPlan, LocationContext, NarrativeRelay
from novel_dev.schemas.librarian import ExtractionResult
from novel_dev.schemas.outline import SynopsisData, VolumeBeat
from novel_dev.schemas.review import FastReviewReport, ScoreResult
from novel_dev.agents.setting_workbench_agent import SettingBatchDraft


def test_outline_coerces_text_and_string_list_fields():
    data = SynopsisData(
        title={"主标题": "试炼"},
        logline=["少年", "夺回命运"],
        core_conflict={"主角": "林风", "阻力": "宗门阴谋"},
        themes={"主题一": "成长", "主题二": "复仇"},
        character_arcs=[
            {"name": {"本名": "林风"}, "arc_summary": ["失去", "觉醒"], "key_turning_points": {"一": "入宗", "二": "背叛"}}
        ],
        milestones=[{"act": {"阶段": "第一幕"}, "summary": ["入局"], "climax_event": {"事件": "夺剑"}}],
        estimated_volumes=1,
        estimated_total_chapters=10,
        estimated_total_words=30000,
    )

    assert data.title == "主标题: 试炼"
    assert data.logline == "少年\n夺回命运"
    assert data.themes == ["主题一: 成长", "主题二: 复仇"]
    assert data.character_arcs[0].name == "本名: 林风"
    assert data.character_arcs[0].key_turning_points == ["一: 入宗", "二: 背叛"]
    assert data.milestones[0].climax_event == "事件: 夺剑"


def test_volume_beat_coerces_text_and_string_list_fields_but_keeps_numbers_strict():
    beat = VolumeBeat(
        chapter_id="ch_1",
        chapter_number=1,
        title={"标题": "暗潮"},
        summary=["宗门", "风波"],
        target_word_count=3000,
        target_mood={"情绪": "tense"},
        key_entities={"主角": "林风"},
        foreshadowings_to_embed={"伏笔": "玉佩发烫"},
        foreshadowings_to_recover="玉佩来历",
        beats=[{"summary": {"目标": "冲突升级"}, "target_mood": ["紧张", "压迫"], "key_entities": "林风"}],
    )

    assert beat.title == "标题: 暗潮"
    assert beat.summary == "宗门\n风波"
    assert beat.target_mood == "情绪: tense"
    assert beat.key_entities == ["主角: 林风"]
    assert beat.foreshadowings_to_embed == ["伏笔: 玉佩发烫"]
    assert beat.foreshadowings_to_recover == ["玉佩来历"]
    assert beat.beats[0].summary == "目标: 冲突升级"
    assert beat.beats[0].key_entities == ["林风"]

    with pytest.raises(ValueError):
        VolumeBeat(
            chapter_id="ch_bad",
            chapter_number="第一章",
            title="坏章",
            summary="坏",
            target_word_count=3000,
            target_mood="tense",
        )


def test_context_coerces_text_and_string_list_fields():
    beat = BeatPlan(
        summary={"目标": "逼出底牌"},
        target_mood=["tense", "dark"],
        key_entities={"人物": "林风"},
        foreshadowings_to_embed="玉佩异动",
    )
    relay = NarrativeRelay(
        scene_state={"场景": "雨夜"},
        emotional_tone=["压抑", "紧迫"],
        new_info_revealed={"线索": "掌门说谎"},
        open_threads={"悬念": "玉佩来历"},
        next_beat_hook=["门外", "脚步声"],
    )
    location = LocationContext(current={"地点": "青云宗"}, parent={"上级": "东域"}, narrative=["山门", "古旧"])

    assert beat.summary == "目标: 逼出底牌"
    assert beat.key_entities == ["人物: 林风"]
    assert relay.scene_state == "场景: 雨夜"
    assert relay.next_beat_hook == "门外\n脚步声"
    assert location.current == "地点: 青云宗"
    assert location.narrative == "山门\n古旧"


def test_review_coerces_text_and_string_list_fields_but_keeps_scores_strict():
    result = ScoreResult(
        overall=88,
        dimensions=[{"name": {"维度": "plot"}, "score": 80, "comment": ["紧张", "有效"]}],
        summary_feedback={"总结": "可用"},
        per_dim_issues=[{"dim": {"维度": "plot"}, "problem": ["冲突偏弱"], "suggestion": {"建议": "加压"}}],
    )
    report = FastReviewReport(
        word_count_ok=True,
        consistency_fixed=True,
        ai_flavor_reduced=False,
        beat_cohesion_ok=True,
        notes={"问题": "钩子不足"},
    )

    assert result.dimensions[0].name == "维度: plot"
    assert result.dimensions[0].comment == "紧张\n有效"
    assert result.summary_feedback == "总结: 可用"
    assert result.per_dim_issues[0].suggestion == "建议: 加压"
    assert report.notes == ["问题: 钩子不足"]

    with pytest.raises(ValueError):
        ScoreResult(overall="高", dimensions=[], summary_feedback="bad")


def test_score_result_normalizes_dimension_schema_drift_from_llm():
    result = ScoreResult.model_validate({
        "dimensions": [
            {"dim": "plot_tension", "score": 80, "per_dim_issues": []},
            {
                "dim": "readability",
                "score": 68,
                "per_dim_issues": [
                    {
                        "dim": "readability",
                        "beat_idx": 1,
                        "problem": "第1个 beat 重复发现古经的信息。",
                        "suggestion": "合并重复描写, 保留一次识海震动。",
                    }
                ],
            },
            {"dim": "hook_strength", "score": 95, "per_dim_issues": []},
        ],
        "summary_feedback": "节奏可读, 但重复描写需要压缩。",
    })

    assert result.overall == 81
    assert [dimension.name for dimension in result.dimensions] == [
        "plot_tension",
        "readability",
        "hook_strength",
    ]
    assert result.dimensions[1].comment == ""
    assert result.per_dim_issues[0].dim == "readability"
    assert result.per_dim_issues[0].beat_idx == 1


def test_librarian_coerces_text_and_recovered_id_list_fields():
    result = ExtractionResult(
        timeline_events=[{"tick": 1, "narrative": {"事件": "玉佩发光"}}],
        spaceline_changes=[{"location_id": "loc_1", "name": {"地点": "禁地"}, "narrative": ["阴冷", "封闭"]}],
        new_entities=[{"type": {"类型": "artifact"}, "name": ["血玉", "残片"], "state": {"owner": "林风"}}],
        foreshadowings_recovered={"伏笔": "玉佩来历"},
        new_foreshadowings=[{"content": {"悬念": "血玉低语"}}],
        new_relationships=[{"source_entity_id": "e1", "target_entity_id": "e2", "relation_type": {"关系": "持有"}}],
    )

    assert result.timeline_events[0].narrative == "事件: 玉佩发光"
    assert result.spaceline_changes[0].name == "地点: 禁地"
    assert result.new_entities[0].type == "类型: artifact"
    assert result.new_entities[0].name == "血玉\n残片"
    assert result.foreshadowings_recovered == ["伏笔: 玉佩来历"]
    assert result.new_foreshadowings[0].content == "悬念: 血玉低语"
    assert result.new_relationships[0].relation_type == "关系: 持有"


def test_librarian_parses_stringified_json_array_fields_from_structured_payload():
    result = ExtractionResult.model_validate({
        "new_entities": '[{"type": "artifact", "name": "无名古经", "state": {"位置": "竹篓"}}]',
        "concept_updates": '[{"entity_id": "识海", "state": {"状态": "震动"}, "diff_summary": {"source": "chapter"}}]',
        "character_updates": '[{"entity_id": "陆照", "state": {"状态": "昏迷"}, "diff_summary": {"source": "chapter"}}]',
        "new_relationships": '[{"source_entity_id": "陆照", "target_entity_id": "无名古经", "relation_type": "持有", "meta": {"状态": "已放入竹篓"}}]',
    })

    assert result.new_entities[0].name == "无名古经"
    assert result.concept_updates[0].entity_id == "识海"
    assert result.character_updates[0].state == {"状态": "昏迷"}
    assert result.new_relationships[0].relation_type == "持有"


def test_setting_batch_draft_parses_stringified_changes_array_from_structured_payload():
    result = SettingBatchDraft.model_validate({
        "summary": "生成全量设定",
        "changes": '[{"target_type": "setting_card", "operation": "create", "after_snapshot": {"doc_type": "worldview", "title": "世界观", "content": "灵潮复苏。"}, "source_ref": "全量设定"}]',
    })

    assert len(result.changes) == 1
    assert result.changes[0].target_type == "setting_card"
    assert result.changes[0].after_snapshot["doc_type"] == "worldview"


def test_setting_batch_draft_parses_double_encoded_changes_array():
    result = SettingBatchDraft.model_validate({
        "summary": "生成全量设定",
        "changes": '"[{\\"target_type\\": \\"setting_card\\", \\"operation\\": \\"create\\", \\"after_snapshot\\": {\\"doc_type\\": \\"power_system\\", \\"title\\": \\"修炼体系\\", \\"content\\": \\"内天地到外天地。\\"}, \\"source_ref\\": \\"全量设定\\"}]"',
    })

    assert len(result.changes) == 1
    assert result.changes[0].after_snapshot["title"] == "修炼体系"


def test_setting_batch_draft_parses_stringified_changes_array_with_trailing_fragment():
    result = SettingBatchDraft.model_validate({
        "summary": "生成全量设定",
        "changes": (
            '[{"target_type": "setting_card", "operation": "create", '
            '"after_snapshot": {"doc_type": "worldview", "title": "世界观", "content": "灵潮复苏。"}, '
            '"source_ref": "全量设定"}]}'
        ),
    })

    assert len(result.changes) == 1
    assert result.changes[0].after_snapshot["title"] == "世界观"


def test_setting_batch_draft_parses_stringified_changes_array_with_raw_content_newlines():
    result = SettingBatchDraft.model_validate({
        "summary": "生成外部宇宙设定",
        "changes": (
            '[{"target_type": "setting_card", "operation": "create", '
            '"after_snapshot": {"doc_type": "plot", "title": "18卷整体结构规划", "content": "## 18卷整体结构规划\n\n'
            '### 核心叙事模式\n- 真实界与外部宇宙穿插推进。"}, '
            '"source_ref": "批次1"}]}'
        ),
    })

    assert len(result.changes) == 1
    assert "核心叙事模式" in result.changes[0].after_snapshot["content"]


def test_setting_batch_draft_parses_stringified_changes_array_with_line_continuation():
    result = SettingBatchDraft.model_validate({
        "summary": "生成外部宇宙设定",
        "changes": (
            '[{"target_type": "setting_card", "operation": "create", '
            '"after_snapshot": {"doc_type": "plot", "title": "跨作品联动", "content": "第一阶段\\\n'
            '第二阶段"}, "source_ref": "批次3"}]'
        ),
    })

    assert len(result.changes) == 1
    assert "第二阶段" in result.changes[0].after_snapshot["content"]


def test_setting_batch_draft_coerces_string_conflict_hints_to_dicts():
    result = SettingBatchDraft.model_validate({
        "summary": "生成外部宇宙设定",
        "changes": [
            {
                "target_type": "setting_card",
                "operation": "create",
                "after_snapshot": {
                    "doc_type": "plot",
                    "title": "跨作品联动",
                    "content": "诛仙、盘龙对标关系待确认。",
                },
                "conflict_hints": [
                    "诛仙、盘龙的世界对标关系待确认",
                    {"type": "source_gap", "message": "外部宇宙进入时机待确认"},
                ],
            }
        ],
    })

    assert result.changes[0].conflict_hints == [
        {"type": "llm_note", "message": "诛仙、盘龙的世界对标关系待确认"},
        {"type": "source_gap", "message": "外部宇宙进入时机待确认"},
    ]


def test_librarian_coerces_text_diff_summary_to_dict():
    result = ExtractionResult.model_validate({
        "character_updates": [{
            "entity_id": "陆照",
            "state": {"身份认知": "被无名古经选中"},
            "diff_summary": "陆照从贫穷采药人转变为被超凡力量选中的觉醒者。",
        }],
    })

    assert result.character_updates[0].diff_summary == {
        "summary": "陆照从贫穷采药人转变为被超凡力量选中的觉醒者。"
    }


def test_librarian_coerces_blank_spaceline_parent_to_none():
    result = ExtractionResult.model_validate({
        "spaceline_changes": [{
            "location_id": "山村",
            "name": "山村",
            "parent_id": "   ",
            "narrative": "一座偏僻山村",
        }],
    })

    assert result.spaceline_changes[0].parent_id is None


def test_librarian_normalizes_common_extraction_shape_drift_from_llm():
    result = ExtractionResult.model_validate({
        "timeline_events": [{
            "tick": 0,
            "description": "光波动迅速逼近",
        }],
        "new_entities": [{
            "type": "mysterious_book",
            "name": "潜入和信息传输",
            "state": "意识相连",
        }],
        "concept_updates": [{
            "id": "world_plant_anomaly",
            "name": "白药的止血效果",
        }],
        "character_updates": [{
            "name": "陆照",
            "change": "昏迷前感知到远处破空声",
        }],
    })

    assert result.timeline_events[0].narrative == "光波动迅速逼近"
    assert result.new_entities[0].state == {"value": "意识相连"}
    assert result.concept_updates[0].entity_id == "world_plant_anomaly"
    assert result.concept_updates[0].state == {"name": "白药的止血效果"}
    assert result.concept_updates[0].diff_summary == {"source": "llm_shape_drift"}
    assert result.character_updates[0].entity_id == "陆照"
    assert result.character_updates[0].state == {"change": "昏迷前感知到远处破空声"}
    assert result.character_updates[0].diff_summary == {
        "summary": "昏迷前感知到远处破空声"
    }
