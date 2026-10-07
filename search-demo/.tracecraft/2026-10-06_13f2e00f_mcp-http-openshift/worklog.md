# Work Log

> 作業タイトル: search-demo を MCP Streamable HTTP サーバー化し OpenShift に配備可能にする
> 開始日時: 2026-10-06
> 目的: `search-demo` の公開 API 横断検索を、2026 年時点のモダンな構成で MCP の HTTP ワークロードとして提供し、コンテナ化と OpenShift 配備マニフェストを用意し、virt 上の VM で動く opencode とクラスタ内 agent framework Pod の双方から利用可能にする
> 背景: 既存の `search-demo` には Python CLI (`search_demo.py`) と opencode 用 Skill (`.opencode/skill/public-api-search/SKILL.md`) があるが、Skill 版は実行環境（Python, スクリプトの配置）をクライアント側に要求し、ローカル利用に限定される
> 期待する最終成果: MCP サーバー実装 / Containerfile / OpenShift マニフェスト一式 / クライアント接続例 / Skill→MCP 移植ナレッジのドキュメント

---

## Step 1: 既存資産の把握

### 目的
移植対象である `search_demo.py` と `SKILL.md` の内容・インターフェースを確定する。

### 背景
MCP ツールの description とスキーマをどう設計するかは、既存 Skill の記述内容に依存する。

### 事前仮説
CLI のオプションがそのまま MCP ツールの入力スキーマになる。

### 実行内容
#### 変更・操作
- `ls -la /Users/kono/gitrepo/mcp-demo` と `find /Users/kono/gitrepo/mcp-demo/search-demo -type f` でファイル構成を確認
- `cat` で `search_demo.py`, `pyproject.toml`, `mise.toml`, `.opencode/skill/public-api-search/SKILL.md`, `README.md` を読んだ

#### 観察した出力
- `search_demo.py`: 標準ライブラリのみ。`SOURCES` dict に 4 ソース（wikipedia / hackernews / github / stackoverflow）、`run_search(query, sources, limit, lang) -> dict` が `ThreadPoolExecutor` で並列取得し `{"query","count","results","errors"}` を返す。同期実装
- `pyproject.toml`: `name = "search-demo"`, `version = "1.0.0"`, `dependencies = []`, `[project.scripts] search-demo = "search_demo:main"`, hatchling の `only-include = ["search_demo.py"]`（単一モジュール構成）
- `SKILL.md`: frontmatter の `description`、オプション表（`--source`/`--limit`/`--lang`/`--format`）、出力 JSON 例、「使い分けの指針」5 項目、「注意」3 項目
- `mise.toml`: python 3.12, uv 0.12.23

#### 参照した情報源
- `/Users/kono/gitrepo/mcp-demo/search-demo/search_demo.py`（`run_search`, `SOURCES`, `main`）
- `/Users/kono/gitrepo/mcp-demo/search-demo/.opencode/skill/public-api-search/SKILL.md`
- `/Users/kono/gitrepo/mcp-demo/search-demo/pyproject.toml`

### 期待結果
MCP 化に必要な関数シグネチャとガイダンス文面が揃う。

### 実際の結果
`run_search` が MCP ツールから直接呼べる形（引数 4 つ・dict 返り）になっていた。
`SKILL.md` の「使い分けの指針」と「注意」は MCP の description に移すべき内容だった。

### 解釈
事実: `search_demo.py` は依存ゼロの単一モジュールで、パッケージとして配布可能な形（pyproject あり）。
事実: `run_search` は同期実装であり、非同期サーバーから呼ぶにはスレッドへの退避が要る。
推測: CLI オプションの `--format` はモデル向けには不要（構造化出力があるため）。

### 次の判断
ユーザーに認証方式とコード構成の方針を確認する。1 対 1 の機械的移植にはならないので、方針を先に固めたい。

---

## Step 2: 方針の確認（認証とコード構成）

### 目的
後戻りの大きい 2 点（認証方式・既存コードの扱い）をユーザーに確認する。

### 背景
認証方式は OpenShift マニフェストの構造（Secret / OAuth 連携の有無）に波及し、コード構成はコンテナの build context に波及する。

### 事前仮説
Bearer トークンとパス依存による再利用が妥当。

### 実行内容
#### 変更・操作
AskUserQuestion で 2 問を提示。

#### 観察した出力
- 認証: 「Bearer トークン (推奨)」を選択
- コード構成: 「既存を再利用する」＋追加要望「これはリファレンス実装でもあり、SKILL に書いてある内容を MCP のコードの description などにどう落とすのかも含めてナレッジを残したいのでドキュメンテーションをしっかり作ってほしい」

#### 参照した情報源
N/A

### 期待結果
方針が確定する。

### 実際の結果
方針確定に加え、**Skill→MCP の翻訳ナレッジのドキュメント化**が成果物として追加された。

### 解釈
事実: ドキュメントが副産物ではなく主成果物の一つになった。

### 次の判断
MCP Python SDK の現行 API を確認してから実装に入る。知識で書くと API 名を誤る可能性がある。

---

## Step 3: MCP Python SDK の現行 API 調査

### 目的
2026 年時点の MCP Python SDK で Streamable HTTP サーバーを書く正しい API を確定する。

### 背景
記憶にある `mcp.server.fastmcp.FastMCP` が現行かどうか未確認。

### 事前仮説
`FastMCP` に `transport="streamable-http"` で起動する。

### 実行内容
#### 変更・操作
- `/tmp/mcpenv` に `uv venv` + `uv pip install mcp uvicorn starlette`
- `python -c "from mcp.server.fastmcp import FastMCP"` を実行
- 続けて `MCPServer.__init__`, `MCPServer.streamable_http_app`, `MCPServer.tool`, `TokenVerifier`, `AuthSettings`, `TransportSecuritySettings` のシグネチャを `inspect` で出力

#### 観察した出力
- `from mcp.server.fastmcp import FastMCP` が `ModuleNotFoundError` で失敗し、「This is mcp 2.x, where FastMCP was renamed to MCPServer (from mcp.server.mcpserver import MCPServer)」というエラーメッセージが出た。インストールされたのは `mcp 2.3.0`
- `MCPServer.streamable_http_app(*, streamable_http_path='/mcp', json_response=False, stateless_http=False, transport_security=None, host='127.0.0.1', ...) -> Starlette`
- `MCPServer.custom_route(path, methods, ...)` がある
- `AuthSettings` のフィールドに `issuer_url`（必須）, `resource_server_url`, `validate_token_resource` がある
- `TransportSecuritySettings` のフィールドは `enable_dns_rebinding_protection`, `allowed_hosts`, `allowed_origins`

#### 参照した情報源
- インストールした `mcp` パッケージ本体（2.3.0）の `mcp/server/fastmcp.py` が出すエラーメッセージ、および `inspect.signature` の出力

### 期待結果
FastMCP ベースで書ける。

### 実際の結果
SDK はメジャーバージョンが上がっており（2.3.0）、`FastMCP` は `MCPServer` に改名、API も変化していた。

### 解釈
事実: 記憶ベースで書いていたら動かないコードになっていた。
事実: `stateless_http` と `transport_security` が `streamable_http_app` の引数として用意されており、水平スケールと DNS rebinding 対策は SDK の機能で賄える。

### 次の判断
`MCPServer` ベースで実装する。認証は `AuthSettings`（OAuth 前提）ではなく ASGI ミドルウェアにするか判断が要る → decisions に記録。

---

## Step 4: サーバー実装

### 目的
MCP サーバー本体を書く。

### 背景
Step 3 で API が確定した。

### 事前仮説
`run_search` を薄くラップするだけで済む。

### 実行内容
#### 変更・操作
以下を新規作成:
- `/Users/kono/gitrepo/mcp-demo/search-mcp/pyproject.toml` — `mcp>=2.3,<3`, `uvicorn[standard]`, `search-demo==1.0.0` に依存。`[tool.uv.sources] search-demo = { path = "../search-demo" }`
- `src/search_mcp/settings.py` — 環境変数からの設定（`MCP_PORT`, `MCP_STATELESS_HTTP`, `MCP_AUTH_TOKENS`, `MCP_ALLOWED_HOSTS`, `MCP_MAX_LIMIT` ほか）
- `src/search_mcp/auth.py` — `BearerTokenMiddleware`（`hmac.compare_digest` で定数時間比較、`/healthz` `/readyz` を除外）
- `src/search_mcp/server.py` — `build_server()`。`SOURCE_GUIDE` dict、`INSTRUCTIONS`、`search` / `list_search_sources` ツール、Pydantic 出力モデル
- `src/search_mcp/app.py` — `create_app()`。custom_route で health を追加し、`streamable_http_app()` を認証ミドルウェアで包む
- `src/search_mcp/__main__.py` — uvicorn 起動（`proxy_headers=True`, `timeout_graceful_shutdown=20`）

