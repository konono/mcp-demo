"""MCP サーバーの振る舞いを実 HTTP 経由で確認する。

外部 API は叩かない: search_demo.run_search を差し替えて、
MCP レイヤ（ツール公開・入力検証・structured output・認証）だけを対象にする。
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
from collections.abc import AsyncIterator

import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

import search_demo
from search_mcp.app import create_app
from search_mcp.settings import Settings

FAKE_PAYLOAD = {
    "query": "asyncio",
    "count": 1,
    "results": [
        {
            "source": "github",
            "title": "python/cpython",
            "url": "https://github.com/python/cpython",
            "snippet": "★1 Python: demo",
        }
    ],
    "errors": [{"source": "wikipedia", "error": "HTTP 503 from example"}],
}


@pytest.fixture
def fake_search(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """search_demo.run_search の呼び出し引数を記録しつつ固定レスポンスを返す。"""
    calls: list[tuple] = []

    def _run_search(query, sources, limit, lang):
        calls.append((query, tuple(sources), limit, lang))
        return FAKE_PAYLOAD

    monkeypatch.setattr(search_demo, "run_search", _run_search)
    return calls


def _settings(**overrides) -> Settings:
    base = {
        # テストは 127.0.0.1 の動的ポートに繋ぐので Host の許可リスト管理を省く
        "enable_dns_rebinding_protection": False,
        "max_limit": 20,
        "default_limit": 5,
    }
    base.update(overrides)
    return Settings(**base)


@contextlib.asynccontextmanager
async def _serve(settings: Settings) -> AsyncIterator[str]:
    """uvicorn で実サーバーを立て、base URL を返す。

    in-process の ASGITransport では Starlette の lifespan が走らず、
    StreamableHTTP のセッションマネージャが初期化されない
    （"Task group is not initialized"）。本番と同じ経路を通すため実際に listen する。
    """
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

    server = uvicorn.Server(uvicorn.Config(create_app(settings), log_level="warning"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        while not server.started:
            await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


def _http(base_url: str, token: str | None = None) -> httpx2.AsyncClient:
    """MCP SDK 2.x の streamable_http_client は httpx2 を使うため、ここも httpx2 で揃える。"""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx2.AsyncClient(base_url=base_url, headers=headers)


def _mcp(base_url: str, http_client: httpx2.AsyncClient) -> Client:
    return Client(streamable_http_client(f"{base_url}/mcp", http_client=http_client))


# --- HTTP ワークロードとしての振る舞い ----------------------------------------


async def test_health_endpoints_bypass_auth() -> None:
    """probe は Authorization を付けられないので認証を素通りする必要がある。"""
    async with _serve(_settings(auth_tokens=["s3cret"])) as base:
        async with _http(base) as client:
            assert (await client.get("/healthz")).text == "ok"
            assert (await client.get("/readyz")).json()["status"] == "ready"


async def test_mcp_endpoint_requires_bearer_token() -> None:
    async with _serve(_settings(auth_tokens=["s3cret"])) as base:
        async with _http(base) as client:
            res = await client.post("/mcp", json={})
            assert res.status_code == 401
            assert res.headers["www-authenticate"].startswith("Bearer")

            res = await client.post("/mcp", json={}, headers={"Authorization": "Bearer wrong"})
            assert res.status_code == 401


async def test_valid_token_reaches_the_mcp_handler() -> None:
    async with _serve(_settings(auth_tokens=["s3cret"])) as base:
        async with _http(base, token="s3cret") as client:
            async with _mcp(base, client) as session:
                tools = await session.list_tools()
    assert {t.name for t in tools.tools} == {"search", "list_search_sources"}


# --- Skill から移植したガイダンスがプロトコル越しに届いているか -------------------


async def test_tool_descriptions_carry_the_skill_guidance() -> None:
    async with _serve(_settings()) as base:
        async with _http(base) as client:
            async with _mcp(base, client) as session:
                assert session.server_info is not None
                assert session.server_info.name == "search-mcp"
                # SKILL.md frontmatter の description 相当が instructions に載る
                assert "引用元" in (session.instructions or "")

                tools = {t.name: t for t in (await session.list_tools()).tools}
                search_tool = tools["search"]

    assert search_tool.annotations is not None
    assert search_tool.annotations.read_only_hint is True
    # 「使い分けの指針」が description に載っていること
    assert "stackoverflow" in (search_tool.description or "")
    # 「注意」のレート制限が description に載っていること
    assert "レート制限" in (search_tool.description or "")
    assert search_tool.input_schema["required"] == ["query"]


async def test_limit_bound_is_published_in_the_input_schema() -> None:
    """SKILL.md では散文だった上限を、スキーマとして機械的に伝える。"""
    async with _serve(_settings(max_limit=7)) as base:
        async with _http(base) as client:
            async with _mcp(base, client) as session:
                tools = {t.name: t for t in (await session.list_tools()).tools}
    limit_schema = tools["search"].input_schema["properties"]["limit"]
    assert any(variant.get("maximum") == 7 for variant in limit_schema["anyOf"])


# --- 検索ツールの入出力 --------------------------------------------------------


async def test_search_returns_structured_output(fake_search: list[tuple]) -> None:
    async with _serve(_settings()) as base:
        async with _http(base) as client:
            async with _mcp(base, client) as session:
                result = await session.call_tool(
                    "search", {"query": "asyncio", "sources": ["github"], "limit": 3}
                )

    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["count"] == 1
    assert result.structured_content["results"][0]["url"] == "https://github.com/python/cpython"
    # 部分失敗は errors に載り、ツール呼び出し自体は成功扱いになる
    assert result.structured_content["errors"][0]["source"] == "wikipedia"
    assert fake_search == [("asyncio", ("github",), 3, "ja")]


async def test_omitting_sources_queries_all(fake_search: list[tuple]) -> None:
    async with _serve(_settings()) as base:
        async with _http(base) as client:
            async with _mcp(base, client) as session:
                await session.call_tool("search", {"query": "rust"})

    _, sources, limit, lang = fake_search[0]
    assert set(sources) == {"wikipedia", "hackernews", "github", "stackoverflow"}
    assert limit == 5  # settings.default_limit
    assert lang == "ja"


async def test_limit_above_max_is_rejected(fake_search: list[tuple]) -> None:
    """未認証の外部 API を守るため、上限超えは外部アクセスに到達させない。"""
    async with _serve(_settings(max_limit=10)) as base:
        async with _http(base) as client:
            async with _mcp(base, client) as session:
                result = await session.call_tool("search", {"query": "x", "limit": 999})

    assert result.is_error is True
    assert fake_search == []


async def test_list_search_sources_describes_each_source() -> None:
    async with _serve(_settings()) as base:
        async with _http(base) as client:
            async with _mcp(base, client) as session:
                result = await session.call_tool("list_search_sources", {})

    payload = result.structured_content["result"]
    assert {s["name"] for s in payload} == {
        "wikipedia",
        "hackernews",
        "github",
        "stackoverflow",
    }
    assert all(s["use_when"] and s["caveats"] for s in payload)
