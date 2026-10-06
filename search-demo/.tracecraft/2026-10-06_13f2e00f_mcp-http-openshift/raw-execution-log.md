# Raw Execution Log

> 作業タイトル: search-demo を MCP Streamable HTTP サーバー化し OpenShift に配備可能にする
> 開始日時: 2026-10-06
> 目的: 実行したコマンドとその stdout/stderr 出力をそのまま時系列で記録する

---

## 1. 既存資産の確認

### 1.1 ディレクトリ構成

```
$ ls -la /Users/kono/gitrepo/mcp-demo; find /Users/kono/gitrepo/mcp-demo/search-demo -type f | head -50
total 0
drwxr-xr-x.  3 agent dialout  96 Oct  6 15:03 .
drwxr-xr-t.  3 root  root     22 Oct  6 14:54 ..
drwxr-xr-x. 10 agent dialout 320 Oct  6 15:13 search-demo
---
/Users/kono/gitrepo/mcp-demo/search-demo/search_demo.py
/Users/kono/gitrepo/mcp-demo/search-demo/pyproject.toml
/Users/kono/gitrepo/mcp-demo/search-demo/README.md
/Users/kono/gitrepo/mcp-demo/search-demo/mise.toml
/Users/kono/gitrepo/mcp-demo/search-demo/dist/search_demo-1.0.0-py3-none-any.whl
/Users/kono/gitrepo/mcp-demo/search-demo/dist/search_demo-1.0.0.tar.gz
... (.tracecraft の既存 3 セッション分のファイルを省略)
/Users/kono/gitrepo/mcp-demo/search-demo/.opencode/skill/public-api-search/SKILL.md
```

### 1.2 既存ファイルの内容確認

```
$ cd /Users/kono/gitrepo/mcp-demo/search-demo && cat search_demo.py pyproject.toml mise.toml .opencode/skill/public-api-search/SKILL.md README.md
... (全文を取得。要点は worklog Step 1 に記載)
```

---

## 2. ツールチェーンの準備

### 2.1 uv が PATH に無い (失敗)

```
$ cd /tmp && uv pip download mcp
/bin/bash: line 1: uv: command not found
```

### 2.2 mise 経由で python / uv を導入

```
$ cd /Users/kono/gitrepo/mcp-demo/search-demo && mise install && eval "$(mise env -s bash)" && which python uv && python -V && uv --version
mise python@3.12.15 Python 3.12.15
mise ✓ python@3.12.15  4.0s  cpython-3.12.15+20261003-aarch64-unknown-linux-gnu-install_only_stripped.tar.gz
mise ████████████████ 2/2 · installed 2 tools in 6.1s
/home/agent/.local/share/mise/installs/python/3.12/bin/python
/home/agent/.local/share/mise/installs/uv/0.12.23/.mise-bins/uv
Python 3.12.15
uv 0.12.23 (aarch64-unknown-linux-gnu)
```

---

## 3. MCP SDK の API 調査

### 3.1 FastMCP の import (失敗 — SDK がメジャーバージョンアップ)

```
$ uv venv /tmp/mcpenv -q && VIRTUAL_ENV=/tmp/mcpenv uv pip install -q "mcp" uvicorn starlette && /tmp/mcpenv/bin/python -c "
import importlib.metadata as md
print('mcp', md.version('mcp'))
from mcp.server.fastmcp import FastMCP
"
Traceback (most recent call last):
  File "<string>", line 4, in <module>
  File "/tmp/mcpenv/lib/python3.12/site-packages/mcp/server/fastmcp.py", line 16, in <module>
    raise ModuleNotFoundError(_MESSAGE, name=__name__)
ModuleNotFoundError: No module named 'mcp.server.fastmcp'. This is mcp 2.x, where FastMCP was renamed to MCPServer (from mcp.server.mcpserver import MCPServer) and other APIs changed; see the migration guide at https://py.sdk.modelcontextprotocol.io/v2/migration/#fastmcp-renamed-to-mcpserver or pin 'mcp<2' to keep running v1 code.
mcp 2.3.0
```

### 3.2 MCPServer の API 確認

