# Retrospective

> 作業タイトル: search-demo を MCP Streamable HTTP サーバー化し OpenShift に配備可能にする
> 期間: 2026-10-06（単一セッション）

---

## この作業は何だったのか

依存ゼロの Python CLI（`search-demo`）と、それを opencode から使うための Skill（`SKILL.md`）を、
MCP Streamable HTTP サーバーとして作り直し、コンテナ化して OpenShift に載せ、
VM 上の opencode とクラスタ内の agent framework Pod の双方から使えるようにした。

ユーザーの意図はもう一段あった。これは**リファレンス実装**であり、
「Skill に書かれた散文を、MCP のコードのどこにどう落とすのか」という知識を残すこと自体が成果物だった。
そのため `docs/skill-to-mcp.md` を中心に据えた。

---

## うまくいったこと

### 実装前に SDK の現物を確認した

最初にやったのが `uv pip install mcp` して `inspect.signature` を叩くことだった。
結果、`FastMCP` は存在せず `MCPServer` に改名されていた（mcp 2.3.0）。
記憶のまま書いていたら、import すら通らないコードを一式書いてから全部直すことになっていた。
`streamable_http_app()` の引数を先に見ていたので、`stateless_http` と `transport_security` が
SDK 標準機能だと分かり、自前実装を避けられた。

**教訓**: メジャーバージョンの変わり目にあるライブラリは、記憶ではなく実物を確認してから設計する。
確認コスト（1 分）に対して、回避できる手戻りが大きすぎる。

### エラーメッセージを読んで原因を特定する経路が速かった

5 件の失敗のうち 3 件は、エラーメッセージ自体が答えを含んでいた。

- `ModuleNotFoundError: ... FastMCP was renamed to MCPServer ...` → そのとおり
- `AttributeError: ... Did you mean: 'structured_content'?` → そのとおり
- `OSError: Readme file does not exist` → そのとおり

残る 2 件は切り分けが要ったが、どちらも「通るものと通らないものの差」から絞れた。

- `InvalidSignature` → `e.__cause__` を出したら `NameError("name 'settings' is not defined")`。
  型の書き方を疑っていたが、実際はスコープの問題だった
- `Task group is not initialized` → `/healthz` は通り `/mcp` だけ落ちる。
  アプリは組み上がっていてセッションマネージャだけ未起動 → lifespan の問題

**教訓**: 「通るもの」と「通らないもの」の境界を見つけるのが最短経路。
`__cause__` を出すのを面倒がらない。

### ツールを 2 つに分けた判断

SKILL.md のガイダンスを全部ツール description に詰め込むと肥大する。
要点（`use_when`）だけ description に置き、詳細（`api`, `caveats`）は
`list_search_sources` に逃がした。Skill の「必要なときに読み込まれる」性質を
ツール分割で再現した形になった。

`SOURCE_GUIDE` dict を単一ソースにして 2 か所から参照したので、文面の重複も避けられた。

---

## うまくいかなかったこと・反省

### テストのアプローチを最初に間違えた

`httpx.ASGITransport` で in-process に叩くのは、普通の Starlette アプリなら妥当な選択だった。
だが `MCPServer` のアプリは lifespan でセッションマネージャを起動する。
「lifespan に依存するかどうか」を先に確認していれば、最初から uvicorn で書けた。

結果的には実 uvicorn にしたことで、認証ミドルウェアの 401 と `WWW-Authenticate` ヘッダまで
HTTP レベルで検証できるようになり、品質は上がった。とはいえ回り道ではあった。

**教訓**: ASGI アプリをテストする前に、lifespan で何かを起動していないか確認する。

### ビルドが通ったことを成功と見なしかけた

`podman build` が成功したイメージが `ModuleNotFoundError` で起動しなかった。
`uv sync` の既定が editable install で、builder ステージの `/build/search-mcp` を指す
`.pth` が runtime ステージには存在しなかった。

このクラスの失敗は**ビルド時に一切警告が出ない**のが厄介で、
`podman run` するまで分からない。

**教訓**: マルチステージで venv だけコピーするなら `--no-editable`。
そしてビルド成功で終わらせず、必ず一度起動する。

### API スキーマ検証をやり切れなかった（残存リスク）

`kubectl apply --dry-run=client` はクラスタ接続を要求するため実行できず、
`kubeconform` も OpenShift CRD スキーマの取得が必要で割に合わなかった。
検証できたのは `kubectl kustomize` のレンダリング（12 リソース、警告なし）まで。

**フィールド名の typo や apiVersion の誤りは検出できていない。**
これは隠さず明示し、配備前に `oc apply --dry-run=server -k ...` を実行することを推奨として渡した。

