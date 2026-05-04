#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter


ROOT = Path(__file__).resolve().parents[1]


def load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()

from novel_dev.agents._llm_helpers import (  # noqa: E402
    _default_subtask_orchestrator,
    _build_orchestrated_retry_prompt,
    _structured_config_for_client,
)
from novel_dev.llm import llm_factory  # noqa: E402
from novel_dev.llm.models import ChatMessage, LLMResponse, LLMToolCall, TokenUsage  # noqa: E402
from novel_dev.llm.orchestrator import LLMToolSpec, OrchestratedLLM, OrchestratedTaskConfig  # noqa: E402
from novel_dev.schemas.context import LocationContext  # noqa: E402


@dataclass
class CallRecord:
    elapsed_ms: int
    prompt_chars: int
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    tool_calls: list[str] = field(default_factory=list)
    structured_payload: bool = False
    finish_reason: str | None = None


class MeteredClient:
    def __init__(self, inner: Any):
        self.inner = inner
        self.config = getattr(inner, "config", None)
        self.records: list[CallRecord] = []

    async def acomplete(self, messages, config=None) -> LLMResponse:
        started = time.perf_counter()
        prompt_chars = _messages_chars(messages)
        response = await self.inner.acomplete(messages, config=config)
        usage = response.usage
        self.records.append(
            CallRecord(
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                prompt_chars=prompt_chars,
                prompt_tokens=usage.prompt_tokens if usage else None,
                completion_tokens=usage.completion_tokens if usage else None,
                total_tokens=usage.total_tokens if usage else None,
                tool_calls=[call.name for call in response.tool_calls],
                structured_payload=response.structured_payload is not None,
                finish_reason=response.finish_reason,
            )
        )
        return response


def _messages_chars(messages: Any) -> int:
    if isinstance(messages, str):
        return len(messages)
    total = 0
    for message in messages:
        total += len(getattr(message, "content", "") or "")
    return total


def _usage_total(records: list[CallRecord]) -> dict[str, int | None]:
    keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    result: dict[str, int | None] = {}
    for key in keys:
        values = [getattr(record, key) for record in records]
        result[key] = sum(value for value in values if value is not None) if any(value is not None for value in values) else None
    return result


def build_scene_inputs() -> dict[str, Any]:
    long_location = (
        "青玄旧碑庭位于外门山腰，三面环松，地面由被雨水磨亮的青石铺成。"
        "庭心立着半截旧碑，碑面有细密因果纹，遇到陆照的道印气息会浮出暗金裂光。"
        "清晨雨雾未散，檀香从守碑小殿飘出，钟声被山谷折回，显得压抑而肃穆。"
        "旧碑南侧有一口封井，井沿刻着守碑禁令：不得以血触碑。"
    )
    return {
        "locations": [
            {
                "name": "青玄旧碑庭",
                "narrative": long_location * 6,
                "meta": {"weather": "雨后晨雾", "sound": "远钟回荡", "smell": "潮湿青苔与檀香"},
            }
        ],
        "entity_states": [
            {
                "name": "陆照",
                "type": "character",
                "state": (
                    "陆照刚取得因果道印，左掌有未愈裂纹，靠近旧碑时会发热。"
                    "他想查清父亲失踪与旧碑禁令的关系，但必须隐藏道印气息。"
                )
                * 5,
            },
            {
                "name": "守碑长老",
                "type": "character",
                "state": (
                    "守碑长老表面守规，实际知道旧碑曾吞没陆照父亲。"
                    "他会用铜铃试探陆照是否携带道印，并阻止他以血触碑。"
                )
                * 5,
            },
            {
                "name": "青衣少女",
                "type": "character",
                "state": (
                    "青衣少女藏在碑庭侧廊，手中有裂纹玉牌。"
                    "她认得陆照掌心纹路，却暂时不愿暴露身份。"
                )
                * 5,
            },
        ],
        "timeline_events": [
            {"tick": 7, "narrative": "陆照在前章取得因果道印，掌心留下灼痕。"},
            {"tick": 8, "narrative": "守碑长老夜里封闭旧碑庭，只允许内门弟子靠近。"},
            {"tick": 9, "narrative": "青衣少女在雨中递出裂纹玉牌，又立刻消失。"},
        ],
        "foreshadowings": [
            {
                "id": "fs_old_tablet_blood_ban",
                "content": "旧碑禁令写着不得以血触碑，但碑底暗纹只有血能点亮。",
            },
            {
                "id": "fs_jade_crack",
                "content": "裂纹玉牌与陆照掌心的因果道印纹路完全吻合。",
            },
        ],
    }


