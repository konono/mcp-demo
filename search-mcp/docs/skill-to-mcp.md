# Skill を MCP に落とす — `public-api-search` を例に

このリポジトリには同じ機能が 2 つの形で存在する。

| | Skill 版 | MCP 版 |
|---|---|---|
| 実体 | `search-demo/.opencode/skill/public-api-search/SKILL.md` | `search-mcp/src/search_mcp/server.py` |
| 配布単位 | マークダウン 1 枚 + ローカルのスクリプト | HTTP サーバー（コンテナ） |
| 届き方 | エージェントのコンテキストに**散文として**読み込まれる | `tools/list` の**スキーマと description** として配信される |
| 実行場所 | エージェントと同じマシン | サーバー側 |
| 利用者 | そのリポジトリを開いた opencode | ネットワークが届く全クライアント |

この文書は、Skill のどの部分が MCP のどこに対応するのかと、
**なぜ機械的な移植にならないのか**を残すためのもの。

> **この例の射程について**
> `public-api-search` は「1 つのスクリプトを叩く・読み取り専用・1 回で完結・添付ファイルなし」
> という最も素直な型である。§1〜§5 はこの型の移植記録そのもの。
> 他の型の Skill を移す場合に何が変わるかは §0 と §6〜§8 にまとめた。

---

## 0. 移植判定 — まずこれを通す

チェックリスト（§4）に進む前に、**そもそも MCP 化できるのか / 何が変わるのか**を確認する。
ここを飛ばすと、実装の終盤で「サーバー側にそのファイルが無い」といった
設計をひっくり返す問題に当たる。

```
0-1. ローカルのファイル・状態に依存するか
       いいえ → そのまま移植できる（本例）
       はい   → §6。移植不可か、引数で受け渡す再設計が要る

0-2. 副作用があるか（書き込み・外部への送信・課金）
       いいえ → read_only_hint=True。共有 Bearer で足りる
       はい   → §7。認証の粒度・冪等性・確認フローを設計し直す

0-3. 添付ファイル（references/, assets/, テンプレート）を持つか
       いいえ → Tools だけでよい（本例）
       はい   → §8。Resources / Prompts を検討する

0-4. 1 回の呼び出しで完結するか
       はい   → stateless_http=True（本例）
       いいえ → 進捗通知・セッションが要る。stateless_http の判断が逆転する
                （`.tracecraft/.../decisions.md` の stateless_http の項を参照）
```

4 つとも「左」なら、本文の §1〜§5 がそのまま手順になる。

---

## 1. 根本的な違い: 散文 vs スキーマ

Skill は「エージェントに読ませる文書」である。書いてあることは全部プロンプトであり、
`--limit は 5 が既定` と書けばモデルはそれを読んで `-n 5` を付ける。
守らなくても誰も止めない。**強制力がない代わりに、何でも書ける。**

MCP ツールでモデルに届くのは 3 つだけ:

1. `name` / `title`
2. `description`（自由文）
3. `inputSchema` / `outputSchema`（JSON Schema）

このうち **スキーマには強制力がある**。範囲外の値はサーバーに届く前に弾かれる。
逆に「こういうときに使え」という判断材料は description にしか書けない。

したがって移植作業の本質は、**SKILL.md の散文を「強制できるもの」と「助言にとどまるもの」に仕分ける**ことになる。

```
SKILL.md の散文
   ├─ 制約（値の範囲・選択肢・必須性）        → inputSchema  …… 機械的に強制
   ├─ 判断材料（いつ使うか・どう選ぶか）      → description  …… モデルへの助言
   ├─ サーバー全体の役割                      → instructions …… セッション単位の助言
   ├─ 出力の読み方                            → outputSchema …… パース不要にする
   └─ 副作用の性質                            → annotations  …… クライアントの承認判断材料
```

---

## 2. 対応表（実際の移植結果）

### 2.1 frontmatter `description` → サーバーの `instructions`

SKILL.md:

