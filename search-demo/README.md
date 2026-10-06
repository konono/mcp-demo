# search-demo

公開 API を横断検索する Python デモスクリプトと、それを opencode から呼び出す Skill。

## 構成

```
search_demo.py                                 # 本体（標準ライブラリのみ・認証不要）
.opencode/skill/public-api-search/SKILL.md     # opencode 用 Skill 定義
```

## 対応ソース

| ソース | API | 認証 |
|---|---|---|
| wikipedia | MediaWiki Action API | 不要 |
| hackernews | Algolia HN Search API | 不要 |
| github | GitHub Repository Search API | 不要（レート制限あり） |
| stackoverflow | Stack Exchange API 2.3 | 不要 |

## 単体での実行

```bash
python3 search_demo.py "asyncio"                        # 全ソース・JSON
python3 search_demo.py "rust" -s github -n 3            # GitHub のみ
python3 search_demo.py "量子計算" -s wikipedia --lang ja -f text
```

Python 3.10+ が必要。このリポジトリでは mise で用意している:

```bash
mise use python@3.12
mise x -- python search_demo.py "asyncio" -f text
```

## opencode から使う

opencode はプロジェクト直下の `.opencode/skill/<name>/SKILL.md` を Skill として読み込む。
このリポジトリをそのまま開けば `public-api-search` が有効になる。

ユーザー全体で使いたい場合は `~/.config/opencode/skill/public-api-search/` に
SKILL.md を置き、SKILL.md 内のコマンドを `search_demo.py` の絶対パスに書き換える。

デモ時のプロンプト例:

- 「asyncio について調べて、出典 URL 付きでまとめて」
- 「Rust の TUI ライブラリを GitHub で探して、スター順に 3 つ」
- 「`ModuleNotFoundError: No module named '_ssl'` の解決策を Stack Overflow で」

## 設計メモ

- 依存ゼロ（`urllib` のみ）にしているので、エージェントが `pip install` を挟まずに即実行できる。
- 各ソースは `ThreadPoolExecutor` で並列取得する。
- 1 つのソースが落ちても他の結果は返し、失敗は `errors` 配列に入れる。
  エージェントが部分結果で回答を続けられるようにするため。
- 出力は既定で JSON。エージェントがパースしやすく、`--format text` は人間確認用。
