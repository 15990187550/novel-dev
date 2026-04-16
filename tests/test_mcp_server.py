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


@pytest.mark.asyncio
async def test_mcp_upload_document():
    result = await mcp.tools["upload_document"]("n1", "setting.txt", "世界观：天玄大陆。")
    assert result["extraction_type"] == "setting"
    assert "id" in result


@pytest.mark.asyncio
async def test_mcp_get_pending_documents():
    upload = await mcp.tools["upload_document"]("n2", "style.txt", "a" * 5000)
    result = await mcp.tools["get_pending_documents"]("n2")
    assert any(i["id"] == upload["id"] for i in result)


@pytest.mark.asyncio
async def test_mcp_analyze_style_from_text():
    result = await mcp.tools["analyze_style_from_text"]("剑光一闪。敌人倒下。")
    assert "style_guide" in result
    assert "style_config" in result
