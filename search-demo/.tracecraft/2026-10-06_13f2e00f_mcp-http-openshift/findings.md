# Findings

> 作業タイトル: search-demo を MCP Streamable HTTP サーバー化し OpenShift に配備可能にする
> 開始日時: 2026-10-06

---

## Finding: MCP Python SDK は 2.x になっており FastMCP は MCPServer に改名されている

### 調べた理由
MCP サーバーを書くにあたり、記憶にある `mcp.server.fastmcp.FastMCP` が現行 API かどうか未確認だった。

### 調査方法
`/tmp/mcpenv` に `uv pip install mcp` でインストールし、`python -c "from mcp.server.fastmcp import FastMCP"` を実行。続けて `inspect.signature` で各 API を出力。

### わかった事実
- インストールされたのは `mcp 2.3.0`
- `mcp.server.fastmcp` は import 時に専用のエラーを投げるスタブになっている
- 現行の入口は `from mcp.server.mcpserver import MCPServer`
- `MCPServer.streamable_http_app()` の引数: `streamable_http_path='/mcp'`, `json_response=False`, `stateless_http=False`, `event_store=None`, `max_request_body_size=4194304`, `session_idle_timeout=1800`, `max_sessions=10000`, `transport_security=None`, `host='127.0.0.1'`
- `MCPServer.custom_route(path, methods, name=None, include_in_schema=True)` で任意の HTTP ルートを追加できる
- クライアント側は高レベル API `mcp.Client` があり、`mcp.client.streamable_http.streamable_http_client(url, http_client=...)` が Transport を返す
- SDK は `httpx` ではなく `httpx2` を使う

### 根拠
`mcp/server/fastmcp.py` が出したエラーメッセージ全文:

```
ModuleNotFoundError: No module named 'mcp.server.fastmcp'. This is mcp 2.x,
where FastMCP was renamed to MCPServer (from mcp.server.mcpserver import MCPServer)
and other APIs changed; see the migration guide at
https://py.sdk.modelcontextprotocol.io/v2/migration/#fastmcp-renamed-to-mcpserver
or pin 'mcp<2' to keep running v1 code.
```

および `inspect.signature(MCPServer.streamable_http_app)` / `inspect.signature(streamable_http_client)` の出力。
`httpx2` は `uv run python -c "import httpx2; print(httpx2.__version__)"` で `2.13.1` を確認。

### 作業への影響
- `pyproject.toml` の依存を `mcp>=2.3,<3` に固定した（1.x と API 非互換のため上限を切る必要がある）
- テストとサンプルクライアントを `httpx` ではなく `httpx2` で書いた
- `stateless_http` と `transport_security` が SDK 標準機能として使えるため、水平スケールと DNS rebinding 対策を自前実装せずに済んだ

### 未確認事項
- `mcp` 2.x の今後のマイナー更新で `streamable_http_app` の引数が変わる可能性。`uv.lock` で固定しているが、`pyproject.toml` の範囲指定は `<3` までしか切っていない

---

## Finding: MCP SDK 2.x のモデルフィールドはスネークケース

### 調べた理由
テストで `result.structuredContent` にアクセスして `AttributeError` になった。

### 調査方法
`mcp_types.Tool.model_fields` と `mcp_types.CallToolResult.model_fields` を出力。

### わかった事実
- `Tool`: `name, title, description, input_schema, execution, output_schema, icons, annotations, meta`
- `CallToolResult`: `meta, content, structured_content, is_error, result_type`
- `ToolAnnotations` はサーバー側で `readOnlyHint=` のキャメルケースでも構築できる（pydantic の alias が効く）が、読み出し側は `read_only_hint`

### 根拠
`uv run python -c "from mcp_types import Tool, CallToolResult; print([f for f in Tool.model_fields]); print([f for f in CallToolResult.model_fields])"` の出力。
また、`ToolAnnotations(readOnlyHint=True)` で構築したサーバーに対し、テストの `assert search_tool.annotations.read_only_hint is True` が通った（9 passed）。

### 作業への影響
- テストを `structured_content` / `is_error` / `input_schema` / `read_only_hint` に書き換えた
- `server.py` 側も混乱を避けるためスネークケース（`read_only_hint=` など）に統一した

### 未確認事項
JSON ワイヤフォーマット上は MCP 仕様どおりキャメルケース（`structuredContent`）のはずだが、ワイヤを直接確認していない。Python 側の属性名のみ確認した。

---

## Finding: uv sync の既定 editable install はマルチステージビルドで壊れる

### 調べた理由
ビルドしたイメージを `podman run` したら `ModuleNotFoundError: No module named 'search_mcp'` が出た。

### 調査方法
`podman run --rm search-mcp:1.0.0` を実行してトレースバックを確認。

### わかった事実
- `uv sync` はプロジェクト自身を editable で入れる（venv に `/build/search-mcp` を指す `.pth` が残る）
- builder ステージを捨てて `/opt/venv` だけを runtime にコピーすると、`.pth` の参照先が存在せず import に失敗する
- `uv sync --no-editable` にすると実体が venv に入り、runtime ステージ単独で動く

### 根拠
修正前の実行結果:

```
Traceback (most recent call last):
  File "/opt/venv/bin/search-mcp", line 4, in <module>
    from search_mcp.__main__ import main
ModuleNotFoundError: No module named 'search_mcp'
```