`run_search` は同期なので `anyio.to_thread.run_sync` で退避した。

#### 観察した出力
`uv sync --extra dev` が最初 `OSError: Readme file does not exist: README.md` で失敗。README.md を作成後は成功。

#### 参照した情報源
- Step 3 で得た `MCPServer` の API シグネチャ
- `search_demo.run_search` / `search_demo.SOURCES`

### 期待結果
サーバーが組み上がる。

### 実際の結果
ファイルは揃ったが、この時点では未実行。

### 解釈
事実: `pyproject.toml` の `readme` フィールドは hatchling のビルド時に実在チェックされる。

### 次の判断
テストを書いて実際に動かす。

---

## Step 5: テスト作成と実行（2 回の失敗を経て成功）

### 目的
MCP プロトコル越しの振る舞い（ツール公開・スキーマ・認証・structured output）を検証する。

### 背景
description とスキーマは「モデルに届くもの」なので、プロトコル越しに確認しないと意味がない。

### 事前仮説
`httpx.ASGITransport` で in-process に叩けば十分。

### 実行内容
#### 変更・操作
- `tests/test_server.py` を作成。`search_demo.run_search` を monkeypatch し外部 API を叩かない構成
- `uv run pytest` を 4 回実行（うち 3 回失敗）し、都度修正

#### 観察した出力
1 回目: 全 9 件が `InvalidSignature: Unable to evaluate type annotations for callable 'search'`（原因は `__cause__` に `NameError("name 'settings' is not defined")`）
2 回目: 7 件が `RuntimeError: Task group is not initialized. Make sure to use run().`
3 回目: 5 件が `AttributeError: 'CallToolResult' object has no attribute 'structuredContent'. Did you mean: 'structured_content'?`
4 回目: `9 passed in 2.66s`

#### 参照した情報源
- pytest の失敗トレースバック
- `mcp_types.Tool.model_fields` / `CallToolResult.model_fields` の出力（`input_schema`, `structured_content`, `is_error` などスネークケース）

### 期待結果
一発で通る。

### 実際の結果
3 つの異なる原因で失敗し、それぞれ修正して 9 件全て成功。詳細は troubleshooting.md の Issue 1〜3。

### 解釈
事実: SDK 2.x はモデルのフィールド名がスネークケース（`structured_content` 等）。
事実: `MCPServer` が返す Starlette アプリは lifespan の実行が必須で、ASGITransport では起動しない。

### 次の判断
コンテナ化に進む。

---

## Step 6: コンテナ化

### 目的
OpenShift で動くイメージを作り、実際に起動することを確認する。

### 背景
`[tool.uv.sources]` のパス依存があるため、build context の設計が必要。

### 事前仮説
UBI9 python-312 のマルチステージで組める。

### 実行内容
#### 変更・操作
- `/Users/kono/gitrepo/mcp-demo/Containerfile` を作成（リポジトリルート配置）。builder: `ubi9/python-312` + uv 0.12.23、runtime: `ubi9/python-312-minimal`、`USER 1001`
- `uv lock` で `search-mcp/uv.lock` を生成（48 パッケージ解決）
- `mise install podman@latest` で podman 6.1.3 を導入し、シンボリックリンク名を修正
- `podman build -f Containerfile -t search-mcp:1.0.0 .` を 2 回実行（1 回目のイメージは起動に失敗）
- `podman run` で起動確認、`podman exec` でコンテナ内から疎通確認
- `/Users/kono/gitrepo/mcp-demo/.dockerignore` を追加後、再ビルドして再確認

#### 観察した出力
- 1 回目のビルドは成功したが `podman run` で `ModuleNotFoundError: No module named 'search_mcp'`
- `uv sync --no-editable` に変更後、再ビルドして起動成功
- コンテナ内から: `health: ok` / `noauth: 401 Bearer realm="search-mcp"` / `uid: 1001`
- `--user 1000670000:0` でも起動成功（ログに `Application startup complete.`）
- ビルド時に `HEALTHCHECK is not supported for OCI image format and will be ignored` の警告

#### 参照した情報源
- podman のビルド出力と `podman logs`
- CLAUDE.md の「mise-installed podman の shim naming issue」の手順

### 期待結果
イメージが起動し health が返る。

### 実際の結果
`--no-editable` 修正後に起動成功。任意 UID（1000670000）での起動も確認。

### 解釈
事実: `uv sync` の既定は editable install で、builder ステージのパスを指す `.pth` が残るため、runtime ステージ単独では import できない。
事実: このイメージは OpenShift の restricted-v2 SCC（任意 UID 注入）で動く。
事実: `HEALTHCHECK` は OCI フォーマットでは無視される。Kubernetes の probe を使うので実害はない。

### 次の判断
OpenShift マニフェストを書く。

---

## Step 7: OpenShift マニフェスト作成と検証

### 目的
`oc apply -k` で配備できるマニフェスト一式を用意する。

### 背景
VM からは Route 経由、クラスタ内 Pod からは Service 経由という 2 経路を同時に満たす必要がある。

### 事前仮説
Deployment / Service / Route / NetworkPolicy / HPA / PDB で足りる。

### 実行内容
#### 変更・操作
`search-mcp/deploy/openshift/` に作成:
`namespace.yaml`, `serviceaccount.yaml`, `configmap.yaml`, `secret.example.yaml`, `deployment.yaml`, `service.yaml`, `route.yaml`, `networkpolicy.yaml`（4 本）, `hpa.yaml`, `pdb.yaml`, `build.yaml`, `kustomization.yaml`
- `mise install kubectl@latest` で kubectl を導入
- `kubectl kustomize .` でレンダリング検証

#### 観察した出力
- 1 回目: `# Warning: 'commonLabels' is deprecated. Please use 'labels' instead.`、`kind:` が 12 個、image が `image-registry.openshift-image-registry.svc:5000/search-mcp/search-mcp:1.0.0` に置換されている
- `labels: - includeSelectors: false` に書き換え後: 警告なしでレンダリング成功
- `kubectl apply --dry-run=client` は API discovery のためクラスタ接続を要求し `connection refused` で失敗

#### 参照した情報源
- `kubectl kustomize` の出力と警告

### 期待結果
警告なしでレンダリングでき、API 検証も通る。

### 実際の結果
レンダリングは成功。**API スキーマ検証はクラスタが無いため未実施。**

### 解釈
事実: YAML の構文とリソース構成は kustomize が解釈できる形になっている。
推測: フィールド名の誤りがあっても kustomize は検出しないため、実クラスタでの `oc apply --dry-run=server` が別途必要。

### 次の判断
ドキュメントとクライアント接続例を書く。

---

## Step 8: クライアント接続例と実 HTTP での疎通確認

### 目的
配備後の利用方法を実際に動く形で示す。

### 背景
「VM 上の opencode から」「Pod の agent framework から」の 2 経路を成果物として求められている。

### 事前仮説
`examples/smoke_client.py` をローカルサーバーに対して動かせば検証になる。

### 実行内容
#### 変更・操作
- `examples/smoke_client.py`, `examples/opencode.json`, `examples/agent-pod.yaml` を作成
- ローカルで `MCP_AUTH_TOKENS=demo-token MCP_PORT=18082 uv run search-mcp` を起動し、`MCP_URL=... MCP_TOKEN=... uv run python examples/smoke_client.py "rust tui"` を実行
- 先に、コンテナ（`--network host`）に対して同じことを試したが失敗

#### 観察した出力
- コンテナ相手: `httpx2` の接続エラー（ExceptionGroup）。DooD 構成のため sibling コンテナの publish ポートはこのコンテナの localhost にはない
- ローカルサーバー相手: `connected: name='search-mcp' title='Public API Search' version='1.0.0'`、instructions 全文、2 ツールの description 1 行目、`search('rust tui')` の結果 8 件（wikipedia / hackernews / github / stackoverflow が混在、`errors: []`）

#### 参照した情報源
- `smoke_client.py` の出力

### 期待結果
MCP クライアントとして完全に動作する。

### 実際の結果
instructions・ツール description・structured output・実 API 検索結果まで一通り確認できた。