**教訓**: 検証できなかったことを「たぶん大丈夫」で埋めない。
未検証の範囲を具体的に書いて、検証手段とセットで渡す。

---

## 技術的に持ち帰る知見

### MCP SDK 2.x

- 入口は `from mcp.server.mcpserver import MCPServer`（`FastMCP` は廃止）
- SDK は `httpx` ではなく **`httpx2`** を使う
- Python 側の属性名はスネークケース（`structured_content`, `is_error`, `input_schema`）。
  ワイヤフォーマットはキャメルケースのまま、pydantic の alias で変換される
- `streamable_http_app()` が返すアプリは lifespan 必須
- `stateless_http` と `TransportSecuritySettings` は SDK 標準。自前で作らない

### PEP 563 とツール定義の相性

ツール関数のアノテーションに設定値（クロージャ変数）を埋め込むなら、
そのモジュールで `from __future__ import annotations` を使ってはいけない。
SDK は `inspect.signature(func, eval_str=True)` でモジュール globals のみを使って評価する。

逆に言えば、「設定で可変にする」か「PEP 563 を使う」かの二択。
今回は環境変数での可変性を優先した。

### コンテナ

- `uv sync --no-editable`（マルチステージ）
- パス依存があると build context はリポジトリルートになる
- `HEALTHCHECK` は OCI フォーマットでは無視される（podman の既定）
- OpenShift 向けには `runAsUser` を書かず `runAsNonRoot: true` のみ。
  任意 UID（`--user 1000670000:0`）で起動することを事前に確認しておく

### kustomize

`commonLabels` は非推奨。`labels` に移すときは `includeSelectors: false` を明示し、
`version` のような可変ラベルを Deployment の immutable なセレクタに入れない。

---

## 設計として残したいこと: Skill と MCP の違い

この作業の中心にあった気づき。

**SKILL.md の記述は散文で、強制力がない。MCP のスキーマには強制力がある。**

SKILL.md の「GitHub 検索は約 10 req/min。`-n` を小さくする」は、
ローカル実行の Skill では十分だった。暴走しても自分のレート制限を食うだけだから。

MCP サーバーは**共有される**。1 クライアントの `limit=1000` が全クライアントに影響する。
「クライアントが注意書きを守ってくれる前提」はネットワーク越しでは成り立たない。
だから `Field(ge=1, le=max_limit)` でスキーマに載せ、サーバー側でもクランプした。

この「散文 → スキーマ」の変換が、Skill を MCP に移植するときの本質だと思う。
description はモデルへの助言、スキーマは契約。
移植するときは各記述について「これは助言か契約か」を判断する必要がある。

同じ構造の判断が他にもあった:

| SKILL.md の記述 | 性質 | MCP での落とし先 |
|---|---|---|
| 使い分けの指針 | 助言 | ツール description |
| レート制限の注意 | **契約にすべき** | inputSchema + サーバー側クランプ |
| `--format` の選択肢 | CLI の UI 都合 | 落とす |
| `-s all` | 型で表現できる | `sources: ... \| None` |
| 出力の JSON 例 | 契約 | Pydantic → outputSchema |
| （記述なし） | — | `ToolAnnotations` で副作用を申告 |

---

## 未解決のまま残したこと

1. **OpenShift マニフェストの API スキーマ検証**（最優先）。
   配備前に `oc apply --dry-run=server -k search-mcp/deploy/openshift/`
2. **`readOnlyRootFilesystem: true` の実地検証**。podman の `--read-only` では試していない
3. **ガイダンス文面の二重管理**。SKILL.md の「使い分けの指針」と `SOURCE_GUIDE` は
   1 対 1 対応ではないため自動同期していない。テストの文字列検査で一部は検知できるが、
   内容のずれは検知できない
4. **認証の粒度**。共有 Bearer では誰が呼んだか分からない。
   監査が要求されたら OAuth 2.1 に移行する（手順は `docs/security.md`）
5. **レート制限そのものは未実装**。`limit` の上限は効くが、呼び出し頻度の制限は無い

---

## 次に同種の作業をするなら

1. SDK の現物確認から始める（変えない）
2. テストは最初から実サーバーで書く（ASGITransport を試さない）
3. コンテナは「ビルド成功 → 即 `podman run`」をワンセットにする
4. マニフェストは、クラスタがあるなら**書きながら** `--dry-run=server` を回す。
   最後にまとめて検証しようとすると、今回のように検証手段が無くて詰む
5. Skill → MCP の移植では、各記述を「助言 / 契約 / 捨てる」に仕分けてから書き始める
