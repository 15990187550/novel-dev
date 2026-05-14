from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novel_dev.schemas.outline import SynopsisData
from novel_dev.schemas.quality import QualityIssue
from novel_dev.services.quality_issue_service import QualityIssueService
from novel_dev.services.story_quality_service import StoryQualityService
from novel_dev.services.story_contract_service import StoryContractService
from novel_dev.testing.generation_runner import make_run_id, validate_run_id
from novel_dev.testing.report import Detail, Issue, ReportWriter, TestRunReport


def build_quality_summary_report(
    snapshot: dict[str, Any],
    *,
    run_id: str | None = None,
    duration_seconds: float = 0.0,
) -> TestRunReport:
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    resolved_run_id = validate_run_id(run_id) or make_run_id("quality-summary")
    checkpoint_value = snapshot.get("checkpoint") or snapshot.get("checkpoint_data") or {}
    checkpoint = checkpoint_value if isinstance(checkpoint_value, dict) else {}
    chapters_value = snapshot.get("chapters") or []
    chapters = chapters_value if isinstance(chapters_value, list) else []
    quality_issues = _quality_issues_from_checkpoint(checkpoint)

    report = TestRunReport(
        run_id=resolved_run_id,
        entrypoint="novel-dev-testing quality-summary",
        status="passed",
        duration_seconds=duration_seconds,
        dataset=str(snapshot.get("dataset") or "snapshot"),
        llm_mode=str(snapshot.get("llm_mode") or "postprocess"),
        artifacts={
            "novel_id": str(snapshot.get("novel_id") or ""),
            "chapter_count": str(len(chapters)),
        },
    )
    _add_quality_issue_artifacts(report, quality_issues)
    _add_standard_quality_issue(report, quality_issues)

    setting_quality = _quality_report_from_snapshot(snapshot, checkpoint)
    story_contract = checkpoint.get("story_contract")
    if not isinstance(story_contract, dict):
        story_contract = StoryContractService.build_from_snapshot(snapshot)
    cross_stage_quality = checkpoint.get("cross_stage_quality")
    if not isinstance(cross_stage_quality, dict):
        cross_stage_quality = StoryContractService.evaluate_cross_stage_quality(snapshot, story_contract)

    _add_longform_scale_detail(report, snapshot, chapters)
    _add_setting_quality_detail(report, setting_quality, snapshot)
    synopsis_quality = _synopsis_quality_from_checkpoint(checkpoint)
    _add_synopsis_quality_detail(report, checkpoint, synopsis_quality)
    _add_volume_quality_detail(report, checkpoint, story_contract, cross_stage_quality)

    if setting_quality and not setting_quality.get("passed", True):
        report.add_issue(_issue(
            "SETTING-QUALITY-001",
            "setting_generation",
            "AI 自动生成/整合设定质量未通过。",
            _flatten_evidence(setting_quality),
        ))

    if synopsis_quality and not synopsis_quality.get("passed", True):
        report.add_issue(_issue(
            "SYNOPSIS-QUALITY-001",
            "brainstorm",
            "总纲质量门禁未通过。",
            _flatten_evidence(synopsis_quality),
        ))

    writability = (
        (checkpoint.get("current_volume_plan") or {})
        .get("review_status", {})
        .get("writability_status")
    )
    if writability and not writability.get("passed", True):
        failed = writability.get("failed_chapter_numbers") or []
        report.add_issue(_issue(
            "VOLUME-WRITABILITY-001",
            "volume_plan",
            "卷纲存在不可直接写正文的章节。",
            [f"failed_chapter_numbers={failed}", *_flatten_evidence(writability)],
        ))

    for item in cross_stage_quality.get("blocking_issues") or []:
        if not isinstance(item, dict):
            continue
        report.add_issue(_issue(
            "CROSS-STAGE-QUALITY-001",
            str(item.get("source_stage") or "cross_stage"),
            str(item.get("message") or "跨阶段故事契约质量未通过。"),
            _flatten_evidence(item),
        ))

    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue
        _add_chapter_quality_detail(report, checkpoint, chapter)
        quality_status = str(chapter.get("quality_status") or "unchecked")
        final_score = chapter.get("final_review_score")
        if quality_status == "block" or (isinstance(final_score, (int, float)) and final_score < 60):
            chapter_id = str(chapter.get("chapter_id") or chapter.get("id") or "unknown")
            target_mismatch = _target_word_count_mismatch(checkpoint, chapter)
            evidence = [
                f"chapter_id={chapter_id}",
                f"quality_status={quality_status}",
                f"final_review_score={final_score}",
                *target_mismatch,
                *_flatten_evidence(chapter.get("quality_reasons") or {}),
            ]
            issue_id = "CHAPTER-TARGET-MISMATCH-001" if target_mismatch else "CHAPTER-QUALITY-001"
            message = (
                "章节质量目标字数来源不一致，质量报告可能存在误判。"
                if target_mismatch
                else "章节质量门禁阻断或成稿评分过低。"
            )
            report.add_issue(_issue(
                issue_id,
                "chapter_final_review",
                message,
                evidence,
            ))
            break

    return report


