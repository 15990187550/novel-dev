from typing import Any, Optional

from novel_dev.agents._llm_helpers import call_and_parse_model
from novel_dev.agents.brainstorm_agent import BrainstormAgent
from novel_dev.agents.volume_planner import VolumePlannerAgent
from novel_dev.repositories.document_repo import DocumentRepository
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.outline_message_repo import OutlineMessageRepository
from novel_dev.repositories.outline_session_repo import OutlineSessionRepository
from novel_dev.schemas.outline import SynopsisData, VolumePlan
from novel_dev.schemas.outline_workbench import (
    OutlineContextWindow,
    OutlineMessagesResponse,
    OutlineItemSummary,
    OutlineMessagePayload,
    OutlineSubmitResponse,
    OutlineWorkbenchPayload,
)
from novel_dev.services.log_service import log_service


class OutlineWorkbenchService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.novel_state_repo = NovelStateRepository(session)
        self.doc_repo = DocumentRepository(session)
        self.outline_session_repo = OutlineSessionRepository(session)
        self.outline_message_repo = OutlineMessageRepository(session)

    async def build_workbench(
        self,
        novel_id: str,
        outline_type: str,
        outline_ref: str,
    ) -> OutlineWorkbenchPayload:
        state = await self.novel_state_repo.get_state(novel_id)
        if state is None:
            raise ValueError(f"Novel state not found: {novel_id}")

        outline_session = await self.outline_session_repo.get_or_create(
            novel_id=novel_id,
            outline_type=outline_type,
            outline_ref=outline_ref,
            status="active",
        )
        context_window = await self._build_context_window(outline_session.id)
        return OutlineWorkbenchPayload(
            novel_id=novel_id,
            outline_type=outline_type,
            outline_ref=outline_ref,
            session_id=outline_session.id,
            outline_items=self.build_outline_items(state.checkpoint_data or {}),
            context_window=context_window,
        )

    def build_outline_items(self, checkpoint_data: dict[str, Any]) -> list[OutlineItemSummary]:
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
        context_window = await self._build_context_window(outline_session.id)
        optimize_result = await self._optimize_outline(
            novel_id=novel_id,
            outline_type=outline_type,
            outline_ref=outline_ref,
            feedback=feedback,
            context_window=context_window,
        )

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
            },
        )
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

        outline_session = await self.outline_session_repo.get_or_create(
            novel_id=novel_id,
            outline_type=outline_type,
            outline_ref=outline_ref,
            status="active",
        )
        context_window = await self._build_context_window(outline_session.id)
        return OutlineMessagesResponse(
            session_id=outline_session.id,
            outline_type=outline_type,
            outline_ref=outline_ref,
            last_result_snapshot=context_window.last_result_snapshot,
            conversation_summary=context_window.conversation_summary,
            recent_messages=context_window.recent_messages,
        )

    async def _build_context_window(self, session_id: str, recent_limit: int = 6) -> OutlineContextWindow:
        outline_session = await self.outline_session_repo.get_by_id(session_id)
        if outline_session is None:
            raise ValueError(f"Outline session not found: {session_id}")

        recent_messages = await self.outline_message_repo.list_recent(session_id, limit=recent_limit)
        ordered_messages = [self._serialize_message(message) for message in reversed(recent_messages)]
        return OutlineContextWindow(
            last_result_snapshot=outline_session.last_result_snapshot,
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

        if outline_type == "synopsis":
            result = await self._optimize_synopsis(
                novel_id=novel_id,
                checkpoint=checkpoint,
                feedback=feedback,
                context_window=context_window,
            )
        elif outline_type == "volume":
            result = await self._optimize_volume(
                novel_id=novel_id,
                outline_ref=outline_ref,
                checkpoint=checkpoint,
                feedback=feedback,
                context_window=context_window,
            )
        else:
            raise ValueError(f"Unsupported outline type: {outline_type}")

        return {
            "content": result["content"],
            "result_snapshot": result["result_snapshot"],
            "conversation_summary": self._merge_conversation_summary(
                context_window.conversation_summary,
                feedback,
            ),
        }

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
    ) -> dict[str, Any]:
        current_snapshot = context_window.last_result_snapshot or checkpoint.get("synopsis_data")
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
        }

    async def _optimize_volume(
        self,
        *,
        novel_id: str,
        outline_ref: str,
        checkpoint: dict[str, Any],
        feedback: str,
        context_window: OutlineContextWindow,
    ) -> dict[str, Any]:
        synopsis_payload = checkpoint.get("synopsis_data")
        if not synopsis_payload:
            raise ValueError("Synopsis not found")

        synopsis = SynopsisData.model_validate(synopsis_payload)
        volume_number = self._parse_volume_number(outline_ref)
        if volume_number is None:
            raise ValueError(f"Invalid volume outline ref: {outline_ref}")

        planner = VolumePlannerAgent(self.session)
        world_snapshot = await planner._load_world_snapshot(novel_id) if volume_number > 1 else None
        plan_context = planner._build_plan_context(synopsis, world_snapshot)

        current_plan_payload = context_window.last_result_snapshot
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
        }

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
