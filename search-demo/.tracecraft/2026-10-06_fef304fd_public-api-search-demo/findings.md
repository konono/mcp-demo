# Findings

> 作業タイトル: (ここに記入)
> 開始日時: (ここに記入)

---

<!-- 以下に調査結果を追加する -->
<!-- 各項目は以下のフォーマットに従う -->

<!--
## Finding: <調査テーマ>

### 調べた理由
なぜこの調査が必要だったのか。

### 調査方法
使用した資料、検索語、コマンド、ログ、実験方法。

### わかった事実
確認できたこと。

### 根拠
事実の裏付け。このセッションでツール（Read, Bash 等）を使って実際に確認した情報のみ記載する。
コードの具体箇所（ファイル:行番号）、コマンド出力の引用、ドキュメントの該当部分。
実行していないコマンドの結果や、読んでいないファイルの内容は根拠にならない。

### 作業への影響
この発見が設計、手順、実装、検証にどう影響したか。

### 未確認事項
まだ確証がないこと、後で確認すべきこと。
-->

> 作業タイトル: 公開 API 検索デモスクリプト + opencode Skill の作成
> 開始日時: 2026-10-06

---

## Finding: 実行環境に Python が無く mise のみ利用可能

### 調べた理由
スクリプトの依存方針を決めるため。

### 調査方法
`python3 -V`、`which mise uv python` を実行。

### わかった事実
`python3` は PATH に存在しない。`mise` のみ `/home/agent/.local/bin/mise` にある。`mise use -g python@3.12` で python@3.12.15 を導入できた。

### 根拠
`python3 -V` → `/bin/bash: line 1: python3: command not found`。`which mise uv python` → `/home/agent/.local/bin/mise` のみ出力、exit code 1。`mise use -g python@3.12` → `mise python@3.12.15 Python 3.12.15`。

### 作業への影響
外部パッケージ（requests / httpx）を避け、`urllib.request` のみで実装する方針を確定させた。

### 未確認事項
mise reshim 後に `python3` が PATH に出るかは未確認。本セッションでは一貫して `mise x -- python` で実行した。

## Finding: 4 つの公開 API はいずれも未認証でアクセス可能

### 調べた理由
デモで API キー設定を不要にしたいため、実際に未認証で叩けるか確認が必要だった。

### 調査方法
`search_demo.py` を実装し、`mise x -- python search_demo.py "asyncio" -f text -n 2` で 4 ソース同時に実行。

### わかった事実
Wikipedia(ja) / Hacker News(Algolia) / GitHub repository search / Stack Exchange(stackoverflow) すべてが未認証で結果を返した。合計 8 件、`errors` は空。

### 根拠
実行出力 `query: asyncio  (8 results)`。内訳は wikipedia 2 件（Async/await ほか）、hackernews 2 件（points/comments 付き）、github 2 件（fastapi/fastapi ★102842 ほか）、stackoverflow 2 件（score 付き）。

### 作業への影響
4 ソースすべてを既定（`all`）の対象として残した。

### 未確認事項
未認証時の実際のレート制限閾値は実測していない。SKILL.md には GitHub 約 10 req/min と一般に知られる値を注意として記載したが、本セッションでは未検証。

## Finding: Wikipedia snippet と Stack Overflow title は HTML エスケープ済みで返る

### 調べた理由
初回実行の出力に `&quot;` が混じっていたため。

### 調査方法
`mise x -- python search_demo.py "asyncio" -f text -n 2` の出力を目視確認。

### わかった事実
Wikipedia の `snippet` は `<span class="searchmatch">` などのタグに加え、`&quot;` 等の文字実体参照を含む。Stack Overflow の `title` も `‘` などがエスケープされて返る。

### 根拠
修正前の出力: `import asyncio async def main(): print(&quot;hello&quot;)`。修正後の出力: `ModuleNotFoundError: No module named ‘_ssl’ in RHEL6 but works in RHEL7`。

### 作業への影響
`strip_html()` に `html.unescape()` を追加し、Stack Overflow の title も `strip_html()` 経由に変更した。

### 未確認事項
Hacker News / GitHub のフィールドにエスケープが含まれるケースがあるかは未確認（今回の出力には現れなかった）。
