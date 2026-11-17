"""
Small toolkit on top of the official A2A Python SDK (a2a-sdk, protocol v1.0).

Every LevelForge agent is a real A2A server:
  * it publishes an Agent Card at  http://127.0.0.1:<port>/.well-known/agent-card.json
    (name, description, skills, endpoint) so other agents can DISCOVER it
  * it accepts JSON-RPC `SendMessage` requests and answers with an A2A Task whose
    artifact holds the result

Messages between our agents carry one JSON object (media type application/json) with a
"skill" field naming which skill of the agent to run.

Agents also use the MCP digital-twin server; `AgentContext.mcp()` records every tool call
so the Director can show the full A2A + MCP trace.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import httpx
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import get_artifact_text, get_message_text, new_task_from_user_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Role,
                       SendMessageRequest, TaskState)

JSON = "application/json"
for _name in ("httpx", "httpcore", "mcp", "uvicorn.access", "a2a"):
    logging.getLogger(_name).setLevel(logging.WARNING)


# --------------------------------------------------------------------------- MCP access
@dataclass
class AgentContext:
    """Per-request context handed to an agent's handler."""
    agent: str
    mcp_url: str
    calls: list = field(default_factory=list)

    async def mcp(self, tool: str, args: dict) -> dict:
        """Call a tool on the LevelForge MCP server and return its structured result."""
        from mcp import Client  # imported lazily: only agents that use tools need it
        t0 = time.perf_counter()
        async with Client(self.mcp_url) as client:
            res = await client.call_tool(tool, args)
        ms = round((time.perf_counter() - t0) * 1000)
        if res.is_error:
            text = " ".join(getattr(c, "text", "") for c in res.content)
            raise RuntimeError(f"MCP tool {tool} failed: {text[:200]}")
        out = res.structured_content
        if out is None:
            out = json.loads(res.content[0].text)
        self.calls.append({"agent": self.agent, "tool": tool, "ms": ms})
        return out


Handler = Callable[[dict, AgentContext], Awaitable[dict]]


# --------------------------------------------------------------------------- server side
class JsonAgentExecutor(AgentExecutor):
    """Runs one LevelForge agent handler for each incoming A2A message."""

    def __init__(self, name: str, handler: Handler, mcp_url: str):
        self.name, self.handler, self.mcp_url = name, handler, mcp_url

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task_from_user_message(context.message)
        if not context.current_task:
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)
        ctx = AgentContext(self.name, self.mcp_url)
        t0 = time.perf_counter()
        try:
            payload = json.loads(get_message_text(context.message) or "{}")
            result = await self.handler(payload, ctx)
            result["_trace"] = {"agent": self.name, "ms": round((time.perf_counter() - t0) * 1000),
                                "mcp_calls": ctx.calls}
            await updater.add_artifact(parts=[new_text_part(text=json.dumps(result), media_type=JSON)],
                                       name="result")
            await updater.update_status(state=TaskState.TASK_STATE_COMPLETED)
        except Exception as e:  # report the failure to the caller as a failed A2A task
            err = {"error": f"{type(e).__name__}: {e}", "_trace": {"agent": self.name, "mcp_calls": ctx.calls}}
            await updater.add_artifact(parts=[new_text_part(text=json.dumps(err), media_type=JSON)],
                                       name="error")
            await updater.update_status(state=TaskState.TASK_STATE_FAILED)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("cancel is not supported")


def build_card(name: str, description: str, skills: list[dict], port: int, host: str = "127.0.0.1") -> AgentCard:
    return AgentCard(
        name=name, description=description, version="1.0",
        default_input_modes=[JSON], default_output_modes=[JSON],
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", url=f"http://{host}:{port}",
                                             protocol_version="1.0")],
        skills=[AgentSkill(id=s["id"], name=s["name"], description=s["description"],
                           tags=s.get("tags", ["levelforge"]), input_modes=[JSON], output_modes=[JSON])
                for s in skills],
    )


def build_app(card: AgentCard, handler: Handler, mcp_url: str):
    from starlette.applications import Starlette
    request_handler = DefaultRequestHandler(agent_executor=JsonAgentExecutor(card.name, handler, mcp_url),
                                            task_store=InMemoryTaskStore(), agent_card=card)
    return Starlette(routes=[*create_agent_card_routes(card), *create_jsonrpc_routes(request_handler, "/")])


# --------------------------------------------------------------------------- client side
class A2AError(RuntimeError):
    pass


class Peers:
    """A2A client used by the Director: discovers agents from their cards and sends them tasks."""

    def __init__(self):
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0))
        self.cards: dict[str, AgentCard] = {}
        self.clients: dict[str, Any] = {}

    async def discover(self, key: str, url: str) -> AgentCard:
        card = await A2ACardResolver(httpx_client=self.http, base_url=url).get_agent_card()
        self.cards[key] = card
        self.clients[key] = await create_client(agent=card, client_config=ClientConfig(
            streaming=False, httpx_client=self.http))
        return card

    async def send(self, key: str, payload: dict) -> dict:
        """Send one JSON task to agent `key` and return the JSON artifact of the finished task."""
        from a2a.helpers import new_text_message
        msg = new_text_message(json.dumps(payload), role=Role.ROLE_USER)
        msg.parts[0].media_type = JSON
        task = None
        async for event in self.clients[key].send_message(SendMessageRequest(message=msg)):
            if event.HasField("task"):
                task = event.task
            elif event.HasField("message"):
                return json.loads(get_message_text(event.message))
        if task is None or not task.artifacts:
            raise A2AError(f"{key}: no result returned")
        data = json.loads(get_artifact_text(task.artifacts[-1]))
        if task.status.state == TaskState.TASK_STATE_FAILED or "error" in data:
            raise A2AError(f"{self.cards[key].name}: {data.get('error', 'task failed')}")
        return data

    async def close(self):
        for c in self.clients.values():
            try:
                await c.close()
            except Exception:
                pass
        await self.http.aclose()
