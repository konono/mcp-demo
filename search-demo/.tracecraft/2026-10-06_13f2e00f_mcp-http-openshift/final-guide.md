# Final Guide: Python CLI + opencode Skill を MCP HTTP サーバー化して OpenShift に載せる

> 対象: `search-demo`（依存ゼロの Python CLI ＋ opencode Skill）
> 成果: MCP Streamable HTTP サーバー / コンテナイメージ / OpenShift マニフェスト / クライアント接続手順
> 検証日: 2026-10-06

この手順書は、本セッションで実際に実行し成功した経路のみを記載する。
途中で失敗した経路と理由は `troubleshooting.md`、判断の理由は `decisions.md` を参照。

---

## 0. 前提条件

- mise（python 3.12 / uv 0.12.23 を導入する）
- コンテナランタイム（本セッションは DooD 構成の podman 6.1.3）
- OpenShift クラスタと `oc`（**本セッションではクラスタ未接続のため、マニフェストは
  レンダリング検証のみ。配備前に `oc apply --dry-run=server` を実行すること**）

---

## 1. SDK の現行 API を確認する（最初にやる）

MCP Python SDK は 2.x でメジャー変更が入っており、`FastMCP` は `MCPServer` に改名されている。
記憶で書かず、必ず実物を確認する。

```bash
uv venv /tmp/mcpenv -q
VIRTUAL_ENV=/tmp/mcpenv uv pip install -q mcp uvicorn
/tmp/mcpenv/bin/python -c "
import inspect
from mcp.server.mcpserver import MCPServer
print(inspect.signature(MCPServer.streamable_http_app))
print(inspect.signature(MCPServer.tool))
"
```

確認しておくべき点:

- `MCPServer.streamable_http_app(streamable_http_path, json_response, stateless_http, transport_security, host)` → Starlette
- `MCPServer.custom_route(path, methods)` でヘルスチェックを足せる
- クライアントは `mcp.Client` + `mcp.client.streamable_http.streamable_http_client(url, http_client=...)`
- **SDK は `httpx` ではなく `httpx2` を使う**
- モデルの属性名はスネークケース（`structured_content`, `is_error`, `input_schema`）

---

## 2. プロジェクトを作る

既存コードを複製せず、パス依存で取り込む。

```
mcp-demo/
  Containerfile          ← リポジトリルートに置く
  .dockerignore
  mise.toml
  search-demo/           ← 既存。触らない
  search-mcp/            ← 新設
```

`search-mcp/pyproject.toml` の要点:

```toml
[project]
requires-python = ">=3.11"
dependencies = [
    "mcp>=2.3,<3",             # 1.x と API 非互換なので上限を切る
    "uvicorn[standard]>=0.38",
    "search-demo==1.0.0",
]

[tool.uv.sources]
search-demo = { path = "../search-demo" }   # PyPI に無いローカルパッケージ

[tool.hatch.build.targets.wheel]
packages = ["src/search_mcp"]
```

**注意**: `readme = "README.md"` を書くなら、同時にファイルも作ること
（hatchling がビルド時に実在をチェックし `OSError` で止まる）。

---

## 3. サーバーを実装する

### 3.1 モジュール構成

| ファイル | 役割 |
|---|---|
| `src/search_mcp/settings.py` | 環境変数からの設定（frozen dataclass） |
| `src/search_mcp/server.py` | MCP サーバー定義（ツール・description・スキーマ） |
| `src/search_mcp/auth.py` | Bearer 認証 ASGI ミドルウェア |
| `src/search_mcp/app.py` | ASGI 組み立て（health, 認証, DNS rebinding 保護） |
| `src/search_mcp/__main__.py` | uvicorn 起動 |

### 3.2 Skill の内容をツール定義に落とす

対応関係（詳細は `search-mcp/docs/skill-to-mcp.md`）:

| SKILL.md | MCP |
|---|---|
| frontmatter `description` | `MCPServer(instructions=...)` |
| オプション表 | `inputSchema`（型・enum・既定値・範囲） |
| 「使い分けの指針」 | ツール `description` の中核 |
| 「注意」 | `description` の制約節 ＋ スキーマでの強制 |
| 「出力」の JSON 例 | Pydantic モデル → `outputSchema` |
| （対応なし） | `ToolAnnotations`（副作用の申告） |

