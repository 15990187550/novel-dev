import pytest

from novel_dev.mcp_server.server import mcp


def test_mcp_server_has_tools():
    expected = {
        "query_entity",
        "get_active_foreshadowings",
        "get_timeline",
        "get_spaceline_chain",
        "get_novel_state",
        "get_novel_documents",
        "upload_document",
        "get_pending_documents",
        "approve_pending_documents",
        "list_style_profile_versions",
        "rollback_style_profile",
        "analyze_style_from_text",
    }
    assert set(mcp.tools.keys()) == expected


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
async def test_mcp_list_style_profile_versions():
    upload = await mcp.tools["upload_document"]("n3", "style.txt", "x" * 10000)
    await mcp.tools["approve_pending_documents"](upload["id"])
    result = await mcp.tools["list_style_profile_versions"]("n3")
    assert len(result) == 1
    assert result[0]["version"] == 1


@pytest.mark.asyncio
async def test_mcp_rollback_style_profile():
    upload = await mcp.tools["upload_document"]("n4", "style.txt", "y" * 10000)
    await mcp.tools["approve_pending_documents"](upload["id"])
    result = await mcp.tools["rollback_style_profile"]("n4", 1)
    assert result["rolled_back_to_version"] == 1


@pytest.mark.asyncio
async def test_mcp_analyze_style_from_text():
    result = await mcp.tools["analyze_style_from_text"]("剑光一闪。敌人倒下。")
    assert "style_guide" in result
    assert "style_config" in result