```
$ /tmp/mcpenv/bin/python -c "
import inspect
from mcp.server.mcpserver import MCPServer
print('INIT', inspect.signature(MCPServer.__init__))
print('MEMBERS', [m for m in dir(MCPServer) if not m.startswith('_')])
print('tool', inspect.signature(MCPServer.tool))
print('run', inspect.signature(MCPServer.run))
"
INIT (self, name: 'str | None' = None, title: 'str | None' = None, description: 'str | None' = None, instructions: 'str | None' = None, website_url: 'str | None' = None, icons: 'list[Icon] | None' = None, version: 'str' = '', auth_server_provider: 'OAuthAuthorizationServerProvider[Any, Any, Any] | None' = None, token_verifier: 'TokenVerifier | None' = None, *, tools: ..., extensions: ..., debug: 'bool' = False, log_level: "Literal['DEBUG','INFO','WARNING','ERROR','CRITICAL']" = 'INFO', ..., auth: 'AuthSettings | None' = None, resource_security: 'ResourceSecurity' = ..., middleware: 'Sequence[ServerMiddleware[Any]] | None' = None)

MEMBERS ['add_prompt', 'add_resource', 'add_tool', 'call_tool', 'completion', 'custom_route', 'description', 'get_prompt', 'icons', 'instructions', 'list_prompts', 'list_resource_templates', 'list_resources', 'list_tools', 'middleware', 'name', 'prompt', 'read_resource', 'remove_prompt', 'remove_tool', 'resource', 'run', 'run_sse_async', 'run_stdio_async', 'run_streamable_http_async', 'session_manager', 'sse_app', 'streamable_http_app', 'title', 'tool', 'version', 'website_url']

tool (self, name: 'str | None' = None, title: 'str | None' = None, description: 'str | None' = None, annotations: 'ToolAnnotations | None' = None, icons: ..., meta: ..., structured_output: 'bool | None' = None) -> 'Callable[[_CallableT], _CallableT]'
run (self, transport: "Literal['stdio', 'sse', 'streamable-http']" = 'stdio', **kwargs: 'Any') -> 'None'
```

### 3.3 streamable_http_app と custom_route のシグネチャ

```
$ /tmp/mcpenv/bin/python -c "
import inspect
from mcp.server.mcpserver import MCPServer
print(inspect.signature(MCPServer.streamable_http_app))
print(inspect.signature(MCPServer.custom_route))
from mcp.server.mcpserver.server import Settings
print([f for f in Settings.model_fields])
"
(self, *, streamable_http_path: 'str' = '/mcp', json_response: 'bool' = False, stateless_http: 'bool' = False, event_store: 'EventStore | None' = None, retry_interval: 'int | None' = None, max_request_body_size: 'int' = 4194304, session_idle_timeout: 'float | None' = 1800, max_sessions: 'int | None' = 10000, transport_security: 'TransportSecuritySettings | None' = None, host: 'str' = '127.0.0.1') -> 'Starlette'
(self, path: 'str', methods: 'list[str]', name: 'str | None' = None, include_in_schema: 'bool' = True)
['debug', 'log_level', 'warn_on_duplicate_resources', 'warn_on_duplicate_tools', 'warn_on_duplicate_prompts', 'dependencies', 'lifespan', 'auth']
```

### 3.4 認証関連の API 確認

```
$ /tmp/mcpenv/bin/python -c "
import inspect
from mcp.server.mcpserver.server import AuthSettings
print('AuthSettings', [f for f in AuthSettings.model_fields])
from mcp.server.auth.provider import TokenVerifier, AccessToken
print(inspect.getsource(TokenVerifier))
print(inspect.getsource(AccessToken))
from mcp.server.transport_security import TransportSecuritySettings as T
print('TSS', [f for f in T.model_fields])
"
AuthSettings ['issuer_url', 'service_documentation_url', 'client_registration_options', 'revocation_options', 'required_scopes', 'identity_assertion_enabled', 'resource_server_url', 'validate_token_resource']

class TokenVerifier(Protocol):
    """Protocol for verifying bearer tokens."""
    async def verify_token(self, token: str) -> AccessToken | None:
        """... Set `AccessToken.resource` to the resource the token was issued for
        (its RFC 8707 resource indicator / `aud`) ... With
        `AuthSettings.validate_token_resource` the bearer middleware then refuses
        any token whose resource is not `resource_server_url` ..."""

class AccessToken(BaseModel):
    token: str
    client_id: str
    scopes: list[str]
    expires_at: int | None = None
    resource: str | None = None  # RFC 8707 resource indicator
    subject: str | None = None
    claims: dict[str, Any] | None = None

TSS ['enable_dns_rebinding_protection', 'allowed_hosts', 'allowed_origins']
```