落とすもの: `--format`（CLI の人間向け UI）、`-s all`（`| None` で表現できる）、短縮形、実行環境の説明。

### 3.3 必ず踏む 3 つの落とし穴

**(1) 同期関数はスレッドに逃がす**

```python
payload = await anyio.to_thread.run_sync(
    search_demo.run_search, query, selected, effective_limit, lang
)
```

**(2) アノテーションに設定値を埋めるなら PEP 563 を使わない**

`Field(le=settings.max_limit)` のようにクロージャ変数を参照する場合、
`from __future__ import annotations` があると SDK の `eval_str=True` が
`NameError` → `InvalidSignature` になる。`server.py` だけ PEP 563 を外す。

**(3) ヘルスチェックは認証を素通りさせる**

kubelet の probe は `Authorization` ヘッダを付けられない。
ミドルウェアで `/healthz` `/readyz` を除外する。

### 3.4 HTTP ワークロードとしての組み立て

```python
mcp = build_server(settings)

@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(_): return PlainTextResponse("ok")

app = mcp.streamable_http_app(
    streamable_http_path=settings.mcp_path,
    stateless_http=True,          # 複数 replica に必要
    json_response=settings.json_response,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=settings.allowed_hosts,   # Route のホスト名を入れる
        allowed_origins=settings.allowed_origins,
    ),
    host=settings.host,
)
if settings.auth_tokens:
    app = BearerTokenMiddleware(app, tokens=settings.auth_tokens)
```

---

## 4. テストする

**in-process の `ASGITransport` では動かない。** `MCPServer` の Starlette アプリは
lifespan で `StreamableHTTPSessionManager` の task group を起動するため、
lifespan を実行しない ASGITransport では
`RuntimeError: Task group is not initialized` になる。

動的ポートで実 uvicorn を立てる:

```python
@contextlib.asynccontextmanager
async def _serve(settings):
    sock = socket.socket(); sock.bind(("127.0.0.1", 0))
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
```

外部 API は `monkeypatch.setattr(search_demo, "run_search", ...)` で差し替える。

検証した項目（9 件、2.66 秒）:

- `/healthz` `/readyz` が認証を素通りする
- `/mcp` が認証なしで 401 + `WWW-Authenticate: Bearer` を返す
- 正しいトークンでツール一覧が取れる
- instructions とツール description に Skill のガイダンスが載っている
- `MCP_MAX_LIMIT` が入力スキーマの `maximum` に反映される
- structured output の内容、部分失敗が `errors` に載ること
- `sources` 省略時に全ソースを引くこと
- 上限超えの `limit` が外部 API に到達しないこと

```bash
uv run pytest -q
# 9 passed in 2.66s
```

---

## 5. コンテナイメージを作る

### 5.1 build context はリポジトリルート

`[tool.uv.sources]` のパス依存があるため、`search-mcp/` だけを context にすると解決できない。
`Containerfile` はリポジトリルートに置く。

### 5.2 マルチステージの要点

```dockerfile
FROM registry.access.redhat.com/ubi9/python-312:latest AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv

# 依存だけ先に入れてキャッシュを効かせる（パス依存先の pyproject も要る）
COPY search-mcp/pyproject.toml search-mcp/uv.lock /build/search-mcp/
COPY search-demo/pyproject.toml search-demo/README.md search-demo/search_demo.py /build/search-demo/
RUN cd /build/search-mcp && uv sync --locked --no-dev --no-editable --no-install-project

COPY search-mcp/src /build/search-mcp/src
COPY search-mcp/README.md /build/search-mcp/
RUN cd /build/search-mcp && uv sync --locked --no-dev --no-editable

FROM registry.access.redhat.com/ubi9/python-312-minimal:latest AS runtime
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" MCP_HOST=0.0.0.0 MCP_PORT=8080
USER 1001
ENTRYPOINT ["search-mcp"]
```

**`--no-editable` が必須。** 付けないと venv に builder のパスを指す `.pth` が残り、
runtime ステージで `ModuleNotFoundError: No module named 'search_mcp'` になる。
ビルド自体は成功するので、必ず `podman run` で起動確認すること。

