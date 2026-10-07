# PROMPT.md — Skill を MCP サーバーに移植する作業指示書

このファイルは **AI エージェントにそのまま渡すためのプロンプト**です。
人間が読むための解説ではありません。

使い方（人間向け・ここだけ）:

1. このリポジトリをエージェントの作業ディレクトリに置く
2. 移植したい Skill のディレクトリを用意する
3. エージェントに次のように指示する

   > `PROMPT.md` を読んで、その指示に従って `<Skill のパス>` を MCP サーバーに移植してください。

### 実行環境の要件（人間向け・ここだけ）

小型モデルやゲートウェイ経由で動かす場合、**モデルの賢さより先に
実行基盤の制約で止まります。** 事前に次を確認してください。

| 項目 | 必要量 | 理由 |
|---|---|---|
| コンテキスト長 | **48k 以上**（推奨 64k） | STEP 0 で読む 5 ファイルだけで約 20k トークン消費します。32k だと作業開始前に埋まります |
| 1 応答あたりの出力 | **4000 トークン以上** | `server.py` を 1 回の write で書き切るのに必要です |
| 1 リクエストの時間上限 | **なし、または 180 秒以上** | プロキシやゲートウェイの 60 秒制限に注意 |

**ゲートウェイの応答時間上限は事前に測ってください。** 次で測れます。

```bash
time curl -s -m 180 "$BASE_URL/v1/chat/completions" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"model":"'"$MODEL"'","max_tokens":4000,
       "messages":[{"role":"user","content":"1 から 300 まで、1 行ずつ数えてください。省略しないこと。"}]}' \
  -o /dev/null -w '%{http_code}\n'
```

接続が切られる場合は、`max_tokens` を下げて二分探索し、
**上限時間 × 生成速度**が 1 応答の出力上限になります。
検証例: 60 秒の上限 / 33 tok/s → 出力は約 1900 トークンが限界でした。

出力上限が 2000 トークンを下回る環境では、**ツール呼び出しの JSON 自体が
生成途中で切れて失敗します**（`Invalid input for tool write: JSON parsing failed`）。
その場合はエージェントに次を追加で指示してください。

> 1 つのファイルを 1 回で書かないでください。
> 50 行ずつに分けて、write → edit → edit … と追記していってください。

---
---

# ここから下がエージェントへの指示

## あなたの役割

あなたは、opencode / Claude Code の **Skill**（マークダウンで書かれた手順書）を、
**MCP（Model Context Protocol）の HTTP サーバー**に移植するエンジニアです。

このリポジトリには、その移植を 1 回やり切った**完成見本**が入っています。
あなたは見本を読み、同じ構造で新しい移植を行います。

## 最重要の原則（これを忘れないでください）

```
Skill の文章は「全部ただのお願い」です。
MCP では、文章は 2 種類に分かれます。

  (A) description = モデルへのお願い（守らなくても動く）
  (B) schema      = サーバーが強制するルール（破ったらエラーになる）

移植とは、Skill の 1 文ずつについて「これは A か B か」を決める作業です。
これ以外のことはしません。
```

Skill はそのリポジトリを開いた 1 人だけが使います。
MCP サーバーは**ネットワーク越しに誰でも使えます**。
だから「クライアントが気をつけてくれるはず」は通用しません。
守らせたいことは (B) schema にしてください。

---

## 作業の全体像

作業は **9 つの STEP** に分かれています。
**STEP を飛ばさないでください。順番どおりに実行してください。**

| STEP | やること | 成果物 |
|---|---|---|
| 0 | 見本を読む | （読むだけ） |
| 1 | 移植対象の Skill を読む | 棚卸し表 |
| 2 | 移植できるか判定する | 判定結果 |
| 3 | 1 文ずつ仕分けする | 仕分け表 |
| 4 | 出力スキーマを決める | Pydantic モデル |
| 5 | サーバーを書く | `server.py` |
| 6 | 周辺を書く | `settings.py` / `auth.py` / `app.py` / `__main__.py` |
| 7 | テストを書く | `tests/` |
| 8 | コンテナとマニフェストを書く | `Containerfile` / `deploy/` |
| 9 | ドキュメントを書く | `README.md` / `docs/skill-to-mcp.md` |