### 3.5 クライアント API の確認

```
$ uv run python -c "
import inspect
from mcp.client.streamable_http import streamable_http_client
print(inspect.signature(streamable_http_client))
from mcp import Client
print([m for m in dir(Client) if not m.startswith('_')])
"
(url: 'str', *, http_client: 'httpx2.AsyncClient | None' = None, terminate_on_close: 'bool' = True, max_sse_event_size: 'int | None' = 1048576) -> 'AsyncGenerator[TransportStreams, None]'
['call_tool', 'client_info', 'complete', 'elicitation_callback', 'extensions', 'get_prompt', 'input_required_max_rounds', 'instructions', 'list_prompts', 'list_resource_templates', 'list_resources', 'list_roots_callback', 'listen', 'log_level', 'logging_callback', 'message_handler', 'mode', 'prior_discover', 'protocol_version', 'raise_exceptions', 'read_resource', 'read_timeout_seconds', 'sampling_callback', 'send_ping', 'server_capabilities', 'server_info', 'session', 'set_logging_level', 'subscribe_resource', ...]
```

### 3.6 httpx2 の確認

```
$ uv run python -c "
import httpx2
print(httpx2.__version__, hasattr(httpx2,'ASGITransport'))
from mcp.shared.transport import Transport
"
Traceback (most recent call last):
  File "<string>", line 4, in <module>
ModuleNotFoundError: No module named 'mcp.shared.transport'
2.13.1 True
```

---

## 4. 依存のインストール

### 4.1 uv sync (失敗 — README.md が無い)

```
$ uv sync --extra dev
  cause: The build backend returned an error
  cause: Call to `hatchling.build.build_editable` failed (exit status: 1)

         [stderr]
         Traceback (most recent call last):
           ...
           File ".../hatchling/metadata/core.py", line 553, in readme
             raise OSError(message)
         OSError: Readme file does not exist: README.md

hint: Build failures usually indicate a problem with the package or the build environment
```

### 4.2 README.md 作成後に再実行 (成功)

```
$ echo "# search-mcp" > README.md && uv sync --extra dev
 + starlette==1.7.0
 + truststore==0.10.4
 + typing-extensions==4.16.0
 + typing-inspection==0.4.4
 + uvicorn==0.54.0
 + uvloop==0.23.0
 + watchfiles==1.3.0
 + websockets==17.2
```

---

## 5. テストの実行

### 5.1 1 回目 (失敗 — InvalidSignature)

```
$ uv run pytest -q
...
>           raise InvalidSignature(f"Unable to evaluate type annotations for callable {func.__name__!r}") from e
E           mcp.server.mcpserver.exceptions.InvalidSignature: Unable to evaluate type annotations for callable 'search'

.venv/lib/python3.12/site-packages/mcp/server/mcpserver/utilities/func_metadata.py:326: InvalidSignature
=========================== short test summary info ============================
FAILED tests/test_server.py::test_health_endpoints_bypass_auth - mcp.server.m...
FAILED tests/test_server.py::test_mcp_endpoint_requires_bearer_token - mcp.se...
FAILED tests/test_server.py::test_valid_token_reaches_the_mcp_handler - mcp.s...
FAILED tests/test_server.py::test_tool_descriptions_carry_the_skill_guidance
FAILED tests/test_server.py::test_limit_bound_is_published_in_the_input_schema
FAILED tests/test_server.py::test_search_returns_structured_output - mcp.serv...
FAILED tests/test_server.py::test_omitting_sources_queries_all - mcp.server.m...
FAILED tests/test_server.py::test_limit_above_max_is_rejected - mcp.server.mc...
FAILED tests/test_server.py::test_list_search_sources_describes_each_source
9 failed in 0.94s
```

### 5.2 原因の特定 (__cause__ の確認)

```
$ uv run python -c "
from search_mcp.settings import Settings
import search_mcp.server as s
try:
    s.build_server(Settings())
except Exception as e:
    print(type(e), e, '| cause:', repr(e.__cause__))
"
<class 'mcp.server.mcpserver.exceptions.InvalidSignature'> Unable to evaluate type annotations for callable 'search' | cause: NameError("name 'settings' is not defined")
```

