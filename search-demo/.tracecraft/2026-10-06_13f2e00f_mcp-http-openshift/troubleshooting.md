# Troubleshooting

> 作業タイトル: search-demo を MCP Streamable HTTP サーバー化し OpenShift に配備可能にする
> 開始日時: 2026-10-06

---

## Issue: FastMCP が import できない

### 症状
`from mcp.server.fastmcp import FastMCP` が `ModuleNotFoundError` になる。

### 影響
サーバー実装の入口が分からず、実装に着手できない。

### 原因候補
1. インストールが不完全
2. `mcp[cli]` など extra が必要
3. SDK のバージョンが上がって API が変わった

### 切り分け
エラーメッセージ自体が原因を明示していた。追加調査なしで 3 と判明。

### 実際の原因
インストールされたのは `mcp 2.3.0` で、`FastMCP` は `MCPServer` に改名されている。
`mcp/server/fastmcp.py` は移行を案内するためだけのスタブになっていた。

### 解決策
`from mcp.server.mcpserver import MCPServer` を使う。`pyproject.toml` の依存を `mcp>=2.3,<3` にした。

### 解決確認
`inspect.signature(MCPServer.__init__)` が正常に出力され、以降の実装・テストが通った（9 passed）。

### 再発防止
LLM の記憶にあるライブラリ API は実際に import して確認してから使う。
特にメジャーバージョンの変わり目は記憶と食い違う。この作業では実装前に確認したため手戻りが最小で済んだ。

---

## Issue: uv sync が README.md の不在で失敗する

### 症状
```
OSError: Readme file does not exist: README.md
```
`Call to hatchling.build.build_editable failed`

### 影響
依存をインストールできず、テストを実行できない。

### 原因候補
1. hatchling のバージョン問題
2. `pyproject.toml` の `readme = "README.md"` が実在しないファイルを指している

### 切り分け
`ls` で `search-mcp/README.md` が存在しないことを確認。2 と判明。

### 実際の原因
`pyproject.toml` に `readme = "README.md"` を書いたが、ファイルをまだ作っていなかった。
hatchling はビルド時に実在をチェックする。

### 解決策
プレースホルダとして `echo "# search-mcp" > README.md` を作成（後で本文を書いた）。

### 解決確認
`uv sync --extra dev` が成功し、48 パッケージが入った。

### 再発防止
`pyproject.toml` に `readme` を書いたら、同じタイミングでファイルも作る。

---

## Issue: InvalidSignature — ツール関数のアノテーションを評価できない

### 症状
テスト 9 件すべてが失敗:
```
mcp.server.mcpserver.exceptions.InvalidSignature:
Unable to evaluate type annotations for callable 'search'
```

### 影響
サーバーが構築できず、テストが 1 件も走らない。

### 原因候補
1. `Literal` / `Annotated` の書き方が SDK 非対応
2. `list[SourceName] | None` のような Union 型が未対応
3. アノテーション内で参照している名前が解決できていない

### 切り分け
`build_server(Settings())` を直接呼んで `e.__cause__` を出力したところ
`NameError("name 'settings' is not defined")` だった。3 と確定。
型の書き方（1, 2）は無関係だった。

### 実際の原因
`server.py` 冒頭の `from __future__ import annotations`（PEP 563）により、
アノテーションが文字列として保存される。SDK は `inspect.signature(func, eval_str=True)` で
これを評価するが、評価にはモジュールの globals しか使われないため、
`Field(le=settings.max_limit)` の `settings`（`build_server` のクロージャ変数）が解決できない。

### 解決策
`server.py` からのみ `from __future__ import annotations` を削除し、
削除理由をファイル冒頭にコメントとして残した。

### 解決確認
同じコードで `InvalidSignature` が消え、次の段階のエラー（Issue 4）に進んだ。
最終的に `limit` の上限がスキーマに反映されることをテストで確認:
`assert any(variant.get("maximum") == 7 for variant in limit_schema["anyOf"])` が通った。

