# クライアントからの接続

接続先は 2 通りある。どちらを使うかで URL と TLS の扱いが変わる。

| クライアントの居場所 | 経路 | URL |
|---|---|---|
| virt 上の VM（opencode） | OpenShift Route（edge TLS） | `https://<route-host>/mcp` |
| クラスタ内の Pod（agent framework） | Service（ClusterIP, 平文） | `http://search-mcp.search-mcp.svc.cluster.local:8080/mcp` |

どちらも `Authorization: Bearer <token>` が必要。

---

## 1. virt 上の VM で動く opencode から

### 1.1 接続情報を取り出す

クラスタ側で:

```bash
oc get route search-mcp -n search-mcp -o jsonpath='{.spec.host}{"\n"}'
oc get secret search-mcp-auth -n search-mcp -o jsonpath='{.data.tokens}' | base64 -d
```

### 1.2 opencode の設定

opencode はリモート MCP サーバーを `type: "remote"` で設定する。
プロジェクト単位なら `opencode.json`、ユーザー全体なら
`~/.config/opencode/opencode.json` に書く。

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "search": {
      "type": "remote",
      "url": "https://search-mcp-search-mcp.apps.example.com/mcp",
      "enabled": true,
      "headers": {
        "Authorization": "Bearer {env:SEARCH_MCP_TOKEN}"
      }
    }
  }
}
```

トークンを設定ファイルに直書きしないこと。`{env:...}` で環境変数から読み、
VM 側ではシェルのプロファイルや systemd の `EnvironmentFile` で与える:

```bash
# /etc/opencode.env （chmod 600）
SEARCH_MCP_TOKEN=<token>
```

`examples/opencode.json` に同じものを置いてある。

### 1.3 既存の Skill を外す

同じ VM に `search-demo` の Skill 版も入っていると、
**同じ機能が Skill とツールの 2 経路でモデルに見える**。
どちらを呼ぶか不定になり、Skill 側はローカルに `search_demo.py` と Python が
必要なので失敗しうる。MCP に移したら Skill 版は消す:

```bash
rm -rf ~/.config/opencode/skill/public-api-search
# プロジェクト内に置いている場合は search-demo/.opencode/skill/ ごと
```

### 1.4 VM 側のネットワーク要件

- Route のホスト名が VM から名前解決できること（クラスタの `*.apps` ドメイン）
- 443/tcp が通ること
- Router の証明書が VM の信頼ストアに入っていること。
  自己署名やプライベート CA の場合は CA を入れる:

```bash
oc get secret -n openshift-ingress router-certs-default \
  -o jsonpath='{.data.tls\.crt}' | base64 -d | sudo tee /etc/pki/ca-trust/source/anchors/openshift-router.crt
sudo update-ca-trust
```

### 1.5 疎通確認

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST "https://$HOST/mcp" -d '{}'                      # 401 が返れば到達している
curl -s "https://$HOST/mcp" \
  -H "Authorization: Bearer $SEARCH_MCP_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

---

## 2. クラスタ内の Pod で動く agent framework から

Route を経由する必要はない。Service に直接繋ぐほうが速く、
TLS 終端も CA 配布も要らない。

### 2.1 namespace にラベルを付ける

NetworkPolicy `search-mcp-allow-agent-namespaces` は、
ラベルの付いた namespace からの ingress だけを許可する。

```bash
oc label namespace <agent-namespace> mcp-client=search-mcp
```

これを忘れると接続がタイムアウトする（401 ではなく無応答になる）。

### 2.2 トークンを配る

Secret は namespace を跨げないので、エージェント側の namespace にコピーする:

```bash
TOKEN=$(oc get secret search-mcp-auth -n search-mcp -o jsonpath='{.data.tokens}' | base64 -d | cut -d, -f2)
oc create secret generic search-mcp-client -n <agent-namespace> \
  --from-literal=token="$TOKEN"
```

サーバー側の `tokens` にカンマ区切りで複数入れてあるなら、
**エージェント用には 2 本目を配る**。VM 側と分けておくと片方だけ失効できる。

### 2.3 Pod の設定

`examples/agent-pod.yaml` に Deployment の例がある。要点:

```yaml
env:
  - name: SEARCH_MCP_URL
    value: http://search-mcp.search-mcp.svc.cluster.local:8080/mcp
  - name: SEARCH_MCP_TOKEN
    valueFrom:
      secretKeyRef:
        name: search-mcp-client
        key: token
```

### 2.4 接続コード

MCP Python SDK 2.x を使う場合:

```python
import os
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

url = os.environ["SEARCH_MCP_URL"]
token = os.environ["SEARCH_MCP_TOKEN"]

async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as http:
    async with Client(streamable_http_client(url, http_client=http)) as session:
        tools = await session.list_tools()
        result = await session.call_tool("search", {"query": "asyncio", "limit": 3})
        print(result.structured_content)
```

動く完全版は `examples/smoke_client.py`。

### 2.5 フレームワーク別のつなぎ方

**Claude Agent SDK** — MCP サーバーを設定で渡す:

```python
from claude_agent_sdk import ClaudeAgentOptions

options = ClaudeAgentOptions(
    mcp_servers={
        "search": {
            "type": "http",
            "url": os.environ["SEARCH_MCP_URL"],
            "headers": {"Authorization": f"Bearer {os.environ['SEARCH_MCP_TOKEN']}"},
        }
    },
    allowed_tools=["mcp__search__search", "mcp__search__list_search_sources"],
)
```

**LangChain / LangGraph** — `langchain-mcp-adapters` で LangChain の Tool に変換する:

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient({
    "search": {
        "transport": "streamable_http",
        "url": os.environ["SEARCH_MCP_URL"],
        "headers": {"Authorization": f"Bearer {os.environ['SEARCH_MCP_TOKEN']}"},
    }
})
tools = await client.get_tools()
```

どのフレームワークでも必要なのは **URL とヘッダだけ**。
`search_demo.py` も Python ランタイムもクライアント側には要らない
——これが Skill 版からの最大の変化。

---

## 3. つながらないときの切り分け

| 症状 | 原因の候補 |
|---|---|
| 接続がタイムアウトする（クラスタ内） | NetworkPolicy。namespace に `mcp-client=search-mcp` ラベルが無い |
| `401 Unauthorized` | トークン不一致。Secret 更新後に Pod を再起動したか確認 |
| `421 Misdirected Request` + `Invalid Host header` | DNS rebinding 保護。ConfigMap の `MCP_ALLOWED_HOSTS` に Route ホストが無い。`/healthz` には適用されないので「probe は通るのに `/mcp` だけ落ちる」形で現れる |
| TLS 検証エラー（VM から） | Router の CA が VM の信頼ストアに無い（1.4 参照） |
| `/healthz` は 200 だが `/mcp` が 503 | probe は通るがアプリの lifespan が起動していない。Pod のログを見る |
| セッションが途中で切れる | `MCP_STATELESS_HTTP=false` のまま replica が複数。true に戻すか Route で cookie 固定する |
| 長いリクエストが切れる | Route の `haproxy.router.openshift.io/timeout` を延ばす |
