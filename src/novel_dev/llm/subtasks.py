from __future__ import annotations

import inspect
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal

SubtaskKind = Literal["retriever", "validator", "repairer"]
SubtaskHandler = Callable[[dict[str, Any]], Awaitable[Any] | Any]


@dataclass(frozen=True)
class SubtaskResult:
    kind: SubtaskKind
    name: str
    payload: Any
    duration_ms: int


@dataclass(frozen=True)
class RetrieverSubtask:
    name: str
    handler: SubtaskHandler


@dataclass(frozen=True)
class ValidatorSubtask:
    name: str
    handler: SubtaskHandler


@dataclass(frozen=True)
class RepairerSubtask:
    name: str
    handler: SubtaskHandler


class LightweightSubtaskOrchestrator:
    def __init__(
        self,
        *,
        retrievers: list[RetrieverSubtask] | None = None,
        validators: list[ValidatorSubtask] | None = None,
        repairers: list[RepairerSubtask] | None = None,
    ):
        self._retrievers = {task.name: task for task in retrievers or []}
        self._validators = {task.name: task for task in validators or []}
        self._repairers = {task.name: task for task in repairers or []}

    async def run_retriever(self, name: str, payload: dict[str, Any]) -> SubtaskResult:
        task = self._get(self._retrievers, name, "retriever")
        return await self._run("retriever", task.name, task.handler, payload)

    async def run_validator(self, name: str, payload: dict[str, Any]) -> SubtaskResult:
        task = self._get(self._validators, name, "validator")
        return await self._run("validator", task.name, task.handler, payload)

    async def run_repairer(self, name: str, payload: dict[str, Any]) -> SubtaskResult:
        task = self._get(self._repairers, name, "repairer")
        return await self._run("repairer", task.name, task.handler, payload)

    def _get(self, registry: dict[str, Any], name: str, kind: SubtaskKind) -> Any:
        task = registry.get(name)
        if task is None:
            raise KeyError(f"Unknown {kind} subtask: {name}")
        return task

    async def _run(
        self,
        kind: SubtaskKind,
        name: str,
        handler: SubtaskHandler,
        payload: dict[str, Any],
    ) -> SubtaskResult:
        started_at = time.perf_counter()
        result = handler(payload)
        if inspect.isawaitable(result):
            result = await result
        return SubtaskResult(
            kind=kind,
            name=name,
            payload=result,
            duration_ms=int((time.perf_counter() - started_at) * 1000),
        )