`Containerfile` の 2 か所を `uv sync --locked --no-dev --no-editable` に変更して再ビルドしたのち、`podman exec smcp python -c "...urlopen('http://127.0.0.1:8080/healthz')..."` が `health: ok` を返した。

### 作業への影響
`Containerfile` の両ステージに `--no-editable` を付け、理由をコメントとして残した。

### 未確認事項
なし。

---

## Finding: ビルドしたイメージは OpenShift の任意 UID 注入で動く

### 調べた理由
OpenShift の `restricted-v2` SCC は namespace ごとの UID 範囲から任意の UID を注入するため、特定 UID 前提のイメージは起動しない。

### 調査方法
`podman run --rm --user 1000670000:0 -e MCP_AUTH_TOKENS=t search-mcp:1.0.0` を実行。

### わかった事実
UID 1000670000 / GID 0 で正常に起動する。

### 根拠
実行時のログ:

```
2026-10-06 15:33:56,471 INFO search_mcp.app bearer auth enabled (1 token(s) configured)
INFO:     Started server process [1]
INFO:     Waiting for application startup.
2026-10-06 15:33:56,481 INFO mcp.server.streamable_http_manager StreamableHTTP session manager started
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8080
```

`podman ps` で `localhost/search-mcp:1.0.0  Up 6 seconds` を確認。

### 作業への影響
`deployment.yaml` の `securityContext` に `runAsUser` を書かず、`runAsNonRoot: true` のみにした。
あわせて `readOnlyRootFilesystem: true` + `/tmp` の emptyDir、全 capability drop、`seccompProfile: RuntimeDefault` を設定した。

### 未確認事項
`readOnlyRootFilesystem: true` の組み合わせは podman 単体では検証していない（`--read-only` での起動は試していない）。実クラスタでの確認が必要。

---

## Finding: HEALTHCHECK は OCI フォーマットのイメージでは無視される

### 調べた理由
`Containerfile` に `HEALTHCHECK` を書いたところ、ビルド時に警告が出た。

### 調査方法
`podman build` の出力を確認。

### わかった事実
podman の既定出力フォーマット（OCI）では `HEALTHCHECK` が保存されず無視される。`docker` フォーマットを指定しないと効かない。

### 根拠
ビルド出力:

```
level=warning msg="HEALTHCHECK is not supported for OCI image format and will be ignored. Must use `docker` format"
```

### 作業への影響
Kubernetes では Deployment の startup/liveness/readiness probe が使われるため実害はない。
`Containerfile` にはコメントで「podman 単体実行時の目安」と明記し、`docs/deploy-openshift.md` にも記載した。

### 未確認事項
なし。

---

## Finding: kustomize の commonLabels は非推奨で、labels への置換にはセレクタの扱いに注意が要る

### 調べた理由
`kubectl kustomize` が警告を出した。

### 調査方法
`kubectl kustomize .` を実行して出力と警告を確認。

### わかった事実
- `commonLabels` は非推奨。`labels` に移行する
- `labels` の既定は `includeSelectors: false`。明示的に `true` にしない限りセレクタには入らない
- `app.kubernetes.io/version` のような可変ラベルをセレクタに入れると、Deployment の `.spec.selector`（immutable）を変更することになり apply が失敗する

### 根拠
1 回目の出力の先頭行:

```
# Warning: 'commonLabels' is deprecated. Please use 'labels' instead. Run 'kustomize edit fix' to update your Kustomization automatically.
```

`labels: - includeSelectors: false / pairs: ...` に書き換え後、`kubectl kustomize .` が警告なしで 12 リソースを出力した。

### 作業への影響
- `kustomization.yaml` を `labels` + `includeSelectors: false` に変更
- セレクタに使う `app.kubernetes.io/name: search-mcp` は各マニフェストに直接記述した
- 理由を `kustomization.yaml` のコメントに残した

### 未確認事項
`kubectl apply --dry-run=client` は API discovery でクラスタ接続を要求するため実行できなかった。**API スキーマレベルの検証は未実施。**
実クラスタでは `oc apply --dry-run=server -k ...` で確認すべき。

---

## Finding: この実行環境（DooD）では sibling コンテナの publish ポートに到達できない

### 調べた理由
ビルドしたイメージに対してサンプルクライアントを実行しようとして接続エラーになった。

### 調査方法
`podman run -d -p 18081:8080 ...` の後 `curl localhost:18081/healthz` を実行。さらに `--network host` でも試行。

### わかった事実
- `-p` でも `--network host` でも、このエージェントコンテナからは到達できない
- コンテナランタイムのソケット（`/run/container.sock`）はホストのものであり、起動したコンテナはホスト側の sibling になる。publish されるポートはホストの localhost であって、このコンテナの localhost ではない
- `podman exec <container> python -c "...urlopen(...)..."` ならコンテナ内から疎通確認できる

### 根拠
- `curl -s localhost:18081/healthz` が空応答、`curl -w '%{http_code}'` が `000`
- `podman ps` では `Up 7 seconds 0.0.0.0:18081->8080/tcp` と表示されており、コンテナ自体は起動している
- `podman exec smcp python ...` は `health: ok` / `noauth: 401 Bearer realm="search-mcp"` / `uid: 1001` を返した

