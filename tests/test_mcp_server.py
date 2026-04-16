import pytest

from novel_dev.mcp_server.server import mcp


def test_mcp_server_has_tools():
    tools = list(mcp.tools.keys())
    assert "query_entity" in tools
    assert "get_active_foreshadowings" in tools
    assert "get_timeline" in tools
    assert "get_spaceline_chain" in tools
    assert "get_novel_state" in tools
    assert "get_novel_documents" in tools


@pytest.mark.asyncio
async def test_query_entity():
    result = await mcp.query_entity("nonexistent")
    assert result["entity_id"] == "nonexistent"
    assert result["state"] is None


@pytest.mark.asyncio
async def test_get_novel_state_not_found():
    result = await mcp.get_novel_state("novel_nonexistent")
    assert result["error"] == "not found"
