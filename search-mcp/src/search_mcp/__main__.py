"""`search-mcp` コマンドのエントリポイント。

uvicorn をライブラリとして起動する。コンテナでは PID 1 がこのプロセスになり、
ワーカー数は replica 数で調整する（1 Pod 1 ワーカー）ので --workers は使わない。
"""

from __future__ import annotations

import uvicorn

from .app import create_app
from .settings import Settings


def main() -> None:
    settings = Settings.from_env()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        # OpenShift の Route / HAProxy がすでに X-Forwarded-* を付けるので尊重する。
        proxy_headers=True,
        forwarded_allow_ips="*",
        # SIGTERM から実際の終了までの猶予。Deployment の
        # terminationGracePeriodSeconds より短くしておく。
        timeout_graceful_shutdown=20,
    )


if __name__ == "__main__":
    main()
