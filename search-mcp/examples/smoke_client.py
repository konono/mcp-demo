#!/usr/bin/env python3
"""配備した search-mcp への疎通確認。

    MCP_URL=https://search-mcp.apps.example.com/mcp \
    MCP_TOKEN=<token> \
    uv run python examples/smoke_client.py "asyncio"

クラスタ内の Pod から実行する場合:

    MCP_URL=http://search-mcp.search-mcp.svc.cluster.local:8080/mcp
"""

from __future__ import annotations

import json
import os
import sys

import anyio
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

URL = os.environ.get("MCP_URL", "http://127.0.0.1:8080/mcp")
TOKEN = os.environ.get("MCP_TOKEN", "")


async def main(query: str) -> None:
    headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
    async with httpx2.AsyncClient(headers=headers, timeout=30.0) as http:
        async with Client(streamable_http_client(URL, http_client=http)) as session:
            print(f"connected: {session.server_info}")
            print(f"instructions:\n{session.instructions}\n")

            for tool in (await session.list_tools()).tools:
                print(f"tool: {tool.name} — {(tool.description or '').splitlines()[0]}")

            print(f"\n--- search({query!r}) ---")
            result = await session.call_tool("search", {"query": query, "limit": 2})
            if result.is_error:
                print("ERROR:", result.content)
                raise SystemExit(1)
            print(json.dumps(result.structured_content, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    anyio.run(main, sys.argv[1] if len(sys.argv) > 1 else "asyncio")
