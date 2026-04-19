from collections import deque
from datetime import datetime
import asyncio


class LogService:
    _instance = None
    _buffers: dict[str, deque] = {}
    _listeners: dict[str, list[asyncio.Queue]] = {}
    MAX_SIZE = 500

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def add_log(self, novel_id: str, agent: str, message: str, level: str = "info"):
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "agent": agent,
            "message": message,
            "level": level,
        }
        buf = self._buffers.setdefault(novel_id, deque(maxlen=self.MAX_SIZE))
        buf.append(entry)
        for q in self._listeners.get(novel_id, []):
            try:
                q.put_nowait(entry)
            except asyncio.QueueFull:
                pass

    def subscribe(self, novel_id: str) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=100)
        self._listeners.setdefault(novel_id, []).append(q)
        for entry in list(self._buffers.get(novel_id, [])):
            try:
                q.put_nowait(entry)
            except asyncio.QueueFull:
                break
        return q

    def unsubscribe(self, novel_id: str, q: asyncio.Queue):
        listeners = self._listeners.get(novel_id, [])
        if q in listeners:
            listeners.remove(q)


log_service = LogService()
