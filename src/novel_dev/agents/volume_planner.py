import json
import math
import re
import uuid
from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field, field_validator, model_validator

from novel_dev.schemas.outline import (
    VolumePlan,
    VolumeBeat,
    VolumeScoreResult,
    SynopsisData,
)
from novel_dev.schemas.context import BeatPlan, ChapterPlan
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.version_repo import EntityVersionRepository
from novel_dev.repositories.timeline_repo import TimelineRepository
from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.agents._llm_helpers import (
    call_and_parse_model,
    coerce_to_str_list,
    coerce_to_text,
    orchestrated_call_and_parse_model,
)
from novel_dev.agents._log_helpers import log_agent_detail, named_items, preview_text
from novel_dev.llm import llm_factory
from novel_dev.llm.context_tools import build_mcp_context_tools
from novel_dev.llm.orchestrator import LLMToolSpec, OrchestratedTaskConfig
from novel_dev.services.flow_control_service import FlowControlService
from novel_dev.services.log_service import logged_agent_step, log_service
from novel_dev.services.narrative_constraint_service import ActiveConstraintContext, NarrativeConstraintBuilder
from novel_dev.services.domain_activation_service import DomainActivationService
from novel_dev.services.story_quality_service import StoryQualityService
from novel_dev.services.story_contract_service import StoryContractService


class VolumeChapterSkeleton(BaseModel):
    chapter_number: int
    chapter_id: str = ""
    title: str
    summary: str

    @staticmethod
    def build_chapter_id(volume_number: int | str | None, chapter_number: int | str) -> str:
        if volume_number is None or volume_number == "":
            return f"ch_{chapter_number}"
        return f"vol_{volume_number}_ch_{chapter_number}"

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_fields(cls, value):
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        if "summary" not in normalized:
            for legacy_key in ("description", "chapter_summary", "content"):
                if legacy_key in normalized:
                    normalized["summary"] = normalized[legacy_key]
                    break
        if "title" not in normalized:
            if "chapter_title" in normalized:
                normalized["title"] = normalized["chapter_title"]
            else:
                summary = coerce_to_text(normalized.get("summary")).strip()
                fallback = summary[:18].rstrip("。！？.!?，,；;、 ")
                chapter_number = normalized.get("chapter_number") or normalized.get("number") or normalized.get("index")
                normalized["title"] = fallback or (f"第{chapter_number}章" if chapter_number else "未命名章节")
        if not normalized.get("chapter_id"):
            chapter_number = normalized.get("chapter_number") or normalized.get("number") or normalized.get("index")
            volume_number = normalized.get("volume_number")
            if chapter_number is not None:
                normalized["chapter_id"] = cls.build_chapter_id(volume_number, chapter_number)
        return normalized


class VolumePlanBlueprint(BaseModel):
    volume_id: str
    volume_number: int
    title: str
    summary: str
    total_chapters: int
    estimated_total_words: int
    chapters: list[VolumeChapterSkeleton] = Field(default_factory=list)
    entity_highlights: dict[str, list[str]] = Field(default_factory=dict)
    relationship_highlights: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_fields(cls, value):
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        volume_number = normalized.get("volume_number") or normalized.get("number") or 1
        if "volume_number" not in normalized:
            normalized["volume_number"] = volume_number
        if "volume_id" not in normalized:
            normalized["volume_id"] = normalized.get("id") or normalized.get("volume_ref") or f"vol_{volume_number}"
        if "title" not in normalized:
            normalized["title"] = normalized.get("volume_title") or normalized.get("name") or f"第{volume_number}卷"
        if "summary" not in normalized:
            normalized["summary"] = normalized.get("volume_summary") or normalized.get("description") or ""
        if "estimated_total_words" not in normalized:
            normalized["estimated_total_words"] = (
                normalized.get("total_words") or normalized.get("word_count") or normalized.get("estimated_words") or 3000
            )
        if "total_chapters" not in normalized:
            normalized["total_chapters"] = normalized.get("chapter_count") or len(normalized.get("chapters") or [])
        entity_highlights = normalized.get("entity_highlights")
        if isinstance(entity_highlights, list):
            normalized["entity_highlights"] = {"general": [str(item) for item in entity_highlights]}
        elif isinstance(entity_highlights, str):
            normalized["entity_highlights"] = {"general": [entity_highlights]}
        chapters = normalized.get("chapters")
        if isinstance(chapters, list):
            normalized_chapters = []
            for index, item in enumerate(chapters, start=1):
                if isinstance(item, dict):
                    item = dict(item)
                    item.setdefault("chapter_number", index)
                    item.setdefault("volume_number", normalized["volume_number"])
                    item.setdefault(
                        "chapter_id",
                        VolumeChapterSkeleton.build_chapter_id(normalized["volume_number"], item["chapter_number"]),
                    )
                normalized_chapters.append(item)
            normalized["chapters"] = normalized_chapters
        return normalized

    @field_validator("entity_highlights", mode="before")
    @classmethod
    def _coerce_entity_highlights(cls, value: Any) -> dict[str, list[str]]:
        if value is None or value == "":
            return {}
        if isinstance(value, dict):
            return {str(key): coerce_to_str_list(item) for key, item in value.items()}
        return {"general": coerce_to_str_list(value)}

    @field_validator("relationship_highlights", mode="before")
    @classmethod
    def _coerce_relationship_highlights(cls, value: Any) -> list[str]:
        return coerce_to_str_list(value)


class VolumeChapterPatch(BaseModel):
    chapter_number: int
    title: Optional[str] = None
    summary: Optional[str] = None
    target_word_count: Optional[int] = None
    target_mood: Optional[str] = None
    key_entities: Optional[list[str]] = None
    foreshadowings_to_embed: Optional[list[str]] = None
    foreshadowings_to_recover: Optional[list[str]] = None
    beats: Optional[list[BeatPlan]] = None

    @field_validator("title", "summary", "target_mood", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)

    @field_validator("key_entities", "foreshadowings_to_embed", "foreshadowings_to_recover", mode="before")
    @classmethod
    def _coerce_string_list_fields(cls, value: Any) -> list[str]:
        return coerce_to_str_list(value)


