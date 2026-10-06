"""共有 Bearer トークンによる ASGI 認証ミドルウェア。

なぜ SDK の `AuthSettings` / OAuth ではなくミドルウェアなのか:
  MCP 仕様の認可は OAuth 2.1 Resource Server を前提としており、
  `AuthSettings` を有効にするとクライアントが RFC 9728 の
  `/.well-known/oauth-protected-resource` を辿って IdP を探しに行く。
  共有トークン運用ではその先に本物の Authorization Server が無いため、
  discovery を生やさずに 401 + WWW-Authenticate だけを返すほうが素直に動く。
  IdP を導入する段になったら、このミドルウェアを外して
  `MCPServer(token_verifier=..., auth=AuthSettings(...))` に差し替える。
  （移行手順は docs/security.md に記載）

ヘルスチェックのパスは常に素通りさせる。kubelet の probe は
Authorization ヘッダを付けられないため。
"""

from __future__ import annotations

import hmac
from collections.abc import Iterable

from starlette.types import ASGIApp, Receive, Scope, Send

_UNAUTHORIZED_BODY = b'{"error":"unauthorized"}'


class BearerTokenMiddleware:
    """`Authorization: Bearer <token>` を検証する ASGI ミドルウェア。"""

    def __init__(
        self,
        app: ASGIApp,
        tokens: Iterable[str],
        exempt_paths: Iterable[str] = ("/healthz", "/readyz"),
    ) -> None:
        self.app = app
        self.tokens = [t for t in tokens if t]
        self.exempt_paths = tuple(exempt_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.tokens:
            await self.app(scope, receive, send)
            return

        if scope.get("path", "") in self.exempt_paths:
            await self.app(scope, receive, send)
            return

        if self._is_authorized(scope):
            await self.app(scope, receive, send)
            return

        await self._reject(send)

    def _is_authorized(self, scope: Scope) -> bool:
        for raw_name, raw_value in scope.get("headers", []):
            if raw_name.lower() != b"authorization":
                continue
            value = raw_value.decode("latin-1")
            scheme, _, token = value.partition(" ")
            if scheme.lower() != "bearer":
                return False
            # タイミング攻撃を避けるため定数時間比較。候補を全部走査してから判定する。
            return any(hmac.compare_digest(token.strip(), known) for known in self.tokens)
        return False

    async def _reject(self, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b'Bearer realm="search-mcp"'),
                    (b"content-length", str(len(_UNAUTHORIZED_BODY)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _UNAUTHORIZED_BODY})
