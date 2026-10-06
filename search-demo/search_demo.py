#!/usr/bin/env python3
"""公開 API を横断検索するデモ用 CLI。

認証不要・標準ライブラリのみで動作する。opencode / Claude Code などの
エージェントから Skill 経由で呼び出すことを想定し、既定で JSON を標準出力に返す。

対応ソース:
  wikipedia  - Wikipedia 検索 API (ja/en 切替可)
  hackernews - Hacker News (Algolia Search API)
  github     - GitHub リポジトリ検索 (未認証)
  stackoverflow - Stack Exchange API (Stack Overflow)

使用例:
  python search_demo.py "python asyncio"
  python search_demo.py "rust" --source github --limit 3
  python search_demo.py "量子計算" --source wikipedia --lang ja --format text
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

USER_AGENT = "search-demo/1.0 (+https://example.invalid; public API demo)"
TIMEOUT = 10.0


class SearchError(RuntimeError):
    """検索ソースへのアクセスに失敗したことを表す。"""


def http_get_json(url: str, params: dict[str, Any]) -> Any:
    """GET して JSON を返す。失敗は SearchError に正規化する。"""
    query = urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(
        f"{url}?{query}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SearchError(f"HTTP {e.code} from {url}") from e
    except urllib.error.URLError as e:
        raise SearchError(f"network error for {url}: {e.reason}") from e
    except json.JSONDecodeError as e:
        raise SearchError(f"invalid JSON from {url}: {e}") from e


def strip_html(text: str) -> str:
    out, depth = [], 0
    for ch in text:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return html.unescape("".join(out)).strip()


def search_wikipedia(query: str, limit: int, lang: str) -> list[dict[str, str]]:
    data = http_get_json(
        f"https://{lang}.wikipedia.org/w/api.php",
        {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": limit,
            "format": "json",
            "formatversion": 2,
        },
    )
    results = []
    for item in data.get("query", {}).get("search", []):
        title = item["title"]
        results.append(
            {
                "source": "wikipedia",
                "title": title,
                "url": f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
                "snippet": strip_html(item.get("snippet", "")),
            }
        )
    return results


def search_hackernews(query: str, limit: int, lang: str) -> list[dict[str, str]]:
    data = http_get_json(
        "https://hn.algolia.com/api/v1/search",
        {"query": query, "hitsPerPage": limit, "tags": "story"},
    )
    results = []
    for hit in data.get("hits", []):
        results.append(
            {
                "source": "hackernews",
                "title": hit.get("title") or hit.get("story_title") or "(no title)",
                "url": hit.get("url")
                or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                "snippet": f"points={hit.get('points')} comments={hit.get('num_comments')} by {hit.get('author')} on {hit.get('created_at')}",
            }
        )
    return results


def search_github(query: str, limit: int, lang: str) -> list[dict[str, str]]:
    data = http_get_json(
        "https://api.github.com/search/repositories",
        {"q": query, "per_page": limit, "sort": "stars", "order": "desc"},
    )
    results = []
    for repo in data.get("items", []):
        results.append(
            {
                "source": "github",
                "title": repo["full_name"],
                "url": repo["html_url"],
                "snippet": f"★{repo['stargazers_count']} {repo.get('language') or '-'}: {(repo.get('description') or '').strip()}",
            }
        )
    return results


def search_stackoverflow(query: str, limit: int, lang: str) -> list[dict[str, str]]:
    data = http_get_json(
        "https://api.stackexchange.com/2.3/search/advanced",
        {
            "q": query,
            "pagesize": limit,
            "order": "desc",
            "sort": "relevance",
            "site": "stackoverflow",
        },
    )
    results = []
    for item in data.get("items", []):
        results.append(
            {
                "source": "stackoverflow",
                "title": strip_html(item["title"]),
                "url": item["link"],
                "snippet": f"score={item.get('score')} answers={item.get('answer_count')} accepted={item.get('is_answered')}",
            }
        )
    return results


SOURCES: dict[str, Callable[[str, int, str], list[dict[str, str]]]] = {
    "wikipedia": search_wikipedia,
    "hackernews": search_hackernews,
    "github": search_github,
    "stackoverflow": search_stackoverflow,
}


def run_search(query: str, sources: list[str], limit: int, lang: str) -> dict[str, Any]:
    results: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    def one(name: str) -> tuple[str, Any]:
        try:
            return name, SOURCES[name](query, limit, lang)
        except SearchError as e:
            return name, e

    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        for name, outcome in pool.map(one, sources):
            if isinstance(outcome, SearchError):
                errors.append({"source": name, "error": str(outcome)})
            else:
                results.extend(outcome)

    return {"query": query, "count": len(results), "results": results, "errors": errors}


def format_text(payload: dict[str, Any]) -> str:
    lines = [f'query: {payload["query"]}  ({payload["count"]} results)']
    for i, r in enumerate(payload["results"], 1):
        lines.append(f'\n{i}. [{r["source"]}] {r["title"]}')
        lines.append(f'   {r["url"]}')
        if r["snippet"]:
            lines.append(f'   {r["snippet"][:200]}')
    for e in payload["errors"]:
        lines.append(f'\n! {e["source"]}: {e["error"]}')
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="公開 API を横断検索するデモ CLI（認証不要・標準ライブラリのみ）"
    )
    parser.add_argument("query", help="検索キーワード")
    parser.add_argument(
        "--source",
        "-s",
        action="append",
        choices=[*SOURCES, "all"],
        help="検索ソース（複数指定可、既定: all）",
    )
    parser.add_argument("--limit", "-n", type=int, default=5, help="ソースごとの件数 (既定: 5)")
    parser.add_argument("--lang", default="ja", help="Wikipedia の言語コード (既定: ja)")
    parser.add_argument(
        "--format", "-f", choices=["json", "text"], default="json", help="出力形式 (既定: json)"
    )
    args = parser.parse_args(argv)

    selected = args.source or ["all"]
    sources = list(SOURCES) if "all" in selected else list(dict.fromkeys(selected))

    payload = run_search(args.query, sources, max(1, args.limit), args.lang)

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_text(payload))

    # 全ソース失敗時のみ異常終了（部分的な失敗は errors に載せて成功扱い）
    return 1 if payload["count"] == 0 and payload["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
