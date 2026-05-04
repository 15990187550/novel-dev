import json
import re
from typing import Any, Optional

from novel_dev.agents._llm_helpers import call_and_parse_model
from novel_dev.agents.brainstorm_agent import BrainstormAgent
from novel_dev.agents.outline_clarification_agent import (
    MAX_CLARIFICATION_ROUNDS,
    OutlineClarificationAgent,
    OutlineClarificationDecision,
    OutlineClarificationRequest,
)
from novel_dev.agents.volume_planner import VolumePlannerAgent
from novel_dev.db.models import OutlineMessage
from novel_dev.repositories.document_repo import DocumentRepository
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.outline_message_repo import OutlineMessageRepository
from novel_dev.repositories.outline_session_repo import OutlineSessionRepository
from novel_dev.schemas.brainstorm_workspace import SettingSuggestionCardMergePayload
from novel_dev.schemas.outline import SynopsisData, VolumePlan
from novel_dev.schemas.outline_workbench import (
    OutlineClearContextResponse,
    OutlineContextWindow,
    OutlineMessagesResponse,
    OutlineItemSummary,
    OutlineMessagePayload,
    OutlineSubmitResponse,
    OutlineWorkbenchPayload,
)
from novel_dev.services.brainstorm_workspace_service import BrainstormWorkspaceService
from novel_dev.services.log_service import log_service


class SuggestionUpdateSummary(BaseModel):
    created: int = 0
    updated: int = 0
    superseded: int = 0
    unresolved: int = 0