def build_catalog(scene_inputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "locations": [
            {"name": item.get("name"), "has_narrative": bool(item.get("narrative"))}
            for item in scene_inputs.get("locations", [])
        ],
        "entities": [
            {"name": item.get("name"), "type": item.get("type"), "has_state": bool(item.get("state"))}
            for item in scene_inputs.get("entity_states", [])
        ],
        "timeline_event_count": len(scene_inputs.get("timeline_events", [])),
        "foreshadowing_ids": [item.get("id") for item in scene_inputs.get("foreshadowings", [])],
        "required_terms": ["因果道印", "裂纹玉牌"],
        "tool_hint": (
            "目录只给出摘要。需要具体人物状态、物品线索或旧碑细节时，"
            "优先用批量工具一次查询同类数据：get_context_location_details / "
            "get_context_entity_states / get_context_foreshadowing_details。"
            "需要时间线时再调用 get_context_timeline_events。"
            "最多查询 3 个最缺的细节。"
        ),
    }


def build_prompt(scene_context: dict[str, Any]) -> str:
    return (
        "你是一位导演，正在为下一幕戏撰写场景说明。请根据以下信息，写一段 200-300 字的场景镜头描述。"
        "这段文字将被直接交给小说家作为写作参考，所以请用具体、可感知的细节，不要抽象概括。必须包含：\n"
        "- 空间环境（地点、光线、声音、气味、天气等感官细节）\n"
        "- 在场人物：陆照、守碑长老、青衣少女\n"
        "- 物品线索：因果道印、裂纹玉牌\n"
        "- 旧碑禁令与上一场景的衔接\n"
        "返回严格 JSON 格式：\n"
        "{\n"
        '  "current": "当前主要地点名称",\n'
        '  "parent": "上级地点/区域（如有）",\n'
        '  "narrative": "完整的场景镜头描述（200-300字）"\n'
        "}\n\n"
        f"场景上下文：{json.dumps(scene_context, ensure_ascii=False)}\n"
    )


def build_tools(scene_inputs: dict[str, Any], max_return_chars: int) -> list[LLMToolSpec]:
    def requested_values(args: dict[str, Any], key: str, fallback_key: str) -> list[str]:
        raw_values = args.get(key)
        if raw_values is None:
            raw_values = args.get(fallback_key)
        if isinstance(raw_values, str):
            raw_values = [raw_values]
        if not isinstance(raw_values, list):
            raw_values = []
        values = []
        for raw in raw_values:
            value = str(raw or "").strip()
            if value and value not in values:
                values.append(value)
        return values[:5]

    def collect(items: list[dict[str, Any]], key: str, values: list[str]) -> dict[str, Any]:
        found = []
        missing = []
        for value in values:
            match = next((item for item in items if item.get(key) == value), None)
            if match:
                found.append(match)
            else:
                missing.append(value)
        return {"items": found, "missing": missing, "requested": values}

    async def get_context_location_details(args: dict[str, Any]) -> dict[str, Any]:
        return collect(scene_inputs["locations"], "name", requested_values(args, "names", "name"))

    async def get_context_entity_states(args: dict[str, Any]) -> dict[str, Any]:
        return collect(scene_inputs["entity_states"], "name", requested_values(args, "names", "name"))

    async def get_context_foreshadowing_details(args: dict[str, Any]) -> dict[str, Any]:
        return collect(scene_inputs["foreshadowings"], "id", requested_values(args, "ids", "id"))

    async def get_context_timeline_events(args: dict[str, Any]) -> dict[str, Any]:
        limit = int(args.get("limit") or 3)
        return {"events": scene_inputs["timeline_events"][:limit]}

    common = {"timeout_seconds": 5, "max_return_chars": max_return_chars}
    return [
        LLMToolSpec(
            name="get_context_location_details",
            description="Read up to 5 location details by exact names.",
            input_schema={
                "type": "object",
                "properties": {"names": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5}},
                "required": ["names"],
            },
            handler=get_context_location_details,
            **common,
        ),
        LLMToolSpec(
            name="get_context_entity_states",
            description="Read up to 5 entity states by exact names.",
            input_schema={
                "type": "object",
                "properties": {"names": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5}},
                "required": ["names"],
            },
            handler=get_context_entity_states,
            **common,
        ),
        LLMToolSpec(
            name="get_context_foreshadowing_details",
            description="Read up to 5 foreshadowing details by exact ids.",
            input_schema={
                "type": "object",
                "properties": {"ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5}},
                "required": ["ids"],
            },
            handler=get_context_foreshadowing_details,
            **common,
        ),
        LLMToolSpec(
            name="get_context_timeline_events",
            description="Read recent timeline events.",
            input_schema={
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 5}},
            },
            handler=get_context_timeline_events,
            **common,
        ),
    ]