### 再発防止
**設定値を型アノテーションに埋め込むモジュールでは PEP 563 を使わない。**
逆に、PEP 563 を使いたいなら上限値をモジュールレベル定数にする。
今回は環境変数での可変性を優先して前者を選んだ。

---

## Issue: Task group is not initialized

### 症状
テスト 7 件が失敗:
```
RuntimeError: Task group is not initialized. Make sure to use run().
  at mcp/server/streamable_http_manager.py:185 in _handle_request
```
`/healthz` を叩くテスト 2 件だけは成功していた。

### 影響
MCP プロトコルを使うテストが全滅する。

### 原因候補
1. `streamable_http_app()` の呼び方が誤り
2. `stateless_http=True` との組み合わせの問題
3. Starlette の lifespan が実行されていない

### 切り分け
`/healthz`（custom_route）は通り `/mcp` だけ落ちることから、
アプリ自体は正しく組み上がっており、MCP のセッションマネージャだけが未起動だと判断した。
テストは `httpx.ASGITransport` で in-process に叩いており、
ASGITransport は lifespan イベントを送らない。3 と確定。

### 実際の原因
`MCPServer.streamable_http_app()` が返す Starlette アプリは、
lifespan で `StreamableHTTPSessionManager` の task group を起動する。
`ASGITransport` は lifespan を実行しないため、task group が未初期化のままリクエストが届いた。

### 解決策
テストを in-process ASGI ではなく **実際に listen する uvicorn サーバー**に変更した。
`tests/test_server.py` に `_serve()` を追加し、動的ポートで `uvicorn.Server.serve()` を
バックグラウンドタスクとして起動、`server.started` を待ってから URL を返す。

### 解決確認
7 件の `RuntimeError` が消え、次の段階のエラー（Issue 5）に進んだ。
最終的に 9 件すべて成功。サーバー起動ログに
`StreamableHTTP session manager started` が出ることも確認した。

### 再発防止
lifespan に依存する ASGI アプリは `ASGITransport` ではテストできない。
`asgi-lifespan` 等で lifespan だけ回す手もあるが、
今回は本番と同じ経路（実 HTTP・実 uvicorn）を通すほうが
認証ミドルウェアや proxy ヘッダの検証も兼ねられるので uvicorn を選んだ。

---

## Issue: CallToolResult に structuredContent 属性がない

### 症状
テスト 5 件が失敗:
```
AttributeError: 'CallToolResult' object has no attribute 'structuredContent'.
Did you mean: 'structured_content'?
```

### 影響
ツールの出力を検証するテストが通らない。

### 原因候補
1. structured output が有効になっていない
2. SDK 2.x で属性名が変わった

### 切り分け
エラーメッセージが代替候補を示していた。
`mcp_types.Tool.model_fields` / `CallToolResult.model_fields` を出力して確認したところ、
`input_schema`, `output_schema`, `structured_content`, `is_error` と
すべてスネークケースだった。2 と確定。

### 実際の原因
MCP SDK 2.x は Python 側の属性名をスネークケースに統一している
（MCP 仕様のワイヤフォーマットはキャメルケースのまま、pydantic の alias で変換）。

### 解決策
テスト内の `structuredContent` → `structured_content`、`isError` → `is_error`、
`inputSchema` → `input_schema`、`readOnlyHint` → `read_only_hint` に一括置換。
あわせて `server.py` の `ToolAnnotations(...)` もスネークケースに統一した
（キャメルケースでも alias で通るが、読み出し側と揃えたほうが混乱しない）。

### 解決確認
`9 passed in 2.66s`。

### 再発防止
SDK のモデルを使うときは `model_fields` で実際のフィールド名を確認する。
仕様上のワイヤ名とバインディングの属性名は一致するとは限らない。

---

## Issue: コンテナが ModuleNotFoundError で起動しない

### 症状
ビルドは成功するが実行時に:
```
File "/opt/venv/bin/search-mcp", line 4, in <module>
    from search_mcp.__main__ import main
ModuleNotFoundError: No module named 'search_mcp'
```

