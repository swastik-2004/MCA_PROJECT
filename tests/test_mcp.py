"""MCP server: the digital-twin tools work through a real MCP client (in-process)."""
import asyncio

from conftest import ROOT
from mcp import Client

from levelforge import mcp_server
from levelforge.level import Level


def test_mcp_tools():
    grid = Level.load(ROOT / "data" / "problem_level.txt").grid

    async def go():
        async with Client(mcp_server.mcp) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            assert {"validate_level", "apply_edits", "evaluate_levels", "kill_worker"} <= names
            ok = (await client.call_tool("validate_level", {"grid": grid})).structured_content
            assert ok["ok"] is True
            edited = (await client.call_tool("apply_edits", {"grid": grid, "edits": [{"op": "add_loop"}],
                                                             "seed": 1})).structured_content
            assert edited["changed"] is True
            res = (await client.call_tool("evaluate_levels", {"grids": [grid, edited["grid"]],
                                                              "runs_per_persona": 15, "seed": 1})).structured_content
            assert len(res["results"]) == 2
            assert res["job"]["sims"] == 2 * 3 * 15
            for r in res["results"]:
                assert 0.0 <= r["quality"]["total"] <= 1.0

    try:
        asyncio.run(go())
    finally:
        if mcp_server._cluster is not None:
            mcp_server._cluster.close()
            mcp_server._cluster = None
