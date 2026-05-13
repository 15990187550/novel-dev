from types import SimpleNamespace

from novel_dev.testing.generation_contracts import (
    build_volume_plan_contract_evidence,
    classify_export_result,
    detect_chapter_text,
    extract_chapter_plan,
    summarize_chapter_counts,
    summarize_quality_gate,
)


def test_extract_chapter_plan_from_current_chapter_plan():
    response = {"volume_id": "vol-1"}
    checkpoint = {
        "current_chapter_plan": {
            "chapter_id": "ch-1",
            "chapter_number": 2,
            "title": "First Plan",
            "summary": "A usable summary",
            "beats": [{"summary": "beat"}],
        }
    }

    result = extract_chapter_plan(response, checkpoint)

    assert result is not None
    assert result.source == "current_chapter_plan"
    assert result.plan["chapter_id"] == "ch-1"


def test_extract_chapter_plan_from_current_volume_plan_chapters():
    response = {"volume_id": "vol-1"}
    checkpoint = {
        "current_volume_plan": {
            "chapters": [
                {
                    "chapter_id": "ch-2",
                    "chapter_number": 1,
                    "title": "Volume Chapter",
                    "summary": "A usable summary",
                }
            ]
        }
    }

    result = extract_chapter_plan(response, checkpoint)

    assert result is not None
    assert result.source == "current_volume_plan.chapters[0]"
    assert result.plan["chapter_id"] == "ch-2"


def test_extract_chapter_plan_from_response_chapter():
    response = {
        "chapter": {
            "chapter_id": "ch-3",
            "chapter_number": 1,
            "title": "Response Chapter",
            "summary": "A usable summary",
        }
    }
    checkpoint = {}

    result = extract_chapter_plan(response, checkpoint)

    assert result is not None
    assert result.source == "response.chapter"
    assert result.plan["chapter_id"] == "ch-3"


def test_extract_chapter_plan_from_response_current_chapter_plan():
    response = {
        "current_chapter_plan": {
            "chapter_id": "ch-4",
            "chapter_number": 3,
            "title": "Response Plan",
            "summary": "A usable summary",
        }
    }
    checkpoint = {}

    result = extract_chapter_plan(response, checkpoint)

    assert result is not None
    assert result.source == "response.current_chapter_plan"
    assert result.plan["chapter_id"] == "ch-4"


def test_extract_chapter_plan_rejects_plan_without_text_material():
    response = {}
    checkpoint = {"current_chapter_plan": {"chapter_id": "ch-5", "chapter_number": 1}}

    assert extract_chapter_plan(response, checkpoint) is None


def test_extract_chapter_plan_rejects_whitespace_only_text_material():
    response = {}
    checkpoint = {
        "current_chapter_plan": {
            "chapter_id": "ch-6",
            "chapter_number": 1,
            "title": "   ",
            "summary": "\n\t",
        }
    }

    assert extract_chapter_plan(response, checkpoint) is None


def test_extract_chapter_plan_handles_non_dict_inputs():
    assert extract_chapter_plan(None, None) is None
    assert extract_chapter_plan("bad", ["bad"]) is None


def test_build_volume_plan_contract_evidence_lists_keys_and_counts():
    response = {"volume_id": "vol-1"}
    checkpoint = {
        "synopsis_data": {},
        "current_volume_plan": {"volume_id": "vol-1", "chapters": []},
    }

    evidence = build_volume_plan_contract_evidence(response, checkpoint)

    assert "response_keys=volume_id" in evidence
    assert "checkpoint_keys=current_volume_plan,synopsis_data" in evidence
    assert "current_chapter_plan_present=false" in evidence
    assert "current_volume_plan_keys=chapters,volume_id" in evidence
    assert "current_volume_plan_chapter_count=0" in evidence


def test_build_volume_plan_contract_evidence_handles_non_dict_inputs():
    evidence = build_volume_plan_contract_evidence(None, "bad")

    assert "response_keys=none" in evidence
    assert "checkpoint_keys=none" in evidence
    assert "current_volume_plan_present=false" in evidence


def test_detect_chapter_text_prefers_polished_text():
    chapter = SimpleNamespace(raw_draft="raw text", polished_text="polished text")

    status = detect_chapter_text(chapter)

    assert status.field == "polished_text"
    assert status.length == len("polished text")
    assert status.has_text is True