各 STEP の終わりに **「STEP N 完了」と宣言してから次に進んでください。**

### 途中経過はファイルに書いてください

STEP 1〜4 の成果物（棚卸し表・判定結果・仕分け表）は、
**会話に書くのではなく `<出力先>/docs/porting-notes.md` に追記してください。**

会話の履歴は長くなると切り詰められます。切り詰められると、
この PROMPT.md の指示ごと失われて作業内容を見失います。
ファイルに書いておけば、見失っても読み直せます。

---

## STEP 0: 見本を読む

次の 4 ファイルを**必ず全部読んでください**。読まずに書き始めてはいけません。

| ファイル | 何が書いてあるか |
|---|---|
| `search-mcp/docs/skill-to-mcp.md` | **移植の判断基準そのもの。一番重要** |
| `search-demo/.opencode/skill/public-api-search/SKILL.md` | 移植元の Skill（見本の入力） |
| `search-mcp/src/search_mcp/server.py` | 移植結果（見本の出力） |
| `search-mcp/tests/test_server.py` | 移植が正しいことの検証方法 |

読み終えたら、次の 3 つを自分の言葉で 1 行ずつ書いてください。

1. 見本では SKILL.md の「使い分けの指針」がどこに移ったか
2. 見本では SKILL.md の「注意」の一部が、なぜ description だけでなくスキーマにもなったか
3. `SOURCE_GUIDE` という辞書が存在する理由

**書けなかったら、もう一度読んでください。** 次に進んではいけません。

---

## STEP 1: 移植対象の Skill を読む

移植したい Skill のディレクトリ全体を読みます。

```
<skill-dir>/
  SKILL.md              ← 必ずある
  scripts/              ← あるかもしれない
  references/           ← あるかもしれない
  assets/               ← あるかもしれない
```

読んだら、**棚卸し表**を作って出力してください。フォーマットは固定です。

```markdown
### 棚卸し

| 項目 | 内容 |
|---|---|
| Skill 名 | |
| frontmatter の description | |
| 実行しているコマンド/スクリプト | |
| 入力（引数・オプション） | |
| 出力の形 | |
| 外部ネットワークに出るか | はい / いいえ |
| ローカルファイルを読むか | はい / いいえ（読むなら何を） |
| ローカルファイルを書くか | はい / いいえ（書くなら何を） |
| 同じ入力で何度呼んでも安全か | はい / いいえ |
| 添付ファイル（references/assets）があるか | はい / いいえ |
```

**推測で埋めないでください。** ファイルを読んで確認した内容だけ書いてください。
分からない欄は「不明」と書いてください。

---

## STEP 2: 移植できるか判定する

棚卸し表を見て、**上から順に**次の表を当てはめてください。
最初に当てはまった行の指示に従います。

| # | 条件 | やること |
|---|---|---|
| 1 | ローカルファイルを**書く**、またはユーザーのマシンの状態を変える | **STOP**。人間に「これは MCP 化すべきでないかもしれません。理由: サーバー側にはユーザーのファイルが無いため」と報告し、指示を待つ |
| 2 | ローカルファイルを**読む**（リポジトリの中身など） | `skill-to-mcp.md` §6 を読む。原則は「Skill のまま残す」。MCP 化するなら、ファイル内容を**引数で渡す**設計に変える。人間に確認する |
| 3 | 外部に副作用がある（API に書き込む、メールを送る、デプロイする等） | `skill-to-mcp.md` §7 を読んでから続行。`read_only_hint=False` と冪等性キーが必須になる |
| 4 | references/ や assets/ に参照資料がある | `skill-to-mcp.md` §8 を読んでから続行。Resources にするか Tool にするか決める |
| 5 | 上のどれにも当てはまらない（外部 API を読むだけ） | **そのまま続行。見本と同じ型です** |

判定結果を次の形で出力してください。

