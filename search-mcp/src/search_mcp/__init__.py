"""search-demo の横断検索を MCP Streamable HTTP サーバーとして公開するパッケージ。"""

from .app import create_app
from .server import build_server
from .settings import Settings

__all__ = ["create_app", "build_server", "Settings"]
__version__ = "1.0.0"
