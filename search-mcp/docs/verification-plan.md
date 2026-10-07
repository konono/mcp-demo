# 未検証項目の潰し方

クラスタが無い環境で作ったため、**実クラスタでしか確かめられない項目が残っている。**
ここには、それぞれを「どう確かめるか」「何が返れば成功か」「失敗したら何を疑うか」を書く。

検証済みの項目は [../README.md](../README.md) の「検証状況」を参照。
ここに書いてあるのは**まだ誰も実行していない手順**であり、
手順自体も未検証である（コマンドの typo が残っている可能性がある）。

| # | 未検証項目 | 所要 | 前提 |
|---|---|---|---|
| 1 | マニフェストの API スキーマ | 1 分 | クラスタへの接続 |
| 2 | Route 経由の疎通（TLS + 外部ホスト名） | 5 分 | 配備済み |
| 3 | Route 経由で opencode からつなぐ | 10 分 | 2 が通ること |
| 4 | クラスタ内 Pod（agent framework）から | 15 分 | 配備済み |
| 5 | NetworkPolicy ×4 | 15 分 | 4 が通ること |
| 6 | HPA | 20 分 | metrics-server |
| 7 | PodDisruptionBudget | 5 分 | replicas 2 以上 |
| 8 | PROMPT.md の STEP 6〜9 | 1 時間 | モデルと作業環境 |

**1 → 2 → 3 の順に進めること。** 1 が通らなければ配備できず、
2 が通らなければ 3 は必ず失敗する。切り分けの手間が変わる。

---

## 1. マニフェストの API スキーマ

`podman kube play` は独自パーサなので、**フィールド名の typo や
apiVersion の誤りを見逃す。** サーバー側スキーマで検証する。

```bash
oc apply --dry-run=server -k search-mcp/deploy/openshift/
```

**成功**: 全リソースが `... (server dry run)` で列挙される（12 リソース）。

**失敗したら**:

| 出力 | 原因 |
|---|---|
| `error validating data: unknown field "xxx"` | フィールド名の typo |
| `no matches for kind "X" in version "Y"` | apiVersion がクラスタのバージョンと不一致 |
| `namespaces "search-mcp" not found` | `--dry-run=server` は Namespace を作らない。先に `oc new-project search-mcp` |

`--dry-run=client` では**不十分**。クライアント側は未知フィールドを素通しする。

---

## 2. Route 経由の疎通（TLS + 外部ホスト名）

ここが本番構成との最大の差分。コンテナ検証は**すべて平文 HTTP** だった。

