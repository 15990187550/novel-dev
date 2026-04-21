import asyncio
import json
import re
from typing import Any, Callable, TypeVar

from pydantic import TypeAdapter, ValidationError

from novel_dev.llm import llm_factory
from novel_dev.llm.models import ChatMessage
from novel_dev.services.log_service import log_service

T = TypeVar("T")


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
) -> T:
    client = llm_factory.get(agent_name, task=task)
    last_error = None
    current_prompt = prompt
    for attempt in range(max_retries):
        try:
            response = await client.acomplete([ChatMessage(role="user", content=current_prompt)])
            cleaned = _strip_markdown(response.text)
            result = parser(cleaned)
            if novel_id:
                log_service.add_log(novel_id, agent_name, f"{task} 成功")
            return result
        except (ValidationError, json.JSONDecodeError) as exc:
            last_error = exc
            if _should_regenerate_json(response.text):
                current_prompt = _build_json_regenerate_prompt(prompt, response.text, exc)
            else:
                current_prompt = _build_json_repair_prompt(prompt, response.text, exc)
            if novel_id:
                log_service.add_log(novel_id, agent_name, f"{task} 解析失败(第 {attempt + 1}/{max_retries} 次): {exc}", level="warning")
            if attempt < max_retries - 1:
                await asyncio.sleep(1 * (attempt + 1))
    if novel_id:
        log_service.add_log(novel_id, agent_name, f"{task} 解析失败，已达最大重试次数: {last_error}", level="error")
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
) -> Any:
    adapter = TypeAdapter(model_cls)

    def parser(text: str):
        payload = json.loads(text)
        return adapter.validate_python(payload)

    return await call_and_parse(
        agent_name=agent_name,
        task=task,
        prompt=prompt,
        parser=parser,
        max_retries=max_retries,
        novel_id=novel_id,
    )