```yaml
description: Wikipedia / Hacker News / GitHub / Stack Overflow の公開 API を横断検索する。
  ユーザーが用語の意味・技術トピックの一次情報・OSS リポジトリ・エラーの既知の解決策を
  探しているとき、または最新の外部情報の裏取りが必要なときに使う。認証不要。
```

Skill の frontmatter `description` は「この Skill を**読み込むべきか**」の判断に使われる。
MCP には「サーバーを読み込むか」という段階が無い（接続した時点でツールは全部見える）ので、
これは `MCPServer(instructions=...)` に移す。initialize のレスポンスで一度だけ届き、
多くのクライアントはシステムプロンプトに差し込む。

`src/search_mcp/server.py` の `INSTRUCTIONS`:

```
次のときに `search` を使う:
  - 用語の意味や技術トピックの一次情報を知りたい
  ...
回答時は必ず結果の `url` を引用元として提示すること。
```

**判断**: 「url を引用元として提示する」という**回答の作法**は instructions に置いた。
ツール description に書いてもよいが、作法はツール単位ではなくセッション単位の話なので
instructions のほうが適切。ツールが増えたときに重複しない。

### 2.2 「使い方」のオプション表 → `inputSchema`

SKILL.md:

| オプション | 説明 | 既定 |
|---|---|---|
| `--source` / `-s` | `wikipedia` `hackernews` `github` `stackoverflow` `all`。複数指定可 | `all` |
| `--limit` / `-n` | ソースごとの取得件数 | `5` |
| `--lang` | Wikipedia の言語コード | `ja` |
| `--format` / `-f` | `json` または `text` | `json` |

移植にあたって 4 つの判断をした。

**(a) `all` という選択肢を消した。**
CLI では「全部」を表す値が要るが、MCP では
`sources: list[SourceName] | None` の `None`（省略）で表せる。
enum に `all` を混ぜると「`["all", "github"]` は何を意味するのか」という
曖昧さがモデルに伝わってしまう。型で表現できる意味を enum に逃がさない。

```python
sources: Annotated[
    list[SourceName] | None,
    Field(description="検索対象ソース。省略すると全ソースを並列に検索する"),
] = None
```

**(b) `--format` を消した。**
`text` は人間が CLI の出力を読むための形式だった。MCP クライアントは構造化データを
受け取って自前で整形するので、出力形式の選択肢はモデルに見せる意味がない。
**Skill にあったオプションを全部移植する必要はない** — CLI という UI の都合で
存在していたものは落とす。

**(c) `--limit` に上限を付けた。**
SKILL.md では「`-n` を小さくする」と注意書きだったものを、
`Field(ge=1, le=settings.max_limit)` でスキーマに書いた。
Skill 版ではローカル実行なので暴走しても自分のレート制限を食うだけだが、
MCP 版は共有サーバーで、1 クライアントの `limit=1000` が全員に影響する。
**散文の注意書きを、強制できる場所に移すべき典型例。**

上限値は `MCP_MAX_LIMIT` で環境ごとに変えられる。そのため
`server.py` では `from __future__ import annotations` を**使っていない**
（アノテーションが文字列化されると SDK 側の eval がクロージャ変数
`settings` を解決できず `InvalidSignature` になる）。

**(d) 短縮形（`-s` / `-n`）を消した。** タイプ数を減らす CLI の都合で、モデルには不要。

### 2.3 「使い分けの指針」 → ツール `description` の中核

SKILL.md の本文:

```
- 用語・概念の定義 → -s wikipedia（日本語なら --lang ja、専門的な内容は --lang en も試す）
- 技術トピックの議論・評判 → -s hackernews
- 実装やライブラリを探す → -s github
- エラーメッセージ・実装上の詰まり → -s stackoverflow（キーワードはエラー文の固有部分を削って短くする）
- 当たりが付かないとき → ソース指定なし（all）で広く拾ってから絞る
```

これは **MCP 版でも最も重要な部分**。ツールを「呼べるようにする」だけなら
`search(query)` で足りるが、それではモデルはいつも全ソースを引いてしまう。

散文を `SOURCE_GUIDE` という dict に構造化し、2 か所から参照している:

