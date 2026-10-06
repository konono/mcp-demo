"""ASGI アプリケーションの組み立て。

MCPServer が返す Starlette アプリに、HTTP ワークロードとして必要なものを足す:
  - /healthz, /readyz : kubelet の probe 用（認証不要）
  - Bearer 認証ミドルウェア
  - DNS rebinding 対策（Route 経由で外部公開するため）
"""

from __future__ import annotations

import logging

from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp

from .auth import BearerTokenMiddleware
from .server import build_server
from .settings import Settings


def create_app(settings: Settings | None = None) -> ASGIApp:
    settings = settings or Settings.from_env()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logger = logging.getLogger(__name__)

    mcp = build_server(settings)

    # custom_route は MCPServer が生成する Starlette アプリにそのまま載る。
    # liveness と readiness を分けておくと、外部 API 障害時に Pod を
    # 再起動させずに Service から外す、といった運用の選択肢が残る。
    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(_: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    @mcp.custom_route("/readyz", methods=["GET"])
    async def readyz(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ready", "stateless": settings.stateless_http})

    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=settings.enable_dns_rebinding_protection,
        allowed_hosts=settings.allowed_hosts,
        allowed_origins=settings.allowed_origins,
    )

    app: ASGIApp = mcp.streamable_http_app(
        streamable_http_path=settings.mcp_path,
        stateless_http=settings.stateless_http,
        json_response=settings.json_response,
        transport_security=transport_security,
        host=settings.host,
    )

    if settings.auth_tokens:
        logger.info("bearer auth enabled (%d token(s) configured)", len(settings.auth_tokens))
        app = BearerTokenMiddleware(app, tokens=settings.auth_tokens)
    else:
        # デモ用に起動はさせるが、気付けるよう警告を出す。
        logger.warning(
            "MCP_AUTH_TOKENS is empty: the server accepts unauthenticated requests. "
            "Do not expose it through an OpenShift Route in this state."
        )

    return app
