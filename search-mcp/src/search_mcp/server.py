"""search-demo の横断検索を MCP ツールとして公開するサーバー定義。

設計の要点は docs/skill-to-mcp.md を参照。要約すると:

  - SKILL.md の frontmatter `description`  -> MCPServer の `instructions`
  - SKILL.md の「使い方」「オプション表」     -> ツールの入力スキーマ（型・enum・既定値）
  - SKILL.md の「使い分けの指針」            -> ツール description の中核
  - SKILL.md の「注意」                      -> ツール description の制約節 + サーバー側のガード
  - SKILL.md の「出力」例                    -> structured output のスキーマ（Pydantic モデル）

Skill はプロンプトとして読ませるマークダウンだが、MCP ツールはスキーマと
description しかモデルに届かない。そのため「人間向けの散文」を
「モデルが呼び出し判断に使える description」と「機械的に強制できるスキーマ」に
分解するのがこの移植作業の本質になる。
"""

# 注意: このモジュールでは `from __future__ import annotations` を使わない。
# ツール関数の Annotated[...] に settings の値（max_limit など）を埋め込んでおり、
# アノテーションが文字列化されると MCP SDK 側の eval がクロージャ変数を解決できず
# InvalidSignature になるため。評価済みのオブジェクトとして渡す必要がある。

import logging
from typing import Annotated, Literal

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

import search_demo

from .settings import Settings

logger = logging.getLogger(__name__)

SourceName = Literal["wikipedia", "hackernews", "github", "stackoverflow"]

# --- SKILL.md の「使い分けの指針」をそのままモデルに渡すための構造化データ -------------
# list_search_sources ツールと search ツールの description の双方から参照する。
# 散文を 1 か所にまとめておくと、Skill 版と MCP 版で指針がずれない。
SOURCE_GUIDE: dict[str, dict[str, str]] = {
    "wikipedia": {
        "api": "MediaWiki Action API",
        "use_when": "用語・概念の定義を押さえたいとき。日本語なら lang='ja'、専門的な内容は lang='en' も試す",
        "caveats": "lang パラメータが効くのはこのソースだけ",
    },
    "hackernews": {
        "api": "Algolia Hacker News Search API",
        "use_when": "技術トピックの議論・評判・一次情報の反応を知りたいとき",
        "caveats": "snippet は points / comments / author / 投稿日のメタ情報になる",
    },
    "github": {
        "api": "GitHub Repository Search API (未認証)",
        "use_when": "実装やライブラリを探すとき。スター数順に並ぶ",
        "caveats": "未認証のレート制限が厳しい（検索は約 10 req/min）。limit は小さく、連続実行は避ける",
    },
    "stackoverflow": {
        "api": "Stack Exchange API 2.3",
        "use_when": "エラーメッセージや実装上の詰まりの既知の解決策を探すとき",
        "caveats": "キーワードはエラー文の固有部分（パスや変数名）を削って短くするとヒットしやすい",
    },
}

INSTRUCTIONS = """\
公開 API（Wikipedia / Hacker News / GitHub / Stack Overflow）を横断検索するサーバー。認証不要の外部 API のみを使う。

次のときに `search` を使う:
  - 用語の意味や技術トピックの一次情報を知りたい
  - OSS のライブラリ・リポジトリを探したい
  - エラーメッセージの既知の解決策を探したい
  - 手持ちの知識が古い可能性があり、外部情報で裏取りしたい

回答時は必ず結果の `url` を引用元として提示すること。
一部のソースが失敗しても処理は続行し、理由は `errors` に入る。`count` が 0 のときは `errors` を必ず読むこと。
"""


# --- 出力スキーマ -------------------------------------------------------------
# SKILL.md では JSON 例を散文で示していたが、MCP では structured output の
# スキーマとしてクライアントに配信できる。モデルがパース方法を推測せずに済む。


class SearchHit(BaseModel):
    """検索結果 1 件。"""

    source: SourceName = Field(description="この結果の出典ソース")
    title: str = Field(description="ページ・リポジトリ・質問のタイトル")
    url: str = Field(description="引用元として提示すべき URL")
    snippet: str = Field(description="要約または件数・スコアなどのメタ情報")


