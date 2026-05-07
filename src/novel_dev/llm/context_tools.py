from __future__ import annotations

import inspect
from typing import Any

from novel_dev.llm.orchestrator import LLMToolSpec
from novel_dev.mcp_server.registry import MCPToolRegistry


_TOOL_DESCRIPTIONS = {
    "get_novel_state": "Read the current phase and checkpoint data for a novel.",
    "query_entity": "Read one entity by id, including latest state and active relationships.",
    "get_novel_documents": "List document summaries for a novel and document type.",
    "search_domain_documents": "Search source documents by novel, domain/work name, document type, and query terms.",
    "get_novel_document_full": "Read a full document by novel id and document id.",
    "get_synopsis": "Read the accepted synopsis document and structured synopsis data.",
    "get_volume_plan": "Read the current persisted volume plan.",
    "get_chapter_draft_status": "Read chapter draft text, status, progress, and metadata.",
    "get_review_result": "Read the current chapter review score and feedback.",
    "get_fast_review_result": "Read the current chapter fast review score and feedback.",
    "get_archive_stats": "Read archived chapter counts and word count statistics.",
}


_TOOL_SCHEMAS = {
    "get_novel_state": {
        "type": "object",
        "properties": {"novel_id": {"type": "string"}},
        "required": ["novel_id"],
    },
    "query_entity": {
        "type": "object",
        "properties": {
            "entity_id": {"type": "string"},
            "novel_id": {"type": "string"},
        },
        "required": ["entity_id"],
    },
    "get_novel_documents": {
        "type": "object",
        "properties": {
            "novel_id": {"type": "string"},
            "doc_type": {"type": "string"},
        },
        "required": ["novel_id", "doc_type"],
    },
    "search_domain_documents": {
        "type": "object",
        "properties": {
            "novel_id": {"type": "string"},
            "query": {"type": "string"},
            "domain_name": {"type": "string"},
            "doc_type": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": ["novel_id", "query"],
    },
    "get_novel_document_full": {
        "type": "object",
        "properties": {
            "novel_id": {"type": "string"},
            "doc_id": {"type": "string"},
        },
        "required": ["novel_id", "doc_id"],
    },
    "get_chapter_draft_status": {
        "type": "object",
        "properties": {
            "novel_id": {"type": "string"},
            "chapter_id": {"type": "string"},
        },
        "required": ["novel_id", "chapter_id"],
    },
}


def build_mcp_context_tools(
    registry: MCPToolRegistry,
    *,
    allowlist: list[str],
    max_return_chars: int = 4000,
    timeout_seconds: float = 5.0,
) -> list[LLMToolSpec]:
    tools = []
    for name in allowlist:
        entry = registry.get(name)
        if entry is None or not entry.read_only:
            continue
        tools.append(LLMToolSpec(
            name=name,
            description=_TOOL_DESCRIPTIONS.get(name, entry.description or f"Call read-only MCP tool {name}."),
            input_schema=_TOOL_SCHEMAS.get(name) or _schema_from_signature(entry.fn),
            handler=_handler_for(entry.fn),
            read_only=True,
            timeout_seconds=timeout_seconds,
            max_return_chars=max_return_chars,
        ))
    return tools


def _handler_for(fn):
    async def handler(args: dict[str, Any]) -> Any:
        result = fn(**args)
        if inspect.isawaitable(result):
            return await result
        return result

    return handler


def _schema_from_signature(fn) -> dict[str, Any]:
    properties = {}
    required = []
    for name, parameter in inspect.signature(fn).parameters.items():
        properties[name] = {"type": _json_type_for(parameter.annotation)}
        if parameter.default is inspect.Parameter.empty:
            required.append(name)
    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _json_type_for(annotation: Any) -> str:
    if annotation is int:
        return "integer"
    if annotation is float:
        return "number"
    if annotation is bool:
        return "boolean"
    if annotation in (dict, list):
        return "object"
    return "string"