class SuggestionCardUpdateEnvelope(BaseModel):
    cards: list[dict[str, Any]] = Field(default_factory=list)
    summary: SuggestionUpdateSummary = Field(default_factory=SuggestionUpdateSummary)

    @field_validator("cards", mode="before")
    @classmethod
    def normalize_card_items(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        normalized = []
        for item in value:
            if isinstance(item, BaseModel):
                normalized.append(item.model_dump(exclude_none=True))
            else:
                normalized.append(item)
        return normalized


class OutlineWorkbenchService:
    _REGENERATE_INTENT = "regenerate"
    _REVISE_INTENT = "revise"

    def __init__(self, session: AsyncSession):
        self.session = session
        self.novel_state_repo = NovelStateRepository(session)
        self.doc_repo = DocumentRepository(session)
        self.outline_session_repo = OutlineSessionRepository(session)
        self.outline_message_repo = OutlineMessageRepository(session)
        self.workspace_service = BrainstormWorkspaceService(session)

    async def _release_connection_before_external_call(self) -> None:
        if self.session.in_transaction():
            await self.session.commit()

    async def build_workbench(
        self,
        novel_id: str,
        outline_type: str,
        outline_ref: str,
    ) -> OutlineWorkbenchPayload:
        state = await self.novel_state_repo.get_state(novel_id)
        if state is None:
            raise ValueError(f"Novel state not found: {novel_id}")

        workspace_outline_drafts = None
        if self._is_brainstorming_phase(state.current_phase):
            workspace_outline_drafts = (
                await self.workspace_service.get_workspace_payload(novel_id)
            ).outline_drafts

        outline_session = await self.outline_session_repo.get_existing(
            novel_id=novel_id,
            outline_type=outline_type,
            outline_ref=outline_ref,
        )
        if outline_session is not None:
            context_window = await self._build_context_window(
                outline_session.id,
                outline_type=outline_type,
                outline_ref=outline_ref,
                workspace_outline_drafts=workspace_outline_drafts,
            )
            session_id = outline_session.id
        else:
            context_window = self._build_empty_context_window(
                outline_type=outline_type,
                outline_ref=outline_ref,
                checkpoint_data=state.checkpoint_data or {},
                workspace_outline_drafts=workspace_outline_drafts,
            )
            session_id = ""
        return OutlineWorkbenchPayload(
            novel_id=novel_id,
            outline_type=outline_type,
            outline_ref=outline_ref,
            session_id=session_id,
            outline_items=self.build_outline_items(
                state.checkpoint_data or {},
                workspace_outline_drafts=workspace_outline_drafts,
                phase=state.current_phase,
            ),
            context_window=context_window,
        )

    def build_outline_items(
        self,
        checkpoint_data: dict[str, Any],
        workspace_outline_drafts: Optional[dict[str, dict[str, Any]]] = None,
        phase: Optional[str] = None,
    ) -> list[OutlineItemSummary]:
        if self._is_brainstorming_phase(phase):
            return self._build_brainstorm_outline_items(
                checkpoint_data,
                workspace_outline_drafts or {},
            )

        items: list[OutlineItemSummary] = []
        synopsis_data = checkpoint_data.get("synopsis_data") or {}
        if synopsis_data:
            items.append(
                OutlineItemSummary(
                    outline_type="synopsis",
                    outline_ref="synopsis",
                    title="总纲",
                    status="ready",
                    summary=synopsis_data.get("logline") or synopsis_data.get("core_conflict"),
                )
            )

        volume_plan = checkpoint_data.get("current_volume_plan") or {}
        volume_number = volume_plan.get("volume_number")
        estimated_volumes = synopsis_data.get("estimated_volumes") or volume_number or 0

        if volume_number:
            review_status = volume_plan.get("review_status") or {}
            items.append(
                OutlineItemSummary(
                    outline_type="volume",
                    outline_ref=f"vol_{volume_number}",
                    title=volume_plan.get("title") or f"第{volume_number}卷",
                    status="needs_revision" if review_status.get("status") == "revise_failed" else "ready",
                    summary=volume_plan.get("summary"),
                )
            )

        existing_refs = {item.outline_ref for item in items}
        for number in range(1, estimated_volumes + 1):
            outline_ref = f"vol_{number}"
            if outline_ref in existing_refs:
                continue
            items.append(
                OutlineItemSummary(
                    outline_type="volume",
                    outline_ref=outline_ref,
                    title=f"第{number}卷",
                    status="missing",
                )
            )
        return items

    async def submit_feedback(
        self,
        novel_id: str,
        outline_type: str,
        outline_ref: str,
        feedback: str,
    ) -> OutlineSubmitResponse:
        state = await self.novel_state_repo.get_state(novel_id)
        if state is None:
            raise ValueError(f"Novel state not found: {novel_id}")

        workspace_outline_drafts = None
        if self._is_brainstorming_phase(state.current_phase):
            workspace_outline_drafts = (
                await self.workspace_service.get_workspace_payload(novel_id)
            ).outline_drafts

        outline_session = await self.outline_session_repo.get_or_create(
            novel_id=novel_id,
            outline_type=outline_type,
            outline_ref=outline_ref,
            status="active",
        )
        await self.outline_message_repo.create(
            session_id=outline_session.id,
            role="user",
            message_type="feedback",
            content=feedback,
            meta={"outline_type": outline_type, "outline_ref": outline_ref},
        )
        context_window = await self._build_context_window(
            outline_session.id,
            outline_type=outline_type,
            outline_ref=outline_ref,
            workspace_outline_drafts=workspace_outline_drafts,
        )
        clarification_decision = await self._run_generation_clarification_gate(
            novel_id=novel_id,
            session_id=outline_session.id,
            state=state,
            outline_type=outline_type,
            outline_ref=outline_ref,
            feedback=feedback,
            context_window=context_window,
            workspace_outline_drafts=workspace_outline_drafts,
        )
        if clarification_decision:
            decision, clarification_round = clarification_decision
        else:
            decision, clarification_round = None, None
        if decision and decision.status == "clarifying":
            outline_session.status = "awaiting_confirmation"
            outline_session.conversation_summary = self._merge_conversation_summary(
                context_window.conversation_summary,
                feedback,
            )
            assistant_message = await self.outline_message_repo.create(
                session_id=outline_session.id,
                role="assistant",
                message_type="question",
                content=self._build_clarification_question_content(decision),
                meta={
                    "outline_type": outline_type,
                    "outline_ref": outline_ref,
                    "interaction_stage": "generation_clarification",
                    "clarification_round": clarification_round,
                    "max_rounds": MAX_CLARIFICATION_ROUNDS,
                    "clarification_status": decision.status,
                    "confidence": decision.confidence,
                    "missing_points": decision.missing_points,
                    "clarification_summary": decision.clarification_summary,
                    "assumptions": decision.assumptions,
                },
            )
            await self.session.commit()
            return OutlineSubmitResponse(
                session_id=outline_session.id,
                assistant_message=self._serialize_message(assistant_message),
                last_result_snapshot=outline_session.last_result_snapshot,
                conversation_summary=outline_session.conversation_summary,
                setting_update_summary=None,
            )

        if decision:
            feedback = self._append_clarification_context(feedback, decision)

        await self._release_connection_before_external_call()
        log_service.add_log(
            novel_id,
            "OutlineWorkbenchService",
            "开始处理大纲反馈",
            event="agent.progress",
            status="started",
            node="outline_feedback",
            task="submit_outline_feedback",
            metadata={
                "outline_type": outline_type,
                "outline_ref": outline_ref,
                "feedback_chars": len(feedback or ""),
            },
        )
        try:
            optimize_result = await self._optimize_outline(
                novel_id=novel_id,
                outline_type=outline_type,
                outline_ref=outline_ref,
                feedback=feedback,
                context_window=context_window,
            )
        except Exception as exc:
            log_service.add_log(
                novel_id,
                "OutlineWorkbenchService",
                f"大纲反馈处理失败: {exc}",
                level="error",
                event="agent.progress",
                status="failed",
                node="outline_feedback",
                task="submit_outline_feedback",
                metadata={
                    "outline_type": outline_type,
                    "outline_ref": outline_ref,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            raise

        outline_session.status = "active"
        outline_session.last_result_snapshot = optimize_result.get("result_snapshot")
        outline_session.conversation_summary = optimize_result.get("conversation_summary")
        log_service.add_log(
            novel_id,
            "OutlineWorkbenchService",
            "大纲反馈结果已生成,开始保存",
            event="agent.progress",
            status="started",
            node="outline_persist",
            task="persist_outline_feedback_result",
            metadata={
                "outline_type": outline_type,
                "outline_ref": outline_ref,
                "has_result_snapshot": bool(optimize_result.get("result_snapshot")),
                "setting_updates": len(optimize_result.get("setting_draft_updates") or []),
            },
        )
        assistant_message = await self.outline_message_repo.create(
            session_id=outline_session.id,
            role="assistant",
            message_type="result",
            content=optimize_result["content"],
            meta={
                "outline_type": outline_type,
                "outline_ref": outline_ref,
                "result_snapshot": optimize_result.get("result_snapshot"),
                "setting_update_summary": optimize_result.get("setting_update_summary"),
            },
        )
        if self._is_brainstorming_phase(state.current_phase):
            if optimize_result.get("result_snapshot"):
                await self.workspace_service.save_outline_draft(
                    novel_id=novel_id,
                    outline_type=outline_type,
                    outline_ref=outline_ref,
                    result_snapshot=optimize_result["result_snapshot"],
                )
            if optimize_result.get("setting_suggestion_card_updates"):
                await self.workspace_service.merge_suggestion_cards(
                    novel_id=novel_id,
                    card_updates=optimize_result["setting_suggestion_card_updates"],
                )
            if optimize_result.get("setting_draft_updates"):
                await self.workspace_service.merge_setting_drafts(
                    novel_id=novel_id,
                    setting_draft_updates=optimize_result["setting_draft_updates"],
                )
        else:
            await self._write_result_snapshot(
                novel_id=novel_id,
                outline_type=outline_type,
                outline_ref=outline_ref,
                result_snapshot=optimize_result.get("result_snapshot"),
            )
        await self.session.commit()
        log_service.add_log(
            novel_id,
            "OutlineWorkbenchService",
            "大纲反馈处理完成",
            event="agent.progress",
            status="succeeded",
            node="outline_feedback",
            task="submit_outline_feedback",
            metadata={
                "outline_type": outline_type,
                "outline_ref": outline_ref,
                "message_id": assistant_message.id,
            },
        )
        return OutlineSubmitResponse(
            session_id=outline_session.id,
            assistant_message=self._serialize_message(assistant_message),
            last_result_snapshot=outline_session.last_result_snapshot,
            conversation_summary=outline_session.conversation_summary,
            setting_update_summary=optimize_result.get("setting_update_summary"),
        )

    async def get_messages(
        self,
        novel_id: str,
        outline_type: str,
        outline_ref: str,
    ) -> OutlineMessagesResponse:
        state = await self.novel_state_repo.get_state(novel_id)
        if state is None:
            raise ValueError(f"Novel state not found: {novel_id}")

        workspace_outline_drafts = None
        if self._is_brainstorming_phase(state.current_phase):
            workspace_outline_drafts = (
                await self.workspace_service.get_workspace_payload(novel_id)
            ).outline_drafts

        outline_session = await self.outline_session_repo.get_existing(
            novel_id=novel_id,
            outline_type=outline_type,
            outline_ref=outline_ref,
        )
        if outline_session is not None:
            context_window = await self._build_context_window(
                outline_session.id,
                outline_type=outline_type,
                outline_ref=outline_ref,
                workspace_outline_drafts=workspace_outline_drafts,
            )
            session_id = outline_session.id
        else:
            context_window = self._build_empty_context_window(
                outline_type=outline_type,
                outline_ref=outline_ref,
                checkpoint_data=state.checkpoint_data or {},
                workspace_outline_drafts=workspace_outline_drafts,
            )
            session_id = ""
        return OutlineMessagesResponse(
            session_id=session_id,
            outline_type=outline_type,
            outline_ref=outline_ref,
            last_result_snapshot=context_window.last_result_snapshot,
            conversation_summary=context_window.conversation_summary,
            recent_messages=context_window.recent_messages,
        )

    async def clear_context(
        self,
        *,
        novel_id: str,
        outline_type: str,
        outline_ref: str,
    ) -> OutlineClearContextResponse:
        state = await self.novel_state_repo.get_state(novel_id)
        if state is None:
            raise ValueError(f"Novel state not found: {novel_id}")

        outline_session = await self.outline_session_repo.get_or_create(
            novel_id=novel_id,
            outline_type=outline_type,
            outline_ref=outline_ref,
            status="active",
        )
        deleted_messages = await self.outline_message_repo.delete_by_session(outline_session.id)
        outline_session.conversation_summary = None
        outline_session.last_result_snapshot = None
        outline_session.status = "active"
        await self.session.commit()

        log_service.add_log(
            novel_id,
            "OutlineWorkbenchService",
            "已清空当前大纲对话上下文",
            event="agent.progress",
            status="succeeded",
            node="outline_context",
            task="clear_outline_context",
            metadata={
                "outline_type": outline_type,
                "outline_ref": outline_ref,
                "deleted_messages": deleted_messages,
            },
        )
        return OutlineClearContextResponse(
            session_id=outline_session.id,
            outline_type=outline_type,
            outline_ref=outline_ref,
            deleted_messages=deleted_messages,
            conversation_summary=outline_session.conversation_summary,
            last_result_snapshot=outline_session.last_result_snapshot,
        )

    async def review_outline(
        self,
        *,
        novel_id: str,
        outline_type: str,
        outline_ref: str,
    ) -> dict[str, Any]:
        state = await self.novel_state_repo.get_state(novel_id)
        if state is None:
            raise ValueError(f"Novel state not found: {novel_id}")

        workspace_outline_drafts = None
        if self._is_brainstorming_phase(state.current_phase):
            workspace_outline_drafts = (
                await self.workspace_service.get_workspace_payload(novel_id)
            ).outline_drafts
        outline_session = await self.outline_session_repo.get_or_create(
            novel_id=novel_id,
            outline_type=outline_type,
            outline_ref=outline_ref,
            status="active",
        )
        context_window = await self._build_context_window(
            outline_session.id,
            outline_type=outline_type,
            outline_ref=outline_ref,
            workspace_outline_drafts=workspace_outline_drafts,
        )
        snapshot = (
            context_window.last_result_snapshot
            or self._get_workspace_snapshot(workspace_outline_drafts, outline_type, outline_ref)
            or self._get_checkpoint_snapshot(state.checkpoint_data or {}, outline_type, outline_ref)
        )
        if not snapshot:
            raise ValueError("Outline snapshot not found")

        reviewed_snapshot = await self._review_result_snapshot(
            novel_id=novel_id,
            outline_type=outline_type,
            result_snapshot=snapshot,
        )
        outline_session.last_result_snapshot = reviewed_snapshot
        if self._is_brainstorming_phase(state.current_phase):
            await self.workspace_service.save_outline_draft(
                novel_id=novel_id,
                outline_type=outline_type,
                outline_ref=outline_ref,
                result_snapshot=reviewed_snapshot,
            )
        else:
            await self._write_result_snapshot(
                novel_id=novel_id,
                outline_type=outline_type,
                outline_ref=outline_ref,
                result_snapshot=reviewed_snapshot,
            )
        await self.session.commit()
        return {
            "session_id": outline_session.id,
            "outline_type": outline_type,
            "outline_ref": outline_ref,
            "result_snapshot": reviewed_snapshot,
            "review_status": reviewed_snapshot.get("review_status"),
        }

    def _build_empty_context_window(
        self,
        *,
        outline_type: str,
        outline_ref: str,
        checkpoint_data: Optional[dict[str, Any]] = None,
        workspace_outline_drafts: Optional[dict[str, dict[str, Any]]] = None,
    ) -> OutlineContextWindow:
        last_result_snapshot = None
        if workspace_outline_drafts is not None:
            last_result_snapshot = self._get_workspace_snapshot(
                workspace_outline_drafts,
                outline_type,
                outline_ref,
            )
        if last_result_snapshot is None:
            last_result_snapshot = self._get_checkpoint_snapshot(
                checkpoint_data or {},
                outline_type,
                outline_ref,
            )
        return OutlineContextWindow(
            last_result_snapshot=last_result_snapshot,
            conversation_summary=None,
            recent_messages=[],
        )

    async def _build_context_window(
        self,
        session_id: str,
        recent_limit: int = 6,
        outline_type: Optional[str] = None,
        outline_ref: Optional[str] = None,
        workspace_outline_drafts: Optional[dict[str, dict[str, Any]]] = None,
    ) -> OutlineContextWindow:
        outline_session = await self.outline_session_repo.get_by_id(session_id)
        if outline_session is None:
            raise ValueError(f"Outline session not found: {session_id}")

        recent_messages = await self.outline_message_repo.list_recent(session_id, limit=recent_limit)
        ordered_messages = [self._serialize_message(message) for message in reversed(recent_messages)]
        last_result_snapshot = outline_session.last_result_snapshot
        if (
            last_result_snapshot is None
            and workspace_outline_drafts is not None
            and outline_type
            and outline_ref
        ):
            last_result_snapshot = self._get_workspace_snapshot(
                workspace_outline_drafts,
                outline_type,
                outline_ref,
            )
        return OutlineContextWindow(
            last_result_snapshot=last_result_snapshot,
            conversation_summary=outline_session.conversation_summary,
            recent_messages=ordered_messages,
        )

    async def _optimize_outline(
        self,
        *,
        novel_id: str,
        outline_type: str,
        outline_ref: str,
        feedback: str,
        context_window: OutlineContextWindow,
    ) -> dict[str, Any]:
        state = await self.novel_state_repo.get_state(novel_id)
        if state is None:
            raise ValueError(f"Novel state not found: {novel_id}")

        checkpoint = dict(state.checkpoint_data or {})
        workspace_outline_drafts = None
        if self._is_brainstorming_phase(state.current_phase):
            workspace_outline_drafts = (
                await self.workspace_service.get_workspace_payload(novel_id)
            ).outline_drafts

        await self._release_connection_before_external_call()
        intent = self._classify_feedback_intent(feedback, outline_type=outline_type)
        if outline_type == "volume" and self._extract_requested_chapter_count(feedback):
            intent = self._REGENERATE_INTENT
        synopsis_snapshot = None
        if outline_type == "synopsis":
            synopsis_snapshot = self._get_workspace_snapshot(
                workspace_outline_drafts,
                "synopsis",
                "synopsis",
            )
            current_synopsis_snapshot = (
                context_window.last_result_snapshot
                or synopsis_snapshot
                or checkpoint.get("synopsis_data")
            )
            if (
                intent == self._REVISE_INTENT
                and self._should_regenerate_synopsis_revision(
                    current_synopsis_snapshot,
                    feedback,
                )
            ):
                intent = self._REGENERATE_INTENT
        log_service.add_log(
            novel_id,
            "OutlineWorkbenchService",
            f"大纲反馈意图识别: {intent}",
            event="agent.progress",
            status="succeeded",
            node="outline_intent",
            task="classify_outline_feedback_intent",
            metadata={
                "outline_type": outline_type,
                "outline_ref": outline_ref,
                "intent": intent,
                "feedback_chars": len(feedback or ""),
            },
        )

        if outline_type == "synopsis":
            if intent == self._REGENERATE_INTENT:
                result = await self._regenerate_synopsis(
                    novel_id=novel_id,
                    checkpoint=checkpoint,
                    feedback=feedback,
                    context_window=context_window,
                    workspace_snapshot=synopsis_snapshot,
                )
            else:
                result = await self._optimize_synopsis(
                    novel_id=novel_id,
                    checkpoint=checkpoint,
                    feedback=feedback,
                    context_window=context_window,
                    workspace_snapshot=synopsis_snapshot,
                )
        elif outline_type == "volume":
            result = await self._optimize_volume(
                novel_id=novel_id,
                outline_ref=outline_ref,
                checkpoint=checkpoint,
                feedback=feedback,
                context_window=context_window,
                workspace_synopsis_snapshot=self._get_workspace_snapshot(
                    workspace_outline_drafts,
                    "synopsis",
                    "synopsis",
                ),
                workspace_plan_snapshot=self._get_workspace_snapshot(
                    workspace_outline_drafts,
                    outline_type,
                    outline_ref,
                ),
                regenerate=intent == self._REGENERATE_INTENT,
            )
        else:
            raise ValueError(f"Unsupported outline type: {outline_type}")

        if result.get("result_snapshot"):
            result["result_snapshot"] = await self._review_result_snapshot(
                novel_id=novel_id,
                outline_type=outline_type,
                result_snapshot=result["result_snapshot"],
            )

        is_brainstorming = self._is_brainstorming_phase(state.current_phase)
        setting_suggestion_card_updates: list[dict[str, Any]] = result.get(
            "setting_suggestion_card_updates",
            [],
        )
        setting_update_summary = self._normalize_setting_update_summary(
            result.get("setting_update_summary"),
            is_brainstorming=is_brainstorming,
        )
        if is_brainstorming and result.get("result_snapshot"):
            (
                setting_suggestion_card_updates,
                setting_update_summary,
            ) = await self._build_suggestion_card_updates(
                novel_id=novel_id,
                outline_type=outline_type,
                outline_ref=outline_ref,
                feedback=feedback,
                context_window=context_window,
                result_snapshot=result["result_snapshot"],
            )

        return {
            "content": result["content"],
            "result_snapshot": result["result_snapshot"],
            "setting_draft_updates": result.get("setting_draft_updates", []),
            "setting_suggestion_card_updates": setting_suggestion_card_updates,
            "setting_update_summary": setting_update_summary,
            "conversation_summary": self._merge_conversation_summary(
                context_window.conversation_summary,
                feedback,
            ),
        }

    def _normalize_setting_update_summary(
        self,
        summary: Optional[dict[str, int]],
        *,
        is_brainstorming: bool,
    ) -> Optional[dict[str, int]]:
        if summary is None:
            return None

        normalized = SuggestionUpdateSummary.model_validate(summary).model_dump()
        if is_brainstorming:
            return normalized
        if any(value != 0 for value in normalized.values()):
            return normalized
        return None

    async def _review_result_snapshot(
        self,
        *,
        novel_id: str,
        outline_type: str,
        result_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        if outline_type == "synopsis":
            synopsis = SynopsisData.model_validate(result_snapshot)
            score = await BrainstormAgent(self.session)._score_synopsis(synopsis, novel_id)
            payload = synopsis.model_dump()
            payload["review_status"] = {
                "status": "accepted" if BrainstormAgent(self.session)._is_acceptable(score) else "needs_revision",
                "reason": "总纲评分通过。" if BrainstormAgent(self.session)._is_acceptable(score) else "总纲存在未达标维度，建议按优化建议继续修订。",
                "score": score.model_dump(),
                "optimization_suggestion": BrainstormAgent(self.session)._build_score_feedback(score),
            }
            return payload
        if outline_type == "volume":
            plan = VolumePlan.model_validate(result_snapshot)
            planner = VolumePlannerAgent(self.session)
            score = await planner._generate_score(plan, novel_id)
            payload = plan.model_dump()
            payload["review_status"] = {
                "status": "accepted" if planner._is_acceptable(score) else "needs_revision",
                "reason": "卷纲评分通过。" if planner._is_acceptable(score) else "卷纲存在未达标维度，建议按优化建议继续修订。",
                "score": score.model_dump(),
                "optimization_suggestion": planner._build_revise_feedback(score),
            }
            return payload
        return result_snapshot

    async def _build_suggestion_card_updates(
        self,
        *,
        novel_id: str,
        outline_type: str,
        outline_ref: str,
        feedback: str,
        context_window: OutlineContextWindow,
        result_snapshot: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        workspace = await self.workspace_service.get_workspace_payload(novel_id)
        active_cards = self.workspace_service.list_active_suggestion_cards(workspace)
        update_prompt = (
            "你是一位小说设定编辑。根据新的 outline 快照、已有建议卡、历史摘要与用户最新意见，"
            "返回 suggestion card 增量更新 JSON。\n"
            "只返回符合 SuggestionCardUpdateEnvelope Schema 的 JSON，不要解释。\n"
            "cards 每一项必须至少包含 merge_key；新增卡建议同时提供 card_type、title、summary、status 和 payload。\n"
            "如果只是补充已有卡，可以返回 merge_key + payload 的补丁；不要只返回 card_id。\n"
            "supersede 操作只需要 operation='supersede' 和 merge_key。\n"
            f"### outline_type\n{outline_type}\n\n"
            f"### outline_ref\n{outline_ref}\n\n"
            f"### 新 outline 快照\n{json.dumps(result_snapshot, ensure_ascii=False)}\n\n"
            f"### 已有 active suggestion cards\n"
            f"{json.dumps([card.model_dump() for card in active_cards], ensure_ascii=False)}\n\n"
            f"### 历史会话摘要\n{context_window.conversation_summary or '无'}\n\n"
            f"### 最近对话\n{self._format_recent_messages(context_window) or '无'}\n\n"
            f"### 用户最新意见\n{feedback}"
        )
        await self._release_connection_before_external_call()
        updates = await call_and_parse_model(
            "OutlineWorkbenchService",
            "build_suggestion_card_updates",
            update_prompt,
            SuggestionCardUpdateEnvelope,
            novel_id=novel_id,
        )
        cards, skipped_count = self._normalize_suggestion_card_updates(
            updates.cards,
            active_cards=active_cards,
            outline_ref=outline_ref,
        )
        summary = updates.summary.model_dump()
        if skipped_count:
            summary["unresolved"] = summary.get("unresolved", 0) + skipped_count
            remaining = skipped_count
            for key in ("created", "updated", "superseded"):
                available = min(summary.get(key, 0), remaining)
                summary[key] = summary.get(key, 0) - available
                remaining -= available
                if remaining <= 0:
                    break
        return cards, summary

    def _normalize_suggestion_card_updates(
        self,
        raw_cards: list[Any],
        *,
        active_cards: list[Any],
        outline_ref: str,
    ) -> tuple[list[dict[str, Any]], int]:
        existing_by_merge_key = {card.merge_key: card for card in active_cards}
        existing_by_card_id = {card.card_id: card for card in active_cards}
        normalized_cards: list[dict[str, Any]] = []
        skipped_count = 0

        for raw_card in raw_cards:
            card = self._coerce_mapping(raw_card)
            if not card:
                skipped_count += 1
                continue

            operation = str(card.get("operation") or "upsert").strip() or "upsert"
            merge_key = str(card.get("merge_key") or "").strip()
            existing = existing_by_merge_key.get(merge_key)
            if existing is None and card.get("card_id"):
                existing = existing_by_card_id.get(str(card["card_id"]).strip())
                if existing is not None and not merge_key:
                    merge_key = existing.merge_key

            if not merge_key:
                skipped_count += 1
                continue
            if operation == "supersede":
                normalized_cards.append({"operation": "supersede", "merge_key": merge_key})
                continue
            if operation != "upsert":
                operation = "upsert"

            payload = self._merge_suggestion_payload(existing, card.get("payload"))
            card_type = str(
                card.get("card_type")
                or (existing.card_type if existing is not None else "")
                or self._card_type_from_merge_key(merge_key)
                or "unknown"
            ).strip()
            title = self._coerce_nonempty_text(card.get("title")) or (
                existing.title if existing is not None else ""
            ) or self._infer_suggestion_title(merge_key, payload)
            summary = self._coerce_nonempty_text(card.get("summary")) or (
                existing.summary if existing is not None else ""
            ) or self._infer_suggestion_summary(payload)
            status = str(
                card.get("status")
                or (existing.status if existing is not None else "")
                or "active"
            ).strip()

            if not card_type or not title or not summary or not status:
                skipped_count += 1
                continue

            source_outline_refs = sorted(
                set(existing.source_outline_refs if existing is not None else [])
                | set(self._coerce_str_list(card.get("source_outline_refs")))
                | ({outline_ref} if outline_ref else set())
            )

            normalized = {
                "operation": operation,
                "merge_key": merge_key,
                "card_id": str(
                    card.get("card_id")
                    or (existing.card_id if existing is not None else "")
                    or f"card:{merge_key}"
                ).strip(),
                "card_type": card_type,
                "title": title,
                "summary": summary,
                "status": status,
                "source_outline_refs": source_outline_refs,
                "payload": payload,
            }
            if card.get("display_order") is not None:
                normalized["display_order"] = card["display_order"]
            normalized_cards.append(
                SettingSuggestionCardMergePayload.model_validate(normalized).model_dump(
                    exclude_none=True
                )
            )

        return normalized_cards, skipped_count

    def _coerce_mapping(self, value: Any) -> dict[str, Any]:
        if isinstance(value, BaseModel):
            return value.model_dump(exclude_none=True)
        if isinstance(value, dict):
            return dict(value)
        return {}

    def _merge_suggestion_payload(self, existing: Any, incoming_payload: Any) -> dict[str, Any]:
        base = dict(existing.payload) if existing is not None else {}
        if isinstance(incoming_payload, dict):
            base.update(incoming_payload)
        return base

    def _card_type_from_merge_key(self, merge_key: str) -> str:
        card_type, _, _ = merge_key.partition(":")
        return card_type.strip()

    def _coerce_nonempty_text(self, value: Any) -> str:
        text = str(value or "").strip()
        return text

    def _coerce_str_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item or "").strip()]

    def _infer_suggestion_title(self, merge_key: str, payload: dict[str, Any]) -> str:
        for key in (
            "canonical_name",
            "name",
            "title",
            "source_entity_ref",
            "target_entity_ref",
            "relation_type",
        ):
            text = self._coerce_nonempty_text(payload.get(key))
            if text:
                if key == "target_entity_ref" and payload.get("source_entity_ref"):
                    return f"{payload['source_entity_ref']} / {text}"
                return text
        return merge_key

    def _infer_suggestion_summary(self, payload: dict[str, Any]) -> str:
        for key in ("summary", "description", "content", "evidence", "rationale", "goal"):
            text = self._coerce_nonempty_text(payload.get(key))
            if text:
                return text
        return "待补充设定建议。"

    async def _write_result_snapshot(
        self,
        *,
        novel_id: str,
        outline_type: str,
        outline_ref: str,
        result_snapshot: Optional[dict[str, Any]],
    ) -> None:
        if not result_snapshot:
            return

        state = await self.novel_state_repo.get_state(novel_id)
        if state is None:
            raise ValueError(f"Novel state not found: {novel_id}")

        checkpoint = dict(state.checkpoint_data or {})
        current_volume_id = state.current_volume_id
        current_chapter_id = state.current_chapter_id

        if outline_type == "synopsis":
            synopsis = SynopsisData.model_validate(result_snapshot)
            checkpoint["synopsis_data"] = synopsis.model_dump()
            synopsis_doc_id = checkpoint.get("synopsis_doc_id")
            if synopsis_doc_id:
                doc = await self.doc_repo.get_by_id(synopsis_doc_id)
                if doc is not None:
                    formatter = BrainstormAgent(self.session)
                    doc.title = synopsis.title
                    doc.content = formatter.format_synopsis_text(synopsis)
        elif outline_type == "volume":
            volume_plan = VolumePlan.model_validate(result_snapshot)
            current_plan = checkpoint.get("current_volume_plan")
            if current_plan is None or self._outline_ref_matches_volume_data(outline_ref, current_plan):
                checkpoint["current_volume_plan"] = volume_plan.model_dump()
                if volume_plan.chapters:
                    checkpoint["current_chapter_plan"] = volume_plan.chapters[0].model_dump()
                current_volume_id = volume_plan.volume_id
                if volume_plan.chapters:
                    current_chapter_id = volume_plan.chapters[0].chapter_id
                await VolumePlannerAgent(self.session)._persist_volume_plan_artifacts(novel_id, volume_plan)

        await self.novel_state_repo.save_checkpoint(
            novel_id=novel_id,
            current_phase=state.current_phase,
            checkpoint_data=checkpoint,
            current_volume_id=current_volume_id,
            current_chapter_id=current_chapter_id,
        )

    def _serialize_message(self, message: Any) -> OutlineMessagePayload:
        return OutlineMessagePayload(
            id=message.id,
            role=message.role,
            message_type=message.message_type,
            content=message.content,
            meta=message.meta,
            created_at=message.created_at.isoformat() if message.created_at else None,
        )

    async def _optimize_synopsis(
        self,
        *,
        novel_id: str,
        checkpoint: dict[str, Any],
        feedback: str,
        context_window: OutlineContextWindow,
        workspace_snapshot: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        current_snapshot = (
            context_window.last_result_snapshot
            or workspace_snapshot
            or checkpoint.get("synopsis_data")
        )
        if not current_snapshot:
            raise ValueError("Synopsis not found")

        current_synopsis = SynopsisData.model_validate(current_snapshot)
        log_service.add_log(
            novel_id,
            "OutlineWorkbenchService",
            "开始根据反馈修订总纲",
            event="agent.progress",
            status="started",
            node="synopsis_revision",
            task="revise_synopsis_with_feedback",
            metadata={
                "title": current_synopsis.title,
                "feedback_chars": len(feedback or ""),
                "estimated_volumes": current_synopsis.estimated_volumes,
                "volume_outlines": len(current_synopsis.volume_outlines),
            },
        )
        source_text = await self._load_brainstorm_source_text(novel_id)
        recent_messages = self._format_recent_messages(context_window)
        log_service.add_log(
            novel_id,
            "OutlineWorkbenchService",
            "总纲修订上下文已准备",
            event="agent.progress",
            status="succeeded",
            node="synopsis_context",
            task="prepare_synopsis_revision_context",
            metadata={
                "source_chars": len(source_text or ""),
                "recent_message_chars": len(recent_messages or ""),
            },
        )
        prompt = (
            "你是一位小说总纲修订专家。请根据当前 SynopsisData、用户最新修改意见、历史会话摘要和参考设定，"
            "返回严格符合 SynopsisData Schema 的 JSON。要求：\n"
            "1. 优先响应用户最新意见。\n"
            "2. 没被用户要求改动的核心设定、角色基础关系和主线方向尽量保持稳定。\n"
            "3. 如果用户调整规模指标（卷数、章数、字数），要同步让结构规模保持自洽。\n"
            "4. 只返回 JSON，不要解释。\n\n"
            "## 输出字段约束(必须严格遵守)\n"
            "只允许以下顶层字段,禁止输出任何额外字段:\n"
            '{"title","logline","core_conflict","themes","character_arcs","milestones",'
            '"estimated_volumes","estimated_total_chapters","estimated_total_words",'
            '"volume_outlines","entity_highlights","relationship_highlights"}\n'
            "- title: 字符串\n"
            "- logline: 字符串\n"
            "- core_conflict: 字符串\n"
            "- themes: 字符串数组,控制在 3-6 个\n"
            "- character_arcs: 数组,每项只包含 name / arc_summary / key_turning_points 三个字段\n"
            "- milestones: 数组,每项只包含 act / summary / climax_event 三个字段\n"
            "- estimated_volumes: 整数\n"
            "- estimated_total_chapters: 整数\n"
            "- estimated_total_words: 整数\n"
            "- volume_outlines: 数组,长度必须等于 estimated_volumes；每项只包含 "
            "volume_number/title/summary/narrative_role/main_goal/main_conflict/start_state/end_state/"
            "climax/hook_to_next/key_entities/relationship_shifts/foreshadowing_setup/"
            "foreshadowing_payoff/target_chapter_range。它是每卷方向契约,不是完整卷纲,禁止写 chapters 或 beats\n"
            "- entity_highlights: 对象,可选键包括 characters / factions / locations / items,值均为字符串数组\n"
            "- relationship_highlights: 字符串数组,每项描述一个关键关系推进\n"
            "禁止使用旧字段: character / arc / turning_points / name / description / chapter_range。\n"
            "不要输出 Markdown、代码块、解释文字、字段注释,也不要输出 worldview_summary、"
            "three_act_structure、volume_hooks、suspense_plants 等任何额外结构。\n\n"
            f"### 当前 SynopsisData\n{current_synopsis.model_dump_json()}\n\n"
            f"### 历史会话摘要\n{context_window.conversation_summary or '无'}\n\n"
            f"### 最近对话\n{recent_messages or '无'}\n\n"
            f"### 用户最新意见\n{feedback}\n\n"
            f"### 参考设定\n{source_text[:4000] or '无'}"
        )
        await self._release_connection_before_external_call()
        revised = await call_and_parse_model(
            "BrainstormAgent",
            "revise_synopsis_with_feedback",
            prompt,
            SynopsisData,
            novel_id=novel_id,
            config_agent_name="outline_workbench_service",
            config_task="revise_synopsis_with_feedback",
        )
        log_service.add_log(
            novel_id,
            "OutlineWorkbenchService",
            f"已根据反馈修订总纲，预计总章数 {revised.estimated_total_chapters}",
            event="agent.progress",
            status="succeeded",
            node="synopsis_revision",
            task="revise_synopsis_with_feedback",
            metadata={
                "title": revised.title,
                "estimated_volumes": revised.estimated_volumes,
                "estimated_total_chapters": revised.estimated_total_chapters,
                "volume_outlines": len(revised.volume_outlines),
            },
        )
        return {
            "content": self._build_synopsis_result_message(current_synopsis, revised),
            "result_snapshot": revised.model_dump(),
            "setting_draft_updates": [],
        }

    async def _regenerate_synopsis(
        self,
        *,
        novel_id: str,
        checkpoint: dict[str, Any],
        feedback: str,
        context_window: OutlineContextWindow,
        workspace_snapshot: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        current_snapshot = (
            context_window.last_result_snapshot
            or workspace_snapshot
            or checkpoint.get("synopsis_data")
        )
        current_synopsis = SynopsisData.model_validate(current_snapshot) if current_snapshot else None
        log_service.add_log(
            novel_id,
            "OutlineWorkbenchService",
            "识别为重写生成总纲,开始重新生成并替换旧版",
            event="agent.progress",
            status="started",
            node="synopsis_regeneration",
            task="generate_synopsis",
            metadata={
                "feedback_chars": len(feedback or ""),
                "previous_title": current_synopsis.title if current_synopsis else None,
            },
        )
        log_service.add_log(
            novel_id,
            "OutlineWorkbenchService",
            "准备总纲重写上下文",
            event="agent.progress",
            status="started",
            node="synopsis_regeneration_context",
            task="prepare_synopsis_regeneration_context",
            metadata={
                "has_previous_snapshot": current_synopsis is not None,
                "recent_messages": len(context_window.recent_messages),
            },
        )
        source_text = await self._load_brainstorm_source_text(novel_id)
        recent_messages = self._format_recent_messages(context_window)
        log_service.add_log(
            novel_id,
            "OutlineWorkbenchService",
            "总纲重写上下文已准备,即将调用模型",
            event="agent.progress",
            status="succeeded",
            node="synopsis_regeneration_context",
            task="prepare_synopsis_regeneration_context",
            metadata={
                "source_chars": len(source_text or ""),
                "recent_message_chars": len(recent_messages or ""),
                "previous_title": current_synopsis.title if current_synopsis else None,
            },
        )
        previous_scale = (
            "无"
            if current_synopsis is None
            else (
                f"旧标题: {current_synopsis.title}\n"
                f"旧预估卷数: {current_synopsis.estimated_volumes}\n"
                f"旧预估总章数: {current_synopsis.estimated_total_chapters}\n"
                f"旧预估总字数: {current_synopsis.estimated_total_words}"
            )
        )
        combined_text = (
            "### 用户本次重写生成要求\n"
            f"{feedback}\n\n"
            "### 历史对话摘要\n"
            f"{context_window.conversation_summary or '无'}\n\n"
            "### 最近对话\n"
            f"{recent_messages or '无'}\n\n"
            "### 旧版规模参考(只可参考规模,禁止继承旧版剧情、人物、势力、地点、物品)\n"
            f"{previous_scale}\n\n"
            "### 参考设定\n"
            f"{source_text or '无'}"
        )
        await self._release_connection_before_external_call()
        log_service.add_log(
            novel_id,
            "OutlineWorkbenchService",
            "调用模型重新生成总纲",
            event="agent.progress",
            status="started",
            node="synopsis_regeneration_llm",
            task="generate_synopsis",
            metadata={"prompt_chars": len(combined_text)},
        )
        regenerated = await BrainstormAgent(self.session)._generate_synopsis(combined_text, novel_id)
        log_service.add_log(
            novel_id,
            "OutlineWorkbenchService",
            f"已重新生成总纲并准备替换旧版: {regenerated.title}",
            event="agent.progress",
            status="succeeded",
            node="synopsis_regeneration",
            task="generate_synopsis",
            metadata={
                "title": regenerated.title,
                "estimated_volumes": regenerated.estimated_volumes,
                "estimated_total_chapters": regenerated.estimated_total_chapters,
                "volume_outlines": len(regenerated.volume_outlines),
            },
        )
        return {
            "content": (
                f"已按你的要求重新生成总纲并替换旧版："
                f"《{regenerated.title}》，预计 {regenerated.estimated_volumes} 卷、"
                f"{regenerated.estimated_total_chapters} 章。"
            ),
            "result_snapshot": regenerated.model_dump(),
            "setting_draft_updates": [],
        }

    async def _optimize_volume(
        self,
        *,
        novel_id: str,
        outline_ref: str,
        checkpoint: dict[str, Any],
        feedback: str,
        context_window: OutlineContextWindow,
        workspace_synopsis_snapshot: Optional[dict[str, Any]] = None,
        workspace_plan_snapshot: Optional[dict[str, Any]] = None,
        regenerate: bool = False,
    ) -> dict[str, Any]:
        synopsis_payload = workspace_synopsis_snapshot or checkpoint.get("synopsis_data")
        if not synopsis_payload:
            raise ValueError("Synopsis not found")

        synopsis = SynopsisData.model_validate(synopsis_payload)
        volume_number = self._parse_volume_number(outline_ref)
        if volume_number is None:
            raise ValueError(f"Invalid volume outline ref: {outline_ref}")

        planner = VolumePlannerAgent(self.session)
        world_snapshot = await planner._load_world_snapshot(novel_id) if volume_number > 1 else None
        plan_context = await planner._build_plan_context(synopsis, world_snapshot, novel_id, volume_number)
        await self._release_connection_before_external_call()

        current_plan_payload = context_window.last_result_snapshot or workspace_plan_snapshot
        if not current_plan_payload:
            persisted_plan = checkpoint.get("current_volume_plan")
            if persisted_plan and self._outline_ref_matches_volume_data(outline_ref, persisted_plan):
                current_plan_payload = persisted_plan

        if regenerate:
            previous_title = None
            if current_plan_payload:
                previous_title = VolumePlan.model_validate(current_plan_payload).title
            log_service.add_log(
                novel_id,
                "OutlineWorkbenchService",
                f"识别为重写生成第 {volume_number} 卷卷纲,开始重新生成并替换旧版",
                event="agent.progress",
                status="started",
                node="volume_regeneration",
                task="generate_volume_plan",
                metadata={
                    "volume_number": volume_number,
                    "feedback_chars": len(feedback or ""),
                    "previous_title": previous_title,
                },
            )
            regenerated = await planner._generate_volume_plan(
                synopsis,
                volume_number,
                world_snapshot,
                novel_id,
                generation_instruction=feedback,
                target_chapters=self._extract_requested_chapter_count(feedback),
            )
            log_service.add_log(
                novel_id,
                "OutlineWorkbenchService",
                f"已重新生成 {regenerated.title}",
                event="agent.progress",
                status="succeeded",
                node="volume_regeneration",
                task="generate_volume_plan",
                metadata={
                    "volume_number": regenerated.volume_number,
                    "total_chapters": regenerated.total_chapters,
                    "estimated_total_words": regenerated.estimated_total_words,
                },
            )
            return {
                "content": f"已按你的要求重新生成并替换《{regenerated.title}》卷纲，共 {regenerated.total_chapters} 章。",
                "result_snapshot": regenerated.model_dump(),
                "setting_draft_updates": [],
            }

        if current_plan_payload:
            current_plan = VolumePlan.model_validate(current_plan_payload)
        else:
            current_plan = await planner._generate_volume_plan(synopsis, volume_number, world_snapshot, novel_id)

        revised = await planner._revise_volume_plan(current_plan, feedback, plan_context, novel_id)
        log_service.add_log(
            novel_id,
            "OutlineWorkbenchService",
            f"已根据反馈修订 {revised.title}",
        )
        return {
            "content": f"已根据反馈更新《{revised.title}》卷纲，共 {revised.total_chapters} 章。",
            "result_snapshot": revised.model_dump(),
            "setting_draft_updates": [],
        }

    def _classify_feedback_intent(self, feedback: str, outline_type: Optional[str] = None) -> str:
        text = (feedback or "").strip().lower()
        if not text:
            return self._REVISE_INTENT

        negative_markers = (
            "不要重写",
            "别重写",
            "不用重写",
            "无需重写",
            "不要重新生成",
            "别重新生成",
            "不用重新生成",
            "无需重新生成",
            "不要从头",
            "别从头",
        )
        if any(marker in text for marker in negative_markers):
            return self._REVISE_INTENT

        regenerate_markers = (
            "重写",
            "重写生成",
            "重新生成",
            "重新写",
            "重新规划",
            "重新设计",
            "重新做",
            "重做",
            "重来",
            "重开",
            "从头生成",
            "从头规划",
            "从头写",
            "从零生成",
            "从零规划",
            "推倒重来",
            "替换旧",
            "替换掉旧",
            "全新生成",
            "全新规划",
            "另起一版",
            "新版本",
            "新创建",
            "再生成一版",
            "再做一版",
        )
        if any(marker in text for marker in regenerate_markers):
            return self._REGENERATE_INTENT
        synopsis_generation_markers = (
            "生成完整总纲",
            "生成总纲草稿",
            "生成完整大纲",
            "完整总纲草稿",
            "完整总纲",
            "补齐一句话梗概",
            "补齐核心冲突",
            "补齐卷数规模",
            "补齐人物弧光",
            "补齐关键里程碑",
        )
        if outline_type == "synopsis" and any(
            marker in text for marker in synopsis_generation_markers
        ):
            return self._REGENERATE_INTENT
        synopsis_review_markers = (
            "overall=",
            "logline_specificity=",
            "conflict_concreteness=",
            "character_arc_depth=",
            "structural_turns=",
            "hook_strength=",
            "评审意见",
            "低于下限",
            "optimization_suggestion",
            "本synopsis",
        )
        if outline_type == "synopsis" and any(
            marker in text for marker in synopsis_review_markers
        ):
            return self._REGENERATE_INTENT
        max_chapters = 3000 if outline_type == "synopsis" else 300
        if self._extract_requested_chapter_count(text, max_chapters=max_chapters):
            return self._REGENERATE_INTENT
        return self._REVISE_INTENT

    def _should_regenerate_synopsis_revision(
        self,
        current_synopsis: SynopsisData | dict[str, Any] | None,
        feedback: str,
    ) -> bool:
        if current_synopsis is None:
            return False
        synopsis = (
            current_synopsis
            if isinstance(current_synopsis, SynopsisData)
            else SynopsisData.model_validate(current_synopsis)
        )
        if synopsis.estimated_total_chapters >= 500:
            return True
        if synopsis.estimated_volumes >= 8:
            return True
        if len(synopsis.volume_outlines or []) >= 8:
            return True
        return False

    @staticmethod
    def _extract_requested_chapter_count(
        feedback: str,
        *,
        max_chapters: int = 300,
    ) -> Optional[int]:
        text = (feedback or "").strip()
        if not text:
            return None
        patterns = (
            r"(?:要求|要|改成|调整为|生成|规划|扩到|扩展到|增加到|做到|约|左右)?\s*(\d{1,4})\s*章(?:左右|上下|附近|以内|以上)?",
            r"(\d{1,4})\s*(?:章|章节)",
        )
        counts: list[int] = []
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                count = int(match.group(1))
                if 1 <= count <= max_chapters:
                    counts.append(count)
        return counts[-1] if counts else None

    def _is_brainstorming_phase(self, phase: Optional[str]) -> bool:
        return phase == "brainstorming"

    def _build_brainstorm_outline_items(
        self,
        checkpoint_data: dict[str, Any],
        outline_drafts: dict[str, dict[str, Any]],
    ) -> list[OutlineItemSummary]:
        items: list[OutlineItemSummary] = []
        checkpoint_synopsis = checkpoint_data.get("synopsis_data") or {}
        synopsis_snapshot = outline_drafts.get("synopsis:synopsis") or checkpoint_synopsis

        if synopsis_snapshot:
            items.append(
                OutlineItemSummary(
                    outline_type="synopsis",
                    outline_ref="synopsis",
                    title="总纲",
                    status="ready" if outline_drafts.get("synopsis:synopsis") else "missing",
                    summary=synopsis_snapshot.get("logline") or synopsis_snapshot.get("core_conflict"),
                )
            )

        volume_snapshots = []
        for outline_key, snapshot in outline_drafts.items():
            if not outline_key.startswith("volume:"):
                continue
            outline_ref = self._extract_outline_ref(outline_key)
            volume_number = self._parse_volume_number(outline_ref)
            volume_snapshots.append((volume_number or 0, outline_ref, snapshot))

        for _, outline_ref, snapshot in sorted(volume_snapshots, key=lambda item: (item[0], item[1])):
            volume_number = self._parse_volume_number(outline_ref)
            items.append(
                OutlineItemSummary(
                    outline_type="volume",
                    outline_ref=outline_ref,
                    title=snapshot.get("title") or (f"第{volume_number}卷" if volume_number else outline_ref),
                    status="ready",
                    summary=snapshot.get("summary"),
                )
            )

        estimated_volumes = (
            synopsis_snapshot.get("estimated_volumes")
            or checkpoint_synopsis.get("estimated_volumes")
            or 0
        )
        existing_refs = {item.outline_ref for item in items}
        for number in range(1, estimated_volumes + 1):
            outline_ref = f"vol_{number}"
            if outline_ref in existing_refs:
                continue
            items.append(
                OutlineItemSummary(
                    outline_type="volume",
                    outline_ref=outline_ref,
                    title=f"第{number}卷",
                    status="missing",
                )
            )
        return items

    def _get_workspace_snapshot(
        self,
        outline_drafts: Optional[dict[str, dict[str, Any]]],
        outline_type: str,
        outline_ref: str,
    ) -> Optional[dict[str, Any]]:
        if not outline_drafts:
            return None
        return outline_drafts.get(f"{outline_type}:{outline_ref}")

    def _get_checkpoint_snapshot(
        self,
        checkpoint_data: dict[str, Any],
        outline_type: str,
        outline_ref: str,
    ) -> Optional[dict[str, Any]]:
        if outline_type == "synopsis" and outline_ref == "synopsis":
            return checkpoint_data.get("synopsis_data")
        if outline_type != "volume":
            return None
        current_volume_plan = checkpoint_data.get("current_volume_plan")
        if self._outline_ref_matches_volume_data(outline_ref, current_volume_plan):
            return current_volume_plan
        return None

    def _extract_outline_ref(self, outline_key: str) -> str:
        _, _, outline_ref = outline_key.partition(":")
        return outline_ref

    async def _run_generation_clarification_gate(
        self,
        *,
        novel_id: str,
        session_id: str,
        state: Any,
        outline_type: str,
        outline_ref: str,
        feedback: str,
        context_window: OutlineContextWindow,
        workspace_outline_drafts: Optional[dict[str, dict[str, Any]]],
    ) -> tuple[OutlineClarificationDecision, int] | None:
        if not self._should_run_generation_clarification(
            state=state,
            outline_type=outline_type,
            outline_ref=outline_ref,
            workspace_outline_drafts=workspace_outline_drafts,
        ):
            return None

        round_number = await self._next_clarification_round_for_session(session_id)
        if OutlineClarificationAgent.is_force_generate_intent(feedback):
            return (
                OutlineClarificationAgent.force_generate_decision("用户要求跳过进一步澄清"),
                round_number,
            )

        request = OutlineClarificationRequest(
            novel_id=novel_id,
            outline_type=outline_type,
            outline_ref=outline_ref,
            feedback=feedback,
            context_window=context_window,
            round_number=round_number,
            max_rounds=MAX_CLARIFICATION_ROUNDS,
            source_text=await self._load_brainstorm_source_text(novel_id),
            workspace_snapshot=self._get_workspace_snapshot(
                workspace_outline_drafts,
                outline_type,
                outline_ref,
            ),
            checkpoint_snapshot=self._get_checkpoint_snapshot(
                state.checkpoint_data or {},
                outline_type,
                outline_ref,
            ),
        )
        await self._release_connection_before_external_call()
        try:
            return await OutlineClarificationAgent().clarify(request), round_number
        except Exception as exc:
            if round_number <= 1 and not self._has_user_clarification_answer(context_window):
                log_service.add_log(
                    novel_id,
                    "OutlineClarificationAgent",
                    f"澄清判断失败，使用本地兜底问题: {exc}",
                    level="warning",
                    event="agent.progress",
                    status="failed",
                    node="outline_clarification",
                    task="outline_clarify",
                    metadata={
                        "outline_type": outline_type,
                        "outline_ref": outline_ref,
                        "clarification_round": round_number,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
                return (
                    OutlineClarificationDecision(
                        status="clarifying",
                        confidence=0.0,
                        missing_points=["澄清模型暂不可用"],
                        questions=[self._fallback_clarification_question(outline_type, outline_ref)],
                        clarification_summary="澄清模型暂不可用，先收集用户最关键的生成偏好。",
                        assumptions=[],
                        reason=f"{type(exc).__name__}: {exc}",
                    ),
                    round_number,
                )

            return (
                OutlineClarificationDecision(
                    status="force_generate",
                    confidence=0.0,
                    missing_points=["澄清模型暂不可用"],
                    questions=[],
                    clarification_summary="澄清模型暂不可用，系统基于当前可见设定生成。",
                    assumptions=["澄清模型暂不可用，系统基于当前可见设定生成。"],
                    reason=f"{type(exc).__name__}: {exc}",
                ),
                round_number,
            )

    def _should_run_generation_clarification(
        self,
        *,
        state: Any,
        outline_type: str,
        outline_ref: str,
        workspace_outline_drafts: Optional[dict[str, dict[str, Any]]],
    ) -> bool:
        if not self._is_brainstorming_phase(getattr(state, "current_phase", None)):
            return False

        items = self.build_outline_items(
            state.checkpoint_data or {},
            workspace_outline_drafts=workspace_outline_drafts,
            phase=state.current_phase,
        )
        current_item = next(
            (
                item
                for item in items
                if item.outline_type == outline_type and item.outline_ref == outline_ref
            ),
            None,
        )
        return current_item is not None and current_item.status == "missing"

    async def _next_clarification_round_for_session(self, session_id: str) -> int:
        result = await self.session.execute(
            select(OutlineMessage.meta).where(OutlineMessage.session_id == session_id)
        )
        rounds: list[int] = []
        for meta in result.scalars().all():
            if (meta or {}).get("interaction_stage") != "generation_clarification":
                continue
            try:
                rounds.append(int((meta or {}).get("clarification_round") or 0))
            except (TypeError, ValueError):
                continue
        return (max(rounds) if rounds else 0) + 1

    def _has_user_clarification_answer(self, context_window: OutlineContextWindow) -> bool:
        seen_question = False
        for message in context_window.recent_messages:
            if (
                message.role == "assistant"
                and message.message_type == "question"
                and (message.meta or {}).get("interaction_stage") == "generation_clarification"
            ):
                seen_question = True
                continue
            if seen_question and message.role == "user":
                return True
        return False

    def _fallback_clarification_question(self, outline_type: str, outline_ref: str) -> str:
        if outline_type == "volume":
            volume_number = self._parse_volume_number(outline_ref)
            label = f"第 {volume_number} 卷" if volume_number else "当前卷"
            return (
                f"开始生成{label}卷纲前，请补充这一卷最关键的主线目标、卷末钩子或必须出现的角色推进。"
                "也可以回复“按当前设定生成”。"
            )
        return "开始生成总纲前，请补充题材基调、核心卖点或必须保留/避免的关键设定。也可以回复“按当前设定生成”。"

    def _build_clarification_question_content(self, decision: OutlineClarificationDecision) -> str:
        question_text = "\n".join(
            f"{index}. {question}"
            for index, question in enumerate(decision.questions[:3], start=1)
        )
        suffix = "如果已经足够，也可以直接回复“按当前设定生成”。"
        return f"{question_text}\n{suffix}".strip()

    def _append_clarification_context(self, feedback: str, decision: OutlineClarificationDecision) -> str:
        parts = [feedback.strip()]
        if decision.clarification_summary:
            parts.append(f"澄清摘要：{decision.clarification_summary}")
        if decision.assumptions:
            parts.append("生成假设：\n" + "\n".join(f"- {item}" for item in decision.assumptions))
        return "\n\n".join(part for part in parts if part)

    async def _load_brainstorm_source_text(self, novel_id: str) -> str:
        docs = await self.doc_repo.get_current_by_type(novel_id, "worldview")
        docs += await self.doc_repo.get_current_by_type(novel_id, "setting")
        docs += await self.doc_repo.get_current_by_type(novel_id, "concept")
        return "\n\n".join(f"[{doc.doc_type}] {doc.title}\n{doc.content}" for doc in docs)

    def _merge_conversation_summary(self, existing: Optional[str], feedback: str) -> str:
        entries = []
        if existing:
            entries.append(existing.strip())
        feedback = feedback.strip()
        if feedback:
            entries.append(f"最新意见：{feedback}")
        return "\n".join(entry for entry in entries if entry).strip()[:1200]

    def _format_recent_messages(self, context_window: OutlineContextWindow) -> str:
        lines = []
        for message in context_window.recent_messages[-6:]:
            role = "用户" if message.role == "user" else "系统"
            lines.append(f"{role}: {message.content}")
        return "\n".join(lines)

    def _build_synopsis_result_message(self, current: SynopsisData, revised: SynopsisData) -> str:
        parts = []
        if current.estimated_total_chapters != revised.estimated_total_chapters:
            parts.append(f"预计总章数调整为约 {revised.estimated_total_chapters} 章")
        if current.estimated_volumes != revised.estimated_volumes:
            parts.append(f"预估卷数调整为 {revised.estimated_volumes} 卷")
        if current.estimated_total_words != revised.estimated_total_words:
            parts.append(f"预估总字数调整为约 {revised.estimated_total_words} 字")
        if current.logline != revised.logline:
            parts.append("同步更新了一句话梗概")
        if current.core_conflict != revised.core_conflict:
            parts.append("同步收紧了核心冲突")
        if not parts:
            parts.append("已根据反馈更新总纲")
        return "已根据反馈更新总纲：" + "，".join(parts) + "。"

    def _parse_volume_number(self, outline_ref: str) -> Optional[int]:
        if not outline_ref.startswith("vol_"):
            return None
        suffix = outline_ref.replace("vol_", "", 1)
        return int(suffix) if suffix.isdigit() else None

    def _outline_ref_matches_volume_data(self, outline_ref: str, payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False
        volume_id = str(payload.get("volume_id") or "")
        if volume_id == outline_ref:
            return True
        volume_number = payload.get("volume_number")
        parsed_number = self._parse_volume_number(outline_ref)
        return parsed_number is not None and volume_number == parsed_number
