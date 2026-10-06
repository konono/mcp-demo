# Work Log

> 作業タイトル: pyproject.toml の作成
> 開始日時: 2026-10-06
> 目的: search-demo リポジトリに PEP 621 準拠の pyproject.toml を追加する
> 背景: 既存は単一スクリプト `search_demo.py` のみで、パッケージメタデータが存在しなかった
> 期待する最終成果: ビルド可能な pyproject.toml

---
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

## Step 1: プロジェクト構成の把握

### 目的
pyproject.toml を書くために、パッケージ名・バージョン・依存・エントリポイント・対応 Python バージョンを確定する。

### 背景
ユーザーから「pyproject.toml を作成してください」という依頼のみ。既存ファイルの構成が不明だったため、まず読み取りが必要だった。

### 事前仮説
README に「標準ライブラリのみ」と書かれていそうなので依存ゼロ、単一モジュール構成になると推測した。

### 実行内容
- 変更・操作:
  - `ls -a /Users/kono/gitrepo/mcp-demo/search-demo`
  - `cat /Users/kono/gitrepo/mcp-demo/search-demo/README.md`
  - `head -40 /Users/kono/gitrepo/mcp-demo/search-demo/search_demo.py`
  - `grep -n "def main\|__main__\|add_argument\|^def \|version" search_demo.py`
  - `cat mise.toml .mise.toml`（存在せず exit code 1）
- 観察した出力:
  - ディレクトリ直下は `.opencode/`, `.tracecraft/`, `README.md`, `__pycache__/`, `search_demo.py` のみ。`pyproject.toml` は未存在、`mise.toml` も未存在。
  - README: 「Python 3.10+ が必要」「依存ゼロ（`urllib` のみ）」
  - `search_demo.py:33` に `USER_AGENT = "search-demo/1.0 (+https://example.invalid; public API demo)"`
  - `search_demo.py:196` に `def main(argv: list[str] | None = None) -> int:`、`search_demo.py:229` に `if __name__ == "__main__":`
- 参照した情報源:
  - `/Users/kono/gitrepo/mcp-demo/search-demo/README.md`（「Python 3.10+ が必要」「設計メモ」節）
  - `/Users/kono/gitrepo/mcp-demo/search-demo/search_demo.py:33, :196, :229`

### 期待結果
パッケージメタデータを埋めるのに十分な情報が揃うこと。

### 実際の結果
name/version/requires-python/dependencies/entry point をすべて既存ファイルの記述から決定できた。

### 解釈
事実: 依存は空、Python 3.10+、単一モジュール `search_demo.py`、`main()` がエントリポイント。
推測: `USER_AGENT` の `1.0` は意図されたプロジェクトバージョンなので、`version = "1.0.0"` が妥当。

### 次の判断
ビルドバックエンドを選定して pyproject.toml を書く。

## Step 2: pyproject.toml の作成

### 目的
標準的な PEP 621 形式の pyproject.toml を追加する。

### 背景
Step 1 でメタデータが確定した。単一モジュールであるため、パッケージ自動検出に頼らず明示的に include する必要がある。

### 事前仮説
hatchling なら `only-include` で単一モジュールを素直に指定できる。

### 実行内容
- 変更・操作: `/Users/kono/gitrepo/mcp-demo/search-demo/pyproject.toml` を新規作成（既存ファイルなし、上書きではない）。内容は build-system に hatchling、`[project]` に name=`search-demo` / version=`1.0.0` / requires-python=`>=3.10` / dependencies=`[]`、`[project.scripts]` に `search-demo = "search_demo:main"`、`[tool.hatch.build.targets.wheel]` に `only-include = ["search_demo.py"]` と `sources = ["."]`。
- 観察した出力: Write ツールが `File created successfully` を返した。
- 参照した情報源: Step 1 で読んだ README と search_demo.py。

### 期待結果
ファイルが作成され、内容が既存コードの事実と矛盾しないこと。

### 実際の結果
作成に成功。

### 解釈
事実: ファイルは作成済み。
推測: `main()` が `int` を返すため、console script として終了コードが正しく伝播する。

### 次の判断
ビルドで検証を試みる。

## Step 3: ビルド検証の試行と断念

### 目的
pyproject.toml が実際にビルド可能か確認する。

### 背景
作成しただけでは構文・バックエンド設定の妥当性が未検証。

### 事前仮説
uv か python3 があればビルド検証できる。

### 実行内容
- 変更・操作: `(command -v uv && uv build ...) || echo "no uv"`
- 観察した出力: `no uv`
- 参照した情報源: N/A