```markdown
### 移植判定

- 当てはまった行: #_
- 理由:
- 追加で読んだ節: §_
- 続行 / 人間に確認
```

---

## STEP 3: 1 文ずつ仕分けする

ここが**この作業の本体**です。時間をかけてください。

SKILL.md を**見出しや箇条書きの 1 項目ずつに分解**し、
それぞれを次の 5 つのどれかに分類します。

| 分類 | 意味 | 行き先 |
|---|---|---|
| **INSTRUCTIONS** | サーバー全体の使いどころ・回答の作法 | `MCPServer(instructions=...)` |
| **DESCRIPTION** | このツールを**いつ使うか**、**どう選ぶか** | `@mcp.tool(description=...)` |
| **SCHEMA** | 守らせたい制約（型・範囲・選択肢） | 引数の型 / `Field(ge=, le=)` / `Literal[...]` |
| **GUARD** | description だけでは不十分で、サーバー側のコードでも止めたいもの | 関数の中の `min()` / `max()` / バリデーション |
| **DROP** | MCP では意味が無いので捨てる | （捨てる） |

### 分類のルール（迷ったらこの表で決める）

| 元の文がこうなら | 分類 |
|---|---|
| 「〜のときに使う」「〜を調べたいとき」 | DESCRIPTION |
| 「〜は〜より優先する」「迷ったら〜」 | DESCRIPTION |
| 「`-n` は 1〜20」「`--format` は json か text」 | **SCHEMA**（description ではない） |
| 「〜しすぎないこと」「〜は小さくすること」 | **SCHEMA + GUARD**（両方） |
| 「必ず URL を引用すること」 | INSTRUCTIONS |
| 「このスクリプトを `python3 xxx.py` で実行する」 | **DROP**（MCP では呼び出し方はクライアントが知らなくていい） |
| 「`cd` してから実行」「venv を有効化」 | **DROP** |
| 出力の JSON 例 | 出力スキーマ（STEP 4 で扱う） |

### 間違えやすいところ（ここを特に注意）

> 「〜しすぎないこと」は DESCRIPTION だけにしてはいけません。

例: SKILL.md に「GitHub は未認証なのでレート制限が厳しい。`-n` を小さくする」とある。

- ローカルの Skill なら、これは注意書きで十分です。使う人は 1 人だから。
- MCP サーバーは**誰でも呼べます**。description を無視するクライアントが必ず来ます。
- だから `Field(ge=1, le=20)` にして**スキーマで拒否**します（= SCHEMA）。
- さらに関数の中でも `min(limit, max_limit)` で押さえます（= GUARD）。

見本の `server.py:156-163`（スキーマ）と `server.py:169-170`（ガード）を見てください。
**同じ 1 文が 2 か所に落ちています。** これが正解です。

### 出力フォーマット（固定）

```markdown
### 仕分け表

| # | SKILL.md の記述（原文を引用） | 分類 | 落とし先 | 備考 |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |
```

**SKILL.md の全行をカバーしてください。** 1 文も飛ばさないでください。
DROP にしたものも必ず表に書いてください（なぜ捨てたか分かるように）。

---

## STEP 4: 出力スキーマを決める

SKILL.md の「出力」の例（JSON のサンプルなど）を、Pydantic モデルにします。

### ルール

1. **全フィールドに `Field(description=...)` を付ける。** 例外なし。
   その説明文はモデルが読みます。「id」だけでは何の id か分かりません。
2. **部分的な失敗を表すフィールドを必ず用意する。**
   複数のことを並列にやるツールなら、一部が失敗することがあります。
3. **件数フィールドの description に「0 のときどうするか」を書く。**

### テンプレート（これをコピーして書き換える）

