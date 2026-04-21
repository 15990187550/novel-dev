from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.outline_message_repo import OutlineMessageRepository
from novel_dev.repositories.outline_session_repo import OutlineSessionRepository
from novel_dev.schemas.outline_workbench import (
    OutlineContextWindow,
    OutlineItemSummary,
    OutlineMessagePayload,
    OutlineSubmitResponse,
    OutlineWorkbenchPayload,
)


class OutlineWorkbenchService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.novel_state_repo = NovelStateRepository(session)
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
    ) -> dict[str, Any]:
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
        return {
            "session_id": outline_session.id,
            "outline_type": outline_type,
            "outline_ref": outline_ref,
            "last_result_snapshot": context_window.last_result_snapshot,
            "conversation_summary": context_window.conversation_summary,
            "recent_messages": [message.model_dump() for message in context_window.recent_messages],
        }

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
        outline_type: str,
        outline_ref: str,
        feedback: str,
        context_window: OutlineContextWindow,
    ) -> dict[str, Any]:
        return {
            "content": f"[stub] 已记录对 {outline_type}:{outline_ref} 的反馈：{feedback}",
            "result_snapshot": context_window.last_result_snapshot,
            "conversation_summary": context_window.conversation_summary or feedback,
        }

    async def _write_result_snapshot(
        self,
        *,
        novel_id: str,
        outline_type: str,
        outline_ref: str,
        result_snapshot: Optional[dict[str, Any]],
    ) -> None:
        _ = (novel_id, outline_type, outline_ref, result_snapshot)

    def _serialize_message(self, message: Any) -> OutlineMessagePayload:
        return OutlineMessagePayload(
            id=message.id,
            role=message.role,
            message_type=message.message_type,
            content=message.content,
            meta=message.meta,
            created_at=message.created_at.isoformat() if message.created_at else None,
        )
