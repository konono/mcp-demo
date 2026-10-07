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