### 解釈
事実: サーバーは MCP クライアントから正常に利用できる。
事実: コンテナのネットワーク到達性はこの実行環境（DooD）の制約であり、イメージの問題ではない（Step 6 で `podman exec` 経由では疎通確認済み）。

### 次の判断
ドキュメントを書いて仕上げる。

---

## Step 9: ドキュメント作成

### 目的
Skill→MCP の翻訳ナレッジを中心に、再現可能な形で文書化する。

### 背景
Step 2 でユーザーが明示的に要望した成果物。

### 事前仮説
対応表を作れば済む。

### 実行内容
#### 変更・操作
作成したファイル:
- `search-mcp/docs/skill-to-mcp.md` — SKILL.md の各部分が MCP のどこに対応するか、落としたもの・足したもの、移植チェックリスト
- `search-mcp/docs/deploy-openshift.md` — ビルドから配備、設計判断
- `search-mcp/docs/clients.md` — VM / Pod 双方の接続設定、切り分け表
- `search-mcp/docs/security.md` — 認証方式の選択理由、ローテーション、OAuth 移行手順
- `search-mcp/README.md` — 全体像
- `/Users/kono/gitrepo/mcp-demo/mise.toml` — 検証に使った podman / kubectl を記録

#### 観察した出力
N/A（ファイル作成のみ）

#### 参照した情報源
- 本セッションの Step 1〜8 の実行結果
- `SKILL.md` と `server.py` の実際の記述

### 期待結果
あとから読んで Skill→MCP 移植を再現できる文書になる。

### 実際の結果
対応表だけでなく「なぜ 1 対 1 にならないか」（散文 vs スキーマ、強制力の有無）を軸にした文書になった。

### 解釈
事実: `--format` や `-s all` のように、CLI の UI 都合で存在するオプションは MCP では不要になる。
事実: 「`-n` を小さくする」という注意書きは、共有サーバーでは `Field(le=...)` として強制すべき内容に変わる。

### 次の判断
最終確認（テスト再実行・再ビルド）を行い、finalize する。

---

## Step 10: 最終確認

### 目的
全成果物が揃った状態で、テストとビルドが通ることを確認する。

### 背景
`.dockerignore` 追加などビルドに影響する変更を後から入れたため。

### 事前仮説
問題なく通る。

### 実行内容
#### 変更・操作
- `uv run pytest -q`
- `podman build -q -f Containerfile -t search-mcp:1.0.0 .`
- `podman run` + `podman exec` で health 確認

#### 観察した出力
- `9 passed in 2.66s`
- ビルド成功（イメージ ID `5f9fbeea811d...`）
- `health: ok` / `image ok after .dockerignore`

#### 参照した情報源
N/A

### 期待結果
全て成功。

### 実際の結果
全て成功。

### 解釈
事実: `.dockerignore` で tests/docs/deploy を除外してもイメージは正常に動作する。

### 次の判断
finalize（final-guide.md と retrospective.md の生成）。

---

## Step 11: skill-to-mcp.md の射程拡張（他の型の Skill への一般化）

### 目的
`docs/skill-to-mcp.md` が `public-api-search`（単一スクリプト・読み取り専用・
1 回で完結・添付なし）という最も素直な型の移植記録に留まっており、
他の型の Skill を移植する際に判断材料が不足していた。これを埋める。

### 背景
ユーザーから「skill-to-mcp.md を見れば今後 skill を mcp に実装していくのは
問題なくできそうか」という問いがあった。既存文書を読み直して穴を列挙し、
ユーザーが追記を承認した。

### 事前仮説
不足しているのは次の 4 点（+ 小さい 3 点）:
1. ローカルファイル・状態に依存する Skill の扱い（移植可否を分ける最大の分岐）
2. 副作用のある Skill — 認証粒度・冪等性・確認フロー
3. Resources / Prompts への言及が皆無（MCP の 3 プリミティブのうち Tools のみ）
4. 失敗の返し方（`errors` フィールド vs `is_error`）の一般論化
小: description の長さの目安 / 移植の検証方法 / 長時間処理

### 実行内容

**変更:**
`/Users/kono/gitrepo/mcp-demo/search-mcp/docs/skill-to-mcp.md` に以下を追加
（276 行 → 615 行）。既存 §1〜§5 は内容を変更せず、§4 の項目 5 に
「目安は後述（§4.1）」の参照のみ追記した。

- 冒頭に射程の注記ブロック（この例は最も素直な型であること）
- **§0 移植判定** — 4 つの分岐（ローカル依存 / 副作用 / 添付ファイル / 単発か）
  を図示し、それぞれ §6〜§8 と decisions.md へ誘導
- **§2.7 失敗の返し方** — 部分失敗は structured output、呼び出し自体の失敗は
  `is_error`。本実装が `SearchResponse.errors` を選んだ理由と、
  「count==0 なら errors を読め」という注意書きがその設計の帰結であること
- **§4.1 description の長さの目安** — 〜400 / 400〜1000 / 1000 超の 3 段階と
  分割の切り口（「呼ぶ前に必ず要るか」）
- **§4.2 移植できたことの検証** — 「起動する」ではなく
  「ガイダンスが届いている」を検証する。`tests/test_server.py` の実アサーションを引用
- **§6 ローカル依存の Skill** — Skill と MCP が競合しないこと、
  「MCP 化しない」が正解のケース、薄い Skill + MCP の折衷、
  ファイル内容を引数で渡す場合の注意（4 MiB 上限 / ログ / 秘匿情報）
- **§7 副作用のある Skill** — 認証粒度の表、annotations の正しい申告、
  冪等キー、plan/apply 2 段分割
- **§8 添付ファイルを持つ Skill** — Tools / Resources / Prompts の役割分担、
  本実装が `list_search_sources` を Resource でなく Tool にした理由
- **§9 まとめ表** — 本例が扱った論点と扱っていない論点の明示

**操作（事実確認）:**
`§8` で `@mcp.resource` / `@mcp.prompt` の存在と引数を推測で書かないため、
SDK の実シグネチャを確認した。

**観察した出力:**
```
resource (self, uri: 'str', *, name: 'str | None' = None, title: 'str | None' = None, ...)
prompt (self, name: 'str | None' = None, title: 'str | None' = None, ...)
```
`@mcp.resource("guide://sources/{name}", title=...)` と
`@mcp.prompt(title=...)` のどちらも有効と確認。

**参照した情報源:**
- `/Users/kono/gitrepo/mcp-demo/search-mcp/docs/skill-to-mcp.md`（改訂前 276 行）
- `.tracecraft/2026-10-06_13f2e00f_mcp-http-openshift/decisions.md`
  （stateless_http / ツール 2 分割 / limit 上限の各項）
- `.tracecraft/.../findings.md`（`max_request_body_size=4194304` の既定値）
- `search-mcp/docs/security.md`（認証粒度の記述との整合）

### 期待結果
- 文書が破綻せず、既存 §1〜§5 の内容が保たれていること
- 既存のテスト 9 件が引き続き通ること（文書のみの変更なので当然だが確認する）

### 実際の結果
- `grep -c '' skill-to-mcp.md` → `615`（改訂前 276 行）
- `uv run pytest -q` → `9 passed in 2.67s`

### 解釈
事実: 文書のみの変更であり、コードとテストに影響していない。
事実: `@mcp.resource` / `@mcp.prompt` は SDK に実在し、文書中のコード例は
シグネチャ上有効である。ただし**実際に動作させてはいない**（本実装では未使用）。

推測: §6 の「MCP 化しない」判断基準と §7 の認証粒度の表は、
本作業で実地検証したものではなく、本作業で得た知見からの一般化である。
特に §7.3 の冪等キーと §7.4 の plan/apply 分割は、本実装に該当するツールが
存在しないため、設計上の指針にとどまる。

### 次の判断
文書の射程拡張は完了。§8 のコード例は未実行であり、
Resources / Prompts を実際に使う Skill を移植する機会に検証する。

---

## Step 12: GitHub リポジトリの作成と push

### 目的
成果物一式を GitHub リポジトリとして公開する。

### 背景
作業ディレクトリ `/Users/kono/gitrepo/mcp-demo` は git リポジトリではなかった
（セッション開始時の環境情報および `git status` の
`fatal: not a git repository` で確認済み）。
ユーザーから `gh` コマンドでのリポジトリ作成と push の依頼があった。

### 事前仮説
- `.venv/` が 72 MB あり、そのままでは不要なものを push してしまう → `.gitignore` が要る
- 公開範囲は外部に出る不可逆な判断なので、ユーザーに確認すべき
- 公開リポジトリに秘密情報が含まれていないか、事前に走査すべき

