---
name: public-api-search
description: Wikipedia / Hacker News / GitHub / Stack Overflow の公開 API を横断検索する。ユーザーが用語の意味・技術トピックの一次情報・OSS リポジトリ・エラーの既知の解決策を探しているとき、または最新の外部情報の裏取りが必要なときに使う。認証不要。
---

# public-api-search

認証不要の公開 API を横断検索し、JSON で結果を返すデモ Skill。
実体は標準ライブラリのみで書かれた `search_demo.py` で、依存のインストールは不要。

## 使い方

リポジトリルートで次を実行する（`python3` が無い環境では `mise x -- python` を使う）:

```bash
python3 search_demo.py "<検索キーワード>"
```

主なオプション:

| オプション | 説明 | 既定 |
|---|---|---|
| `--source` / `-s` | `wikipedia` `hackernews` `github` `stackoverflow` `all`。複数指定可 | `all` |
| `--limit` / `-n` | ソースごとの取得件数 | `5` |
| `--lang` | Wikipedia の言語コード（`ja` / `en` など） | `ja` |
| `--format` / `-f` | `json` または `text` | `json` |

## 出力

```json
{
  "query": "asyncio",
  "count": 8,
  "results": [
    { "source": "github", "title": "fastapi/fastapi", "url": "https://github.com/fastapi/fastapi", "snippet": "★102842 Python: FastAPI framework..." }
  ],
  "errors": []
}
```

- `results[].source` で出典が分かる。回答時は必ず `url` を引用元として提示する。
- 一部のソースが失敗しても処理は続行し、`errors` に理由が入る（全滅時のみ終了コード 1）。

## 使い分けの指針

- 用語・概念の定義 → `-s wikipedia`（日本語なら `--lang ja`、専門的な内容は `--lang en` も試す）
- 技術トピックの議論・評判 → `-s hackernews`
- 実装やライブラリを探す → `-s github`
- エラーメッセージ・実装上の詰まり → `-s stackoverflow`（キーワードはエラー文の固有部分を削って短くする）
- 当たりが付かないとき → ソース指定なし（`all`）で広く拾ってから絞る

## 注意

- GitHub と Stack Exchange は未認証のためレート制限が厳しい（GitHub 検索は約 10 req/min）。連続実行は避け、`-n` を小さくする。
- 日本語キーワードはそのまま渡してよい（内部で URL エンコードする）。
- ネットワーク不通時は `errors` にのみ記録されるため、`count` が 0 のときは `errors` を必ず読むこと。

## 動作確認

```bash
python3 search_demo.py "asyncio" -f text -n 2
```