### 影響
イメージが使えない。

### 原因候補
1. `COPY --from=builder /opt/venv /opt/venv` が不完全
2. `PATH` の設定ミス
3. editable install の参照先が runtime ステージに存在しない

### 切り分け
`/opt/venv/bin/search-mcp` 自体は存在して実行されている（トレースバックがそこから出ている）ので
1 と 2 は否定される。残る 3 を検証するため `uv sync` の挙動を確認し、
既定が editable であることから、venv に `/build/search-mcp` を指す `.pth` が
残っていると判断した。

### 実際の原因
`uv sync` の既定はプロジェクト自身を editable で入れる。
builder ステージを捨てる runtime ステージには `/build/search-mcp` が存在しないため import に失敗する。

### 解決策
`Containerfile` の `uv sync` 2 か所に `--no-editable` を追加し、理由をコメントで残した。

### 解決確認
再ビルド後、`podman run -d` したコンテナに対し `podman exec` で:
```
health: ok
noauth: 401 Bearer realm="search-mcp"
uid: 1001
```

### 再発防止
**マルチステージで venv だけをコピーするなら `uv sync --no-editable` を使う。**
この失敗はビルドが成功してしまうため、ビルドが通っただけで終わらせず
必ず `podman run` で起動確認する。

---

## Issue: ビルドしたコンテナにクライアントから接続できない

### 症状
`podman run -d -p 18081:8080` の後、`curl localhost:18081/healthz` が空応答（HTTP コード `000`）。
`--network host` でも `httpx2` の接続エラー（ExceptionGroup）。

### 影響
イメージに対する MCP クライアント経由の疎通確認ができない。

### 原因候補
1. コンテナ内でサーバーが起動していない
2. bind アドレスが 127.0.0.1 になっている
3. この実行環境のネットワーク構成の問題

### 切り分け
- `podman logs smcp` に `Uvicorn running on http://0.0.0.0:8080` と
  `Application startup complete.` が出ており、1 と 2 は否定された
- `podman ps` は `Up 7 seconds 0.0.0.0:18081->8080/tcp` を表示していた
- `podman exec smcp python -c "...urlopen('http://127.0.0.1:8080/healthz')..."` は `health: ok` を返した

→ サーバーは正常。到達経路の問題（3）と確定。

### 実際の原因
この環境は DooD（Docker outside of Docker）で、コンテナランタイムのソケット
`/run/container.sock` はホストのもの。`podman run` で作られるコンテナは
**ホスト側の sibling コンテナ**であり、`-p` で publish されるのはホストの
localhost であって、このエージェントコンテナの localhost ではない。
`--network host` の host もホストを指すため同様に到達できない。

### 解決策
- コンテナの疎通確認は `podman exec` 経由で行う
- MCP クライアント経由の完全な疎通確認は、同じコードをローカルで
  `uv run search-mcp` として起動して実施する

### 解決確認
ローカル起動に対し `examples/smoke_client.py` を実行し、
initialize（server_info / instructions）、tools/list（2 ツール）、
`search("rust tui")` の実 API 検索結果 8 件（4 ソース混在、`errors: []`）を確認した。

### 再発防止
環境固有の制約であり、コードの問題ではない。
DooD 環境ではコンテナ間の到達性を前提にせず、
`podman exec` か、同一ネットワークに置いた検証用コンテナを使う。

---

## Issue: kustomize が commonLabels の非推奨警告を出す

### 症状
```
# Warning: 'commonLabels' is deprecated. Please use 'labels' instead.
```

### 影響
動作はするが、将来のバージョンで壊れる可能性がある。

### 原因候補
kustomize の仕様変更。原因は警告文のとおりで切り分け不要。

### 切り分け
`labels` に単純置換すると `includeSelectors` の既定値が問題になるか確認が必要だった。
`app.kubernetes.io/version: 1.0.0` をセレクタに含めると、
バージョン更新時に Deployment の immutable な `.spec.selector` を変更することになる。