### 作業への影響
- コンテナの疎通確認は `podman exec` 経由で行った
- MCP クライアントでの完全な疎通確認は、コンテナではなくローカルの `uv run search-mcp` に対して実施した（`search('rust tui')` が 4 ソース混在で 8 件返ることを確認）

### 未確認事項
コンテナイメージに対する MCP クライアント経由の疎通は未実施。ただしコンテナ内からの HTTP 層の確認と、同一コードに対するローカルでの MCP 層の確認は取れている。

---

## Finding: ツール関数のアノテーションに設定値を埋め込む場合、PEP 563 を使えない

### 調べた理由
`Field(le=settings.max_limit)` のようにクロージャ変数を使ったところ、サーバー構築時に例外が出た。

### 調査方法
`build_server(Settings())` を直接呼び、`__cause__` を出力。

### わかった事実
- MCP SDK は `inspect.signature(func, eval_str=True)` でアノテーションを評価する
- `from __future__ import annotations`（PEP 563）があるとアノテーションは文字列になり、評価時にモジュールの globals しか参照されない
- ネストした関数のクロージャ変数（`settings`）は解決できず `NameError` → `InvalidSignature` になる

### 根拠
```
<class 'mcp.server.mcpserver.exceptions.InvalidSignature'>
Unable to evaluate type annotations for callable 'search'
| cause: NameError("name 'settings' is not defined")
```

`src/search_mcp/server.py` から `from __future__ import annotations` を削除したところ、同じコードでテストが通った。

### 作業への影響
- `server.py` でのみ PEP 563 を使わないことにし、その理由をファイル冒頭のコメントに明記した
- 他のモジュール（`settings.py`, `auth.py`, `app.py`）は従来どおり使っている

### 未確認事項
なし。

---

## Finding: 許可されていない Host の拒否は 400 ではなく 421 Misdirected Request

### 調べた理由
E2E テストでコンテナを専用ネットワーク上に置き、`http://e2e-srv:8080/mcp` に
curl したところ、認証は通るはずなのに想定外のステータスが返った。
また、ドキュメント 3 箇所に「400 になる」と記載していたが、
これは**実際に確認した値ではなく推測で書いたもの**だった。

### 調査方法
`MCP_DNS_REBINDING_PROTECTION` を既定（true）、`MCP_ALLOWED_HOSTS` を未設定のまま
コンテナを起動し、クライアントコンテナから `/mcp` に POST してヘッダごと確認した。

### わかった事実
- 許可されていない Host では **`421 Misdirected Request`** が返り、
  ボディは `Invalid Host header`
- この検査は **`/mcp` にのみ適用される**。`custom_route` で生やした
  `/healthz` `/readyz` には適用されず、Host に関係なく 200 を返す
- `MCP_ALLOWED_HOSTS` に接続先の `host:port` を設定すると 200 になる

### 根拠

拒否時（`MCP_ALLOWED_HOSTS` 未設定）:

```
$ curl -s -X POST http://e2e-srv:8080/mcp -H "Authorization: Bearer tok-a" ... -D /tmp/h
Invalid Host header
HTTP/1.1 421 Misdirected Request
date: Wed, 07 Oct 2026 00:38:25 GMT
server: uvicorn
content-length: 19
```

同じ条件で `/healthz` は 200（E2E Phase 3 の
「ヘルスチェックは認証を素通りする」チェックが PASS している）。

許可後（`MCP_ALLOWED_HOSTS=e2e-srv:8080`）:

```
HTTP/1.1 200 OK
content-type: application/json
{"jsonrpc":"2.0","id":1,"result":{"capabilities":{...},"instructions":"公開 API（...
```

### 作業への影響
ドキュメント 3 ファイル 4 箇所の「400」を「421 Misdirected Request」に訂正した。

- `search-mcp/docs/clients.md` のトラブルシュート表
- `search-mcp/docs/deploy-openshift.md` の ConfigMap 節
- `.tracecraft/.../final-guide.md` の §7 と §9

あわせて「`/healthz` には適用されないため、**probe は通るのに `/mcp` だけ落ちる**
という形で現れる」という切り分け情報を追記した。
症状だけ見ると「アプリは生きているのにクライアントから使えない」となり、
認証の問題と誤診しやすい。

E2E テストに恒久的なチェックとして 2 件追加した
（素の起動時と、ConfigMap 由来の設定で起動した Pod の両方）。

### 未確認事項
OpenShift Router（HAProxy）が 421 をそのまま透過するか、
別のステータスに書き換えるかは未確認。Route 経由での挙動は実クラスタでの確認が必要。

---

## Finding: podman kube play で Deployment の probe 定義を検証できる

### 調べた理由
OpenShift クラスタが無い環境で、Deployment マニフェストをどこまで検証できるかを知りたかった。

### 調査方法
`kubectl kustomize` の出力から podman が解釈できる 3 種
（ConfigMap / Service / Deployment）だけを抜き出し、Secret を足して
`podman kube play --network e2e-net` で起動した。

### わかった事実
- podman は Deployment を受け付け、`<deployment名>-pod` という名前の Pod として起動する
  （`replicas: 2` は無視され 1 つだけ起動する）
- **Deployment の `livenessProbe` / `readinessProbe` が podman の healthcheck に変換される。**
  `podman ps` の STATUS が `(healthy)` になることで、
  probe のパス・ポート・タイミング設定が妥当だったことを確認できる
- ConfigMap の `envFrom` と Secret の `secretKeyRef` も解決される。
  Secret 由来のトークンで認証が通ることを確認した