```python
SOURCE_GUIDE = {
    "github": {
        "api": "GitHub Repository Search API (未認証)",
        "use_when": "実装やライブラリを探すとき。スター数順に並ぶ",
        "caveats": "未認証のレート制限が厳しい（検索は約 10 req/min）。limit は小さく、連続実行は避ける",
    },
    ...
}
```

1. `search` の description に `use_when` を展開する（呼ぶ前に読まれる）
2. `list_search_sources` ツールが全文を返す（モデルが明示的に調べられる）

**なぜ 2 経路にしたか**: description を長くしすぎると、接続しているツール全部の
description がコンテキストを食う。要点だけ description に置き、
詳細（API 名・制約）は「聞かれたら返す」ツールに逃がした。
Skill の「必要なときに読み込まれる」性質を、ツール分割で再現している。

### 2.4 「注意」 → description の制約節 ＋ サーバー側のガード

SKILL.md:

```
- GitHub と Stack Exchange は未認証のためレート制限が厳しい（GitHub 検索は約 10 req/min）。
- 日本語キーワードはそのまま渡してよい（内部で URL エンコードする）。
- ネットワーク不通時は errors にのみ記録されるため、count が 0 のときは errors を必ず読むこと。
```

3 つとも扱いが違う。

| 注意書き | 移した先 | 理由 |
|---|---|---|
| レート制限 | description ＋ `MCP_MAX_LIMIT` でのクランプ | 助言だけでは守られない。サーバー側でも止める |
| 日本語をそのまま渡してよい | `query` の `Field(description=...)` | その引数の話なので引数の説明に書く |
| `count==0` なら `errors` を読め | `instructions` ＋ `errors` フィールドの description | 結果の読み方はセッション共通の作法 |

### 2.5 「出力」の JSON 例 → `outputSchema`（Pydantic モデル）

SKILL.md では JSON の実例を 1 つ貼って「こういう形で返る」と示していた。
MCP では Pydantic モデルを返り値型にするだけで JSON Schema が自動生成され、
`structuredContent` として型付きで届く。**モデルが例から形を推測する必要がなくなる。**

```python
class SearchHit(BaseModel):
    source: SourceName = Field(description="この結果の出典ソース")
    url: str = Field(description="引用元として提示すべき URL")
    ...
```

フィールドの `description` に「引用元として提示すべき」と書けるのが効く。
Skill では本文に散っていた作法を、それが現れる場所に貼り付けられる。

### 2.6 Skill に無かったもの: `annotations`

```python
annotations=ToolAnnotations(
    read_only_hint=True, destructive_hint=False,
    idempotent_hint=True, open_world_hint=True,
)
```

Skill には対応物が無い。クライアント（とユーザー）が
「このツールは自動承認してよいか」を判断するためのメタデータ。
`open_world_hint=True` は「外部ネットワークを触る」という申告で、
オフライン前提の環境や、外部送信を監査したい環境で意味を持つ。

HTTP サーバーとして不特定のクライアントに公開する以上、
**副作用の性質を機械可読で申告するのは実質必須**だと考えてよい。

### 2.7 失敗の返し方 — `errors` フィールドか `is_error` か

Skill には「失敗の返し方」という概念が無い。スクリプトが非ゼロ終了すれば、
エージェントは stderr を読んで判断する。MCP には 2 つの経路がある。

| | 使う場面 | モデルから見た意味 |
|---|---|---|
| structured output の中のフィールド（`errors: [...]`） | **部分的な失敗**。結果は返っている | 「ツールは動いた。この範囲は欠けている」 |
| `is_error: true`（例外送出） | **呼び出し自体の失敗**。返す結果が無い | 「ツールが失敗した。引数を直すか諦める」 |

本実装は 4 ソースのうち 1 つが落ちても残り 3 つの結果を返したいので、
`SearchResponse.errors` に入れて `is_error` は使っていない。