def test_detect_chapter_text_falls_back_to_raw_draft():
    chapter = SimpleNamespace(raw_draft="raw text", polished_text="   ")

    status = detect_chapter_text(chapter)

    assert status.field == "raw_draft"
    assert status.length == len("raw text")
    assert status.has_text is True


def test_detect_chapter_text_ignores_non_string_payloads():
    chapter = SimpleNamespace(raw_draft=["not", "text"], polished_text={"bad": "type"})

    status = detect_chapter_text(chapter)

    assert status.field == "none"
    assert status.length == 0
    assert status.has_text is False


def test_detect_chapter_text_handles_missing_chapter():
    status = detect_chapter_text(None)

    assert status.field == "none"
    assert status.length == 0
    assert status.has_text is False


def test_detect_chapter_text_reads_dict_payloads():
    status = detect_chapter_text({"raw_draft": "raw text", "polished_text": " polished text "})

    assert status.field == "polished_text"
    assert status.length == len("polished text")
    assert status.has_text is True


def test_summarize_chapter_counts_separates_generated_archived_blocked_pending():
    chapters = [
        {"chapter_id": "ch-1", "status": "archived", "polished_text": "正文", "quality_status": "pass"},
        {"chapter_id": "ch-2", "status": "edited", "polished_text": "正文", "quality_status": "block"},
        {"chapter_id": "ch-3", "status": "pending", "polished_text": "", "quality_status": "unchecked"},
    ]

    counts = summarize_chapter_counts(chapters)

    assert counts == {
        "planned": 3,
        "generated_text": 2,
        "archived": 1,
        "blocked": 1,
        "pending": 1,
    }


def test_summarize_chapter_counts_counts_non_dict_entries_as_planned_only():
    counts = summarize_chapter_counts([{"status": "pending"}, "bad"])

    assert counts["planned"] == 2
    assert counts["pending"] == 1
    assert counts["generated_text"] == 0


def test_summarize_chapter_counts_handles_non_list_input_as_empty():
    assert summarize_chapter_counts({"status": "pending"}) == {
        "planned": 0,
        "generated_text": 0,
        "archived": 0,
        "blocked": 0,
        "pending": 0,
    }


def test_classify_export_result_distinguishes_missing_reasons():
    assert classify_export_result({}, archived_chapter_count=0) == "no_archived_chapters"
    assert classify_export_result({}, archived_chapter_count=2) == "export_not_requested"
    assert classify_export_result({"exported_path": ""}, archived_chapter_count=2) == "export_failed"
    assert classify_export_result({"exported_path": "/tmp/out.md"}, archived_chapter_count=2) == "export_succeeded"
    assert classify_export_result({"exported_path": "/tmp/out.md"}, archived_chapter_count=0) == "export_succeeded"
    assert classify_export_result(None, archived_chapter_count=0) == "no_archived_chapters"


def test_summarize_quality_gate_returns_status_and_reasons():
    chapter = SimpleNamespace(
        quality_status="block",
        quality_reasons={"word_count_drift": "too short"},
    )

    summary = summarize_quality_gate(chapter)

    assert summary.status == "block"
    assert "word_count_drift" in summary.reasons


def test_summarize_quality_gate_handles_missing_chapter():
    summary = summarize_quality_gate(None)

    assert summary.status == "missing_chapter"
    assert summary.reasons == ""


def test_summarize_quality_gate_defaults_missing_values():
    chapter = SimpleNamespace()

    summary = summarize_quality_gate(chapter)

    assert summary.status == "unchecked"
    assert summary.reasons == ""


def test_summarize_quality_gate_defaults_falsey_status_and_stringifies_reasons():
    chapter = SimpleNamespace(quality_status="", quality_reasons=["needs review"])

    summary = summarize_quality_gate(chapter)

    assert summary.status == "unchecked"
    assert summary.reasons == "needs review"


def test_summarize_quality_gate_flattens_non_dict_reason_sequences():
    chapter = SimpleNamespace(
        quality_status="warn",
        quality_reasons=("too short", "missing beat"),
    )

    summary = summarize_quality_gate(chapter)

    assert summary.status == "warn"
    assert summary.reasons == "too short,missing beat"


def test_summarize_quality_gate_sorts_unordered_reason_containers():
    chapter = SimpleNamespace(
        quality_status="warn",
        quality_reasons={"missing beat", "too short"},
    )

    summary = summarize_quality_gate(chapter)

    assert summary.status == "warn"
    assert summary.reasons == "missing beat,too short"