```python
from pydantic import BaseModel, Field


class XxxItem(BaseModel):
    """結果 1 件。"""

    # 全フィールドに description を付ける
    name: str = Field(description="＜モデルが何と解釈すべきか＞")


class XxxError(BaseModel):
    """1 件分の失敗。全体は失敗扱いにしない。"""

    target: str = Field(description="失敗した対象")
    error: str = Field(description="失敗理由")


class XxxResponse(BaseModel):
    count: int = Field(description="items の件数。0 のときは errors を必ず読むこと")
    items: list[XxxItem] = Field(description="＜何のリストか＞")
    errors: list[XxxError] = Field(description="失敗した対象。空なら全件成功")
```

### 失敗の返し分け（重要・間違えやすい）

| 状況 | どうするか |
|---|---|
| 一部だけ失敗した（3 件中 1 件が取れなかった） | **正常に返す。** `errors` に入れる。例外を投げない |
| 呼び出し自体が成立しない（引数が不正、全部失敗） | **例外を投げる。** MCP SDK が `isError: true` にしてくれる |

一部失敗で例外を投げてはいけません。取れた分の結果が捨てられます。
詳しくは `skill-to-mcp.md` §2.7。

---

## STEP 5: サーバーを書く

### 先に読むこと: この SDK の落とし穴

**この 5 つを守らないと動きません。**

| # | 守ること | 守らないとどうなるか |
|---|---|---|
| 1 | `from mcp.server.mcpserver import MCPServer` を使う | MCP SDK 2.x では `FastMCP` は `MCPServer` に改名されています。`FastMCP` は存在しません |
| 2 | `server.py` に `from __future__ import annotations` を**書かない** | SDK が `inspect.signature(..., eval_str=True)` でアノテーションを評価します。文字列化されるとクロージャ変数（`settings.max_limit` など）を解決できず `InvalidSignature` になります |
| 3 | Python 側の属性名は **snake_case**（`read_only_hint`、`structured_content`、`input_schema`） | JSON の通信内容は camelCase（`readOnlyHint`）ですが、Python のコードは snake_case です。混ぜるとエラーになります |
| 4 | HTTP クライアントは `httpx` ではなく **`httpx2`** | この SDK は `httpx2` に依存しています。`import httpx` は失敗します |
| 5 | 同期処理（`requests`、`urllib`、`time.sleep`）は `anyio.to_thread.run_sync()` で包む | イベントループが止まり、他のリクエストが全部待たされます |

### 書き方

見本 `search-mcp/src/search_mcp/server.py` を**そのまま下敷きにしてください。**
構造を変えないでください。

```python
"""＜Skill 名＞ を MCP ツールとして公開するサーバー定義。

設計の要点は docs/skill-to-mcp.md を参照。
"""

# 注意: このモジュールでは `from __future__ import annotations` を使わない。
# ツール関数の Annotated[...] に settings の値を埋め込んでおり、
# アノテーションが文字列化されると SDK 側の eval が解決できず InvalidSignature になるため。

import logging
from typing import Annotated, Literal

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from .settings import Settings

logger = logging.getLogger(__name__)

# --- STEP 3 で INSTRUCTIONS に分類したものをここに置く ---
INSTRUCTIONS = """\
＜このサーバーが何をするか 1 行＞

次のときに `＜ツール名＞` を使う:
  - ＜状況 1＞
  - ＜状況 2＞

＜回答の作法。例: 必ず url を引用元として示すこと＞
"""

# --- STEP 4 で決めた Pydantic モデルをここに置く ---


def build_server(settings: Settings | None = None) -> MCPServer:
    """MCPServer を組み立てて返す。テストから呼べるよう副作用を持たせない。"""
    settings = settings or Settings.from_env()

    mcp = MCPServer(
        name="＜サーバー名＞",
        title="＜人間向けの表示名＞",
        version="1.0.0",
        instructions=INSTRUCTIONS,
        log_level=settings.log_level,
    )

    @mcp.tool(
        name="＜ツール名＞",
        title="＜表示名＞",
        description=(
            "＜何をするツールか 1〜2 文＞\n\n"
            "＜STEP 3 で DESCRIPTION に分類したもの＞\n\n"
            "注意: ＜制約。スキーマにもしたものをもう一度書く＞"
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,       # 読むだけなら True。書くなら False
            destructive_hint=False,    # 既存のものを壊すなら True
            idempotent_hint=True,      # 同じ入力で何度呼んでも同じなら True
            open_world_hint=True,      # 外部ネットワークに出るなら True
        ),
    )
    async def tool_name(
        # STEP 3 で SCHEMA に分類したものを、ここに型と Field で書く
        query: Annotated[
            str,
            Field(description="＜この引数が何か＞"),
        ],
        limit: Annotated[
            int | None,
            Field(
                description=f"＜説明＞（省略時 {settings.default_limit}）",
                ge=1,
                le=settings.max_limit,   # ← スキーマで強制する
            ),
        ] = None,
    ) -> XxxResponse:
        # STEP 3 で GUARD に分類したものを、ここに書く
        effective_limit = settings.default_limit if limit is None else limit
        effective_limit = max(1, min(effective_limit, settings.max_limit))

        logger.info("tool_name query=%r limit=%d", query, effective_limit)

        # 同期処理は必ずスレッドに逃がす
        payload = await anyio.to_thread.run_sync(既存の関数, query, effective_limit)
        return XxxResponse.model_validate(payload)

    return mcp
```