### 実際の原因
`commonLabels` が非推奨になり `labels` に置き換えられた。

### 解決策
```yaml
labels:
  - includeSelectors: false
    pairs:
      app.kubernetes.io/part-of: mcp-demo
      app.kubernetes.io/version: 1.0.0
```
セレクタに使う `app.kubernetes.io/name: search-mcp` は各マニフェストに直接記述し、
kustomize の label 注入に依存しないようにした。理由はコメントで残した。

### 解決確認
`kubectl kustomize .` が警告なしで 12 リソースを出力。
image が `image-registry.openshift-image-registry.svc:5000/search-mcp/search-mcp:1.0.0` に置換されていることも確認。

### 再発防止
`labels` に移行する際は `includeSelectors` を必ず明示する。
可変ラベル（version など）をセレクタに入れない。

---

## Issue: kubectl apply --dry-run=client がクラスタ接続を要求する（未解決）

### 症状
```
Couldn't get current server API group list: Get "http://localhost:8080/api?timeout=32s": connection refused
unable to recognize "/tmp/rendered.yaml": ...
```

### 影響
マニフェストの **API スキーマレベルの検証ができていない**。
フィールド名の typo や apiVersion の誤りは検出できていない。

### 原因候補
1. `--validate=false` の付け方が足りない
2. client dry-run でも API discovery が必要

### 切り分け
`--validate=false` を付けても同じエラーが出た。
`kubectl apply --dry-run=client` はリソース種別の解決に API discovery を使うため、
クラスタ無しでは動かない。2 と確定。

### 実際の原因
クラスタに接続していない環境で、かつ OpenShift 固有リソース
（Route, BuildConfig, ImageStream）は組み込みスキーマにも存在しない。

### 解決策（未適用）
検証できたのは `kubectl kustomize` によるレンダリング（YAML 構文と kustomize の解釈）までにとどめた。
選択肢としては:
- 実クラスタで `oc apply --dry-run=server -k ...`（最も確実）
- `kubeconform` + OpenShift の CRD スキーマ（スキーマ取得にネットワークが要る）

### 解決確認
**未解決。** レンダリングが通ることのみ確認済み。

### 再発防止
配備前に実クラスタで `oc apply --dry-run=server -k search-mcp/deploy/openshift/` を必ず実行する。
この制約は README / deploy ドキュメントではなく、この記録と最終報告で明示した。

---

## Issue: opencode が「The socket connection was closed unexpectedly」で落ちる

### 症状
`opencode run` で Qwen 3.6 35B A3B（LiteLLM MaaS Gateway 経由）に
移植作業をさせると、参照ファイルを読み終えた直後に落ちる。

```
Now I have a complete understanding of both the instructions and the reference implementation.
Error: Cannot connect to API: The socket connection was closed unexpectedly.
For more information, pass `verbose: true` in the second argument to fetch()
```

### 影響
移植作業が 1 ステップも進まない。生成ファイルはゼロ。
エラーメッセージがネットワーク層のものなので、原因の見当が付かない。

### 原因候補
1. コンテキスト長の超過（設定では 32000、参照ファイルだけで約 20k 消費）
2. 入力が長すぎてゲートウェイが拒否している
3. ゲートウェイ／Route の応答時間上限
4. ネットワークの一時的な不調
5. opencode 側のバグ

### 切り分け
ゲートウェイに直接リクエストを送り、変数を 1 つずつ変えた。

**(a) 入力長を変える** — 候補 2 の検証。

```
~14k tokens: OK (2s)
~29k tokens: OK (3s)
~43k tokens: OK (5s)
```

43k でも通る。入力長は原因ではない。候補 2 を除外。

**(b) コンテキスト上限を調べる** — 候補 1 の検証。

```
HTTP 400 litellm.ContextWindowExceededError:
  This model's maximum context length is 65536 tokens.
```

実機の上限は 65536 で、設定の 32000 は過小申告だった。
ただし切断時のエラーは 400 ではなく接続断なので、
これは別の問題（後述）であり、切断の直接原因ではない。候補 1 を除外。