```bash
HOST=$(oc get route search-mcp -o jsonpath='{.spec.host}')
TOKEN=$(oc get secret search-mcp-auth -o jsonpath='{.data.tokens}' | base64 -d | cut -d, -f1)

# 2-1. 認証なし → 401
curl -s -o /dev/null -w '%{http_code}\n' -X POST "https://$HOST/mcp" -d '{}'

# 2-2. 正しいトークン → tools/list が返る
curl -s "https://$HOST/mcp" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

**成功**: 2-1 が `401`、2-2 で `search` と `list_search_sources` が返る。

**ここで一番出やすいのは 421。**

```
421 Misdirected Request / Invalid Host header
```

`MCP_ALLOWED_HOSTS` に Route のホスト名が入っていない。
ConfigMap を実際のホスト名に合わせる（`docs/deploy-openshift.md` 手順 3）。
`/healthz` には適用されないため、**probe は成功しているのに `/mcp` だけ落ちる**
という見え方になる。401 でも 400 でもなく 421 である。

なお `Accept` ヘッダを省くと Host 検証より先に **400** で弾かれる。
421 を確認したいときは上記のヘッダを全部付けること（コンテナ検証で踏んだ）。

**その他の失敗**:

| 症状 | 疑うもの |
|---|---|
| TLS 検証エラー | Router の CA がクライアントの信頼ストアに無い（`docs/clients.md` §1.4） |
| 503 | Pod が Ready でない。`oc get pods`、`oc logs` |
| タイムアウト | Route の `haproxy.router.openshift.io/timeout`（既定 30s） |

---

## 3. Route 経由で opencode からつなぐ

2 が通ってから。平文コンテナでの接続は確認済みなので、
**ここで新しく確かめているのは TLS と外部ホスト名だけ**。

`examples/opencode.local.json` の URL を Route に差し替える
（= `examples/opencode.json` の形）。

```bash
export SEARCH_MCP_TOKEN=$TOKEN
opencode run "利用可能な MCP ツールの名前を列挙してください。ツールは呼ばないでください。"
```

**成功**: `search_search` と `search_list_search_sources` が挙がる。
ツール名には**サーバー名の接頭辞が付く**（`opencode.json` のキーが `search` のため）。

次に実際に呼ばせる。

```bash
opencode run "search ツールで GitHub から 'kubernetes operator' を 3 件検索して"
```

**成功**: `⚙ search_search {...}` が表示され、結果が返る。
あわせて `oc logs deploy/search-mcp` に
`INFO search_mcp.server search query='kubernetes operator' ...` が出ること。

> **ツールが挙がらなくても、opencode はエラーを出さない。**
> 認証に失敗すると MCP の登録を諦め、`WebFetch` など別の手段で回答を作る。
> ユーザーからは成功と区別がつかない。必ず**サーバー側のログで 401 を確認**すること。
> 詳細は `docs/clients.md` §1.8。

最後にスキーマ強制を確認する。これが通れば、このリポジトリの主張
（description はお願い、スキーマは強制）が本番構成でも成立したことになる。

```bash
opencode run "search ツールを limit=100 で呼んでください。エラーをそのまま見せて。query は 'python'、sources は github だけで。"
```

**成功**: 次のエラーがモデルまで届く。

```
Input should be less than or equal to 20 [type=less_than_equal, input_value=100, input_type=int]
```

---

## 4. クラスタ内 Pod（agent framework）から

設定は `docs/clients.md` §2、Pod の例は `examples/agent-pod.yaml`。
Route を経由せず **Service の ClusterIP** で入る経路を確かめる。

```bash
oc label namespace <agent-namespace> mcp-client=search-mcp

oc run mcp-probe -n <agent-namespace> --rm -it --restart=Never \
  --image=registry.access.redhat.com/ubi9/ubi-minimal:latest -- \
  curl -s -o /dev/null -w '%{http_code}\n' \
  http://search-mcp.search-mcp.svc.cluster.local:8080/healthz
```

**成功**: `200`。

次に認証込みで `/mcp` を叩く。

```bash
oc run mcp-probe -n <agent-namespace> --rm -it --restart=Never \
  --image=registry.access.redhat.com/ubi9/ubi-minimal:latest -- \
  curl -s http://search-mcp.search-mcp.svc.cluster.local:8080/mcp \
    -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

**成功**: ツール一覧が返る。

**注意**: クラスタ内は**平文 HTTP**（`http://`、ポート 8080）。
Service 名は `<service>.<namespace>.svc.cluster.local`。
`MCP_ALLOWED_HOSTS` にこの FQDN も入れる必要がある点に注意
（Route のホスト名だけだと 421 になる）。カンマ区切りで両方書く。

---

## 5. NetworkPolicy ×4

4 が通ってから。**「通ること」だけ見ても検証にならない。
拒否されるべき経路が拒否されることを見る。**

```bash
# 5-1. ラベルの無い namespace からは届かない（拒否の確認）
oc create namespace np-test
oc run deny-probe -n np-test --rm -it --restart=Never \
  --image=registry.access.redhat.com/ubi9/ubi-minimal:latest -- \
  curl -s -m 5 -o /dev/null -w '%{http_code}\n' \
  http://search-mcp.search-mcp.svc.cluster.local:8080/healthz
```

**成功（= 拒否されること）**: タイムアウトして `000`。
`200` が返ったら **NetworkPolicy が効いていない**。CNI がポリシーを
サポートしているか確認する（OpenShift SDN / OVN-Kubernetes なら対応）。

```bash
# 5-2. ラベルを付けると届く（許可の確認）
oc label namespace np-test mcp-client=search-mcp
# 同じ curl を再実行 → 200

# 後片付け
oc delete namespace np-test
```

**5-3. Route 経由が生きていること**（Router からの ingress 許可）:
手順 2 をもう一度実行する。default-deny を入れた後に
Route が落ちていないかの確認になる。