### `annotations` の決め方（迷わないための表）

| ツールの性質 | read_only | destructive | idempotent | open_world |
|---|---|---|---|---|
| 外部 API を読むだけ | `True` | `False` | `True` | `True` |
| ローカルの定数を返すだけ | `True` | `False` | `True` | `False` |
| 外部に新しく作る（作成） | `False` | `False` | `False` | `True` |
| 外部を上書き・削除する | `False` | **`True`** | `False` | `True` |

`destructive_hint=True` を付け忘れると、クライアントが**確認なしで自動実行**します。
書き込み系では必ず確認してください。

### 既存コードは書き直さない

移植元のスクリプトがあるなら、**ロジックをコピーしないでください。**
パス依存として取り込み、`import` して使ってください。

```toml
# pyproject.toml
dependencies = ["＜元のパッケージ名＞", "mcp>=2.3,<3", "uvicorn[standard]", "anyio"]

[tool.uv.sources]
＜元のパッケージ名＞ = { path = "../＜元のディレクトリ＞" }
```

ロジックを 2 か所に持つと、必ずずれます。

---

## STEP 6: 周辺を書く

次の 4 ファイルは**見本からほぼそのままコピーできます。**
`search-mcp/src/search_mcp/` の同名ファイルをコピーし、設定項目だけ差し替えてください。

| ファイル | 役割 | 変える場所 |
|---|---|---|
| `settings.py` | 環境変数の読み込み | ツール固有の設定項目（`default_limit` など） |
| `auth.py` | Bearer トークン認証 | **変えない** |
| `app.py` | ASGI 組み立て（health / 認証 / DNS rebinding 保護） | サーバー名のみ |
| `__main__.py` | uvicorn 起動 | **変えない** |

### 環境変数の規約

| 変数 | 既定 | 意味 |
|---|---|---|
| `MCP_HOST` | `0.0.0.0` | bind アドレス |
| `MCP_PORT` | `8080` | **1024 未満にしない。** OpenShift の制限付き SCC では bind できません |
| `MCP_STATELESS_HTTP` | `true` | **true のままにする。** false だと replica を増やせません |
| `MCP_AUTH_TOKENS` | 空 | 許可する Bearer トークン（カンマ区切り） |
| `MCP_DNS_REBINDING_PROTECTION` | `true` | Host / Origin の検証 |
| `MCP_ALLOWED_HOSTS` | 空 | **外部公開するなら必須。** Route のホスト名を入れる |

### 落とし穴（環境変数）

- **「未設定」と「空文字」は違います。** `MCP_STATELESS_HTTP: ""` は既定値 `true` に戻らず
  `false` になります。ConfigMap では「値を空にする」のではなく「キーごと消して」ください。
- `MCP_ALLOWED_HOSTS` が合っていないと、`/mcp` が
  **`421 Misdirected Request` / `Invalid Host header`** を返します。
  `/healthz` は通るので「probe は成功しているのに `/mcp` だけ落ちる」という見え方をします。
  401 でも 400 でもありません。421 です。