- Pod の DNS 名は Service 名ではなく `search-mcp-pod`。
  Service 名でのアクセスを模すには `Host:` ヘッダを手で付ける必要がある
- マニフェストが指すクラスタ内レジストリのイメージ名は、
  ローカルイメージに同じタグを付ける（`podman tag`）ことで解決できる

### 根拠

```
$ podman kube play --network e2e-net /tmp/e2e/secret.yaml /tmp/e2e/kube.yaml
Secrets:
96afaf2249c25aef5fab0e182
Pod:
a06b9684075f21c2ed3f3b31a65337d10b5693aaeb6b4e0490d5c3a5d0d3fbb6
Container:
b6c832333defa25217e8ce81442b41c63e2d0626817be586adddd51a2cceeb20

$ podman ps --filter name=search-mcp-pod-server --format '{{.Status}}'
Up 16 seconds (healthy)

$ podman pod ps
POD ID        NAME            STATUS   ...  # OF CONTAINERS
a06b9684075f  search-mcp-pod  Running  ...  2
```

Pod 内のアプリログに probe からのアクセスが残っている:

```
INFO:     127.0.0.1:59738 - "GET /healthz HTTP/1.1" 200 OK
INFO:     127.0.0.1:59748 - "GET /healthz HTTP/1.1" 200 OK
```

### 作業への影響
E2E テストの Phase 5 として恒久化した
（`search-mcp/tests/e2e/run-e2e.sh`）。
`securityContext`・`envFrom`・`secretKeyRef`・probe・コンテナポートが
実際に機能することを、クラスタ無しで確認できるようになった。

### 未確認事項
- **Route / NetworkPolicy / HPA / PDB は podman に概念が無く検証できない**
- `replicas: 2` が無視されるため、複数 replica でのロードバランスと
  stateless 動作は未検証
- **API スキーマ検証にはならない。** podman は自前のパーサで解釈しており、
  Kubernetes/OpenShift の admission による検証とは別物。
  フィールド名の typo は依然として検出できない

---

## Finding: 環境変数の「未設定」と「空文字」は別の意味になる

### 調べた理由
`Settings.from_env()` のテストを書く際、既定値 `True` の項目
（`stateless_http` / `enable_dns_rebinding_protection`）について
ConfigMap で `MCP_STATELESS_HTTP: ""` と書いた場合にどうなるか確認が要った。
Kubernetes の ConfigMap では「キーを消す」と「値を空にする」が混同されやすい。

### 調査方法
`search-mcp/src/search_mcp/settings.py:17-21` の `_bool` を読み、
`test_unset_booleans_keep_their_default` で両方の経路を実行して比較した。

### わかった事実
- `_bool` は `os.environ.get(name)` が `None`（未設定）のときだけ既定値を返す。
- 空文字は `"".strip().lower() in {"1","true","yes","on"}` が偽になるため
  **false** になる。既定値には戻らない。
- 結果として `MCP_STATELESS_HTTP: ""` を ConfigMap に残すと
  stateless が無効化され、セッションがプロセスに乗る。
  `replicas: 2` のままだとロードバランス先によってセッションが見つからなくなる。

### 根拠
`search-mcp/src/search_mcp/settings.py:17-21`

```python
def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
```

`search-mcp/tests/test_settings.py::test_unset_booleans_keep_their_default` が
未設定で `True`、空文字で `False` になることを実行して確認している（38 passed）。

### 作業への影響
挙動自体は意図どおりなので変更しない。
「値を空にする」のではなく「キーごと消す」ことを前提にした設計である。
ただし落とし穴なのでテストで固定し、worklog Step 15 に記録した。

### 未確認事項
`deploy/openshift/configmap.yaml` の各キーについて、
運用中に値を空にする運用が実際にあり得るかは未検討。
現在のマニフェストは全キーに明示的な値を入れているため、この経路には入らない。

---

## Finding: MaaS ゲートウェイに 60 秒の応答時間上限があり、長い生成が必ず切断される

### 調べた理由
ユーザーから LiteLLM MaaS Gateway（Qwen 3.6 35B A3B）の接続情報が提供され、
`PROMPT.md` を実際に opencode で試せるか確認することになった。
1 回目の実行が `Cannot connect to API: The socket connection was closed
unexpectedly` で落ちたため、原因を切り分けた。

### 調査方法
ゲートウェイの `/v1/chat/completions` に直接リクエストを送り、
`stream` と `max_tokens` を変えて成否と所要時間を測った。
認証トークンは環境変数経由で渡した（値はここに記録しない）。

### わかった事実

**1. 生成に 60 秒以上かかるリクエストは、必ず切断される。**

| stream | max_tokens | 結果 |
|---|---|---|
| false | 600 | OK（19 秒） |
| false | 6000 | RemoteDisconnected（60 秒） |
| true | 600 | OK（18 秒） |
| true | 6000 | RemoteDisconnected（60 秒） |

ストリーミングでも回避できない。`stream=true` でも切断までに受信した
SSE チャンクは 0 件だった（ゲートウェイが応答全体をバッファしている）。

**2. スループットは約 33 tok/s。したがって出力上限は実質 1900 トークン前後。**