### 破壊的操作の事前記録
- **操作対象**: GitHub 上の新規リポジトリ `konono/mcp-demo`、およびローカルの git 初期化
- **操作目的**: 成果物の公開
- **影響範囲**: 外部（GitHub）。公開リポジトリは第三者から参照され、
  キャッシュやインデックスに残りうる
- **破壊的か**: 既存データの破壊はない。ただし**公開は不可逆**
  （削除してもキャッシュ・フォーク・インデックスは消えない）
- **事前確認した状態**: `gh auth status` で konono としてログイン済み、
  既存の同名リポジトリは `gh repo create` が失敗しないことで非存在を確認
- **復旧方法**: `gh repo delete konono/mcp-demo`。
  ただし公開済みの内容は取り消せない
- **実行後に確認する状態**: リポジトリの visibility、ルート直下のファイル一覧、
  `.venv` が含まれていないこと

### 実行内容

**操作 1: 認証と現状の確認**
```
gh auth status  → Logged in to github.com account konono (GITHUB_TOKEN)
git status      → fatal: not a git repository
du -sh search-mcp/.venv → 72M
```

**操作 2: 秘密情報の走査**
```
grep -rniE "(gho_|ghp_|BEGIN .*PRIVATE KEY|password|api[_-]?key *[:=])" .
```
→ `.venv/` と `__pycache__` を除外した結果、**該当なし**。
`deploy/openshift/secret.example.yaml` はプレースホルダのみで、
kustomization の resources からも外してある（Step 7 の判断）。

**操作 3: ユーザーへの確認（AskUserQuestion）**
- 公開範囲 → **public**（ユーザー選択）
- `.tracecraft/` を含めるか → **含める**（ユーザー選択）

**変更 1: `/Users/kono/gitrepo/mcp-demo/.gitignore` を新規作成**
`__pycache__/`, `.venv/`, `dist/`, `*.egg-info/`, `.pytest_cache/`,
`.env`, `*.secret.yaml` を除外。
`secret.example.yaml` はプレースホルダなので**追跡対象のまま**にし、
その旨をコメントに明記した。

**変更 2: `/Users/kono/gitrepo/mcp-demo/README.md` を新規作成**
リポジトリルートに README が無く、公開すると入口が無い状態だったため作成。
Skill 版と MCP 版の対比表、`docs/skill-to-mcp.md` を主眼として提示、
ドキュメント索引、`.tracecraft` への導線、すぐ動かす手順、構成図、
**検証状況の表（API スキーマ検証が未実施であることを ❌ で明示）** を含めた。

**操作 4: git 初期化とコミット**
```
git init -b main && git add -A
git -c user.name=... -c user.email=... commit -F - <<...
```

**操作 5: リポジトリ作成と push**
```
gh repo create mcp-demo --public --source=. --remote=origin --push --description "..."
```

### 期待結果
- 追跡ファイルが 60〜70 件、合計 1 MB 未満（`.venv` が除外されている）
- public リポジトリが作成され、main ブランチが push される

### 実際の結果

`git status --short | wc -l` → **68 ファイル**
`git ls-files | xargs du -ch | tail -1` → **764K**

`.tracecraft/` は今回のセッション（`13f2e00f`）だけでなく、
`search-demo` 自体を作った過去 3 セッション分
（`4f25b8be_mise-toml-seiritsu`, `dd86561f_pyproject-toml`,
`fef304fd_public-api-search-demo`）も含まれていた。
いずれも秘密情報の走査済み範囲内なのでそのまま含めた。

コミット: `a028ac8 Add MCP HTTP server, container, and OpenShift manifests for search-demo`

push 出力:
```
https://github.com/konono/mcp-demo
To https://github.com/konono/mcp-demo.git
 * [new branch]      HEAD -> main
branch 'main' set up to track 'origin/main'.
```

事後確認:
```
gh repo view --json url,visibility,defaultBranchRef
  → https://github.com/konono/mcp-demo / PUBLIC / main
gh api repos/konono/mcp-demo/contents --jq '.[].name'
  → .dockerignore .gitignore Containerfile README.md mise.toml search-demo search-mcp
```
`.venv` がリモートに存在しないことを確認。

### 解釈
事実: public リポジトリとして公開され、追跡内容は意図したものと一致している。
事実: 秘密情報の走査で該当は無く、`secret.example.yaml` はプレースホルダのみ。

推測: `.tracecraft/` の過去 3 セッション分も公開対象になったが、
ユーザーの「含める」という選択は今回のセッション分を念頭に置いたものだった可能性がある。
内容はいずれも `search-demo` の作成過程であり、秘密情報は含まれていないため
そのままとしたが、ユーザーに事実として報告する。

### 次の判断
この Step 12 とフェーズ 12 の記録自体が未コミットなので、追記後に 2 つ目の
コミットとして push する。

---

## Step 13: MIT ライセンスの追加

### 目的
public リポジトリにライセンス表記を追加し、第三者が利用できる状態にする。

### 背景
Step 12 で public として公開したが LICENSE ファイルが無かった。
ライセンス表記の無い公開リポジトリは法的には全権利留保の扱いになり、
リファレンス実装として参照・再利用してもらう意図と矛盾する。
最終報告でこの点を指摘し、ユーザーが MIT を選択した。

### 事前仮説
- `LICENSE` ファイルの設置だけで GitHub はライセンスを認識する
- `pyproject.toml` の `license` フィールドも揃えておくべき
- PEP 639 の SPDX 文字列形式（`license = "MIT"`）が現行の書き方だが、
  hatchling のバージョンが対応しているかは未確認

### 実行内容

**変更 1: `/Users/kono/gitrepo/mcp-demo/LICENSE` を新規作成**
MIT License 全文。著作権表記は `Copyright (c) 2026 konono`
（`gh auth status` で確認済みのアカウント名を使用）。

**変更 2: `/Users/kono/gitrepo/mcp-demo/search-mcp/pyproject.toml`**
`readme = "README.md"` の次行に `license = "MIT"` を追加。

当初 `license-files = ["../LICENSE"]` も併記したが、
プロジェクトルート外のパスを hatchling が受け付けるか不明だったため削除した。
LICENSE はリポジトリルートにあり、2 つのパッケージから共有される配置になっている。

**変更 3: `/Users/kono/gitrepo/mcp-demo/search-demo/pyproject.toml`**
同様に `license = "MIT"` を追加。

**変更 4: `/Users/kono/gitrepo/mcp-demo/README.md`**
末尾に「## ライセンス」節を追加し、LICENSE へリンクした。

**操作: ビルドとテストの確認**
```
cd search-mcp && uv lock && uv run pytest -q
```

### 期待結果
- `license = "MIT"`（SPDX 文字列形式）を hatchling が受け付け、ビルドが通ること
- 既存のテスト 9 件が通ること

### 実際の結果
```
Resolved 48 packages in 1ms
Installed 2 packages in 9ms
.........                                                                [100%]
9 passed in 2.65s
```

`Installed 2 packages` は `search-demo` と `search-mcp` の両ホイールが
再ビルドされたことを示しており、**両方の `pyproject.toml` の
`license = "MIT"` を hatchling が受け付けた**ことの確認になっている。

### 解釈
事実: PEP 639 の SPDX 文字列形式がこの hatchling バージョンで有効であり、
ビルドとテストに影響はない。

推測: `license-files` を省いたため、ビルドされたホイールの `.dist-info` に
LICENSE ファイル自体は同梱されていない可能性がある。
このパッケージは PyPI 公開を想定しておらず（`[tool.uv.sources]` のパス依存）、
リポジトリルートに LICENSE があれば用は足りるため、確認していない。

### 次の判断
コミットして push する。GitHub 側がライセンスを認識したかを
`gh repo view --json licenseInfo` で事後確認する。

---

## Step 14: E2E テストの設計と実装

### 目的
ユーザーから「E2E テスト。container build して立ち上げて curl レベルで問題なく動くか。
OpenShift 環境は無いが podman play などやれることを計画してテストしてほしい」
という依頼があった。単体テスト（9 件）が触れていない層を実際に動かして検証する。

### 背景
直前の回答で、単体テストの穴として次を報告していた:
- `search_demo` 本体のテストがゼロ
- OpenShift の ConfigMap が設定する経路（`MCP_JSON_RESPONSE=true`）が未検証
- DNS rebinding 保護はテストで**無効化**しており一度も動いていない
- コンテナイメージに対するテストが無い（`podman exec` での手動確認のみ）
- マニフェストの検証が無い

