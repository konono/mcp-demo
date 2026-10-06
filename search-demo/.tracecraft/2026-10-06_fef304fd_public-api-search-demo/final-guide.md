# <作業タイトル>

## 1. 概要

今回実現したこと。

## 2. 背景と目的

なぜこの作業が必要だったのか。

## 3. 前提条件

必要な環境、権限、ツール、入力情報。

## 4. 最終成果物

作成・変更したもの、最終構成、重要なファイル。

## 5. 設計判断

重要な判断とその理由。decisions.md から主要な判断を要約。

## 6. 調査してわかったこと

作業中の重要な発見。findings.md から主要な発見を要約。

## 7. 実施手順

再現可能な手順。worklog.md の成功したステップを整理。

## 8. 動作確認

確認方法、期待結果、実際の結果。

## 9. 発生した問題と解決

主要な問題、原因、解決策。troubleshooting.md から要約。

## 10. ロールバック・復旧

戻し方、バックアップ、復旧手順。

## 11. 運用・保守上の注意

監視、ログ、セキュリティ、権限、制約、メンテナンス。

## 12. 付録

コマンド一覧、設定例、参考情報、関連ファイル。

> 作業タイトル: 公開 API 検索デモスクリプト + opencode Skill の作成
> 完了日時: 2026-10-06

## ゴール

認証不要の公開 API を横断検索する Python CLI を作り、opencode から Skill として呼び出せる状態にする。

## 成果物

| パス | 内容 |
|---|---|
| `/Users/kono/gitrepo/search-demo/search_demo.py` | 本体 CLI（標準ライブラリのみ） |
| `/Users/kono/gitrepo/search-demo/.opencode/skill/public-api-search/SKILL.md` | opencode 用 Skill 定義 |
| `/Users/kono/gitrepo/search-demo/README.md` | 利用方法・設計メモ |

## 再現手順

### 1. Python を用意する（未インストールの場合）

```bash
mise use -g python@3.12
```

以降 `mise x -- python` で実行する（PATH 上の `python3` が無い環境のため）。

### 2. スクリプトの要件

- `urllib.request` のみ使用、外部依存なし
- 4 ソース: wikipedia / hackernews / github / stackoverflow を `SOURCES` dict に登録
- `http_get_json()` で HTTPError / URLError / JSONDecodeError を `SearchError` に正規化
- `ThreadPoolExecutor` で並列取得、ソース単位の失敗は `errors` に収集し処理継続
- 外部 API のテキストは `strip_html()`（タグ除去 + `html.unescape()`）を必ず通す
- 出力既定は JSON、`--format text` で人間向け

### 3. 動作確認

```bash
mise x -- python search_demo.py "asyncio" -f text -n 2
mise x -- python search_demo.py "rust tui" -s github -n 3
mise x -- python search_demo.py "量子計算" -s wikipedia --lang ja -f text
```

4 ソースすべてで `errors` が空になれば成功。

### 4. opencode への登録

プロジェクト直下に `.opencode/skill/<name>/SKILL.md` を置く。frontmatter は:

```yaml
---
name: public-api-search
description: <いつ使うかを含めた説明。エージェントはこれだけで起動を判断する>
---
```

全ユーザーで使う場合は `~/.config/opencode/skill/public-api-search/` に置き、
SKILL.md 内のコマンドを `search_demo.py` の絶対パスに書き換える。

## つまずきポイント

- **Wikipedia の snippet / Stack Overflow の title は HTML エスケープ済み**。タグ除去だけでは `&quot;` が残る。`html.unescape()` を併用する。
- **GitHub と Stack Exchange は未認証だとレート制限が厳しい**。デモ中の連打を避け、`-n` を小さくする。
- **部分失敗は終了コードに出ない**。`count` が 0 のときは `errors` を読む運用を SKILL.md に明記した。

## 未検証事項

- opencode 実機での Skill 読み込みは本セッションでは確認していない。
- 未認証時のレート制限の実測値は取っていない。