```python
class SourceError(BaseModel):
    source: SourceName
    error: str = Field(description="このソースの取得に失敗した理由")

class SearchResponse(BaseModel):
    count: int = Field(description="results の件数。0 のときは errors を必ず読むこと")
    results: list[SearchHit]
    errors: list[SourceError] = Field(description="取得に失敗したソース。空なら全ソース成功")
```

**原則**: モデルに回復させたい（部分結果を使わせたい・別のソースを試させたい）失敗は
structured output に入れる。`is_error` にすると情報が文字列に潰れ、
クライアントによっては結果そのものが捨てられる。

逆に、引数が不正・認証切れ・外部 API が全滅、のように**返す結果が存在しない**ときは
素直に例外を投げて `is_error` にする。「空の結果 + errors」で返すと
モデルが「ヒット 0 件だった」と誤読する。

SKILL.md の「`count` が 0 のときは `errors` を必ず読むこと」という注意書きは、
この設計を取ったがゆえに必要になったもの。**設計判断が、書くべき description を決める**。

---

## 3. 落としたもの・足したもの

### 落とした

- `--format text` — CLI の人間向け UI
- `-s all` — 型で表現できる
- 短縮オプション — モデルには不要
- 「リポジトリルートで実行する」「`python3` が無ければ `mise x --`」
  — 実行環境の話。サーバー側に閉じたので消えた。**これが MCP 化の最大の利点**で、
  クライアント側はもう Python も mise も持たなくてよい

### 足した

- `list_search_sources` ツール（description の肥大化を避けるため）
- `limit` の上限（共有サーバーなので）
- `annotations`（承認判断のため）
- `/healthz` `/readyz`（HTTP ワークロードとして必要）
- Bearer 認証（ネットワーク越しになったので）

---

## 4. 移植するときのチェックリスト

Skill を MCP に移す作業を他のものでもやるなら、この順で考えるとよい。

1. **frontmatter の description はどこへ行くか** — 多くは `instructions`。
   ただしツールが 1 つしかないなら、そのツールの description に寄せたほうが届きやすい
2. **オプション表のうち、CLI の都合で存在するものはどれか** — 出力形式、短縮形、
   「全部」を表す特殊値。これらは落とす
3. **散文の注意書きのうち、強制できるものはどれか** — 値の範囲、選択肢、必須性。
   スキーマに移す。特に共有サーバーになる場合、
   「クライアントが守ってくれる前提」は成り立たない
4. **「いつ使うか」は description に残す** — ここを削ると、ツールは呼べるが
   呼ばれなくなる（または常に全部呼ばれる）
5. **description が長くなりすぎたら、ツールを分けて逃がす** — 常時コンテキストを
   食う description と、必要なときだけ呼ばれるツールのトレードオフ。
   目安は後述（§4.1）
6. **出力例はスキーマにする** — Pydantic モデルを返り値型にするだけでよい
7. **副作用を annotations で申告する** — ローカル Skill では暗黙でよかったが、
   リモートサーバーでは明示する
8. **実行環境の説明は消える** — これが移植の利得。消し忘れると、
   クライアント側で不要な前提を課すことになる
9. **失敗の返し方を決める** — 部分失敗は structured output、
   呼び出し自体の失敗は `is_error`（§2.7）
10. **移植できたかを検証する** — 「サーバーが起動する」ではなく
    「ガイダンスがモデルに届いている」を検証する（§4.2）

### 4.1 description の長さの目安

厳密な基準は無いが、運用上の判断材料として:

- **〜400 文字程度**: 問題にならない。1 ツールならここに収める
- **400〜1000 文字**: ツールが 2〜3 個なら許容。それ以上あるなら分割を検討
- **1000 文字超**: ほぼ確実に分割すべき。他の MCP サーバーと併用されると、
  ツール一覧だけでコンテキストを食い、肝心のツール選択精度が落ちる

分割の切り口は「**呼ぶ前に必ず要るか**」。
本実装では「どのソースを選ぶか」（`use_when`）は呼ぶ前に必要なので description、
「そのソースの API 名と制約」（`api` / `caveats`）は必要なときだけなので
`list_search_sources` に逃がした。

