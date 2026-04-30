import asyncio
import json
import re
import time
from typing import Any, Callable, TypeVar, get_origin

from pydantic import TypeAdapter, ValidationError

from novel_dev.llm import llm_factory
from novel_dev.llm.models import ChatMessage, StructuredOutputConfig, TaskConfig
from novel_dev.services.flow_control_service import raise_if_cancelled_sync
from novel_dev.services.log_service import log_service

T = TypeVar("T")
StructuredNormalizer = Callable[[Any, Exception | None], Any]

_STRUCTURED_NORMALIZERS: dict[tuple[str, str], StructuredNormalizer] = {}


class StructuredPayloadMissingError(ValueError):
    pass


def register_structured_normalizer(agent_name: str, task: str, normalizer: StructuredNormalizer) -> None:
    _STRUCTURED_NORMALIZERS[(agent_name, task)] = normalizer


def _get_structured_normalizer(agent_name: str, task: str) -> StructuredNormalizer | None:
    return _STRUCTURED_NORMALIZERS.get((agent_name, task))


def _strip_markdown(text: str) -> str:
    """Strip markdown code blocks and extract the first JSON object or array."""
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```", "", text)
    text = text.strip()

    start_obj = text.find("{")
    start_arr = text.find("[")
    starts = [pos for pos in (start_obj, start_arr) if pos != -1]
    if not starts:
        return text

    start = min(starts)
    brace_count = 0
    in_string = False
    escape_next = False
    for i, ch in enumerate(text[start:], start):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "[{":
            brace_count += 1
        elif ch in "]}":
            brace_count -= 1
            if brace_count == 0:
                return text[start : i + 1]
    return text


def _stringify_structured_value(value: Any) -> str:
    if isinstance(value, dict):
        parts = []
        for key, val in value.items():
            if isinstance(val, (dict, list)):
                parts.append(f"{key}: {_stringify_structured_value(val)}")
            else:
                parts.append(f"{key}: {val}")
        return "\n".join(parts)
    if isinstance(value, list):
        return "\n".join(_stringify_structured_value(item) if isinstance(item, (dict, list)) else str(item) for item in value)
    return str(value)


def _build_json_repair_prompt(original_prompt: str, bad_output: str, error: Exception) -> str:
    return (
        "你上一次返回的内容不是合法 JSON。请在不改变原始语义的前提下，"
        "把它修复成一个可被 json.loads 解析的 JSON 值。\n\n"
        "要求:\n"
        "1. 只返回 JSON，本体之外不要有任何解释、Markdown 或代码块。\n"
        "2. 保留原有字段与内容语义，不要新增需求中未要求的字段。\n"
        "3. 修复所有未转义双引号、缺失逗号、缺失括号、尾部截断等 JSON 语法问题。\n\n"
        f"原始任务:\n{original_prompt}\n\n"
        f"JSON 解析失败:\n{error}\n\n"
        f"待修复内容:\n{bad_output}"
    )


def _build_json_regenerate_prompt(original_prompt: str, bad_output: str, error: Exception) -> str:
    return (
        "你上一次返回为空，或返回的内容根本不是 JSON。"
        "请重新完成原始任务，并且只返回一个合法 JSON 值。\n\n"
        "要求:\n"
        "1. 只返回 JSON，本体之外不要有任何解释、Markdown 或代码块。\n"
        "2. 必须完整返回，不能留空，不能只写省略内容。\n"
        "3. 字段必须严格符合原始任务要求。\n\n"
        f"原始任务:\n{original_prompt}\n\n"
        f"上次错误:\n{error}\n\n"
        f"上次返回:\n{bad_output or '[EMPTY]'}"
    )


def _should_regenerate_json(bad_output: str) -> bool:
    stripped = (bad_output or "").strip()
    if not stripped:
        return True
    return "{" not in stripped and "[" not in stripped


def _should_regenerate_for_error(error: Exception, bad_output: str) -> bool:
    if _should_regenerate_json(bad_output):
        return True
    if isinstance(error, json.JSONDecodeError) and "Unterminated string" in str(error):
        return True
    return False


def _tool_name_for_task(task: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", task).strip("_").lower()
    return f"emit_{normalized or 'payload'}"


def _is_list_model(model_cls: Any) -> bool:
    return get_origin(model_cls) is list


def _simplify_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    defs = schema.get("$defs", {})

    def simplify(value: Any) -> Any:
        if isinstance(value, list):
            return [simplify(item) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            ref = value["$ref"]
            prefix = "#/$defs/"
            if isinstance(ref, str) and ref.startswith(prefix):
                target = defs.get(ref.removeprefix(prefix), {})
                return simplify(target)
        simplified = {}
        for key, item in value.items():
            if key in {"$defs", "title", "default", "examples"}:
                continue
            simplified[key] = simplify(item)
        return simplified

    return simplify(schema)


def _build_response_json_schema(model_cls: Any) -> tuple[dict[str, Any], bool]:
    schema = _simplify_json_schema(TypeAdapter(model_cls).json_schema())
    if _is_list_model(model_cls) or schema.get("type") == "array":
        return {
            "type": "object",
            "properties": {"items": schema},
            "required": ["items"],
            "additionalProperties": False,
        }, True
    return schema, False


def _structured_config_for_client(client: Any, task: str, model_cls: Any) -> TaskConfig | None:
    base_config = getattr(client, "config", None)
    if not isinstance(base_config, TaskConfig):
        return None
    schema, wrap_array = _build_response_json_schema(model_cls)
    structured_output = base_config.structured_output or StructuredOutputConfig()
    structured_output = structured_output.model_copy(
        update={
            "schema_name": structured_output.schema_name or _tool_name_for_task(task),
            "wrap_array": wrap_array,
        }
    )
    if structured_output.mode == "json_text":
        return base_config.model_copy(
            update={
                "structured_output": structured_output,
                "response_tool_name": None,
                "response_json_schema": None,
            }
        )
    schema_name = structured_output.schema_name
    if schema_name == "emit_payload":
        schema_name = _tool_name_for_task(task)
        structured_output = structured_output.model_copy(update={"schema_name": schema_name})
    return base_config.model_copy(
        update={
            "structured_output": structured_output,
            "response_tool_name": schema_name,
            "response_json_schema": schema,
        }
    )


def _text_fallback_structured_config(config: TaskConfig) -> TaskConfig:
    structured_output = config.structured_output or StructuredOutputConfig()
    structured_output = structured_output.model_copy(update={"mode": "json_text"})
    return config.model_copy(
        update={
            "structured_output": structured_output,
            "response_tool_name": None,
            "response_json_schema": None,
        }
    )


def _diagnostic_json_error_message(error: Exception, bad_output: str) -> str:
    return (
        f"{error} | raw_len={len(bad_output or '')} | "
        f"raw_tail={(bad_output or '')[-300:]}"
    )


def _is_empty_structured_payload(payload: Any) -> bool:
    return isinstance(payload, dict) and not payload


def _validation_missing_paths(error: Exception) -> list[str]:
    if not isinstance(error, ValidationError):
        return []
    paths = []
    for item in error.errors():
        if item.get("type") != "missing":
            continue
        loc = item.get("loc") or ()
        paths.append(".".join(str(part) for part in loc))
    return paths


def _classify_parse_error(error: Exception, bad_output: str) -> str:
    if isinstance(error, StructuredPayloadMissingError):
        return "missing_tool_payload"
    if isinstance(error, json.JSONDecodeError):
        if "{" not in (bad_output or "") and "[" not in (bad_output or ""):
            return "missing_tool_payload"
        return "empty_response" if not (bad_output or "").strip() else "json_decode_error"
    if isinstance(error, ValidationError):
        return "validation_missing_fields" if _validation_missing_paths(error) else "schema_shape_mismatch"
    return "parse_error"


def _normalize_payload(
    agent_name: str,
    task: str,
    payload: Any,
    error: Exception | None,
) -> tuple[Any, bool]:
    normalizer = _get_structured_normalizer(agent_name, task)
    if normalizer is None:
        return payload, False
    normalized = normalizer(payload, error)
    return normalized, normalized is not payload


def _fallback_driver_for_parse(client: Any) -> tuple[Any, TaskConfig | None] | None:
    fallback = getattr(client, "fallback", None)
    fallback_config = getattr(client, "fallback_config", None)
    if fallback is None or fallback_config is None:
        return None
    return fallback, fallback_config


def _preview_text(value: str | None, limit: int = 300) -> str:
    text = (value or "").replace("\r", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _prompt_metadata(prompt: str, *, limit: int = 300) -> dict[str, Any]:
    return {
        "prompt_chars": len(prompt or ""),
        "prompt_preview": _preview_text(prompt, limit),
    }


def _response_metadata(response: Any | None, *, output_source: str | None = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "output_source": output_source,
        "finish_reason": getattr(response, "finish_reason", None) if response is not None else None,
        "usage": None,
    }
    usage = getattr(response, "usage", None) if response is not None else None
    if usage is not None:
        metadata["usage"] = usage.model_dump() if hasattr(usage, "model_dump") else usage
    text = getattr(response, "text", "") if response is not None else ""
    metadata["raw_len"] = len(text or "")
    if text:
        metadata["raw_preview"] = _preview_text(text, 300)
    return metadata


def _parse_failure_metadata(error: Exception, raw_output: str, *, source: str | None = None) -> dict[str, Any]:
    return {
        "error": str(error),
        "error_kind": _classify_parse_error(error, raw_output),
        "missing_paths": _validation_missing_paths(error),
        "raw_len": len(raw_output or ""),
        "raw_tail": _preview_text((raw_output or "")[-300:], 300),
        "output_source": source,
    }


def _log_llm_event(
    novel_id: str,
    agent_name: str,
    task: str,
    message: str,
    *,
    status: str,
    node: str = "llm_call",
    level: str = "info",
    metadata: dict[str, Any] | None = None,
    duration_ms: int | None = None,
) -> None:
    if not novel_id:
        return
    source_filename = metadata.get("source_filename") if metadata else None
    if source_filename and source_filename not in message:
        message = f"{message}（文件: {source_filename}）"
    log_service.add_log(
        novel_id,
        agent_name,
        message,
        level=level,
        event="agent.llm",
        status=status,
        node=node,
        task=task,
        metadata=metadata,
        duration_ms=duration_ms,
    )


async def _await_llm_response_with_progress(
    awaitable: Any,
    *,
    novel_id: str,
    agent_name: str,
    task: str,
    attempt_metadata: dict[str, Any],
    started_at: float,
    interval_seconds: int = 15,
) -> Any:
    response_task = asyncio.create_task(awaitable)
    heartbeat = 0
    try:
        while True:
            done, _ = await asyncio.wait({response_task}, timeout=interval_seconds)
            if response_task in done:
                return await response_task
            heartbeat += 1
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            _log_llm_event(
                novel_id,
                agent_name,
                task,
                f"{task} 等待模型响应中({elapsed_ms // 1000}s)",
                status="waiting",
                metadata={
                    **attempt_metadata,
                    "heartbeat": heartbeat,
                    "elapsed_ms": elapsed_ms,
                },
                duration_ms=elapsed_ms,
            )
    except BaseException:
        response_task.cancel()
        raise


def _repair_truncated_json(text: str) -> str | None:
    stripped = (text or "").strip()
    if not stripped:
        return None

    start_obj = stripped.find("{")
    start_arr = stripped.find("[")
    starts = [pos for pos in (start_obj, start_arr) if pos != -1]
    if not starts:
        return None

    candidate = stripped[min(starts):]
    stack: list[str] = []
    in_string = False
    escape_next = False

    for ch in candidate:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]":
            if stack and stack[-1] == ch:
                stack.pop()

    repaired = candidate
    if escape_next:
        return None
    if in_string:
        # A payload cut off inside a string has already lost content.
        # Prefer asking the model to regenerate instead of silently truncating semantics.
        return None
    repaired += "".join(reversed(stack))
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    return repaired if repaired != candidate else None


def coerce_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return _stringify_structured_value(value)


def coerce_to_str_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [coerce_to_text(item) for item in value]
    if isinstance(value, dict):
        return [
            f"{key}: {_stringify_structured_value(item)}" if isinstance(item, (dict, list)) else f"{key}: {item}"
            for key, item in value.items()
        ]
    return [coerce_to_text(value)]


async def call_and_parse(
    agent_name: str,
    task: str,
    prompt: str,
    parser: Callable[[str], T],
    max_retries: int = 3,
    novel_id: str = "",
    context_metadata: dict[str, Any] | None = None,
    config_agent_name: str | None = None,
    config_task: str | None = None,
    client: Any | None = None,
) -> T:
    context_metadata = context_metadata or {}
    config_agent_name = config_agent_name or agent_name
    config_task = config_task or task
    client = client or llm_factory.get(config_agent_name, task=config_task)
    last_error = None
    current_prompt = prompt
    for attempt in range(max_retries):
        raise_if_cancelled_sync(novel_id)
        attempt_metadata = {
            "attempt": attempt + 1,
            "max_retries": max_retries,
            "structured": False,
            **_prompt_metadata(current_prompt),
            **context_metadata,
        }
        started_at = time.perf_counter()
        _log_llm_event(
            novel_id,
            agent_name,
            task,
            f"{task} 调用模型(第 {attempt + 1}/{max_retries} 次)",
            status="started",
            metadata=attempt_metadata,
        )
        try:
            response = await _await_llm_response_with_progress(
                client.acomplete([ChatMessage(role="user", content=current_prompt)]),
                novel_id=novel_id,
                agent_name=agent_name,
                task=task,
                attempt_metadata=attempt_metadata,
                started_at=started_at,
            )
            cleaned = _strip_markdown(response.text)
            try:
                result = parser(cleaned)
            except (ValidationError, json.JSONDecodeError):
                repaired = _repair_truncated_json(cleaned)
                if repaired:
                    result = parser(repaired)
                else:
                    raise
            _log_llm_event(
                novel_id,
                agent_name,
                task,
                f"{task} 成功",
                status="succeeded",
                node="llm_parse",
                metadata={**attempt_metadata, **_response_metadata(response, output_source="text")},
                duration_ms=int((time.perf_counter() - started_at) * 1000),
            )
            raise_if_cancelled_sync(novel_id)
            return result
        except (ValidationError, json.JSONDecodeError) as exc:
            last_error = exc
            if _should_regenerate_for_error(exc, response.text):
                current_prompt = _build_json_regenerate_prompt(prompt, response.text, exc)
            else:
                current_prompt = _build_json_repair_prompt(prompt, response.text, exc)
            failure_metadata = {**attempt_metadata, **_parse_failure_metadata(exc, response.text, source="text")}
            _log_llm_event(
                novel_id,
                agent_name,
                task,
                f"{task} 解析失败(第 {attempt + 1}/{max_retries} 次): {exc}",
                status="failed",
                node="llm_parse",
                level="warning",
                metadata=failure_metadata,
                duration_ms=int((time.perf_counter() - started_at) * 1000),
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(1 * (attempt + 1))
    _log_llm_event(
        novel_id,
        agent_name,
        task,
        f"{task} 解析失败，已达最大重试次数: {last_error}",
        status="failed",
        node="llm_parse",
        level="error",
        metadata={
            "max_retries": max_retries,
            **_prompt_metadata(current_prompt),
            **context_metadata,
            **(_parse_failure_metadata(last_error, "", source="text") if last_error else {}),
        },
    )
    raise RuntimeError(
        f"LLM parse failed after {max_retries} retries for {agent_name}/{task}: {last_error}"
    ) from last_error


async def call_and_parse_model(
    agent_name: str,
    task: str,
    prompt: str,
    model_cls: Any,
    max_retries: int = 3,
    novel_id: str = "",
    context_metadata: dict[str, Any] | None = None,
    config_agent_name: str | None = None,
    config_task: str | None = None,
) -> Any:
    context_metadata = context_metadata or {}
    config_agent_name = config_agent_name or agent_name
    config_task = config_task or task
    adapter = TypeAdapter(model_cls)

    def validate_payload(payload: Any, *, source: str, last_error: Exception | None = None):
        if _is_list_model(model_cls) and isinstance(payload, dict):
            if "items" in payload:
                payload = payload["items"]
            else:
                list_values = [value for value in payload.values() if isinstance(value, list)]
                if len(list_values) == 1:
                    payload = list_values[0]
        try:
            return adapter.validate_python(payload)
        except ValidationError as exc:
            normalized, changed = _normalize_payload(agent_name, task, payload, exc)
            if not changed:
                raise
            result = adapter.validate_python(normalized)
            _log_llm_event(
                novel_id,
                agent_name,
                task,
                f"{task} 输出已归一化后通过校验",
                status="succeeded",
                node="llm_normalize",
                metadata={
                    **context_metadata,
                    "source": source,
                    "error_kind": _classify_parse_error(exc, ""),
                    "missing_paths": _validation_missing_paths(exc),
                },
            )
            return result

    def parser(text: str):
        payload = json.loads(text)
        return validate_payload(payload, source="text")

    def payload_parser(payload: Any):
        return validate_payload(payload, source="tool")

    client = llm_factory.get(config_agent_name, task=config_task)
    structured_config = _structured_config_for_client(client, task, model_cls)
    if structured_config is not None:
        last_error = None
        current_prompt = prompt
        active_client = client
        active_structured_config = structured_config
        fallback_started = False
        text_fallback_started = False
        attempt = 0
        while attempt < max_retries:
            raise_if_cancelled_sync(novel_id)
            response = None
            attempt_metadata = {
                "attempt": attempt + 1,
                "max_retries": max_retries,
                "structured": True,
                "tool_name": active_structured_config.response_tool_name,
                "schema_name": (
                    active_structured_config.structured_output.schema_name
                    if active_structured_config.structured_output else None
                ),
                "structured_mode": (
                    active_structured_config.structured_output.mode
                    if active_structured_config.structured_output else None
                ),
                "json_text_fallback": text_fallback_started,
                "fallback": fallback_started,
                **_prompt_metadata(current_prompt),
                **context_metadata,
            }
            started_at = time.perf_counter()
            _log_llm_event(
                novel_id,
                agent_name,
                task,
                f"{task} 调用模型(第 {attempt + 1}/{max_retries} 次)",
                status="started",
                metadata=attempt_metadata,
            )
            try:
                response = await _await_llm_response_with_progress(
                    active_client.acomplete(
                        [ChatMessage(role="user", content=current_prompt)],
                        config=active_structured_config,
                    ),
                    novel_id=novel_id,
                    agent_name=agent_name,
                    task=task,
                    attempt_metadata=attempt_metadata,
                    started_at=started_at,
                )
                if response.structured_payload is not None:
                    result = payload_parser(response.structured_payload)
                    output_source = "tool"
                else:
                    cleaned = _strip_markdown(response.text)
                    if not cleaned.strip():
                        raise StructuredPayloadMissingError(
                            f"{task} did not return structured tool payload or JSON text"
                        )
                    result = parser(cleaned)
                    output_source = "text"
                _log_llm_event(
                    novel_id,
                    agent_name,
                    task,
                    f"{task} 成功",
                    status="succeeded",
                    node="llm_parse",
                    metadata={
                        **attempt_metadata,
                        "used_structured_payload": response.structured_payload is not None,
                        **_response_metadata(response, output_source=output_source),
                    },
                    duration_ms=int((time.perf_counter() - started_at) * 1000),
                )
                raise_if_cancelled_sync(novel_id)
                return result
            except (ValidationError, json.JSONDecodeError) as exc:
                last_error = exc
                bad_output = response.text if response is not None else ""
                error_kind = _classify_parse_error(exc, bad_output)
                if _should_regenerate_for_error(exc, bad_output):
                    current_prompt = _build_json_regenerate_prompt(prompt, bad_output, exc)
                else:
                    current_prompt = _build_json_repair_prompt(prompt, bad_output, exc)
                _log_llm_event(
                    novel_id,
                    agent_name,
                    task,
                    f"{task} 解析失败(第 {attempt + 1}/{max_retries} 次): "
                    f"{_diagnostic_json_error_message(exc, bad_output)}",
                    status="failed",
                    node="llm_parse",
                    level="warning",
                    metadata={
                        **attempt_metadata,
                        **_parse_failure_metadata(
                            exc,
                            bad_output,
                            source="tool" if response is not None and response.structured_payload is not None else "text",
                        ),
                        "finish_reason": response.finish_reason if response is not None else None,
                        "usage": response.usage.model_dump() if response is not None and response.usage else None,
                    },
                    duration_ms=int((time.perf_counter() - started_at) * 1000),
                )
                if (
                    isinstance(exc, ValidationError)
                    and response is not None
                    and _is_empty_structured_payload(response.structured_payload)
                    and not text_fallback_started
                    and active_structured_config.response_tool_name
                    and (active_structured_config.structured_output or StructuredOutputConfig()).fallback_to_text
                ):
                    missing_error = StructuredPayloadMissingError(
                        f"{task} returned an empty structured tool payload"
                    )
                    active_structured_config = _text_fallback_structured_config(active_structured_config)
                    current_prompt = _build_json_regenerate_prompt(prompt, bad_output, missing_error)
                    text_fallback_started = True
                    attempt = 0
                    _log_llm_event(
                        novel_id,
                        agent_name,
                        task,
                        f"{task} 结构化 tool 输出为空，降级为 JSON 文本模式重试",
                        status="started",
                        node="llm_text_fallback",
                        level="warning",
                        metadata={
                            **context_metadata,
                            **_prompt_metadata(current_prompt),
                            "error_kind": "empty_tool_payload",
                            "error": str(exc),
                            "raw_len": len(bad_output or ""),
                            "raw_tail": _preview_text((bad_output or "")[-300:], 300),
                        },
                    )
                    continue
                attempt += 1
                if attempt >= max_retries and not fallback_started:
                    fallback_info = _fallback_driver_for_parse(client)
                    if fallback_info is not None:
                        fallback_client, _ = fallback_info
                        fallback_structured_config = _structured_config_for_client(fallback_client, task, model_cls)
                        if fallback_structured_config is not None:
                            _log_llm_event(
                                novel_id,
                                agent_name,
                                task,
                                f"{task} 主模型解析失败，切换备用模型重试",
                                status="started",
                                node="llm_fallback",
                                level="warning",
                                metadata={
                                    **context_metadata,
                                    **_prompt_metadata(current_prompt),
                                    "error_kind": error_kind,
                                    "error": str(exc),
                                },
                            )
                            active_client = fallback_client
                            active_structured_config = fallback_structured_config
                            current_prompt = prompt
                            fallback_started = True
                            attempt = 0
                            continue
                if attempt < max_retries:
                    await asyncio.sleep(1 * (attempt + 1))
            except StructuredPayloadMissingError as exc:
                last_error = exc
                bad_output = response.text if response is not None else ""
                error_kind = _classify_parse_error(exc, bad_output)
                current_prompt = _build_json_regenerate_prompt(prompt, bad_output, exc)
                _log_llm_event(
                    novel_id,
                    agent_name,
                    task,
                    f"{task} 结构化输出缺失(第 {attempt + 1}/{max_retries} 次): "
                    f"{_diagnostic_json_error_message(exc, bad_output)}",
                    status="failed",
                    node="llm_parse",
                    level="warning",
                    metadata={
                        **attempt_metadata,
                        **_parse_failure_metadata(exc, bad_output, source="missing_tool"),
                        "finish_reason": response.finish_reason if response is not None else None,
                        "usage": response.usage.model_dump() if response is not None and response.usage else None,
                    },
                    duration_ms=int((time.perf_counter() - started_at) * 1000),
                )
                if (
                    not text_fallback_started
                    and active_structured_config.response_tool_name
                    and (active_structured_config.structured_output or StructuredOutputConfig()).fallback_to_text
                ):
                    active_structured_config = _text_fallback_structured_config(active_structured_config)
                    current_prompt = _build_json_regenerate_prompt(prompt, bad_output, exc)
                    text_fallback_started = True
                    attempt = 0
                    _log_llm_event(
                        novel_id,
                        agent_name,
                        task,
                        f"{task} 结构化 tool 输出缺失，降级为 JSON 文本模式重试",
                        status="started",
                        node="llm_text_fallback",
                        level="warning",
                        metadata={
                            **context_metadata,
                            **_prompt_metadata(current_prompt),
                            "error_kind": error_kind,
                            "error": str(exc),
                        },
                    )
                    continue
                attempt += 1
                if attempt >= max_retries and not fallback_started:
                    fallback_info = _fallback_driver_for_parse(client)
                    if fallback_info is not None:
                        fallback_client, _ = fallback_info
                        fallback_structured_config = _structured_config_for_client(fallback_client, task, model_cls)
                        if fallback_structured_config is not None:
                            _log_llm_event(
                                novel_id,
                                agent_name,
                                task,
                                f"{task} 结构化输出缺失，切换备用模型重试",
                                status="started",
                                node="llm_fallback",
                                level="warning",
                                metadata={
                                    **context_metadata,
                                    **_prompt_metadata(current_prompt),
                                    "error_kind": error_kind,
                                    "error": str(exc),
                                },
                            )
                            active_client = fallback_client
                            active_structured_config = fallback_structured_config
                            current_prompt = prompt
                            fallback_started = True
                            text_fallback_started = False
                            attempt = 0
                            continue
                if attempt < max_retries:
                    await asyncio.sleep(1 * (attempt + 1))
        _log_llm_event(
            novel_id,
            agent_name,
            task,
            f"{task} 解析失败，已达最大重试次数: {last_error}",
            status="failed",
            node="llm_parse",
            level="error",
            metadata={
                "max_retries": max_retries,
                "structured": True,
                **_prompt_metadata(current_prompt),
                **context_metadata,
                "error": str(last_error),
                "error_kind": _classify_parse_error(last_error, "") if last_error else "parse_error",
                "missing_paths": _validation_missing_paths(last_error) if last_error else [],
            },
        )
        raise RuntimeError(
            f"LLM parse failed after {max_retries} retries for {agent_name}/{task}: {last_error}"
        ) from last_error

    return await call_and_parse(
        agent_name=agent_name,
        task=task,
        prompt=prompt,
        parser=parser,
        max_retries=max_retries,
        novel_id=novel_id,
        context_metadata=context_metadata,
        config_agent_name=config_agent_name,
        config_task=config_task,
        client=client,
    )
