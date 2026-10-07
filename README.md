# mcp-demo

opencode の **Skill** として書かれた機能を、**MCP サーバー**として作り直すとどうなるか —
その移植過程と判断理由をまるごと残したリファレンス実装。

同じ「公開 API 横断検索」という機能が、このリポジトリには 2 つの形で存在する。

| | Skill 版 | MCP 版 |
|---|---|---|
| 場所 | [`search-demo/`](search-demo/) | [`search-mcp/`](search-mcp/) |
| 実体 | 依存ゼロの Python CLI + `SKILL.md` | Streamable HTTP サーバー（コンテナ） |
| 届き方 | エージェントのコンテキストに**散文**として | `tools/list` の**スキーマと description** として |
| 利用者 | そのリポジトリを開いた opencode | ネットワークが届く全クライアント |

検索ロジックは二重管理していない。MCP 版はパス依存で `search-demo` を取り込んでいる。

---

## このリポジトリの主眼

**[`search-mcp/docs/skill-to-mcp.md`](search-mcp/docs/skill-to-mcp.md)**

SKILL.md の各記述が MCP のどこに落ちるのか、なぜ機械的な移植にならないのかを
実コード付きで整理したもの。核心は 1 行で言える。

> Skill の散文はすべて助言だが、MCP では「助言（description）」と「契約（schema）」に分かれる。
> 移植とは、各記述がどちらなのかを一つずつ決めていく作業である。

例えば SKILL.md の「GitHub 検索は約 10 req/min。`-n` を小さくする」という注意書きは、
ローカル実行の Skill では十分でも、共有サーバーでは `Field(ge=1, le=max_limit)` という
**強制力のある契約**にしなければならない。「クライアントが守ってくれる前提」は
ネットワーク越しでは成り立たないため。

他の型の Skill（ローカルファイルに依存する / 副作用がある / 添付ファイルを持つ）を
移植する場合の判断材料も §0 と §6〜§8 に含めた。

### 生成 AI に移植させる

この知識をエージェントに実行させるための作業指示書が
**[`PROMPT.md`](PROMPT.md)** にある。リポジトリごと渡して、こう指示する。

> `PROMPT.md` を読んで、その指示に従って `<Skill のパス>` を MCP サーバーに移植してください。

9 つの STEP、判断を要する箇所はすべて分岐表、コピーして使うテンプレート、
最後に完成チェックリスト、という構成にしてある。
30B 前後のモデルでも齟齬が出ないよう、判断を仰ぐのではなく表を引かせる形で書いた。

**実機で試した。** Qwen3.6 35B A3B（OpenAI 互換ゲートウェイ経由）に
別の Skill を移植させたところ、仕分け（STEP 3）で仕込んだ 4 つの罠のうち 3 つを正解し、
生成したコードは SDK の落とし穴 5 項目をすべて回避した。
散文の注意書き「一度に 5 都市程度まで」を `Field(le=5)` と関数内ガードの
**両方**に落とし、理由まで書いていた。ここが移植の最難関にあたる。

ただし**推論モデルでは thinking を切らないと失敗する。**
`reasoning_content` は画面に出ないまま出力枠と応答時間を食い潰すため、
ツール呼び出しの JSON が途中で壊れる。モデルの能力不足に見えるが設定の問題。
効いたのは `chat_template_kwargs: {"enable_thinking": false}` だけだった
（比較表は PROMPT.md の「実行環境の要件」）。

---

## ドキュメント

| | |
|---|---|
| [skill-to-mcp.md](search-mcp/docs/skill-to-mcp.md) | **Skill → MCP の移植知識**（このリポジトリの主眼） |
| [PROMPT.md](PROMPT.md) | **生成 AI に移植作業をさせるための作業指示書**。そのままエージェントに渡す |
| [deploy-openshift.md](search-mcp/docs/deploy-openshift.md) | ビルドと OpenShift への配備 |
| [clients.md](search-mcp/docs/clients.md) | VM 上の opencode / クラスタ内 Pod からの接続 |
| [security.md](search-mcp/docs/security.md) | 認証の設計、トークンのローテーション、OAuth 2.1 への移行 |
| [examples/README.md](search-mcp/examples/README.md) | **opencode から実際につないだ手順**と、動いた設定ファイル |
| [verification-plan.md](search-mcp/docs/verification-plan.md) | **まだ検証できていない項目を、どう潰すか**。手順と成功条件 |
| [search-mcp/README.md](search-mcp/README.md) | MCP サーバーの構成と環境変数 |