class VolumePlanPatch(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    estimated_total_words: Optional[int] = None
    entity_highlights: Optional[dict[str, list[str]]] = None
    relationship_highlights: Optional[list[str]] = None
    chapter_patches: list[VolumeChapterPatch] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_full_plan_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        if "chapter_patches" not in normalized and isinstance(normalized.get("chapters"), list):
            normalized["chapter_patches"] = normalized["chapters"]
        entity_highlights = normalized.get("entity_highlights")
        if isinstance(entity_highlights, list):
            normalized["entity_highlights"] = {"general": [str(item) for item in entity_highlights]}
        elif isinstance(entity_highlights, str):
            normalized["entity_highlights"] = {"general": [entity_highlights]}
        return normalized

    @field_validator("title", "summary", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)

    @field_validator("relationship_highlights", mode="before")
    @classmethod
    def _coerce_string_list_fields(cls, value: Any) -> list[str]:
        return coerce_to_str_list(value)

    @field_validator("entity_highlights", mode="before")
    @classmethod
    def _coerce_entity_highlights(cls, value: Any) -> dict[str, list[str]]:
        if value is None or value == "":
            return {}
        if isinstance(value, dict):
            return {str(key): coerce_to_str_list(item) for key, item in value.items()}
        return {"general": coerce_to_str_list(value)}


class VolumePlanSemanticJudgement(BaseModel):
    passed: bool = True
    hard_conflicts: list[str] = Field(default_factory=list)
    soft_warnings: list[str] = Field(default_factory=list)
    repair_suggestions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        if "hard_conflicts" not in normalized:
            for legacy_key in ("conflicts", "fatal_issues", "violations"):
                if legacy_key in normalized:
                    normalized["hard_conflicts"] = normalized[legacy_key]
                    break
        if "soft_warnings" not in normalized and "warnings" in normalized:
            normalized["soft_warnings"] = normalized["warnings"]
        if "repair_suggestions" not in normalized:
            for legacy_key in ("suggestions", "fixes", "recommendations"):
                if legacy_key in normalized:
                    normalized["repair_suggestions"] = normalized[legacy_key]
                    break
        if "passed" not in normalized:
            normalized["passed"] = not bool(coerce_to_str_list(normalized.get("hard_conflicts")))
        return normalized

    @field_validator("hard_conflicts", "soft_warnings", "repair_suggestions", mode="before")
    @classmethod
    def _coerce_string_list_fields(cls, value: Any) -> list[str]:
        return coerce_to_str_list(value)


class VolumeBeatExpansion(BaseModel):
    chapter_id: str = ""
    chapter_number: Optional[int] = None
    title: str = ""
    summary: str = ""
    target_word_count: int = 3000
    target_mood: str = "tense"
    key_entities: list[str] = Field(default_factory=list)
    foreshadowings_to_embed: list[str] = Field(default_factory=list)
    foreshadowings_to_recover: list[str] = Field(default_factory=list)
    beats: list[BeatPlan] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        chapter_number = normalized.get("chapter_number") or normalized.get("number") or normalized.get("index")
        if chapter_number is not None and "chapter_number" not in normalized:
            normalized["chapter_number"] = chapter_number
        if "chapter_id" not in normalized and chapter_number is not None:
            volume_number = normalized.get("volume_number")
            normalized["chapter_id"] = VolumeChapterSkeleton.build_chapter_id(volume_number, chapter_number)
        if "summary" not in normalized:
            for legacy_key in ("description", "chapter_summary", "content"):
                if legacy_key in normalized:
                    normalized["summary"] = normalized[legacy_key]
                    break
        if "target_word_count" not in normalized:
            for legacy_key in ("word_count", "estimated_words", "target_words"):
                if legacy_key in normalized:
                    normalized["target_word_count"] = normalized[legacy_key]
                    break
        if "target_mood" not in normalized:
            for legacy_key in ("mood", "tone", "emotion"):
                if legacy_key in normalized:
                    normalized["target_mood"] = normalized[legacy_key]
                    break
        if "foreshadowings_to_recover" not in normalized:
            for legacy_key in ("planned_foreshadowings", "required_foreshadowings", "recover_foreshadowings"):
                if legacy_key in normalized:
                    normalized["foreshadowings_to_recover"] = normalized[legacy_key]
                    break
        return normalized

    @field_validator("chapter_id", "title", "summary", "target_mood", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)

    @field_validator("key_entities", "foreshadowings_to_embed", "foreshadowings_to_recover", mode="before")
    @classmethod
    def _coerce_string_list_fields(cls, value: Any) -> list[str]:
        return coerce_to_str_list(value)


class VolumePlannerAgent:
    MAX_AUTOREVISE_CHAPTERS = 18
    CONSTRAINT_SOURCE_DOC_TYPES = ("worldview", "setting", "concept", "synopsis")

    def __init__(self, session: AsyncSession):
        self.session = session
        self.state_repo = NovelStateRepository(session)
        self.doc_repo = DocumentRepository(session)
        self.chapter_repo = ChapterRepository(session)
        self.entity_repo = EntityRepository(session)
        self.version_repo = EntityVersionRepository(session)
        self.timeline_repo = TimelineRepository(session)
        self.foreshadowing_repo = ForeshadowingRepository(session)
        self.director = NovelDirector(session)
        self.constraint_builder = NarrativeConstraintBuilder()
        self.domain_activation_service = DomainActivationService(session)

    async def _release_connection_before_external_call(self) -> None:
        if self.session.in_transaction():
            await self.session.commit()

    @logged_agent_step("VolumePlannerAgent", "生成分卷规划", node="volume_plan", task="plan")
    async def plan(self, novel_id: str, volume_number: Optional[int] = None) -> VolumePlan:
        log_service.add_log(novel_id, "VolumePlannerAgent", "开始生成分卷规划")
        state = await self.state_repo.get_state(novel_id)
        if not state:
            log_service.add_log(novel_id, "VolumePlannerAgent", "小说状态未找到", level="error")
            raise ValueError(f"Novel state not found for {novel_id}")
        if state.current_phase != Phase.VOLUME_PLANNING.value:
            log_service.add_log(novel_id, "VolumePlannerAgent", f"当前阶段 {state.current_phase} 不允许规划分卷", level="error")
            raise ValueError(f"Cannot plan volume from phase {state.current_phase}")

        checkpoint = dict(state.checkpoint_data or {})
        synopsis_data = checkpoint.get("synopsis_data")
        if not synopsis_data:
            raise ValueError("synopsis_data missing in checkpoint_data")

        synopsis = SynopsisData.model_validate(synopsis_data)

        if volume_number is None:
            volume_number = self._infer_volume_number(checkpoint, state)
        target_chapters = self._infer_exact_target_chapters(synopsis, volume_number)
        log_agent_detail(
            novel_id,
            "VolumePlannerAgent",
            f"卷纲规划输入已准备：第 {volume_number} 卷",
            node="volume_plan_input",
            task="plan",
            status="started",
            metadata={
                "volume_number": volume_number,
                "synopsis_title": synopsis.title,
                "estimated_volumes": synopsis.estimated_volumes,
                "estimated_total_chapters": synopsis.estimated_total_chapters,
                "target_chapters": target_chapters,
                "current_volume_id": state.current_volume_id,
                "current_chapter_id": state.current_chapter_id,
                "checkpoint_keys": sorted(checkpoint.keys()),
            },
        )

        world_snapshot = await self._load_world_snapshot(novel_id) if volume_number > 1 else None
        await self._release_connection_before_external_call()
        volume_plan = await self._generate_volume_plan(
            synopsis,
            volume_number,
            world_snapshot,
            novel_id,
            target_chapters=target_chapters,
        )
        plan_context = await self._build_plan_context(synopsis, world_snapshot, novel_id, volume_number)

        attempt = checkpoint.get("volume_plan_attempt_count", 0)
        skip_full_revise = len(volume_plan.chapters) > self.MAX_AUTOREVISE_CHAPTERS
        while True:
            score = await self._generate_score(volume_plan, novel_id, target_chapters=target_chapters)
            log_agent_detail(
                novel_id,
                "VolumePlannerAgent",
                f"卷纲评分完成：overall={score.overall}",
                node="volume_score",
                task="score_volume_plan",
                metadata={
                    "attempt": attempt + 1,
                    "overall": score.overall,
                    "outline_fidelity": score.outline_fidelity,
                    "character_plot_alignment": score.character_plot_alignment,
                    "hook_distribution": score.hook_distribution,
                    "foreshadowing_management": score.foreshadowing_management,
                    "chapter_hooks": score.chapter_hooks,
                    "page_turning": score.page_turning,
                    "summary_feedback": score.summary_feedback,
                },
            )
            if self._is_acceptable(score):
                log_service.add_log(novel_id, "VolumePlannerAgent", f"评分通过，overall={score.overall}")
                break
            if skip_full_revise:
                log_service.add_log(
                    novel_id,
                    "VolumePlannerAgent",
                    "大卷纲已跳过自动整卷修订，请在工作台继续细化章节。",
                    level="warning",
                )
                break
            attempt += 1
            checkpoint["volume_plan_attempt_count"] = attempt
            log_agent_detail(
                novel_id,
                "VolumePlannerAgent",
                f"卷纲评分未通过，开始第 {attempt} 次修订",
                node="volume_revision",
                task="revise_volume_plan",
                status="started",
                level="warning",
                metadata={
                    "attempt": attempt,
                    "overall": score.overall,
                    "reason": self._build_revise_feedback(score, volume_plan),
                },
            )
            if attempt >= 3:
                log_service.add_log(novel_id, "VolumePlannerAgent", "已达最大修订次数", level="error")
                checkpoint["current_volume_plan"] = self._build_reviewed_volume_plan_payload(
                    volume_plan,
                    score=score,
                    status="revise_failed",
                    reason="已达最大自动修订次数，请在大纲工作台人工调整。",
                    attempt=attempt,
                )
                checkpoint.pop("current_chapter_plan", None)
                await self.director.save_checkpoint(
                    novel_id,
                    phase=Phase.VOLUME_PLANNING,
                    checkpoint_data=checkpoint,
                    volume_id=volume_plan.volume_id,
                    chapter_id=None,
                )
                return volume_plan
            try:
                volume_plan = await self._revise_volume_plan(
                    volume_plan,
                    self._build_revise_feedback(score, volume_plan),
                    plan_context,
                    novel_id,
                )
            except RuntimeError as exc:
                log_service.add_log(novel_id, "VolumePlannerAgent", f"自动修订失败，已保留当前卷纲: {exc}", level="error")
                checkpoint["current_volume_plan"] = self._build_reviewed_volume_plan_payload(
                    volume_plan,
                    score=score,
                    status="revise_failed",
                    reason=f"自动修订失败: {exc}",
                    attempt=attempt,
                )
                checkpoint.pop("current_chapter_plan", None)
                await self.director.save_checkpoint(
                    novel_id,
                    phase=Phase.VOLUME_PLANNING,
                    checkpoint_data=checkpoint,
                    volume_id=volume_plan.volume_id,
                    chapter_id=None,
                )
                return volume_plan

        checkpoint["current_volume_plan"] = self._build_reviewed_volume_plan_payload(
            volume_plan,
            score=score,
            status="accepted" if self._is_acceptable(score) else "needs_manual_review",
            reason="卷纲评分通过。" if self._is_acceptable(score) else "大卷纲已跳过自动整卷修订，请在大纲工作台继续细化章节。",
            attempt=attempt + 1,
        )
        checkpoint["current_chapter_plan"] = self._extract_chapter_plan(volume_plan.chapters[0])
        checkpoint["volume_plan_attempt_count"] = 0
        await self._persist_volume_plan_artifacts(novel_id, volume_plan)
        log_agent_detail(
            novel_id,
            "VolumePlannerAgent",
            f"分卷规划完成：{volume_plan.title}，共 {len(volume_plan.chapters)} 章",
            node="volume_plan_result",
            task="plan",
            metadata={
                "volume_id": volume_plan.volume_id,
                "title": volume_plan.title,
                "chapter_count": len(volume_plan.chapters),
                "estimated_total_words": volume_plan.estimated_total_words,
                "chapters": [
                    {
                        "chapter_id": chapter.chapter_id,
                        "chapter_number": chapter.chapter_number,
                        "title": chapter.title,
                        "summary_preview": preview_text(chapter.summary),
                    }
                    for chapter in volume_plan.chapters[:12]
                ],
            },
        )

        await self.director.save_checkpoint(
            novel_id,
            phase=Phase.CONTEXT_PREPARATION,
            checkpoint_data=checkpoint,
            volume_id=volume_plan.volume_id,
            chapter_id=volume_plan.chapters[0].chapter_id,
        )
        log_service.add_log(novel_id, "VolumePlannerAgent", "进入 context_preparation 阶段")

        return volume_plan

    async def _persist_volume_plan_artifacts(self, novel_id: str, volume_plan: VolumePlan) -> None:
        for chapter_plan in volume_plan.chapters:
            await self.chapter_repo.ensure_from_plan(novel_id, volume_plan.volume_id, chapter_plan)
        await self.doc_repo.create(
            doc_id=f"doc_{uuid.uuid4().hex[:8]}",
            novel_id=novel_id,
            doc_type="volume_plan",
            title=f"{volume_plan.title}",
            content=volume_plan.model_dump_json(),
        )

    # Overall 只要及格,但关键维度(爽点分布、人物与情节契合)必须达标,否则是"虚高"。
    OVERALL_THRESHOLD = 75
    KEY_DIM_THRESHOLDS = {
        "hook_distribution": 75,
        "character_plot_alignment": 75,
        "page_turning": 70,
    }
    CHAPTER_BATCH_SIZE = 4

    def _suggest_volume_chapter_range(self, synopsis: SynopsisData, target_chapters: Optional[int] = None) -> tuple[int, int]:
        if target_chapters:
            return target_chapters, target_chapters
        estimated_volumes = max(1, synopsis.estimated_volumes or 1)
        estimated_total_chapters = max(1, synopsis.estimated_total_chapters or 1)
        rough_chapters_per_volume = math.ceil(estimated_total_chapters / estimated_volumes)

        if rough_chapters_per_volume <= 6:
            lower = max(3, rough_chapters_per_volume)
            upper = max(lower, min(6, rough_chapters_per_volume + 1))
            return lower, upper
        if rough_chapters_per_volume <= 18:
            lower = max(6, rough_chapters_per_volume - 2)
            upper = min(20, rough_chapters_per_volume + 2)
            return lower, max(lower, upper)
        return 20, 36

    def _infer_exact_target_chapters(self, synopsis: SynopsisData, volume_number: int) -> Optional[int]:
        for outline in synopsis.volume_outlines or []:
            if outline.volume_number != volume_number:
                continue
            raw_range = (outline.target_chapter_range or "").strip()
            if not raw_range:
                return None
            single = re.fullmatch(r"(\d+)", raw_range)
            if single:
                return int(single.group(1))
            ranged = re.fullmatch(r"(\d+)\s*[-~—–至到]\s*(\d+)", raw_range)
            if not ranged:
                return None
            lower = int(ranged.group(1))
            upper = int(ranged.group(2))
            return lower if lower == upper else None
        return None

    def _is_acceptable(self, score) -> bool:
        if score.overall < self.OVERALL_THRESHOLD:
            return False
        for dim, floor in self.KEY_DIM_THRESHOLDS.items():
            if getattr(score, dim, 100) < floor:
                return False
        return True

    def _build_revise_feedback(self, score, plan: VolumePlan | None = None) -> str:
        failing = []
        for dim, floor in self.KEY_DIM_THRESHOLDS.items():
            val = getattr(score, dim, 100)
            if val < floor:
                failing.append(f"{dim}={val}(下限 {floor})")
        lines = [f"overall={score.overall}(下限 {self.OVERALL_THRESHOLD})"] if score.overall < self.OVERALL_THRESHOLD else []
        if failing:
            lines.append("关键维度未达标: " + ", ".join(failing))
        if score.summary_feedback:
            lines.append(f"评审意见: {score.summary_feedback}")
        if plan is not None:
            writability = self._build_volume_writability_summary(plan)
            if not writability.get("passed", True):
                lines.append("章节可写性未通过，必须优先修正以下结构问题:")
                for chapter in writability.get("chapters", []):
                    report = chapter.get("report") or {}
                    blocking = report.get("blocking_issues") or []
                    if blocking:
                        lines.append(
                            f"- 第 {chapter.get('chapter_number')} 章《{chapter.get('title')}》: "
                            + "；".join(str(item) for item in blocking[:4])
                        )
                    suggestions = report.get("repair_suggestions") or []
                    for item in suggestions[:2]:
                        lines.append(f"- 修复方式: {item}")
        lines.append(
            "请针对以上未达标维度逐项修正:"
            "爽点分布不足就增加每 2-3 章的小高潮与钩子;"
            "人物与情节契合低说明角色目标/动机与情节推进脱节,需补强动机逻辑;"
            "页面翻动欲低意味着章末钩子不够,需在每章结尾加入悬念/反转/赌注升级。"
        )
        return "\n".join(lines)

    def _build_reviewed_volume_plan_payload(
        self,
        plan: VolumePlan,
        *,
        score: VolumeScoreResult,
        status: str,
        reason: str,
        attempt: int,
    ) -> dict[str, Any]:
        payload = plan.model_dump()
        writability = self._build_volume_writability_summary(plan)
        payload["review_status"] = {
            "status": status,
            "reason": reason,
            "attempt": attempt,
            "score": score.model_dump(),
            "writability_status": writability,
        }
        return payload

    def _build_volume_writability_summary(self, plan: VolumePlan) -> dict[str, Any]:
        chapter_reports = []
        failed_numbers = []
        for chapter in plan.chapters:
            report = StoryQualityService.evaluate_chapter_writability(chapter)
            if not report.passed:
                failed_numbers.append(chapter.chapter_number)
            chapter_reports.append({
                "chapter_id": chapter.chapter_id,
                "chapter_number": chapter.chapter_number,
                "title": chapter.title,
                "report": report.model_dump(),
            })
        return {
            "passed": not failed_numbers,
            "failed_chapter_numbers": failed_numbers,
            "chapters": chapter_reports,
        }

    def _infer_volume_number(self, checkpoint: dict, state) -> int:
        if state.current_volume_id and state.current_volume_id.startswith("vol_"):
            try:
                return int(state.current_volume_id.replace("vol_", ""))
            except ValueError:
                pass
        return 1

    async def _build_plan_context(
        self,
        synopsis: SynopsisData,
        world_snapshot: Optional[dict],
        novel_id: str = "",
        volume_number: Optional[int] = None,
    ) -> str:
        synopsis_text = synopsis.model_dump_json()[:12000]
        constraint_block = ""
        if volume_number is not None:
            source_text = await self._load_constraint_source_text(novel_id)
            constraint = await self.domain_activation_service.build_context(
                novel_id=novel_id,
                synopsis=synopsis,
                volume_number=volume_number,
                source_text=source_text,
                world_snapshot=world_snapshot,
            )
            constraint_block = "\n\n" + constraint.to_prompt_block()
        if not world_snapshot:
            return f"### 大纲数据\n{synopsis_text}{constraint_block}"
        return (
            f"### 大纲数据\n{synopsis_text}\n\n"
            "### 前卷世界状态快照\n"
            f"活跃人物:\n{world_snapshot.get('entities', '无')}\n"
            f"未回收伏笔:\n{world_snapshot.get('foreshadowings', '无')}\n"
            f"已推进时间线:\n{world_snapshot.get('timeline', '无')}"
            f"{constraint_block}"
        )

    def _build_volume_contract_context(self, synopsis: SynopsisData, volume_number: int) -> str:
        outlines = list(synopsis.volume_outlines or [])
        if not outlines:
            return "### 本卷总纲契约\n无明确卷级契约，请从总纲整体推导，但不要偏离核心冲突。"

        def dump_contract(label: str, number: int) -> str:
            match = next((item for item in outlines if item.volume_number == number), None)
            if not match:
                return ""
            return f"### {label}\n{match.model_dump_json()}"

        blocks = [
            dump_contract("上一卷契约", volume_number - 1),
            dump_contract("本卷总纲契约(必须优先遵守)", volume_number),
            dump_contract("下一卷契约(仅用于衔接铺垫)", volume_number + 1),
        ]
        return "\n\n".join(block for block in blocks if block)

    def _build_score_plan_snapshot(self, plan: VolumePlan) -> str:
        snapshot = {
            "volume_id": plan.volume_id,
            "volume_number": plan.volume_number,
            "title": plan.title,
            "summary": plan.summary,
            "total_chapters": plan.total_chapters,
            "estimated_total_words": plan.estimated_total_words,
            "chapters": [],
        }
        for chapter in plan.chapters:
            hook = chapter.beats[-1].summary if chapter.beats else ""
            snapshot["chapters"].append({
                "chapter_number": chapter.chapter_number,
                "title": chapter.title,
                "summary": chapter.summary,
                "hook": hook,
                "foreshadowings_to_embed": chapter.foreshadowings_to_embed,
                "foreshadowings_to_recover": chapter.foreshadowings_to_recover,
            })
        return json.dumps(snapshot, ensure_ascii=False)

    async def _generate_volume_plan(
        self,
        synopsis: SynopsisData,
        volume_number: int,
        world_snapshot: Optional[dict] = None,
        novel_id: str = "",
        generation_instruction: str = "",
        target_chapters: Optional[int] = None,
    ) -> VolumePlan:
        log_agent_detail(
            novel_id,
            "VolumePlannerAgent",
            "卷纲生成输入摘要已准备",
            node="volume_generate_input",
            task="generate_volume_plan",
            status="started",
            metadata={
                "volume_number": volume_number,
                "synopsis_title": synopsis.title,
                "synopsis_chars": len(synopsis.model_dump_json()),
                "world_snapshot_present": bool(world_snapshot),
                "generation_instruction_preview": preview_text(generation_instruction, 300),
                "target_chapters": target_chapters,
            },
        )
        MAX_CHARS = 8000
        chapter_range = self._suggest_volume_chapter_range(synopsis, target_chapters=target_chapters)
        volume_contract_block = self._build_volume_contract_context(synopsis, volume_number)
        source_text = await self._load_constraint_source_text(novel_id)
        constraint_context = await self.domain_activation_service.build_context(
            novel_id=novel_id,
            synopsis=synopsis,
            volume_number=volume_number,
            source_text=source_text,
            world_snapshot=world_snapshot,
        )
        log_service.add_log(
            novel_id,
            "VolumePlannerAgent",
            "已构建第 "
            f"{volume_number} 卷叙事约束包: "
            f"规则域[{self._join_log_names(constraint_context.active_domains)}], "
            f"片段[{self._join_log_names(constraint_context.source_snippets)}]",
            event="agent.progress",
            status="succeeded",
            node="volume_constraints",
            task="build_active_constraint_context",
            metadata={
                "volume_number": volume_number,
                "active_domains": constraint_context.active_domains,
                "source_snippets": constraint_context.source_snippets[:12],
                "source_snippet_count": len(constraint_context.source_snippets),
                "current_scope": constraint_context.current_scope[:12],
                "allowed_conflicts": constraint_context.allowed_conflicts[:12],
                "foreshadow_only": constraint_context.foreshadow_only[:12],
                "forbidden_now": constraint_context.forbidden_now[:12],
                "power_ladder": constraint_context.power_ladder[:12],
                "knowledge_boundaries": constraint_context.knowledge_boundaries[:12],
                "executable_constraints": [
                    item.to_prompt_line() for item in constraint_context.executable_constraints[:12]
                ],
            },
        )
        constraint_block = constraint_context.to_prompt_block()

        world_block = ""
        if world_snapshot:
            log_service.add_log(
                novel_id,
                "VolumePlannerAgent",
                "卷纲使用前卷世界状态快照: "
                f"实体[{self._snapshot_preview(world_snapshot.get('entities'))}], "
                f"伏笔[{self._snapshot_preview(world_snapshot.get('foreshadowings'))}], "
                f"时间线[{self._snapshot_preview(world_snapshot.get('timeline'))}]",
                event="agent.progress",
                status="succeeded",
                node="volume_world_snapshot",
                task="generate_volume_plan",
                metadata={
                    "entities_preview": self._snapshot_preview(world_snapshot.get("entities"), limit=500),
                    "foreshadowings_preview": self._snapshot_preview(world_snapshot.get("foreshadowings"), limit=500),
                    "timeline_preview": self._snapshot_preview(world_snapshot.get("timeline"), limit=500),
                },
            )
            world_block = (
                "\n\n### 前卷世界状态快照(本卷规划必须与以下事实一致,不得与之矛盾)\n"
                f"活跃人物:\n{world_snapshot.get('entities', '无')}\n"
                f"未回收伏笔(本卷内应考虑回收部分):\n{world_snapshot.get('foreshadowings', '无')}\n"
                f"已推进时间线:\n{world_snapshot.get('timeline', '无')}\n"
            )
        instruction_block = (
            "\n\n### 本次重新生成要求\n"
            f"{generation_instruction.strip()[:1200]}\n"
            "必须按以上要求重新生成完整卷纲,不要沿用旧卷纲结构。"
            if generation_instruction.strip()
            else ""
        )

        scale_rule = (
            f"1. total_chapters 必须等于 {target_chapters} 章，chapters 数组也必须恰好包含 {target_chapters} 项。\n"
            if target_chapters
            else f"1. total_chapters 必须控制在 {chapter_range[0]}-{chapter_range[1]} 章之间。\n"
        )
        orchestration_config = llm_factory.resolve_orchestration_config(
            "volume_planner_agent",
            "generate_volume_plan",
        )
        if orchestration_config is not None:
            volume_contract_block = self._build_volume_contract_catalog(synopsis, volume_number)
        synopsis_prompt_data = (
            self._build_synopsis_catalog(synopsis)
            if orchestration_config is not None
            else synopsis.model_dump_json()[:MAX_CHARS]
        )
        if orchestration_config is not None:
            story_contract = {
                "protagonist_goal": synopsis.logline,
                "current_stage_goal": "",
                "first_chapter_goal": "",
                "core_conflict": synopsis.core_conflict,
                "key_clues": [],
                "antagonistic_pressure": "",
                "must_carry_forward": [],
            }
        else:
            story_contract = StoryContractService.build_from_snapshot({
                "checkpoint": {
                    "synopsis_data": synopsis.model_dump(mode="json"),
                    "current_volume_number": volume_number,
                }
            })
        story_contract_block = (
            "## 故事契约\n"
            f"{json.dumps(story_contract, ensure_ascii=False)}\n"
            "当前卷章节摘要要继承 protagonist_goal、current_stage_goal、core_conflict,"
            "并把主角目标、阻力、选择代价写进每章推进。"
        )
        volume_context = {
            "novel_id": novel_id,
            "volume_number": volume_number,
            "synopsis": synopsis.model_dump(mode="json"),
            "story_contract": story_contract,
            "world_snapshot": world_snapshot,
            "constraint_block": constraint_block,
            "generation_instruction": generation_instruction,
            "target_chapters": target_chapters,
        }

        prompt = (
            "你是一位小说分卷规划专家。请根据以下大纲数据,"
            "只生成卷纲骨架 VolumePlanBlueprint，返回严格符合 VolumePlanBlueprint Schema 的 JSON。\n"
            "不要返回 VolumePlan，不要返回 beats，不要展开章节细节。\n"
            "## 结构要求\n"
            "1. 只输出卷级字段和 chapters 骨架，每章只保留 chapter_number/title/summary。\n"
            "2. 每章给出有意义的标题和摘要，不用『第X章』这类占位符。\n"
            "3. 章节之间保持因果连贯，平均每 2-3 章安排 1 个冲突点/悬念点。\n"
            "4. 本卷整体规划出 1 个卷级高潮和 1 个卷末钩子，但只体现在 chapter summary 的推进里。\n"
            "5. entity_highlights 与 relationship_highlights 只保留最关键的 3-5 条，能省则省。\n"
            "6. 估算字数合理。\n\n"
            "## 叙事约束\n"
            "1. 必须遵守 ActiveConstraintContext 的当前阶段边界。\n"
            "1.1 必须遵守“可执行设定约束”；hard/sequence 约束中的节点必须在章节摘要中按顺序体现。\n"
            "2. 高阶敌人、终局真相、后续世界/体系若未在本卷允许范围内，只能写成伏笔、残痕、传闻、代理人或异常现象。\n"
            "3. 缺少设定依据时不得硬编关键事实，应保守降级为待确认线索。\n"
            "4. 不得重新引入用户已删除或未批准的旧设定。\n\n"
            "5. 境界、功法层级、势力层级等专有层级名称必须逐字来自总纲、当前设定或 ActiveConstraintContext；"
            "不得按通用修仙套路自造如“某某三层/七层”等未提供层级。\n\n"
            "## 输出规模限制\n"
            f"{scale_rule}"
            "2. 这是单卷可执行规划,不要试图一次覆盖整部小说的全部章节。\n"
            "3. 每章 summary 控制在 25-50 字，优先写主线推进与章末悬念。\n"
            "4. 不要返回 beats、target_word_count、target_mood、foreshadowings 字段。\n"
            "5. 优先保证 JSON 完整，不要输出解释，不要输出 Markdown。\n\n"
            f"大纲数据:\n{synopsis_prompt_data}\n\n"
            f"{volume_contract_block}\n\n"
            f"{story_contract_block}\n\n"
            f"{constraint_block}\n\n"
            f"当前卷号:{volume_number}"
            f"{world_block}"
            f"{instruction_block}"
        )
        await self._release_connection_before_external_call()
        blueprint = await self._call_volume_blueprint_model(
            prompt,
            novel_id=novel_id,
            orchestration_config=orchestration_config,
            volume_context=volume_context,
        )
        if target_chapters and len(blueprint.chapters) != target_chapters:
            log_service.add_log(
                novel_id,
                "VolumePlannerAgent",
                f"卷纲章节数不符合用户要求: 返回 {len(blueprint.chapters)} 章，要求 {target_chapters} 章，开始强约束重试",
                level="warning",
                event="agent.progress",
                status="failed",
                node="volume_plan_scale",
                task="generate_volume_plan",
                metadata={"returned_chapters": len(blueprint.chapters), "target_chapters": target_chapters},
            )
            retry_prompt = (
                f"{prompt}\n\n"
                "### 纠错要求\n"
                f"上一次返回了 {len(blueprint.chapters)} 章，不符合用户要求。"
                f"这一次必须生成恰好 {target_chapters} 个 chapters 骨架，"
                f"chapter_number 从 1 连续到 {target_chapters}，不得少于或多于。"
            )
            await self._release_connection_before_external_call()
            blueprint = await self._call_volume_blueprint_model(
                retry_prompt,
                novel_id=novel_id,
                orchestration_config=orchestration_config,
                volume_context=volume_context,
            )
            if len(blueprint.chapters) != target_chapters:
                raise ValueError(
                    f"generate_volume_plan returned {len(blueprint.chapters)} chapters, expected {target_chapters}"
                )
        blueprint = await self._repair_blueprint_constraint_violations(
            blueprint=blueprint,
            base_prompt=prompt,
            constraint_context=constraint_context,
            novel_id=novel_id,
            target_chapters=target_chapters,
        )
        blueprint = await self._repair_blueprint_semantic_conflicts(
            blueprint=blueprint,
            base_prompt=prompt,
            constraint_context=constraint_context,
            novel_id=novel_id,
            target_chapters=target_chapters,
        )
        detailed_chapters = await self._expand_volume_plan_batches(
            blueprint,
            synopsis,
            world_snapshot=world_snapshot,
            constraint_block=constraint_block,
            novel_id=novel_id,
        )
        result = VolumePlan(
            volume_id=blueprint.volume_id,
            volume_number=blueprint.volume_number,
            title=blueprint.title,
            summary=blueprint.summary,
            total_chapters=len(detailed_chapters),
            estimated_total_words=blueprint.estimated_total_words,
            chapters=detailed_chapters,
            entity_highlights=blueprint.entity_highlights,
            relationship_highlights=blueprint.relationship_highlights,
        )
        log_agent_detail(
            novel_id,
            "VolumePlannerAgent",
            f"卷纲生成完成：{result.title}",
            node="volume_generate_result",
            task="generate_volume_plan",
            metadata={
                "volume_id": result.volume_id,
                "title": result.title,
                "chapter_count": len(result.chapters),
                "chapter_batch_count": math.ceil(len(result.chapters) / self.CHAPTER_BATCH_SIZE) if result.chapters else 0,
                "chapters": named_items([chapter.model_dump() for chapter in result.chapters[:12]]),
            },
        )
        return result

    def _build_synopsis_catalog(self, synopsis: SynopsisData) -> str:
        return json.dumps(
            {
                "title": synopsis.title,
                "logline": synopsis.logline,
                "estimated_volumes": synopsis.estimated_volumes,
                "estimated_total_chapters": synopsis.estimated_total_chapters,
                "estimated_total_words": synopsis.estimated_total_words,
                "volume_outlines": [
                    {
                        "volume_number": item.volume_number,
                        "title": item.title,
                        "main_goal": item.main_goal,
                        "target_chapter_range": item.target_chapter_range,
                    }
                    for item in (synopsis.volume_outlines or [])
                ],
                "tool_hint": "可按需调用只读上下文工具获取完整总纲、约束和世界状态。",
            },
            ensure_ascii=False,
        )

    def _build_volume_contract_catalog(self, synopsis: SynopsisData, volume_number: int) -> str:
        outlines = list(synopsis.volume_outlines or [])
        current = next((item for item in outlines if item.volume_number == volume_number), None)
        previous = next((item for item in outlines if item.volume_number == volume_number - 1), None)
        next_item = next((item for item in outlines if item.volume_number == volume_number + 1), None)
        return (
            "### 本卷总纲契约(目录模式，详情可调用 get_volume_planner_context)\n"
            f"当前卷: {current.title if current else f'第{volume_number}卷'}\n"
            f"当前卷目标: {current.main_goal if current else ''}\n"
            f"目标章节范围: {current.target_chapter_range if current else ''}\n"
            f"上一卷: {previous.title if previous else '无'}\n"
            f"下一卷: {next_item.title if next_item else '无'}"
        )

    async def _call_volume_blueprint_model(
        self,
        prompt: str,
        *,
        novel_id: str,
        orchestration_config: OrchestratedTaskConfig | None,
        volume_context: dict[str, Any],
    ) -> VolumePlanBlueprint:
        if orchestration_config is None:
            return await call_and_parse_model(
                "VolumePlannerAgent",
                "generate_volume_plan",
                prompt,
                VolumePlanBlueprint,
                max_retries=3,
                novel_id=novel_id,
            )
        return await orchestrated_call_and_parse_model(
            "VolumePlannerAgent",
            "generate_volume_plan",
            prompt,
            VolumePlanBlueprint,
            tools=self._build_volume_planner_tools(
                novel_id=novel_id,
                volume_context=volume_context,
                orchestration_config=orchestration_config,
            ),
            task_config=orchestration_config,
            novel_id=novel_id,
            max_retries=3,
        )

    def _build_volume_planner_tools(
        self,
        *,
        novel_id: str,
        volume_context: dict[str, Any],
        orchestration_config: OrchestratedTaskConfig,
    ) -> list[LLMToolSpec]:
        tools: list[LLMToolSpec] = []
        if "get_volume_planner_context" in orchestration_config.tool_allowlist:
            async def get_volume_planner_context(args: dict[str, Any]) -> dict[str, Any]:
                requested_novel_id = str(args.get("novel_id") or novel_id)
                if requested_novel_id != novel_id:
                    return {"error": "novel_id does not match current volume planning task"}
                return volume_context

            tools.append(LLMToolSpec(
                name="get_volume_planner_context",
                description="Read the full synopsis, active constraints, world snapshot, and volume planning instruction.",
                input_schema={
                    "type": "object",
                    "properties": {"novel_id": {"type": "string"}},
                    "required": ["novel_id"],
                },
                handler=get_volume_planner_context,
                read_only=True,
                timeout_seconds=orchestration_config.tool_timeout_seconds or 5.0,
                max_return_chars=orchestration_config.max_tool_result_chars,
            ))

        from novel_dev.mcp_server.server import internal_mcp_registry

        tools.extend(build_mcp_context_tools(
            internal_mcp_registry,
            allowlist=orchestration_config.tool_allowlist,
            max_return_chars=orchestration_config.max_tool_result_chars,
            timeout_seconds=orchestration_config.tool_timeout_seconds or 5.0,
        ))
        return tools

    async def _repair_blueprint_constraint_violations(
        self,
        *,
        blueprint: VolumePlanBlueprint,
        base_prompt: str,
        constraint_context: ActiveConstraintContext,
        novel_id: str,
        target_chapters: Optional[int],
    ) -> VolumePlanBlueprint:
        violations = self._validate_blueprint_constraints(blueprint, constraint_context)
        if not violations:
            log_service.add_log(
                novel_id,
                "VolumePlannerAgent",
                "卷纲设定约束校验通过",
                event="agent.progress",
                status="succeeded",
                node="volume_constraint_validation",
                task="validate_volume_plan_constraints",
                metadata={
                    "volume_number": blueprint.volume_number,
                    "checked_constraints": len(constraint_context.executable_constraints),
                },
            )
            return blueprint

        log_service.add_log(
            novel_id,
            "VolumePlannerAgent",
            "卷纲设定约束校验失败，开始强约束修正: " + "；".join(violations[:6]),
            level="warning",
            event="agent.progress",
            status="failed",
            node="volume_constraint_validation",
            task="validate_volume_plan_constraints",
            metadata={
                "volume_number": blueprint.volume_number,
                "violations": violations,
                "checked_constraints": len(constraint_context.executable_constraints),
            },
        )
        chapter_rule = (
            f"必须仍然生成恰好 {target_chapters} 个 chapters。"
            if target_chapters
            else "必须保持 total_chapters 与 chapters 数组规模符合原输出规模要求。"
        )
        retry_prompt = (
            f"{base_prompt}\n\n"
            "### 设定约束校验失败，必须重写卷纲骨架\n"
            f"{chapter_rule}\n"
            "绝对不得改变章节数量；如果返回章节数不符，系统会视为修复失败并做强制收缩。\n"
            "以下 hard 约束违反了设定，必须修正：\n"
            + "\n".join(f"- {item}" for item in violations)
            + "\n修正要求：缺失的设定节点必须落实到具体章节 title 或 summary 中，顺序必须符合设定链；"
            "不要只在卷摘要里罗列。仍然只返回 VolumePlanBlueprint JSON。"
        )
        await self._release_connection_before_external_call()
        repaired = await call_and_parse_model(
            "VolumePlannerAgent", "generate_volume_plan", retry_prompt, VolumePlanBlueprint, max_retries=3, novel_id=novel_id
        )
        repaired = self._coerce_blueprint_to_target_chapters(
            repaired,
            target_chapters=target_chapters,
            novel_id=novel_id,
            repair_stage="generate_volume_plan constraint repair",
        )
        remaining = self._validate_blueprint_constraints(repaired, constraint_context)
        if remaining:
            raise ValueError("generate_volume_plan violates setting constraints after repair: " + "；".join(remaining[:8]))
        log_service.add_log(
            novel_id,
            "VolumePlannerAgent",
            "卷纲设定约束修正完成",
            event="agent.progress",
            status="succeeded",
            node="volume_constraint_validation",
            task="validate_volume_plan_constraints",
            metadata={"volume_number": repaired.volume_number},
        )
        return repaired

    def _validate_blueprint_constraints(
        self,
        blueprint: VolumePlanBlueprint,
        constraint_context: ActiveConstraintContext,
    ) -> list[str]:
        violations: list[str] = []
        for constraint in constraint_context.executable_constraints:
            if constraint.priority != "hard" or constraint.constraint_type != "sequence" or len(constraint.terms) < 2:
                continue
            positions: list[int] = []
            missing: list[str] = []
            for term in constraint.terms:
                position = self._find_constraint_term_position(term, blueprint)
                if position < 0:
                    missing.append(term)
                else:
                    positions.append(position)
            if missing:
                violations.append(f"{constraint.title} 缺失必经节点: {', '.join(missing)}")
                continue
            if positions != sorted(positions):
                violations.append(f"{constraint.title} 必经节点顺序错误: {' -> '.join(constraint.terms)}")
        return violations

    def _find_constraint_term_position(self, term: str, blueprint: VolumePlanBlueprint) -> int:
        candidates = [term, *self.constraint_builder._term_aliases(term)]
        for index, chapter in enumerate(blueprint.chapters):
            chapter_text = f"{chapter.title}\n{chapter.summary}"
            if any(candidate and candidate in chapter_text for candidate in candidates):
                return index
        return -1

    def _coerce_blueprint_to_target_chapters(
        self,
        blueprint: VolumePlanBlueprint,
        *,
        target_chapters: Optional[int],
        novel_id: str,
        repair_stage: str,
    ) -> VolumePlanBlueprint:
        if not target_chapters or len(blueprint.chapters) == target_chapters:
            return blueprint
        if len(blueprint.chapters) < target_chapters:
            raise ValueError(
                f"{repair_stage} returned {len(blueprint.chapters)} chapters, expected at least {target_chapters}"
            )

        total = len(blueprint.chapters)
        merged_chapters: list[dict[str, Any]] = []
        for index in range(target_chapters):
            start = index * total // target_chapters
            end = (index + 1) * total // target_chapters
            group = blueprint.chapters[start:end]
            if not group:
                raise ValueError(f"{repair_stage} produced an empty chapter slice during chapter-count coercion")
            merged_chapters.append(
                self._merge_blueprint_chapter_group(
                    blueprint.volume_number,
                    chapter_number=index + 1,
                    chapters=group,
                )
            )

        payload = blueprint.model_dump()
        payload["total_chapters"] = target_chapters
        payload["chapters"] = merged_chapters
        coerced = VolumePlanBlueprint.model_validate(payload)
        log_service.add_log(
            novel_id,
            "VolumePlannerAgent",
            f"{repair_stage} 返回 {total} 章，已自动收缩为 {target_chapters} 章以保持上游契约",
            level="warning",
            event="agent.progress",
            status="degraded",
            node="volume_plan_scale",
            task="repair_volume_plan_scale",
            metadata={
                "repair_stage": repair_stage,
                "returned_chapters": total,
                "target_chapters": target_chapters,
            },
        )
        return coerced

    def _merge_blueprint_chapter_group(
        self,
        volume_number: int,
        *,
        chapter_number: int,
        chapters: list[VolumeChapterSkeleton],
    ) -> dict[str, Any]:
        first = chapters[0]
        last = chapters[-1]
        title = first.title
        if len(chapters) > 1 and last.title and last.title != first.title:
            title = f"{first.title}至{last.title}"
        summary_parts = [chapter.summary.strip().rstrip("。！？!?；;") for chapter in chapters if chapter.summary.strip()]
        summary = "；".join(summary_parts) if summary_parts else first.summary
        if summary and summary[-1] not in "。！？!?":
            summary += "。"
        return {
            "chapter_number": chapter_number,
            "chapter_id": VolumeChapterSkeleton.build_chapter_id(volume_number, chapter_number),
            "title": title,
            "summary": summary,
        }

    async def _repair_blueprint_semantic_conflicts(
        self,
        *,
        blueprint: VolumePlanBlueprint,
        base_prompt: str,
        constraint_context: ActiveConstraintContext,
        novel_id: str,
        target_chapters: Optional[int],
    ) -> VolumePlanBlueprint:
        judgement = await self._judge_blueprint_semantic_conflicts(
            blueprint=blueprint,
            constraint_context=constraint_context,
            novel_id=novel_id,
        )
        if judgement.passed or not judgement.hard_conflicts:
            log_service.add_log(
                novel_id,
                "VolumePlannerAgent",
                "卷纲语义设定裁判通过" + (f"，软警告 {len(judgement.soft_warnings)} 条" if judgement.soft_warnings else ""),
                event="agent.progress",
                status="succeeded",
                node="volume_semantic_judge",
                task="judge_volume_plan_semantics",
                metadata=judgement.model_dump(),
            )
            return blueprint

        log_service.add_log(
            novel_id,
            "VolumePlannerAgent",
            "卷纲语义设定裁判失败，开始修正: " + "；".join(judgement.hard_conflicts[:6]),
            level="warning",
            event="agent.progress",
            status="failed",
            node="volume_semantic_judge",
            task="judge_volume_plan_semantics",
            metadata=judgement.model_dump(),
        )
        chapter_rule = (
            f"必须仍然生成恰好 {target_chapters} 个 chapters。"
            if target_chapters
            else "必须保持 total_chapters 与 chapters 数组规模符合原输出规模要求。"
        )
        retry_prompt = (
            f"{base_prompt}\n\n"
            "### LLM 语义设定裁判失败，必须重写卷纲骨架\n"
            f"{chapter_rule}\n"
            "绝对不得改变章节数量；如果返回章节数不符，系统会视为修复失败并做强制收缩。\n"
            "以下是必须修复的 hard 设定冲突：\n"
            + "\n".join(f"- {item}" for item in judgement.hard_conflicts)
            + "\n以下是修复建议：\n"
            + "\n".join(f"- {item}" for item in judgement.repair_suggestions[:8])
            + "\n修正要求：不得与设定事实、阶段边界、伏笔限制、人物/势力关系冲突；"
            "如果信息不足，降级为传闻、残痕、误判或待确认线索。"
            "entity_highlights 与 relationship_highlights 也必须同步修正，"
            "不能保留旧的高确定性表述；必要时直接删除冲突条目。"
            "卷摘要与章节摘要也必须同步修正，避免正文线索已降级但摘要仍保留已证实口吻。"
            "仍然只返回 VolumePlanBlueprint JSON。"
        )
        await self._release_connection_before_external_call()
        repaired = await call_and_parse_model(
            "VolumePlannerAgent", "generate_volume_plan", retry_prompt, VolumePlanBlueprint, max_retries=3, novel_id=novel_id
        )
        repaired = self._coerce_blueprint_to_target_chapters(
            repaired,
            target_chapters=target_chapters,
            novel_id=novel_id,
            repair_stage="generate_volume_plan semantic repair",
        )
        remaining_hard = self._validate_blueprint_constraints(repaired, constraint_context)
        if remaining_hard:
            raise ValueError("generate_volume_plan violates setting constraints after semantic repair: " + "；".join(remaining_hard[:8]))
        second_judgement = await self._judge_blueprint_semantic_conflicts(
            blueprint=repaired,
            constraint_context=constraint_context,
            novel_id=novel_id,
        )
        if not second_judgement.passed and second_judgement.hard_conflicts:
            raise ValueError(
                "generate_volume_plan semantic conflicts remain after repair: "
                + "；".join(second_judgement.hard_conflicts[:8])
            )
        log_service.add_log(
            novel_id,
            "VolumePlannerAgent",
            "卷纲语义设定修正完成",
            event="agent.progress",
            status="succeeded",
            node="volume_semantic_judge",
            task="judge_volume_plan_semantics",
            metadata=second_judgement.model_dump(),
        )
        return repaired

    async def _judge_blueprint_semantic_conflicts(
        self,
        *,
        blueprint: VolumePlanBlueprint,
        constraint_context: ActiveConstraintContext,
        novel_id: str,
    ) -> VolumePlanSemanticJudgement:
        judge_constraints = [
            item
            for item in constraint_context.executable_constraints
            if item.constraint_type == "fact"
        ]
        if not judge_constraints:
            return VolumePlanSemanticJudgement(passed=True, confidence=1.0)

        constraints = "\n".join(
            f"- {item.to_prompt_line()}" for item in judge_constraints[:16]
        )
        prompt = (
            "你是小说设定一致性裁判。请判断卷纲骨架是否语义上违反设定约束。\n"
            "只返回严格符合 VolumePlanSemanticJudgement Schema 的 JSON。\n\n"
            "## 判断重点\n"
            "1. 事实冲突：人物身份、势力关系、法宝归属、地点归属是否写反或无依据改写。\n"
            "2. 阶段越界：当前卷只能伏笔的高阶敌人/世界/能力，是否被写成正面冲突或已解决事件。\n"
            "3. 能力不匹配：主角当前阶段是否完成设定上不可能完成的事。\n"
            "4. 关系错乱：关系变化是否缺少过程，是否与既有设定直接矛盾。\n"
            "5. 旧设定复活：是否重新引入已删除或未批准设定。\n\n"
            "## 裁判标准\n"
            "- 如果只是传闻、梦兆、残影、误判、远景伏笔，且没有造成实际正面交锋或结论，可以通过或给 soft_warnings。\n"
            "- 只有明确违反 hard 设定、越级正面展开、事实写反、能力跳跃时，才放入 hard_conflicts。\n"
            "- repair_suggestions 必须具体到如何降级、替换或补过程。\n\n"
            f"### 可执行设定约束\n{constraints}\n\n"
            f"### 当前卷纲骨架\n{blueprint.model_dump_json()[:12000]}"
        )
        await self._release_connection_before_external_call()
        return await call_and_parse_model(
            "VolumePlannerAgent",
            "judge_volume_plan_semantics",
            prompt,
            VolumePlanSemanticJudgement,
            max_retries=2,
            novel_id=novel_id,
        )

    async def _expand_volume_plan_batches(
        self,
        blueprint: VolumePlanBlueprint,
        synopsis: SynopsisData,
        *,
        world_snapshot: Optional[dict],
        novel_id: str,
        constraint_block: str = "",
    ) -> list[VolumeBeat]:
        chapters: list[VolumeBeat] = []
        skeletons = blueprint.chapters
        flow_control = FlowControlService(self.session)
        for start in range(0, len(skeletons), self.CHAPTER_BATCH_SIZE):
            await flow_control.raise_if_cancelled(novel_id)
            batch = skeletons[start:start + self.CHAPTER_BATCH_SIZE]
            start_no = batch[0].chapter_number
            end_no = batch[-1].chapter_number
            log_service.add_log(novel_id, "VolumePlannerAgent", f"扩展章节细节: 第 {start_no}-{end_no} 章")
            prompt = self._build_volume_plan_batch_prompt(
                blueprint,
                synopsis,
                batch,
                world_snapshot=world_snapshot,
                constraint_block=constraint_block,
            )
            await self._release_connection_before_external_call()
            batch_result = await call_and_parse_model(
                "VolumePlannerAgent",
                "expand_volume_plan_batch",
                prompt,
                list[VolumeBeatExpansion],
                max_retries=3,
                novel_id=novel_id,
            )
            completed_batch = self._complete_expanded_batch(batch_result, batch)
            for chapter in completed_batch:
                chapters.append(await self._repair_unwritable_expanded_chapter(
                    chapter,
                    blueprint=blueprint,
                    synopsis=synopsis,
                    constraint_block=constraint_block,
                    novel_id=novel_id,
                ))
            await flow_control.raise_if_cancelled(novel_id)
        return chapters

    async def _repair_unwritable_expanded_chapter(
        self,
        chapter: VolumeBeat,
        *,
        blueprint: VolumePlanBlueprint,
        synopsis: SynopsisData,
        constraint_block: str,
        novel_id: str,
    ) -> VolumeBeat:
        report = StoryQualityService.evaluate_chapter_writability(chapter)
        if report.passed:
            return chapter

        deterministic = self._deterministic_repair_unwritable_chapter(chapter, report)
        deterministic_report = StoryQualityService.evaluate_chapter_writability(deterministic)
        if deterministic_report.passed:
            log_agent_detail(
                novel_id,
                "VolumePlannerAgent",
                f"章节可写性确定性补强完成：第 {chapter.chapter_number} 章",
                node="volume_writability_repair",
                task="repair_chapter_writability",
                status="succeeded",
                metadata={
                    "chapter_number": chapter.chapter_number,
                    "before": report.model_dump(),
                    "after": deterministic_report.model_dump(),
                    "mode": "deterministic",
                },
            )
            return deterministic

        prompt = (
            "你是小说章节计划修复器。请只修复当前章节不可写的 beats，返回 VolumeChapterPatch JSON。\n"
            "硬性要求:\n"
            "1. 不新增、删除、重排章节；chapter_number 必须保持不变。\n"
            "2. 不改变章节 title、主线事实、已给定实体和伏笔方向。\n"
            "3. beats 必须完整返回 2-3 个，每个 summary 必须包含：角色目标、具体阻力、当场选择、失败代价、停点。\n"
            "4. 最后一个 beat 必须有章末钩子；不要扩写正文。\n\n"
            f"### 可写性问题\n{json.dumps(report.model_dump(), ensure_ascii=False)}\n\n"
            f"### 当前章节\n{chapter.model_dump_json()}\n\n"
            f"### 整卷骨架\n{blueprint.model_dump_json()[:6000]}\n\n"
            f"### 总纲\n{synopsis.model_dump_json()[:6000]}\n\n"
            f"{constraint_block[:4000]}"
        )
        try:
            await self._release_connection_before_external_call()
            patch = await call_and_parse_model(
                "VolumePlannerAgent",
                "repair_chapter_writability",
                prompt,
                VolumeChapterPatch,
                max_retries=2,
                novel_id=novel_id,
            )
            repaired = self._apply_volume_plan_patch(
                VolumePlan(
                    volume_id=blueprint.volume_id,
                    volume_number=blueprint.volume_number,
                    title=blueprint.title,
                    summary=blueprint.summary,
                    total_chapters=1,
                    estimated_total_words=chapter.target_word_count,
                    chapters=[chapter],
                ),
                VolumePlanPatch(chapter_patches=[patch]),
            ).chapters[0]
        except Exception as exc:
            log_service.add_log(
                novel_id,
                "VolumePlannerAgent",
                f"章节可写性修复失败，使用确定性补强: {exc}",
                level="warning",
            )
            repaired = deterministic

        repaired_report = StoryQualityService.evaluate_chapter_writability(repaired)
        if not repaired_report.passed:
            repaired = self._deterministic_repair_unwritable_chapter(repaired, repaired_report)
        log_agent_detail(
            novel_id,
            "VolumePlannerAgent",
            f"章节可写性修复完成：第 {chapter.chapter_number} 章",
            node="volume_writability_repair",
            task="repair_chapter_writability",
            status="succeeded",
            metadata={
                "chapter_number": chapter.chapter_number,
                "before": report.model_dump(),
                "after": StoryQualityService.evaluate_chapter_writability(repaired).model_dump(),
            },
        )
        return repaired

    def _deterministic_repair_unwritable_chapter(
        self,
        chapter: VolumeBeat,
        report,
    ) -> VolumeBeat:
        payload = chapter.model_dump()
        beats = []
        weak_indexes = set(report.weak_beats or [])
        for index, beat in enumerate(chapter.beats):
            beat_payload = beat.model_dump()
            if index in weak_indexes:
                summary = beat.summary.strip().rstrip("。！？!?")
                actor = (beat.key_entities or chapter.key_entities or ["主角"])[0]
                beat_payload["summary"] = (
                    f"{summary}；{actor}必须在继续追查与保全自身之间做出选择，"
                    "阻力当场升级，失败代价是失去关键线索并暴露处境，结尾留下新的危险信号。"
                )
            beats.append(beat_payload)
        payload["beats"] = beats
        return VolumeBeat.model_validate(payload)

    def _complete_expanded_batch(
        self,
        expansions: list[VolumeBeatExpansion],
        skeletons: list[VolumeChapterSkeleton],
    ) -> list[VolumeBeat]:
        if len(expansions) != len(skeletons):
            raise ValueError(f"expand_volume_plan_batch returned {len(expansions)} chapters, expected {len(skeletons)}")

        expected_numbers = [chapter.chapter_number for chapter in skeletons]
        resolved_numbers = [
            expansion.chapter_number if expansion.chapter_number is not None else skeletons[index].chapter_number
            for index, expansion in enumerate(expansions)
        ]
        if len(set(resolved_numbers)) != len(resolved_numbers):
            raise ValueError(f"expand_volume_plan_batch returned duplicate chapter_number values: {resolved_numbers}")
        if set(resolved_numbers) != set(expected_numbers):
            missing_numbers = sorted(set(expected_numbers) - set(resolved_numbers))
            unexpected_numbers = sorted(set(resolved_numbers) - set(expected_numbers))
            raise ValueError(
                f"expand_volume_plan_batch returned chapter_number mismatch: "
                f"missing {missing_numbers}, unexpected {unexpected_numbers}, expected {expected_numbers}"
            )

        skeleton_by_number = {chapter.chapter_number: chapter for chapter in skeletons}
        completed_by_number: dict[int, VolumeBeat] = {}
        for index, expansion in enumerate(expansions):
            chapter_number = resolved_numbers[index]
            skeleton = skeleton_by_number[chapter_number]
            payload = expansion.model_dump()
            payload["chapter_number"] = chapter_number
            payload["chapter_id"] = payload.get("chapter_id") or skeleton.chapter_id
            payload["title"] = payload.get("title") or skeleton.title
            payload["summary"] = payload.get("summary") or skeleton.summary
            completed_by_number[chapter_number] = VolumeBeat.model_validate(payload)
        return [completed_by_number[number] for number in expected_numbers]

    def _build_volume_plan_batch_prompt(
        self,
        blueprint: VolumePlanBlueprint,
        synopsis: SynopsisData,
        batch: list[VolumeChapterSkeleton],
        *,
        world_snapshot: Optional[dict],
        constraint_block: str = "",
    ) -> str:
        batch_payload = [
            {
                "chapter_number": chapter.chapter_number,
                "chapter_id": VolumeChapterSkeleton.build_chapter_id(blueprint.volume_number, chapter.chapter_number),
                "title": chapter.title,
                "summary": chapter.summary,
            }
            for chapter in batch
        ]
        world_block = ""
        if world_snapshot:
            world_block = (
                "\n\n### 前卷世界状态快照\n"
                f"活跃人物:\n{world_snapshot.get('entities', '无')}\n"
                f"未回收伏笔:\n{world_snapshot.get('foreshadowings', '无')}\n"
                f"已推进时间线:\n{world_snapshot.get('timeline', '无')}\n"
            )
        return (
            "你是一位小说分卷规划专家。请根据给定的卷纲骨架，补全一批章节的详细 VolumeBeatExpansion 数组。"
            "只返回合法 JSON 数组，每一项补全章节细节即可。\n"
            "要求:\n"
            "1. 只扩展本批章节，不要返回其他章节。\n"
            "2. 每章保留 chapter_number/title/summary 主线含义一致。\n"
            f"3. chapter_id 必须逐项使用本批待扩展章节提供的 chapter_id，格式为 vol_{blueprint.volume_number}_ch_<chapter_number>。\n"
            "4. target_word_count 给出合理整数；target_mood 用简短英文或中文短语。\n"
            "5. 每章 2-3 个 beats，每个 beat 只写 summary 和 target_mood，必要时补 key_entities / foreshadowings_to_embed。\n"
            "6. 章节之间必须形成因果推进，最后一个 beat 要有章末钩子。\n"
            f"7. 本批最多 {self.CHAPTER_BATCH_SIZE} 章，优先保证 JSON 完整，不要扩写成长段正文。\n"
            "8. 必须遵守 ActiveConstraintContext，不要把只能伏笔的高阶内容写成本批正面冲突。\n"
            "9. 境界、功法层级、势力层级等专有层级名称必须逐字来自整卷骨架、整体大纲或 ActiveConstraintContext；"
            "不得自行补写不存在的层级编号或通用修仙境界。\n"
            "10. 不要输出 Markdown，不要解释。\n\n"
            f"### 整卷骨架\n{blueprint.model_dump_json()[:8000]}\n\n"
            f"### 整体大纲\n{synopsis.model_dump_json()[:8000]}\n\n"
            f"{constraint_block}\n\n"
            f"### 本批待扩展章节\n{json.dumps(batch_payload, ensure_ascii=False)}"
            f"{world_block}"
        )

    async def _load_constraint_source_text(self, novel_id: str) -> str:
        if not novel_id:
            return ""
        try:
            docs = []
            for doc_type in self.CONSTRAINT_SOURCE_DOC_TYPES:
                docs.extend(await self.doc_repo.get_current_by_type(novel_id, doc_type))
            if docs:
                log_service.add_log(
                    novel_id,
                    "VolumePlannerAgent",
                    "卷纲叙事约束来源: "
                    + self._join_log_names([f"{doc.doc_type}/{doc.title} v{doc.version}" for doc in docs]),
                    event="agent.progress",
                    status="succeeded",
                    node="volume_context_sources",
                    task="load_constraint_source_text",
                    metadata={
                        "documents": [
                            {
                                "id": doc.id,
                                "type": doc.doc_type,
                                "title": doc.title,
                                "version": doc.version,
                            }
                            for doc in docs
                        ],
                        "document_count": len(docs),
                    },
                )
            return "\n\n".join(f"[{doc.doc_type}] {doc.title}\n{doc.content}" for doc in docs)[:10000]
        except Exception as exc:
            log_service.add_log(novel_id, "VolumePlannerAgent", f"叙事约束来源加载失败: {exc}", level="warning")
            return ""

    @staticmethod
    def _join_log_names(values: list[str], limit: int = 6) -> str:
        cleaned = [str(value).strip() for value in values if str(value or "").strip()]
        if not cleaned:
            return "无"
        suffix = f" 等{len(cleaned)}项" if len(cleaned) > limit else ""
        return "、".join(cleaned[:limit]) + suffix

    @staticmethod
    def _snapshot_preview(value, limit: int = 120) -> str:
        text = str(value or "无").strip()
        return text[:limit] if text else "无"

    async def _load_world_snapshot(self, novel_id: str) -> dict:
        """为跨卷延续加载世界状态快照:活跃实体、未回收伏笔、近期时间线。"""
        try:
            entities = await self.entity_repo.list_by_novel(novel_id)
            entity_lines = []
            for e in entities[:30]:
                latest = await self.version_repo.get_latest(e.id)
                state_str = str(latest.state) if latest else ""
                entity_lines.append(f"- [{e.type}] {e.name}: {state_str[:200]}")
            entities_text = "\n".join(entity_lines) if entity_lines else "无"

            fs_list = await self.foreshadowing_repo.list_active(novel_id=novel_id)
            fs_lines = [f"- {fs.content}" for fs in fs_list[:30]]
            fs_text = "\n".join(fs_lines) if fs_lines else "无"

            tick = await self.timeline_repo.get_current_tick() or 0
            events = await self.timeline_repo.get_around_tick(tick, radius=5, novel_id=novel_id)
            tl_lines = [f"- tick={e.tick}: {e.narrative}" for e in events[:15]]
            tl_text = "\n".join(tl_lines) if tl_lines else "无"

            return {"entities": entities_text, "foreshadowings": fs_text, "timeline": tl_text}
        except Exception as exc:
            log_service.add_log(novel_id, "VolumePlannerAgent", f"世界快照加载失败: {exc}", level="warning")
            return {}

    async def _generate_score(
        self,
        plan: VolumePlan,
        novel_id: str = "",
        target_chapters: Optional[int] = None,
    ) -> VolumeScoreResult:
        log_service.add_log(novel_id, "VolumePlannerAgent", "开始评分卷纲")
        scale_contract = ""
        if target_chapters == 1:
            scale_contract = (
                "## 明确规模契约\n"
                "本次上游明确要求 target_chapters=1。评审必须按『单章验收规划』评分，"
                "不得因为只有 1 章而要求扩展为多章或长卷。\n"
                "- hook_distribution: 评价单章内部是否包含清晰的小高潮、悬念推进和章末钩子；"
                "不要套用『每 2-3 章一个小高潮』。\n"
                "- foreshadowing_management: 允许单章内埋设并部分回收，或留下明确可承接线索；"
                "不要因为缺少跨章节呼应而直接判低分。\n"
                "- page_turning: 评价读者是否想继续读下一阶段/下一章，而不是是否存在多个章节。\n"
                "- overall: 重点判断这 1 章是否可作为当前 scope 的最小可用章节计划。\n\n"
            )
        elif target_chapters:
            scale_contract = (
                "## 明确规模契约\n"
                f"本次上游明确要求 target_chapters={target_chapters}。评审必须在该章节数约束内判断质量，"
                "不得以扩展章节数作为主要修改建议。\n\n"
            )
        prompt = (
            "你是一个小说分卷规划评审专家。请根据以下 VolumePlan JSON 进行多维度评分，"
            "返回严格符合 VolumeScoreResult Schema 的 JSON。\n\n"
            f"{scale_contract}"
            "## Rubric\n"
            "- outline_fidelity >=75: 与 synopsis 主线、卷目标、章节推进一致，不偏题。\n"
            "- character_plot_alignment >=75: 角色目标、动机、行动与章节冲突推进一致。\n"
            "- hook_distribution >=75: 平均每 2-3 章有小高潮/悬念点，卷内有卷级高潮。\n"
            "- foreshadowing_management >=75: 埋设与回收有呼应，不是孤立点缀。\n"
            "- chapter_hooks >=75: 多数章节结尾有明确钩子。\n"
            "- page_turning >=70: 读者会自然想继续读下一章。\n"
            "## 输出\n"
            "严格 JSON，summary_feedback 控制在 300 字内，指出最需要改的 2-3 点。"
            f"\n\n### VolumePlan\n{self._build_score_plan_snapshot(plan)}"
        )
        await self._release_connection_before_external_call()
        result = await call_and_parse_model(
            "VolumePlannerAgent", "score_volume_plan", prompt, VolumeScoreResult, max_retries=3, novel_id=novel_id
        )
        log_service.add_log(novel_id, "VolumePlannerAgent", f"评分完成: overall={result.overall}")
        return result

    async def _revise_volume_plan(self, plan: VolumePlan, feedback: str, plan_context: str = "", novel_id: str = "") -> VolumePlan:
        log_service.add_log(novel_id, "VolumePlannerAgent", "开始修订卷纲")
        prompt = (
            "你是一个小说分卷规划专家。请根据以下 VolumePlan、原始规划上下文与评审反馈进行局部修正，"
            "返回严格符合 VolumePlanPatch Schema 的 JSON。\n\n"
            "要求:\n"
            "1. 只返回需要修改的字段，不要重写整卷 VolumePlan。\n"
            "2. chapter_patches 只包含需要修改的章节，使用 chapter_number 定位。\n"
            "3. 不要新增、删除、重排章节；不要返回 total_chapters、volume_id、volume_number。\n"
            "4. beats 只有在该章节拍确实需要替换时才返回完整新 beats。\n"
            "5. 每个需要重写的 beat 必须显式包含：角色目标、具体阻力、当场选择、失败代价、章末停点。\n"
            "6. 如果评审指出事件过密，必须减少单个 beat 承担的大事件数量，避免一拍塞入多个关键转折。\n"
            "7. 如果评审指出伏笔关联偏弱，必须让新埋设线索直接服务当前冲突或章末钩子，不要孤立悬空。"
            f"\n\n### 当前 VolumePlan\n{plan.model_dump_json()}"
            f"\n\n### 原始规划上下文\n{plan_context}"
            f"\n\n### 反馈\n{feedback}"
        )
        await self._release_connection_before_external_call()
        patch = await call_and_parse_model(
            "VolumePlannerAgent", "revise_volume_plan", prompt, VolumePlanPatch, max_retries=3, novel_id=novel_id
        )
        result = self._apply_volume_plan_patch(plan, patch)
        log_service.add_log(novel_id, "VolumePlannerAgent", "卷纲修订完成")
        return result

    def _apply_volume_plan_patch(self, plan: VolumePlan, patch: VolumePlanPatch) -> VolumePlan:
        payload = plan.model_dump()
        for field in (
            "title",
            "summary",
            "estimated_total_words",
            "entity_highlights",
            "relationship_highlights",
        ):
            value = getattr(patch, field)
            if value is not None:
                payload[field] = value

        chapters_by_number = {
            chapter.get("chapter_number"): chapter
            for chapter in payload.get("chapters", [])
        }
        for chapter_patch in patch.chapter_patches:
            chapter_payload = chapters_by_number.get(chapter_patch.chapter_number)
            if chapter_payload is None:
                log_service.add_log(
                    "",
                    "VolumePlannerAgent",
                    f"忽略不存在的章节补丁: chapter_number={chapter_patch.chapter_number}",
                    level="warning",
                )
                continue
            patch_payload = chapter_patch.model_dump(exclude_none=True)
            patch_payload.pop("chapter_number", None)
            chapter_payload.update(patch_payload)

        payload["total_chapters"] = len(payload.get("chapters", []))
        return VolumePlan.model_validate(payload)

    def _extract_chapter_plan(self, volume_beat: VolumeBeat) -> dict:
        """Extract chapter plan from VolumeBeat without mutating input."""
        chapter_plan = volume_beat.model_dump()
        beats = [b.model_dump() for b in volume_beat.beats]
        if volume_beat.foreshadowings_to_embed and beats:
            if not beats[0].get("foreshadowings_to_embed"):
                beats[0]["foreshadowings_to_embed"] = list(volume_beat.foreshadowings_to_embed)
        chapter_plan["beats"] = beats
        writable = StoryQualityService.evaluate_chapter_writability(volume_beat)
        chapter_plan["writability_status"] = writable.model_dump()
        chapter_plan["writing_cards"] = [
            card.model_dump()
            for card in StoryQualityService.build_writing_cards(ChapterPlan.model_validate(chapter_plan))
        ]
        return chapter_plan
