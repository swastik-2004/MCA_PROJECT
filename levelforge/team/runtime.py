"""
Starts and stops the whole team: the MCP server (with its master-worker cluster) and one
process per A2A agent. Used by run_team.py and experiments.py.

    with TeamRuntime(workers=5, offline=True, log_dir="outputs_team/logs") as team:
        result = team.optimise({...job...})
"""
from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from .agents import ROSTER, WORKER_KEYS

ROOT = Path(__file__).resolve().parents[2]


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if sys.platform != "win32":   # ignore sockets in TIME_WAIT from a run that just ended
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _wait_http(url: str, deadline: float) -> bool:
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except Exception:
            time.sleep(0.4)
    return False


def _wait_port(port: int, deadline: float) -> bool:
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.4)
    return False


class TeamRuntime:
    def __init__(self, workers: int = 5, offline: bool = False, base_port: int = 9100, mcp_port: int = 9150,
                 log_dir: str | Path = "outputs_team/logs", director_console: bool = True,
                 startup_timeout: float = 120):
        self.workers, self.offline = workers, offline
        self.base_port, self.mcp_port = base_port, mcp_port
        self.log_dir = Path(log_dir)
        self.director_console = director_console
        self.startup_timeout = startup_timeout
        self.mcp_url = f"http://127.0.0.1:{mcp_port}/mcp"
        self.procs: list[tuple[str, subprocess.Popen]] = []
        self._files = []
        self.startup_seconds = 0.0

    @property
    def ports(self) -> list[int]:
        return [self.mcp_port] + [self.base_port + ROSTER[k][1] for k in ROSTER]

    def _spawn(self, name: str, cmd: list[str], env: dict, console: bool) -> None:
        if console:
            p = subprocess.Popen(cmd, cwd=ROOT, env=env)
        else:
            f = open(self.log_dir / f"{name}.log", "w", encoding="utf-8")
            self._files.append(f)
            p = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=f, stderr=subprocess.STDOUT)
        self.procs.append((name, p))

    def start(self) -> "TeamRuntime":
        busy = [p for p in self.ports if not port_free(p)]
        if busy:
            raise RuntimeError(f"Ports {busy} are already in use (is another run still open?). "
                               f"Close it, or use --base-port 9200 --mcp-port 9250.")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8",
               "LEVELFORGE_WORKERS": str(self.workers),
               "PYTHONPATH": str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")}
        if self.offline:
            env["LEVELFORGE_OFFLINE"] = "1"
        else:
            env.pop("LEVELFORGE_OFFLINE", None)
        if not self.director_console:
            env["NO_COLOR"] = "1"
        t0 = time.time()
        py = sys.executable
        self._spawn("mcp", [py, "-m", "levelforge.mcp_server", "--http", "--port", str(self.mcp_port),
                            "--workers", str(self.workers)], env, False)
        for key in WORKER_KEYS:
            self._spawn(key, [py, "-m", "levelforge.team.serve", key, "--base-port", str(self.base_port),
                              "--mcp", self.mcp_url], env, False)
        self._spawn("director", [py, "-m", "levelforge.team.serve", "director", "--base-port",
                                 str(self.base_port), "--mcp", self.mcp_url], env, self.director_console)
        deadline = time.time() + self.startup_timeout
        ok = _wait_port(self.mcp_port, deadline)
        for key in ROSTER:
            ok = ok and _wait_http(f"http://127.0.0.1:{self.base_port + ROSTER[key][1]}"
                                   "/.well-known/agent-card.json", deadline)
        dead = [n for n, p in self.procs if p.poll() is not None]
        if not ok or dead:
            self.stop()
            raise RuntimeError(f"Could not start {dead or 'all agents (timeout)'}; see {self.log_dir}")
        self.startup_seconds = time.time() - t0
        return self

    def stop(self) -> None:
        for _, p in self.procs:
            if p.poll() is None:
                p.terminate()
        for _, p in self.procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        for f in self._files:
            f.close()
        self.procs.clear()
        self._files.clear()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    # ------------------------------------------------------------------ requests
    def optimise(self, job: dict) -> dict:
        return asyncio.run(self._send(job))

    async def _send(self, job: dict) -> dict:
        from .a2a_kit import Peers
        peers = Peers()
        try:
            await peers.discover("director", f"http://127.0.0.1:{self.base_port + ROSTER['director'][1]}")
            res = await peers.send("director", {"skill": "optimise_level", **job})
            res.pop("_trace", None)
            return res
        finally:
            await peers.close()

    def cluster_status(self) -> dict:
        async def go():
            from mcp import Client
            async with Client(self.mcp_url) as c:
                r = await c.call_tool("cluster_status", {})
                return r.structured_content or {}
        try:
            return asyncio.run(go())
        except Exception:
            return {}