def _add_longform_scale_detail(
    report: TestRunReport,
    snapshot: dict[str, Any],
    chapters: list[Any],
) -> None:
    target = snapshot.get("acceptance_target")
    source_materials = snapshot.get("source_materials")
    if not isinstance(target, dict) and not isinstance(source_materials, list):
        return

    normalized_chapters = [item for item in chapters if isinstance(item, dict)]
    generated_word_count = sum(_chapter_text_length(item) for item in normalized_chapters)
    source_items = [item for item in source_materials or [] if isinstance(item, dict)]
    source_char_count = sum(_safe_int(item.get("char_count")) or 0 for item in source_items)
    approved_count = sum(1 for item in source_items if str(item.get("status") or "") == "approved")

    if isinstance(target, dict):
        for key in (
            "target_volumes",
            "target_chapters",
            "target_word_count",
            "target_volume_number",
            "target_volume_chapters",
            "target_volume_word_count",
            "chapter_target_word_count",
        ):
            value = _safe_int(target.get(key))
            if value is not None:
                report.artifacts[key] = str(value)

    report.artifacts["generated_chapter_count"] = str(len(normalized_chapters))
    report.artifacts["generated_word_count"] = str(generated_word_count)
    report.artifacts["source_material_count"] = str(len(source_items))
    report.artifacts["source_material_approved_count"] = str(approved_count)
    report.artifacts["source_material_char_count"] = str(source_char_count)

    evidence = [
        f"generated_chapter_count={len(normalized_chapters)}",
        f"generated_word_count={generated_word_count}",
        f"source_material_count={len(source_items)}",
        f"source_material_approved_count={approved_count}",
        f"source_material_char_count={source_char_count}",
    ]
    if isinstance(target, dict):
        evidence.extend(
            f"{key}={target.get(key)}"
            for key in (
                "target_volumes",
                "target_chapters",
                "target_word_count",
                "target_volume_number",
                "target_volume_chapters",
                "target_volume_word_count",
                "chapter_target_word_count",
            )
            if target.get(key) not in (None, "")
        )
    report.details.append(Detail(
        id=f"LONGFORM-SCALE-DETAIL-{len(report.details) + 1:03d}",
        stage="longform_scale",
        title="长篇目标规模与资料导入统计",
        evidence=evidence[:28],
        recommendation=[],
    ))


def _add_setting_quality_detail(
    report: TestRunReport,
    setting_quality: dict[str, Any] | None,
    snapshot: dict[str, Any],
) -> None:
    if not setting_quality and not (snapshot.get("setting_review_batch") or snapshot.get("setting_review_changes")):
        return
    evidence = _flatten_evidence(setting_quality or {})
    batch = snapshot.get("setting_review_batch") if isinstance(snapshot.get("setting_review_batch"), dict) else {}
    if batch:
        evidence.extend(_flatten_evidence({
            "review_batch_status": batch.get("status"),
            "review_batch_summary": batch.get("summary"),
        }))
    report.details.append(Detail(
        id=f"SETTING-QUALITY-DETAIL-{len(report.details) + 1:03d}",
        stage="setting_generation",
        title="世界观与设定质量详情",
        evidence=evidence[:24],
        recommendation=_recommendations_from_quality(setting_quality),
    ))


