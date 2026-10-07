# Decisions

> 作業タイトル: search-demo を MCP Streamable HTTP サーバー化し OpenShift に配備可能にする
> 開始日時: 2026-10-06

---

## Decision: 認証は共有 Bearer トークン（ASGI ミドルウェア）にする

### 背景
MCP サーバーを Route で外部公開するため、認証が要る。
MCP 仕様の認可は OAuth 2.1 Resource Server を前提にしている。

### 選択肢
1. 共有 Bearer トークン（Secret から環境変数）
2. 認証なし（NetworkPolicy + Service のみ）
3. OAuth 2.1 Resource Server（SDK の `AuthSettings` + `TokenVerifier`）

### 採用した案
1（AskUserQuestion でユーザーが選択）。さらに実装方式として、
SDK の `AuthSettings` を有効にせず、独自の ASGI ミドルウェア（`src/search_mcp/auth.py`）にした。

### 採用理由
- 利用者は VM 上の opencode と Pod 内の agent framework の 2 種類のみで、
  どちらも人間の対話的ログインを挟まない。設定ファイル / Secret から静的資格情報を読む形
- `AuthSettings` を有効にすると RFC 9728 の `/.well-known/oauth-protected-resource` が生え、
  クライアントはそこから Authorization Server を探す。実在する IdP が無いと
  「クライアントが認可フローを始めようとして失敗する」という分かりにくい壊れ方になる
- ミドルウェアなら `401 + WWW-Authenticate: Bearer` だけを返せる

### 採用しなかった案と理由
- **2（認証なし）**: Route で外部公開する構成なので不可。
  ただしコードとしては `MCP_AUTH_TOKENS` 未設定時に警告ログを出して動く形にしてある
  （クラスタ内限定のデモ用）
- **3（OAuth）**: IdP が無い。導入段では構成が重すぎる

### トレードオフ
- 得たもの: 設定 1 行で繋がる。クライアント側の実装が不要
- 失ったもの: 誰が呼んだか分からない（ログは IP のみ）。失効の粒度が粗い。自動ローテーションが無い
- 緩和策: `MCP_AUTH_TOKENS` をカンマ区切りの複数トークン対応にし、
  クライアントごとに別トークンを配れるようにした。片方だけ失効できる
- 注意点: 環境変数で読むため、Secret 更新後は `oc rollout restart` が必須

### 見直し条件
- IdP（Keycloak / OpenShift OAuth）が利用可能になったとき
- 「誰が何を検索したか」の監査が要求されたとき
- クライアントが 3 種類以上に増え、トークン管理が破綻したとき

移行手順は `search-mcp/docs/security.md` に具体的なコード付きで記載した。

---

## Decision: search-demo はパス依存で再利用し、コードを複製しない

### 背景
MCP サーバーは `search_demo.run_search` の検索ロジックを使う。

### 選択肢
1. `search-mcp/` を新設し、`[tool.uv.sources]` のパス依存で `search-demo` を取り込む
2. `search-demo/` 内に MCP サーバーのエントリポイントを同居させる
3. `search-mcp/` に検索ロジックをコピーして完全独立

### 採用した案
1（AskUserQuestion でユーザーが選択）。

### 採用理由
- 検索ロジックの二重管理を避けられる
- CLI（`search-demo`）とサーバー（`search-mcp`）の責務が分かれ、
  依存（`mcp`, `uvicorn`）が CLI 側に漏れない。`search-demo` は依存ゼロを保てる
- `search-demo` がリファレンス実装として残る（ユーザーの意図）

### 採用しなかった案と理由
- **2（同居）**: `search-demo` の「依存ゼロ・標準ライブラリのみ」という設計上の売りが壊れる
- **3（コピー）**: 二重管理になる。4 ソースの API 仕様変更時に両方直す必要がある

### トレードオフ
- 得たもの: ロジックの単一ソース
- 失ったもの: **コンテナの build context がリポジトリルートになる**。
  `search-mcp/` だけを context にするとパス依存が解決できない。
  `Containerfile` をリポジトリルートに置き、README / deploy ドキュメントに明記した
- 残る問題: **ガイダンスの文面（SKILL.md の「使い分けの指針」と `SOURCE_GUIDE`）は二重管理のまま。**
  これは 1 対 1 の対応ではないため自動同期していない。
  `docs/skill-to-mcp.md` §5 に明記し、テストで description の内容を文字列検査することで
  ずれの一部を検知できるようにした

