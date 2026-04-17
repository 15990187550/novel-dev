from unittest.mock import patch


def test_mcp_stdio_entrypoint_calls_run():
    from novel_dev.mcp_server.server import mcp
    with patch.object(mcp, "run") as mock_run:
        import runpy
        runpy.run_module("novel_dev.mcp_server", run_name="__main__")
        mock_run.assert_called_once_with(transport="stdio")
