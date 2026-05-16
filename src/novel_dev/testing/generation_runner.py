from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Any, Awaitable, Callable, Literal

import httpx
from sqlalchemy import select
from novel_dev.db.models import Chapter
from novel_dev.db.engine import async_session_maker
from novel_dev.llm.exceptions import LLMRateLimitError, LLMTimeoutError
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.setting_workbench_repo import SettingWorkbenchRepository
from novel_dev.agents.director import Phase
from novel_dev.testing.generation_contracts import (
    build_volume_plan_contract_evidence,
    detect_chapter_text,
    extract_chapter_plan,
    summarize_quality_gate,
)
from novel_dev.testing.fixtures import GenerationFixture, load_generation_fixture
from novel_dev.testing.quality import validate_outline, validate_settings
from novel_dev.testing.report import Issue, IssueType, ReportWriter, TestRunReport
from novel_dev.services.story_contract_service import StoryContractService


LLMMode = Literal["fake", "real", "real_then_fake_on_external_block"]
AcceptanceScope = Literal["real-contract", "real-e2e-export", "real-longform-volume1"]
Step = Callable[[], Awaitable[None]]
API_GENERATION_STAGES = (
    "preflight_health",
    "create_novel",
    "create_setting_session",
    "advance_setting_session",
    "generate_setting_review_batch",
    "apply_generated_settings",
    "upload_seed_setting",
    "upload_source_materials",
    "approve_seed_setting",
    "approve_source_materials",
    "consolidate_settings",
    "apply_consolidated_settings",
    "brainstorm",
    "volume_plan",
    "auto_run_chapters",
    "export",
)
MAX_SETTING_CLARIFICATION_ROUNDS = 5
API_SMOKE_TIMEOUT_SECONDS = 600
GENERATION_JOB_POLL_INTERVAL_SECONDS = 2
GENERATION_JOB_MAX_POLLS = 900
ACCEPTANCE_TARGET_WORD_COUNT_FLOOR = 1000


@dataclass(frozen=True, slots=True)
class MinimalChapterPlanResult:
    chapter_id: str
    volume_id: str
    source: str
    target_word_count: int


@dataclass(frozen=True, slots=True)
class BrainstormContractResult:
    original_estimated_volumes: int | None
    original_estimated_total_chapters: int | None
    shrunk_estimated_total_chapters: int


@dataclass(frozen=True, slots=True)
class SourceMaterial:
    filename: str
    path: str
    content: str
    char_count: int
    byte_count: int


def _acceptance_target_word_count(fixture: GenerationFixture) -> int:
    return max(ACCEPTANCE_TARGET_WORD_COUNT_FLOOR, fixture.minimum_chapter_chars)


class ContractValidationError(RuntimeError):
    def __init__(self, stage: str, message: str, evidence: list[str]):
        super().__init__(message)
        self.stage = stage
        self.evidence = evidence


@dataclass(frozen=True, slots=True)
class GenerationRunOptions:
    dataset: str = "minimal_builtin"
    llm_mode: LLMMode = "real_then_fake_on_external_block"
    acceptance_scope: AcceptanceScope = "real-contract"
    stage: str | None = None
    run_id: str | None = None
    report_root: str = "reports/test-runs"
    api_base_url: str = "http://127.0.0.1:8000"
    resume_novel_id: str | None = None
    resume_from_stage: str | None = None
    resume_reset_current_chapter: bool = False
    source_dir: str | None = None
    target_volumes: int = 18
    target_chapters: int = 1200
    target_word_count: int = 2_000_000
    target_volume_number: int = 1
    target_volume_chapters: int | None = None

    def resolved_target_volume_chapters(self) -> int:
        if self.target_volume_chapters is not None:
            return self.target_volume_chapters
        if self.target_volumes <= 0:
            raise ValueError("target_volumes must be positive")
        if self.target_chapters <= 0:
            raise ValueError("target_chapters must be positive")
        base, remainder = divmod(self.target_chapters, self.target_volumes)
        return base + (1 if self.target_volume_number <= remainder else 0)

    def resolved_chapter_target_word_count(self) -> int:
        if self.target_chapters <= 0:
            raise ValueError("target_chapters must be positive")
        return round(self.target_word_count / self.target_chapters)

    def resolved_target_volume_word_count(self) -> int:
        return self.resolved_target_volume_chapters() * self.resolved_chapter_target_word_count()


def make_run_id(prefix: str) -> str:
    stamp = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    return f"{stamp}-{prefix}"


def validate_run_id(run_id: str | None) -> str | None:
    if run_id is None:
        return None
    if Path(run_id).is_absolute() or "/" in run_id or "\\" in run_id or ".." in run_id:
        raise ValueError("Unsafe run_id: use a simple name without paths.")
    return run_id


def validate_stage(stage: str | None) -> str | None:
    if stage is None:
        return None
    if stage not in API_GENERATION_STAGES:
        valid = ", ".join(API_GENERATION_STAGES)
        raise ValueError(f"Unknown generation stage: {stage}. Valid stages: {valid}")
    return stage


def validate_resume_options(options: GenerationRunOptions) -> str | None:
    target_stage = validate_stage(options.stage)
    resume_from_stage = validate_stage(options.resume_from_stage)
    if options.resume_novel_id and resume_from_stage is None:
        raise ValueError("--resume-novel-id requires --resume-from-stage")
    if resume_from_stage is not None and not options.resume_novel_id:
        raise ValueError("--resume-from-stage requires --resume-novel-id")
    if target_stage is not None and resume_from_stage is not None:
        target_index = API_GENERATION_STAGES.index(target_stage)
        resume_index = API_GENERATION_STAGES.index(resume_from_stage)
        if target_index < resume_index:
            raise ValueError("--stage cannot be before --resume-from-stage")
    return resume_from_stage


def validate_acceptance_scope(scope: str | None) -> AcceptanceScope:
    if scope in {None, ""}:
        return "real-contract"
    if scope in {"real-contract", "real-e2e-export", "real-longform-volume1"}:
        return scope
    raise ValueError(
        "Unknown acceptance scope: "
        f"{scope}. Valid scopes: real-contract, real-e2e-export, real-longform-volume1"
    )


def _should_require_export(scope: AcceptanceScope, *, archived_count: int) -> bool:
    if scope in {"real-e2e-export", "real-longform-volume1"}:
        return True
    return archived_count >= 1