| max_tokens | completion | 所要 | tok/s |
|---|---|---|---|
| 400 | 400 | 11.9s | 33.7 |
| 800 | 800 | 29.5s | 27.1 |
| 1200 | 1200 | 37.2s | 32.3 |
| 1600 | 1600 | 47.6s | 33.6 |
| 2000 | — | 59s で切断 | — |

**3. 実際のコンテキスト上限は 65536 トークン。** ユーザー提供の
`opencode.json` の `limit.context` は 32000 で、実機の半分を申告していた。

```
litellm.ContextWindowExceededError: This model's maximum context length is
65536 tokens. However, you requested 16 output tokens and your prompt
contains at least 65521 input tokens
```

**4. 入力側は 60 秒制限にほぼ掛からない。** 43,180 トークンの
プロンプトでも 5 秒で応答が返った（出力 16 トークン）。
制約は出力トークン数であって入力長ではない。

### 根拠
いずれもゲートウェイへの実リクエストの結果。
エンドポイント: `https://maas-rhdp.apps.maas.redhatworkshops.io/v1`
モデル ID: `qwen36-35b-a3b`（`/v1/models` で確認、1 件のみ）
認証: Bearer トークン（値は `<REDACTED>`）

### 作業への影響
`PROMPT.md` の内容ではなく、**実行基盤の制約**が移植作業の成否を決める。

出力 1900 トークンでは、`server.py` 相当のファイルを 1 回の `write`
ツール呼び出しで書き切れない。実際に opencode の実行では
`Invalid input for tool write: JSON parsing failed` が 17 回発生した。
ツール呼び出しの JSON が生成途中で打ち切られ、パースに失敗している。

つまり次の板挟みになる:

- 出力上限を上げる → 60 秒を超えて接続が切れる
- 出力上限を下げる → ツール呼び出しの JSON が途中で切れる

対策は「1 ファイルを複数回の追記に分割する」しかない。

### 未確認事項
- 60 秒がどのレイヤの設定か（OpenShift Route の `haproxy.router.openshift.io/timeout`、
  LiteLLM 側、vLLM 側のいずれか）は特定していない。外部からは区別できない。
- この制限がこの検証環境固有か、MaaS の恒常的な設定かは不明。
- 延長可能かどうかも不明。ゲートウェイの管理者に確認が要る。

---

## Finding: PROMPT.md の STEP 1〜2 は 35B モデルで意図どおり機能した

### 調べた理由
`PROMPT.md` は 30B 級モデル向けに書いたが、Step 16 の時点では
実際に走らせた検証をしていなかった（「設計上の推論にとどまる」と記録した）。
実機が使えるようになったので確認した。

### 調査方法
検証用のワークスペース `~/opencode-trial/` を作り、次を配置した。

- `PROMPT.md` と `search-mcp/` `search-demo/`（見本一式）
- 新しい移植対象として `weather-demo/`（Open-Meteo で複数都市の天気予報を
  取る依存ゼロの Python スクリプト + `SKILL.md`）
- opencode の設定（provider = litellm、model = qwen36-35b-a3b）

`weather-demo` には `PROMPT.md` が警告している罠を意図的に仕込んだ。
選択肢が固定のオプション（`-m`）、範囲のある数値（`-d` は 1〜14）、
「一度に 5 都市程度まで」というレート制限の注意書き、
`python3 weather_demo.py` という実行方法の記述、部分失敗の仕様。

opencode を非対話モード（`opencode run --auto`）で実行した。

### わかった事実

**STEP 0〜2 は完全に意図どおり動いた。**

1. モデルは指示どおり `PROMPT.md` を最初に読み、続いて見本 4 ファイル
   （`skill-to-mcp.md` / 見本の `SKILL.md` / `server.py` / `test_server.py`）を
   読んだ。STEP 0 の「見本を読んでから書き始める」は守られた。
2. 自発的に STEP 単位の TODO リストを作った。
3. STEP 1 の棚卸し表を、指定したフォーマットどおりに出力した。
   内容は正確で、`-d` の範囲 1〜14、`-m` の選択肢、出力の JSON 構造、
   「読み取り専用」「添付ファイルなし」をすべて正しく埋めていた。
4. STEP 2 の移植判定で `#5`（外部 API を読むだけ）を正しく選び、
   理由も「ローカルファイルの読書きなし、副作用なし、添付ファイルなし」と
   判定表の条件をなぞる形で書いた。

実際に生成された `weather-mcp/docs/porting-notes.md` の STEP 2 部分:

```markdown
## STEP 2: 移植判定

- 当てはまった行: #5
- 理由: 外部 API を読むだけ（Open-Meteo 天気予報）。ローカルファイルの
  読書きなし、副作用なし、添付ファイルなし
- 追加で読んだ節: なし
- 続行: そのまま続行
```

**STEP 3 以降には到達できなかった。** 原因は上記の 60 秒制限であって、
`PROMPT.md` の記述ではない。

### 根拠
- 生成物 `~/opencode-trial/weather-mcp/docs/porting-notes.md`（STEP 1〜2 を記載）
- opencode の実行ログ `/tmp/oc-run4.log`（`Invalid Tool` が 17 回）
- opencode のログ `~/.local/share/opencode/log/opencode.log`

### 作業への影響
「判断を仰ぐのではなく表を引かせる」という `PROMPT.md` の設計方針は、
35B 級モデルに対して有効だと確認できた。
出力フォーマットを固定したことで、生成物が検証可能な形で残ることも確認できた。