def _add_synopsis_quality_detail(
    report: TestRunReport,
    checkpoint: dict[str, Any],
    synopsis_quality: dict[str, Any] | None,
) -> None:
    synopsis = checkpoint.get("synopsis_data") if isinstance(checkpoint.get("synopsis_data"), dict) else {}
    review = synopsis.get("review_status") if isinstance(synopsis.get("review_status"), dict) else {}
    if not synopsis and not synopsis_quality:
        return
    evidence = []
    if review.get("overall") is not None:
        evidence.append(f"overall={review.get('overall')}")
    evidence.extend(_flatten_evidence(synopsis_quality or {}))
    if synopsis.get("core_conflict"):
        evidence.append(f"core_conflict={synopsis.get('core_conflict')}")
    report.details.append(Detail(
        id=f"SYNOPSIS-QUALITY-DETAIL-{len(report.details) + 1:03d}",
        stage="brainstorm",
        title="总纲质量详情",
        evidence=evidence[:24],
        recommendation=_recommendations_from_quality(synopsis_quality),
    ))


def _add_volume_quality_detail(
    report: TestRunReport,
    checkpoint: dict[str, Any],
    story_contract: dict[str, Any],
    cross_stage_quality: dict[str, Any],
) -> None:
    plan = checkpoint.get("current_volume_plan") if isinstance(checkpoint.get("current_volume_plan"), dict) else {}
    review = plan.get("review_status") if isinstance(plan.get("review_status"), dict) else {}
    writability = review.get("writability_status") if isinstance(review.get("writability_status"), dict) else {}
    cross_warnings = [
        item for item in (cross_stage_quality.get("warnings") or [])
        if isinstance(item, dict) and item.get("source_stage") != "editing"
    ]
    contract_present = any(
        story_contract.get(key)
        for key in ("protagonist_goal", "current_stage_goal", "first_chapter_goal", "core_conflict")
    )
    if not plan and not writability and not cross_warnings and not contract_present:
        return
    evidence = []
    if review.get("overall") is not None:
        evidence.append(f"overall={review.get('overall')}")
    evidence.extend(_flatten_evidence(writability))
    evidence.extend(
        f"story_contract.{key}={value}"
        for key, value in story_contract.items()
        if key in {"protagonist_goal", "current_stage_goal", "first_chapter_goal", "core_conflict"} and value
    )
    evidence.extend(
        f"cross_stage_warning.{item.get('code')}={item.get('message')}"
        for item in cross_warnings
        if isinstance(item, dict)
    )
    recommendation = _recommendations_from_quality(writability)
    recommendation.extend(
        str(item.get("recommendation"))
        for item in cross_warnings
        if isinstance(item, dict) and item.get("recommendation")
    )
    report.details.append(Detail(
        id=f"VOLUME-QUALITY-DETAIL-{len(report.details) + 1:03d}",
        stage="volume_plan",
        title="卷纲与跨阶段承接质量详情",
        evidence=evidence[:28],
        recommendation=recommendation[:16],
    ))


