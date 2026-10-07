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
