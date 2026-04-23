import json
from typing import Any, Optional

from novel_dev.agents._llm_helpers import call_and_parse_model
from novel_dev.agents.brainstorm_agent import BrainstormAgent
from novel_dev.agents.volume_planner import VolumePlannerAgent
from novel_dev.repositories.document_repo import DocumentRepository
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.outline_message_repo import OutlineMessageRepository
from novel_dev.repositories.outline_session_repo import OutlineSessionRepository
from novel_dev.schemas.brainstorm_workspace import SettingSuggestionCardMergePayload
from novel_dev.schemas.outline import SynopsisData, VolumePlan
from novel_dev.schemas.outline_workbench import (
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
    cards: list[SettingSuggestionCardMergePayload] = Field(default_factory=list)
    summary: SuggestionUpdateSummary = Field(default_factory=SuggestionUpdateSummary)


class OutlineWorkbenchService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.novel_state_repo = NovelStateRepository(session)
        self.doc_repo = DocumentRepository(session)
        self.outline_session_repo = OutlineSessionRepository(session)
        self.outline_message_repo = OutlineMessageRepository(session)
        self.workspace_service = BrainstormWorkspaceService(session)

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
        return OutlineWorkbenchPayload(
            novel_id=novel_id,
            outline_type=outline_type,
            outline_ref=outline_ref,
            session_id=outline_session.id,
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
            items.append(
                OutlineItemSummary(
                    outline_type="volume",
                    outline_ref=f"vol_{volume_number}",
                    title=volume_plan.get("title") or f"第{volume_number}卷",
                    status="ready",
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
        if self._should_request_generation_confirmation(
            state=state,
            outline_session=outline_session,
            outline_type=outline_type,
            outline_ref=outline_ref,
            workspace_outline_drafts=workspace_outline_drafts,
        ):
            outline_session.status = "awaiting_confirmation"
            outline_session.conversation_summary = self._merge_conversation_summary(
                context_window.conversation_summary,
                feedback,
            )
            assistant_message = await self.outline_message_repo.create(
                session_id=outline_session.id,
                role="assistant",
                message_type="question",
                content=self._build_generation_confirmation_message(
                    outline_type=outline_type,
                    outline_ref=outline_ref,
                ),
                meta={
                    "outline_type": outline_type,
                    "outline_ref": outline_ref,
                    "interaction_stage": "generation_confirmation",
                },
            )
            await self.session.commit()
            return OutlineSubmitResponse(
                session_id=outline_session.id,
                assistant_message=self._serialize_message(assistant_message),
                last_result_snapshot=outline_session.last_result_snapshot,
                conversation_summary=outline_session.conversation_summary,
            )

        optimize_result = await self._optimize_outline(
            novel_id=novel_id,
            outline_type=outline_type,
            outline_ref=outline_ref,
            feedback=feedback,
            context_window=context_window,
        )

        outline_session.status = "active"
        outline_session.last_result_snapshot = optimize_result.get("result_snapshot")
        outline_session.conversation_summary = optimize_result.get("conversation_summary")
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
        return OutlineSubmitResponse(
            session_id=outline_session.id,
            assistant_message=self._serialize_message(assistant_message),
            last_result_snapshot=outline_session.last_result_snapshot,
            conversation_summary=outline_session.conversation_summary,
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
        return OutlineMessagesResponse(
            session_id=outline_session.id,
            outline_type=outline_type,
            outline_ref=outline_ref,
            last_result_snapshot=context_window.last_result_snapshot,
            conversation_summary=context_window.conversation_summary,
            recent_messages=context_window.recent_messages,
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

        if outline_type == "synopsis":
            result = await self._optimize_synopsis(
                novel_id=novel_id,
                checkpoint=checkpoint,
                feedback=feedback,
                context_window=context_window,
                workspace_snapshot=self._get_workspace_snapshot(
                    workspace_outline_drafts,
                    "synopsis",
                    "synopsis",
                ),
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
            )
        else:
            raise ValueError(f"Unsupported outline type: {outline_type}")

        setting_suggestion_card_updates: list[dict[str, Any]] = result.get(
            "setting_suggestion_card_updates",
            [],
        )
        setting_update_summary: dict[str, int] = result.get(
            "setting_update_summary",
            SuggestionUpdateSummary().model_dump(),
        )
        if self._is_brainstorming_phase(state.current_phase) and result.get("result_snapshot"):
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
            f"### outline_type\n{outline_type}\n\n"
            f"### outline_ref\n{outline_ref}\n\n"
            f"### 新 outline 快照\n{json.dumps(result_snapshot, ensure_ascii=False)}\n\n"
            f"### 已有 active suggestion cards\n"
            f"{json.dumps([card.model_dump() for card in active_cards], ensure_ascii=False)}\n\n"
            f"### 历史会话摘要\n{context_window.conversation_summary or '无'}\n\n"
            f"### 最近对话\n{self._format_recent_messages(context_window) or '无'}\n\n"
            f"### 用户最新意见\n{feedback}"
        )
        updates = await call_and_parse_model(
            "OutlineWorkbenchService",
            "build_suggestion_card_updates",
            update_prompt,
            SuggestionCardUpdateEnvelope,
            novel_id=novel_id,
        )
        return [item.model_dump() for item in updates.cards], updates.summary.model_dump()

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
        source_text = await self._load_brainstorm_source_text(novel_id)
        recent_messages = self._format_recent_messages(context_window)
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
            '"estimated_volumes","estimated_total_chapters","estimated_total_words"}\n'
            "- title: 字符串\n"
            "- logline: 字符串\n"
            "- core_conflict: 字符串\n"
            "- themes: 字符串数组,控制在 3-6 个\n"
            "- character_arcs: 数组,每项只包含 name / arc_summary / key_turning_points 三个字段\n"
            "- milestones: 数组,每项只包含 act / summary / climax_event 三个字段\n"
            "- estimated_volumes: 整数\n"
            "- estimated_total_chapters: 整数\n"
            "- estimated_total_words: 整数\n"
            "禁止使用旧字段: character / arc / turning_points / name / description / chapter_range。\n"
            "不要输出 Markdown、代码块、解释文字、字段注释,也不要输出 worldview_summary、"
            "three_act_structure、volume_hooks、suspense_plants 等任何额外结构。\n\n"
            f"### 当前 SynopsisData\n{current_synopsis.model_dump_json()}\n\n"
            f"### 历史会话摘要\n{context_window.conversation_summary or '无'}\n\n"
            f"### 最近对话\n{recent_messages or '无'}\n\n"
            f"### 用户最新意见\n{feedback}\n\n"
            f"### 参考设定\n{source_text[:4000] or '无'}"
        )
        revised = await call_and_parse_model(
            "BrainstormAgent",
            "revise_synopsis_with_feedback",
            prompt,
            SynopsisData,
            novel_id=novel_id,
        )
        log_service.add_log(
            novel_id,
            "OutlineWorkbenchService",
            f"已根据反馈修订总纲，预计总章数 {revised.estimated_total_chapters}",
        )
        return {
            "content": self._build_synopsis_result_message(current_synopsis, revised),
            "result_snapshot": revised.model_dump(),
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
        plan_context = planner._build_plan_context(synopsis, world_snapshot)

        current_plan_payload = context_window.last_result_snapshot or workspace_plan_snapshot
        if not current_plan_payload:
            persisted_plan = checkpoint.get("current_volume_plan")
            if persisted_plan and self._outline_ref_matches_volume_data(outline_ref, persisted_plan):
                current_plan_payload = persisted_plan

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

    def _extract_outline_ref(self, outline_key: str) -> str:
        _, _, outline_ref = outline_key.partition(":")
        return outline_ref

    def _should_request_generation_confirmation(
        self,
        *,
        state: Any,
        outline_session: Any,
        outline_type: str,
        outline_ref: str,
        workspace_outline_drafts: Optional[dict[str, dict[str, Any]]],
    ) -> bool:
        if not self._is_brainstorming_phase(getattr(state, "current_phase", None)):
            return False
        if getattr(outline_session, "status", "") == "awaiting_confirmation":
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

    def _build_generation_confirmation_message(self, *, outline_type: str, outline_ref: str) -> str:
        if outline_type == "synopsis":
            return (
                "在我开始生成总纲草稿前，先确认几个关键信息。你可以直接用一条消息回复，也可以只回答你在意的部分：\n"
                "1. 题材、基调和你最想突出的卖点是什么？\n"
                "2. 预计卷数、总篇幅是否按当前设定走，还是要调整？\n"
                "3. 有没有必须保留或必须避免的人物关系、世界观设定、终局方向？\n"
                "如果你已经想清楚，也可以直接回复“按当前设定生成”，我再开始生成总纲草稿。"
            )

        volume_number = self._parse_volume_number(outline_ref)
        volume_label = f"第 {volume_number} 卷" if volume_number else "当前卷"
        return (
            f"在我开始生成{volume_label}卷纲前，先确认几个关键信息。你可以直接用一条消息回复，也可以只回答最在意的部分：\n"
            "1. 这一卷最核心的主线目标、冲突和情绪走向是什么？\n"
            "2. 有没有必须出现的角色推进、伏笔回收或卷末钩子？\n"
            "3. 节奏上更偏升级推进、群像展开，还是阴谋揭示？\n"
            f"如果你已经想清楚，也可以直接回复“按当前设定生成{volume_label}卷纲”，我再开始生成。"
        )

    async def _load_brainstorm_source_text(self, novel_id: str) -> str:
        docs = await self.doc_repo.get_by_type(novel_id, "worldview")
        docs += await self.doc_repo.get_by_type(novel_id, "setting")
        docs += await self.doc_repo.get_by_type(novel_id, "concept")
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
