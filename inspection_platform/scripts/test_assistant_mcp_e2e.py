#!/usr/bin/env python3
"""E2E: prompt.submit → session.info + tool.start (MCP vs terminal)."""

from __future__ import annotations

import asyncio
import json
import re
import sys
import urllib.request

HERMES = "http://127.0.0.1:8001/hermes-agent"
PROMPT = "我想查看灭火器的规范，请调用知识库检索工具查询后回答。"


def fetch_session_token() -> str:
    html = urllib.request.urlopen(f"{HERMES}/", timeout=60).read().decode("utf-8", errors="replace")
    m = re.search(r"__HERMES_SESSION_TOKEN__=\"([^\"]+)\"", html)
    if not m:
        raise RuntimeError("HERMES_SESSION_TOKEN not found")
    return m.group(1)


async def run_e2e() -> int:
    import websockets

    token = fetch_session_token()
    uri = f"ws://127.0.0.1:8001/hermes-agent/api/ws?token={token}"

    mcp_tool_names: list[str] = []
    tool_starts: list[str] = []
    events: list[str] = []
    session_id: str | None = None

    async with websockets.connect(uri, max_size=16 * 1024 * 1024) as ws:
        await ws.recv()  # gateway.ready

        async def rpc(method: str, params: dict, rid: int) -> None:
            await ws.send(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}))

        await rpc("session.create", {"cols": 100}, 1)

        end = asyncio.get_event_loop().time() + 420
        prompt_sent = False

        while asyncio.get_event_loop().time() < end:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=min(180, end - asyncio.get_event_loop().time()))
            except asyncio.TimeoutError:
                break
            msg = json.loads(raw)

            if msg.get("id") == 1 and "result" in msg:
                session_id = (msg.get("result") or {}).get("session_id")
                events.append(f"session.create ok {session_id}")

            em = msg.get("method")
            payload = (msg.get("params") or {}).get("payload") if em == "event" else (msg.get("params") or {})
            etype = (msg.get("params") or {}).get("type") if em == "event" else em

            if etype:
                events.append(str(etype))
            if etype == "session.info":
                tools = payload.get("tools") or {}
                for k, names in tools.items():
                    if "sia" in k or any("sia" in n for n in names):
                        mcp_tool_names.extend(names)
                        print(f">>> session.info toolset {k}: {len(names)} tools")
            if etype == "tool.start":
                name = payload.get("name") or ""
                tool_starts.append(name)
                print(f">>> tool.start: {name}")
            if etype == "error":
                events.append(f"error:{payload.get('message')}")
            if etype == "turn.complete":
                break

            if session_id and not prompt_sent and msg.get("id") == 1:
                prompt_sent = True
                await rpc("prompt.submit", {"session_id": session_id, "text": PROMPT}, 2)
                events.append("prompt.submit sent")

    print("\n=== events (tail) ===")
    for e in events[-25:]:
        print(" ", e)
    print(f"MCP tools in session.info: {mcp_tool_names}")
    print(f"tool.starts: {tool_starts}")

    if any("sia" in t for t in tool_starts):
        print("RESULT: PASS MCP invoked")
        return 0
    if any(t == "terminal" for t in tool_starts):
        print("RESULT: FAIL terminal instead of MCP")
        return 2
    print("RESULT: FAIL no tool calls")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run_e2e()))
