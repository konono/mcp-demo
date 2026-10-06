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

## Finding 1: search-demo の依存・対応バージョン・エントリポイント

### 調べた理由
pyproject.toml の `dependencies` / `requires-python` / `[project.scripts]` を事実に基づいて埋めるため。

### 調査方法
`cat README.md` と `grep -n` による `search_demo.py` の関数定義・`__main__` ガードの抽出。

### わかった事実
- 依存ライブラリはゼロ（標準ライブラリ `urllib` のみ）
- 対応 Python は 3.10 以上
- エントリポイント関数は `main(argv: list[str] | None = None) -> int`
- プロジェクトは単一モジュール構成（パッケージディレクトリを持たない）

### 根拠
- `/Users/kono/gitrepo/mcp-demo/search-demo/README.md` 「Python 3.10+ が必要」および設計メモ「依存ゼロ（`urllib` のみ）にしているので、エージェントが `pip install` を挟まずに即実行できる」
- `/Users/kono/gitrepo/mcp-demo/search-demo/search_demo.py:196` `def main(argv: list[str] | None = None) -> int:`
- `/Users/kono/gitrepo/mcp-demo/search-demo/search_demo.py:229` `if __name__ == "__main__":`
- `ls -a` の結果、トップレベルは `search_demo.py` のみで `src/` やパッケージディレクトリは存在しない

### 作業への影響
`dependencies = []`、`requires-python = ">=3.10"`、`search-demo = "search_demo:main"` を確定。単一モジュールのため wheel ターゲットに `only-include` を明記した。

### 未確認事項
- `USER_AGENT` の `search-demo/1.0` がプロジェクトバージョンとして維持される意図かどうかは未確認（バージョン文字列の二重管理になる）
- ライセンス、author 情報は既存ファイルに記載がなく未確認のため pyproject.toml に含めていない

## Finding 2: この環境には Python ランタイムが設定されていない

### 調べた理由
作成した pyproject.toml をビルドして検証したかったため。

### 調査方法
`python3 --version`、`command -v uv` の実行。`cat mise.toml .mise.toml`。

### わかった事実
- `python3` は mise のシムだが、バージョンが未設定で実行不可
- `uv` は未インストール
- リポジトリに `mise.toml` / `.mise.toml` は存在しない

### 根拠
- `python3 --version` の stderr: `mise ERROR No version is set for shim: python3` / `Set a global default version with one of the following: mise use -g python@3.12.15`
- `command -v uv` が失敗し、フォールバックの `echo "no uv"` が出力された
- `cat mise.toml .mise.toml` が exit code 1（ファイルなし）

### 作業への影響
pyproject.toml のビルド検証を実施できなかった。構文・設定の妥当性は未検証のまま納品している。

### 未確認事項
- hatchling の `only-include` + `sources = ["."]` の組み合わせが実際に `search_demo.py` を wheel ルートに配置するか（実ビルド未実施）

## Finding 3: uv は Python 未設定の環境でも自前で CPython を取得する

### 調べた理由
Finding 2 でこの環境には Python がないと判明していたため、ビルド前に Python を別途インストールする必要があるかを知る必要があった。

### 調査方法
`mise use uv@latest` で uv のみを導入し、Python を入れずに `mise x -- uv build` を実行して挙動を観察した。

### わかった事実
- uv 単体で `Downloading cpython-3.14.8-linux-aarch64-gnu (download) (28.9MiB)` を行い、取得した CPython でビルドを完遂した
- mise への Python 追加は不要だった
- ただし `mise x -- python` は依然として使えない（uv が取得した Python は mise のシムには登録されない）
- 任意の Python コードを動かしたい場合は `mise x -- uv run --no-project python -c "..."` が使える

### 根拠
- `mise x -- uv build` の stdout 冒頭の `Downloading cpython-3.14.8-linux-aarch64-gnu (download) (28.9MiB)`
- `mise x -- python -c "import zipfile;..."` の stderr: `mise ERROR No version is set for shim: python`
- 同じコードを `mise x -- uv run --no-project python -c ...` で実行すると wheel のファイル一覧が正常に出力された

### 作業への影響
Python ランタイムを mise に追加せずにビルド検証を完了できた。`mise.toml` に追加されたのは `uv` のみで済んだ。

### 未確認事項
- uv がどの Python バージョンを選ぶかの決定ロジック（`requires-python = ">=3.10"` を見て 3.14.8 を選んだのか、単に最新を取っただけか）は未確認

## Finding 4: hatchling の only-include はターゲットごとに個別指定が必要

### 調べた理由
Decision 1 で `.opencode` や `__pycache__` の混入を避けるために hatchling を選んだが、その狙いが達成されているかを成果物の中身で確認する必要があった。

### 調査方法
生成された wheel を Python の `zipfile.ZipFile(...).namelist()` で、sdist を `tar tzf` で一覧表示して比較した。

### わかった事実
- `[tool.hatch.build.targets.wheel]` の `only-include` は wheel ターゲットにのみ適用される
- sdist ターゲットには別の既定ルールが適用され、`.opencode/skill/public-api-search/SKILL.md` と `.tracecraft/` 配下の全 14 ファイルが混入していた
- `[tool.hatch.build.targets.sdist]` に `only-include` を追加することで sdist も 5 ファイル（`search_demo.py`, `README.md`, `mise.toml`, `pyproject.toml`, `PKG-INFO`）に絞れた
- `pyproject.toml` と `PKG-INFO` は `only-include` に列挙しなくても hatchling が自動で sdist に含める

### 根拠
- 修正前の `tar tzf dist/search_demo-1.0.0.tar.gz` 出力に `search_demo-1.0.0/.tracecraft/2026-10-06_dd86561f_pyproject-toml/worklog.md` などが並んでいた
- 同時点の wheel の `namelist()` は `search_demo.py` と `search_demo-1.0.0.dist-info/` 配下 4 件のみだった
- `/Users/kono/gitrepo/mcp-demo/search-demo/pyproject.toml` に sdist ターゲットを追加後の `tar tzf` 出力は 5 件のみ

### 作業への影響
pyproject.toml に `[tool.hatch.build.targets.sdist]` を追加した。これがなければ作業ジャーナルが配布物に同梱されるところだった。

### 未確認事項
- 環境情報は `Is a git repository: false` を示しており、git 管理下であれば hatchling の VCS ベース除外（.gitignore 参照）が働いて混入しなかった可能性があるが、未検証
