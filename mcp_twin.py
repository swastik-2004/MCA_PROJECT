"""
Start the LevelForge digital-twin MCP server (stdio) - the entry point for Claude Desktop
or any other MCP host. See README section "MCP server" for the config snippet.

    python mcp_twin.py              # stdio
    python mcp_twin.py --http       # Streamable HTTP on http://127.0.0.1:9150/mcp
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from levelforge.mcp_server import main  # noqa: E402

if __name__ == "__main__":
    main()