このうちコンテナ・設定経路・マニフェストを E2E で埋める。

### 事前仮説
- DooD 環境のため publish ポートには到達できない（Step 7 の既知の制約）。
  専用ネットワーク上にクライアントコンテナを置けば回避できるはず
- ランタイムイメージ（ubi9/python-312-minimal）に curl は入っていない可能性が高い
- `podman kube play` は Route / NetworkPolicy / HPA / PDB を解釈できないが、
  Deployment / ConfigMap / Service / Secret は扱えるはず

### 実行内容

**操作 1: 環境の確認**
```
podman --version          → 6.1.3
podman kube play --help   → 利用可能
podman run --entrypoint="" search-mcp:1.0.0 sh -c 'which curl'
                          → which 自体が無い。curl も無い
```
→ クライアント用に `registry.access.redhat.com/ubi9/ubi-minimal`（curl 7.76.1）を pull。

**操作 2: イメージの再ビルド**
既存イメージは 9 時間前のもので、Step 13 の `pyproject.toml` 変更を含まないため
再ビルドした。`2c6c24dabc8b`。

**操作 3: ネットワーク越しの到達性を確認（仮説検証）**
```
podman network create e2e-net
podman run -d --name e2e-srv --network e2e-net ... search-mcp:1.0.0
podman run --rm --network e2e-net ubi-minimal curl -w '%{http_code}' http://e2e-srv:8080/healthz
  → healthz=200
```
→ DooD でも専用ネットワーク経由なら到達できることを確認。この方式で進める。

**観察した出力（想定外）**: `/mcp` への POST が
`HTTP/1.1 421 Misdirected Request` / `Invalid Host header` を返した。
→ findings に「許可されていない Host の拒否は 400 ではなく 421」として記録。
ドキュメント 3 ファイル 4 箇所の記述が誤りだったと判明。

**操作 4: read-only rootfs の確認（未検証事項の解消）**
```
podman run -d --read-only --tmpfs /tmp --user 1000670000:0 ... search-mcp:1.0.0
  → Up 3 seconds / ro-healthz=200
```
→ findings（Step 6）の未確認事項「`readOnlyRootFilesystem: true` は podman 単体では
未検証」を解消した。

**操作 5: podman kube play の確認**
`kubectl kustomize` の出力（12 リソース）から ConfigMap / Service / Deployment を
抽出し、Secret を足して起動。マニフェストが指すクラスタ内レジストリのイメージ名は
`podman tag` でローカルイメージに別名を付けて解決した。
→ `Up 16 seconds (healthy)`。**Deployment の probe が podman の healthcheck に
変換され、実際に通ることを確認。** findings に記録。

**変更: `/Users/kono/gitrepo/mcp-demo/search-mcp/tests/e2e/run-e2e.sh` を新規作成**
上記の探索を 5 フェーズ 36 チェックとして恒久化した。

- Phase 1: イメージのメタデータ（USER / ENTRYPOINT / EXPOSE）
- Phase 2: SCC 相当（任意 UID + read-only rootfs + cap-drop ALL）
- Phase 3: HTTP 契約（**ConfigMap と同じ設定で起動**。json_response / DNS 保護を有効に）
- Phase 4: コンテナから外部 API への実疎通
- Phase 5: `podman kube play` での Deployment 起動と probe

設計上の判断:
- クライアントコンテナは常駐させて `podman exec` する
  （チェックごとにコンテナを起こすと 1 秒 × 20 回以上かかる）
- `trap cleanup EXIT` でコンテナ・Pod・Secret・ネットワーク・一時ディレクトリを掃除
- `E2E_SKIP_BUILD` / `E2E_SKIP_NETWORK` で部分実行できるようにした
- 失敗時は expected / actual を出す。FAIL が 1 件でもあれば exit 1

**変更: ドキュメントの訂正（4 箇所）**
- `search-mcp/docs/clients.md` トラブルシュート表: 400 → 421。
  「`/healthz` には適用されないので probe は通るのに `/mcp` だけ落ちる」を追記
- `search-mcp/docs/deploy-openshift.md`: 同上
- `.tracecraft/.../final-guide.md` §7 と §9: 同上

**変更: README の更新**
- ルート `README.md` の検証状況の表に E2E 36 件を追加し、
  Route / NetworkPolicy / HPA / PDB が検証できないことを ❌ で明示
- `search-mcp/README.md` に「テスト」節を新設。
  単体と E2E の守備範囲の違いを表にした

### 期待結果
- 36 チェックすべて PASS
- クリーンアップ後にコンテナ・ネットワークが残らない
- 単体テスト 9 件に影響しない

### 実際の結果

ビルドを含む完走:
```
== 結果
  PASS: 36
  FAIL: 0
EXIT=0
```

クリーンアップ確認:
```
$ podman ps -a --format '{{.Names}}' | grep -iE 'e2e|search-mcp'
$ podman network ls --format '{{.Name}}' | grep e2e
（いずれも出力なし）
```

単体テスト:
```
9 passed in 2.67s
```

### 解釈
事実: 単体テストが触れていなかった 3 つの層（コンテナランタイム、
本番設定の経路、Deployment マニフェスト）を実際に動かして確認できた。
特に `MCP_JSON_RESPONSE=true` と DNS rebinding 保護は、
**単体テストでは無効化しているためこれまで一度も実行されていなかった**。

事実: ドキュメントに推測で書いた「400」が誤りだった。
E2E を書いたことで、実装ではなく**ドキュメントのバグ**が 1 件見つかった。

推測: `podman kube play` が通ることは API スキーマ検証の代わりにはならない。
podman は自前のパーサで解釈しており、Kubernetes の admission とは別物のため、
フィールド名の typo は依然として検出できないと考えられる。
この点は findings の未確認事項に明記した。

### 次の判断
コミットして push する。残る穴は `search_demo` 本体の単体テストと
`Settings.from_env()` のテストで、これらは E2E の対象外。

---

## Step 15: 単体テストの穴埋め（search_demo 本体と Settings.from_env）

### 目的
Step 14 で E2E を整えた結果、残る未検証領域が 2 つに絞れた。
`search_demo.py`（検索ロジック本体）にテストが 1 件も無いことと、
`Settings.from_env()` が単体テストから到達していないこと。これを埋める。

### 背景
既存の `search-mcp/tests/test_server.py` は `search_demo.run_search` を
monkeypatch で差し替えている。MCP レイヤだけを見るための正しい設計だが、
その結果として**検索ロジック本体が壊れてもテストは緑のまま**になる。
E2E は実 API を 1 回叩くだけで、レスポンス形のバリエーション（欠けたフィールド、
null の `description`、HTML エスケープ）は通らない。

`Settings.from_env()` は ConfigMap / Secret から来る文字列の唯一の入口。
ここを間違えると「マニフェストは正しいのに挙動が既定値のまま」という
原因の見えにくい障害になる。E2E では正常系の組み合わせしか通らない。

### 事前仮説
- `search_demo` のテストは `urllib.request.urlopen` の差し替えで書ける。
  本体は `http_get_json` 内で `urlopen` を呼ぶだけなので、HTTP を模す必要はない。
- pytest を `search-demo` に入れると「依存ゼロ」という売りが崩れる懸念があるが、
  `[project.optional-dependencies] dev` に置けば実行時依存は増えない。

### 実行内容

**変更・操作:**

1. `search-demo/pyproject.toml` に dev extra を追加。
   ```toml
   # テストにだけ pytest が要る。実行時の依存ゼロは崩さない。
   [project.optional-dependencies]
   dev = ["pytest>=8"]
   ```
   `dependencies = []` はそのまま。

2. `search-demo/tests/test_search_demo.py` を新規作成（38 件）。
   `capture` フィクスチャで `urllib.request.urlopen` を差し替え、
   リクエスト URL を記録しつつ固定の JSON を返す。カバー範囲:
   - `http_get_json`: クエリ文字列の組み立て、日本語のパーセントエンコード、
     リスト値の展開（`doseq=True`）、HTTPError / URLError / JSONDecodeError →
     `SearchError` への正規化
   - `strip_html`: タグ除去、エンティティ復元、入れ子、閉じていない `<b`
   - 4 ソースのパース: Wikipedia の URL 組み立て（空白→`_`→quote）、
     HN の `title`→`story_title`→`(no title)` フォールバックと
     url 欠落時の `item?id=` フォールバック、GitHub の `description`/`language`
     が null のケース、Stack Overflow のタイトルの unescape
   - ソースごとに異なる件数パラメータ名（`srlimit` / `hitsPerPage` /
     `per_page` / `pagesize`）を取り違えていないこと
   - `run_search`: 複数ソースのマージ、部分失敗が `errors` に落ちること、
     `SearchError` 以外は握り潰さないこと、出力順が入力順であること
   - `main()`: 既定の全ソース展開、`-s` の重複排除、`-s all` の優先、
     `max(1, limit)` のクランプ、終了コード（全滅時のみ 1）

