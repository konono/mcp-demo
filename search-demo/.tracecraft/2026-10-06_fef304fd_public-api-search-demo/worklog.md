# Work Log

> 作業タイトル: (ここに記入)
> 開始日時: (ここに記入)
> 目的: (ここに記入)
> 背景: (ここに記入)
> 期待する最終成果: (ここに記入)

---

<!-- 以下に作業ステップを時系列で追加する -->
<!-- 各ステップは以下のフォーマットに従う -->

<!--
## Step 1: <作業名>

### 目的
このステップで実現・確認したいこと。

### 背景
なぜこのステップが必要になったのか。

### 事前仮説
この時点で考えている原因、方針、期待される挙動。

### 実行内容
#### 変更・操作
変更したファイル（パス）、実行したコマンド、操作の要点。

#### 観察した出力
コマンド出力・ログ・エラーメッセージの要点（全文貼り付け不要、判断に影響した部分のみ）。

#### 参照した情報源
参照したドキュメント、コード箇所（ファイル:行番号）、Web ページ、エラーメッセージの検索結果など。

### 期待結果
事前に想定していた結果。

### 実際の結果
このステップで実行したツールの出力に基づく結果のみ。他のステップで得た情報や、
実行していないコマンドの推測結果は書かない。

### 解釈
結果から何が言えるか。事実と推測を分ける。

### 次の判断
次に何をするか。その理由。
-->

> 作業タイトル: 公開 API 検索デモスクリプト + opencode Skill の作成
> 開始日時: 2026-10-06
> 目的: opencode から Skill 経由で呼び出せる、公開 API 検索のデモ用 Python スクリプトを用意する
> 背景: デモ用途。skill.md を書いて opencode から呼び出す流れを見せたい
> 期待する最終成果: 認証不要で即実行できる検索 CLI と、それを説明する SKILL.md / README

---

## Step 1: 作業環境の確認

### 目的
対象ディレクトリの状態と Python 実行環境の有無を確認する。

### 背景
スクリプトの依存方針（標準ライブラリのみか、httpx 等を使うか）は、環境に何が入っているかで変わる。

### 事前仮説
Python は入っている、もしくは mise で入れられる。

### 実行内容
#### 変更・操作
- `ls -a /Users/kono/gitrepo/search-demo`
- `python3 -V` / `python3 -c "import httpx"`
- `which mise uv python`

#### 観察した出力
- 対象ディレクトリは空（`.` と `..` のみ）
- `python3: command not found`
- `which` は `/home/agent/.local/bin/mise` のみ返し、uv と python は無し（exit code 1）

#### 参照した情報源
/home/agent/.claude/CLAUDE.md（mise が利用可能であること）

### 期待結果
Python の有無が判明すること。

### 実際の結果
Python 未インストール、mise のみ利用可能。ディレクトリは空。

### 解釈
事実: 実行環境に Python ランタイムが無い。推測: デモを見る人の環境にも同様のばらつきがあり得るため、依存を増やさない方が安全。

### 次の判断
mise で Python 3.12 を入れる。スクリプトは標準ライブラリのみで書く。

## Step 2: Python 3.12 の導入

### 目的
スクリプトを実行・検証できるようにする。

### 背景
Step 1 で Python が無いことを確認した。

### 事前仮説
`mise use -g python@3.12` でプリビルドバイナリが入る。

### 実行内容
#### 変更・操作
`mise use -g python@3.12`（グローバル設定 `~/.config/mise/config.toml` を更新）

#### 観察した出力
`mise python@3.12.15 Python 3.12.15` / `installed 1 tool in 7.5s` / `tools: python@3.12.15`

#### 参照した情報源
N/A

### 期待結果
python3.12 が mise 経由で使えるようになる。

### 実際の結果
python@3.12.15 がインストールされ、グローバル設定に記録された。

### 解釈
事実: `mise x -- python` で実行可能になった。なお PATH 直下の `python3` は shim 未反映のため `mise x --` 経由で呼ぶ必要がある。

### 次の判断
スクリプト本体を作成する。

## Step 3: search_demo.py の作成

### 目的
認証不要の公開 API を横断検索する CLI を実装する。

### 背景
デモで「エージェントが外部情報を取ってくる」様子を見せるには、キー設定なしで即動くことが重要。

### 事前仮説
Wikipedia / Hacker News(Algolia) / GitHub / Stack Exchange はいずれも未認証でクエリ可能。