→ `src/search_mcp/server.py` から `from __future__ import annotations` を削除

### 5.3 2 回目 (失敗 — Task group is not initialized)

```
$ uv run pytest -q
    |   File ".../mcp/server/streamable_http_manager.py", line 427, in __call__
    |     await self.session_manager.asgi_app(scope, receive, send)
    |   File ".../mcp/server/transport_security.py", line 183, in __call__
    |     await self.app(scope, replay, send)
    |   File ".../mcp/server/streamable_http_manager.py", line 185, in _handle_request
    |     raise RuntimeError("Task group is not initialized. Make sure to use run().")
    | RuntimeError: Task group is not initialized. Make sure to use run().
    +------------------------------------
------------------------------ Captured log call -------------------------------
WARNING  search_mcp.app:app.py:60 MCP_AUTH_TOKENS is empty: the server accepts unauthenticated requests. Do not expose it through an OpenShift Route in this state.
=========================== short test summary info ============================
FAILED tests/test_server.py::test_valid_token_reaches_the_mcp_handler - Runti...
FAILED tests/test_server.py::test_tool_descriptions_carry_the_skill_guidance
FAILED tests/test_server.py::test_limit_bound_is_published_in_the_input_schema
FAILED tests/test_server.py::test_search_returns_structured_output - RuntimeE...
FAILED tests/test_server.py::test_omitting_sources_queries_all - RuntimeError...
FAILED tests/test_server.py::test_limit_above_max_is_rejected - RuntimeError(...
FAILED tests/test_server.py::test_list_search_sources_describes_each_source
7 failed, 2 passed in 3.08s
```

→ テストを `httpx.ASGITransport` から実 uvicorn 起動（`_serve()`）に変更

### 5.4 3 回目 (失敗 — 属性名がスネークケース)

```
$ uv run pytest -q
E                   AttributeError: 'CallToolResult' object has no attribute 'structuredContent'. Did you mean: 'structured_content'?

.venv/lib/python3.12/site-packages/pydantic/main.py:1042: AttributeError
=========================== short test summary info ============================
FAILED tests/test_server.py::test_tool_descriptions_carry_the_skill_guidance
FAILED tests/test_server.py::test_limit_bound_is_published_in_the_input_schema
FAILED tests/test_server.py::test_search_returns_structured_output - Attribut...
FAILED tests/test_server.py::test_limit_above_max_is_rejected - AttributeErro...
FAILED tests/test_server.py::test_list_search_sources_describes_each_source
5 failed, 4 passed in 3.08s
```

### 5.5 フィールド名の確認

```
$ uv run python -c "
from mcp_types import Tool, CallToolResult
print([f for f in Tool.model_fields])
print([f for f in CallToolResult.model_fields])
"
['name', 'title', 'description', 'input_schema', 'execution', 'output_schema', 'icons', 'annotations', 'meta']
['meta', 'content', 'structured_content', 'is_error', 'result_type']
```

### 5.6 4 回目 (成功)

```
$ uv run python - <<'PY'
p='tests/test_server.py'
s=open(p).read()
s=s.replace('.structuredContent','.structured_content').replace('.isError','.is_error').replace('.inputSchema','.input_schema').replace('readOnlyHint','read_only_hint')
open(p,'w').write(s)
PY
$ uv run pytest -q
.........                                                                [100%]
9 passed in 2.67s
```

### 5.7 server.py の ToolAnnotations もスネークケースに統一

```
$ uv run pytest -q
.........                                                                [100%]
9 passed in 2.66s
```

---

## 6. ローカルでの実 API 疎通確認

### 6.1 サーバー起動と HTTP レベルの確認

```
$ MCP_AUTH_TOKENS=<REDACTED> MCP_DNS_REBINDING_PROTECTION=false MCP_PORT=18080 uv run search-mcp > /tmp/srv.log 2>&1 &
$ sleep 4; curl -s localhost:18080/healthz; curl -s -o /dev/null -w "no-auth=%{http_code}\n" -X POST localhost:18080/mcp -d '{}'
ok
no-auth=401
```

### 6.2 MCP クライアントからの検索実行