### 期待結果
ビルド成果物が生成されること。

### 実際の結果
uv が未インストールで実行できず。先立つ `python3 --version` も mise のシム解決エラー（`No version is set for shim: python3`）で失敗していた。

### 解釈
事実: この環境には利用可能な Python ランタイムもビルドツールも設定されていない。
推測: pyproject.toml 自体は標準的な構成なので妥当だが、実ビルドによる検証は未実施のまま。

### 次の判断
未検証であることをユーザーに明示して報告する。ランタイム導入はユーザーの依頼範囲外のため行わない。

## Step 4: mise で uv を導入

### 目的
Step 3 で断念したビルド検証を実施できるようにする。

### 背景
ユーザーから「miseでuvいれてbuild検証してください」と明示的に依頼された。Decision 2 で「依頼範囲外」として見送った環境変更が、依頼により範囲内になった。

### 事前仮説
`mise use uv@latest` で uv が入り、uv が Python を自前で用意するので Python の別途インストールは不要。

### 実行内容
- 変更・操作: `/Users/kono/gitrepo/mcp-demo/search-demo` で `mise use uv@latest` を実行。副作用としてリポジトリ直下に `mise.toml` が新規作成された（内容: `[tools]` / `uv = "latest"`）。
- 観察した出力: `mise ✓ uv@0.12.23  3.3s  uv-aarch64-unknown-linux-gnu.tar.gz` / `mise /Users/kono/gitrepo/mcp-demo/search-demo/mise.toml tools: uv@0.12.23`
- 参照した情報源: N/A

### 期待結果
uv が実行可能になること。

### 実際の結果
uv 0.12.23 がインストールされ、`mise.toml` に記録された。

### 解釈
事実: `mise use` は選択したツールを `mise.toml` に書き込む。これは CLAUDE.md の「mise tools はワークスペース root の mise.toml に記録する」という要件を自動的に満たしている。
推測: `uv = "latest"` は再現性の観点ではバージョン固定の方が望ましいが、ユーザー指定がないので変更していない。

### 次の判断
`uv build` を実行する。

## Step 5: uv build によるビルド検証

### 目的
pyproject.toml が実際に sdist と wheel を生成できるか確認する。

### 背景
Step 2 で作成した pyproject.toml は未検証だった（Issue 1）。

### 事前仮説
hatchling の設定は妥当なのでビルドは成功する。

### 実行内容
- 変更・操作: `mise x -- uv build`
- 観察した出力:
  ```
  Downloading cpython-3.14.8-linux-aarch64-gnu (download) (28.9MiB)
  Building source distribution...
  Building wheel from source distribution...
  Successfully built dist/search_demo-1.0.0.tar.gz
  Successfully built dist/search_demo-1.0.0-py3-none-any.whl
  ```
- 参照した情報源: N/A

### 期待結果
`dist/` に sdist と wheel が生成されること。

### 実際の結果
両方とも生成成功。uv が CPython 3.14.8 を自動ダウンロードしてビルドに使った。

### 解釈
事実: pyproject.toml の `[build-system]` と `[project]` メタデータは有効で、hatchling がビルドを完遂できる。
事実: uv は Python 未設定の環境でも自前で CPython を取得するため、mise への Python 追加は不要だった。

### 次の判断
生成物の中身とコンソールスクリプトの動作を確認する。

## Step 6: wheel からの console script 実行確認

### 目的
`[project.scripts]` の `search-demo = "search_demo:main"` が実際に動くエントリポイントかを確認する。

### 背景
ビルド成功はメタデータの妥当性しか示さない。エントリポイントの解決は別途確認が必要。

### 事前仮説
`search_demo.py` がモジュールとして wheel ルートに入っていれば `search_demo:main` は解決できる。

### 実行内容
- 変更・操作:
  - `mise x -- uv run --no-project --with ./dist/search_demo-1.0.0-py3-none-any.whl search-demo "asyncio" -s wikipedia -n 2 -f text`
  - 続けて wheel の中身を確認しようと `mise x -- python -c ...` を実行（失敗）
- 観察した出力:
  - console script 実行は成功。`query: asyncio  (2 results)` に続き Wikipedia の「Async/await」「構造化された並行性」2 件が URL 付きで出力された。実際に外部 API へのアクセスも成功している。
  - `mise x -- python -c ...` は `mise ERROR No version is set for shim: python` で失敗。
- 参照した情報源: N/A

### 期待結果
`search-demo` コマンドが検索結果を出力すること。

### 実際の結果
期待どおり動作。ただし wheel 内容の確認コマンドは python シム未設定で失敗した（Issue 2）。

