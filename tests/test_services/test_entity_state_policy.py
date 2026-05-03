from novel_dev.services.entity_state_policy import EntityStatePolicy


def test_normalize_flat_state_into_structured_layers():
    result = EntityStatePolicy.normalize_update(
        entity_type="character",
        entity_name="陆照",
        latest_state={"name": "陆照", "身份": "主角", "境界": "凡人"},
        extracted_state={"状态": "昏迷"},
        chapter_id="vol_1_ch_1",
        diff_summary={"source": "chapter"},
    )

    assert result.state["canonical_profile"] == {
        "name": "陆照",
        "identity_role": "主角",
    }
    assert result.state["current_state"]["cultivation_level"] == "凡人"
    assert result.state["current_state"]["condition"] == "昏迷"
    assert result.state["observations"] == {}
    assert result.state["canonical_meta"] == {}
    assert any(event["type"] == "flat_state_normalized" for event in result.events)


def test_current_state_fields_replace_previous_current_values():
    result = EntityStatePolicy.normalize_update(
        entity_type="character",
        entity_name="陆照",
        latest_state={
            "canonical_profile": {"name": "陆照", "identity_role": "主角"},
            "current_state": {"condition": "昏迷", "location": "断崖石缝"},
            "observations": {},
            "canonical_meta": {},
        },
        extracted_state={"状态": "清醒但虚弱", "位置": "山村"},
        chapter_id="vol_1_ch_2",
        diff_summary={"source": "chapter"},
    )

    assert result.state["canonical_profile"]["identity_role"] == "主角"
    assert result.state["current_state"]["condition"] == "清醒但虚弱"
    assert result.state["current_state"]["location"] == "山村"


def test_canonical_conflict_is_demoted_to_current_state():
    result = EntityStatePolicy.normalize_update(
        entity_type="character",
        entity_name="陆照",
        latest_state={
            "canonical_profile": {"name": "陆照", "identity_role": "主角"},
            "current_state": {},
            "observations": {},
            "canonical_meta": {"identity_role": {"source": "setting"}},
        },
        extracted_state={"身份": "小人物", "职业": "采药人"},
        chapter_id="vol_1_ch_1",
        diff_summary={"source": "chapter"},
    )

    assert result.state["canonical_profile"]["identity_role"] == "主角"
    assert result.state["current_state"]["social_position"] == "小人物"
    assert result.state["current_state"]["occupation"] == "采药人"
    assert {
        "type": "canonical_conflict_demoted",
        "field": "身份",
        "canonical_field": "identity_role",
        "from": "主角",
        "to": "小人物",
        "written_to": "current_state.social_position",
    } in result.events


def test_empty_canonical_field_can_be_inferred_from_chapter():
    result = EntityStatePolicy.normalize_update(
        entity_type="character",
        entity_name="陆照",
        latest_state={
            "canonical_profile": {"name": "陆照"},
            "current_state": {},
            "observations": {},
            "canonical_meta": {},
        },
        extracted_state={"身份": "主角"},
        chapter_id="vol_1_ch_1",
        diff_summary={"source": "chapter"},
    )

    assert result.state["canonical_profile"]["identity_role"] == "主角"
    assert result.state["canonical_meta"]["identity_role"] == {
        "source": "chapter_inferred",
        "chapter_id": "vol_1_ch_1",
    }
    assert any(event["type"] == "canonical_field_inferred" for event in result.events)


def test_unclassified_fields_are_preserved_as_observations():
    result = EntityStatePolicy.normalize_update(
        entity_type="character",
        entity_name="陆照",
        latest_state=None,
        extracted_state={"变化": "陆照接触古经后昏迷", "奇怪字段": "未知值"},
        chapter_id="vol_1_ch_1",
        diff_summary={"source": "chapter"},
    )

    observations = result.state["observations"]["vol_1_ch_1"]
    assert "变化: 陆照接触古经后昏迷" in observations
    assert "奇怪字段: 未知值" in observations
    assert any(event["type"] == "unclassified_observed" for event in result.events)


def test_non_dict_extracted_state_is_preserved_as_observation():
    result = EntityStatePolicy.normalize_update(
        entity_type="character",
        entity_name="陆照",
        latest_state=None,
        extracted_state="陆照在第一章以采药人身份登场",
        chapter_id="vol_1_ch_1",
        diff_summary={"source": "chapter"},
    )

    assert result.state["canonical_profile"] == {"name": "陆照"}
    assert result.state["current_state"] == {}
    assert result.state["observations"]["vol_1_ch_1"] == [
        "陆照在第一章以采药人身份登场"
    ]


def test_canonical_meta_only_state_is_treated_as_structured():
    result = EntityStatePolicy.normalize_update(
        entity_type="character",
        entity_name="陆照",
        latest_state={
            "canonical_meta": {"identity_role": {"source": "setting"}},
        },
        extracted_state={"状态": "昏迷"},
        chapter_id="vol_1_ch_1",
        diff_summary={"source": "chapter"},
    )

    assert result.state["canonical_meta"] == {
        "identity_role": {"source": "setting"},
    }
    assert result.state["canonical_profile"] == {"name": "陆照"}
    assert result.state["current_state"]["condition"] == "昏迷"
    assert not any(event["type"] == "flat_state_normalized" for event in result.events)


def test_structured_state_preserves_existing_top_level_layers():
    result = EntityStatePolicy.normalize_update(
        entity_type="character",
        entity_name="陆照",
        latest_state={
            "canonical_profile": {"name": "陆照"},
            "current_state": {},
            "observations": {},
            "canonical_meta": {},
            "relationship_state": {"师父": "玄微"},
            "custom_layer": ["kept"],
        },
        extracted_state={"状态": "清醒"},
        chapter_id="vol_1_ch_2",
        diff_summary={"source": "chapter"},
    )

    assert result.state["relationship_state"] == {"师父": "玄微"}
    assert result.state["custom_layer"] == ["kept"]
    assert result.state["current_state"]["condition"] == "清醒"


def test_structured_state_with_legacy_keys_folds_them_into_layers():
    result = EntityStatePolicy.normalize_update(
        entity_type="character",
        entity_name="陆照",
        latest_state={
            "canonical_meta": {"identity_role": {"source": "setting"}},
            "身份": "主角",
            "境界": "凡人",
        },
        extracted_state={"身份": "小人物"},
        chapter_id="vol_1_ch_1",
        diff_summary={"source": "chapter"},
    )

    assert result.state["canonical_profile"]["identity_role"] == "主角"
    assert result.state["current_state"]["cultivation_level"] == "凡人"
    assert result.state["current_state"]["social_position"] == "小人物"
    assert {
        "type": "canonical_conflict_demoted",
        "field": "身份",
        "canonical_field": "identity_role",
        "from": "主角",
        "to": "小人物",
        "written_to": "current_state.social_position",
    } in result.events


def test_normalize_update_does_not_mutate_input_observations():
    latest_state = {
        "canonical_profile": {"name": "陆照"},
        "current_state": {},
        "observations": {"vol_1_ch_1": ["旧观察"]},
        "canonical_meta": {},
    }

    result = EntityStatePolicy.normalize_update(
        entity_type="character",
        entity_name="陆照",
        latest_state=latest_state,
        extracted_state={"变化": "新增观察"},
        chapter_id="vol_1_ch_1",
        diff_summary={"source": "chapter"},
    )

    assert latest_state["observations"]["vol_1_ch_1"] == ["旧观察"]
    assert result.state["observations"]["vol_1_ch_1"] == [
        "旧观察",
        "变化: 新增观察",
    ]