```
$ uv run python - <<'PY'
import anyio, httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

async def main():
    async with httpx2.AsyncClient(headers={"Authorization":"Bearer <REDACTED>"}) as http:
        async with Client(streamable_http_client("http://127.0.0.1:18080/mcp", http_client=http)) as s:
            print("server:", s.server_info)
            r = await s.call_tool("search", {"query":"asyncio","sources":["github"],"limit":2})
            sc = r.structured_content
            print("count:", sc["count"], "errors:", sc["errors"])
            for h in sc["results"]:
                print(" -", h["source"], h["title"], h["url"])
anyio.run(main)
PY
server: name='search-mcp' title='Public API Search' version='1.0.0' description=None website_url=None icons=None
count: 2 errors: []
 - github fastapi/fastapi https://github.com/fastapi/fastapi
 - github home-assistant/core https://github.com/home-assistant/core
```

### 6.3 サーバーログ

```
$ tail -5 /tmp/srv.log
INFO:     127.0.0.1:42970 - "POST /mcp HTTP/1.1" 401 Unauthorized
INFO:     127.0.0.1:42982 - "POST /mcp HTTP/1.1" 200 OK
2026-10-06 15:30:32,293 INFO search_mcp.server search query='asyncio' sources=['github'] limit=2 lang=ja
INFO:     127.0.0.1:42982 - "POST /mcp HTTP/1.1" 200 OK
INFO:     127.0.0.1:42982 - "POST /mcp HTTP/1.1" 200 OK
```

---

## 7. コンテナ化

### 7.1 uv.lock 生成

```
$ uv lock
Resolved 48 packages in 2ms
$ ls uv.lock
uv.lock
```

### 7.2 コンテナ CLI が無い

```
$ docker version --format '{{.Server.Version}}'
/bin/bash: line 1: docker: command not found
$ ls /run/container.sock; which podman buildah; echo "DOCKER_HOST=$DOCKER_HOST"
/run/container.sock
DOCKER_HOST=unix:///run/container.sock CONTAINER_HOST=unix:///run/container.sock
```

### 7.3 podman の導入とシンボリックリンク修正

```
$ mise install podman@latest
mise WARN  podman installed but not activated — it is not in any config file.

$ PODMAN_DIR=$(mise where podman@latest) && (cd "$PODMAN_DIR/bin" && ln -sf ../podman-remote-static-linux_* podman) && "$PODMAN_DIR/bin/podman" version
/bin/bash: line 1: /home/agent/.local/share/mise/installs/podman/6.1.3/bin/podman: No such file or directory

$ ls -R /home/agent/.local/share/mise/installs/podman/6.1.3
/home/agent/.local/share/mise/installs/podman/6.1.3:
bin
podman-remote

$ P=/home/agent/.local/share/mise/installs/podman/6.1.3 && ln -sf ../podman-remote $P/bin/podman && $P/bin/podman version
Client:       Podman Engine
Version:      6.1.3
API Version:  6.1.3
Go Version:   go1.27.1
```

(CLAUDE.md の手順はバイナリ名が `podman-remote-static-linux_*` を想定しているが、
実際のバイナリ名は `podman-remote` だった)

### 7.4 1 回目のビルド (成功)

```
$ podman build -f Containerfile -t search-mcp:1.0.0 .
... (省略)
 + search-mcp==1.0.0 (from file:///build/search-mcp)
--> deda6bc866a7
[2/2] STEP 1/8: FROM registry.access.redhat.com/ubi9/python-312-minimal:latest AS runtime
... (省略)
[2/2] STEP 7/8: HEALTHCHECK --interval=30s --timeout=3s --start-period=5s     CMD python -c "..."
time="2026-10-07T00:33:08+09:00" level=warning msg="HEALTHCHECK is not supported for OCI image format and will be ignored. Must use `docker` format"
[2/2] STEP 8/8: ENTRYPOINT ["search-mcp"]
Successfully tagged localhost/search-mcp:1.0.0
a332e345c7c0595f47e11187118beec8a616d3ac58f08fcda796fea036c5f70a
```

### 7.5 起動 (失敗 — ModuleNotFoundError)

```
$ podman run -d --rm --name smcp -p 18081:8080 -e MCP_AUTH_TOKENS=<REDACTED> -e MCP_DNS_REBINDING_PROTECTION=false search-mcp:1.0.0 && sleep 5 && curl -s localhost:18081/healthz
(curl: 空応答)
Error: no container with name or ID "smcp" found: no such container

$ podman run --rm search-mcp:1.0.0
Traceback (most recent call last):
  File "/opt/venv/bin/search-mcp", line 4, in <module>
    from search_mcp.__main__ import main
ModuleNotFoundError: No module named 'search_mcp'
```

