import hashlib
from datetime import datetime
from typing import Any


STAGE_CONTEXT = "context"
STAGE_DRAFT = "draft"
STAGE_REVIEW = "review"
STAGE_EDIT_FAST_REVIEW = "edit_fast_review"
STAGE_LIBRARIAN_ARCHIVE = "librarian_archive"

CHAPTER_RUN_STAGES = [
    STAGE_CONTEXT,
    STAGE_DRAFT,
    STAGE_REVIEW,
    STAGE_EDIT_FAST_REVIEW,
    STAGE_LIBRARIAN_ARCHIVE,
]


PHASE_TO_STAGE = {
    "context_preparation": STAGE_CONTEXT,
    "drafting": STAGE_DRAFT,
    "reviewing": STAGE_REVIEW,
    "editing": STAGE_EDIT_FAST_REVIEW,
    "fast_reviewing": STAGE_EDIT_FAST_REVIEW,
    "librarian": STAGE_LIBRARIAN_ARCHIVE,
    "completed": STAGE_LIBRARIAN_ARCHIVE,
}


STAGE_TO_PHASE = {
    STAGE_CONTEXT: "context_preparation",
    STAGE_DRAFT: "drafting",
    STAGE_REVIEW: "reviewing",
    STAGE_EDIT_FAST_REVIEW: "editing",
    STAGE_LIBRARIAN_ARCHIVE: "librarian",
}


class ChapterRunStateService:
    @staticmethod
    def text_hash(text: str | None) -> str | None:
        if text is None:
            return None
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def stage_from_phase(phase: str | None) -> str:
        return PHASE_TO_STAGE.get(str(phase or ""), STAGE_CONTEXT)

    @staticmethod
    def phase_for_stage(stage: str | None) -> str:
        return STAGE_TO_PHASE.get(str(stage or ""), "context_preparation")

    @staticmethod
    def next_stage(stage: str) -> str | None:
        try:
            idx = CHAPTER_RUN_STAGES.index(stage)
        except ValueError:
            return None
        if idx + 1 >= len(CHAPTER_RUN_STAGES):
            return None
        return CHAPTER_RUN_STAGES[idx + 1]

    @staticmethod
    def artifact_versions(chapter: Any | None) -> dict:
        if chapter is None:
            return {}
        return {
            "raw_draft_hash": ChapterRunStateService.text_hash(getattr(chapter, "raw_draft", None)),
            "polished_text_hash": ChapterRunStateService.text_hash(getattr(chapter, "polished_text", None)),
            "quality_checked_at": (
                getattr(chapter, "quality_checked_at", None).isoformat()
                if getattr(chapter, "quality_checked_at", None)
                else None
            ),
        }

    @staticmethod
    def get(checkpoint: dict) -> dict:
        run = checkpoint.get("chapter_run")
        return dict(run) if isinstance(run, dict) else {}

    @staticmethod
    def ensure(
        checkpoint: dict,
        *,
        novel_id: str,
        chapter_id: str,
        phase: str,
        run_id: str | None = None,
        chapter: Any | None = None,
    ) -> dict:
        run = ChapterRunStateService.get(checkpoint)
        if run.get("chapter_id") != chapter_id:
            run = {
                "novel_id": novel_id,
                "chapter_id": chapter_id,
                "stage": ChapterRunStateService.stage_from_phase(phase),
                "completed_stages": [],
                "attempts": {},
                "last_error": None,
                "artifact_versions": {},
                "started_at": datetime.utcnow().isoformat() + "Z",
            }
        else:
            run.setdefault("novel_id", novel_id)
            run.setdefault("completed_stages", [])
            run.setdefault("attempts", {})
            run.setdefault("stage", ChapterRunStateService.stage_from_phase(phase))
            run.setdefault("artifact_versions", {})
        if run_id:
            run["run_id"] = run_id
        if chapter is not None:
            run["artifact_versions"] = ChapterRunStateService.artifact_versions(chapter)
        run["updated_at"] = datetime.utcnow().isoformat() + "Z"
        checkpoint["chapter_run"] = run
        return run

    @staticmethod
    def mark_stage(
        checkpoint: dict,
        *,
        stage: str,
        status: str,
        chapter: Any | None = None,
        error: str | None = None,
    ) -> dict:
        run = ChapterRunStateService.get(checkpoint)
        run["stage"] = stage
        completed = list(run.get("completed_stages") or [])
        if status == "succeeded" and stage not in completed:
            completed.append(stage)
        run["completed_stages"] = completed
        if error:
            run["last_error"] = {"stage": stage, "error": error}
        elif status == "succeeded":
            run["last_error"] = None
        if chapter is not None:
            run["artifact_versions"] = ChapterRunStateService.artifact_versions(chapter)
        run["updated_at"] = datetime.utcnow().isoformat() + "Z"
        checkpoint["chapter_run"] = run
        return run

    @staticmethod
    def quality_gate_matches_current_polished(checkpoint: dict, chapter: Any | None) -> bool:
        if chapter is None:
            return False
        run = ChapterRunStateService.get(checkpoint)
        artifact_versions = run.get("artifact_versions") if isinstance(run.get("artifact_versions"), dict) else {}
        expected_hash = artifact_versions.get("polished_text_hash")
        current_hash = ChapterRunStateService.text_hash(getattr(chapter, "polished_text", None))
        if expected_hash is None:
            return True
        return expected_hash == current_hash