判断に迷ったら、**要点を description に残し、詳細を逃がす**。
逃がしたツールが呼ばれなければ、それは要らなかったということ。

### 4.2 移植できたことの検証

「サーバーが起動する」「ツールが呼べる」は移植の検証になっていない。
**SKILL.md にあったガイダンスがモデルに届いているか**を検証する。

本実装の `tests/test_server.py` では、MCP プロトコル越しに次を確認している。

```python
# 回答の作法が instructions に載っているか
assert "引用元" in (session.instructions or "")

# 使い分けの指針が description に載っているか
assert "stackoverflow" in (search_tool.description or "")

# 注意書きが description に載っているか
assert "レート制限" in (search_tool.description or "")

# 散文だった制約が、強制力のあるスキーマになっているか
limit_schema = search_tool.input_schema["properties"]["limit"]
assert any(v.get("maximum") == 7 for v in limit_schema["anyOf"])   # MCP_MAX_LIMIT=7

# 副作用の申告
assert search_tool.annotations.read_only_hint is True
```

最後の 2 つが重要で、**「description に書いた」で終わらせず
「スキーマとして強制されている」を確認している**。
文字列検査は粗いが、ガイダンスを丸ごと消す事故は防げる。

加えて、サーバー起動後に実クライアントから 1 回呼び、
**initialize の `instructions` と `tools/list` の全文を目で読む**。
`examples/smoke_client.py` はこのために両方を出力している。
モデルに渡るものを人間が一度も読まずに公開しない。

---

## 5. 両方を維持する場合

このリポジトリは Skill 版（`search-demo/`）を残したまま MCP 版を足している。
検索ロジックは `search_demo.run_search` ひとつで、MCP 版は
`[tool.uv.sources] search-demo = { path = "../search-demo" }` で依存として取り込む。
**ロジックは二重管理しないが、ガイダンスの文面は二重管理になる。**

SKILL.md の「使い分けの指針」を直したら `SOURCE_GUIDE` も直す必要がある。
これを自動化することもできる（SKILL.md をパースして description を生成する）が、
2.2〜2.4 で見たとおり対応は 1 対 1 ではないので、この規模では手動同期にしている。
ずれを検知するため、`tests/test_server.py` で
「指針と制約が description に載っていること」を文字列で検査している。

```python
assert "stackoverflow" in (search_tool.description or "")
assert "レート制限" in (search_tool.description or "")
```

これは「description に何が書いてあるか」のテストであって、
「SKILL.md と一致しているか」のテストではない。
片方だけ更新する事故は防げないので、**Skill 版を廃止できるなら廃止したほうがよい**。

---

# 他の型の Skill を移す場合

ここから先は `public-api-search` では現れなかったが、
他の Skill を移植するときに必ず当たる論点。§0 の判定で「右」に倒れたときに読む。

---

## 6. ローカルのファイル・状態に依存する Skill（§0-1）

**これが移植の可否を分ける最大の分岐。**

本例では「実行環境の説明が消えること」を移植の利得として挙げた（§3）。
これは**外部 API を叩くだけで、ローカルに触れていなかったから**成立した話で、
一般には逆向きに働く。

```
Skill:  エージェントと同じマシンで動く → ユーザーのファイルが見える
MCP:    サーバー側で動く               → ユーザーのファイルは存在しない
```

### 判定

| Skill がやること | MCP 化 |
|---|---|
| 外部 API / 計算 / 変換（入力が引数で閉じる） | **そのまま移植できる**（本例） |
| ユーザーのファイルを**読む** | 内容を引数で渡す形に再設計。サイズ上限に注意 |
| ユーザーのファイルを**書く** | 原則 MCP 化しない。結果を返してクライアントに書かせる |
| リポジトリ全体を走査する | MCP 化しない。Skill のままが正しい |
| ユーザー環境のコマンド（`git`, `kubectl`）を叩く | MCP 化しない。認可の境界が壊れる |

### 「MCP 化しない」が正解のことがある

Skill と MCP は**競合する選択肢ではない**。

