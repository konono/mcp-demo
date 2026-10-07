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

### 1.6 検証状況（opencode 1.18.34 で実機確認済み）

この節の設定は**実際に opencode から接続して確認してあります**。
確認環境: opencode 1.18.34 / モデル `qwen36-35b-a3b`（OpenAI 互換ゲートウェイ）。
サーバー側は 2 通りで確認しました。

1. `uv run search-mcp` でローカル起動（`127.0.0.1:8080`、DNS rebinding 保護 無効）
2. **コンテナ**（`podman run`、固定 IP `10.89.7.10:8080`、**DNS rebinding 保護 有効**、
   OpenShift の `restricted-v2` SCC 相当の制約つき:
   `--user 1000670000:0 --read-only --cap-drop ALL --security-opt no-new-privileges`）

2 のほうが本番に近い構成です。再現手順は
[../examples/README.md](../examples/README.md)、設定は
[../examples/opencode.local.json](../examples/opencode.local.json)。

| 確認したこと | 結果 |
|---|---|
| `"type": "remote"` でサーバーが登録される | ✅ `search` として認識された |
| `headers` の `{env:SEARCH_MCP_TOKEN}` 展開 | ✅ 環境変数から解決された |
| モデルからツールが見える | ✅ |
| ツールが実際に呼べる | ✅ `{"query":"asyncio","sources":["github"],"limit":3}` が通った |
| **スキーマの上限がクライアント経由でも効く** | ✅ `limit=100` が Pydantic で弾かれ、エラーがモデルまで届いた |

弾かれたときモデルが受け取るメッセージ:

```
Error executing tool search: 1 validation error for searchArguments
limit
  Input should be less than or equal to 20 [type=less_than_equal, input_value=100, input_type=int]
```

`docs/skill-to-mcp.md` の前提（description は「お願い」、スキーマは「強制」）が、
実クライアント経由で成立していることをここで確認しています。

コンテナ構成（上記 2）では、加えて次も確認しました。

| 確認したこと | 結果 |
|---|---|
| 任意 UID / read-only rootfs で起動する | ✅ `uid=1000670000(1000670000) gid=0(root)`、`/` への書き込みは拒否 |
| **DNS rebinding 保護 有効のまま opencode から使える** | ✅ `MCP_ALLOWED_HOSTS=10.89.7.10:8080` |
| 許可外 Host は弾かれる | ✅ `421 Misdirected Request` / `Invalid Host header` |
| `/healthz` は Host 検証を受けない | ✅ 許可外 Host でも 200 |

未確認: **Route 経由（TLS + 外部ホスト名 + OpenShift Router）**。
上記はすべて平文 HTTP です。TLS 終端と Router のタイムアウトは試せていません。
確かめる手順は [verification-plan.md](verification-plan.md) §2〜3 にあります。

### 1.6.1 Host 検証を curl で試すときの注意

不正なリクエストは **Host 検証より先に 400 で弾かれます。**
`-d '{}'` だけで投げると 421 ではなく 400 が返り、
「保護が効いていない」と誤読します。`Accept` まで正しく付けてください。

```bash
# 400。Host 検証に到達していない
curl -X POST "http://$HOST/mcp" -H 'Host: evil.example.com' -d '{}'

# 421 Misdirected Request / Invalid Host header
curl -X POST "http://$HOST/mcp" -H 'Host: evil.example.com' \
  -H "Authorization: Bearer $SEARCH_MCP_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

認証（401）のほうは最も外側のミドルウェアなので `-d '{}'` でも確認できます。

### 1.7 ツール名にサーバー名の接頭辞が付く

opencode はツールを `<MCP サーバー名>_<ツール名>` で登録します。
`opencode.json` で `"search"` という名前にしたので、実際の呼び出しは
**`search_search`** / **`search_list_search_sources`** になります。

プロンプトやエージェント定義でツール名を直接指定する場合は接頭辞込みで書いてください。
サーバー名を `search-mcp` にすると `search-mcp_search` になります。

### 1.8 トークンが違うとき、エラーは出ません

**これは運用上の罠です。** トークンが間違っていると、opencode は
MCP サーバーの登録に失敗しますが、**エージェントは何も言わずに続行します。**
ツールが最初から存在しなかったかのように振る舞い、
`WebFetch` など別の手段で答えを作って returns します。

実際に `SEARCH_MCP_TOKEN=wrong-token` で試したときの挙動:

- サーバー側ログ: `POST /mcp ... 401 Unauthorized`
- opencode: `search_search` を提示せず、代わりに Wikipedia API を直接 WebFetch
- ユーザーから見ると**普通に成功したように見える**

認証失敗は 401 を見ないと分かりません。つながったつもりで使い始める前に、
必ず 1.5 の疎通確認か、「利用可能な MCP ツールを列挙して」で
`search_search` が出ることを確かめてください。

なお 401 を返すと opencode は OAuth ディスカバリに進みます
（`/.well-known/oauth-authorization-server`、`/.well-known/openid-configuration`、
`POST /register`）。本サーバーはこれらにも 401 を返し、クライアントは諦めます。
共有トークン運用では意図どおりの挙動です（理由は `auth.py` の冒頭コメント）。

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
| **エラーは出ないがツールが使われない** | 認証失敗。opencode は黙って別の手段に逃げる（1.8 参照）。サーバー側ログの 401 を見る |
| プロンプトで `search` を指定しても呼ばれない | opencode のツール名は `search_search`（1.7 参照） |
