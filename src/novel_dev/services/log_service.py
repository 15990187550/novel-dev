from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from functools import wraps
import inspect
import asyncio
import time
from typing import Any, AsyncIterator, Callable

from sqlalchemy import delete, select

from novel_dev.db.engine import async_session_maker
from novel_dev.db.models import AgentLog


class LogService:
    _instance = None
    _buffers: dict[str, deque] = {}
    _listeners: dict[str, list[asyncio.Queue]] = {}
    _pending_tasks: set[asyncio.Task] = set()
    MAX_SIZE = 500
    RETENTION_DAYS = 7

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def add_log(
        self,
        novel_id: str,
        agent: str,
        message: str,
        level: str = "info",
        *,
        event: str | None = None,
        status: str | None = None,
        node: str | None = None,
        task: str | None = None,
        metadata: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ):
        source_filename = metadata.get("source_filename") if metadata else None
        if source_filename and source_filename not in message:
            message = f"{message}（文件: {source_filename}）"
        timestamp = datetime.utcnow()
        entry = {
            "timestamp": timestamp.isoformat() + "Z",
            "agent": agent,
            "message": message,
            "level": level,
        }
        if event is not None:
            entry["event"] = event
        if status is not None:
            entry["status"] = status
        if node is not None:
            entry["node"] = node
        if task is not None:
            entry["task"] = task
        if metadata is not None:
            entry["metadata"] = metadata
        if duration_ms is not None:
            entry["duration_ms"] = duration_ms
        self._schedule_persist(novel_id, entry, timestamp)
        buf = self._buffers.setdefault(novel_id, deque(maxlen=self.MAX_SIZE))
        buf.append(entry)
        for q in self._listeners.get(novel_id, []):
            try:
                q.put_nowait(entry)
            except asyncio.QueueFull:
                pass

    def _schedule_persist(self, novel_id: str, entry: dict[str, Any], timestamp: datetime) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self._persist_entry(novel_id, entry, timestamp))
        self._pending_tasks.add(task)
        task.add_done_callback(self._handle_persist_done)

    def _handle_persist_done(self, task: asyncio.Task) -> None:
        self._pending_tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _persist_entry(self, novel_id: str, entry: dict[str, Any], timestamp: datetime) -> None:
        async with async_session_maker() as session:
            session.add(AgentLog(
                novel_id=novel_id,
                timestamp=timestamp,
                agent=entry["agent"],
                message=entry["message"],
                level=entry["level"],
                event=entry.get("event"),
                status=entry.get("status"),
                node=entry.get("node"),
                task=entry.get("task"),
                meta=entry.get("metadata"),
                duration_ms=entry.get("duration_ms"),
            ))
            cutoff = timestamp - timedelta(days=self.RETENTION_DAYS)
            await session.execute(delete(AgentLog).where(AgentLog.timestamp < cutoff))
            await session.commit()

    async def flush_pending(self) -> None:
        if not self._pending_tasks:
            return
        await asyncio.gather(*list(self._pending_tasks), return_exceptions=True)

    def subscribe(self, novel_id: str) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=100)
        self._listeners.setdefault(novel_id, []).append(q)
        for entry in list(self._buffers.get(novel_id, [])):
            try:
                q.put_nowait(entry)
            except asyncio.QueueFull:
                break
        return q

    async def subscribe_with_history(self, novel_id: str) -> asyncio.Queue:
        await self.flush_pending()
        q = asyncio.Queue(maxsize=100)
        self._listeners.setdefault(novel_id, []).append(q)
        cutoff = datetime.utcnow() - timedelta(days=self.RETENTION_DAYS)
        async with async_session_maker() as session:
            result = await session.execute(
                select(AgentLog)
                .where(AgentLog.novel_id == novel_id, AgentLog.timestamp >= cutoff)
                .order_by(AgentLog.timestamp.desc(), AgentLog.id.desc())
                .limit(self.MAX_SIZE)
            )
            rows = list(result.scalars())[::-1]
            for row in rows:
                try:
                    q.put_nowait(self._row_to_entry(row))
                except asyncio.QueueFull:
                    break
        return q

    def _row_to_entry(self, row: AgentLog) -> dict[str, Any]:
        entry = {
            "timestamp": row.timestamp.isoformat() + "Z",
            "agent": row.agent,
            "message": row.message,
            "level": row.level,
        }
        if row.event is not None:
            entry["event"] = row.event
        if row.status is not None:
            entry["status"] = row.status
        if row.node is not None:
            entry["node"] = row.node
        if row.task is not None:
            entry["task"] = row.task
        if row.meta is not None:
            entry["metadata"] = row.meta
        if row.duration_ms is not None:
            entry["duration_ms"] = row.duration_ms
        return entry

    def unsubscribe(self, novel_id: str, q: asyncio.Queue):
        listeners = self._listeners.get(novel_id, [])
        if q in listeners:
            listeners.remove(q)

    def clear_memory(self, novel_id: str) -> None:
        self._buffers.pop(novel_id, None)
        for queue in self._listeners.get(novel_id, []):
            while not queue.empty():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break