def _add_chapter_quality_detail(
    report: TestRunReport,
    checkpoint: dict[str, Any],
    chapter: dict[str, Any],
) -> None:
    critique = checkpoint.get("critique_feedback") or {}
    per_dim_issues = checkpoint.get("per_dim_issues") or []
    editor_guard_warnings = checkpoint.get("editor_guard_warnings") or []
    quality_reasons = chapter.get("quality_reasons") or {}
    quality_status = str(chapter.get("quality_status") or "unchecked")
    final_score = chapter.get("final_review_score")
    if quality_status == "unchecked" and final_score is None and not quality_reasons:
        return
    if not any([critique, per_dim_issues, editor_guard_warnings, quality_reasons]):
        return

    chapter_id = str(chapter.get("chapter_id") or chapter.get("id") or "unknown")
    evidence = [
        f"chapter_id={chapter_id}",
        f"quality_status={quality_status}",
        f"final_review_score={final_score}",
    ]
    recommendation: list[str] = []

    if isinstance(critique, dict):
        if critique.get("overall") is not None:
            evidence.append(f"overall={critique.get('overall')}")
        if critique.get("summary"):
            evidence.append(f"summary={critique.get('summary')}")
        breakdown = critique.get("breakdown") or {}
        if isinstance(breakdown, dict):
            for dim, value in breakdown.items():
                score = value.get("score") if isinstance(value, dict) else value
                if score is not None:
                    evidence.append(f"{dim}={score}")

    if isinstance(per_dim_issues, list):
        for issue in per_dim_issues[:8]:
            if not isinstance(issue, dict):
                continue
            dim = issue.get("dim") or "unknown"
            beat = issue.get("beat_idx")
            problem = issue.get("problem")
            suggestion = issue.get("suggestion")
            location = f"beat={beat}" if beat is not None else "whole_chapter"
            if problem:
                evidence.append(f"{dim}.{location}.problem={problem}")
            if suggestion:
                recommendation.append(f"{dim}.{location}.suggestion={suggestion}")

    if isinstance(editor_guard_warnings, list):
        evidence.append(f"editor_guard_warnings_count={len(editor_guard_warnings)}")
        for warning in editor_guard_warnings[:5]:
            if not isinstance(warning, dict):
                continue
            beat = warning.get("beat_index")
            issues = warning.get("issues") or []
            focus = warning.get("suggested_rewrite_focus")
            if issues:
                evidence.append(f"editor_guard.beat={beat}.issues={issues}")
            if focus:
                recommendation.append(f"editor_guard.beat={beat}.focus={focus}")

    if isinstance(quality_reasons, dict):
        for item in (quality_reasons.get("blocking_items") or []) + (quality_reasons.get("warning_items") or []):
            if isinstance(item, dict):
                evidence.append(f"quality_gate.{item.get('code')}={item.get('message')}")

    report.details.append(
        Detail(
            id=f"CHAPTER-QUALITY-DETAIL-{len(report.details) + 1:03d}",
            stage="chapter_final_review",
            title="章节具体质量评价",
            evidence=evidence[:24],
            recommendation=recommendation[:16],
        )
    )


def _recommendations_from_quality(value: dict[str, Any] | None) -> list[str]:
    if not isinstance(value, dict):
        return []
    result: list[str] = []
    for key in ("warnings", "warning_items", "weaknesses", "blocking_issues", "recommendations"):
        items = value.get(key)
        if isinstance(items, list):
            for item in items[:8]:
                if isinstance(item, dict):
                    message = item.get("message") or item.get("recommendation") or item.get("suggestion")
                    if message:
                        result.append(str(message))
                elif item not in (None, "", [], {}):
                    result.append(str(item))
    return result[:16]


def _add_quality_issue_artifacts(report: TestRunReport, issues: list[QualityIssue]) -> None:
    if not issues:
        return
    summary = QualityIssueService.summarize(issues)
    report.artifacts["quality_issue_total"] = str(summary["total"])
    report.artifacts["quality_issue_by_category"] = _format_counter_artifact(summary["by_category"])
    report.artifacts["quality_issue_by_code"] = _format_counter_artifact(summary["by_code"])
    report.artifacts["quality_issue_by_severity"] = _format_counter_artifact(summary["by_severity"])
    report.artifacts["quality_issue_by_repairability"] = _format_counter_artifact(summary["by_repairability"])


def _add_standard_quality_issue(report: TestRunReport, issues: list[QualityIssue]) -> None:
    blocking = [issue for issue in issues if issue.severity == "block"]
    if not blocking:
        return
    report.add_issue(_issue(
        "STANDARD-QUALITY-ISSUE-001",
        "chapter_final_review",
        "标准质量问题包含阻断项。",
        [
            f"quality_issue_total={len(issues)}",
            f"blocking_issue_count={len(blocking)}",
            *[
                f"{issue.code}.{issue.scope}={';'.join(issue.evidence) if issue.evidence else issue.category}"
                for issue in blocking[:8]
            ],
        ],
    ))


def _quality_issues_from_checkpoint(checkpoint: dict[str, Any]) -> list[QualityIssue]:
    if not isinstance(checkpoint, dict):
        return []
    raw_issues = checkpoint.get("quality_issues")
    if not isinstance(raw_issues, list):
        return []
    issues: list[QualityIssue] = []
    for item in raw_issues:
        if not isinstance(item, dict):
            continue
        try:
            issues.append(QualityIssue.model_validate(item))
        except Exception:
            continue
    return issues