### 見直し条件
- `search-demo` の CLI が不要になったら、ロジックを `search-mcp` に取り込んで 1 パッケージにする
- 逆に `search-demo` を PyPI に公開するなら、パス依存をバージョン依存に変える

---

## Decision: stateless_http を既定で有効にする

### 背景
OpenShift で replicas 2 以上、HPA で最大 6 まで増やす構成にしたい。

### 選択肢
1. `stateless_http=True`（セッションをプロセスに持たない）
2. `stateless_http=False` + Route の cookie による sticky session

### 採用した案
1。`MCP_STATELESS_HTTP` の既定を `true` にした。

### 採用理由
- Streamable HTTP のセッション ID はプロセスメモリに持たれる。
  stateful のまま replica を増やすと 2 回目のリクエストが別 Pod に飛び、セッション未知エラーになる
- stateless なら各リクエストが独立し、ロードバランスも HPA も素直に効く
- Route 側で cookie 固定を設定する必要がなくなる（`disable_cookies: "true"` + roundrobin にできた）

### 採用しなかった案と理由
2 は sticky session の設定ミスが起きやすく、Pod 入れ替え時にセッションが切れる。
公開しているツールは 2 つとも単発の read なので、セッションを持つ利点が無い。

### トレードオフ
- 得たもの: 水平スケールが素直に効く。Route の設定が単純になる
- 失ったもの: **サーバー発の通知（進捗通知・リソース更新通知）が使えない**。
  長時間かかるツールを追加する場合は制約になる

### 見直し条件
- 時間のかかるツール（大量検索、クロール等）を追加して進捗通知が必要になったとき。
  その場合は `MCP_STATELESS_HTTP=false` にし、Route で cookie 固定を有効化し、
  `haproxy.router.openshift.io/timeout` を見直す

---

## Decision: ConfigMap では json_response を true にする

### 背景
Streamable HTTP は SSE ストリームか単発 JSON のどちらでも応答できる。

### 選択肢
1. SSE（SDK の既定）
2. 単発 JSON

### 採用した案
コードの既定は 1（SDK に合わせる）だが、**OpenShift 配備用 ConfigMap では 2**
（`MCP_JSON_RESPONSE: "true"`）にした。

### 採用理由
SSE は HAProxy（OpenShift Router）のバッファリングや idle timeout の影響を受けやすい。
長時間ストリームを返さない以上、単発 JSON のほうがトラブルが少ない。

### 採用しなかった案と理由
SSE を既定にすると、Route 経由で「途中で切れる」系の切り分けにくい問題を抱え込む。

### トレードオフ
- 得たもの: Route 配下での安定性
- 失ったもの: ストリーミング応答。進捗通知と同様、現状のツールでは不要
- 注意点: コードの既定（false）と ConfigMap の値（true）が食い違っている。
  ローカル実行と OpenShift で挙動が変わるので、両方にコメントで理由を残した

### 見直し条件
stateless_http を無効化するタイミングと同じ。進捗通知を使うなら SSE に戻す。

---

## Decision: テストは in-process ASGI ではなく実 uvicorn で行う

### 背景
`httpx.ASGITransport` でのテストが `RuntimeError: Task group is not initialized` で失敗した
（troubleshooting Issue 4）。

### 選択肢
1. `asgi-lifespan` 等で lifespan だけ回して in-process のまま続ける
2. 動的ポートで uvicorn を実際に起動する
3. `MCPServer` を直接呼び、HTTP 層をスキップする

### 採用した案
2。`tests/test_server.py` の `_serve()` で動的ポートに uvicorn を立てる。

### 採用理由
- 本番と同じ経路（実 HTTP・実 uvicorn・実ミドルウェア）を通せる
- 認証ミドルウェアの 401 と `WWW-Authenticate` ヘッダを HTTP レベルで検証できる
- health エンドポイントが認証を素通りすることも同じ経路で確認できる

### 採用しなかった案と理由
- **1**: 依存が増えるうえ、認証ミドルウェアの検証は結局 HTTP 経由になる
- **3**: 「MCP プロトコル越しに description とスキーマが届くか」が検証対象なので、
  HTTP 層をスキップすると主目的を外す

### トレードオフ
- 得たもの: 実経路での検証。9 件のテストが認証・スキーマ・structured output を網羅
- 失ったもの: 実行時間（2.66 秒）。テストごとにサーバーを起動するため in-process より遅い
- 注意点: ポートは `bind(("127.0.0.1", 0))` で OS に選ばせているので衝突しない

### 見直し条件
テスト数が増えて実行時間が問題になったら、サーバーを session スコープの fixture にして
設定違いのものだけ個別に立てる。