### 実行内容
#### 変更・操作
`/Users/kono/gitrepo/search-demo/search_demo.py` を新規作成。
- `http_get_json()` で urllib をラップし、HTTPError / URLError / JSONDecodeError を `SearchError` に正規化
- `search_wikipedia` / `search_hackernews` / `search_github` / `search_stackoverflow` の 4 関数を `SOURCES` dict に登録
- `run_search()` で ThreadPoolExecutor による並列取得、ソース単位の失敗は `errors` に収集
- argparse で `--source/-s`（複数可・all）、`--limit/-n`、`--lang`、`--format/-f` を提供
- 全ソース失敗時のみ終了コード 1

#### 観察した出力
ファイル作成成功。

#### 参照した情報源
各 API のエンドポイント仕様（MediaWiki Action API, hn.algolia.com/api/v1/search, api.github.com/search/repositories, api.stackexchange.com/2.3/search/advanced）

### 期待結果
4 ソースすべてから結果が取得できる。

### 実際の結果
この時点では未実行。

### 解釈
N/A（次ステップで検証）

### 次の判断
実際に実行して全ソースの応答を確認する。

## Step 4: 実行検証と HTML エスケープの修正

### 目的
全ソースが実際に結果を返すか確認する。

### 背景
API のレスポンス構造は実際に叩かないと確証が持てない。

### 事前仮説
全ソース成功する。

### 実行内容
#### 変更・操作
`mise x -- python search_demo.py "asyncio" -f text -n 2` を実行。
結果を受けて 2 箇所を修正:
- `strip_html()` の戻り値を `html.unescape()` で包む
- Stack Overflow の `title` を `strip_html()` 経由にする

#### 観察した出力
`query: asyncio  (8 results)` で 4 ソース × 2 件が返った。
ただし Wikipedia の snippet に `&quot;hello&quot;` のような HTML エンティティが残っていた。

#### 参照した情報源
実行出力そのもの

### 期待結果
8 件取得。

### 実際の結果
8 件取得できたが、エンティティが未デコードだった。

### 解釈
事実: Wikipedia の snippet と Stack Overflow の title は HTML エスケープ済みで返る。タグ除去だけでは不十分。

### 次の判断
修正後に再検証し、ソース個別指定も確認する。

## Step 5: 修正後の再検証

### 目的
修正が効いているか、ソース個別指定が動くかを確認する。

### 背景
Step 4 の修正を未検証のまま残さないため。

### 事前仮説
エンティティがデコードされ、`-s` 指定で単一ソースのみ返る。

### 実行内容
#### 変更・操作
- `mise x -- python search_demo.py "ModuleNotFoundError _ssl" -s stackoverflow -n 2`
- `mise x -- python search_demo.py "量子計算" -s wikipedia -n 1 -f text`

#### 観察した出力
- 前者: stackoverflow のみ 2 件、`"errors": []`。title に `‘_ssl’` が正しくデコードされて表示
- 後者: 「量子コンピュータ」1 件、日本語 snippet が平文で表示、URL は percent-encode 済み

#### 参照した情報源
実行出力そのもの

### 期待結果
両方成功。

### 実際の結果
両方成功。日本語クエリも正常に処理された。

### 解釈
事実: HTML エンティティのデコード、ソース絞り込み、日本語クエリ、text/json 両形式がいずれも動作する。

### 次の判断
ドキュメント（SKILL.md / README.md）を書いて完了とする。

## Step 6: SKILL.md と README.md の作成

### 目的
opencode から Skill として呼び出せる状態にする。

### 背景
ユーザーの主目的は「skill.md を書いて opencode から呼び出すデモ」。

### 事前仮説
opencode はプロジェクト直下の `.opencode/skill/<name>/SKILL.md` を読む。

### 実行内容
#### 変更・操作
- `/Users/kono/gitrepo/search-demo/.opencode/skill/public-api-search/SKILL.md` を作成。frontmatter に `name` と、発動条件を含む `description` を記載。本文にオプション表、出力例、ソースの使い分け指針、レート制限の注意を記載
- `/Users/kono/gitrepo/search-demo/README.md` を作成。構成・対応 API 表・実行例・opencode への配置方法・デモ用プロンプト例・設計メモを記載

#### 観察した出力
両ファイル作成成功。

#### 参照した情報源
Step 4/5 の実行出力（SKILL.md の出力例・README の実行例に使用）

### 期待結果
opencode がこのリポジトリを開くだけで Skill を認識できる。

### 実際の結果
ファイルは作成済み。opencode 実機での読み込みは未検証。

### 解釈
推測: `.opencode/skill/<name>/SKILL.md` の配置規約は正しいが、このセッションでは opencode を起動していないため未確認。

### 次の判断
ユーザーに opencode 実機での確認を委ねる。