def _format_counter_artifact(values: dict[str, int]) -> str:
    return ",".join(f"{key}={values[key]}" for key in sorted(values))


def write_quality_summary_report(
    *,
    input_json: str | Path,
    report_root: str | Path,
    run_id: str | None = None,
) -> TestRunReport:
    snapshot = json.loads(Path(input_json).read_text(encoding="utf-8"))
    report = build_quality_summary_report(snapshot, run_id=run_id)
    ReportWriter(Path(report_root) / report.run_id).write(report)
    return report


def _quality_report_from_snapshot(snapshot: dict[str, Any], checkpoint: dict[str, Any]) -> dict[str, Any] | None:
    direct = checkpoint.get("setting_quality_report")
    if isinstance(direct, dict):
        return direct
    batch_snapshot = snapshot.get("setting_review_batch") or snapshot.get("setting_batch") or {}
    batch_input = batch_snapshot.get("input_snapshot") if isinstance(batch_snapshot, dict) else None
    if isinstance(batch_input, dict) and isinstance(batch_input.get("setting_quality_report"), dict):
        return batch_input["setting_quality_report"]
    return None


def _synopsis_quality_from_checkpoint(checkpoint: dict[str, Any]) -> dict[str, Any] | None:
    synopsis = checkpoint.get("synopsis_data") if isinstance(checkpoint.get("synopsis_data"), dict) else {}
    review = synopsis.get("review_status") if isinstance(synopsis.get("review_status"), dict) else {}
    cached = review.get("synopsis_quality_report") if isinstance(review.get("synopsis_quality_report"), dict) else None
    if not synopsis:
        return cached
    try:
        model = SynopsisData.model_validate(synopsis)
    except Exception:
        return cached
    return StoryQualityService.evaluate_synopsis(model).model_dump()


def _issue(id_: str, stage: str, message: str, evidence: list[str]) -> Issue:
    return Issue(
        id=id_,
        type="GENERATION_QUALITY",
        severity="high",
        stage=stage,
        is_external_blocker=False,
        real_llm=True,
        fake_rerun_status=None,
        message=message,
        evidence=evidence[:12],
        reproduce="novel-dev-testing quality-summary --input-json <snapshot.json>",
    )


def _target_word_count_mismatch(checkpoint: dict[str, Any], chapter: dict[str, Any]) -> list[str]:
    current_plan = checkpoint.get("current_chapter_plan") or {}
    context_plan = (checkpoint.get("chapter_context") or {}).get("chapter_plan") or {}
    current_target = current_plan.get("target_word_count")
    context_target = context_plan.get("target_word_count")
    gate_items = ((chapter.get("quality_reasons") or {}).get("blocking_items") or []) + (
        (chapter.get("quality_reasons") or {}).get("warning_items") or []
    )
    gate_targets = []
    for item in gate_items:
        if not isinstance(item, dict) or item.get("code") != "word_count_drift":
            continue
        detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
        if "target_word_count" in detail:
            gate_targets.append(detail.get("target_word_count"))
    targets = [value for value in [current_target, context_target, *gate_targets] if value not in (None, "")]
    if len({str(value) for value in targets}) <= 1:
        return []
    return [
        "root_cause=checkpoint_target_mismatch",
        f"current_chapter_plan.target_word_count={current_target}",
        f"chapter_context.chapter_plan.target_word_count={context_target}",
        f"quality_gate.target_word_count={gate_targets[0] if gate_targets else None}",
    ]


def _chapter_text_length(chapter: dict[str, Any]) -> int:
    text = chapter.get("polished_text") or chapter.get("raw_draft") or ""
    if not isinstance(text, str):
        return 0
    return len(text.replace(" ", "").replace("\n", ""))


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _flatten_evidence(value: Any, *, prefix: str = "") -> list[str]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, dict):
        result: list[str] = []
        for key, item in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(item, (dict, list)):
                result.extend(_flatten_evidence(item, prefix=next_prefix))
            elif item not in (None, "", [], {}):
                result.append(f"{next_prefix}={item}")
        return result
    if isinstance(value, list):
        return [
            f"{prefix or 'item'}[{index}]={item}"
            for index, item in enumerate(value)
            if item not in (None, "", [], {})
        ]
    return [f"{prefix or 'value'}={value}"]