---

## Decision: マニフェストは kustomize で構成し、Secret は含めない

### 背景
OpenShift への配備手段を決める必要がある。

### 選択肢
1. 素の YAML を `oc apply -f` で順番に適用
2. kustomize（`oc apply -k`）
3. Helm チャート
4. OpenShift Template

### 採用した案
2。`deploy/openshift/kustomization.yaml` 一式。

### 採用理由
- `oc` に組み込まれており追加ツールが要らない（`oc apply -k`）
- イメージ参照の置換（`images:`）が宣言的に書ける
- overlay で環境差分（dev / prod）を足せる余地がある
- Argo CD などの GitOps ツールがそのまま読める

### 採用しなかった案と理由
- **1**: 適用順序とイメージ名の書き換えを手でやることになる
- **3（Helm）**: テンプレート言語の学習コストに見合わない規模。
  配備先が OpenShift に限定されているので値の抽象化の利得が小さい
- **4（Template）**: OpenShift 固有で、GitOps ツールとの相性が kustomize に劣る

### トレードオフ
- 得たもの: 追加ツール不要、GitOps 互換
- 失ったもの: 値の抽象化。`MCP_ALLOWED_HOSTS` の Route ホスト名は
  **ユーザーが手で書き換える前提**になった。これは `docs/deploy-openshift.md` に手順として明記した

### Secret を kustomization に含めない判断
`secret.example.yaml` を作ったうえで `kustomization.yaml` の `resources` から外した。
トークンをリポジトリに置かないため。`oc create secret generic` での作成手順を
README と deploy ドキュメントに書いた。

### 見直し条件
- 環境が 3 つ以上に増えたら overlay を切る
- Sealed Secrets / External Secrets Operator が使えるなら、Secret も宣言的に管理する

---

## Decision: ツールを 2 つに分け、詳細ガイダンスを list_search_sources に逃がす

### 背景
SKILL.md の「使い分けの指針」（5 項目）と「注意」（3 項目）を
MCP のどこに載せるかを決める必要があった。

### 選択肢
1. `search` ツール 1 つにして、description に全部書く
2. `search` + `list_search_sources` の 2 ツールに分け、要点を description、詳細を後者に逃がす
3. ソースごとにツールを分ける（`search_github`, `search_wikipedia`, ...）

### 採用した案
2。

### 採用理由
- ツールの description は接続中つねにコンテキストを消費する。
  全ソースの API 名・制約まで書くと肥大する
- 「どのソースを選ぶか」の要点（`use_when`）だけ description に置き、
  詳細（`api`, `caveats`）は必要なときだけ呼べるツールに逃がした
- Skill の「必要なときに読み込まれる」性質を、ツール分割で再現している
- 文面の単一ソースとして `SOURCE_GUIDE` dict を置き、2 か所から参照している

### 採用しなかった案と理由
- **1**: description が長くなりすぎる。他の MCP サーバーと併用されることを考えると、
  1 ツールのコンテキスト占有は小さいほうがよい
- **3（ソースごとに分割）**: ツールが 4 つに増え、
  `search_demo.run_search` の並列取得という利点（全ソース同時検索）が使えなくなる。
  「当たりが付かないときは全ソース」という SKILL.md の指針も表現できない

### トレードオフ
- 得たもの: description の肥大回避、ガイダンス文面の単一ソース化
- 失ったもの: モデルが `list_search_sources` を呼ばない可能性。
  description の `use_when` だけで判断するケースが多くなる想定。
  そのため `use_when` のほうを description に置いた（優先度の高い情報を常時見える側に）

### 見直し条件
運用して `list_search_sources` が一度も呼ばれないなら、統合して description に吸収する。
逆に description が長すぎてツール選択の精度が落ちるなら、さらに逃がす。

---

## Decision: CLI のオプションを全部は移植しない

### 背景
SKILL.md のオプション表には `--source` / `--limit` / `--lang` / `--format` があった。

### 選択肢
1. 全オプションを MCP ツールの引数にそのまま移植
2. CLI の UI 都合で存在するものは落とす

### 採用した案
2。具体的には:
- `--format` を落とした（structured output があるので出力形式の選択は不要）
- `-s all` という enum 値を落とした（`sources=None` で表現）
- 短縮形（`-s` / `-n`）を落とした

### 採用理由
- `--format text` は人間が CLI 出力を読むための形式。MCP クライアントは構造化データを受け取って自前で整形する
- `all` を enum に混ぜると `["all", "github"]` のような曖昧な入力が
  スキーマ上は valid になり、モデルに誤った自由度を与える。型（`| None`）で表現できる意味を enum に逃がさない