### 作業記録

`search-demo/.tracecraft/` に、この実装を作る過程をそのまま残してある。
成功した手順だけでなく、**失敗 12 件・判断 13 件・調査知見 18 件**を含む。

| | |
|---|---|
| [final-guide.md](search-demo/.tracecraft/2026-10-06_13f2e00f_mcp-http-openshift/final-guide.md) | 再現可能な手順書 |
| [troubleshooting.md](search-demo/.tracecraft/2026-10-06_13f2e00f_mcp-http-openshift/troubleshooting.md) | 詰まった箇所と切り分け過程 |
| [decisions.md](search-demo/.tracecraft/2026-10-06_13f2e00f_mcp-http-openshift/decisions.md) | 設計判断とトレードオフ |
| [findings.md](search-demo/.tracecraft/2026-10-06_13f2e00f_mcp-http-openshift/findings.md) | 調査して判明した事実 |
| [retrospective.md](search-demo/.tracecraft/2026-10-06_13f2e00f_mcp-http-openshift/retrospective.md) | 振り返り |

---

## すぐ動かす

```bash
cd search-mcp
MCP_AUTH_TOKENS=dev-token uv run search-mcp

# 別ターミナルから
MCP_URL=http://127.0.0.1:8080/mcp MCP_TOKEN=dev-token \
  uv run python examples/smoke_client.py "rust tui"
```

CLI 版だけ試すなら依存は要らない。

```bash
python3 search-demo/search_demo.py "rust tui" -s github -n 3
```

### opencode からつなぐ

実際に接続できた設定が
[`search-mcp/examples/opencode.local.json`](search-mcp/examples/opencode.local.json) にある。
コンテナで起動して opencode から使うまでの手順は
[`search-mcp/examples/README.md`](search-mcp/examples/README.md)。

つながると、こう動く。

```
⚙ search_search {"query":"kubernetes operator","sources":["github"],"limit":3}
1. prometheus-operator/prometheus-operator
2. cloudnative-pg/cloudnative-pg
3. chaos-mesh/chaos-mesh
```

**注意: トークンが違ってもエラーは出ない。** opencode は MCP の登録に失敗しても
黙って続行し、`WebFetch` など別の手段で回答を作る。成功と区別がつかない。
まず「利用可能な MCP ツールを列挙して」と聞いて `search_search` が出るか確かめること
（ツール名にはサーバー名の接頭辞が付く）。詳細は
[clients.md](search-mcp/docs/clients.md) §1.7〜1.8。

---

## 構成

```
mcp-demo/
├── PROMPT.md                  生成 AI に移植作業をさせるための指示書
├── Containerfile              UBI9 マルチステージ（build context はリポジトリルート）
├── search-demo/               Skill 版。標準ライブラリのみ
│   ├── search_demo.py
│   ├── tests/                 38 件（urlopen を差し替え、ネットワークに出ない）
│   ├── .opencode/skill/public-api-search/SKILL.md
│   └── .tracecraft/           作業記録
└── search-mcp/                MCP 版
    ├── src/search_mcp/        settings / server / auth / app
    ├── docs/                  移植知識・配備・接続・セキュリティ
    ├── examples/              opencode.local.json（検証済み）/ opencode.json
    │                          smoke_client.py / agent-pod.yaml / README.md
    ├── deploy/openshift/      kustomize 一式（12 リソース）
    └── tests/                 単体 38 件 + e2e/run-e2e.sh 36 チェック
```

---

## 検証状況

### 自動テスト

