"""search_demo の単体テスト。

ネットワークには一切出ない。`urllib.request.urlopen` を差し替えて、
各ソースの**レスポンスのパース**と、失敗時の振る舞いを対象にする。

ここが壊れても MCP 版のテスト（search-mcp/tests/test_server.py）は
`run_search` をモックしているため緑のままになる。だからこちらが要る。
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
import urllib.request

import pytest

import search_demo


# --- urlopen の差し替え --------------------------------------------------------


class _FakeResponse(io.BytesIO):
    """urlopen の戻り値（コンテキストマネージャ + read()）を模す。"""

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


@pytest.fixture
def capture(monkeypatch: pytest.MonkeyPatch):
    """urlopen を差し替え、リクエスト URL を記録しつつ固定の JSON を返す。

    使い方: capture(payload) で戻り値を固定し、capture.urls で URL を見る。
    """

    class _Capture:
        urls: list[str] = []

        def __call__(self, payload: object, *, raises: Exception | None = None) -> None:
            def _urlopen(req, timeout=None):  # noqa: ANN001
                self.urls.append(req.full_url)
                if raises is not None:
                    raise raises
                return _FakeResponse(json.dumps(payload).encode("utf-8"))

            monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

        def raw(self, body: bytes) -> None:
            """JSON として不正なボディを返したい場合。"""

            def _urlopen(req, timeout=None):  # noqa: ANN001
                self.urls.append(req.full_url)
                return _FakeResponse(body)

            monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    cap = _Capture()
    cap.urls = []
    return cap


# --- http_get_json -------------------------------------------------------------


def test_http_get_json_builds_the_query_string(capture) -> None:
    capture({"ok": True})
    assert search_demo.http_get_json("https://example.invalid/api", {"a": 1, "b": "x y"}) == {
        "ok": True
    }
    assert capture.urls == ["https://example.invalid/api?a=1&b=x+y"]


def test_japanese_keywords_are_url_encoded(capture) -> None:
    """SKILL.md の「日本語キーワードはそのまま渡してよい（内部でエンコードする）」の裏付け。"""
    capture({})
    search_demo.http_get_json("https://example.invalid/api", {"q": "量子計算"})
    query = urllib.parse.parse_qs(urllib.parse.urlparse(capture.urls[0]).query)
    assert query["q"] == ["量子計算"]
    assert "量子計算" not in capture.urls[0]  # 生のまま載せていない


def test_list_params_are_expanded(capture) -> None:
    capture({})
    search_demo.http_get_json("https://example.invalid/api", {"t": ["a", "b"]})
    assert capture.urls[0].endswith("t=a&t=b")


def test_http_error_becomes_search_error(capture) -> None:
    capture(None, raises=urllib.error.HTTPError("u", 503, "Service Unavailable", {}, None))
    with pytest.raises(search_demo.SearchError, match=r"HTTP 503"):
        search_demo.http_get_json("https://example.invalid/api", {})


def test_network_error_becomes_search_error(capture) -> None:
    capture(None, raises=urllib.error.URLError("name resolution failed"))
    with pytest.raises(search_demo.SearchError, match=r"network error"):
        search_demo.http_get_json("https://example.invalid/api", {})


def test_invalid_json_becomes_search_error(capture) -> None:
    capture.raw(b"<html>503 from a proxy</html>")
    with pytest.raises(search_demo.SearchError, match=r"invalid JSON"):
        search_demo.http_get_json("https://example.invalid/api", {})


# --- strip_html ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('<span class="searchmatch">asyncio</span> とは', "asyncio とは"),
        ("a &amp; b &lt;c&gt;", "a & b <c>"),
        ("  周囲の空白  ", "周囲の空白"),
        ("<b><i>入れ子</i></b>", "入れ子"),
        ("閉じていない <b", "閉じていない"),  # 壊れた HTML でも例外にしない
        ("", ""),
    ],
)
def test_strip_html(raw: str, expected: str) -> None:
    assert search_demo.strip_html(raw) == expected


# --- 各ソースのパース ------------------------------------------------------------


def test_wikipedia_builds_article_urls(capture) -> None:
    capture(
        {
            "query": {
                "search": [
                    {"title": "Python (プログラミング言語)", "snippet": '<span>汎用</span>の言語'},
                ]
            }
        }
    )
    [hit] = search_demo.search_wikipedia("python", 5, "ja")

    assert hit["source"] == "wikipedia"
    assert hit["title"] == "Python (プログラミング言語)"
    # 空白はアンダースコアにしてから URL エンコードする
    assert hit["url"].startswith("https://ja.wikipedia.org/wiki/Python_")
    assert " " not in hit["url"]
    assert hit["snippet"] == "汎用の言語"


def test_wikipedia_honours_the_lang_parameter(capture) -> None:
    capture({"query": {"search": []}})
    search_demo.search_wikipedia("python", 5, "en")
    assert capture.urls[0].startswith("https://en.wikipedia.org/w/api.php?")


def test_hackernews_falls_back_when_fields_are_missing(capture) -> None:
    capture(
        {
            "hits": [
                {"title": "Show HN: a thing", "url": "https://example.invalid/a", "points": 10},
                # url が無い投稿は HN のアイテムページに落とす
                {"story_title": "Ask HN: anything?", "objectID": "42"},
                # title も story_title も無い
                {"objectID": "43"},
            ]
        }
    )
    hits = search_demo.search_hackernews("hn", 5, "ja")

    assert hits[0]["url"] == "https://example.invalid/a"
    assert hits[1]["title"] == "Ask HN: anything?"
    assert hits[1]["url"] == "https://news.ycombinator.com/item?id=42"
    assert hits[2]["title"] == "(no title)"
    assert all(h["source"] == "hackernews" for h in hits)


def test_github_tolerates_null_description_and_language(capture) -> None:
    capture(
        {
            "items": [
                {
                    "full_name": "python/cpython",
                    "html_url": "https://github.com/python/cpython",
                    "stargazers_count": 60000,
                    "language": "Python",
                    "description": " The Python programming language ",
                },
                # GitHub は description / language を null で返すことがある
                {
                    "full_name": "u/empty",
                    "html_url": "https://github.com/u/empty",
                    "stargazers_count": 0,
                    "language": None,
                    "description": None,
                },
            ]
        }
    )
    hits = search_demo.search_github("python", 5, "ja")

    assert hits[0]["snippet"] == "★60000 Python: The Python programming language"
    assert hits[1]["snippet"] == "★0 -: "


def test_stackoverflow_unescapes_titles(capture) -> None:
    capture(
        {
            "items": [
                {
                    "title": "Why does &lt;div&gt; not center?",
                    "link": "https://stackoverflow.com/q/1",
                    "score": 3,
                    "answer_count": 2,
                    "is_answered": True,
                }
            ]
        }
    )
    [hit] = search_demo.search_stackoverflow("css", 5, "ja")

    assert hit["title"] == "Why does <div> not center?"
    assert hit["snippet"] == "score=3 answers=2 accepted=True"


@pytest.mark.parametrize(
    ("fn", "payload"),
    [
        (search_demo.search_wikipedia, {}),
        (search_demo.search_wikipedia, {"query": {"search": []}}),
        (search_demo.search_hackernews, {}),
        (search_demo.search_github, {}),
        (search_demo.search_stackoverflow, {}),
    ],
)
def test_empty_or_unexpected_payloads_yield_no_results(capture, fn, payload) -> None:
    """キーが欠けていても KeyError にせず空リストを返す。"""
    capture(payload)
    assert fn("q", 5, "ja") == []


def test_limit_is_passed_to_each_api(capture) -> None:
    """ソースごとにパラメータ名が違うので、取り違えていないか確認する。"""
    expected = {
        search_demo.search_wikipedia: "srlimit",
        search_demo.search_hackernews: "hitsPerPage",
        search_demo.search_github: "per_page",
        search_demo.search_stackoverflow: "pagesize",
    }
    for fn, param in expected.items():
        capture({})
        fn("q", 3, "ja")
        query = urllib.parse.parse_qs(urllib.parse.urlparse(capture.urls[-1]).query)
        assert query[param] == ["3"], f"{fn.__name__} の {param}"


def test_sources_registry_matches_the_mcp_server() -> None:
    """SOURCES のキーは MCP 側の SourceName リテラルと一致している必要がある。"""
    assert set(search_demo.SOURCES) == {
        "wikipedia",
        "hackernews",
        "github",
        "stackoverflow",
    }


# --- run_search ----------------------------------------------------------------


def _stub_sources(monkeypatch: pytest.MonkeyPatch, behaviour: dict) -> list[tuple]:
    """SOURCES の各関数を差し替える。値が例外ならそれを送出する。"""
    calls: list[tuple] = []

    def make(name: str, outcome: object):
        def _fn(query: str, limit: int, lang: str):
            calls.append((name, query, limit, lang))
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        return _fn

    monkeypatch.setattr(
        search_demo, "SOURCES", {k: make(k, v) for k, v in behaviour.items()}
    )
    return calls


def test_run_search_merges_results_from_every_source(monkeypatch) -> None:
    calls = _stub_sources(
        monkeypatch,
        {
            "github": [{"source": "github", "title": "g", "url": "u1", "snippet": ""}],
            "wikipedia": [{"source": "wikipedia", "title": "w", "url": "u2", "snippet": ""}],
        },
    )
    payload = search_demo.run_search("q", ["github", "wikipedia"], 3, "ja")

    assert payload["query"] == "q"
    assert payload["count"] == 2
    assert payload["errors"] == []
    assert {r["source"] for r in payload["results"]} == {"github", "wikipedia"}
    # 引数がそのまま各ソースに渡る
    assert sorted(calls) == [("github", "q", 3, "ja"), ("wikipedia", "q", 3, "ja")]


def test_partial_failure_keeps_the_other_results(monkeypatch) -> None:
    """1 ソースが落ちても残りは返す。これが MCP 側で errors フィールドになる。"""
    _stub_sources(
        monkeypatch,
        {
            "github": [{"source": "github", "title": "g", "url": "u", "snippet": ""}],
            "wikipedia": search_demo.SearchError("HTTP 503 from wikipedia"),
        },
    )
    payload = search_demo.run_search("q", ["github", "wikipedia"], 3, "ja")

    assert payload["count"] == 1
    assert payload["errors"] == [{"source": "wikipedia", "error": "HTTP 503 from wikipedia"}]


def test_all_sources_failing_yields_zero_count_and_errors(monkeypatch) -> None:
    _stub_sources(
        monkeypatch,
        {
            "github": search_demo.SearchError("boom"),
            "wikipedia": search_demo.SearchError("boom"),
        },
    )
    payload = search_demo.run_search("q", ["github", "wikipedia"], 3, "ja")

    assert payload["count"] == 0
    assert len(payload["errors"]) == 2


def test_unexpected_exceptions_are_not_swallowed(monkeypatch) -> None:
    """SearchError 以外はバグなので握り潰さない（errors に紛れると原因が見えなくなる）。"""
    _stub_sources(monkeypatch, {"github": ValueError("bug in the parser")})
    with pytest.raises(ValueError, match="bug in the parser"):
        search_demo.run_search("q", ["github"], 3, "ja")


def test_results_follow_the_requested_source_order(monkeypatch) -> None:
    """並列取得でも出力順は入力順（pool.map の性質）。再現性のために固定しておく。"""
    _stub_sources(
        monkeypatch,
        {
            "github": [{"source": "github", "title": "g", "url": "u", "snippet": ""}],
            "wikipedia": [{"source": "wikipedia", "title": "w", "url": "u", "snippet": ""}],
        },
    )
    payload = search_demo.run_search("q", ["wikipedia", "github"], 3, "ja")
    assert [r["source"] for r in payload["results"]] == ["wikipedia", "github"]


# --- format_text ---------------------------------------------------------------


def test_format_text_renders_results_and_errors() -> None:
    text = search_demo.format_text(
        {
            "query": "q",
            "count": 1,
            "results": [
                {"source": "github", "title": "t", "url": "https://u", "snippet": "s"}
            ],
            "errors": [{"source": "wikipedia", "error": "HTTP 503"}],
        }
    )
    assert "query: q  (1 results)" in text
    assert "1. [github] t" in text
    assert "https://u" in text
    assert "! wikipedia: HTTP 503" in text


def test_format_text_truncates_long_snippets() -> None:
    text = search_demo.format_text(
        {
            "query": "q",
            "count": 1,
            "results": [{"source": "s", "title": "t", "url": "u", "snippet": "x" * 500}],
            "errors": [],
        }
    )
    assert "x" * 200 in text
    assert "x" * 201 not in text


# --- CLI -----------------------------------------------------------------------


def test_cli_defaults_to_all_sources(monkeypatch, capsys) -> None:
    seen: dict = {}

    def _run(query, sources, limit, lang):
        seen.update(query=query, sources=sources, limit=limit, lang=lang)
        return {"query": query, "count": 0, "results": [], "errors": []}

    monkeypatch.setattr(search_demo, "run_search", _run)
    assert search_demo.main(["rust"]) == 0

    assert seen["sources"] == list(search_demo.SOURCES)
    assert seen["limit"] == 5
    assert seen["lang"] == "ja"
    # 既定は JSON 出力
    assert json.loads(capsys.readouterr().out)["query"] == "rust"


def test_cli_deduplicates_repeated_sources(monkeypatch, capsys) -> None:
    seen: dict = {}
    monkeypatch.setattr(
        search_demo,
        "run_search",
        lambda q, s, n, l: (  # noqa: E741
            seen.update(sources=s),
            {"query": q, "count": 0, "results": [], "errors": []},
        )[1],
    )
    search_demo.main(["q", "-s", "github", "-s", "github", "-s", "wikipedia"])
    assert seen["sources"] == ["github", "wikipedia"]


def test_cli_all_overrides_other_sources(monkeypatch) -> None:
    seen: dict = {}
    monkeypatch.setattr(
        search_demo,
        "run_search",
        lambda q, s, n, l: (  # noqa: E741
            seen.update(sources=s),
            {"query": q, "count": 0, "results": [], "errors": []},
        )[1],
    )
    search_demo.main(["q", "-s", "github", "-s", "all"])
    assert seen["sources"] == list(search_demo.SOURCES)


def test_cli_clamps_limit_to_at_least_one(monkeypatch) -> None:
    seen: dict = {}
    monkeypatch.setattr(
        search_demo,
        "run_search",
        lambda q, s, n, l: (  # noqa: E741
            seen.update(limit=n),
            {"query": q, "count": 0, "results": [], "errors": []},
        )[1],
    )
    search_demo.main(["q", "-n", "0"])
    assert seen["limit"] == 1


def test_cli_text_format(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        search_demo,
        "run_search",
        lambda *a: {
            "query": "q",
            "count": 1,
            "results": [{"source": "github", "title": "t", "url": "u", "snippet": ""}],
            "errors": [],
        },
    )
    search_demo.main(["q", "-f", "text"])
    out = capsys.readouterr().out
    assert "1. [github] t" in out
    assert not out.lstrip().startswith("{")


def test_cli_exits_nonzero_only_when_everything_failed(monkeypatch) -> None:
    """部分的な失敗は成功扱い。全滅のときだけ 1 を返す。"""
    monkeypatch.setattr(
        search_demo,
        "run_search",
        lambda *a: {"query": "q", "count": 0, "results": [], "errors": [{"s": "e"}]},
    )
    assert search_demo.main(["q"]) == 1

    monkeypatch.setattr(
        search_demo,
        "run_search",
        lambda *a: {
            "query": "q",
            "count": 1,
            "results": [{"source": "s", "title": "t", "url": "u", "snippet": ""}],
            "errors": [{"s": "e"}],
        },
    )
    assert search_demo.main(["q"]) == 0

    # ヒット 0 でもエラーが無ければ「見つからなかった」だけなので 0
    monkeypatch.setattr(
        search_demo,
        "run_search",
        lambda *a: {"query": "q", "count": 0, "results": [], "errors": []},
    )
    assert search_demo.main(["q"]) == 0


def test_cli_rejects_unknown_sources() -> None:
    with pytest.raises(SystemExit):
        search_demo.main(["q", "-s", "bing"])
