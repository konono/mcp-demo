# search-mcp

`search-demo` の公開 API 横断検索を、**MCP (Model Context Protocol) の
Streamable HTTP サーバー**として公開する。OpenShift 上にコンテナとして配備し、
virt 上の VM で動く opencode からも、クラスタ内の agent framework Pod からも使える。

```
                       ┌─────────────────────────────────────┐
   virt の VM          │ OpenShift (namespace: search-mcp)   │
  ┌──────────┐ HTTPS   │  ┌────────┐      ┌───────────────┐  │
  │ opencode ├─────────┼─►│ Route  ├─────►│  Deployment   │  │   公開 API
  └──────────┘ (edge   │  │ (edge) │      │  search-mcp   ├──┼──► Wikipedia
               TLS)    │  └────────┘      │  replicas: 2  │  │    Hacker News
                       │                  │  (stateless)  │  │    GitHub
  ┌──────────┐  HTTP   │  ┌────────┐      │               │  │    Stack Overflow
  │  agent   ├─────────┼─►│Service ├─────►│  :8080 /mcp   │  │
  │   Pod    │ (cluster│  │ClusterIP      └───────────────┘  │
  └──────────┘  内)    │  └────────┘                         │
                       └─────────────────────────────────────┘
```

## 公開しているもの

| ツール | 内容 |
|---|---|
| `search` | Wikipedia / Hacker News / GitHub / Stack Overflow を横断検索。structured output で `{query, count, results[], errors[]}` を返す |
| `list_search_sources` | 各ソースの使いどころと制約を返す |

| エンドポイント | 用途 |
|---|---|
| `POST /mcp` | MCP Streamable HTTP。Bearer 認証が要る |
| `GET /healthz` | liveness。認証不要 |
| `GET /readyz` | readiness。認証不要 |

## ドキュメント

| 文書 | 内容 |
|---|---|
| [docs/skill-to-mcp.md](docs/skill-to-mcp.md) | **SKILL.md をどう MCP のツール定義に落としたか。**何を description に残し、何をスキーマで強制し、何を捨てたか |
| [docs/deploy-openshift.md](docs/deploy-openshift.md) | ビルドから配備、設計判断（stateless にした理由など） |
| [docs/clients.md](docs/clients.md) | VM 上の opencode / クラスタ内 Pod からの接続設定と切り分け表 |
| [docs/security.md](docs/security.md) | 認証方式の選択理由、ローテーション手順、OAuth 2.1 への移行手順 |

## 構成

```
Containerfile                       # リポジトリルートに置く（build context の都合）
search-demo/                        # 検索ロジック本体。MCP 版はこれを依存として取り込む
search-mcp/
  src/search_mcp/
    server.py                       # MCP サーバー定義（ツール・description・スキーマ）
    app.py                          # ASGI 組み立て（health, 認証, DNS rebinding 保護）
    auth.py                         # Bearer 認証ミドルウェア
    settings.py                     # 環境変数からの設定
    __main__.py                     # uvicorn 起動
  deploy/openshift/                 # kustomize 一式
  examples/                         # opencode.json, agent-pod.yaml, smoke_client.py
  tests/test_server.py              # 実 HTTP でのプロトコルテスト（単体）
  tests/e2e/run-e2e.sh              # コンテナ・マニフェストまで含む E2E
```

検索ロジックは `search-demo` 側にしかない。`pyproject.toml` の
`[tool.uv.sources]` でパス依存として取り込んでいるので二重管理にならない。

## ローカルで動かす

```bash
cd search-mcp
mise install
uv sync --extra dev

MCP_AUTH_TOKENS=dev-token \
MCP_ALLOWED_HOSTS=127.0.0.1:8080 \
uv run search-mcp
```

別のシェルから:

```bash
MCP_URL=http://127.0.0.1:8080/mcp MCP_TOKEN=dev-token \
  uv run python examples/smoke_client.py "asyncio"
```

## テスト

**単体**（9 件。外部 API は叩かない。`run_search` を差し替えて MCP レイヤだけを見る）:

```bash
cd search-mcp && uv run pytest
```

**E2E**（36 件。イメージをビルドして実際に起動し、curl で叩く）:

