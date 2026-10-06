"""環境変数から読む実行時設定。

コンテナ／OpenShift での配備を前提にしているため、設定はすべて環境変数で与える。
ConfigMap（非機密）と Secret（トークン）を分けてマウントできるようにするのが目的。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _split(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # --- HTTP ---
    host: str = "0.0.0.0"  # コンテナ内では全インターフェースで待ち受ける
    port: int = 8080  # OpenShift の制限付き SCC では 1024 未満を bind できない
    mcp_path: str = "/mcp"  # Streamable HTTP のエンドポイント

    # --- MCP transport ---
    # stateless: セッションをプロセスに持たないので replica を増やしても
    # sticky session なしでロードバランスできる。水平スケールのため既定で有効。
    stateless_http: bool = True
    # json_response: SSE ストリームではなく単発 JSON で返す。
    # Route / Ingress 側のバッファリングに影響されにくく、デモ用途では安定する。
    json_response: bool = False

    # --- auth ---
    # 空ならば認証なし（クラスタ内 Service 限定のデモ用）。
    auth_tokens: list[str] = field(default_factory=list)

    # --- DNS rebinding 対策 ---
    # Route 経由で外部公開する場合、到達しうる Host / Origin を列挙する。
    # 空リストかつ無効化していない場合は SDK の既定（localhost のみ）になり
    # Route 経由のアクセスが 400 になるため、本番では必ず設定する。
    enable_dns_rebinding_protection: bool = True
    allowed_hosts: list[str] = field(default_factory=list)
    allowed_origins: list[str] = field(default_factory=list)

    # --- 検索挙動 ---
    default_limit: int = 5
    max_limit: int = 20  # 未認証の外部 API を叩くのでクライアントからの乱用を抑える
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            host=os.environ.get("MCP_HOST", "0.0.0.0"),
            port=int(os.environ.get("MCP_PORT", "8080")),
            mcp_path=os.environ.get("MCP_PATH", "/mcp"),
            stateless_http=_bool("MCP_STATELESS_HTTP", True),
            json_response=_bool("MCP_JSON_RESPONSE", False),
            auth_tokens=_split(os.environ.get("MCP_AUTH_TOKENS")),
            enable_dns_rebinding_protection=_bool("MCP_DNS_REBINDING_PROTECTION", True),
            allowed_hosts=_split(os.environ.get("MCP_ALLOWED_HOSTS")),
            allowed_origins=_split(os.environ.get("MCP_ALLOWED_ORIGINS")),
            default_limit=int(os.environ.get("MCP_DEFAULT_LIMIT", "5")),
            max_limit=int(os.environ.get("MCP_MAX_LIMIT", "20")),
            log_level=os.environ.get("MCP_LOG_LEVEL", "INFO").upper(),
        )