def load_source_materials(source_dir: str | Path) -> list[SourceMaterial]:
    root = Path(source_dir).expanduser()
    if not root.exists():
        raise ValueError(f"Source material directory does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"Source material path is not a directory: {root}")

    materials: list[SourceMaterial] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() not in {".md", ".txt"}:
            continue
        content = path.read_text(encoding="utf-8")
        materials.append(
            SourceMaterial(
                filename=path.name,
                path=str(path),
                content=content,
                char_count=len(content),
                byte_count=path.stat().st_size,
            )
        )
    if not materials:
        raise ValueError(f"No .md or .txt source material files found in: {root}")
    return materials


def _is_longform_volume1(scope: AcceptanceScope) -> bool:
    return scope == "real-longform-volume1"


def _build_create_novel_payload(title: str, acceptance_scope: str = "") -> dict[str, str]:
    if acceptance_scope == "real-longform-volume1":
        return {
            "title": title,
            "primary_category_slug": "xuanhuan",
            "secondary_category_slug": "zhutian",
        }
    return {
        "title": title,
        "primary_category_slug": "general",
        "secondary_category_slug": "uncategorized",
    }


def _summarize_genre_report(state_payload: dict) -> dict:
    payload = state_payload if isinstance(state_payload, dict) else {}
    checkpoint = payload.get("checkpoint_data")
    if not isinstance(checkpoint, dict):
        checkpoint = {}

    genre = payload.get("genre") or checkpoint.get("genre") or {}
    if not isinstance(genre, dict):
        genre = {}

    template = checkpoint.get("genre_template")
    if not isinstance(template, dict):
        template = {}

    matched_templates = template.get("matched_templates")
    if not isinstance(matched_templates, list):
        matched_templates = []

    warnings = template.get("warnings")
    if not isinstance(warnings, list):
        warnings = []

    primary = genre.get("primary_name") or "通用"
    secondary = genre.get("secondary_name") or "未分类"
    return {
        "genre": f"{primary} / {secondary}",
        "template_layers": len(matched_templates),
        "template_warnings": warnings,
        "template_evidence_available": bool(matched_templates),
    }


def _target_artifacts(options: GenerationRunOptions) -> dict[str, str]:
    return {
        "target_volumes": str(options.target_volumes),
        "target_chapters": str(options.target_chapters),
        "target_word_count": str(options.target_word_count),
        "target_volume_number": str(options.target_volume_number),
        "target_volume_chapters": str(options.resolved_target_volume_chapters()),
        "chapter_target_word_count": str(options.resolved_chapter_target_word_count()),
        "target_volume_word_count": str(options.resolved_target_volume_word_count()),
    }


def _build_quality_gate_evidence(
    *,
    chapter_id: str,
    job_id: str,
    stopped_reason: str | None,
    archived_count: int,
    quality_status: str,
    quality_reasons: str,
) -> list[str]:
    evidence = [
        f"chapter_id={chapter_id}",
        f"job_id={job_id}",
    ]
    if stopped_reason is not None:
        evidence.append(f"chapter_job_stopped_reason={stopped_reason}")
    evidence.extend(
        [
            f"archived_chapter_count={archived_count}",
            f"quality_status={quality_status}",
            f"quality_reasons={quality_reasons}",
        ]
    )
    return evidence


async def run_generation_acceptance(options: GenerationRunOptions) -> TestRunReport:
    started = time.monotonic()
    target_stage = validate_stage(options.stage)
    resume_from_stage = validate_resume_options(options)
    acceptance_scope = validate_acceptance_scope(options.acceptance_scope)
    fixture = load_generation_fixture(options.dataset)
    run_id = validate_run_id(options.run_id) or make_run_id("generation-real")

    report = TestRunReport(
        run_id=run_id,
        entrypoint="scripts/verify_generation_real.sh",
        status="passed",
        duration_seconds=time.monotonic() - started,
        dataset=fixture.dataset,
        llm_mode=options.llm_mode,
        environment={"api_base_url": options.api_base_url},
    )
    report.artifacts["fixture_title"] = fixture.title
    report.artifacts["contract_scope"] = acceptance_scope
    report.artifacts["acceptance_scope"] = acceptance_scope
    if target_stage is not None:
        report.artifacts["target_stage"] = target_stage
    if options.resume_novel_id:
        report.artifacts["resume_novel_id"] = options.resume_novel_id
    if resume_from_stage is not None:
        report.artifacts["resume_from_stage"] = resume_from_stage
    if options.resume_reset_current_chapter:
        report.artifacts["resume_reset_current_chapter"] = "true"
    if _is_longform_volume1(acceptance_scope):
        if not options.source_dir:
            raise ValueError("real-longform-volume1 requires --source-dir")
        source_materials = load_source_materials(options.source_dir)
        source_materials_payload = [
            {
                "filename": item.filename,
                "path": item.path,
                "status": "discovered",
                "char_count": item.char_count,
                "byte_count": item.byte_count,
            }
            for item in source_materials
        ]
        report.artifacts.update(_target_artifacts(options))
        report.artifacts["source_dir"] = str(Path(options.source_dir).expanduser())
        report.artifacts["source_material_count"] = str(len(source_materials))
        report.artifacts["source_material_char_count"] = str(
            sum(item.char_count for item in source_materials)
        )
        report.artifacts["source_material_byte_count"] = str(
            sum(item.byte_count for item in source_materials)
        )
        report.artifacts["source_materials_json"] = json.dumps(
            source_materials_payload,
            ensure_ascii=False,
        )
    if options.llm_mode == "fake":
        try:
            _run_fake_generation_diagnostic(fixture)
        except Exception as exc:
            report.add_issue(
                classify_exception(
                    "fake_generation_diagnostic",
                    exc,
                    real_llm=False,
                    acceptance_scope=acceptance_scope,
                )
            )
        report.duration_seconds = time.monotonic() - started
        return report

    if options.llm_mode != "fake":
        try:
            artifacts, issues = await _run_api_smoke_flow(options, fixture)
        except Exception as exc:
            report.add_issue(
                classify_exception(
                    "api_smoke_flow",
                    exc,
                    real_llm=False,
                    acceptance_scope=acceptance_scope,
                )
            )
        else:
            report.artifacts.update(artifacts)
            for issue in issues:
                report.add_issue(issue)
            if not any(issue.is_external_blocker for issue in issues):
                try:
                    _validate_report_artifacts(report.artifacts)
                except Exception as exc:
                    report.add_issue(
                        classify_exception(
                            "export_contract",
                            exc,
                            real_llm=False,
                            acceptance_scope=acceptance_scope,
                        )
                    )

    report.duration_seconds = time.monotonic() - started
    return report


async def run_generation_acceptance_and_write(
    options: GenerationRunOptions,
) -> TestRunReport:
    report = await run_generation_acceptance(options)
    report_root = Path(options.report_root) / report.run_id
    if any(issue.is_external_blocker for issue in report.issues):
        report.artifacts["quality_summary_status"] = "skipped_external_blocker"
        ReportWriter(report_root).write(report)
        return report
    try:
        snapshot = await _build_generation_quality_snapshot(report)
        if snapshot is not None:
            artifacts_dir = report_root / "artifacts"
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            snapshot_path = artifacts_dir / "generation_snapshot.json"
            snapshot_path.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            report.artifacts["generation_snapshot_json"] = str(snapshot_path)
            quality_report = _write_quality_summary_bundle(
                report_root=report_root,
                snapshot=snapshot,
                parent_run_id=report.run_id,
            )
            report.artifacts["quality_summary_json"] = str(
                report_root / "quality-summary" / "summary.json"
            )
            report.artifacts["quality_summary_md"] = str(
                report_root / "quality-summary" / "summary.md"
            )
            report.artifacts["quality_summary_status"] = quality_report.status
            report.artifacts["quality_summary_run_id"] = quality_report.run_id
            _merge_quality_summary_issues(report, quality_report)
    except Exception as exc:
        acceptance_scope = validate_acceptance_scope(
            str(report.artifacts.get("acceptance_scope") or "real-contract")
        )
        report.add_issue(
            classify_exception(
                "quality_summary",
                exc,
                real_llm=False,
                acceptance_scope=acceptance_scope,
            )
        )
    ReportWriter(report_root).write(report)
    return report


async def _build_generation_quality_snapshot(
    report: TestRunReport,
) -> dict[str, Any] | None:
    novel_id = str(report.artifacts.get("novel_id") or "").strip()
    if not novel_id:
        return None

    async with async_session_maker() as session:
        state = await NovelStateRepository(session).get_state(novel_id)
        chapter_rows = await session.execute(
            select(Chapter)
            .where(Chapter.novel_id == novel_id)
            .order_by(Chapter.chapter_number.asc(), Chapter.id.asc())
        )
        chapters = chapter_rows.scalars().all()

        review_repo = SettingWorkbenchRepository(session)
        review_batch = None
        review_batch_id = str(report.artifacts.get("review_batch_id") or "").strip()
        if review_batch_id:
            review_batch = await review_repo.get_review_batch(review_batch_id)
        if review_batch is None:
            batches = await review_repo.list_review_batches(novel_id)
            review_batch = batches[0] if batches else None
        review_changes = await review_repo.list_review_changes(review_batch.id) if review_batch is not None else []

    checkpoint = dict(state.checkpoint_data or {}) if state is not None else {}
    setting_review_changes = [
        {
            "id": change.id,
            "object_type": change.target_type,
            "target_type": change.target_type,
            "operation": change.operation,
            "target_id": change.target_id,
            "status": change.status,
            "before_snapshot": change.before_snapshot,
            "after_snapshot": change.after_snapshot,
            "conflict_hints": change.conflict_hints,
        }
        for change in review_changes
    ]
    enrichment_input = {
        "checkpoint": checkpoint,
        "setting_review_changes": setting_review_changes,
    }
    story_contract = checkpoint.get("story_contract")
    if not isinstance(story_contract, dict):
        story_contract = StoryContractService.build_from_snapshot(enrichment_input)
    cross_stage_quality = checkpoint.get("cross_stage_quality")
    if not isinstance(cross_stage_quality, dict):
        cross_stage_quality = StoryContractService.evaluate_cross_stage_quality(enrichment_input, story_contract)
    snapshot: dict[str, Any] = {
        "run_id": report.run_id,
        "novel_id": novel_id,
        "dataset": report.dataset,
        "llm_mode": report.llm_mode,
        "artifacts": dict(report.artifacts),
        "checkpoint": {
            **checkpoint,
            "story_contract": story_contract,
            "cross_stage_quality": cross_stage_quality,
            "current_phase": getattr(state, "current_phase", None),
            "current_volume_id": getattr(state, "current_volume_id", None),
            "current_chapter_id": getattr(state, "current_chapter_id", None),
        },
        "chapters": [
            {
                "chapter_id": chapter.id,
                "id": chapter.id,
                "volume_id": chapter.volume_id,
                "chapter_number": chapter.chapter_number,
                "title": chapter.title,
                "status": chapter.status,
                "quality_status": chapter.quality_status,
                "quality_reasons": chapter.quality_reasons,
                "draft_review_score": chapter.draft_review_score,
                "fast_review_score": chapter.fast_review_score,
                "final_review_score": chapter.final_review_score,
                "world_state_ingested": chapter.world_state_ingested,
                "raw_draft": chapter.raw_draft,
                "polished_text": chapter.polished_text,
            }
            for chapter in chapters
        ],
    }
    acceptance_target = _acceptance_target_from_artifacts(report.artifacts)
    if acceptance_target:
        snapshot["acceptance_target"] = acceptance_target
    source_materials = _source_materials_from_artifacts(report.artifacts)
    if source_materials:
        snapshot["source_materials"] = source_materials
    if review_batch is not None:
        snapshot["setting_review_batch"] = {
            "id": review_batch.id,
            "status": review_batch.status,
            "source_type": review_batch.source_type,
            "summary": review_batch.summary,
            "input_snapshot": review_batch.input_snapshot,
            "error_message": review_batch.error_message,
        }
        snapshot["setting_review_changes"] = setting_review_changes
    return snapshot


def _write_quality_summary_bundle(
    *,
    report_root: Path,
    snapshot: dict[str, Any],
    parent_run_id: str,
) -> TestRunReport:
    from novel_dev.testing.quality_summary import build_quality_summary_report

    quality_report = build_quality_summary_report(
        snapshot,
        run_id=f"{parent_run_id}-quality-summary",
    )
    ReportWriter(report_root / "quality-summary").write(quality_report)
    return quality_report


def _acceptance_target_from_artifacts(artifacts: dict[str, str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for key in (
        "target_volumes",
        "target_chapters",
        "target_word_count",
        "target_volume_number",
        "target_volume_chapters",
        "target_volume_word_count",
        "chapter_target_word_count",
    ):
        value = _coerce_int(artifacts.get(key))
        if value is not None:
            result[key] = value
    return result


def _source_materials_from_artifacts(artifacts: dict[str, str]) -> list[dict[str, Any]]:
    raw = artifacts.get("source_materials_json")
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _merge_quality_summary_issues(
    report: TestRunReport,
    quality_report: TestRunReport,
) -> None:
    existing = {(issue.id, issue.stage, issue.message) for issue in report.issues}
    for issue in quality_report.issues:
        key = (issue.id, issue.stage, issue.message)
        if key in existing:
            continue
        report.add_issue(issue)
        existing.add(key)


async def run_stage_with_classification(
    stage: str,
    real_step: Step,
    fake_step: Step,
    acceptance_scope: AcceptanceScope = "real-contract",
) -> tuple[Issue | None, str | None]:
    try:
        await real_step()
    except Exception as exc:
        issue = classify_exception(
            stage,
            exc,
            real_llm=True,
            acceptance_scope=acceptance_scope,
        )
        if not should_run_fake_diagnostic(issue.type):
            return issue, None

        try:
            await fake_step()
        except Exception:
            issue.fake_rerun_status = "failed"
            return issue, "failed"

        issue.fake_rerun_status = "passed"
        return issue, "passed"

    return None, None


async def _run_api_smoke_flow(
    options: GenerationRunOptions,
    fixture: GenerationFixture,
) -> tuple[dict[str, str], list[Issue]]:
    target_stage = validate_stage(options.stage)
    resume_from_stage = validate_resume_options(options)
    resume_stage_index = (
        API_GENERATION_STAGES.index(resume_from_stage)
        if resume_from_stage is not None
        else None
    )
    acceptance_scope = validate_acceptance_scope(options.acceptance_scope)
    longform_volume1 = _is_longform_volume1(acceptance_scope)
    source_materials: list[SourceMaterial] = []
    if longform_volume1:
        if not options.source_dir:
            raise ValueError("real-longform-volume1 requires --source-dir")
        source_materials = load_source_materials(options.source_dir)
    artifacts: dict[str, str] = {
        "contract_scope": acceptance_scope,
        "acceptance_scope": acceptance_scope,
    }
    if options.resume_novel_id:
        artifacts["novel_id"] = options.resume_novel_id
        artifacts["resume_novel_id"] = options.resume_novel_id
    if resume_from_stage is not None:
        artifacts["resume_from_stage"] = resume_from_stage
    if options.resume_reset_current_chapter:
        artifacts["resume_reset_current_chapter"] = "true"
    if longform_volume1:
        artifacts.update(_target_artifacts(options))
        artifacts["source_dir"] = str(Path(options.source_dir or "").expanduser())
        artifacts["source_material_count"] = str(len(source_materials))
        artifacts["source_material_char_count"] = str(
            sum(item.char_count for item in source_materials)
        )
        artifacts["source_material_byte_count"] = str(
            sum(item.byte_count for item in source_materials)
        )
    issues: list[Issue] = []
    quality_gate_issue: Issue | None = None

    async def fake_step() -> None:
        _run_fake_generation_diagnostic(fixture)

    async def run_stage(stage: str, real_step: Step) -> bool:
        if resume_stage_index is not None and stage in API_GENERATION_STAGES:
            stage_index = API_GENERATION_STAGES.index(stage)
            if stage != "preflight_health" and stage_index < resume_stage_index:
                artifacts[f"{stage}_status"] = "skipped_for_resume"
                return True

        if options.llm_mode == "real_then_fake_on_external_block":
            issue, _fake_status = await run_stage_with_classification(
                stage,
                real_step,
                fake_step,
                acceptance_scope=acceptance_scope,
            )
        else:
            try:
                await real_step()
            except Exception as exc:
                issue = classify_exception(
                    stage,
                    exc,
                    real_llm=True,
                    acceptance_scope=acceptance_scope,
                )
            else:
                issue = None

        if issue is not None:
            issues.append(issue)
            return False
        return True

    def should_stop_after(stage: str) -> bool:
        if target_stage != stage:
            return False
        artifacts["stopped_at_stage"] = stage
        return True

    async with httpx.AsyncClient(
        base_url=options.api_base_url,
        timeout=API_SMOKE_TIMEOUT_SECONDS,
        trust_env=False,
    ) as client:
        def record_genre_template_summary(state_payload: dict[str, Any]) -> None:
            artifacts["genre_template_summary"] = json.dumps(
                _summarize_genre_report(state_payload),
                ensure_ascii=False,
            )

        async def preflight_health() -> None:
            response = await client.get("/healthz")
            response.raise_for_status()

        if not await run_stage("preflight_health", preflight_health):
            return artifacts, issues
        if should_stop_after("preflight_health"):
            return artifacts, issues

        if options.resume_novel_id:
            async def resume_existing_novel() -> None:
                resume_artifacts = await _prepare_resume_state(
                    options.resume_novel_id,
                    options,
                    resume_from_stage=resume_from_stage,
                )
                artifacts.update(resume_artifacts)

            if not await run_stage("resume_existing_novel", resume_existing_novel):
                return artifacts, issues

        async def create_novel() -> None:
            data = await _request_json(
                client.post(
                    "/api/novels",
                    json=_build_create_novel_payload(fixture.title, options.acceptance_scope),
                )
            )
            artifacts["novel_id"] = _require_string(data, "novel_id", "create_novel")
            record_genre_template_summary(data)

        if not await run_stage("create_novel", create_novel):
            return artifacts, issues
        if should_stop_after("create_novel"):
            return artifacts, issues

        novel_id = artifacts["novel_id"]

        async def create_setting_session() -> None:
            data = await _request_json(
                client.post(
                    f"/api/novels/{novel_id}/settings/sessions",
                    json={
                        "title": "Codex real generation settings acceptance",
                        "initial_idea": fixture.initial_setting_idea,
                        "target_categories": [],
                    },
                )
            )
            artifacts["setting_session_id"] = _require_string(
                data,
                "id",
                "create_setting_session",
            )

        if not await run_stage("create_setting_session", create_setting_session):
            return artifacts, issues
        if should_stop_after("create_setting_session"):
            return artifacts, issues

        setting_session_id = artifacts.get("setting_session_id", "")

        async def advance_setting_session() -> None:
            last_questions: list[str] = []
            for attempt in range(1, MAX_SETTING_CLARIFICATION_ROUNDS + 1):
                data = await _request_json(
                    client.post(
                        f"/api/novels/{novel_id}/settings/sessions/"
                        f"{setting_session_id}/reply",
                        json={
                            "content": _build_setting_clarification_reply(
                                fixture,
                                last_questions=last_questions,
                                attempt=attempt,
                            )
                        },
                    )
                )
                session = data.get("session")
                if not isinstance(session, dict):
                    raise RuntimeError("advance_setting_session response missing session")

                status = _first_string(session, "status")
                if status is not None:
                    artifacts["setting_session_status"] = status

                clarification_round = _coerce_int(session.get("clarification_round"))
                if clarification_round is not None:
                    artifacts["setting_clarification_round"] = str(clarification_round)

                if status == "ready_to_generate":
                    return
                if status != "clarifying":
                    raise RuntimeError(
                        "advance_setting_session returned unexpected status"
                    )

                last_questions = _coerce_string_list(data.get("questions"))

            raise RuntimeError(
                "advance_setting_session did not reach ready_to_generate"
            )

        if not await run_stage("advance_setting_session", advance_setting_session):
            return artifacts, issues
        if should_stop_after("advance_setting_session"):
            return artifacts, issues

        async def generate_setting_review_batch() -> None:
            data = await _request_json(
                client.post(
                    f"/api/novels/{novel_id}/settings/sessions/{setting_session_id}/generate",
                    json={},
                )
            )
            review_batch_id = _first_string(data, "id", "review_batch_id", "batch_id")
            if review_batch_id is not None:
                artifacts["review_batch_id"] = review_batch_id

        if not await run_stage(
            "generate_setting_review_batch",
            generate_setting_review_batch,
        ):
            return artifacts, issues
        if should_stop_after("generate_setting_review_batch"):
            return artifacts, issues

        if longform_volume1:
            async def apply_generated_settings() -> None:
                review_batch_id = artifacts.get("review_batch_id")
                if not review_batch_id:
                    raise RuntimeError("generate_setting_review_batch did not return review_batch_id")
                await _approve_review_batch_non_conflict_changes(
                    client,
                    novel_id,
                    review_batch_id,
                    artifacts,
                    artifact_prefix="generated_setting",
                )

            if not await run_stage("apply_generated_settings", apply_generated_settings):
                return artifacts, issues
            if should_stop_after("apply_generated_settings"):
                return artifacts, issues

        if longform_volume1:
            pending_ids: list[str] = []
            uploaded_materials: list[dict[str, Any]] = []

            async def upload_source_materials() -> None:
                for material in source_materials:
                    data = await _request_json(
                        client.post(
                            f"/api/novels/{novel_id}/documents/upload",
                            json={
                                "filename": material.filename,
                                "content": material.content,
                            },
                        )
                    )
                    pending_id = _first_string(data, "pending_id", "id")
                    if pending_id is None:
                        raise RuntimeError(
                            f"upload_source_materials missing pending id for {material.filename}"
                        )
                    pending_ids.append(pending_id)
                    uploaded_materials.append(
                        {
                            "filename": material.filename,
                            "path": material.path,
                            "pending_id": pending_id,
                            "status": "uploaded",
                            "char_count": material.char_count,
                            "byte_count": material.byte_count,
                        }
                    )
                artifacts["source_material_uploaded_count"] = str(len(pending_ids))
                artifacts["source_material_pending_ids"] = ",".join(pending_ids)

            if not await run_stage("upload_source_materials", upload_source_materials):
                return artifacts, issues
            if should_stop_after("upload_source_materials"):
                return artifacts, issues

            async def approve_source_materials() -> None:
                for pending_id in pending_ids:
                    await _request_json(
                        client.post(
                            f"/api/novels/{novel_id}/documents/pending/approve",
                            json={"pending_id": pending_id, "field_resolutions": []},
                        )
                    )
                for item in uploaded_materials:
                    item["status"] = "approved"
                artifacts["source_material_approved_count"] = str(len(pending_ids))
                artifacts["source_materials_json"] = json.dumps(
                    uploaded_materials,
                    ensure_ascii=False,
                )

            if not await run_stage("approve_source_materials", approve_source_materials):
                return artifacts, issues
            if should_stop_after("approve_source_materials"):
                return artifacts, issues

            async def consolidate_settings() -> None:
                data = await _request_json(
                    client.post(
                        f"/api/novels/{novel_id}/settings/consolidations",
                        json={"selected_pending_ids": []},
                    )
                )
                job_id = _require_string(data, "job_id", "consolidate_settings")
                artifacts["setting_consolidation_job_id"] = job_id
                job = await _poll_generation_job(
                    client,
                    novel_id,
                    job_id,
                    failure_stage="consolidate_settings",
                )
                result_payload = job.get("result_payload")
                if isinstance(result_payload, dict):
                    batch_id = _first_string(result_payload, "batch_id")
                    if batch_id is not None:
                        artifacts["setting_consolidation_batch_id"] = batch_id

            if not await run_stage("consolidate_settings", consolidate_settings):
                return artifacts, issues
            if should_stop_after("consolidate_settings"):
                return artifacts, issues

            async def apply_consolidated_settings() -> None:
                batch_id = artifacts.get("setting_consolidation_batch_id")
                if not batch_id:
                    raise RuntimeError("consolidate_settings did not return batch_id")
                await _approve_review_batch_non_conflict_changes(
                    client,
                    novel_id,
                    batch_id,
                    artifacts,
                    artifact_prefix="consolidated_setting",
                )

            if not await run_stage("apply_consolidated_settings", apply_consolidated_settings):
                return artifacts, issues
            if should_stop_after("apply_consolidated_settings"):
                return artifacts, issues
        else:
            async def upload_seed_setting() -> None:
                data = await _request_json(
                    client.post(
                        f"/api/novels/{novel_id}/documents/upload",
                        json={
                            "filename": "codex_seed_setting.md",
                            "content": fixture.initial_setting_idea,
                        },
                    )
                )
                pending_id = _first_string(data, "pending_id", "id")
                if pending_id is not None:
                    artifacts["pending_id"] = pending_id

            if not await run_stage("upload_seed_setting", upload_seed_setting):
                return artifacts, issues
            if should_stop_after("upload_seed_setting"):
                return artifacts, issues

            async def approve_seed_setting() -> None:
                pending_id = artifacts.get("pending_id")
                if pending_id is None:
                    raise RuntimeError("upload_seed_setting did not return pending_id")
                await _request_json(
                    client.post(
                        f"/api/novels/{novel_id}/documents/pending/approve",
                        json={"pending_id": pending_id, "field_resolutions": []},
                    )
                )

            if not await run_stage("approve_seed_setting", approve_seed_setting):
                return artifacts, issues
            if should_stop_after("approve_seed_setting"):
                return artifacts, issues

        async def brainstorm() -> None:
            await _request_json(client.post(f"/api/novels/{novel_id}/brainstorm"))

        if not await run_stage("brainstorm", brainstorm):
            return artifacts, issues
        if should_stop_after("brainstorm"):
            return artifacts, issues

        if not longform_volume1:
            brainstorm_contract = await _prepare_minimal_synopsis(novel_id, fixture)
            if brainstorm_contract.original_estimated_volumes is not None:
                artifacts["brainstorm_original_estimated_volumes"] = str(
                    brainstorm_contract.original_estimated_volumes
                )
            if brainstorm_contract.original_estimated_total_chapters is not None:
                artifacts["brainstorm_original_estimated_total_chapters"] = str(
                    brainstorm_contract.original_estimated_total_chapters
                )
            artifacts["brainstorm_shrunk_estimated_total_chapters"] = str(
                brainstorm_contract.shrunk_estimated_total_chapters
            )
        else:
            await _prepare_longform_synopsis_contract(novel_id, options)

        volume_plan_response: dict[str, Any] = {}

        async def volume_plan() -> None:
            nonlocal volume_plan_response
            data = await _request_json(
                client.post(
                    f"/api/novels/{novel_id}/volume_plan",
                    json={"volume_number": options.target_volume_number if longform_volume1 else 1},
                )
            )
            volume_plan_response = data
            volume_id = _first_string(data, "volume_id", "id")
            if volume_id is not None:
                artifacts["volume_id"] = volume_id

        if not await run_stage("volume_plan", volume_plan):
            return artifacts, issues
        if should_stop_after("volume_plan"):
            return artifacts, issues

        if not longform_volume1:
            chapter_plan = await _prepare_minimal_chapter_plan(
                novel_id,
                fixture,
                volume_plan_response=volume_plan_response,
                acceptance_scope=acceptance_scope,
            )
            artifacts["chapter_id"] = chapter_plan.chapter_id
            artifacts["chapter_plan_source"] = chapter_plan.source
            artifacts["chapter_target_word_count"] = str(chapter_plan.target_word_count)
        else:
            await _prepare_longform_volume_plan_contract(novel_id, options)

        async def auto_run_chapters() -> None:
            nonlocal quality_gate_issue
            max_chapters = options.resolved_target_volume_chapters() if longform_volume1 else 1
            data = await _request_json(
                client.post(
                    f"/api/novels/{novel_id}/chapters/auto-run",
                    json={"max_chapters": max_chapters, "stop_at_volume_end": True},
                )
            )
            job_id = _require_string(data, "job_id", "auto_run_chapters")
            artifacts["chapter_auto_run_job_id"] = job_id
            max_polls = GENERATION_JOB_MAX_POLLS
            if longform_volume1:
                max_polls = max(max_polls, max_chapters * 900)
            job = await _poll_generation_job(
                client,
                novel_id,
                job_id,
                failure_stage="auto_run_chapters",
                max_polls=max_polls,
            )
            result_payload = job.get("result_payload") or {}
            if not isinstance(result_payload, dict):
                raise RuntimeError("auto_run_chapters result_payload must be an object")
            completed_chapters = _coerce_string_list(result_payload.get("completed_chapters"))
            if completed_chapters:
                artifacts["completed_chapter_ids"] = ",".join(completed_chapters)
                artifacts["completed_chapter_count"] = str(len(completed_chapters))
                artifacts.setdefault("chapter_id", completed_chapters[0])
            stopped_reason = _first_string(result_payload, "stopped_reason")
            if stopped_reason is not None:
                artifacts["chapter_job_stopped_reason"] = stopped_reason

            chapter_id = (
                artifacts.get("chapter_id")
                or _first_string(result_payload, "failed_chapter_id", "current_chapter_id")
                or await _current_chapter_id_from_state(novel_id)
            )
            if chapter_id is not None:
                artifacts["chapter_id"] = chapter_id
            if chapter_id is None:
                raise ContractValidationError(
                    "auto_run_chapters_contract",
                    "auto_run_chapters missing prepared chapter_id",
                    [],
                )

            chapter = await _get_chapter_contract_state(novel_id, chapter_id)
            text_status = detect_chapter_text(chapter)
            artifacts["chapter_text_status"] = text_status.field
            artifacts["chapter_text_length"] = str(text_status.length)
            if not text_status.has_text:
                raise ContractValidationError(
                    "auto_run_chapters_contract",
                    "auto_run_chapters completed without generated chapter text",
                    [f"chapter_id={chapter_id}", f"job_id={job_id}"],
                )

            quality = summarize_quality_gate(chapter)
            artifacts["quality_status"] = quality.status
            if quality.reasons:
                artifacts["quality_reasons"] = quality.reasons

            stats = await _request_json(client.get(f"/api/novels/{novel_id}/archive_stats"))
            archived_count = _coerce_int(stats.get("archived_chapter_count")) or 0
            artifacts["archived_chapter_count"] = str(archived_count)
            total_word_count = _coerce_int(stats.get("total_word_count"))
            if total_word_count is not None:
                artifacts["total_word_count"] = str(total_word_count)

            if longform_volume1 and archived_count < max_chapters:
                raise ContractValidationError(
                    "auto_run_chapters_contract",
                    "longform volume generation archived fewer chapters than requested",
                    [
                        f"requested_chapters={max_chapters}",
                        f"completed_chapter_count={len(completed_chapters)}",
                        f"archived_chapter_count={archived_count}",
                        f"job_id={job_id}",
                    ],
                )

            if archived_count < 1:
                if quality.status == "block":
                    evidence = _build_quality_gate_evidence(
                        chapter_id=chapter_id,
                        job_id=job_id,
                        stopped_reason=stopped_reason,
                        archived_count=archived_count,
                        quality_status=quality.status,
                        quality_reasons=quality.reasons or "none",
                    )
                    quality_gate_issue = Issue(
                        id="GENERATION_QUALITY-quality_gate",
                        type="GENERATION_QUALITY",
                        severity="high",
                        stage="quality_gate",
                        is_external_blocker=False,
                        real_llm=True,
                        fake_rerun_status=None,
                        message="Chapter generated text but quality gate blocked archival",
                        evidence=evidence,
                        reproduce=_reproduce_command_for_stage(
                            "quality_gate",
                            acceptance_scope,
                        ),
                    )
                    return
                raise RuntimeError("auto_run_chapters did not archive any chapter")

        if not await run_stage("auto_run_chapters", auto_run_chapters):
            return artifacts, issues
        if quality_gate_issue is not None:
            issues.append(quality_gate_issue)
            if acceptance_scope == "real-contract":
                return artifacts, issues
        if should_stop_after("auto_run_chapters"):
            return artifacts, issues

        archived_count = _coerce_int(artifacts.get("archived_chapter_count")) or 0
        if not _should_require_export(acceptance_scope, archived_count=archived_count):
            artifacts["export_status"] = "not_applicable_quality_blocked"
            return artifacts, issues

        if acceptance_scope == "real-e2e-export" and archived_count < 1:
            export_contract_evidence = _build_quality_gate_evidence(
                chapter_id=artifacts.get("chapter_id", "unknown"),
                job_id=artifacts.get("chapter_auto_run_job_id", "unknown"),
                stopped_reason=artifacts.get("chapter_job_stopped_reason"),
                archived_count=archived_count,
                quality_status=artifacts.get("quality_status", "unknown"),
                quality_reasons=artifacts.get("quality_reasons", "none"),
            )
            issues.append(
                Issue(
                    id="SYSTEM_BUG-export_contract",
                    type="SYSTEM_BUG",
                    severity="high",
                    stage="export_contract",
                    is_external_blocker=False,
                    real_llm=True,
                    fake_rerun_status=None,
                    message=(
                        "real-e2e-export requires at least one archived chapter "
                        "before export"
                    ),
                    evidence=export_contract_evidence,
                    reproduce=_reproduce_command_for_stage(
                        "export_contract",
                        acceptance_scope,
                    ),
                )
            )
            return artifacts, issues

        async def export() -> None:
            data = await _request_json(
                client.post(f"/api/novels/{novel_id}/export", params={"format": "md"})
            )
            exported_path = _first_string(data, "exported_path", "path")
            if exported_path is not None:
                artifacts["exported_path"] = exported_path

        await run_stage("export", export)
        if should_stop_after("export"):
            return artifacts, issues
        return artifacts, issues


async def _request_json(response_awaitable: Awaitable[httpx.Response]) -> dict[str, Any]:
    response = await response_awaitable
    response.raise_for_status()
    if not response.content:
        return {}
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("HTTP response JSON must be an object")
    return data


async def _approve_review_batch_non_conflict_changes(
    client: httpx.AsyncClient,
    novel_id: str,
    batch_id: str,
    artifacts: dict[str, str],
    *,
    artifact_prefix: str,
) -> None:
    detail = await _request_json(
        client.get(f"/api/novels/{novel_id}/settings/review_batches/{batch_id}")
    )
    raw_changes = detail.get("changes")
    changes = [item for item in raw_changes if isinstance(item, dict)] if isinstance(raw_changes, list) else []
    approvable_ids = [
        str(change["id"])
        for change in changes
        if change.get("id")
        and change.get("target_type") != "conflict"
        and str(change.get("status") or "pending") == "pending"
    ]
    conflict_count = sum(1 for change in changes if change.get("target_type") == "conflict")
    artifacts[f"{artifact_prefix}_change_count"] = str(len(changes))
    artifacts[f"{artifact_prefix}_approvable_change_count"] = str(len(approvable_ids))
    artifacts[f"{artifact_prefix}_conflict_change_count"] = str(conflict_count)
    if not approvable_ids:
        artifacts[f"{artifact_prefix}_batch_status"] = _batch_status_from_detail(detail) or "no_approvable_changes"
        return

    result = await _request_json(
        client.post(
            f"/api/novels/{novel_id}/settings/review_batches/{batch_id}/approve",
            json={"change_ids": approvable_ids, "approve_all": False},
        )
    )
    artifacts[f"{artifact_prefix}_approved_change_ids"] = ",".join(approvable_ids)
    artifacts[f"{artifact_prefix}_batch_status"] = _batch_status_from_detail(result) or "unknown"


def _batch_status_from_detail(data: dict[str, Any]) -> str | None:
    batch = data.get("batch")
    if isinstance(batch, dict):
        return _first_string(batch, "status")
    return _first_string(data, "status")


async def _poll_generation_job(
    client: httpx.AsyncClient,
    novel_id: str,
    job_id: str,
    *,
    failure_stage: str = "generation_job",
    max_polls: int | None = None,
) -> dict[str, Any]:
    last_status = "unknown"
    for _ in range(max_polls or GENERATION_JOB_MAX_POLLS):
        data = await _request_json(client.get(f"/api/novels/{novel_id}/generation_jobs/{job_id}"))
        status = _first_string(data, "status") or "unknown"
        last_status = status
        if status == "succeeded":
            return data
        if status in {"failed", "cancelled"}:
            error_message = _first_string(data, "error_message") or f"generation job {status}"
            evidence = _build_generation_job_failure_evidence(data)
            evidence.extend(await _fetch_generation_checkpoint_failure_evidence(client, novel_id))
            raise ContractValidationError(failure_stage, error_message, evidence)
        await asyncio.sleep(GENERATION_JOB_POLL_INTERVAL_SECONDS)

    raise RuntimeError(f"generation job polling timed out: {job_id} last_status={last_status}")


def _build_generation_job_failure_evidence(job: dict[str, Any]) -> list[str]:
    evidence = []
    for key in ("job_id", "status", "error_message"):
        value = job.get(key)
        if value not in (None, ""):
            evidence.append(f"{key}={value}")
    result_payload = job.get("result_payload")
    if isinstance(result_payload, dict):
        for key in (
            "stopped_reason",
            "failed_phase",
            "failed_chapter_id",
            "current_phase",
            "current_chapter_id",
            "error",
        ):
            value = result_payload.get(key)
            if value not in (None, ""):
                evidence.append(f"result_payload.{key}={value}")
    return evidence


async def _fetch_generation_checkpoint_failure_evidence(
    client: httpx.AsyncClient,
    novel_id: str,
) -> list[str]:
    try:
        state = await _request_json(client.get(f"/api/novels/{novel_id}/state"))
    except Exception as exc:
        return [f"checkpoint_evidence_unavailable={exc}"]
    checkpoint = state.get("checkpoint_data")
    if not isinstance(checkpoint, dict):
        return []

    evidence = []
    guard = checkpoint.get("chapter_structure_guard")
    if guard:
        evidence.append(f"chapter_structure_guard={_compact_json(guard)}")
    writer_failures = checkpoint.get("writer_guard_failures")
    if isinstance(writer_failures, list):
        evidence.append(f"writer_guard_failures_count={len(writer_failures)}")
        if writer_failures:
            evidence.append(f"writer_guard_last_failure={_compact_json(writer_failures[-1])}")
    editor_warnings = checkpoint.get("editor_guard_warnings")
    if isinstance(editor_warnings, list):
        evidence.append(f"editor_guard_warnings_count={len(editor_warnings)}")
    return evidence


def _compact_json(value: Any, limit: int = 1200) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= limit else f"{text[:limit]}..."


async def _get_chapter_contract_state(novel_id: str, chapter_id: str) -> Any | None:
    async with async_session_maker() as session:
        chapter = await ChapterRepository(session).get_by_id(chapter_id)
        if chapter is None or chapter.novel_id != novel_id:
            return None
        return chapter


async def _prepare_resume_state(
    novel_id: str,
    options: GenerationRunOptions,
    *,
    resume_from_stage: str | None,
) -> dict[str, str]:
    async with async_session_maker() as session:
        repo = NovelStateRepository(session)
        state = await repo.get_state(novel_id)
        if state is None:
            raise RuntimeError(f"Novel state not found for {novel_id}")

        artifacts = {
            "resume_current_phase": state.current_phase,
        }
        if state.current_volume_id:
            artifacts["volume_id"] = state.current_volume_id
        if state.current_chapter_id:
            artifacts["chapter_id"] = state.current_chapter_id

        checkpoint = dict(state.checkpoint_data or {})
        checkpoint_changed = checkpoint.pop("flow_control", None) is not None
        if not (
            options.resume_reset_current_chapter
            and resume_from_stage == "auto_run_chapters"
        ):
            if checkpoint_changed:
                await repo.save_checkpoint(
                    novel_id,
                    state.current_phase,
                    checkpoint,
                    current_volume_id=state.current_volume_id,
                    current_chapter_id=state.current_chapter_id,
                )
                await session.commit()
                artifacts["resume_cleared_flow_stop"] = "true"
            return artifacts

        chapter_id = _chapter_id_from_state_payload(
            current_chapter_id=state.current_chapter_id,
            checkpoint=checkpoint,
        )
        if chapter_id is None:
            raise ContractValidationError(
                "resume_contract",
                "cannot reset current chapter because no persisted chapter id was found",
                [f"novel_id={novel_id}", f"current_phase={state.current_phase}"],
            )

        await ChapterRepository(session).reset_generation(chapter_id)
        for key in (
            "chapter_context",
            "chapter_draft",
            "review_result",
            "review_scores",
            "edit_result",
            "fast_review_result",
            "librarian_result",
            "quality_gate",
        ):
            checkpoint.pop(key, None)

        await repo.save_checkpoint(
            novel_id,
            Phase.CONTEXT_PREPARATION.value,
            checkpoint,
            current_volume_id=state.current_volume_id,
            current_chapter_id=chapter_id,
        )
        await session.commit()

        artifacts["resume_reset_chapter_id"] = chapter_id
        artifacts["resume_current_phase"] = Phase.CONTEXT_PREPARATION.value
        artifacts["chapter_id"] = chapter_id
        if checkpoint_changed:
            artifacts["resume_cleared_flow_stop"] = "true"
        return artifacts


async def _current_chapter_id_from_state(novel_id: str) -> str | None:
    async with async_session_maker() as session:
        state = await NovelStateRepository(session).get_state(novel_id)
        if state is None:
            return None
        return _chapter_id_from_state_payload(
            current_chapter_id=state.current_chapter_id,
            checkpoint=dict(state.checkpoint_data or {}),
        )


def _chapter_id_from_state_payload(
    *,
    current_chapter_id: str | None,
    checkpoint: dict[str, Any],
) -> str | None:
    if current_chapter_id:
        return current_chapter_id

    current_plan = checkpoint.get("current_chapter_plan")
    if isinstance(current_plan, dict):
        chapter_id = _first_string(current_plan, "chapter_id", "id")
        if chapter_id:
            return chapter_id

    context = checkpoint.get("chapter_context")
    if isinstance(context, dict):
        context_plan = context.get("chapter_plan")
        if isinstance(context_plan, dict):
            chapter_id = _first_string(context_plan, "chapter_id", "id")
            if chapter_id:
                return chapter_id

    volume_plan = checkpoint.get("current_volume_plan")
    if isinstance(volume_plan, dict):
        chapters = volume_plan.get("chapters")
        if isinstance(chapters, list):
            for item in chapters:
                if isinstance(item, dict):
                    chapter_id = _first_string(item, "chapter_id", "id")
                    if chapter_id:
                        return chapter_id

    return None


async def _prepare_minimal_chapter_plan(
    novel_id: str,
    fixture: GenerationFixture,
    *,
    volume_plan_response: dict[str, Any],
    acceptance_scope: AcceptanceScope = "real-contract",
) -> MinimalChapterPlanResult:
    target_word_count = _acceptance_target_word_count(fixture)
    isolated_volume_id = f"acceptance-{novel_id}-vol1"
    isolated_chapter_id = f"acceptance-{novel_id}-ch1"
    async with async_session_maker() as session:
        repo = NovelStateRepository(session)
        chapter_repo = ChapterRepository(session)
        state = await repo.get_state(novel_id)
        if state is None:
            raise RuntimeError(f"Novel state not found for {novel_id}")

        checkpoint = dict(state.checkpoint_data or {})
        checkpoint["acceptance_scope"] = acceptance_scope
        current_volume_plan = dict(checkpoint.get("current_volume_plan") or {})
        review_status = current_volume_plan.get("review_status")
        if isinstance(review_status, dict) and review_status.get("status") == "revise_failed":
            raise ContractValidationError(
                "volume_plan_contract",
                "volume_plan review failed before a usable acceptance chapter plan was prepared",
                build_volume_plan_contract_evidence(volume_plan_response, checkpoint),
            )
        extraction = extract_chapter_plan(volume_plan_response, checkpoint)
        if extraction is None:
            raise ContractValidationError(
                "volume_plan_contract",
                "volume_plan did not produce a usable chapter plan",
                build_volume_plan_contract_evidence(volume_plan_response, checkpoint),
            )

        current_chapter_plan = dict(extraction.plan)
        current_chapter_plan["chapter_id"] = isolated_chapter_id
        current_chapter_plan["chapter_number"] = 1
        current_chapter_plan["target_word_count"] = target_word_count
        beats = current_chapter_plan.get("beats")
        if isinstance(beats, list) and beats:
            beat_target_word_count = max(1, round(target_word_count / len(beats)))
            normalized_beats = []
            for beat in beats:
                beat_payload = dict(beat) if isinstance(beat, dict) else {"summary": str(beat)}
                beat_payload["target_word_count"] = beat_target_word_count
                normalized_beats.append(beat_payload)
            current_chapter_plan["beats"] = normalized_beats
        checkpoint["current_chapter_plan"] = current_chapter_plan
        chapter_context = checkpoint.get("chapter_context")
        if isinstance(chapter_context, dict):
            chapter_context = dict(chapter_context)
            chapter_context["chapter_plan"] = dict(current_chapter_plan)
            checkpoint["chapter_context"] = chapter_context

        current_volume_plan["volume_id"] = isolated_volume_id
        current_volume_plan["estimated_total_words"] = target_word_count
        current_volume_plan["total_chapters"] = 1
        current_volume_plan["chapters"] = [dict(current_chapter_plan)]
        checkpoint["current_volume_plan"] = current_volume_plan

        chapter = await chapter_repo.ensure_from_plan(
            novel_id,
            isolated_volume_id,
            current_chapter_plan,
        )
        if chapter.novel_id != novel_id:
            chapter.novel_id = novel_id
        if chapter.volume_id != isolated_volume_id:
            chapter.volume_id = isolated_volume_id
        if chapter.chapter_number != 1:
            chapter.chapter_number = 1
        if chapter.title != current_chapter_plan.get("title"):
            chapter.title = current_chapter_plan.get("title")
        await chapter_repo.reset_generation(isolated_chapter_id)

        await repo.save_checkpoint(
            novel_id,
            Phase.CONTEXT_PREPARATION.value,
            checkpoint,
            current_volume_id=isolated_volume_id,
            current_chapter_id=isolated_chapter_id,
        )
        await session.commit()

    return MinimalChapterPlanResult(
        chapter_id=isolated_chapter_id,
        volume_id=isolated_volume_id,
        source=extraction.source,
        target_word_count=target_word_count,
    )


async def _prepare_minimal_synopsis(
    novel_id: str,
    fixture: GenerationFixture,
) -> BrainstormContractResult:
    async with async_session_maker() as session:
        repo = NovelStateRepository(session)
        state = await repo.get_state(novel_id)
        if state is None:
            raise RuntimeError(f"Novel state not found for {novel_id}")

        checkpoint = dict(state.checkpoint_data or {})
        raw_synopsis = checkpoint.get("synopsis_data")
        if raw_synopsis is not None and not isinstance(raw_synopsis, dict):
            raise ContractValidationError(
                "brainstorm_contract",
                "brainstorm persisted malformed synopsis_data",
                _build_brainstorm_contract_evidence(
                    checkpoint,
                    synopsis=raw_synopsis,
                ),
            )

        synopsis = dict(raw_synopsis or {})
        if not synopsis:
            raise ContractValidationError(
                "brainstorm_contract",
                "brainstorm did not persist synopsis_data",
                _build_brainstorm_contract_evidence(checkpoint, synopsis=None),
            )
        original_estimated_volumes = _coerce_int(synopsis.get("estimated_volumes"))
        original_estimated_total_chapters = _coerce_int(
            synopsis.get("estimated_total_chapters")
        )
        outlines = synopsis.get("volume_outlines")
        if outlines is not None and not isinstance(outlines, list):
            raise ContractValidationError(
                "brainstorm_contract",
                "brainstorm persisted malformed volume_outlines",
                _build_brainstorm_contract_evidence(checkpoint, synopsis=synopsis),
            )

        synopsis["estimated_volumes"] = 1
        synopsis["estimated_total_chapters"] = 1
        synopsis["estimated_total_words"] = _acceptance_target_word_count(fixture)

        if isinstance(outlines, list) and outlines and not isinstance(outlines[0], dict):
            raise ContractValidationError(
                "brainstorm_contract",
                "brainstorm persisted malformed first volume outline",
                _build_brainstorm_contract_evidence(
                    checkpoint,
                    synopsis=synopsis,
                    first_outline=outlines[0],
                ),
            )

        first_outline = dict(outlines[0] or {}) if isinstance(outlines, list) and outlines else {}
        first_outline["volume_number"] = 1
        first_outline.setdefault("title", "第1卷")
        first_outline.setdefault("summary", synopsis.get("logline") or synopsis.get("core_conflict") or "最小验收卷")
        first_outline["target_chapter_range"] = "1-1"
        synopsis["volume_outlines"] = [first_outline]

        checkpoint["synopsis_data"] = synopsis
        await repo.save_checkpoint(
            novel_id,
            state.current_phase,
            checkpoint,
            current_volume_id=state.current_volume_id,
            current_chapter_id=state.current_chapter_id,
        )
        await session.commit()

    return BrainstormContractResult(
        original_estimated_volumes=original_estimated_volumes,
        original_estimated_total_chapters=original_estimated_total_chapters,
        shrunk_estimated_total_chapters=1,
    )


async def _prepare_longform_synopsis_contract(
    novel_id: str,
    options: GenerationRunOptions,
) -> None:
    async with async_session_maker() as session:
        repo = NovelStateRepository(session)
        state = await repo.get_state(novel_id)
        if state is None:
            raise RuntimeError(f"Novel state not found for {novel_id}")

        checkpoint = dict(state.checkpoint_data or {})
        raw_synopsis = checkpoint.get("synopsis_data")
        if raw_synopsis is not None and not isinstance(raw_synopsis, dict):
            raise ContractValidationError(
                "brainstorm_contract",
                "brainstorm persisted malformed synopsis_data",
                _build_brainstorm_contract_evidence(checkpoint, synopsis=raw_synopsis),
            )
        synopsis = dict(raw_synopsis or {})
        if not synopsis:
            raise ContractValidationError(
                "brainstorm_contract",
                "brainstorm did not persist synopsis_data",
                _build_brainstorm_contract_evidence(checkpoint, synopsis=None),
            )
        outlines = synopsis.get("volume_outlines")
        if outlines is not None and not isinstance(outlines, list):
            raise ContractValidationError(
                "brainstorm_contract",
                "brainstorm persisted malformed volume_outlines",
                _build_brainstorm_contract_evidence(checkpoint, synopsis=synopsis),
            )

        normalized_outlines = []
        for item in outlines or []:
            if isinstance(item, dict):
                normalized_outlines.append(dict(item))
        target_outline = next(
            (
                item
                for item in normalized_outlines
                if _coerce_int(item.get("volume_number")) == options.target_volume_number
            ),
            None,
        )
        if target_outline is None:
            target_outline = {
                "volume_number": options.target_volume_number,
                "title": f"第{options.target_volume_number}卷",
                "summary": synopsis.get("logline") or synopsis.get("core_conflict") or "长篇验收目标卷",
            }
            normalized_outlines.append(target_outline)

        start_chapter, end_chapter = _target_volume_chapter_range(options)
        target_outline["volume_number"] = options.target_volume_number
        target_outline.setdefault("title", f"第{options.target_volume_number}卷")
        target_outline.setdefault("summary", synopsis.get("logline") or synopsis.get("core_conflict") or "长篇验收目标卷")
        target_outline["target_chapter_range"] = f"{start_chapter}-{end_chapter}"

        synopsis["estimated_volumes"] = options.target_volumes
        synopsis["estimated_total_chapters"] = options.target_chapters
        synopsis["estimated_total_words"] = options.target_word_count
        synopsis["volume_outlines"] = sorted(
            normalized_outlines,
            key=lambda item: _coerce_int(item.get("volume_number")) or 0,
        )
        checkpoint["synopsis_data"] = synopsis
        checkpoint["acceptance_scope"] = options.acceptance_scope
        checkpoint["longform_target"] = {
            "target_volumes": options.target_volumes,
            "target_chapters": options.target_chapters,
            "target_word_count": options.target_word_count,
            "target_volume_number": options.target_volume_number,
            "target_volume_chapters": options.resolved_target_volume_chapters(),
            "chapter_target_word_count": options.resolved_chapter_target_word_count(),
            "target_volume_word_count": options.resolved_target_volume_word_count(),
        }

        await repo.save_checkpoint(
            novel_id,
            state.current_phase,
            checkpoint,
            current_volume_id=state.current_volume_id,
            current_chapter_id=state.current_chapter_id,
        )
        await session.commit()


async def _prepare_longform_volume_plan_contract(
    novel_id: str,
    options: GenerationRunOptions,
) -> None:
    chapter_target = options.resolved_chapter_target_word_count()
    target_chapter_count = options.resolved_target_volume_chapters()
    async with async_session_maker() as session:
        repo = NovelStateRepository(session)
        state = await repo.get_state(novel_id)
        if state is None:
            raise RuntimeError(f"Novel state not found for {novel_id}")

        checkpoint = dict(state.checkpoint_data or {})
        volume_plan = checkpoint.get("current_volume_plan")
        if not isinstance(volume_plan, dict):
            raise ContractValidationError(
                "volume_plan_contract",
                "volume_plan did not persist current_volume_plan",
                build_volume_plan_contract_evidence({}, checkpoint),
            )
        volume_plan = dict(volume_plan)
        chapters = volume_plan.get("chapters")
        if not isinstance(chapters, list) or not chapters:
            raise ContractValidationError(
                "volume_plan_contract",
                "volume_plan did not persist usable chapters",
                build_volume_plan_contract_evidence(volume_plan, checkpoint),
            )

        source_chapters = []
        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            source_chapters.append(dict(chapter))

        archived_rows = await session.execute(
            select(Chapter.chapter_number)
            .where(Chapter.novel_id == novel_id)
            .where(Chapter.volume_id == (volume_plan.get("volume_id") or state.current_volume_id))
            .where(Chapter.status == "archived")
        )
        fixed_prefix_count = max([number for number in archived_rows.scalars().all() if number] or [0])
        if len(source_chapters) < target_chapter_count:
            source_chapters = _expand_longform_chapter_plan(
                source_chapters,
                target_count=target_chapter_count,
                fixed_prefix_count=fixed_prefix_count,
                volume_id=str(volume_plan.get("volume_id") or state.current_volume_id or "vol_1"),
            )
        elif len(source_chapters) > target_chapter_count:
            source_chapters = source_chapters[:target_chapter_count]

        normalized_chapters = []
        for chapter_payload in source_chapters:
            chapter_payload = dict(chapter_payload)
            chapter_payload["target_word_count"] = chapter_target
            beats = chapter_payload.get("beats")
            if isinstance(beats, list) and beats:
                beat_target = max(1, round(chapter_target / len(beats)))
                normalized_beats = []
                for beat in beats:
                    beat_payload = dict(beat) if isinstance(beat, dict) else {"summary": str(beat)}
                    beat_payload["target_word_count"] = beat_target
                    normalized_beats.append(beat_payload)
                chapter_payload["beats"] = normalized_beats
            normalized_chapters.append(chapter_payload)

        volume_plan["chapters"] = normalized_chapters
        volume_plan["total_chapters"] = target_chapter_count
        volume_plan["estimated_total_words"] = options.resolved_target_volume_word_count()
        checkpoint["current_volume_plan"] = volume_plan
        checkpoint["acceptance_scope"] = options.acceptance_scope

        current_chapter_id = state.current_chapter_id
        current_plan = checkpoint.get("current_chapter_plan")
        replacement = None
        if isinstance(current_plan, dict):
            current_id = current_plan.get("chapter_id")
            replacement = next((item for item in normalized_chapters if item.get("chapter_id") == current_id), None)
        if replacement is None and current_chapter_id:
            replacement = next((item for item in normalized_chapters if item.get("chapter_id") == current_chapter_id), None)
        if replacement is None and normalized_chapters:
            replacement = normalized_chapters[0]
        if replacement is not None:
            checkpoint["current_chapter_plan"] = dict(replacement)
            chapter_context = checkpoint.get("chapter_context")
            if isinstance(chapter_context, dict):
                chapter_context = dict(chapter_context)
                chapter_context["chapter_plan"] = dict(replacement)
                checkpoint["chapter_context"] = chapter_context

        await repo.save_checkpoint(
            novel_id,
            state.current_phase,
            checkpoint,
            current_volume_id=state.current_volume_id,
            current_chapter_id=state.current_chapter_id,
        )
        await session.commit()


def _target_volume_chapter_range(options: GenerationRunOptions) -> tuple[int, int]:
    start = 1
    for volume_number in range(1, options.target_volume_number):
        base, remainder = divmod(options.target_chapters, options.target_volumes)
        start += base + (1 if volume_number <= remainder else 0)
    end = start + options.resolved_target_volume_chapters() - 1
    return start, end


def _expand_longform_chapter_plan(
    chapters: list[dict[str, Any]],
    *,
    target_count: int,
    fixed_prefix_count: int = 0,
    volume_id: str,
) -> list[dict[str, Any]]:
    if target_count <= 0 or not chapters:
        return chapters

    fixed_prefix_count = max(0, min(fixed_prefix_count, len(chapters), target_count))
    fixed_prefix = [dict(chapter) for chapter in chapters[:fixed_prefix_count]]
    remaining_sources = [dict(chapter) for chapter in chapters[fixed_prefix_count:]]
    remaining_target = target_count - fixed_prefix_count
    if remaining_target <= 0 or not remaining_sources:
        return fixed_prefix[:target_count]

    source_indexes = [
        min(
            len(remaining_sources) - 1,
            int(offset * len(remaining_sources) / remaining_target),
        )
        for offset in range(remaining_target)
    ]
    total_parts_by_source: dict[int, int] = {}
    for source_index in source_indexes:
        total_parts_by_source[source_index] = total_parts_by_source.get(source_index, 0) + 1
    seen_parts_by_source: dict[int, int] = {}

    expanded = fixed_prefix
    phase_labels = ("铺垫", "试探", "升级", "兑现", "余波")
    for offset, source_index in enumerate(source_indexes, start=1):
        chapter_number = fixed_prefix_count + offset
        source = dict(remaining_sources[source_index])
        seen_parts_by_source[source_index] = seen_parts_by_source.get(source_index, 0) + 1
        part_index = seen_parts_by_source[source_index]
        part_total = total_parts_by_source[source_index]
        phase = phase_labels[min(part_index - 1, len(phase_labels) - 1)]

        title = str(source.get("title") or f"第{chapter_number}章").strip()
        if part_total > 1:
            title = f"{title}·{phase}"

        summary = str(source.get("summary") or title).strip()
        if part_total > 1:
            summary = (
                f"{summary} 本章作为该情节节点的{phase}段推进，"
                "只完成当前小目标，保留后续冲突、线索或反转给下一章。"
            )

        payload = dict(source)
        payload["chapter_id"] = f"{volume_id}_ch_{chapter_number}"
        payload["chapter_number"] = chapter_number
        payload["title"] = title
        payload["summary"] = summary
        expanded.append(payload)

    return expanded


def _first_string(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return str(value)
    return None


def _coerce_int(value: Any) -> int | None:
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


def _coerce_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _build_brainstorm_contract_evidence(
    checkpoint: dict[str, Any],
    *,
    synopsis: Any | None,
    first_outline: Any | None = None,
) -> list[str]:
    evidence = [f"checkpoint_keys={_sorted_keys(checkpoint)}"]
    if synopsis is None:
        evidence.append("synopsis_present=false")
        return evidence

    if not isinstance(synopsis, dict):
        evidence.append(f"synopsis_type={type(synopsis).__name__}")
        return evidence

    evidence.append(f"synopsis_keys={_sorted_keys(synopsis)}")
    outlines = synopsis.get("volume_outlines")
    evidence.append(f"volume_outlines_type={type(outlines).__name__}")
    if isinstance(outlines, list):
        evidence.append(f"volume_outlines_count={len(outlines)}")
    if first_outline is not None:
        evidence.append(f"first_volume_outline_type={type(first_outline).__name__}")
    return evidence


def _sorted_keys(data: dict[str, Any]) -> str:
    keys = sorted(str(key) for key in data.keys())
    return ",".join(keys) if keys else "none"


def _build_setting_clarification_reply(
    fixture: GenerationFixture,
    *,
    last_questions: list[str],
    attempt: int,
) -> str:
    lines = [
        f"这是自动化验收的第 {attempt} 轮澄清回复。",
        fixture.initial_setting_idea,
        "默认要求：直接围绕宗门、修炼规则、主角、对立势力、核心冲突和第一章目标补全最小可用设定。",
        "如果还有局部信息缺口，请基于以上目标采用保守假设，并尽快进入可生成状态。",
    ]
    if last_questions:
        lines.append("针对当前问题，统一补充如下：")
        lines.extend(f"- {question}" for question in last_questions)
        lines.append(
            "回答：第一卷聚焦林照在青云宗外门调查家族覆灭线索，"
            "对立势力至少包含玄火盟或血海殿，前期目标是活下来并拿到第一条真相线索。"
        )
    return "\n".join(lines)


def _require_string(data: dict[str, Any], key: str, stage: str) -> str:
    value = _first_string(data, key)
    if value is None:
        raise RuntimeError(f"{stage} response missing {key}")
    return value


def _run_fake_generation_diagnostic(fixture: GenerationFixture) -> None:
    settings_findings = validate_settings(
        {
            "worldview": fixture.initial_setting_idea,
            "characters": ["林照"],
            "factions": ["青云宗"],
            "locations": ["青云宗外门"],
            "rules": ["修炼规则"],
            "core_conflicts": ["查明家族覆灭真相"],
        }
    )
    outline_findings = validate_outline(
        {
            "main_line": fixture.initial_setting_idea,
            "conflicts": ["林照追查真相时遭遇对立势力阻挠"],
            "character_motivations": ["林照要查明家族覆灭真相"],
            "chapters": [{"beats": ["觉醒目标", "进入调查"]}],
        }
    )
    findings = settings_findings + outline_findings
    if findings:
        messages = "; ".join(
            f"{finding.code}: {finding.message}" for finding in findings
        )
        raise RuntimeError(f"Fake generation diagnostic validation failed: {messages}")


def _validate_report_artifacts(artifacts: dict[str, str]) -> None:
    exported_path = artifacts.get("exported_path")
    acceptance_scope = validate_acceptance_scope(
        artifacts.get("acceptance_scope") or artifacts.get("contract_scope")
    )
    archived_count = _coerce_int(artifacts.get("archived_chapter_count")) or 0
    if exported_path is None:
        if _should_require_export(acceptance_scope, archived_count=archived_count):
            raise ContractValidationError(
                "export_contract",
                "Exported novel file missing: exported_path not returned",
                [f"archived_chapter_count={archived_count}"],
            )
        return

    export_file = Path(exported_path)
    if not export_file.exists():
        raise ContractValidationError(
            "export_contract",
            f"Exported novel file missing: {exported_path}",
            [f"exported_path={exported_path}"],
        )
    if export_file.stat().st_size == 0:
        raise ContractValidationError(
            "export_contract",
            f"Exported novel file is empty: {exported_path}",
            [f"exported_path={exported_path}"],
        )


def _timeout_is_external(message: str) -> bool:
    return _has_external_marker(message)


def _quota_or_provider_is_external(message: str) -> bool:
    return _has_external_marker(message)


def _has_external_marker(message: str) -> bool:
    normalized = message.lower()
    tokens = set(re.findall(r"[a-z0-9]+", normalized))
    phrases = (
        "rate limit",
        "rate limited",
        "provider timeout",
        "upstream timeout",
        "upstream queue",
        "external provider",
    )
    localized_markers = ("限流", "配额", "上游", "供应商")
    return (
        bool(tokens & {"rate", "quota", "provider", "upstream", "network"})
        or any(phrase in normalized for phrase in phrases)
        or any(marker in message for marker in localized_markers)
    )


def _exception_is_parse_failure(message: str) -> bool:
    markers = ("parse", "json", "validation")
    normalized = message.lower()
    return any(marker in normalized for marker in markers)


def _auth_or_config_is_external(message: str) -> bool:
    normalized = message.lower()
    markers = (
        "api key",
        "authentication",
        "unauthorized",
        "permission denied",
        "invalid key",
        "401",
        "认证失败",
        "配置或认证失败",
        "有效的 api key",
    )
    return any(marker in normalized or marker in message for marker in markers)


def classify_exception(
    stage: str,
    exc: Exception,
    real_llm: bool,
    acceptance_scope: AcceptanceScope = "real-contract",
) -> Issue:
    issue_type: IssueType
    is_external_blocker = False
    evidence: list[str] = []

    if isinstance(exc, ContractValidationError):
        issue_type = "SYSTEM_BUG"
        return Issue(
            id=f"{issue_type}-{exc.stage}",
            type=issue_type,
            severity="high",
            stage=exc.stage,
            is_external_blocker=False,
            real_llm=real_llm,
            fake_rerun_status=None,
            message=str(exc) or exc.__class__.__name__,
            evidence=exc.evidence,
            reproduce=_reproduce_command_for_stage(exc.stage, acceptance_scope),
        )
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        message = _http_status_error_message(exc)
        evidence.append(f"http_status={status_code}")
        response_text = getattr(exc.response, "text", "")
        if response_text:
            evidence.append(f"response_text={_truncate_evidence(response_text)}")
        if status_code == 429:
            issue_type = "EXTERNAL_BLOCKED"
            is_external_blocker = True
        elif status_code in {401, 502} and _auth_or_config_is_external(message):
            issue_type = "EXTERNAL_BLOCKED"
            is_external_blocker = True
        elif status_code in {402, 403} and _quota_or_provider_is_external(message):
            issue_type = "EXTERNAL_BLOCKED"
            is_external_blocker = True
        elif status_code == 504:
            if _timeout_is_external(message):
                issue_type = "EXTERNAL_BLOCKED"
                is_external_blocker = True
            else:
                issue_type = "TIMEOUT_INTERNAL"
        else:
            issue_type = "SYSTEM_BUG"
    elif isinstance(exc, httpx.TimeoutException):
        issue_type = "TIMEOUT_INTERNAL"
    elif isinstance(exc, LLMRateLimitError):
        issue_type = "EXTERNAL_BLOCKED"
        is_external_blocker = True
    elif isinstance(exc, LLMTimeoutError):
        if _timeout_is_external(str(exc)):
            issue_type = "EXTERNAL_BLOCKED"
            is_external_blocker = True
        else:
            issue_type = "TIMEOUT_INTERNAL"
    elif _exception_is_parse_failure(str(exc)):
        issue_type = "LLM_PARSE_ERROR"
    else:
        issue_type = "SYSTEM_BUG"

    return Issue(
        id=f"{issue_type}-{stage}",
        type=issue_type,
        severity="high",
        stage=stage,
        is_external_blocker=is_external_blocker,
        real_llm=real_llm,
        fake_rerun_status=None,
        message=str(exc) or exc.__class__.__name__,
        evidence=evidence,
        reproduce=_reproduce_command_for_stage(stage, acceptance_scope),
    )


def _truncate_evidence(value: str, limit: int = 800) -> str:
    value = value.replace("\n", "\\n")
    return value if len(value) <= limit else f"{value[:limit]}..."


def _reproduce_command_for_stage(
    stage: str,
    acceptance_scope: AcceptanceScope = "real-contract",
) -> str:
    command = ["scripts/verify_generation_real.sh"]
    if acceptance_scope != "real-contract":
        command.extend(["--acceptance-scope", acceptance_scope])
    stage_arg = _stage_argument_for_reproduce(stage)
    if stage_arg is not None:
        command.extend(["--stage", stage_arg])
        return " ".join(command)
    if stage == "fake_generation_diagnostic":
        command.extend(["--llm-mode", "fake"])
        return " ".join(command)
    return " ".join(command)


def _stage_argument_for_reproduce(stage: str) -> str | None:
    if stage == "quality_gate":
        return "auto_run_chapters"
    if stage in API_GENERATION_STAGES:
        return stage
    if stage.endswith("_contract"):
        candidate = stage.removesuffix("_contract")
        if candidate in API_GENERATION_STAGES:
            return candidate
    return None


def _http_status_error_message(exc: httpx.HTTPStatusError) -> str:
    parts = [str(exc)]
    try:
        parts.append(exc.response.text)
    except Exception:
        pass
    return "\n".join(part for part in parts if part)


def should_fake_rerun_affect_final_status(issue_type: IssueType) -> bool:
    return issue_type == "EXTERNAL_BLOCKED"


def should_run_fake_diagnostic(issue_type: IssueType) -> bool:
    return issue_type in {"EXTERNAL_BLOCKED", "TIMEOUT_INTERNAL"}