3. `search-mcp/tests/test_settings.py` を新規作成（27 件）。
   `autouse` フィクスチャで `MCP_*` を全削除し、実行環境に依存させない。
   既定値が README の表と一致すること、全変数が読まれること、
   真偽値の表記ゆれ（`1`/`true`/`TRUE`/`yes`/`on`/前後空白）、
   未知の値と空文字は false、**未設定と空文字が別物**であること、
   カンマ区切りの空白除去と空要素除去、`int` パース失敗は例外にすること、
   dataclass が frozen であることを確認。

4. `search-mcp/tests/test_server.py` に 2 件追記。
   `auth.py:62`（Bearer 以外のスキームを拒否）が未到達だったため、
   `Basic ...` / スキーム無し / `bearers3cret` / 空文字で 401 になることと、
   RFC 7235 どおり小文字 `bearer` は受けることを確認。

**観察した出力:**

```
# search-demo
38 passed in 0.04s
Name             Stmts   Miss  Cover   Missing
search_demo.py     102      1    99%   230

# search-mcp
38 passed in 3.70s
src/search_mcp/__init__.py       5      0   100%
src/search_mcp/__main__.py       9      9     0%   7-32
src/search_mcp/app.py           27      0   100%
src/search_mcp/auth.py          34      0   100%
src/search_mcp/server.py        45      0   100%
src/search_mcp/settings.py      27      0   100%
TOTAL                          147      9    94%
```

**参照した情報源:**
- `search-demo/search_demo.py` 全 231 行（各ソースのパースとフォールバックの確認）
- `search-mcp/src/search_mcp/settings.py:13-21`（`_split` / `_bool` の仕様）
- `search-mcp/src/search_mcp/auth.py:55-65`（`_is_authorized` の分岐）

### 期待結果
新規テストが通り、`settings.py` と `auth.py` のカバレッジが 100% になる。

### 実際の結果
期待どおり。両スイートとも初回実行で全件成功した。
`search_demo.py` の未到達は 230 行目（`if __name__ == "__main__"` ガード）のみ。
`search_mcp/__main__.py` は 0% のままだが、ここは uvicorn の起動処理で、
E2E（Phase 14）が実際にコンテナを起動して通している。

### 解釈
事実: 単体テスト総数は 9 → 76 件になった。
事実: 既存コードのバグは 1 件も見つからなかった。全テストが初回で通っている。

推測: バグが出なかったのは、`search_demo.py` が小さく（102 文）、
標準ライブラリだけで書かれていて分岐が浅いため。
ただしこれらのテストの価値は「今バグを見つけること」より
**回帰を防ぐこと**にある。特に 4 ソースの件数パラメータ名は
API ごとに違い（`srlimit` / `hitsPerPage` / `per_page` / `pagesize`）、
コピー&ペーストで取り違えやすい箇所だった。

事実: `test_unset_booleans_keep_their_default` が示すとおり、
`MCP_STATELESS_HTTP=""`（空文字で設定）は未設定とは異なり false になる。
Kubernetes の ConfigMap で値を空にしたまま残すと stateless が無効化される。
これは意図した挙動だが、マニフェストを書く際の落とし穴になる。

### 次の判断
README 3 箇所（ルート / search-mcp / search-demo）の検証状況を更新し、
コミットして push する。

---

## Step 16: 生成 AI 向けの移植指示書（PROMPT.md）の作成

### 目的
`skill-to-mcp.md` の知識を、人間ではなく**生成 AI に実行させる**ための
作業指示書を用意する。想定する読み手は 30B 前後のローカルモデル
（ユーザー指定: qwen3.6-35B 程度）。

### 背景
`skill-to-mcp.md` は人間のエンジニアが読んで判断するための文書で、
「〜を検討する」「〜が望ましい」といった**判断を委ねる書き方**が多い。
フロンティアモデルなら補完できるが、30B 級では曖昧さが脱落や誤解に直結する。

ユーザーの要求は「齟齬なく伝わる形で」。
つまり**判断を仰ぐのではなく、分岐表を引かせる**形に変換する必要がある。

### 事前仮説
小型モデルで失敗しやすいのは次の 4 点と想定した。
1. 手順を飛ばす（特に地味で重要な工程）
2. 暗黙の判断を要求されると、それらしい既定値で埋めてしまう
3. 長い文脈の前半で述べた制約を後半で忘れる
4. 検証していないことを検証したと書く

### 実行内容

**変更・操作:**

1. `/Users/kono/gitrepo/mcp-demo/PROMPT.md` を新規作成（約 480 行）。
   冒頭に「ここから下がエージェントへの指示」という区切りを置き、
   人間向けの使い方とエージェント向けの本文を物理的に分離した。

   仮説への対処を構造に落とした:

   | 想定した失敗 | 構造での対処 |
   |---|---|
   | 手順を飛ばす | 9 STEP に分割し、各 STEP の末尾で「STEP N 完了」と宣言させる。STEP 0 は「見本を読む」だけで、読めたことを 3 つの質問への回答で自己検証させる |
   | 暗黙の判断 | 判断箇所をすべて表にした。移植可否は「上から順に当てはめ、最初に合った行に従う」5 行の表。`ToolAnnotations` の 4 つの真偽値は性質別の 4 行表。文の分類は「元の文がこうなら → この分類」の対応表 |
   | 制約を忘れる | SDK の落とし穴 5 件を STEP 5 の冒頭に表で再掲し、同じ項目を末尾の完成チェックリストにも重複して置いた |
   | 検証のでっち上げ | 「やってはいけないこと」表に明記し、`podman kube play` がスキーマ検証にならないことを個別に書いた |

2. STEP 3（仕分け）を本体と位置づけ、出力フォーマットを固定した。
   分類は INSTRUCTIONS / DESCRIPTION / SCHEMA / GUARD / DROP の 5 つ。
   見本の `server.py:156-163`（スキーマ）と `server.py:169-170`（ガード）を
   行番号付きで参照させ、**同じ 1 文が 2 か所に落ちるのが正解**だと示した。

3. コピーして使えるテンプレートを 4 つ埋め込んだ。
   出力スキーマの Pydantic モデル、`build_server()` の骨格、
   テストの uvicorn 起動コード、`securityContext`。
   `＜...＞` を穴埋め箇所の目印として統一した。

4. Step 15 で得た知見を落とし穴として取り込んだ。
   環境変数の「未設定と空文字は違う」、許可外 Host は 421 であって 400/401 ではない、
   モックした境界の向こう側を誰がテストするか。

5. `README.md`（ルート）と `search-mcp/README.md` からリンクした。

**観察した出力:**

記載内容の裏取りとして実行:

```console
$ grep -n "def create_app" search-mcp/src/search_mcp/app.py && ls search-demo/.opencode/skill/public-api-search/ && ls Containerfile && grep -n "emptyDir\|runAsUser\|tmp" search-mcp/deploy/openshift/deployment.yaml
23:def create_app(settings: Settings | None = None) -> ASGIApp:
SKILL.md
Containerfile
34:        # restricted-v2 SCC が UID を割り当てるので runAsUser は書かない。
61:            # readOnlyRootFilesystem のため、書き込みが要る場所だけ emptyDir を当てる。
62:            - name: tmp
63:              mountPath: /tmp
94:        - name: tmp
95:          emptyDir: {}
```

`skill-to-mcp.md` の節番号も参照前に確認した:

```console
$ grep -n "^#\{1,3\} " search-mcp/docs/skill-to-mcp.md
23:## 0. 移植判定 — まずこれを通す
...
411:## 6. ローカルのファイル・状態に依存する Skill（§0-1）
469:## 7. 副作用のある Skill（§0-2）
537:## 8. 添付ファイルを持つ Skill（§0-3）
```