**(c) 出力長とストリーミングを変える** — 候補 3 の検証。

```
stream=False max_tokens=600:  OK 6094B in 19s
stream=False max_tokens=6000: RemoteDisconnected after 60s
stream=True  max_tokens=600:  OK  261B in 18s
stream=True  max_tokens=6000: RemoteDisconnected after 60s
```

**きっかり 60 秒で切断される。** stream の有無に関係しない。
再現性も 100%。候補 4（一時的な不調）と候補 5（opencode のバグ）を除外。

**(d) 限界値を測る**

```
max_tokens=400:  400 tok in 11.9s (33.7 tok/s)
max_tokens=800:  800 tok in 29.5s (27.1 tok/s)
max_tokens=1200: 1200 tok in 37.2s (32.3 tok/s)
max_tokens=1600: 1600 tok in 47.6s (33.6 tok/s)
max_tokens=2000: 切断 (59s)
```

### 実際の原因
**ゲートウェイ（または前段の Route／プロキシ）に 60 秒の応答時間上限がある。**

生成速度が約 33 tok/s なので、1 応答で出せるのは実質 1900 トークン前後。
opencode の既定では `limit.output` が 8000 に設定されており、
モデルが長い応答を始めると必ず 60 秒を超えて切断される。

`stream=true` でも回避できないのは、ゲートウェイが SSE を
そのまま流さずバッファしているため（切断までの受信チャンク数が 0 だった）。

### 解決策
根本解決はゲートウェイ側の設定変更（上限の延長）。これは管理者の領域。

クライアント側の緩和策:

1. `limit.output` を 1200〜1600 に下げる
2. `limit.context` を実機に合わせて 60000 前後にする（32000 は過小申告）
3. エージェントに「1 ファイルを 1 回で書かず、分割して追記する」と指示する

### 解決確認
緩和策を適用した試行で、STEP 0〜2 までは完走し、
`weather-mcp/docs/porting-notes.md` が正しい内容で生成された。

ただし**完全な解決にはならなかった。** 出力を 1200 に絞ると、
今度はツール呼び出しの JSON が生成途中で打ち切られる。

```
✗ Invalid Tool
The arguments provided to the tool are invalid: Invalid input for tool write:
JSON parsing failed: Text: {"filePath": ".../src/weather_mcp/server.py".
Error message: JSON Parse error: Expected '}'
```

計 17 回発生し、`server.py` を書けずに終わった。
出力を上げれば 60 秒で切れ、下げればツール呼び出しが壊れる、という板挟み。

### 再発防止
`PROMPT.md` の冒頭に「実行環境の要件」節を追加し、
作業前にゲートウェイの応答時間上限を測る curl コマンドを載せた。
必要量（コンテキスト 48k 以上、出力 4000 トークン以上、時間上限 180 秒以上）も明記した。

---

## Issue: 出力上限を下げるとモデルがタスク自体を見失う

### 症状
60 秒制限を避けるため `limit.output` を 1500 に下げたところ、
STEP 1 の出力が途中で切れ、その直後にモデルがこう応答した。

```
**STEP 1: 棚卸し**
Continue if you have next steps, or stop and ask for clarification if you are unsure how to proceed.
...
I need more context about what we were working on. Let me check the project state:
...
This is a fresh session — I don't have prior conversation history. Based on the
workspace contents, there's an existing weather forecast project:
...
If you'd like to continue work on this or something else, let me know what to do next.
```

PROMPT.md を読んだことも、移植作業中であることも忘れている。

### 影響
作業が中断するだけでなく、**モデルが「指示されていない」と判断して
勝手に別の提案を始める。** 放置すると無関係な作業をされる危険がある。

### 原因候補
1. 出力の打ち切りで会話が壊れた
2. コンテキスト長超過による履歴の切り詰めで PROMPT.md が落ちた
3. モデル側のセッション管理の問題

### 切り分け
この時点の設定は `context: 32000`。
実測で STEP 0 の参照ファイル 5 点だけで 19,658 トークンある。

