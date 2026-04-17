import sys

from novel_dev.mcp_server.server import mcp

if __name__ == "__main__":
    try:
        mcp.run(transport="stdio")
    except Exception as exc:
        print(f"MCP server failed to start: {exc}", file=sys.stderr)
        sys.exit(1)