### 5.3 ビルドと確認

```bash
cd <リポジトリルート>
uv --project search-mcp lock          # uv.lock を先に作る
podman build -f Containerfile -t search-mcp:1.0.0 .

podman run -d --rm --name smcp -e MCP_AUTH_TOKENS=dev-token search-mcp:1.0.0
podman exec smcp python -c "
import urllib.request as u
print('health:', u.urlopen('http://127.0.0.1:8080/healthz').read().decode())
print('uid:', __import__('os').getuid())
"
# health: ok
# uid: 1001
```

### 5.4 OpenShift の任意 UID で動くことを確認する

`restricted-v2` SCC は namespace の UID 範囲から任意の UID を注入する。

```bash
podman run --rm --user 1000670000:0 -e MCP_AUTH_TOKENS=t search-mcp:1.0.0
# INFO: Application startup complete. が出れば OK
```

マニフェスト側は `runAsUser` を**書かない**（`runAsNonRoot: true` のみ）。

### 5.5 既知の制約

- `HEALTHCHECK` は OCI フォーマットでは無視される（ビルド時に警告）。
  Kubernetes では Deployment の probe を使うので実害はない
- DooD 環境では、起動したコンテナの publish ポートはホスト側に出るため、
  エージェントコンテナからは `curl localhost:<port>` で到達できない。
  `podman exec` で確認する

---

## 6. OpenShift マニフェストを書く

`search-mcp/deploy/openshift/` に kustomize 一式（12 リソース）。

| ファイル | 要点 |
|---|---|
| `namespace.yaml` | 配備先 |
| `serviceaccount.yaml` | 専用 SA。K8s API を呼ばないので RoleBinding なし |
| `configmap.yaml` | `MCP_STATELESS_HTTP=true`, `MCP_JSON_RESPONSE=true`, `MCP_ALLOWED_HOSTS` |
| `deployment.yaml` | replicas 2、`runAsUser` なし、`readOnlyRootFilesystem` + `/tmp` emptyDir、startup/liveness/readiness probe |
| `service.yaml` | ClusterIP:8080。stateless なので sessionAffinity 不要 |
| `route.yaml` | edge TLS、`timeout: 120s`、`disable_cookies: true`、roundrobin |
| `networkpolicy.yaml` | 既定全拒否 ＋ Router / `mcp-client=search-mcp` ラベル namespace / 監視 |
| `hpa.yaml` | CPU 70%、2〜6、scaleDown 安定化 300s |
| `pdb.yaml` | `minAvailable: 1` |
| `build.yaml` | ImageStream + BuildConfig（任意。kustomization 外） |
| `secret.example.yaml` | **kustomization に含めない。** トークンは `oc create secret` |

### 6.1 kustomization の注意

`commonLabels` は非推奨。`labels` に移すときは `includeSelectors` を明示する:

```yaml
labels:
  - includeSelectors: false      # version をセレクタに入れると apply が壊れる
    pairs:
      app.kubernetes.io/part-of: mcp-demo
      app.kubernetes.io/version: 1.0.0
```

セレクタ用の `app.kubernetes.io/name` は各マニフェストに直接書く。

### 6.2 検証

```bash
kubectl kustomize search-mcp/deploy/openshift/     # 警告なしで 12 リソース
```

**`kubectl apply --dry-run=client` はクラスタ接続を要求するため実行できない。**
API スキーマ検証は配備前に実クラスタで:

```bash
oc apply --dry-run=server -k search-mcp/deploy/openshift/
```

---

## 7. 配備する

```bash
oc new-project search-mcp

# 1. トークンを作る（VM 用と Pod 用を分けるなら 2 本）
oc create secret generic search-mcp-auth \
  --from-literal=tokens="$(openssl rand -hex 32),$(openssl rand -hex 32)"

# 2. Route のホスト名を確認して configmap.yaml の MCP_ALLOWED_HOSTS を書き換える
oc get ingresses.config/cluster -o jsonpath='{.spec.domain}{"\n"}'
#   → search-mcp-search-mcp.apps.<domain>
#   Service の FQDN も許可リストに入れること

# 3. イメージを push（またはクラスタ内ビルド）
oc apply -f search-mcp/deploy/openshift/build.yaml
oc start-build search-mcp --from-dir=. --follow   # リポジトリルートから

# 4. 適用
oc apply -k search-mcp/deploy/openshift/
oc rollout status deploy/search-mcp
```