→ `Containerfile` の `uv sync` に `--no-editable` を追加

### 7.6 2 回目のビルドと起動 (成功、ただし curl は到達せず)

```
$ podman build -q -f Containerfile -t search-mcp:1.0.0 . && podman run -d --rm --name smcp -p 18081:8080 -e MCP_AUTH_TOKENS=<REDACTED> -e MCP_DNS_REBINDING_PROTECTION=false search-mcp:1.0.0 && sleep 5 && echo "health: $(curl -s localhost:18081/healthz)" && curl -s -o /dev/null -w "noauth=%{http_code}\n" -XPOST localhost:18081/mcp -d '{}'
8088e1326ad4c576540b1fd85c2632bd8d52f11b73535a90c42d4f34029e0f5a
health:
noauth=000
(exit code 7)

$ podman logs smcp; podman ps -a --filter name=smcp --format '{{.Status}} {{.Ports}}'
2026-10-06 15:33:42,131 INFO search_mcp.app bearer auth enabled (1 token(s) configured)
INFO:     Started server process [1]
INFO:     Waiting for application startup.
2026-10-06 15:33:42,143 INFO mcp.server.streamable_http_manager StreamableHTTP session manager started
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
Up 7 seconds 0.0.0.0:18081->8080/tcp
```

### 7.7 コンテナ内からの疎通確認 (成功)

```
$ podman exec smcp python -c "
import urllib.request as u
print('health:', u.urlopen('http://127.0.0.1:8080/healthz').read().decode())
try:
    u.urlopen(u.Request('http://127.0.0.1:8080/mcp', data=b'{}', headers={'Content-Type':'application/json'}))
except Exception as e:
    print('noauth:', e.code, e.headers.get('WWW-Authenticate'))
print('uid:', __import__('os').getuid())
"
health: ok
noauth: 401 Bearer realm="search-mcp"
uid: 1001
```

### 7.8 任意 UID での起動確認 (OpenShift restricted-v2 相当)

```
$ podman run --rm --user 1000670000:0 -e MCP_AUTH_TOKENS=<REDACTED> search-mcp:1.0.0 &
2026-10-06 15:33:56,471 INFO search_mcp.app bearer auth enabled (1 token(s) configured)
INFO:     Started server process [1]
INFO:     Waiting for application startup.
2026-10-06 15:33:56,481 INFO mcp.server.streamable_http_manager StreamableHTTP session manager started
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)

$ podman ps --format '{{.Image}} {{.Status}}'
ghcr.io/konono/aw-claude:4.15.1-debian12 Up 11 hours
ghcr.io/konono/aw-claude:4.15.1-debian12 Up 39 minutes
localhost/search-mcp:1.0.0 Up 6 seconds
```

---

## 8. OpenShift マニフェストの検証

### 8.1 kubectl の導入

```
$ mise install kubectl@latest; ls $(mise where kubectl@latest)
kubectl
```

### 8.2 1 回目の kustomize build (非推奨警告)

```
$ kubectl kustomize . > /tmp/rendered.yaml; echo "exit=$?"; grep -c "^kind:" /tmp/rendered.yaml
exit=0
12

$ grep -n "image:\|commonLabels\|deprecat" /tmp/rendered.yaml | head
1:# Warning: 'commonLabels' is deprecated. Please use 'labels' instead. Run 'kustomize edit fix' to update your Kustomization automatically.
118:        image: image-registry.openshift-image-registry.svc:5000/search-mcp/search-mcp:1.0.0
```

### 8.3 labels + includeSelectors に修正後 (成功)

```
$ kubectl kustomize . > /tmp/rendered.yaml && echo "render ok (no warnings)"
render ok (no warnings)
```

### 8.4 API 検証 (失敗 — クラスタ未接続)

```
$ kubectl apply --dry-run=client --validate=false -f /tmp/rendered.yaml
E1006 15:35:30.616726    2501 memcache.go:381] "Couldn't get current server API group list" err="Get \"http://localhost:8080/api?timeout=32s\": dial tcp [::1]:8080: connect: connection refused"
... (同じエラーが 12 回)
unable to recognize "/tmp/rendered.yaml": Get "http://localhost:8080/api?timeout=32s": dial tcp [::1]:8080: connect: connection refused
... (12 行)
```