| | |
|---|---|
| 単体テスト 76 件 | ✅ `cd search-mcp && uv run pytest -q`（38 件）<br>✅ `cd search-demo && uv run --extra dev pytest -q`（38 件） |
| カバレッジ | ✅ `search_demo.py` 99% / `search_mcp` 94%（残りは uvicorn 起動部で E2E 側） |
| **E2E 36 件** | ✅ `search-mcp/tests/e2e/run-e2e.sh` |

### コンテナ・マニフェスト

| | |
|---|---|
| コンテナ起動 | ✅ 任意 UID（1000670000）/ read-only rootfs / cap-drop ALL |
| 本番設定の経路 | ✅ `MCP_JSON_RESPONSE=true` と DNS rebinding 保護を実際に通した |
| Deployment の probe | ✅ `podman kube play` で healthy になることを確認 |
| 実 API 疎通 | ✅ コンテナ内から GitHub 検索が返る |
| kustomize レンダリング | ✅ 警告なしで 12 リソース |
| **マニフェストの API スキーマ検証** | ❌ **未実施**（クラスタが要る） |
| Route / NetworkPolicy / HPA / PDB | ❌ podman に概念が無い |

### 実クライアントからの接続（手動検証・CI では回らない）

opencode 1.18.34 + Qwen3.6 35B A3B から、2 通りの構成で接続した。

| | |
|---|---|
| ローカルプロセス（保護 無効） | ✅ 接続・ツール呼び出し |
| **コンテナ（保護 有効・SCC 相当の制約つき）** | ✅ 接続・ツール呼び出し |
| **スキーマ上限がクライアント経由でも効く** | ✅ `limit=100` が Pydantic に弾かれ、エラーがモデルまで届いた |
| 許可外 Host の拒否 | ✅ `421 Misdirected Request` |
| `/healthz` が Host 検証を受けない | ✅ probe 用に素通り |
| **Route 経由（TLS + 外部ホスト名）** | ❌ **未検証** |
| クラスタ内 Pod の agent framework | ❌ 未検証 |

3 行目がこのリポジトリの主張の裏付けにあたる。
「description はお願い、スキーマは強制」が実クライアント越しに成立している。

### 生成 AI による移植（PROMPT.md）

| | |
|---|---|
| STEP 3（仕分け） | ✅ 仕込んだ 4 つの罠のうち 3 つ正解 |
| STEP 4〜5（コード生成） | ✅ SDK の落とし穴 5 項目をすべて回避 |
| STEP 6〜9 | ❌ 未実行 |
| 生成コードの起動・テスト | ❌ 未実施（構文検証もしていない） |

1 回の試行であり、再現性は未確認。

---

### ❌ をどう潰すか

上の ❌ はすべて、**手順を
[verification-plan.md](search-mcp/docs/verification-plan.md) に書いてある。**
項目ごとに「どう確かめるか」「何が返れば成功か」「失敗したら何を疑うか」を
まとめた。所要時間と依存関係（どれを先にやるべきか）も付けた。

クラスタがあるなら、まずこれだけ実行すること。1 分で終わる。

```bash
oc apply --dry-run=server -k search-mcp/deploy/openshift/
```

`podman kube play` は独自パーサなのでフィールド名の typo を見逃す。
クラスタが無い環境で作ったため、マニフェストの**フィールド名の typo や
apiVersion の誤りは検出できていない**。

---

E2E は DooD 環境でも動くよう、専用ネットワーク上のクライアントコンテナから
curl する構成にしてある（publish したポートにはこのプロセスから到達できないため）。
同じ理由で、opencode からの接続検証ではコンテナ IP を直接指定している。

## 要件

Python 3.12 / uv。MCP SDK は 2.x 系（`mcp>=2.3,<3`）。
1.x とは API 非互換（`FastMCP` → `MCPServer`）。

ツールは `mise.toml` に記載してある（`mise install` で揃う）。

| | |
|---|---|
| python 3.12 / uv | 本体とテスト |
| podman | イメージのビルドと動作確認（DooD 経由） |
| kubectl | kustomize build |
| opencode | MCP クライアントとしての接続検証 |

## ライセンス

MIT License — [LICENSE](LICENSE)
