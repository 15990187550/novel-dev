import pytest

from novel_dev.llm.context_tools import build_mcp_context_tools
from novel_dev.mcp_server.registry import MCPToolEntry, MCPToolRegistry


@pytest.mark.asyncio
async def test_build_mcp_context_tools_exposes_only_readonly_allowlisted_entries():
    async def read_state(novel_id: str):
        return {"novel_id": novel_id}

    async def write_state(novel_id: str):
        return {"written": novel_id}

    registry = MCPToolRegistry({
        "get_novel_state": MCPToolEntry("get_novel_state", read_state, read_only=True),
        "upload_document": MCPToolEntry("upload_document", write_state, read_only=False),
    })

    tools = build_mcp_context_tools(registry, allowlist=["get_novel_state", "upload_document"])

    assert [tool.name for tool in tools] == ["get_novel_state"]
    result = await tools[0].handler({"novel_id": "n1"})
    assert result == {"novel_id": "n1"}
