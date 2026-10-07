# OpenShift への配備

## 前提

- `oc` でクラスタにログイン済み
- イメージを push できるレジストリ（クラスタ内の internal registry でも外部でもよい）
- 配備先 namespace を作れる権限

## 1. イメージをビルドする

build context は**リポジトリルート**。`search-mcp/pyproject.toml` が
`[tool.uv.sources]` で `../search-demo` を参照しているため、
`search-mcp/` だけを context にすると依存を解決できない。

```bash
cd <リポジトリルート>
podman build -f Containerfile -t search-mcp:1.0.0 .
```

### クラスタ内でビルドする場合

```bash
oc apply -f search-mcp/deploy/openshift/build.yaml
oc start-build search-mcp --from-dir=. --follow   # リポジトリルートから
```

`build.yaml` は `kustomization.yaml` に含めていない。
手元ビルド＋外部レジストリ運用でも使えるようにするため。

## 2. Secret を作る

トークンはマニフェストに入れない。クラスタ側で生成する。

```bash
oc new-project search-mcp

oc create secret generic search-mcp-auth \
  --from-literal=tokens="$(openssl rand -hex 32)"
```

クライアントごとにトークンを分けたい場合はカンマ区切りで複数入れる。
片方だけ失効させられる。

```bash
oc create secret generic search-mcp-auth \
  --from-literal=tokens="$(openssl rand -hex 32),$(openssl rand -hex 32)"
```

## 3. ConfigMap のホスト名を実環境に合わせる

`deploy/openshift/configmap.yaml` の `MCP_ALLOWED_HOSTS` /
`MCP_ALLOWED_ORIGINS` は DNS rebinding 対策の許可リストで、
**ここを直さないと Route 経由のアクセスが
`421 Misdirected Request` / `Invalid Host header` になる**
（E2E テストで確認済み。`/healthz` には適用されないため、
probe は通るのに `/mcp` だけ落ちるという形で現れる）。

Route のホスト名を先に確定させる:

```bash
# host を指定しない場合、割り当てられるのは <name>-<namespace>.apps.<domain>
oc get ingresses.config/cluster -o jsonpath='{.spec.domain}{"\n"}'
# => apps.example.com   →  search-mcp-search-mcp.apps.example.com
```

`configmap.yaml` を次のように書き換える:

```yaml
MCP_ALLOWED_HOSTS: "search-mcp-search-mcp.apps.example.com,search-mcp.search-mcp.svc.cluster.local:8080,search-mcp:8080"
MCP_ALLOWED_ORIGINS: "https://search-mcp-search-mcp.apps.example.com"
```

クラスタ内からの Service 名でのアクセスも Host ヘッダに乗るので、
**Service の FQDN も許可リストに入れる**こと。
検証中に切り分けたいだけなら `MCP_DNS_REBINDING_PROTECTION: "false"` にできるが、
Route を公開した状態では戻すこと。

## 4. 適用する

```bash
oc apply -k search-mcp/deploy/openshift/
```

作られるもの:

| リソース | 役割 |
|---|---|
| Namespace `search-mcp` | 配備先 |
| ServiceAccount `search-mcp` | 専用 SA（Kubernetes API は呼ばないので RoleBinding なし） |
| ConfigMap `search-mcp-config` | 非機密の設定 |
| Deployment `search-mcp` | replicas 2、restricted-v2 SCC 互換 |
| Service `search-mcp` | ClusterIP:8080。クラスタ内クライアント用 |
| Route `search-mcp` | edge TLS。クラスタ外（VM 上の opencode）用 |
| NetworkPolicy ×4 | 既定全拒否＋Router/エージェント namespace/監視のみ許可 |
| HPA | CPU 70% で 2〜6 replica |
| PodDisruptionBudget | ドレイン中も最低 1 Pod |

Secret `search-mcp-auth` は手順 2 で別途作る（kustomization に含めていない）。

## 5. 確認する

```bash
oc rollout status deploy/search-mcp
oc get route search-mcp -o jsonpath='{.spec.host}{"\n"}'

TOKEN=$(oc get secret search-mcp-auth -o jsonpath='{.data.tokens}' | base64 -d | cut -d, -f1)
HOST=$(oc get route search-mcp -o jsonpath='{.spec.host}')

# 認証なしは 401
curl -s -o /dev/null -w '%{http_code}\n' -X POST "https://$HOST/mcp" -d '{}'

# ツール一覧が返る
curl -s "https://$HOST/mcp" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

MCP クライアントでの疎通確認は `examples/smoke_client.py` を使う:

```bash
cd search-mcp
MCP_URL="https://$HOST/mcp" MCP_TOKEN="$TOKEN" uv run python examples/smoke_client.py
```

## 設計上の判断メモ

### なぜ stateless_http にしたか

Streamable HTTP はセッション ID をプロセスメモリに持つ実装がある。
stateful のまま replica を増やすと、2 回目のリクエストが別 Pod に飛んで
セッション未知エラーになるため、Route 側で cookie による固定が必要になる。
`MCP_STATELESS_HTTP=true` にすれば各リクエストが独立し、
ロードバランスも HPA も素直に効く。

トレードオフ: サーバー発の通知（進捗・リソース更新）が使えない。
このサーバーのツールはどちらも単発の read なので支障がない。

### なぜ json_response を既定 true にしたか（ConfigMap 側）

SSE ストリームは HAProxy のバッファリングや idle timeout の影響を受けやすい。
長時間ストリームを返さないので、単発 JSON のほうがトラブルが少ない。
進捗通知が必要になったら `MCP_JSON_RESPONSE: "false"` に戻し、
Route の `haproxy.router.openshift.io/timeout` を見直す。

### なぜ readOnlyRootFilesystem + emptyDir(/tmp) か

アプリはファイルを書かないが、Python や httpx が一時ファイルを作る可能性がある。
ルートを読み取り専用にしたうえで `/tmp` だけ書けるようにしておくのが安全側。

### なぜ runAsUser を書かないか

OpenShift の `restricted-v2` SCC は namespace ごとに割り当てた UID 範囲から
任意の UID を注入する。マニフェストで UID を固定すると SCC に弾かれる。
イメージ側も特定 UID に依存しない作りにしてある（検証済み: UID 1000670000 で起動する）。

### HEALTHCHECK について

`Containerfile` の `HEALTHCHECK` は OCI フォーマットでは無視される
（podman のビルド時に警告が出る）。Kubernetes では Deployment 側の
startup/liveness/readiness probe が使われるので実害はない。
`podman run` 単体で使うときのためだけに残してある。
