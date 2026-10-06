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

## Issue 1: Python ランタイム未設定でビルド検証ができない

### 症状
`python3 --version` が `mise ERROR No version is set for shim: python3` で失敗。`uv` も未インストール。

### 影響
作成した pyproject.toml をビルドして検証できない。構文エラーやバックエンド設定ミスがあっても検出できない。

### 原因候補
1. mise にグローバルな Python バージョンが設定されていない
2. リポジトリに mise.toml がなく、プロジェクトローカルの指定もない
3. uv などの代替ビルドツールが未インストール

### 切り分け
- `cat mise.toml .mise.toml` → exit code 1。候補 2 を確認。
- `command -v uv` → 失敗。候補 3 を確認。
- mise のエラーメッセージ自体が `mise use -g python@3.12.15` を提案しており、候補 1 を確認。

### 実際の原因
候補 1 と 2 の両方。mise はインストール済みだが Python バージョンが global にもプロジェクトにも設定されていない。

### 解決策
未解決。Python のインストールはユーザーの依頼（pyproject.toml の作成）の範囲外であり、環境を変更する副作用があるため実施しなかった。README には `mise use python@3.12` の記載があるので、検証したい場合はそれを実行すればよい。

### 解決確認
N/A（未解決のまま。ユーザーに未検証である旨を報告する）

### 再発防止
リポジトリに `mise.toml` をコミットして Python バージョンを固定すれば、同じ環境で再現なく python が使える。ただしこれもユーザー依頼外のため今回は作成していない。

## Issue 2: mise x -- python が使えない（uv 導入後も）

### 症状
uv 導入・ビルド成功後も `mise x -- python -c "import zipfile;..."` が
`mise ERROR No version is set for shim: python` で失敗する。

### 影響
wheel の中身を確認するための単発 Python スクリプトが実行できない。

### 原因候補
1. mise に Python ツールが登録されていない
2. uv が取得した CPython が mise のシムに登録されていない
3. uv build が Python を使ったのだから python は使えるはず、という前提自体が誤り

### 切り分け
- `mise.toml` の内容は `[tools]` / `uv = "latest"` のみで Python の記載なし → 候補 1 を確認
- `uv build` は成功していた（CPython 3.14.8 を自分でダウンロード）→ uv は Python を持っているが mise 経由では見えない。候補 2・3 を確認

### 実際の原因
uv が取得した CPython は uv の管理下にあり、mise のシム（`mise x -- python`）からは参照できない。mise には uv しか登録していないので python シムは解決できない。

### 解決策
`mise x -- uv run --no-project python -c "..."` を使う。`--no-project` でカレントの pyproject.toml を無視し、uv 管理の Python をそのまま起動する。

### 解決確認
```
$ mise x -- uv run --no-project python -c "import zipfile;print(...)"
search_demo.py
search_demo-1.0.0.dist-info/METADATA
...
```
wheel のファイル一覧が正常に出力された。

### 再発防止
この環境で Python を単発実行したいときは `mise x -- uv run --no-project python` を使う。mise に python を追加する必要はない。

## Issue 3: sdist に .tracecraft/ と .opencode/ が混入

### 症状
`tar tzf dist/search_demo-1.0.0.tar.gz` の結果に
`search_demo-1.0.0/.opencode/skill/public-api-search/SKILL.md` と
`search_demo-1.0.0/.tracecraft/` 配下 14 ファイルが含まれていた。
一方 wheel は `search_demo.py` + dist-info のみで clean だった。

### 影響
配布用の sdist に作業ジャーナル（調査過程・判断記録）とエディタ設定が同梱される。
配布物としては不適切で、意図しない情報が外部に出る可能性がある。

### 原因候補
1. `only-include` の指定が誤っている
2. `only-include` が wheel ターゲットにしか効いていない
3. git リポジトリでないため hatchling の VCS ベース除外が働いていない

### 切り分け
- wheel は clean だった → `only-include` 自体は正しく機能している。候補 1 を否定。
- pyproject.toml に書いたのは `[tool.hatch.build.targets.wheel]` のみで sdist ターゲットの設定がなかった → 候補 2 を確認。
- 環境情報の `Is a git repository: false` は候補 3 とも整合するが、候補 2 だけで現象を説明できる。

### 実際の原因
候補 2。hatchling のビルドターゲット設定はターゲットごとに独立しており、
wheel 用の `only-include` は sdist に適用されない。sdist の既定はプロジェクトルート配下をほぼ全部含める挙動だった。

### 解決策
`/Users/kono/gitrepo/mcp-demo/search-demo/pyproject.toml` に追加:
```toml
[tool.hatch.build.targets.sdist]
only-include = ["search_demo.py", "README.md", "mise.toml"]
```

### 解決確認
`rm -rf dist && mise x -- uv build` 後:
```
$ tar tzf dist/search_demo-1.0.0.tar.gz
search_demo-1.0.0/mise.toml
search_demo-1.0.0/search_demo.py
search_demo-1.0.0/README.md
search_demo-1.0.0/pyproject.toml
search_demo-1.0.0/PKG-INFO
```
さらに sdist から直接インストールして実行しても動作した:
`mise x -- uv run --no-project --with ./dist/search_demo-1.0.0.tar.gz search-demo "rust" -s github -n 1 -f text`
→ GitHub 検索結果が 1 件返った。

### 再発防止
ビルド設定を書いたら成果物の中身を必ず一覧表示して確認する。
ビルドが「成功」することと、中身が正しいことは別の検証項目である。