→ API スキーマ検証は未実施のまま。実クラスタでの `oc apply --dry-run=server` が必要

---

## 9. サンプルクライアントでの最終疎通確認

### 9.1 コンテナ相手 (失敗 — DooD のネットワーク制約)

```
$ podman run -d --rm --name smcp --network host -e MCP_AUTH_TOKENS=<REDACTED> -e MCP_ALLOWED_HOSTS=127.0.0.1:8080 search-mcp:1.0.0
$ MCP_URL=http://127.0.0.1:8080/mcp MCP_TOKEN=<REDACTED> uv run python examples/smoke_client.py "rust tui"
  + Exception Group Traceback (most recent call last):
  |   File ".../examples/smoke_client.py", line 31, in main
  |     async with Client(streamable_http_client(URL, http_client=http)) as session:
  ...
  |   File ".../anyio/_backends/_asyncio.py", line 847, in __aexit__
  |     raise BaseExceptionGroup(
  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
  +-+---------------- 1 ----------------
    | Traceback (most recent call last):
    |   File ".../httpx2/_transports/default.py", line 98, in map_httpcore_exceptions
    (接続エラー)
```

### 9.2 ローカルサーバー相手 (成功)

```
$ MCP_AUTH_TOKENS=<REDACTED> MCP_ALLOWED_HOSTS=127.0.0.1:18082 MCP_PORT=18082 uv run search-mcp >/tmp/s2.log 2>&1 &
$ MCP_URL=http://127.0.0.1:18082/mcp MCP_TOKEN=<REDACTED> uv run python examples/smoke_client.py "rust tui"
connected: name='search-mcp' title='Public API Search' version='1.0.0' description=None website_url=None icons=None
instructions:
公開 API（Wikipedia / Hacker News / GitHub / Stack Overflow）を横断検索するサーバー。認証不要の外部 API のみを使う。

次のときに `search` を使う:
  - 用語の意味や技術トピックの一次情報を知りたい
  - OSS のライブラリ・リポジトリを探したい
  - エラーメッセージの既知の解決策を探したい
  - 手持ちの知識が古い可能性があり、外部情報で裏取りしたい

回答時は必ず結果の `url` を引用元として提示すること。
一部のソースが失敗しても処理は続行し、理由は `errors` に入る。`count` が 0 のときは `errors` を必ず読むこと。

tool: search — Wikipedia / Hacker News / GitHub / Stack Overflow を横断検索し、タイトル・URL・要約の一覧を返す。認証不要・外部ネットワークアクセスあり。
tool: list_search_sources — search ツールで指定できるソースと、それぞれの使いどころ・制約を返す。どのソースを選ぶべきか迷ったときに先に呼ぶ。外部アクセスは発生しない。

--- search('rust tui') ---
{
  "query": "rust tui",
  "count": 8,
  "results": [
    {
      "source": "wikipedia",
      "title": "パッケージ管理システム",
      "url": "https://ja.wikipedia.org/wiki/%E3%83%91%E3%83%83%E3%82%B1%E3%83%BC%E3%82%B8%E7%AE%A1%E7%90%86%E3%82%B7%E3%82%B9%E3%83%86%E3%83%A0",
      "snippet": "RubyGemsはRuby言語用のパッケージ管理システムであり..."
    },
    {
      "source": "hackernews",
      "title": "DNSGlobe – Rust TUI to watch DNS propagate around the world",
      "url": "https://github.com/514-labs/dnsglobe",
      "snippet": "points=83 comments=70 by Callicles on 2026-07-05T21:55:53Z"
    },
    ... (全 8 件)
```

---

## 10. 最終確認

### 10.1 .dockerignore 追加後のテストとビルド

```
$ uv run pytest -q
.........                                                                [100%]
9 passed in 2.66s

$ podman build -q -f Containerfile -t search-mcp:1.0.0 .
5f9fbeea811d0e4536f82bea47d29a4dad283063ccefc3f28f64b08cf25422f0
```

### 10.2 イメージの最終動作確認