- 短縮形はタイプ数を減らす CLI の都合

### 採用しなかった案と理由
1 は「移植漏れが無い」という安心感はあるが、
モデルに見せる選択肢が増えるほど誤用の余地が増える。

### トレードオフ
- 得たもの: スキーマが小さく曖昧さがない
- 失ったもの: CLI との引数の完全な対応。CLI に慣れた人が MCP 版を見ると引数が違う。
  この差分と理由は `docs/skill-to-mcp.md` §3「落としたもの・足したもの」に明記した

### 見直し条件
なし。CLI と MCP は別の UI であり、同一にする理由がない。

---

## Decision: limit の上限をスキーマで強制する

### 背景
SKILL.md には「GitHub 検索は約 10 req/min。連続実行は避け、`-n` を小さくする」という
**注意書き（散文）** があった。

### 選択肢
1. 同じ内容を description に書くだけ（Skill と同じ扱い）
2. `Field(ge=1, le=MAX)` でスキーマに書き、サーバー側でもクランプする

### 採用した案
2。`MCP_MAX_LIMIT`（既定 20）で設定可能にし、
`Annotated[int | None, Field(ge=1, le=settings.max_limit)]` として入力スキーマに載せた。
さらに実行前に `max(1, min(limit, max_limit))` でクランプしている。

### 採用理由
Skill 版はローカル実行なので、暴走しても自分のレート制限を食うだけだった。
MCP 版は**共有サーバー**で、1 クライアントの `limit=1000` が全クライアントに影響する。
「クライアントが注意書きを守ってくれる前提」はネットワーク越しでは成り立たない。

### 採用しなかった案と理由
1 では強制力がない。description はモデルへの助言にすぎない。

### トレードオフ
- 得たもの: 外部 API のレート制限を共有サーバーとして守れる
- 失ったもの: **`server.py` で PEP 563（`from __future__ import annotations`）が使えなくなった。**
  上限値を環境変数から取るため、アノテーション内でクロージャ変数を参照する必要があり、
  文字列化されると SDK の eval が解決できない（troubleshooting Issue 3）
- 代替案: 上限をモジュールレベル定数にすれば PEP 563 を使えるが、環境ごとの可変性を失う。
  可変性を優先した

### 見直し条件
上限を環境ごとに変える必要がなくなったら、定数化して PEP 563 を復活させてよい。

---

## Decision: マニフェストの API 検証をスキップし、未検証であることを明示する

### 背景
`kubectl apply --dry-run=client` がクラスタ接続を要求して実行できなかった
（troubleshooting Issue 9）。

### 選択肢
1. `kubeconform` 等のオフライン検証ツールを導入する
2. 検証をスキップし、未検証であることを明示する
3. ローカルに kind / minikube を立てる

### 採用した案
2。`kubectl kustomize` によるレンダリング検証（12 リソース、警告なし）までで止め、
最終報告と troubleshooting に「API スキーマ検証は未実施」と明記した。

### 採用理由
- OpenShift 固有リソース（Route, BuildConfig, ImageStream）は
  Kubernetes の組み込みスキーマに無く、オフライン検証には CRD スキーマの取得が要る
- 実クラスタでの `oc apply --dry-run=server` が最も確実で、ユーザーは実環境を持っている
- 検証できていないことを隠すより、明示して配備前の確認手順として渡すほうがよい

### 採用しなかった案と理由
- **1（kubeconform）**: OpenShift CRD スキーマの取得にネットワークが要り、
  バージョン整合も取れない。得られる保証に対して手間が大きい
- **3（kind）**: OpenShift 固有リソースは kind には存在しない。Route の検証ができない

### トレードオフ
- 得たもの: 時間。レンダリング検証で YAML 構文とリソース構成は確認できている
- 失ったもの: フィールド名 typo や apiVersion 誤りの検出。**これは残存リスク**
- 緩和策: 配備手順の最初に `oc apply --dry-run=server -k ...` を置くことを推奨として伝えた

### 見直し条件
クラスタにアクセスできるようになったら即座に `oc apply --dry-run=server` を実行する。

---

## Decision: pytest を search-demo の dev extra に置き、実行時依存ゼロを維持する

### 背景
`search_demo.py` は「エージェントが `pip install` を挟まずに即実行できる」ことを
売りにして依存ゼロで書いてある。一方で単体テストを入れるには pytest が要る。

