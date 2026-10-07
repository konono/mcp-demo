# examples

| ファイル | 用途 | 検証状況 |
|---|---|---|
| `opencode.local.json` | ローカル／コンテナで動かした `search-mcp` に opencode からつなぐ | ✅ **実機で接続確認済み**（opencode 1.18.34） |
| `opencode.json` | OpenShift の Route 経由でつなぐ | ❌ 未検証（形式は `opencode.local.json` と同じ。URL が HTTPS の Route ホストになるだけ） |
| `agent-pod.yaml` | クラスタ内の agent framework Pod から使う | ❌ 未検証 |
| `smoke_client.py` | MCP SDK で疎通だけ見るスクリプト | ✅ |

## `opencode.local.json` の再現手順

これは**実際にこの手順で動かして確認したもの**です。

### 1. イメージをビルドする

build context はリポジトリルート（`search-demo/` も要るため）。

```bash
cd <リポジトリルート>
podman build -f Containerfile -t search-mcp:1.0.0 .
```

### 2. コンテナを起動する

`opencode.local.json` の URL が `10.89.7.10:8080` なのは、**IP を固定したいから**です。
DNS rebinding 保護を有効にすると `MCP_ALLOWED_HOSTS` に接続先を書く必要があり、
IP が起動のたびに変わると書けません。専用ネットワークを作って固定します。

```bash
podman network create --subnet 10.89.7.0/24 mcp-net

podman run -d --name search-mcp --network mcp-net --ip 10.89.7.10 \
  --user 1000670000:0 --read-only --tmpfs /tmp \
  --cap-drop ALL --security-opt no-new-privileges \
  -e MCP_AUTH_TOKENS=container-token \
  -e MCP_JSON_RESPONSE=true \
  -e MCP_DNS_REBINDING_PROTECTION=true \
  -e MCP_ALLOWED_HOSTS=10.89.7.10:8080 \
  search-mcp:1.0.0
```

`--user 1000670000:0 --read-only --cap-drop ALL` は OpenShift の
`restricted-v2` SCC 相当の制約です。本番と同じ条件で動くことを確かめるために付けています。

### 3. 疎通を確認する

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://10.89.7.10:8080/healthz   # 200
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://10.89.7.10:8080/mcp -d '{}'   # 401
```

### 4. opencode からつなぐ

```bash
mkdir -p ~/oc-mcp-test && cd ~/oc-mcp-test
cp <リポジトリ>/search-mcp/examples/opencode.local.json ./opencode.json
# opencode.json に provider / model の定義を足す（下記「モデルの設定」参照）

export SEARCH_MCP_TOKEN=container-token
opencode run "search ツールで GitHub から 'kubernetes operator' を 3 件検索して"
```

成功すると次のように出ます。

```
⚙ search_search {"query":"kubernetes operator","sources":["github"],"limit":3}
1. **prometheus-operator/prometheus-operator** — https://github.com/prometheus-operator/prometheus-operator
...
```

## モデルの設定

`opencode.local.json` には `mcp` セクションしか入れていません。
モデルの設定は環境ごとに違うためです。OpenAI 互換ゲートウェイを使う場合は
同じ `opencode.json` に次をマージしてください。

```json
{
  "provider": {
    "litellm": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "MaaS Gateway",
      "options": {
        "baseURL": "https://<ゲートウェイ>/v1",
        "apiKey": "{env:LLM_TOKEN}"
      },
      "models": {
        "<モデル名>": { "name": "<モデル名>", "limit": { "context": 60000, "output": 4000 } }
      }
    }
  },
  "model": "litellm/<モデル名>"
}
```

推論モデル（Qwen3 系など）を使う場合は thinking を切らないと
出力枠を思考が食い潰します。詳細は [../../PROMPT.md](../../PROMPT.md) の
「実行環境の要件」を参照。

## つまずきやすいところ

### トークンが違ってもエラーが出ない

opencode は MCP サーバーの登録に失敗しても**黙って続行**し、
`WebFetch` など別の手段で回答を作ります。成功と区別がつきません。
`docs/clients.md` §1.8 を参照。

まずツールが見えているかを確認してください。

```bash
opencode run "利用可能な MCP ツールの名前を列挙してください。ツールは呼ばないでください。"
```

`search_search` が出なければつながっていません。

### ツール名には接頭辞が付く

`mcp` のキーを `search` にしたので、実際のツール名は **`search_search`** です
（`<サーバー名>_<ツール名>`）。

### publish したポートに届かない場合がある

DooD 構成（コンテナの中から `/run/container.sock` 経由で podman を使う）では、
`-p 18080:8080` で publish したポートは**ホスト側**に出ます。
podman を叩いているコンテナからは届きません。
上の手順でコンテナ IP を直接使っているのはこのためです。

### `-d '{}'` では Host 検証を試せない

`MCP_ALLOWED_HOSTS` の動作を確認したいときは、
`Accept` ヘッダまで正しく付けてください。不正なリクエストは
Host 検証より**先に** 400 で弾かれます。

```bash
# 400 が返る（Host 検証まで到達していない）
curl -X POST http://10.89.7.10:8080/mcp -H 'Host: evil.example.com' -d '{}'

# 421 Misdirected Request / Invalid Host header が返る
curl -X POST http://10.89.7.10:8080/mcp -H 'Host: evil.example.com' \
  -H 'Authorization: Bearer container-token' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```
