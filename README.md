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

---

## ドキュメント

| | |
|---|---|
| [skill-to-mcp.md](search-mcp/docs/skill-to-mcp.md) | **Skill → MCP の移植知識**（このリポジトリの主眼） |
| [deploy-openshift.md](search-mcp/docs/deploy-openshift.md) | ビルドと OpenShift への配備 |
| [clients.md](search-mcp/docs/clients.md) | VM 上の opencode / クラスタ内 Pod からの接続 |
| [security.md](search-mcp/docs/security.md) | 認証の設計、トークンのローテーション、OAuth 2.1 への移行 |
| [search-mcp/README.md](search-mcp/README.md) | MCP サーバーの構成と環境変数 |

### 作業記録

`search-demo/.tracecraft/` に、この実装を作る過程をそのまま残してある。
成功した手順だけでなく、**失敗 9 件・判断 10 件・調査知見 8 件**を含む。

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

---

## 構成

```
mcp-demo/
├── Containerfile              UBI9 マルチステージ（build context はリポジトリルート）
├── search-demo/               Skill 版。標準ライブラリのみ
│   ├── search_demo.py
│   ├── .opencode/skill/public-api-search/SKILL.md
│   └── .tracecraft/           作業記録
└── search-mcp/                MCP 版
    ├── src/search_mcp/        settings / server / auth / app
    ├── docs/                  移植知識・配備・接続・セキュリティ
    ├── examples/              smoke_client.py / opencode.json / agent-pod.yaml
    ├── deploy/openshift/      kustomize 一式（12 リソース）
    └── tests/                 9 件
```

---

## 検証状況

| | |
|---|---|
| テスト 9 件 | ✅ `uv run pytest -q` |
| 実 API 疎通 | ✅ 4 ソース混在で結果取得 |
| コンテナ起動 | ✅ 任意 UID（1000670000）でも起動 |
| kustomize レンダリング | ✅ 警告なしで 12 リソース |
| **マニフェストの API スキーマ検証** | ❌ **未実施** |

クラスタが無い環境で作ったため、マニフェストはレンダリングが通ることしか
確認できていない。フィールド名の typo や apiVersion の誤りは検出できていないので、
配備前に実クラスタで確認すること。

```bash
oc apply --dry-run=server -k search-mcp/deploy/openshift/
```

## 要件

Python 3.12 / uv（`mise.toml` に記載）。MCP SDK は 2.x 系（`mcp>=2.3,<3`）。
1.x とは API 非互換（`FastMCP` → `MCPServer`）。