### 確認

```bash
HOST=$(oc get route search-mcp -o jsonpath='{.spec.host}')
TOKEN=$(oc get secret search-mcp-auth -o jsonpath='{.data.tokens}' | base64 -d | cut -d, -f1)

curl -s -o /dev/null -w '%{http_code}\n' -X POST "https://$HOST/mcp" -d '{}'   # 401
MCP_URL="https://$HOST/mcp" MCP_TOKEN="$TOKEN" \
  uv run python search-mcp/examples/smoke_client.py "asyncio"
```

**`MCP_ALLOWED_HOSTS` に Route ホストを入れ忘れると `421 Misdirected Request` /
`Invalid Host header` になる**（401 ではない。E2E テストで確認済み）。

---

## 8. クライアントを繋ぐ

### 8.1 virt 上の VM の opencode（Route 経由）

`~/.config/opencode/opencode.json`:

```json
{
  "mcp": {
    "search": {
      "type": "remote",
      "url": "https://search-mcp-search-mcp.apps.example.com/mcp",
      "enabled": true,
      "headers": { "Authorization": "Bearer {env:SEARCH_MCP_TOKEN}" }
    }
  }
}
```

- トークンは `{env:...}` で環境変数から読む（設定ファイルに直書きしない）
- Router の CA が VM の信頼ストアに無ければ入れる
- **既存の Skill 版を削除する**。同じ機能が 2 経路で見えると呼び分けが不定になる:
  `rm -rf ~/.config/opencode/skill/public-api-search`

### 8.2 クラスタ内の agent framework Pod（Service 経由）

```bash
# NetworkPolicy の許可条件
oc label namespace <agent-ns> mcp-client=search-mcp

# トークンを配る（2 本目を使う）
TOKEN=$(oc get secret search-mcp-auth -n search-mcp -o jsonpath='{.data.tokens}' | base64 -d | cut -d, -f2)
oc create secret generic search-mcp-client -n <agent-ns> --from-literal=token="$TOKEN"
```

Pod の env:

```yaml
- name: SEARCH_MCP_URL
  value: http://search-mcp.search-mcp.svc.cluster.local:8080/mcp
- name: SEARCH_MCP_TOKEN
  valueFrom: { secretKeyRef: { name: search-mcp-client, key: token } }
```

接続コード（MCP SDK 2.x）:

```python
async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as http:
    async with Client(streamable_http_client(url, http_client=http)) as session:
        result = await session.call_tool("search", {"query": "asyncio", "limit": 3})
        print(result.structured_content)
```

Claude Agent SDK / LangChain での書き方は `search-mcp/docs/clients.md` §2.5。

---

## 9. つながらないときの切り分け

| 症状 | 原因 |
|---|---|
| タイムアウト（クラスタ内） | NetworkPolicy。namespace のラベル漏れ |
| 401 | トークン不一致。Secret 更新後に `oc rollout restart` したか |
| **421 Misdirected Request** | **`MCP_ALLOWED_HOSTS` に Route ホストが無い**（`/healthz` は通る） |
| TLS 検証エラー（VM） | Router の CA が VM に無い |
| セッションが切れる | `MCP_STATELESS_HTTP=false` のまま replica 複数 |
| 長いリクエストが切れる | Route の `haproxy.router.openshift.io/timeout` |

---

## 10. トークンのローテーション

環境変数で読むため、**Secret 更新だけでは反映されない。**

```bash
# 1. 新旧併記
oc patch secret search-mcp-auth --type=merge -p '{"stringData":{"tokens":"<old>,<new>"}}'
oc rollout restart deploy/search-mcp
# 2. クライアントを新トークンに切り替え
# 3. 旧を外す
oc patch secret search-mcp-auth --type=merge -p '{"stringData":{"tokens":"<new>"}}'
oc rollout restart deploy/search-mcp
```

OAuth 2.1 への移行手順は `search-mcp/docs/security.md`。