### 選択肢
1. `[project.optional-dependencies] dev = ["pytest>=8"]` に置く
2. `dependencies` に直接入れる
3. 標準ライブラリの `unittest` で書き、依存を一切増やさない
4. テストを `search-mcp` 側に置き、`search-demo` のパッケージ構成を触らない

### 採用した案
1（dev extra）。

### 採用理由
- `dependencies = []` が保たれるので、`python3 search_demo.py` は
  今までどおり何もインストールせずに動く。README の主張が崩れない。
- `uv run --extra dev pytest` という 1 行でテストできる。
- `search-mcp` 側は既に pytest を使っており、書き方を揃えられる。

### 採用しなかった案と理由
- 2: 実行時に不要なものを必須依存にすると、売りである「即実行」が崩れる。
- 3: `unittest` でも書けるが、`parametrize` が無いので
  「4 ソース × レスポンス形のバリエーション」が冗長になる。
  テストの読みやすさはリファレンス実装としての価値に直結するため避けた。
- 4: 検索ロジックのテストが別パッケージにあると、
  `search_demo.py` だけを取り出して使う人がテストを見つけられない。
  また `search-demo` を単体で CI に掛けられなくなる。

### トレードオフ
`search-demo` に `.venv` と `uv.lock` が増える（`.gitignore` 済み）。
テストを実行する人にだけ uv / pytest が必要になり、
「標準ライブラリだけで完結」という性質はテスト実行時には成り立たない。

### 見直し条件
`search-demo` を sdist / wheel として外部に配る必要が出た場合。
その際は `[tool.hatch.build.targets.sdist]` に `tests/` を含めるか判断する
（現状は `search_demo.py` / `README.md` / `mise.toml` のみに絞っている）。

---

## Decision: 生成 AI 向けの指示書を skill-to-mcp.md とは別ファイルにする

### 背景
ユーザーから「生成 AI にこのマニュアルを見ながら Skill → MCP の作業を
進めてもらうための Prompt.md が欲しい。相手は qwen3.6-35B 程度なので
齟齬なく伝わる形で」という要求が出た。

既存の `skill-to-mcp.md` は人間のエンジニア向けで、
「〜を検討する」「〜が望ましい」という**判断を委ねる書き方**をしている。
30B 級のモデルではこの曖昧さが工程の脱落や推測での穴埋めにつながる。

### 選択肢
1. `PROMPT.md` を別ファイルとして新設し、`skill-to-mcp.md` を参照させる
2. `skill-to-mcp.md` 自体を手順書の形に書き換える
3. `skill-to-mcp.md` の末尾に「AI 向け手順」節を足す
4. Skill（`.opencode/skill/` 配下）として配置する

### 採用した案
1（別ファイル `/Users/kono/gitrepo/mcp-demo/PROMPT.md`）。

### 採用理由
- **読み手が違うと最適な書き方が違う。** 人間向けには「なぜそうするか」が要るが、
  小型モデル向けには「何をするか」を曖昧さなく並べる方が効く。
  同じ文書で両立させると、どちらにとっても読みにくくなる。
- `skill-to-mcp.md` は判断材料のリファレンスとして残り、
  `PROMPT.md` から §番号で参照できる。役割分担が明確になる。
- ファイル名が `PROMPT.md` なら、人間が「これをエージェントに渡せばいい」と
  即座に分かる。リポジトリルートに置けば発見性も高い。

### 採用しなかった案と理由
- 2: 「なぜその判断なのか」を失う。このリポジトリの主眼は移植知識の記録であり、
  手順書に圧縮すると、射程外のケースに遭遇した人が応用できなくなる。
- 3: 1 ファイルが 1100 行規模になる。小型モデルは長文脈の前半を忘れやすく、
  「本編を読んでから手順に入る」構成はむしろ不利。
- 4: Skill にすると opencode / Claude Code に閉じる。
  ローカルの qwen を含む任意のクライアントに渡せる素のマークダウンが要件に合う。

### トレードオフ
`skill-to-mcp.md` と `PROMPT.md` で内容が二重になる箇所がある
（SDK の落とし穴、エラーの返し分けなど）。片方だけ直すとずれる。
PROMPT.md 側は節番号で参照する形を多用して重複を抑えたが、
完全には避けられていない。

### 見直し条件
- 実際に小型モデルで走らせて、脱落する STEP が判明した場合
- MCP SDK が 3.x になり、落とし穴の一覧が変わった場合
  （PROMPT.md の STEP 5 冒頭の表と完成チェックリストの 2 箇所を直す必要がある）