**参照した情報源:**
- `search-mcp/docs/skill-to-mcp.md` の節構成（§0 / §2.7 / §4.1 / §6〜§8 への参照を作るため）
- `search-mcp/src/search_mcp/server.py` 全 201 行（テンプレートの骨格と行番号参照）
- `search-mcp/src/search_mcp/app.py:23`（`create_app` のシグネチャ）
- `search-mcp/deploy/openshift/deployment.yaml:34,61-63,94-95`（`runAsUser` 不記載と emptyDir）

### 期待結果
判断を要する箇所がすべて表引きになっており、
小型モデルが自由記述で補完する余地が残っていないこと。

### 実際の結果
作成完了。PROMPT.md 内で参照している節番号・ファイルパス・行番号・
シンボル名は、上記のとおり実ファイルを読んで確認済み。

### 解釈
事実: `skill-to-mcp.md` の記述のうち、PROMPT.md で表に変換したのは
移植可否判定、文の分類、`ToolAnnotations` の 4 値、エラーの返し分けの 4 箇所。
いずれも元の文書では散文で「〜の場合は〜する」と書かれていた。

推測: 小型モデルで最も効くのは STEP 3 の出力フォーマット固定だと考える。
表を埋めさせることで「SKILL.md の全行をカバーしたか」が自己検証可能になり、
脱落が目に見える形で残る。散文で「仕分けてください」と言うだけでは、
数項目を処理した時点で次の工程に進んでしまう可能性が高い。

未確認: 実際に 30B 級のモデルに PROMPT.md を渡して移植させる検証は行っていない。
手元に該当モデルの実行環境が無いため。有効性は設計上の推論にとどまる。

### 次の判断
コミットして push する。ユーザーは現地（OpenShift 環境）での検証に移る。

---

## Step 17: PROMPT.md の実機検証（opencode + Qwen 3.6 35B A3B）

### 目的
Step 16 で作成した `PROMPT.md` を、想定読者である 30B 級モデルに
実際に実行させ、有効性を確認する。

### 背景
Step 16 の時点では「実際に 30B 級のモデルに渡して移植させる検証は行っていない。
手元に該当モデルの実行環境が無いため。有効性は設計上の推論にとどまる」と記録した。
ユーザーから LiteLLM MaaS Gateway（Qwen 3.6 35B A3B）の接続情報が提供され、
検証が可能になった。

### 事前仮説
PROMPT.md の構造（STEP 分割・判断表・出力フォーマット固定）が効けば、
棚卸し表と仕分け表が指定どおりの形で出てくるはず。
懸念はコンテキスト長で、STEP 0 で 5 ファイルを読むと
申告された 32000 トークンを圧迫すると見込んだ。

### 実行内容

**変更・操作:**

1. `opencode` を mise でインストール（1.18.34）。グローバル設定に追加した。
   `python@3.12` と `uv` もグローバルに設定した（検証用ワークスペースが
   リポジトリ外にあり、mise の shim がプロジェクト外で解決できなかったため）。

2. 検証用ワークスペース `~/opencode-trial/` を作成。
   リポジトリ外に置いたのは、生成物や認証情報を誤ってコミットしないため。
   - `PROMPT.md` / `search-mcp/` / `search-demo/` / `Containerfile` をコピー
   - 新しい移植対象 `weather-demo/` を作成（下記）
   - `opencode.json`（ユーザー提供の設定をそのまま使用）
   - トークンは `.vllm-token`（600）に置き、検証終了後に削除した

3. 移植対象として `weather-demo/` を新規作成。
   Open-Meteo の公開 API で複数都市の天気予報を取る依存ゼロのスクリプト
   （`weather_demo.py`、約 120 行）と `SKILL.md`（62 行）。
   見本と同じ「外部 API を読むだけ」型にしつつ、
   `PROMPT.md` が警告している罠を意図的に仕込んだ:
   - 選択肢が固定のオプション `-m`（Literal になるべき）
   - 範囲のある数値 `-d` は 1〜14（ge/le になるべき）
   - 「一度に 5 都市程度まで」というレート制限の注意書き
     （DESCRIPTION だけでなく SCHEMA + GUARD になるべき）
   - `python3 weather_demo.py` という実行方法の記述（DROP されるべき）
   - 部分失敗の仕様（errors フィールドになるべき）

   動作確認:
   ```
   $ python3 weather-demo/weather_demo.py Tokyo Osaka -d 2 -f text
   # Tokyo (日本)
     date=2026-10-07  temperature=25.0  precipitation=0.0  wind=9.3
     date=2026-10-08  temperature=24.0  precipitation=0.0  wind=5.1
   # Osaka (日本)
     date=2026-10-07  temperature=24.2  precipitation=0.0  wind=11.2
     date=2026-10-08  temperature=26.2  precipitation=0.0  wind=7.9
   ```

4. `opencode run --auto` で移植を指示。計 4 回試行した。

**観察した出力:**

| 試行 | 設定 | 結果 |
|---|---|---|
| 1 | context 32000 / output 8000（ユーザー提供のまま） | 参照ファイル読了後に `Cannot connect to API: The socket connection was closed unexpectedly` |
| 2 | context 32000 / output 1500 | STEP 1 の途中で出力が切れ、その後モデルが「This is a fresh session — I don't have prior conversation history」と応答。タスクを見失った |
| 3 | context 60000 / output 1200 | opencode が起動後に停止し、15 分間ログも出力も無し。原因未特定（stdin を閉じていなかった可能性） |
| 4 | context 60000 / output 1200、stdin を `/dev/null` に | STEP 0〜2 は成功。STEP 5 以降のファイル生成で `Invalid input for tool write: JSON parsing failed` が 17 回発生し、完走せず |

試行 4 の成果物 `weather-mcp/docs/porting-notes.md`:
STEP 1 の棚卸し表を指定フォーマットどおりに出力し、内容も正確だった
（`-d` の範囲 1〜14、`-m` の選択肢、出力の JSON 構造、読み取り専用の判定）。
STEP 2 も `#5`（外部 API を読むだけ）を正しく選択した。

**参照した情報源:**
- ゲートウェイ `/v1/models`（モデル ID の確認）
- ゲートウェイ `/v1/chat/completions`（制限の測定。詳細は findings）
- `/tmp/oc-run1.log` 〜 `/tmp/oc-run4.log`
- `~/.local/share/opencode/log/opencode.log`
- 生成物 `~/opencode-trial/weather-mcp/docs/porting-notes.md`

### 期待結果
PROMPT.md の STEP に沿って移植が進み、最低でも仕分け表まで到達する。

### 実際の結果
STEP 0〜2 は意図どおり動いたが、STEP 3 以降には到達しなかった。
原因は PROMPT.md の記述ではなく、**ゲートウェイの 60 秒応答時間上限**だった
（findings に 2 件として記録）。

測定結果の要点:
- 生成に 60 秒以上かかるリクエストは stream の有無を問わず切断される
- スループットは約 33 tok/s。したがって 1 応答の出力上限は実質 1900 トークン
- 実際のコンテキスト上限は 65536。ユーザー提供の設定は 32000 と申告しており、実機の半分
- 入力長は制約にならない（43,180 トークンのプロンプトが 5 秒で成功）

### 解釈
事実: PROMPT.md の「判断を仰ぐのではなく表を引かせる」設計は、
35B 級モデルに対して機能した。棚卸し表の全項目が正確に埋まり、
移植判定も判定表の条件をなぞる形で正しい行を選んでいる。
Step 16 で「設計上の推論にとどまる」としていた部分のうち、
STEP 0〜2 については実証できた。

事実: 出力上限 1200〜1500 トークンでは、ツール呼び出しの JSON が
生成途中で打ち切られ、ファイルを書けない。
これは「出力を抑えれば 60 秒制限を回避できる」という回避策が
別の形で破綻することを示している。

推測: 試行 2 でモデルがタスクを見失ったのは、
context 32000 の申告に対して参照ファイル読了時点で上限に達し、
opencode が履歴を切り詰めた結果、PROMPT.md ごと失われたためと考える。
opencode の内部動作は確認していないため断定しない。

事実: PROMPT.md の STEP 0 は「見本 4 ファイルを全部読め」と指示しているが、
これらは実測で合計 19,658 トークンある
（PROMPT.md 7055 / skill-to-mcp.md 7349 / SKILL.md 714 /
server.py 2191 / test_server.py 2349）。
32k コンテキストでは、この指示自体が作業を不可能にする。

### 次の判断
測定で判明した要件を PROMPT.md に反映する。
具体的には (a) 実行環境の要件と測定方法を冒頭に追加、
(b) 途中経過を会話ではなくファイルに書くよう指示を追加。
検証用トークンは削除済み。ワークスペースはリポジトリ外のため影響なし。

