#!/usr/bin/env bash
# コンテナイメージに対する E2E テスト。
#
# 単体テスト（tests/test_server.py）が検証していない層を対象にする:
#   - コンテナイメージが実際に起動するか（任意 UID / read-only rootfs）
#   - HTTP レベルの契約（curl から見た挙動）
#   - OpenShift 配備で有効になる設定（MCP_JSON_RESPONSE / DNS rebinding 保護）
#   - Deployment マニフェストの probe 定義が実際に通るか（podman kube play）
#
# この環境は DooD（コンテナランタイムのソケットがホストのもの）であり、
# publish したポートにはこのプロセスから到達できない。そのため
# 専用ネットワーク上にクライアントコンテナを置き、そこから curl する。
#
#   使い方: search-mcp/tests/e2e/run-e2e.sh
#   環境変数:
#     E2E_SKIP_BUILD=1    イメージを再ビルドしない
#     E2E_SKIP_NETWORK=1  外部 API を叩くチェックを飛ばす
set -uo pipefail

IMAGE=search-mcp:1.0.0
OCP_IMAGE=image-registry.openshift-image-registry.svc:5000/search-mcp/search-mcp:1.0.0
CLIENT_IMAGE=registry.access.redhat.com/ubi9/ubi-minimal:latest
NET=e2e-net
SRV=e2e-srv
CLI=e2e-cli
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
WORK=$(mktemp -d)

PASS=0
FAIL=0

ok()   { printf '  \033[32mPASS\033[0m %s\n' "$1"; PASS=$((PASS+1)); }
ng()   { printf '  \033[31mFAIL\033[0m %s\n' "$1"; printf '       %s\n' "${2:-}"; FAIL=$((FAIL+1)); }
phase(){ printf '\n\033[1m== %s\033[0m\n' "$1"; }

# actual == expected なら PASS
check() {
  local name=$1 expected=$2 actual=$3
  if [[ "$actual" == "$expected" ]]; then ok "$name"; else ng "$name" "expected=[$expected] actual=[$actual]"; fi
}

# actual が expected を含むなら PASS
contains() {
  local name=$1 needle=$2 hay=$3
  if [[ "$hay" == *"$needle"* ]]; then ok "$name"; else ng "$name" "[$needle] not found in: ${hay:0:200}"; fi
}

cleanup() {
  podman rm -f "$SRV" "$CLI" >/dev/null 2>&1
  podman kube down "$WORK/kube.yaml" >/dev/null 2>&1
  podman pod rm -f search-mcp-pod >/dev/null 2>&1
  podman secret rm search-mcp-auth >/dev/null 2>&1
  podman network rm -f "$NET" >/dev/null 2>&1
  rm -rf "$WORK"
}
trap cleanup EXIT

# クライアントコンテナ内で curl を実行する。
# 毎回コンテナを起こすと遅いので、常駐させた 1 つに exec する。
cc() { podman exec "$CLI" "$@"; }

# JSON-RPC リクエストを 1 本投げてレスポンスボディを返す
rpc() {
  local host=$1 token=$2 body=$3
  cc curl -s -m 20 -X POST "http://${host}:8080/mcp" \
    -H "Authorization: Bearer ${token}" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d "$body"
}

# ---------------------------------------------------------------- Phase 1

phase "Phase 1: イメージのビルドとメタデータ"

if [[ "${E2E_SKIP_BUILD:-0}" != "1" ]]; then
  if podman build -q -f "$REPO_ROOT/Containerfile" -t "$IMAGE" "$REPO_ROOT" >/dev/null 2>&1; then
    ok "podman build"
  else
    ng "podman build" "ビルドに失敗した。以降のテストは実行できない"
    exit 1
  fi
else
  ok "podman build (skipped)"
fi

check "USER が 1001（root では動かない）" "1001" \
  "$(podman image inspect "$IMAGE" --format '{{.Config.User}}')"
check "ENTRYPOINT が search-mcp" "[search-mcp]" \
  "$(podman image inspect "$IMAGE" --format '{{.Config.Entrypoint}}')"
check "EXPOSE 8080" "map[8080/tcp:{}]" \
  "$(podman image inspect "$IMAGE" --format '{{.Config.ExposedPorts}}')"

# ---------------------------------------------------------------- Phase 2

phase "Phase 2: OpenShift の SecurityContext 相当での起動"

podman network create "$NET" >/dev/null 2>&1

# restricted-v2 SCC は namespace の範囲から任意の UID を注入する。
# あわせて readOnlyRootFilesystem: true + /tmp emptyDir も再現する。
podman run -d --rm --name e2e-scc --network "$NET" \
  --user 1000670000:0 --read-only --tmpfs /tmp \
  --cap-drop ALL --security-opt no-new-privileges \
  -e MCP_AUTH_TOKENS=t -e MCP_ALLOWED_HOSTS=e2e-scc:8080 "$IMAGE" >/dev/null 2>&1