```
$ podman run -d --rm --name smcp2 -e MCP_AUTH_TOKENS=<REDACTED> search-mcp:1.0.0 && sleep 5 && podman exec smcp2 python -c "
import urllib.request as u
print('health:', u.urlopen('http://127.0.0.1:8080/healthz').read().decode())
" && podman rm -f smcp2 && echo "image ok after .dockerignore"
health: ok
image ok after .dockerignore
```

---

## Phase 11: skill-to-mcp.md の射程拡張

### SDK の resource / prompt デコレータのシグネチャ確認

```
$ cd /Users/kono/gitrepo/mcp-demo/search-mcp && uv run python -c "
from mcp.server.mcpserver import MCPServer
import inspect
for n in ('resource','prompt','tool'):
    print(n, hasattr(MCPServer,n) and str(inspect.signature(getattr(MCPServer,n)))[:160])
"
```

stdout（各行 160 文字で切り詰め）:

```
resource (self, uri: 'str', *, name: 'str | None' = None, title: 'str | None' = None, description: 'str | None' = None, mime_type: 'str | None' = None, icons: 'list[Icon
prompt (self, name: 'str | None' = None, title: 'str | None' = None, description: 'str | None' = None, icons: 'list[Icon] | None' = None) -> 'Callable[[_CallableT], _C
tool (self, name: 'str | None' = None, title: 'str | None' = None, description: 'str | None' = None, annotations: 'ToolAnnotations | None' = None, icons: 'list[Icon]
```

→ 文書 §8 のコード例（`@mcp.resource("guide://sources/{name}", title=...)` /
`@mcp.prompt(title=...)`）はシグネチャ上有効。

### 文書変更後のテスト

```
$ uv run pytest -q
.........                                                                [100%]
9 passed in 2.67s
```

### 行数確認

```
$ grep -c '' /Users/kono/gitrepo/mcp-demo/search-mcp/docs/skill-to-mcp.md
615
```

（改訂前は 276 行）

---

## Phase 12: GitHub リポジトリの作成と push

### 認証と現状確認

```
$ gh auth status
github.com
  ✓ Logged in to github.com account konono (GITHUB_TOKEN)
  - Active account: true
  - Git operations protocol: https
  - Token: <REDACTED>

$ git status
fatal: not a git repository (or any parent up to mount point /Users/kono/gitrepo)

$ ls -a
.  ..  .dockerignore  Containerfile  mise.toml  search-demo  search-mcp
```

### 秘密情報の走査

```
$ grep -rniE "(gho_|ghp_|BEGIN .*PRIVATE KEY|password|api[_-]?key *[:=])" --include='*' . \
    | grep -v '\.venv/' | grep -v '__pycache__' | head -20
（出力なし）
```

### サイズ確認

```
$ du -sh search-mcp/* search-mcp/.venv | sort -h | tail -5
48K	search-mcp/deploy
56K	search-mcp/docs
68K	search-mcp/src
252K	search-mcp/uv.lock
72M	search-mcp/.venv
```

→ `.venv` を除外する `.gitignore` が必須と判断。

### git 初期化とステージング

```
$ git init -q -b main && git add -A && git status --short | wc -l
68

$ git ls-files | xargs du -ch 2>/dev/null | tail -1
764K	total
```

### コミット

```
$ git -c user.name="konono" -c user.email="konono@users.noreply.github.com" commit -q -F - <<'MSG'
Add MCP HTTP server, container, and OpenShift manifests for search-demo
...
MSG

$ git log --oneline
a028ac8 Add MCP HTTP server, container, and OpenShift manifests for search-demo
```

### リポジトリ作成と push

```
$ gh repo create mcp-demo --public --source=. --remote=origin --push \
    --description "opencode の Skill を MCP サーバーに移植するリファレンス実装 — 移植知識・コンテナ・OpenShift マニフェスト・作業記録つき"
https://github.com/konono/mcp-demo
To https://github.com/konono/mcp-demo.git
 * [new branch]      HEAD -> main
branch 'main' set up to track 'origin/main'.
```

### 事後確認

```
$ gh repo view --json url,visibility,defaultBranchRef -q '.url, .visibility, .defaultBranchRef.name'
https://github.com/konono/mcp-demo
PUBLIC
main

$ gh api repos/konono/mcp-demo/contents --jq '.[].name' | tr '\n' ' '
.dockerignore .gitignore Containerfile README.md mise.toml search-demo search-mcp
```
