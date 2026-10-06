# セキュリティ設計と、OAuth へ移るときの手順

## 現状の構成

| 層 | 対策 |
|---|---|
| 認証 | 共有 Bearer トークン（Secret から環境変数 `MCP_AUTH_TOKENS`） |
| 転送 | Route で edge TLS 終端。`insecureEdgeTerminationPolicy: Redirect` で HTTP は 301 |
| ネットワーク | NetworkPolicy で既定全拒否。Router / ラベル付き namespace / 監視のみ許可 |
| Web 攻撃 | DNS rebinding 保護（`MCP_ALLOWED_HOSTS` / `MCP_ALLOWED_ORIGINS`） |
| 実行 | 非 root、`readOnlyRootFilesystem`、全 capability drop、`seccompProfile: RuntimeDefault` |
| 乱用 | `MCP_MAX_LIMIT` で 1 リクエストあたりの外部 API 呼び出し回数を抑制 |

## なぜ OAuth ではなく共有トークンなのか

MCP 仕様の認可は OAuth 2.1 Resource Server を前提にしている。
SDK の `AuthSettings` を有効にすると、サーバーは RFC 9728 の
`/.well-known/oauth-protected-resource` を生やし、クライアントはそこから
Authorization Server を探して認可フローを始める。

このデモの利用者は 2 種類しかなく、どちらも**人間の対話的ログインを挟まない**:

- VM 上の opencode（設定ファイルに書いた資格情報で動く）
- Pod 内の agent framework（Secret から読む）

この形に OAuth を被せると、discovery の先に実在する IdP が必要になり、
無いと「クライアントが認可フローを始めようとして失敗する」という
分かりにくい壊れ方をする。そのため discovery を生やさず、
`401 + WWW-Authenticate: Bearer` だけを返す ASGI ミドルウェア
（`src/search_mcp/auth.py`）にしてある。

### 共有トークン運用の限界

- **誰が呼んだか分からない。** ログに残るのは IP だけ
- **失効の粒度が粗い。** トークン単位でしか切れない
- **自動ローテーションが無い。** 手で Secret を更新して Pod を再起動する

カンマ区切りで複数トークンを設定できるようにしてあるのは、この粗さを
少し緩和するため（クライアントごとに別トークンを配れば、片方だけ失効できる）。

```bash
oc create secret generic search-mcp-auth \
  --from-literal=tokens="<vm-opencode-token>,<agent-pod-token>"
```

### ローテーション手順

無停止でやるには、新旧を併記する期間を作る。

```bash
# 1. 新トークンを追加（旧も残す）
oc patch secret search-mcp-auth -n search-mcp --type=merge \
  -p "{\"stringData\":{\"tokens\":\"<old-token>,<new-token>\"}}"
oc rollout restart deploy/search-mcp -n search-mcp

# 2. 全クライアントを新トークンに切り替える

# 3. 旧トークンを外す
oc patch secret search-mcp-auth -n search-mcp --type=merge \
  -p "{\"stringData\":{\"tokens\":\"<new-token>\"}}"
oc rollout restart deploy/search-mcp -n search-mcp
```

環境変数で読んでいるため、Secret を更新しただけでは反映されない
（`envFrom`/`secretKeyRef` はコンテナ起動時に解決される）。
**必ず rollout restart が要る。**

## OAuth 2.1 へ移行する場合

IdP（Keycloak / Red Hat build of Keycloak、OpenShift OAuth など）が入ったら、
次の 3 点を変えるだけで移行できる。

**1. ミドルウェアを外す。** `src/search_mcp/app.py` の

```python
if settings.auth_tokens:
    app = BearerTokenMiddleware(app, tokens=settings.auth_tokens)
```

を削除する。

**2. `TokenVerifier` を実装してサーバーに渡す。**

```python
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings

class JWTVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        claims = decode_and_validate(token)  # IdP の JWKS で署名・aud・exp を検証
        if claims is None:
            return None
        return AccessToken(
            token=token,
            client_id=claims["azp"],
            scopes=claims.get("scope", "").split(),
            subject=claims["sub"],
            resource=claims.get("aud"),
        )

mcp = MCPServer(
    name="search-mcp",
    token_verifier=JWTVerifier(),
    auth=AuthSettings(
        issuer_url="https://keycloak.example.com/realms/mcp",
        resource_server_url="https://search-mcp.apps.example.com",
        required_scopes=["search:read"],
        validate_token_resource=True,  # RFC 8707。他サービス向けトークンの流用を防ぐ
    ),
)
```

`validate_token_resource=True` にすると、`AccessToken.resource` が
`resource_server_url` と一致しないトークンを拒否する。これを入れないと、
同じ IdP が発行した別サービス用のトークンでこのサーバーを呼べてしまう。

**3. クライアント設定を変える。** 静的ヘッダをやめ、
各クライアントを OAuth クライアントとして登録する。
opencode / agent framework とも MCP の認可フローに対応しているので、
サーバー側が discovery を返せば自動で辿る。

移行後は `MCP_AUTH_TOKENS` と `auth.py` は不要になる。

## 残っているリスク

- **外向き通信が制限されていない。** egress NetworkPolicy を書いていないので、
  Pod は任意の外部ホストに出られる。検索先 API のドメインに限定したい場合は
  egress ルール（または EgressFirewall）を追加する
- **レート制限がサーバー側に無い。** `MCP_MAX_LIMIT` は 1 リクエストあたりの
  上限で、リクエスト頻度は制限していない。クライアントが連打すると
  GitHub / Stack Exchange のレート制限に当たり、全クライアントが影響を受ける。
  本気で共有運用するなら Route の前に rate limit を置く
- **監査ログが弱い。** 誰が何を検索したかは `search query=...` の INFO ログにしか残らず、
  クライアントの識別もできない。OAuth に移れば `sub` / `client_id` を記録できる