```bash
search-mcp/tests/e2e/run-e2e.sh

#   E2E_SKIP_BUILD=1    イメージを再ビルドしない
#   E2E_SKIP_NETWORK=1  外部 API を叩くチェックを飛ばす
```

単体テストが見ていない層をこちらで押さえている。

| | |
|---|---|
| イメージのメタデータ | `USER 1001` / ENTRYPOINT / EXPOSE |
| SCC 相当での起動 | 任意 UID（1000670000）/ read-only rootfs / cap-drop ALL |
| **本番設定の経路** | `MCP_JSON_RESPONSE=true`（SSE 無効）と DNS rebinding 保護。**単体テストでは無効化しているため、ここでしか動かない** |
| HTTP 契約 | 401 と `WWW-Authenticate`、probe の認証バイパス、許可外 Host の 421 |
| MCP プロトコル | initialize / tools/list / tools/call を生の JSON-RPC で |
| 外部 API への実疎通 | コンテナ内から GitHub 検索 |
| Deployment マニフェスト | `podman kube play` で起動し、probe が healthy になるまで待つ |

E2E は専用ネットワーク上にクライアントコンテナを置き、そこから curl する。
DooD 環境では publish したポートがホスト側に出るため、
テストを実行するプロセスからは到達できないため。

検証できないもの: Route / NetworkPolicy / HPA / PDB（podman に概念が無い）、
マニフェストの API スキーマ（クラスタが要る）。

## コンテナで動かす

build context は**リポジトリルート**。`search-demo/` も context に要るため。

```bash
cd <リポジトリルート>
podman build -f Containerfile -t search-mcp:1.0.0 .
podman run --rm -p 8080:8080 \
  -e MCP_AUTH_TOKENS=dev-token \
  -e MCP_DNS_REBINDING_PROTECTION=false \
  search-mcp:1.0.0
```

## OpenShift に配備する

```bash
oc new-project search-mcp
oc create secret generic search-mcp-auth --from-literal=tokens="$(openssl rand -hex 32)"
# deploy/openshift/configmap.yaml の MCP_ALLOWED_HOSTS を Route のホスト名に合わせる
oc apply -k search-mcp/deploy/openshift/
```

詳細と注意点は [docs/deploy-openshift.md](docs/deploy-openshift.md)。

## 設定（環境変数）

| 変数 | 既定 | 説明 |
|---|---|---|
| `MCP_HOST` | `0.0.0.0` | bind アドレス |
| `MCP_PORT` | `8080` | bind ポート（非特権） |
| `MCP_PATH` | `/mcp` | MCP エンドポイントのパス |
| `MCP_STATELESS_HTTP` | `true` | セッションを持たない。複数 replica に必要 |
| `MCP_JSON_RESPONSE` | `false` | `true` で SSE ではなく単発 JSON（Route 配下では推奨） |
| `MCP_AUTH_TOKENS` | 空 | 許可する Bearer トークン（カンマ区切り）。空だと認証なし |
| `MCP_DNS_REBINDING_PROTECTION` | `true` | Host / Origin の検証 |
| `MCP_ALLOWED_HOSTS` | 空 | 許可する Host。Route 経由なら必須 |
| `MCP_ALLOWED_ORIGINS` | 空 | 許可する Origin |
| `MCP_DEFAULT_LIMIT` | `5` | `limit` 省略時のソースごと件数 |
| `MCP_MAX_LIMIT` | `20` | `limit` の上限。入力スキーマに反映される |
| `MCP_LOG_LEVEL` | `INFO` | ログレベル |

## Skill 版との関係

`search-demo/.opencode/skill/public-api-search/SKILL.md` は、同じ機能を
opencode のローカル Skill として提供する**リファレンス実装**として残してある。

同じ opencode に両方を入れると同じ機能が 2 経路で見えて呼び分けが不定になるため、
MCP に移したら Skill 版は外すこと（[docs/clients.md](docs/clients.md) §1.3）。

散文の Skill をスキーマ付きの MCP ツールへどう翻訳したかは
[docs/skill-to-mcp.md](docs/skill-to-mcp.md) にまとめてある。