```
PROMPT.md                 7055
skill-to-mcp.md           7349
SKILL.md                   714
server.py                 2191
test_server.py            2349
                  合計  19,658
```

ここに opencode のシステムプロンプトとツール定義が加わるため、
最初の応答を始める時点で 32000 にかなり近い。
`context` を 60000 に上げた試行 4 では同じ現象は起きなかった。

### 実際の原因
推測: コンテキスト長の切り詰めで PROMPT.md が履歴から落ちた（候補 2）。
opencode の切り詰めアルゴリズムは確認していないため断定しない。
ただし context を上げると再現しなくなったことから、整合する。

### 解決策
1. `limit.context` を実機の上限（65536）に近づける
2. **PROMPT.md 側の対策**: STEP 1〜4 の成果物を会話ではなく
   `docs/porting-notes.md` に書かせる。
   会話が切り詰められても、ファイルに残っていれば読み直せる。

### 解決確認
context を 60000 にした試行では、タスクを見失う現象は再現しなかった。
`porting-notes.md` への書き出し指示も機能し、STEP 1〜2 の内容がファイルに残った。

### 再発防止
PROMPT.md の「作業の全体像」直後に「途中経過はファイルに書いてください」節を追加した。
理由（会話は切り詰められるが、ファイルは残る）も併記した。

---

## Issue: completion_tokens を消費しているのに content が None で返る

### 症状

ゲートウェイに STEP 3 の実行を依頼したところ、`usage.completion_tokens` が
`max_tokens` に指定した 1600 に達し 57 秒かかったにもかかわらず、
`choices[0].message.content` が `None` だった。
これを `write()` に渡したスクリプトが
`TypeError: write() argument must be str, not None` で落ちた。

### 影響

生成が成功しているのか失敗しているのかが判別できない。
opencode 経由の 4 回の失敗も、同じ事象を別の形で見ていた可能性がある。

### 原因候補

1. ゲートウェイが本文を別フィールドに入れている
2. `finish_reason` が `length` で本文が捨てられている
3. モデルが空応答を返した

### 切り分け

`message` オブジェクトを `json.dumps` でそのまま出力した。結果:

```json
{"finish_reason": "stop",
 "message": {"content": "\n\n2", "role": "assistant",
             "reasoning_content": "Here's a thinking process:\n1. **Analyze User Input:** ..."}}
```

`finish_reason` は `length` ではなく `stop`。本文は `reasoning_content` にあった。
候補 1 が正しい。

確認のため「1+1は？ 短く答えて。」という最小の質問を投げたところ、
それでも `reasoning_content` が 1304 字生成された。
つまりタスクの難易度とは無関係に、毎ターン思考が走る。

### 実際の原因

`qwen36-35b-a3b` は推論モデルであり、既定で thinking が有効。
思考は `reasoning_content` に入り、`content` とは別枠だが
**`max_tokens` と応答時間は共有する**。
STEP 3 では 1600 トークンの枠を思考が使い切り、本文が出る前に打ち切られた。

### 解決策

リクエストボディに次を追加する。

```json
{ "chat_template_kwargs": { "enable_thinking": false } }
```

他に `reasoning_effort: "none"` / `"low"`、
`thinking: {"type": "disabled"}`、プロンプト末尾の `/no_think` を試したが、
**いずれも無視された**（thinking が 1287〜1441 字生成され続けた）。
効いたのは `chat_template_kwargs` のみ。

### 解決確認

同じ STEP 3 のリクエストが、thinking 有効時は 1600 トークン / 57 秒で
本文 0 字だったのに対し、無効化後は 990 トークン / 38 秒で
17 行の仕分け表が返った。60 秒の壁の内側に収まった。

### 再発防止

PROMPT.md の「実行環境の要件」に推論モデルの節を追加し、
5 通りの比較表と効く設定を明記した。
推論モデルを使う場合、この設定が無いと失敗は
「モデルの能力不足」に見えるが、実際は設定の問題である。
