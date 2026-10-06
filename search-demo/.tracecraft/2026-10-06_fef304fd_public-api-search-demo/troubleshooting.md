# Troubleshooting

> 作業タイトル: (ここに記入)
> 開始日時: (ここに記入)

---

<!-- 以下に問題の切り分けと解決過程を追加する -->
<!-- 各項目は以下のフォーマットに従う -->

<!--
## Issue: <問題名>

### 症状
観測された問題。

### 影響
何ができなかったか、どの範囲に影響したか。

### 原因候補
考えた原因の一覧。

### 切り分け
各原因候補をどう検証したか。

### 実際の原因
最終的に原因だと判断したもの。

### 解決策
実施した修正。

### 解決確認
なぜ解決したと言えるか。確認した結果。

### 再発防止
次回同じ問題を避ける方法。
-->

> 作業タイトル: 公開 API 検索デモスクリプト + opencode Skill の作成
> 開始日時: 2026-10-06

---

## Issue: 検索結果に HTML エンティティがそのまま表示される

### 症状
`mise x -- python search_demo.py "asyncio" -f text -n 2` の Wikipedia 結果 snippet に
`print(&quot;hello&quot;)` のように文字実体参照が残った。

### 影響
エージェントがこの文字列をそのまま引用すると、ユーザーへの回答に `&quot;` が混入する。デモの見栄えも損なう。

### 原因候補
1. API がタグ付き HTML を返しており、自作の `strip_html()` がタグしか除去していない
2. レスポンスのエンコーディング指定ミス
3. json のデコードミス

### 切り分け
出力を確認すると日本語は正しく表示され、壊れているのは `&quot;` / `&amp;` 等の実体参照のみだった。これによりエンコーディング（候補 2）と JSON デコード（候補 3）は除外できる。

### 実際の原因
`strip_html()` が `<` 〜 `>` の除去だけを行い、HTML の文字実体参照をデコードしていなかった。Wikipedia の search API は snippet を HTML 断片として返すため、タグと実体参照の両方が含まれる。

### 解決策
`search_demo.py` に `import html` を追加し、`strip_html()` の戻り値を `html.unescape(...)` で包んだ。あわせて Stack Overflow の `title` も `strip_html()` を通すよう変更した（こちらも同様にエスケープ済みで返るため）。

### 解決確認
`mise x -- python search_demo.py "ModuleNotFoundError _ssl" -s stackoverflow -n 2` の出力で
`No module named ‘_ssl’ in RHEL6 but works in RHEL7` と正しくデコードされた表示を確認した。
`mise x -- python search_demo.py "量子計算" -s wikipedia -n 1 -f text` でも日本語 snippet が平文で表示された。

### 再発防止
外部 API のテキストフィールドは「HTML 断片である可能性」を前提に、タグ除去と実体参照デコードを常にセットで行う。今回は `strip_html()` 一箇所に集約したので、新ソース追加時はこの関数を通すだけでよい。
