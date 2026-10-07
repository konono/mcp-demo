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
   配備前に `oc apply --dry-run=server -k search-mcp/deploy/openshift/`。
   `podman kube play` は独自パーサなのでフィールド名の typo を検出できない
2. **Route / NetworkPolicy / HPA / PDB**。podman に概念が無いため未検証。
   `replicas: 2` も無視されるので、複数 replica での stateless 動作も未確認
3. **ガイダンス文面の二重管理**。SKILL.md の「使い分けの指針」と `SOURCE_GUIDE` は
   1 対 1 対応ではないため自動同期していない。テストの文字列検査で一部は検知できるが、
   内容のずれは検知できない
4. **認証の粒度**。共有 Bearer では誰が呼んだか分からない。
   監査が要求されたら OAuth 2.1 に移行する（手順は `docs/security.md`）
5. **レート制限そのものは未実装**。`limit` の上限は効くが、呼び出し頻度の制限は無い

---

## モックの置き場所が、そのままテストの死角になる

MCP 側のテストは `search_demo.run_search` を monkeypatch で差し替えている。
MCP レイヤだけを見るための正しい設計だが、副作用として
**検索ロジックが壊れてもテストは緑のまま**になっていた。
しかも `search-demo` には単体テストが 1 件も無かったので、
リポジトリ全体として誰もそこを見ていなかった。

E2E を書いた時点でこれが見えた。E2E は実 API を 1 回叩くだけで、
レスポンス形のバリエーション（欠けたフィールド、null の `description`、
HTML エスケープ）は通らない。「E2E があるから本体も見ている」は錯覚だった。

**教訓**: モックを置いた境界の向こう側を、誰がテストしているか明示的に確認する。
カバレッジの数字は依存パッケージを計測対象から外すので、この穴を映さない。
今回も `--cov=search_mcp` だけ見ていた間は 93% と出ていて、
`search_demo.py` のカバレッジは 0% だった。

同じ理由で `Settings.from_env()` も抜けていた。
テストは `Settings(...)` を直接組み立てていて、環境変数の経路を通っていない。
**本番だけが通る経路はテストの死角になる**という典型例。

---

## 次に同種の作業をするなら

1. SDK の現物確認から始める（変えない）
2. テストは最初から実サーバーで書く（ASGITransport を試さない）
3. モックした境界ごとに「向こう側は誰が見るか」を決めてから進む。
   カバレッジは計測対象を広げないと死角を映さない
4. コンテナは「ビルド成功 → 即 `podman run`」をワンセットにする
5. マニフェストは、クラスタがあるなら**書きながら** `--dry-run=server` を回す。
   最後にまとめて検証しようとすると、今回のように検証手段が無くて詰む
6. Skill → MCP の移植では、各記述を「助言 / 契約 / 捨てる」に仕分けてから書き始める

## 見えないトークンは、無いトークンではない

PROMPT.md を 35B モデルに渡す実機検証で、4 回連続して失敗した。
失敗の形は毎回違った。接続が切れる。モデルがタスクを見失う。
ツール呼び出しの JSON が途中で壊れる。
共通していたのは「出力が足りない」ことだった。

ゲートウェイの応答時間上限を二分探索で 60 秒と測り、
生成速度を 33 tok/s と測り、掛け算して「1 応答あたり約 1900 トークン」
という数字を出した。この数字自体は正しかった。
正しくなかったのは、その 1900 トークンが何に使われているかの想定である。

このモデルは推論モデルで、毎ターン 1300 字前後の思考を生成していた。
思考は `reasoning_content` という別フィールドに入るため、
レスポンスを `content` だけ見ていると**何も生成されなかったように見える**。
しかし `max_tokens` と応答時間は本文と共有している。
1900 トークンの枠はあったが、本文が出る前に尽きていた。

気づいたきっかけは `TypeError: write() argument must be str, not None` という、
調査とは何の関係もないスクリプトの落ち方だった。
`completion_tokens` が 1600 に達しているのに `content` が `None` という
矛盾が、オブジェクト全体を出力させた。

教訓は、測った数字が正しくても、その数字の**内訳**を確認していなければ
解釈を誤るということ。「60 秒で切れる」は事実、
「だから長い生成ができない」も事実、
しかし「だからモデルには荷が重い」は推論であり、間違っていた。

## 失敗の原因を、測っていない対象に帰属させない

4 回失敗した時点で「このモデルには無理」と書くことはできた。
実際そう書きたくなる状況だった。試行回数は十分に見えたし、
失敗の種類も多様だった。

だが振り返ると、4 回の失敗で観測していたのは opencode の挙動と
ゲートウェイの挙動だけで、**モデルの判断を一度も見ていなかった**。
仕分け表を 1 枚も読んでいない状態で、仕分け能力を評価しようとしていた。

opencode を外して API を直接叩き、thinking を切って STEP 3 を投げたら、
38 秒で 17 行の仕分け表が返ってきた。
そこには「一度に 5 都市程度までにすること」という散文の注意書きが
`SCHEMA + GUARD` に分類され、備考に
「ネットワーク越しの誰でも呼べるため」と理由まで書かれていた。
これは PROMPT.md が「ここを特に注意」として一節を割いた、最難関の判断である。

能力は最初からあった。測る前に結論を出していたら、
PROMPT.md に不要な簡略化を加えていたはずで、それは文書を悪くしていた。

## 罠を仕込んだ検証用 Skill が効いた

検証のために作った weather-forecast の SKILL.md には、
PROMPT.md が「間違えやすい」と名指ししている項目を 4 つ仕込んでおいた。
固定選択肢のオプション、範囲のある数値、「〜しすぎないこと」という散文の制約、
`python3 xxx.py` という実行方法の記述。

これがあったおかげで、生成物の良し悪しを印象ではなく採点で言えた。
3 つ正解、1 つ欠落。欠落した 1 つ（使い方のコードブロックを
DROP として表に載せる）は、そのまま PROMPT.md への追記になった。

指示書を書いたら、その指示書が警告している失敗を
わざと起こせる入力を作って試す。これは次も使える。