podman run -d --rm --name "$CLI" --network "$NET" --entrypoint "" \
  "$CLIENT_IMAGE" sleep infinity >/dev/null 2>&1

for _ in $(seq 30); do
  cc curl -sf -m 2 -o /dev/null http://e2e-scc:8080/healthz 2>/dev/null && break
  sleep 0.5
done

check "任意 UID + read-only rootfs + cap-drop ALL で起動する" "200" \
  "$(cc curl -s -m 5 -o /dev/null -w '%{http_code}' http://e2e-scc:8080/healthz)"
contains "起動ログに session manager started が出る" "StreamableHTTP session manager started" \
  "$(podman logs e2e-scc 2>&1)"
podman rm -f e2e-scc >/dev/null 2>&1

# ---------------------------------------------------------------- Phase 3

phase "Phase 3: HTTP 契約（ConfigMap と同じ設定で起動）"

# OpenShift の ConfigMap が設定する値を再現する。
# 単体テストはコードの既定値（json_response=false / DNS 保護無効）しか通らないため、
# ここが本番設定を実際に動かす唯一の場所になる。
podman run -d --rm --name "$SRV" --network "$NET" \
  -e MCP_AUTH_TOKENS=tok-a,tok-b \
  -e MCP_STATELESS_HTTP=true \
  -e MCP_JSON_RESPONSE=true \
  -e MCP_DNS_REBINDING_PROTECTION=true \
  -e MCP_ALLOWED_HOSTS="$SRV:8080" \
  -e MCP_MAX_LIMIT=10 \
  "$IMAGE" >/dev/null 2>&1

for _ in $(seq 30); do
  cc curl -sf -m 2 -o /dev/null "http://$SRV:8080/healthz" 2>/dev/null && break
  sleep 0.5
done

check "GET /healthz が ok を返す" "ok" "$(cc curl -s -m 5 "http://$SRV:8080/healthz")"
contains "GET /readyz が ready を返す" '"status":"ready"' "$(cc curl -s -m 5 "http://$SRV:8080/readyz")"
contains "readyz が stateless であることを報告する" '"stateless":true' "$(cc curl -s -m 5 "http://$SRV:8080/readyz")"

# --- 認証
check "トークン無しの /mcp は 401" "401" \
  "$(cc curl -s -m 5 -o /dev/null -w '%{http_code}' -X POST "http://$SRV:8080/mcp" -d '{}')"
contains "401 に WWW-Authenticate: Bearer が付く" "Bearer" \
  "$(cc curl -s -m 5 -D - -o /dev/null -X POST "http://$SRV:8080/mcp" -d '{}' | grep -i www-authenticate)"
check "誤ったトークンは 401" "401" \
  "$(cc curl -s -m 5 -o /dev/null -w '%{http_code}' -X POST "http://$SRV:8080/mcp" \
      -H 'Authorization: Bearer wrong' -d '{}')"
check "ヘルスチェックは認証を素通りする（probe は Authorization を付けられない）" "200" \
  "$(cc curl -s -m 5 -o /dev/null -w '%{http_code}' "http://$SRV:8080/healthz")"

# --- DNS rebinding 保護
check "許可されていない Host は 421 で拒否される" "421" \
  "$(cc curl -s -m 5 -o /dev/null -w '%{http_code}' -X POST "http://$SRV:8080/mcp" \
      -H 'Host: evil.example.com' -H 'Authorization: Bearer tok-a' \
      -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{}')"

# --- MCP プロトコル
INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"e2e","version":"0"}}}'