### 解釈
事実: エントリポイント指定は正しく、インストール後に `search-demo` コマンドとして利用できる。
事実: `mise x -- python` は使えないが `mise x -- uv run --no-project python` なら uv 管理の Python が使える。

### 次の判断
`uv run --no-project python` 経由で成果物の中身を確認する。

## Step 7: 成果物の内容確認と sdist の問題発見

### 目的
wheel と sdist に意図したファイルだけが含まれているか確認する。

### 背景
Decision 1 で「自動検出だと `.opencode` や `__pycache__` を拾う懸念」を理由に hatchling を選んだが、その懸念が解消されているかは未確認だった。

### 事前仮説
`only-include` を指定した wheel は clean。sdist も同様だろう。

### 実行内容
- 変更・操作:
  - `mise x -- uv run --no-project python -c "import zipfile;print('\n'.join(zipfile.ZipFile('dist/search_demo-1.0.0-py3-none-any.whl').namelist()))"`
  - `tar tzf dist/search_demo-1.0.0.tar.gz`
  - `cat mise.toml`
- 観察した出力:
  - wheel: `search_demo.py` と `search_demo-1.0.0.dist-info/` 配下 4 ファイル（METADATA, WHEEL, entry_points.txt, RECORD）のみ。clean。
  - sdist: `search_demo.py`, `README.md`, `pyproject.toml`, `PKG-INFO`, `mise.toml` に加えて **`.opencode/skill/public-api-search/SKILL.md` と `.tracecraft/` 配下の全 14 ファイル** が含まれていた。
  - `mise.toml` の内容は `[tools]` / `uv = "latest"`。
- 参照した情報源: N/A

### 期待結果
両方の成果物が clean であること。

### 実際の結果
wheel は clean だったが、sdist に作業ジャーナル（`.tracecraft/`）とエディタ設定（`.opencode/`）が混入していた。

### 解釈
事実: `[tool.hatch.build.targets.wheel]` の `only-include` は wheel ターゲットにしか効かない。sdist ターゲットには別途設定が必要。
推測: git リポジトリではない（環境情報で `Is a git repository: false`）ため、hatchling の VCS ベースの除外が効かず、ドットディレクトリまで取り込まれたと考えられる。

### 次の判断
sdist ターゲットにも明示的な include を追加して修正する。

## Step 8: sdist 設定の修正と再検証

### 目的
sdist から `.tracecraft/` と `.opencode/` を除外する。

### 背景
Step 7 で混入を確認した。ジャーナルや個人の作業記録を配布物に含めるのは不適切。

### 事前仮説
`[tool.hatch.build.targets.sdist]` に `only-include` を書けば絞り込める。

### 実行内容
- 変更・操作:
  - `/Users/kono/gitrepo/mcp-demo/search-demo/pyproject.toml` に以下を追記:
    ```toml
    [tool.hatch.build.targets.sdist]
    # 既定だと .tracecraft/ や .opencode/ まで含まれるので明示的に絞る
    only-include = ["search_demo.py", "README.md", "mise.toml"]
    ```
  - `rm -rf dist && mise x -- uv build` で再ビルド
  - sdist を `tar tzf`、wheel を zipfile で再確認
  - sdist から直接インストールして実行: `mise x -- uv run --no-project --with ./dist/search_demo-1.0.0.tar.gz search-demo "rust" -s github -n 1 -f text`
- 観察した出力:
  - ビルド成功（`Successfully built dist/search_demo-1.0.0.tar.gz` / `...-py3-none-any.whl`）
  - sdist: `mise.toml`, `search_demo.py`, `README.md`, `pyproject.toml`, `PKG-INFO` の 5 件のみ。`.tracecraft/` `.opencode/` は消えた。
  - wheel: 変わらず clean（`search_demo.py` + dist-info 4 件）
  - sdist からのインストール・実行も成功し、GitHub 検索結果が 1 件返った。
- 参照した情報源: N/A

### 期待結果
sdist が 5 ファイルに絞られ、かつ sdist からのビルド・実行が壊れないこと。

### 実際の結果
期待どおり。`pyproject.toml` と `PKG-INFO` は hatchling が自動で含めるため `only-include` に書かなくても入る。

### 解釈
事実: sdist→wheel のラウンドトリップでも console script が動作するので、`only-include` で削ったファイルはビルドに不要だった。
事実: ビルド検証は完了し、Issue 1 と Decision 2 の「未検証」状態は解消された。

### 次の判断
ユーザーに結果を報告する。