log_service = LogService()


def _with_metadata_source_filename(message: str, metadata: dict[str, Any] | None = None) -> str:
    source_filename = metadata.get("source_filename") if metadata else None
    if source_filename and source_filename not in message:
        return f"{message}（文件: {source_filename}）"
    return message


@asynccontextmanager
async def agent_step(
    novel_id: str,
    agent: str,
    label: str,
    *,
    node: str | None = None,
    task: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AsyncIterator[None]:
    """Emit paired start/end logs for a frontend-visible agent workflow node."""
    if not novel_id:
        yield
        return
    from novel_dev.services.flow_control_service import raise_if_cancelled_sync

    raise_if_cancelled_sync(novel_id)
    start = time.perf_counter()
    log_service.add_log(
        novel_id,
        agent,
        _with_metadata_source_filename(f"{label}开始", metadata),
        event="agent.step",
        status="started",
        node=node,
        task=task,
        metadata=metadata,
    )
    try:
        yield
    except Exception as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        failure_metadata = dict(metadata or {})
        failure_metadata["error"] = f"{type(exc).__name__}: {exc}"
        log_service.add_log(
            novel_id,
            agent,
            _with_metadata_source_filename(f"{label}失败: {exc}", failure_metadata),
            level="error",
            event="agent.step",
            status="failed",
            node=node,
            task=task,
            metadata=failure_metadata,
            duration_ms=duration_ms,
        )
        raise
    else:
        raise_if_cancelled_sync(novel_id)
        duration_ms = int((time.perf_counter() - start) * 1000)
        log_service.add_log(
            novel_id,
            agent,
            _with_metadata_source_filename(f"{label}完成", metadata),
            event="agent.step",
            status="succeeded",
            node=node,
            task=task,
            metadata=metadata,
            duration_ms=duration_ms,
        )


def logged_agent_step(
    agent: str,
    label: str,
    *,
    node: str | None = None,
    task: str | None = None,
    novel_id_arg: str = "novel_id",
    metadata_builder: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
) -> Callable:
    """Decorate an async public agent entrypoint with frontend-visible lifecycle logs."""
    def decorator(func: Callable) -> Callable:
        signature = inspect.signature(func)

        @wraps(func)
        async def wrapper(*args, **kwargs):
            bound = signature.bind_partial(*args, **kwargs)
            novel_id = bound.arguments.get(novel_id_arg, "")
            metadata = metadata_builder(bound.arguments) if metadata_builder else None
            session = getattr(bound.arguments.get("self"), "session", None)
            if session is not None and novel_id:
                from novel_dev.services.flow_control_service import FlowControlService

                await FlowControlService(session).raise_if_cancelled(str(novel_id))
            async with agent_step(str(novel_id or ""), agent, label, node=node, task=task, metadata=metadata):
                result = await func(*args, **kwargs)
            if session is not None and novel_id:
                from novel_dev.services.flow_control_service import FlowControlService

                await FlowControlService(session).raise_if_cancelled(str(novel_id))
            return result

        return wrapper

    return decorator