---

## Step 18: thinking を切って Qwen 3.6 の移植能力そのものを測る

### 目的

「PROMPT.md は 35B 級モデルに通用するか」を、実行基盤の制約と切り分けて測る。

### 背景

Step 17 で opencode 経由の移植を 4 回試み、全て失敗した。しかし失敗の形は
いずれも実行基盤由来（接続切断、コンテキスト切り詰め、ツール JSON の truncate）で、
モデルの仕分け判断や生成コードの質を一度も観測できていなかった。
この状態で「qwen3.6 では無理だった」と報告するのは事実に反する。

### 事前仮説

60 秒 / 33 tok/s から計算される約 1900 トークンの出力枠は、
1 ファイルの write には足りるはず。計算が合わないので別の要因がある。

### 実行内容

**変更・操作**

1. opencode を経由せず `/v1/chat/completions` を urllib で直接呼ぶスクリプトを書いた。
2. PROMPT.md + SKILL.md + weather_demo.py を 1 プロンプトに詰め、
   STEP 3 のみを `max_tokens=1600` で依頼した。
3. `content` が `None` で返ったため、message オブジェクト全体を出力した。
4. `reasoning_content` を発見。thinking を止める方法を 5 通り試した。
5. 効いた `chat_template_kwargs: {"enable_thinking": false}` を付けて
   STEP 3 を再実行、続けて STEP 4〜5 を実行した。
6. 背景で走らせていた opencode の run 3 / run 4 を TaskStop で停止した。

**観察した出力**

- 最初の STEP 3: `completion_tokens=1600` を消費、57 秒、`content` は `None`。
  `reasoning_content` にのみ生成があった。
- 「1+1は？」のベンチ: 既定で reasoning 1304 字 / content 0 字 / 400 tok / 15 秒。
  `chat_template_kwargs` で reasoning 0 字 / content 182 字 / 75 tok / 3 秒。
  `reasoning_effort` / `thinking` / `/no_think` はいずれも無効。
- thinking を切った STEP 3: prompt 9026 / completion 990 / 38 秒。17 行の仕分け表。
- thinking を切った STEP 4〜5: completion 2400（上限到達）、200 行の server.py。

**参照した情報源**

- `/home/agent/opencode-trial/weather-demo/.opencode/skill/weather-forecast/SKILL.md`
  （罠を 4 つ仕込んだ検証用 Skill）
- 生成物 `/tmp/step3.md`、`/tmp/step5.py`

### 期待結果

thinking を切れば 60 秒の枠内に可視出力が収まり、
モデルの移植能力を初めて観測できる。

### 実際の結果

収まった。STEP 3 は 38 秒で完走。仕分け表は仕込んだ罠 4 つのうち 3 つを正解し、
特に最難関の「一度に 5 都市程度まで」を SCHEMA + GUARD の両方に落とした。
落としたのは「## 使い方」のコードブロックを DROP として表に載せること 1 件のみ。
STEP 5 のコードは SDK の落とし穴 5 項目をすべて回避していた。
残った欠陥は型注釈 1 箇所と、スキーマ側の `max_length` 欠落、
関数内 import の 3 つで、いずれも軽微。

### 解釈

**事実**: 失敗の支配的な原因は不可視の思考トークンだった。
`reasoning_content` は出力枠と応答時間を消費するが画面には出ない。
60 秒の壁は実在するが、その枠を先に使い切っていたのは thinking である。

**事実**: Step 17 の worklog と Finding に書いた「60 秒の壁が原因」という
説明は不完全だった。訂正を Finding として追記した（既存エントリは変更しない）。

**推測**: opencode の 17 回連続した `JSON parsing failed` も、
同じ機序（思考で枠を使い切り、ツール呼び出しの JSON が途中で切れる）と考える。
ただし opencode が `reasoning_content` をどう扱うかは確認していないため断定しない。

### 次の判断

PROMPT.md の「実行環境の要件」に推論モデルの節を追加し、
STEP 3 に「使い方のコードブロックを落としがち」という注意を追記した。
コミットしてユーザーに報告する。

---

## Step 19: opencode を実クライアントとして search-mcp に接続する

### 目的

「opencode から MCP として使う」という本来の要件が、実際に動くかを確認する。

### 背景

ユーザーから「mcp を opencode で実際に使うというところは検証されているか」と
問われた。確認したところ、検証していなかった。
`search-mcp/examples/opencode.json` はドキュメントを読んで書いただけで、
opencode に読み込ませたことがない。E2E 36 件は生の JSON-RPC を curl で叩くもので、
opencode は登場しない。`docs/clients.md` には検証状況の節が無かった。

### 事前仮説

`examples/opencode.json` の形式は正しいはずだが、未検証なので断定できない。

### 実行内容

**変更・操作**

1. `search-mcp` をローカル起動した。
   `MCP_AUTH_TOKENS=dev-token MCP_DNS_REBINDING_PROTECTION=false MCP_JSON_RESPONSE=true uv run search-mcp`
2. opencode のバイナリが消えていた（`which opencode` が空、
   `/home/agent/.local/share/mise/installs/opencode/` も存在しない）。
   `mise use -g opencode@latest` で再インストールした（1.18.34）。
3. `~/oc-mcp-test/opencode.json` に、LiteLLM プロバイダ定義と
   `mcp.search` の remote 設定（`http://127.0.0.1:8080/mcp`）を書いた。
4. 4 つの確認を順に実行した: ツール列挙 / ツール呼び出し /
   `limit=100` でのスキーマ上限 / 誤ったトークン。
5. `{env:SEARCH_MCP_TOKEN}` 展開の確認。1 回目は python3 の shim が無く
   設定の書き換えが失敗していたため、`mise use -g python@3.12` で直して再実行した。

**観察した出力**

- ツール列挙: opencode が `search` サーバーを認識し、
  Wikipedia / Hacker News / GitHub / Stack Overflow を列挙した。
- ツール呼び出し: `search_search {"query":"asyncio","sources":["github"],"limit":3}`
  が成功。サーバーログに
  `INFO search_mcp.server search query='asyncio' sources=['github'] limit=3 lang=ja`。
- `limit=100`:
  `Error executing tool search: 1 validation error for searchArguments / limit /
  Input should be less than or equal to 20`
  がモデルまで届き、モデルが「`limit` の上限は 20 です」と回答した。
- 誤トークン: サーバーログに 401。opencode はツールを提示せず、
  **代わりに WebFetch で Wikipedia API を直接叩いて回答した**。エラー表示は無し。
- 401 の直後、opencode は `/.well-known/oauth-authorization-server`、
  `/.well-known/openid-configuration`、`POST /register` を順に試し、
  いずれも 401 を受けて諦めていた（サーバーログの 401 は計 12 件）。

**参照した情報源**

- `search-mcp/src/search_mcp/auth.py:1-15`（OAuth discovery を生やさない設計理由）
- `search-mcp/examples/opencode.json`
- サーバーログ `/tmp/mcp-server.log`

### 期待結果

接続できる。スキーマ上限はクライアント経由でも効く。

### 実際の結果

どちらも成立した。加えて、想定していなかった 2 点が見つかった。

1. opencode はツールを `<サーバー名>_<ツール名>` で登録する。
   実際の名前は `search_search` であって `search` ではない。
2. トークンが違うとき、エージェントは**無言で別の手段に逃げる**。

### 解釈

**事実**: `docs/skill-to-mcp.md` の中心的な主張
（description は「お願い」、スキーマは「サーバーが強制するルール」）が、
実クライアント経由で成立することを初めて確認した。
これまでは curl による生の JSON-RPC でしか確認していなかった。

**事実**: 誤トークン時の WebFetch へのフォールバックは、
ユーザーから見ると成功と区別がつかない。ドキュメントに警告が必要な挙動である。

**推測**: OAuth discovery への 401 は `auth.py` の設計どおりの結果で、
クライアントは正しく諦めている。ただし仕様上は 404 のほうが素直かもしれない。
MCP 仕様の該当箇所を確認していないため断定しない。

### 次の判断

`docs/clients.md` に §1.6（検証状況）・§1.7（ツール名の接頭辞）・
§1.8（認証失敗が無言になる件）を追加し、§3 の切り分け表に 2 行足した。
README の検証状況にも 1 段落追加した。Route 経由（TLS + 外部ホスト名）は
依然として未検証なので、その旨を明記した。