**egress は制限していない。** `policyTypes: ["Ingress"]` のみなので、
Pod から Wikipedia / GitHub への外向き通信はポリシーの影響を受けない。
外部 API が引けない場合は NetworkPolicy ではなく、
クラスタのプロキシ設定か DNS を疑うこと。

---

## 6. HPA

`metrics-server` が入っていないと HPA は動かない。まず確認する。

```bash
oc get apiservice v1beta1.metrics.k8s.io
oc adm top pods -n search-mcp     # 値が出れば metrics は取れている
oc get hpa search-mcp
```

**成功**: `TARGETS` が `<n>%/70%` の形で表示される。
`<unknown>/70%` なら metrics が取れていない（この状態ではスケールしない）。

負荷をかけて増えることを見る。

```bash
oc run load -n search-mcp --rm -it --restart=Never \
  --image=registry.access.redhat.com/ubi9/ubi-minimal:latest -- \
  sh -c 'while true; do
    curl -s -o /dev/null http://search-mcp:8080/healthz
  done'

# 別ターミナルで
oc get hpa search-mcp -w
```

**成功**: replicas が 2 から増える（上限 6）。

**注意**: `/healthz` は軽すぎて CPU 70% に届かない可能性が高い。
その場合は `/mcp` に実際の検索を投げる。ただし**外部 API を叩くので
レート制限に注意**すること。スケールダウンは既定で 5 分の安定化待ちがある。

---

## 7. PodDisruptionBudget

`minAvailable: 1`。ドレイン中も最低 1 Pod が残ることを確かめる。

```bash
oc get pdb search-mcp
```

**成功**: `ALLOWED DISRUPTIONS` が `1` 以上（replicas 2、minAvailable 1 のため）。

実際にドレインして確かめる場合:

```bash
NODE=$(oc get pods -n search-mcp -o jsonpath='{.items[0].spec.nodeName}')
oc adm drain "$NODE" --ignore-daemonsets --delete-emptydir-data --dry-run=server
```

**成功**: PDB 違反のエラーが出ない。

> **実際の `drain` は他のワークロードも退避させる。**
> 共用クラスタでは `--dry-run=server` までにとどめること。

`ALLOWED DISRUPTIONS` が `0` の場合、replicas が 1 に落ちていないか
（HPA の下限は 2）、Pod が Ready になっているかを確認する。

---

## 8. PROMPT.md の STEP 6〜9

実機検証では STEP 3〜5（仕分けとコード生成）までしか実行していない。
STEP 6（周辺ファイル）・7（テスト）・8（コンテナ）・9（ドキュメント）は未実行。
生成された `server.py` も**起動していないし構文検証もしていない**。

確かめ方:

```bash
# 1. PROMPT.md の「実行環境の要件」を満たすか測る（特に推論モデル）
#    thinking が切れているかは、短い質問の消費トークンで分かる
#    切れていれば 100 トークン未満、切れていなければ 400 以上

# 2. 移植させる
opencode run "PROMPT.md を読んで、その指示に従って <Skill のパス> を MCP サーバーに移植してください。"

# 3. 生成物を実際に動かす
cd <出力先> && uv sync --extra dev && uv run pytest
MCP_AUTH_TOKENS=dev-token uv run <サーバー名>
```

**成功の基準**: `uv run pytest` が通り、サーバーが起動して
`tools/list` が返ること。「それらしいコードが出た」は成功ではない。

**既知の弱点**（1 回の試行で観測したもの。再現性は未確認）:

| 現象 | 対処 |
|---|---|
| 「## 使い方」のコードブロックが仕分け表から落ちる | PROMPT.md STEP 3 に注意を追記済み。それでも落ちたら指摘する |
| `str` 型なのに既定値が `None` | 生成後にレビューする |
| スキーマ側の上限（`max_length` など）が実装から漏れる | 仕分け表に書いた制約がコードに全部落ちているか突き合わせる |

3 行目が特に重要。**仕分け表では正しく SCHEMA と書いたのに、
コードではガードだけになる**ことがある。表とコードを 1 行ずつ照合すること。

---

## 検証したら

結果を [../README.md](../README.md) の「検証状況」に反映し、
❌ を ✅ に変える。**失敗した場合は ✅ にせず、何がどう失敗したかを残す。**
このリポジトリは「検証したふりをしない」ことを方針にしている。