def score_payload(payload: LocationContext) -> dict[str, Any]:
    narrative = payload.narrative or ""
    required = ["陆照", "守碑长老", "青衣少女", "因果道印", "裂纹玉牌"]
    detail_terms = ["旧碑禁令", "以血触碑", "檀香", "掌心", "铜铃"]
    return {
        "narrative_chars": len(narrative),
        "required_hits": {term: term in narrative for term in required},
        "detail_hits": {term: term in narrative for term in detail_terms},
        "hit_count": sum(term in narrative for term in required + detail_terms),
        "narrative_preview": narrative[:240],
    }


async def run_old(prompt: str) -> dict[str, Any]:
    client = MeteredClient(llm_factory.get("ContextAgent", task="build_scene_context"))
    config = _structured_config_for_client(client, "build_scene_context", LocationContext)
    if config is None:
        raise RuntimeError("missing structured config")
    started = time.perf_counter()
    response = await client.acomplete([ChatMessage(role="user", content=prompt)], config=config)
    payload_raw = response.structured_payload
    if payload_raw is None:
        payload_raw = json.loads(response.text)
    payload = TypeAdapter(LocationContext).validate_python(payload_raw)
    return {
        "ok": True,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "initial_prompt_chars": len(prompt),
        "api_calls": [record.__dict__ for record in client.records],
        "usage_total": _usage_total(client.records),
        "tool_call_count": sum(len(record.tool_calls) for record in client.records),
        "score": score_payload(payload),
    }


async def run_new(
    prompt: str,
    scene_inputs: dict[str, Any],
    max_tool_calls: int,
    max_return_chars: int,
    max_retries: int = 3,
) -> dict[str, Any]:
    client = MeteredClient(llm_factory.get("ContextAgent", task="build_scene_context"))
    config = _structured_config_for_client(client, "build_scene_context", LocationContext)
    if config is None:
        raise RuntimeError("missing structured config")
    task_config = OrchestratedTaskConfig(
        tool_allowlist=[
            "get_context_location_details",
            "get_context_entity_states",
            "get_context_foreshadowing_details",
            "get_context_timeline_events",
        ],
        max_tool_calls=max_tool_calls,
        tool_timeout_seconds=5,
        max_tool_result_chars=max_return_chars,
        enable_subtasks=True,
        validator_subtask="location_context_quality",
        repairer_subtask="schema_repair",
    )
    orchestrator = OrchestratedLLM(
        client=client,
        base_config=config,
        response_schema=LocationContext,
        response_tool_name=config.response_tool_name or "emit_build_scene_context",
        tools=build_tools(scene_inputs, max_return_chars),
        task_config=task_config,
        subtask_orchestrator=_default_subtask_orchestrator("ContextAgent", "build_scene_context", task_config),
    )
    started = time.perf_counter()
    current_prompt = prompt
    retry_count = 0
    for attempt in range(max_retries):
        try:
            payload = await orchestrator.run(
                current_prompt,
                agent_name="ContextAgent",
                task="build_scene_context",
                novel_id="measure-ab",
            )
            break
        except Exception as exc:
            if attempt >= max_retries - 1:
                return {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "initial_prompt_chars": len(prompt),
                    "retry_count": retry_count,
                    "api_calls": [record.__dict__ for record in client.records],
                    "usage_total": _usage_total(client.records),
                    "tool_call_count": sum(len(record.tool_calls) for record in client.records),
                }
            retry_count += 1
            current_prompt = _build_orchestrated_retry_prompt(prompt, exc)
    else:
        raise RuntimeError("new chain failed without an exception")
    return {
        "ok": True,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "initial_prompt_chars": len(prompt),
        "retry_count": retry_count,
        "api_calls": [record.__dict__ for record in client.records],
        "usage_total": _usage_total(client.records),
        "tool_call_count": sum(len(record.tool_calls) for record in client.records),
        "score": score_payload(payload),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--max-tool-calls", type=int, default=4)
    parser.add_argument("--max-return-chars", type=int, default=1600)
    args = parser.parse_args()

    scene_inputs = build_scene_inputs()
    old_prompt = build_prompt(scene_inputs)
    new_prompt = build_prompt(build_catalog(scene_inputs))
    results = []
    for index in range(args.runs):
        item: dict[str, Any] = {"run": index + 1}
        try:
            item["old"] = await run_old(old_prompt)
        except Exception as exc:
            item["old"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "initial_prompt_chars": len(old_prompt)}
        try:
            item["new"] = await run_new(new_prompt, scene_inputs, args.max_tool_calls, args.max_return_chars)
        except Exception as exc:
            item["new"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "initial_prompt_chars": len(new_prompt)}
        results.append(item)
    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