- **Skill が向くもの**: ユーザーの環境・ファイル・認可の文脈が要る作業
- **MCP が向くもの**: 環境に依存せず、複数のクライアントで共有したい能力

本例が MCP 向きだったのは、「Python も mise も要らなくなる」という
クライアント側の前提削減が効いたからであって、すべての Skill に当てはまるわけではない。
**移植の前に「これは共有すべき能力か、ユーザー環境の作業か」を問う。**

### 折衷: 薄い Skill + MCP

ローカル要素が一部だけなら、分割できる。

```
Skill（ローカルに残す）: ファイルを読む・結果を書き戻す・git を叩く
MCP（サーバーに出す）  : 重い処理・外部 API・共有したいロジック
```

この場合、SKILL.md は「MCP ツール `foo` を呼んで、結果をこのファイルに書く」という
**手順書**に痩せる。ガイダンスのうち「いつ使うか」は MCP の description に移り、
「どう組み合わせるか」が Skill に残る。

### ファイル内容を引数で渡す場合の注意

- **サイズ**: SDK の `max_request_body_size` は既定 4 MiB。
  大きなファイルを想定するなら明示的に上げるか、分割を前提にする
- **ログ**: 引数はサーバーのログに載りうる。
  ユーザーのファイル内容が共有サーバーのログに残ることを許容できるか確認する
- **秘匿情報**: 引数で渡される以上、サーバー運用者から見える。
  認証情報を含みうるファイルは渡させない設計にする

---

## 7. 副作用のある Skill（§0-2）

本例は `read_only_hint=True` だった。書き込み系ではほぼ全部の判断が変わる。

### 7.1 認証の粒度が足りなくなる

共有 Bearer トークンは「呼んでよいか」しか判定できない。**誰が呼んだかは分からない。**

読み取り専用なら「ログは送信元 IP のみ」で済ませられる（`docs/security.md` の判断）。
破壊的操作では済まない。何かを消したときに**誰が消したかを特定できない**のは、
運用上ほぼ受け入れられない。

| ツールの性質 | 最低限必要な認証 |
|---|---|
| 読み取り専用 | 共有 Bearer（本実装） |
| 冪等な書き込み | クライアントごとに別トークン ＋ 呼び出しログ |
| 破壊的・不可逆 | 呼び出し元を識別できる認証（OAuth 2.1 等）＋ 監査ログ |

移行手順は `docs/security.md` に記載した。
**副作用のある Skill を移植するなら、共有 Bearer から始めない。**

### 7.2 annotations を正しく申告する

```python
annotations=ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,    # 既存の状態を壊しうる
    idempotent_hint=False,    # 同じ引数で 2 回呼ぶと結果が変わる
    open_world_hint=True,
)
```

クライアントはこれを見て自動承認するかを決める。
**誤った申告（破壊的なのに `read_only_hint=True`）は、
ユーザーの承認なしに実行される原因になる。** 迷ったら安全側に倒す。

### 7.3 冪等性を設計する

HTTP 越しの呼び出しはリトライされる。ネットワークエラーでクライアントが再送したとき、
2 回実行されて困るなら冪等キーを引数に入れる。

```python
request_id: Annotated[str | None, Field(
    description="再送時に同じ値を渡すと、重複実行を防ぐ"
)] = None
```

Skill はローカル同期実行だったので、この問題が存在しなかった。
**ネットワーク越しになった時点で新しく発生する要件**であり、SKILL.md には対応物が無い。

### 7.4 「確認してから実行」が効かなくなる

Skill ではエージェントが「実行してよいですか」とユーザーに聞き、
承認を得てからスクリプトを叩ける。MCP サーバーはその承認を見ていない。

承認フローを MCP 側で表現したいなら、ツールを 2 段に分ける。

```
plan_xxx   （read_only）→ 何が起きるかを返す
apply_xxx  （destructive）→ plan の ID を受け取って実行
```

`terraform plan` / `apply` と同じ形。
description に「必ず `plan_xxx` を先に呼ぶこと」と書いても強制力は無いので、
`apply_xxx` 側で**存在しない / 期限切れの plan ID を拒否する**（§1 の「散文を強制力のある場所へ」）。

