from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novel_dev.testing.generation_runner import make_run_id, validate_run_id
from novel_dev.testing.report import Issue, ReportWriter, TestRunReport


def build_quality_summary_report(
    snapshot: dict[str, Any],
    *,
    run_id: str | None = None,
    duration_seconds: float = 0.0,
) -> TestRunReport:
    resolved_run_id = validate_run_id(run_id) or make_run_id("quality-summary")
    checkpoint = snapshot.get("checkpoint") or snapshot.get("checkpoint_data") or {}
    chapters = snapshot.get("chapters") or []

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

    setting_quality = _quality_report_from_snapshot(snapshot, checkpoint)
    if setting_quality and not setting_quality.get("passed", True):
        report.add_issue(_issue(
            "SETTING-QUALITY-001",
            "setting_generation",
            "AI 自动生成/整合设定质量未通过。",
            _flatten_evidence(setting_quality),
        ))

    synopsis_quality = (
        (checkpoint.get("synopsis_data") or {})
        .get("review_status", {})
        .get("synopsis_quality_report")
    )
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

    for chapter in chapters:
        quality_status = str(chapter.get("quality_status") or "unchecked")
        final_score = chapter.get("final_review_score")
        if quality_status == "block" or (isinstance(final_score, (int, float)) and final_score < 60):
            chapter_id = str(chapter.get("chapter_id") or chapter.get("id") or "unknown")
            evidence = [
                f"chapter_id={chapter_id}",
                f"quality_status={quality_status}",
                f"final_review_score={final_score}",
                *_flatten_evidence(chapter.get("quality_reasons") or {}),
            ]
            report.add_issue(_issue(
                "CHAPTER-QUALITY-001",
                "chapter_final_review",
                "章节质量门禁阻断或成稿评分过低。",
                evidence,
            ))
            break

    return report


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
