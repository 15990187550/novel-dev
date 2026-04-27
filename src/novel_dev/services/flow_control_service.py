from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import NovelState
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.services.log_service import log_service


_CANCEL_REQUESTS: set[str] = set()


class FlowCancelledError(RuntimeError):
    """Raised when a user-requested flow stop is observed at a safe checkpoint."""


def request_cancel(novel_id: str) -> None:
    if novel_id:
        _CANCEL_REQUESTS.add(novel_id)


def clear_cancel_request(novel_id: str) -> None:
    if novel_id:
        _CANCEL_REQUESTS.discard(novel_id)


def is_cancel_requested(novel_id: str) -> bool:
    return bool(novel_id and novel_id in _CANCEL_REQUESTS)


def raise_if_cancelled_sync(novel_id: str) -> None:
    if is_cancel_requested(novel_id):
        raise FlowCancelledError("流程已停止")


class FlowControlService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.state_repo = NovelStateRepository(session)

    async def request_stop(self, novel_id: str) -> dict[str, Any]:
        state = await self.state_repo.get_state(novel_id)
        if not state:
            raise ValueError(f"Novel state not found for {novel_id}")

        request_cancel(novel_id)
        checkpoint = dict(state.checkpoint_data or {})
        checkpoint["flow_control"] = {
            "cancel_requested": True,
            "requested_at": datetime.utcnow().isoformat() + "Z",
            "reason": "user_requested",
        }
        await self.state_repo.save_checkpoint(
            novel_id,
            current_phase=state.current_phase,
            checkpoint_data=checkpoint,
            current_volume_id=state.current_volume_id,
            current_chapter_id=state.current_chapter_id,
        )
        log_service.add_log(
            novel_id,
            "FlowControl",
            "已请求停止当前流程",
            level="warning",
            event="flow.stop",
            status="stop_requested",
            node="flow_control",
            task="stop",
        )
        return {"novel_id": novel_id, "stop_requested": True}

    async def clear_stop(self, novel_id: str) -> None:
        clear_cancel_request(novel_id)
        state = await self.state_repo.get_state(novel_id)
        if not state:
            return
        checkpoint = dict(state.checkpoint_data or {})
        if checkpoint.pop("flow_control", None) is not None:
            await self.state_repo.save_checkpoint(
                novel_id,
                current_phase=state.current_phase,
                checkpoint_data=checkpoint,
                current_volume_id=state.current_volume_id,
                current_chapter_id=state.current_chapter_id,
            )

    async def is_cancel_requested(self, novel_id: str) -> bool:
        if is_cancel_requested(novel_id):
            return True
        result = await self.session.execute(
            select(NovelState.checkpoint_data).where(NovelState.novel_id == novel_id)
        )
        checkpoint = result.scalar_one_or_none() or {}
        flow_control = checkpoint.get("flow_control") if isinstance(checkpoint, dict) else {}
        return bool(flow_control and flow_control.get("cancel_requested"))

    async def raise_if_cancelled(self, novel_id: str) -> None:
        if await self.is_cancel_requested(novel_id):
            log_service.add_log(
                novel_id,
                "FlowControl",
                "流程已停止",
                level="warning",
                event="flow.stop",
                status="stopped",
                node="flow_control",
                task="stop",
            )
            raise FlowCancelledError("流程已停止")