---

## STEP 7: テストを書く

### 必ず守ること

| ルール | 理由 |
|---|---|
| テストは **in-process の `ASGITransport` では動かない**。実際に uvicorn を起動する | `MCPServer` の Starlette アプリは lifespan で task group を起動します。lifespan を実行しないと `RuntimeError: Task group is not initialized` になります |
| テスト中は `enable_dns_rebinding_protection=False` にする | そうしないと `127.0.0.1:<ランダムポート>` が拒否されます |
| **モックを置いた境界の向こう側も誰かがテストする** | 見本では `run_search` をモックしたため、検索ロジック本体が無検査のまま残っていました |

### 最低限これだけは書く（7 項目）

1. 認証なしで `/mcp` を叩くと **401** と `WWW-Authenticate: Bearer` が返る
2. 間違ったトークンでも 401 が返る
3. 正しいトークンで `tools/list` が取れる
4. `instructions` と `description` に、STEP 3 で入れたはずの文字列が実際に載っている
5. スキーマの上限（`le=...`）が `inputSchema` の `maximum` に反映されている
6. 上限を超える引数を渡すとエラーになり、**外部 API に到達しない**
7. 一部失敗が `errors` に載り、残りの結果は返る

4 と 5 が重要です。
「description に書いたつもり」が本当にクライアントに届いているかを、
**プロトコル越しに確認する**のが移植の検証です。

### テストの起動コード（コピーして使う）

```python
@contextlib.asynccontextmanager
async def _serve(settings):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))          # OS に空きポートを選ばせる
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(settings), log_level="warning"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        while not server.started:
            await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task
```

---

## STEP 8: コンテナとマニフェストを書く

`Containerfile` と `search-mcp/deploy/openshift/` を**そのままコピー**し、
イメージ名・サーバー名・ポートだけ差し替えてください。

### 変えてはいけない設定（OpenShift で必須）

```yaml
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  runAsNonRoot: true
  capabilities:
    drop: ["ALL"]
  seccompProfile:
    type: RuntimeDefault
```

- `runAsUser` は**書かないでください**。OpenShift が任意の UID を割り当てます。
- そのため、書き込みが必要な場所には `emptyDir` を当ててください（`/tmp` など）。
- ポートは 8080（1024 未満は bind できません）。

### 動作確認（クラスタが無い場合）

```bash
# 1. ビルド
podman build -f Containerfile -t <image>:1.0.0 .

# 2. OpenShift 相当の制約で起動できるか
podman run --rm \
  --user 1000670000:0 --read-only --tmpfs /tmp \
  --cap-drop ALL --security-opt no-new-privileges \
  -e MCP_AUTH_TOKENS=test <image>:1.0.0

# 3. マニフェストの probe が通るか（podman kube play を使う）
kubectl kustomize deploy/openshift/ > all.yaml
# Deployment / Service / ConfigMap だけ抜き出して podman kube play に渡す
```

**`podman kube play` はスキーマ検証にはなりません。** 独自パーサなので
フィールド名の typo を見逃します。クラスタがあるなら必ず次を実行してください。

```bash
oc apply --dry-run=server -k deploy/openshift/
```

実行できなかった場合は、**「未検証」とドキュメントに明記してください。**
検証したふりをしてはいけません。

---

## STEP 9: ドキュメントを書く

次の 2 つを書きます。

### 9-1. `README.md`

- 何を公開しているか（ツール名と 1 行説明の表）
- 環境変数の表
- ローカルでの起動方法
- テストの実行方法と件数
- **検証状況の表**（✅ と ❌ を正直に書く）

### 9-2. `docs/skill-to-mcp.md`

**STEP 3 の仕分け表をそのまま清書したもの**が中核です。
「元の記述 → 分類 → 落とし先 → なぜそうしたか」を残してください。

次の 3 点を必ず含めてください。