一方で、**ファイルを書く工程が実行基盤の出力上限に当たる**ことが分かった。
`PROMPT.md` には「1 ファイルを 1 回で書く」前提のテンプレートを載せているが、
出力上限が厳しい環境では分割して書く必要がある。

### 未確認事項
- STEP 3（仕分け）以降の品質は未検証。60 秒制限のため到達していない。
- 制限の緩いゲートウェイであれば完走するかどうかも未確認。
- 1 回目の試行では、コンテキストを 32000 と申告した状態で
  参照ファイルを読み切った直後にモデルが
  「This is a fresh session — I don't have prior conversation history」と応答した。
  コンテキスト切り詰めで `PROMPT.md` ごと失われたと推測するが、
  opencode の内部動作は確認していないため断定しない。

---

## Finding: qwen36-35b-a3b は推論モデルで、thinking が出力枠と時間を食い潰していた

### 調べた理由

opencode 経由の移植が 4 回とも失敗した。失敗の形は「ツール呼び出しの JSON が
途中で切れる」「モデルがタスク自体を見失う」で、どちらも出力枠の不足を示唆していた。
しかし 60 秒 / 33 tok/s から計算した約 1900 トークンの枠は、
1 ファイル分の write には足りるはずだった。計算が合わないので原因を調べた。

### 調査方法

opencode を経由せず、ゲートウェイの `/v1/chat/completions` を
urllib で直接叩いた。まず STEP 3 の実行を `max_tokens=1600` で依頼したところ、
`completion_tokens=1600` を消費したのに `content` が `None` で返った
（スクリプトが `TypeError: write() argument must be str, not None` で落ちた）。
レスポンスの message オブジェクトをそのまま出力して中身を確認した。

### わかった事実

1. message には `content` の他に `reasoning_content` フィールドがあり、
   生成はすべてそちらに入っていた。`qwen36-35b-a3b` は推論モデルである。

2. 思考は短い質問でも発生する。「1+1は？ 短く答えて。」で
   `reasoning_content` が 1304 字、`content` が 0 字（`max_tokens=400` で打ち切り）。

3. thinking を止める方法を 5 通り試し、効いたのは 1 つだけだった。

   | 設定 | reasoning | content | tokens | 時間 |
   |---|---|---|---|---|
   | 既定 | 1304 字 | 0 字 | 400 | 15 秒 |
   | `chat_template_kwargs: {"enable_thinking": false}` | **0 字** | **182 字** | **75** | **3 秒** |
   | `reasoning_effort: "none"` | 1292 字 | 0 字 | 400 | 13 秒 |
   | `reasoning_effort: "low"` | 1287 字 | 0 字 | 400 | 20 秒 |
   | `extra_body` の `thinking: {"type":"disabled"}` | 1323 字 | 0 字 | 400 | 17 秒 |
   | プロンプト末尾に `/no_think` | 1441 字 | 0 字 | 400 | 14 秒 |

4. `chat_template_kwargs` を付けると、同じタスクが 400 トークン / 15 秒から
   75 トークン / 3 秒になった。

### 根拠

すべて `https://maas-rhdp.apps.maas.redhatworkshops.io/v1/chat/completions`
（model: `qwen36-35b-a3b`、token は `<REDACTED>`）への実リクエストの結果。
raw-execution-log.md Phase 18 に全出力を記録した。

### 作業への影響

Finding「MaaS ゲートウェイに 60 秒の応答時間上限」で記録した
「60 秒の壁が原因」という説明は**不完全だった**。60 秒の壁は実在するが、
その枠を先に食い潰していたのは不可視の思考トークンである。
thinking を切れば同じ枠で 5 倍以上の可視出力が出る。

PROMPT.md の「実行環境の要件」に推論モデル向けの節を追加した。

### 未確認事項

- opencode の provider 設定から `chat_template_kwargs` を渡せるかどうか。
  opencode の設定スキーマを確認していない。
- 60 秒の上限がどの層（Route の haproxy timeout / LiteLLM / vLLM）のものか。

---

## Finding: thinking を切れば 35B モデルは STEP 3〜5 を実用品質で実行できた

### 調べた理由

「PROMPT.md が 35B 級モデルに通用するか」が検証の目的だったが、
ここまでの失敗はすべて実行基盤由来で、モデルの移植能力そのものを
一度も測れていなかった。「モデルには無理だった」と結論するのは誤りになる。

### 調査方法

`chat_template_kwargs: {"enable_thinking": false}` を付け、
opencode を経由せず API を直接呼んだ。PROMPT.md 全文 + 移植対象の
SKILL.md + weather_demo.py を 1 プロンプトに詰め（prompt 9026 トークン）、
STEP 3 のみを依頼。続けてその出力を文脈に足して STEP 4〜5 を依頼した。

検証用の SKILL.md には、PROMPT.md が「間違えやすい」と名指ししている罠を
意図的に 4 つ仕込んである。

### わかった事実

**STEP 3（仕分け）**: completion 990 トークン / 38 秒。17 行の仕分け表を生成。

| 仕込んだ罠 | 期待 | 結果 |
|---|---|---|
| `-m` は 4 択 | SCHEMA / `Literal` | ✅ 「選択肢を `Literal` で固定」 |
| `-d` は 1〜14 | SCHEMA / `ge=1, le=14` | ✅ |
| 「一度に 5 都市程度まで」 | **SCHEMA + GUARD** | ✅ `Field(le=5)` と `min(len(cities), 5)` の両方を指定 |
| 「`cd` / `python3 weather_demo.py`」 | DROP として表に載せる | ❌ 表から欠落 |