class SourceError(BaseModel):
    """1 ソースの取得失敗。全体は失敗扱いにしない。"""

    source: str = Field(description="失敗したソース名")
    error: str = Field(description="失敗理由（HTTP ステータス、ネットワークエラーなど）")


class SearchResponse(BaseModel):
    query: str = Field(description="実際に検索に使ったキーワード")
    count: int = Field(description="results の件数")
    results: list[SearchHit] = Field(description="全ソースをマージした結果")
    errors: list[SourceError] = Field(
        description="取得に失敗したソース。空でなく count が 0 なら検索自体が成立していない"
    )


class SourceInfo(BaseModel):
    name: SourceName
    api: str = Field(description="背後で叩いている公開 API")
    use_when: str = Field(description="このソースを選ぶべき状況")
    caveats: str = Field(description="レート制限や癖など、呼ぶ前に知っておくべきこと")


def build_server(settings: Settings | None = None) -> MCPServer:
    """MCPServer を組み立てて返す。テストからも使えるよう副作用を持たせない。"""
    settings = settings or Settings.from_env()

    mcp = MCPServer(
        name="search-mcp",
        title="Public API Search",
        version="1.0.0",
        instructions=INSTRUCTIONS,
        log_level=settings.log_level,
    )

    @mcp.tool(
        name="search",
        title="公開 API 横断検索",
        description=(
            "Wikipedia / Hacker News / GitHub / Stack Overflow を横断検索し、"
            "タイトル・URL・要約の一覧を返す。認証不要・外部ネットワークアクセスあり。\n\n"
            "ソースの選び方:\n"
            + "\n".join(f"  - {n}: {g['use_when']}" for n, g in SOURCE_GUIDE.items())
            + "\n  - 当たりが付かないときは sources を省略して全ソースを引き、結果を見てから絞り込む。\n\n"
            "注意: GitHub と Stack Exchange は未認証のためレート制限が厳しい。"
            "連続して呼ばず、limit は小さくする。日本語キーワードはそのまま渡してよい。"
        ),
        annotations=ToolAnnotations(
            # 外部 API を読むだけで副作用はない。クライアントが自動承認の判断に使える。
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        ),
    )
    async def search(
        query: Annotated[
            str,
            Field(description="検索キーワード。日本語可。エラー文を渡すときは固有部分を削って短くする"),
        ],
        sources: Annotated[
            list[SourceName] | None,
            Field(description="検索対象ソース。省略すると全ソースを並列に検索する"),
        ] = None,
        limit: Annotated[
            int | None,
            Field(
                description=f"ソースごとの取得件数（省略時 {settings.default_limit}）",
                ge=1,
                le=settings.max_limit,
            ),
        ] = None,
        lang: Annotated[
            str,
            Field(description="Wikipedia の言語コード（ja / en など）。他ソースには影響しない"),
        ] = "ja",
    ) -> SearchResponse:
        effective_limit = settings.default_limit if limit is None else limit
        effective_limit = max(1, min(effective_limit, settings.max_limit))
        selected = list(sources) if sources else list(search_demo.SOURCES)

        logger.info(
            "search query=%r sources=%s limit=%d lang=%s",
            query,
            selected,
            effective_limit,
            lang,
        )

        # search_demo.run_search は urllib + ThreadPoolExecutor の同期実装。
        # イベントループを塞がないようワーカースレッドに逃がす。
        payload = await anyio.to_thread.run_sync(
            search_demo.run_search, query, selected, effective_limit, lang
        )
        return SearchResponse.model_validate(payload)

    @mcp.tool(
        name="list_search_sources",
        title="検索ソース一覧",
        description=(
            "search ツールで指定できるソースと、それぞれの使いどころ・制約を返す。"
            "どのソースを選ぶべきか迷ったときに先に呼ぶ。外部アクセスは発生しない。"
        ),
        annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True),
    )
    def list_search_sources() -> list[SourceInfo]:
        return [SourceInfo(name=name, **info) for name, info in SOURCE_GUIDE.items()]  # type: ignore[arg-type]

    return mcp
