from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class MCPToolEntry:
    name: str
    fn: Callable[..., Any]
    read_only: bool
    description: str = ""


class MCPToolRegistry:
    def __init__(self, entries: dict[str, MCPToolEntry]):
        self._entries = entries

    @classmethod
    def from_fastmcp(
        cls,
        mcp: Any,
        *,
        write_tool_names: set[str] | None = None,
    ) -> "MCPToolRegistry":
        write_tool_names = write_tool_names or set()
        tools = getattr(getattr(mcp, "_tool_manager", None), "_tools", {})
        entries = {}
        for name, tool in tools.items():
            entries[name] = MCPToolEntry(
                name=name,
                fn=tool.fn,
                read_only=name not in write_tool_names,
                description=getattr(tool, "description", "") or "",
            )
        return cls(entries)

    def get(self, name: str) -> MCPToolEntry | None:
        return self._entries.get(name)

    def list(self, *, read_only: bool | None = None) -> list[MCPToolEntry]:
        entries = list(self._entries.values())
        if read_only is None:
            return entries
        return [entry for entry in entries if entry.read_only is read_only]