3 つ正解、1 つ欠落。特に 3 つ目（散文の注意書きをスキーマに格上げし、
さらにコードでも押さえる）は PROMPT.md が「ここを特に注意」として
書いた最難関の判断で、備考に「ネットワーク越しの誰でも呼べるため」と
理由まで書いていた。指示書の意図が伝わっている。

なお `-f/--format` を DROP に分類し、理由を
「MCP クライアントは JSON 形式で受け取るため」と書いた。これは正解で、
かつ PROMPT.md の DROP 例に無い項目を自力で判断している。

**STEP 4〜5（コード生成）**: completion 2400 トークン上限 / 200 行を生成。
SDK の落とし穴 5 項目はすべて守られていた。

- `from mcp.server.mcpserver import MCPServer`（`FastMCP` ではない）
- `from __future__ import annotations` 無し。不要である理由のコメントまで転記
- snake_case（`read_only_hint`）
- `anyio.to_thread.run_sync()` で同期処理を包んだ
- Pydantic 全フィールドに `Field(description=...)`
- `ToolAnnotations` 4 項目が読み取り専用ツールとして正しい
- GUARD を関数本体に実装（`effective_cities[: settings.max_cities]`）

残った欠陥は 3 つ、いずれも軽微:

1. `lang: Annotated[str, ...] = None` — 既定値 `None` に対し型が `str`。
   `str | None` であるべき
2. `cities` のスキーマに `max_length=5` が無い。STEP 3 では
   `Field(le=5)` と書いたのに、コードではコード側の切り詰めだけになった
3. `from weather_demo import run_forecast` を関数本体の中で import している

### 根拠

生成物は `/tmp/step3.md` と `/tmp/step5.py`。
raw-execution-log.md Phase 18 に実行コマンドと全出力を記録した。

### 作業への影響

PROMPT.md の STEP 3 に「## 使い方 のコードブロックを表から落としがち」
という注意を追記した（唯一の欠落に対応）。

「PROMPT.md は 35B 級に通用するか」への答えは **通用する**。
ただし条件付きで、推論モデルなら thinking を切ることが前提になる。

### 未確認事項

- STEP 6〜9（周辺ファイル・テスト・コンテナ・ドキュメント）は実行していない。
- 生成された `server.py` を実際に起動・テストしていない。構文も検証していない。
- 1 回の試行の結果であり、再現性は未確認。

---

## Finding: opencode 実クライアントからの接続で、スキーマ強制が機能することを確認した

### 調べた理由

本プロジェクトの要件は「opencode から MCP として使えること」だった。
しかし検証は curl による生の JSON-RPC までで、
`examples/opencode.json` は一度も opencode に読ませていなかった。

### 調査方法

`search-mcp` をローカル起動（`127.0.0.1:8080`、`MCP_AUTH_TOKENS=dev-token`）し、
opencode 1.18.34 + `qwen36-35b-a3b` から 4 パターン実行した。

### わかった事実

1. `"type": "remote"` + `headers.Authorization` の設定で接続できる。
   `{env:SEARCH_MCP_TOKEN}` の展開も動く。

2. ツールは `<MCP サーバー名>_<ツール名>` で登録される。
   `opencode.json` のキーを `search` にしたので `search_search` になった。

3. **スキーマの上限がクライアント経由でも強制される。**
   `limit=100` を指定すると Pydantic が弾き、モデルは次を受け取った。

   ```
   Error executing tool search: 1 validation error for searchArguments
   limit
     Input should be less than or equal to 20 [type=less_than_equal, input_value=100, input_type=int]
   ```

   モデルはこれを読んで「`limit` の上限は 20 です」と回答した。

4. **トークンが誤っているとき、エージェントは無言で別手段に逃げる。**
   サーバーは 401 を返すが、opencode はツールを提示せず、
   `WebFetch` で Wikipedia API を直接叩いて回答を作った。
   ユーザーからは成功と区別がつかない。

5. 401 を受けた opencode は OAuth ディスカバリに進む
   （`/.well-known/oauth-authorization-server` →
   `/.well-known/openid-configuration` → `POST /register`）。
   いずれも 401 を返すと諦める。`auth.py:1-15` の設計意図どおり。

### 根拠

サーバーログ `/tmp/mcp-server.log`（`POST /mcp` 10 件、401 計 12 件、
`INFO search_mcp.server search query='asyncio' sources=['github'] limit=3 lang=ja`）と、
opencode の標準出力。Step 19 の worklog に全文を記録した。

### 作業への影響

`docs/skill-to-mcp.md` の前提が実クライアントで裏付けられた。
これまでは「curl で弾けた」までしか言えなかった。

`docs/clients.md` に §1.6〜1.8 を追加し、§3 の切り分け表に
「エラーは出ないがツールが使われない」「`search` を指定しても呼ばれない」を足した。

### 未確認事項

- **Route 経由（TLS + 外部ホスト名 + DNS rebinding 保護 有効）での接続は未検証。**
  上記はすべて平文 localhost で、`MCP_DNS_REBINDING_PROTECTION=false` にしている。