1. **落としたもの**（DROP にした記述）と、その理由
2. **足したもの**（SKILL.md に無かったが MCP で必要になったもの。`annotations` など）
3. **散文からスキーマに格上げしたもの**と、その理由

これが次の移植をする人への一番の資産です。

---

## 完成チェックリスト

全部に ✅ が付くまで「完了」と言わないでください。

### コード

- [ ] `server.py` に `from __future__ import annotations` が**無い**
- [ ] `from mcp.server.mcpserver import MCPServer` を使っている（`FastMCP` ではない）
- [ ] Python の属性名が snake_case（`read_only_hint` であって `readOnlyHint` ではない）
- [ ] 同期処理が `anyio.to_thread.run_sync()` で包まれている
- [ ] 全ての Pydantic フィールドに `Field(description=...)` が付いている
- [ ] `ToolAnnotations` を全ツールに付けた
- [ ] 書き込み系ツールに `read_only_hint=False` を付けた
- [ ] 移植元のロジックをコピーせず、import して使っている
- [ ] ポートが 8080（1024 以上）

### 仕分け

- [ ] SKILL.md の全記述が仕分け表に載っている（DROP も含む）
- [ ] 「〜しすぎないこと」系の記述が、description **だけ**になっていない
- [ ] 選択肢が決まっている引数が `Literal[...]` になっている
- [ ] 範囲がある数値に `ge=` / `le=` が付いている

### テスト

- [ ] 実際に uvicorn を起動してテストしている（ASGITransport ではない）
- [ ] 401 と `WWW-Authenticate` を検証した
- [ ] description の内容がプロトコル越しに届いていることを検証した
- [ ] スキーマの上限が `inputSchema` に出ていることを検証した
- [ ] 上限超えが外部 API に到達しないことを検証した
- [ ] **モックした境界の向こう側に、別のテストがある**

### ドキュメント

- [ ] 検証できなかったことを ❌ として明記した
- [ ] 落としたもの・足したもの・格上げしたものを書いた

---

## やってはいけないこと

| ❌ してはいけない | 理由 |
|---|---|
| STEP 3（仕分け）を飛ばして、いきなりコードを書く | 何を description にして何を schema にするかが、この作業の本体です |
| 移植元のロジックをコピー&ペーストする | 2 か所に持つと必ずずれます。import してください |
| 「〜しすぎないこと」を description だけにする | ネットワーク越しのクライアントは守りません |
| 実行していないコマンドの結果を書く | 検証していないことを検証したと書かないでください |
| 検証できなかった項目をドキュメントから省く | ❌ として残してください |
| 一部失敗で例外を投げる | 取れた分の結果が捨てられます。`errors` に入れてください |
| `runAsUser` を指定する | OpenShift が任意 UID を割り当てるので衝突します |
| 推測で SKILL.md の内容を補完する | 読んで確認した内容だけ書いてください |

---

## 困ったときの参照先

| 状況 | 読む場所 |
|---|---|
| 分類に迷う | `search-mcp/docs/skill-to-mcp.md` §2（対応表） |
| ローカルファイルに依存する Skill | `skill-to-mcp.md` §6 |
| 副作用がある Skill | `skill-to-mcp.md` §7 |
| 添付ファイルがある Skill | `skill-to-mcp.md` §8 |
| エラーの返し方に迷う | `skill-to-mcp.md` §2.7 |
| description の長さに迷う | `skill-to-mcp.md` §4.1 |
| 実際に詰まったエラー | `search-demo/.tracecraft/*/troubleshooting.md` |
| なぜその設計にしたか | `search-demo/.tracecraft/*/decisions.md` |
| 配備の手順 | `search-mcp/docs/deploy-openshift.md` |

---

## 最後に

分からないことがあったら、**推測で進めずに人間に聞いてください。**
特に次の 3 つは必ず確認してください。

1. STEP 2 で「人間に確認」になった場合
2. 認証方式（Bearer トークンでよいか）
3. Skill 版を残すか、MCP に一本化するか
   （同じ opencode に両方入れると、同じ機能が 2 経路で見えて呼び分けが不定になります）