HDR=$(cc curl -s -m 10 -D - -o /dev/null -X POST "http://$SRV:8080/mcp" \
  -H 'Authorization: Bearer tok-a' -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' -d "$INIT")

contains "MCP_JSON_RESPONSE=true で SSE ではなく JSON が返る" "content-type: application/json" \
  "$(echo "$HDR" | tr 'A-Z' 'a-z')"
if echo "$HDR" | grep -qi '^mcp-session-id'; then
  ng "stateless_http=true ではセッション ID を発行しない" "mcp-session-id ヘッダが返った"
else
  ok "stateless_http=true ではセッション ID を発行しない"
fi

INIT_RES=$(rpc "$SRV" tok-a "$INIT")
contains "initialize が成功する" '"serverInfo"' "$INIT_RES"
contains "SKILL.md の作法が instructions に載っている" "引用元" "$INIT_RES"

# 2 本目のトークンも通る（クライアントごとに別トークンを配れること）
contains "2 本目のトークンでも認証が通る" '"serverInfo"' "$(rpc "$SRV" tok-b "$INIT")"

TOOLS=$(rpc "$SRV" tok-a '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}')
contains "tools/list に search がある" '"search"' "$TOOLS"
contains "tools/list に list_search_sources がある" '"list_search_sources"' "$TOOLS"
contains "使い分けの指針が description に載っている" "stackoverflow" "$TOOLS"
contains "レート制限の注意が description に載っている" "レート制限" "$TOOLS"
contains "MCP_MAX_LIMIT=10 が inputSchema に反映されている" '"maximum":10' "$TOOLS"
contains "read_only_hint が申告されている" '"readOnlyHint":true' "$TOOLS"

SRC=$(rpc "$SRV" tok-a '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"list_search_sources","arguments":{}}}')
contains "list_search_sources が structuredContent を返す" '"structuredContent"' "$SRC"
contains "list_search_sources が 4 ソースを返す" '"hackernews"' "$SRC"

# 上限超えはサーバーに届く前にスキーマで弾かれ、外部 API に到達しない
OVER=$(rpc "$SRV" tok-a '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"search","arguments":{"query":"x","limit":999}}}')
contains "limit=999 が拒否される（契約としての強制）" "isError" "$OVER"

# ---------------------------------------------------------------- Phase 4

phase "Phase 4: 外部 API への実疎通"

if [[ "${E2E_SKIP_NETWORK:-0}" == "1" ]]; then
  printf '  SKIP (E2E_SKIP_NETWORK=1)\n'
else
  REAL=$(rpc "$SRV" tok-a '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"search","arguments":{"query":"rust tui","sources":["github"],"limit":2}}}')
  contains "コンテナから外部 API を検索できる" '"url"' "$REAL"
  contains "検索結果が github から返る" 'github.com' "$REAL"
fi

podman rm -f "$SRV" >/dev/null 2>&1

# ---------------------------------------------------------------- Phase 5

phase "Phase 5: Deployment マニフェストを podman kube play で起動"

# OpenShift クラスタが無いため、kustomize の出力から podman が解釈できる
# 3 種（ConfigMap / Service / Deployment）だけを取り出して起動する。
# Route / NetworkPolicy / HPA / PDB は podman では検証できない。
if ! kubectl kustomize "$REPO_ROOT/search-mcp/deploy/openshift/" > "$WORK/all.yaml" 2>/dev/null; then
  ng "kustomize のレンダリング" "kubectl kustomize に失敗した"
else
  ok "kustomize のレンダリング"

  awk '
    BEGIN { RS="\n---\n"; ORS="" }
    /\nkind: (ConfigMap|Service|Deployment)\n/ { print (n++ ? "\n---\n" : "") $0 }
  ' "$WORK/all.yaml" > "$WORK/kube.yaml"

  cat > "$WORK/secret.yaml" <<'YAML'
apiVersion: v1
kind: Secret
metadata:
  name: search-mcp-auth
  namespace: search-mcp
type: Opaque
stringData:
  tokens: "e2e-token-1,e2e-token-2"
YAML

  # マニフェストはクラスタ内レジストリを指すので、ローカルイメージに別名を付ける
  podman tag "$IMAGE" "$OCP_IMAGE" >/dev/null 2>&1

  if podman kube play --network "$NET" "$WORK/secret.yaml" "$WORK/kube.yaml" >/dev/null 2>&1; then
    ok "podman kube play が Deployment を起動できる"
  else
    ng "podman kube play が Deployment を起動できる" "$(podman kube play --network "$NET" "$WORK/secret.yaml" "$WORK/kube.yaml" 2>&1 | tail -3)"
  fi

  # Deployment の probe は podman の healthcheck に変換される。
  # (healthy) になれば、probe のパス・ポート・タイミングが妥当だったことになる。
  STATUS=""
  for _ in $(seq 60); do
    STATUS=$(podman ps --filter name=search-mcp-pod-server --format '{{.Status}}')
    [[ "$STATUS" == *"(healthy)"* ]] && break
    [[ "$STATUS" == *"(unhealthy)"* ]] && break
    sleep 1
  done
  contains "Deployment の probe が healthy になる" "(healthy)" "$STATUS"

  # Pod の DNS 名は search-mcp-pod だが、ConfigMap の MCP_ALLOWED_HOSTS は
  # Service 名（search-mcp:8080）を許可している。Host ヘッダで Service 経由を模す。
  check "ConfigMap 由来の設定で /healthz が応答する" "200" \
    "$(cc curl -s -m 5 -o /dev/null -w '%{http_code}' http://search-mcp-pod:8080/healthz)"

  POD_INIT=$(cc curl -s -m 10 -X POST http://search-mcp-pod:8080/mcp \
    -H 'Host: search-mcp:8080' -H 'Authorization: Bearer e2e-token-1' \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    -d "$INIT")
  contains "Secret 由来のトークンで認証が通る" '"serverInfo"' "$POD_INIT"

  check "ConfigMap の MCP_ALLOWED_HOSTS に無い Host は拒否される" "421" \
    "$(cc curl -s -m 5 -o /dev/null -w '%{http_code}' -X POST http://search-mcp-pod:8080/mcp \
        -H 'Host: evil.example.com' -H 'Authorization: Bearer e2e-token-1' \
        -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{}')"
fi

# ---------------------------------------------------------------- 結果

printf '\n\033[1m== 結果\033[0m\n'
printf '  PASS: %d\n  FAIL: %d\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]] || exit 1