- クラスタ内 Pod の agent framework（§2）からの接続も未検証のまま。
- `list_search_sources` ツールは呼ばせていない。
- 自動テスト化していない。手動検証であり、CI では回らない。

---

## Finding: 許可外 Host の 421 は、正しい Accept ヘッダを付けないと観測できない

### 調べた理由

コンテナを DNS rebinding 保護 有効で起動し、許可外 Host で `/mcp` を叩いたところ
**400** が返った。既存の Finding では 421 を観測しているため矛盾する。
保護が効いていないのか、観測方法が悪いのかを切り分ける必要があった。

### 調査方法

同じ許可外 Host に対して、ヘッダを変えて 2 回リクエストした。

```bash
# 1 回目
curl -X POST http://10.89.7.10:8080/mcp -H 'Host: evil.example.com' \
  -H 'Authorization: Bearer container-token' -d '{}'

# 2 回目（Content-Type と Accept を追加）
curl -X POST http://10.89.7.10:8080/mcp -H 'Host: evil.example.com' \
  -H 'Authorization: Bearer container-token' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

### わかった事実

1. 1 回目は `400`。2 回目は `421 Misdirected Request` / `Invalid Host header`。
2. 同じリクエストを許可済み Host で投げると `200`。
3. したがって保護は正しく機能しており、
   **`Accept` を欠いたリクエストが Host 検証より先に 400 で弾かれていた**だけ。
4. ミドルウェアの順序は、認証（401）が最も外側。
   認証は `-d '{}'` だけのリクエストでも確認できる（実際 401 が返る）。
   Host 検証は Streamable HTTP の層にあるため、そこまで到達させる必要がある。

### 根拠

Phase 20 の実行ログ。レスポンスヘッダ全文:

```
HTTP/1.1 421 Misdirected Request
server: uvicorn
content-length: 19

Invalid Host header
```

### 作業への影響

既存の Finding「`MCP_ALLOWED_HOSTS` が合っていないと 421 を返す」は**正しい**。
訂正は不要。足りなかったのは**確認手順**のほうで、
`docs/clients.md` §1.5 の疎通確認は `-d '{}'` を使っており、
これを Host 検証の確認に流用すると 400 を見て誤った結論に至る。

`docs/clients.md` に §1.6.1 として確認手順を追加し、
`examples/README.md` にも同じ注意を書いた。

### 未確認事項

- Streamable HTTP の層で 400 を返している正確な位置（SDK のどのコード）は
  特定していない。`Accept` の欠落が原因であることは実験から言えるが、
  SDK のソースは読んでいない。

---

## Finding: コンテナ構成でも、DNS rebinding 保護を有効にしたまま opencode から使える

### 調べた理由

Step 19 の検証は `uv run search-mcp` によるローカルプロセスで、
`MCP_DNS_REBINDING_PROTECTION=false` にしていた。
本番は保護 有効・コンテナ・任意 UID で動く。構成差が残っていた。

### 調査方法

専用ネットワーク `mcp-net`（`10.89.7.0/24`）を作り、IP を `10.89.7.10` に固定して
OpenShift の `restricted-v2` SCC 相当の制約つきで起動した。

```bash
podman run -d --name search-mcp --network mcp-net --ip 10.89.7.10 \
  --user 1000670000:0 --read-only --tmpfs /tmp \
  --cap-drop ALL --security-opt no-new-privileges \
  -e MCP_AUTH_TOKENS=container-token \
  -e MCP_JSON_RESPONSE=true \
  -e MCP_DNS_REBINDING_PROTECTION=true \
  -e MCP_ALLOWED_HOSTS=10.89.7.10:8080 \
  search-mcp:1.0.0
```

IP を固定したのは、`MCP_ALLOWED_HOSTS` に接続先を書く必要があり、
起動のたびに IP が変わると設定できないため。

### わかった事実

1. opencode から `search_search` が呼べた。
   コンテナログに
   `INFO search_mcp.server search query='kubernetes operator' sources=['github'] limit=3 lang=ja`。
2. `podman exec search-mcp id` → `uid=1000670000(1000670000) gid=0(root)`。
   Containerfile の `USER 1001` ではなく、`--user` で与えた任意 UID で動いている。
3. `touch /nope` → `Read-only file system`。rootfs は読み取り専用。
4. 許可外 Host は 421 で弾かれ、`/healthz` は許可外 Host でも 200。
5. **DooD 構成では publish したポートに届かない。**
   `-p 18080:8080` で起動しても `curl http://127.0.0.1:18080/healthz` は
   `000`（接続失敗）。コンテナ IP 直指定（`http://10.88.0.28:8080/healthz`）なら 200。

### 根拠

Phase 20 の実行ログ。`podman logs` / `podman exec` / `curl -w '%{http_code}'` の出力。

### 作業への影響

本番構成との残り差分は **Route（TLS 終端 + 外部ホスト名 + Router のタイムアウト）**
だけになった。`examples/opencode.local.json` と `examples/README.md` に
動いた設定と再現手順を残した。

### 未確認事項

- Route 経由は未検証。TLS 終端、`haproxy.router.openshift.io/timeout`、
  外部ホスト名での `MCP_ALLOWED_HOSTS` はいずれも試せていない。
- publish したポートに届かない理由は DooD 構成と推測しているが、
  ホスト側のネットワーク設定は確認していない。
- `list_search_sources` ツールはコンテナ構成でも呼んでいない。