---

## 8. 添付ファイルを持つ Skill（§0-3）

Skill は `SKILL.md` 単体とは限らず、`references/`・`assets/`・テンプレート・
補助スクリプトを同梱する形が普通にある。本例は単体だったので Tools だけで足りたが、
MCP には他に 2 つのプリミティブがある。

| MCP プリミティブ | 制御するのは | Skill 側の対応物 |
|---|---|---|
| **Tools** | モデル（モデルが呼ぶ） | 実行するスクリプト |
| **Resources** | アプリ（クライアントが読み込む） | `references/` の参照資料・テンプレート |
| **Prompts** | ユーザー（ユーザーが選ぶ） | 「こう使え」という定型の呼び出し手順 |

### 8.1 Resources — 参照資料・テンプレート

「必要になったら読む大きめの資料」は Resources にする。
description に貼ると常時コンテキストを食い、Tools にすると
「資料を読む」という不自然なツールが増える。

```python
@mcp.resource("guide://sources/{name}", title="ソース別の詳細ガイド")
async def source_guide(name: str) -> str:
    return SOURCE_GUIDE[name]["caveats"]
```

**判断基準**:

| | 落とし先 |
|---|---|
| 呼ぶ前に必ず要る要点 | ツール description |
| モデルが自分で判断して取りに行く詳細 | **Tool**（本実装の `list_search_sources`） |
| クライアント/ユーザーが選んで文脈に入れる資料 | **Resource** |

本実装が `list_search_sources` を Resource ではなく Tool にしたのは、
**Resources はクライアント実装によって扱いが大きく違う**ため。
opencode・Claude Agent SDK・LangChain で挙動が揃わない。
Tool なら必ずモデルから見える。**複数クライアントから使わせるなら Tool のほうが堅い。**

### 8.2 Prompts — 定型の使い方

SKILL.md の「典型的な使い方」節に相当する。
ユーザーが明示的に選んで起動する（スラッシュコマンド等に現れる）。

```python
@mcp.prompt(title="エラーの解決策を調べる")
def investigate_error(message: str) -> str:
    return f"次のエラーの既知の解決策を調べて。固有部分を削った短いキーワードで "
           f"stackoverflow と github を検索すること。\n\n{message}"
```

Resources 同様クライアント依存が強い。**無くても機能が成立する作りにしておく。**

### 8.3 補助スクリプトの扱い

Skill が同梱していた補助スクリプトは、MCP 化すると 2 つに分かれる。

- **サーバー側のロジックになるもの** → パッケージに取り込む（本例の `search_demo`）
- **ユーザー環境で動く必要があるもの** → §6。MCP に移さず Skill に残す

---

## 9. まとめ: どこまでが本例の射程か

| 論点 | 本例で扱った | 他の Skill で要注意 |
|---|---|---|
| 散文 → スキーマの仕分け | ✅ §1〜§2 | 全 Skill 共通 |
| CLI 都合のオプションを落とす | ✅ §2.2 | 全 Skill 共通 |
| 使い分けの指針 → description | ✅ §2.3 | 全 Skill 共通 |
| 出力例 → outputSchema | ✅ §2.5 | 全 Skill 共通 |
| annotations | ✅ §2.6（read_only のみ） | 破壊的なら §7.2 |
| 失敗の返し方 | ✅ §2.7 | 全 Skill 共通 |
| ローカルファイル依存 | ❌ 該当なし | **§6。移植可否を分ける** |
| 副作用・認証の粒度 | ❌ 該当なし | **§7。共有 Bearer では不足** |
| Resources / Prompts | ❌ 該当なし | §8 |
| 長時間処理・進捗通知 | ❌ 該当なし | `stateless_http` の判断が逆転する |

**最初に覚えるべきは §1 の一行に尽きる。**
Skill の散文はすべて助言だが、MCP では「助言（description）」と
「契約（schema）」に分かれる。移植とは、各記述がどちらなのかを
一つずつ決めていく作業である。
