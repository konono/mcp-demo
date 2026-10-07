"""Settings.from_env() の単体テスト。

環境変数は ConfigMap / Secret からの唯一の入口なので、
パースを間違えると「マニフェストは正しいのに挙動が既定値のまま」になる。
E2E では正常系の組み合わせしか通らないため、境界はここで押さえる。
"""

from __future__ import annotations

import pytest

from search_mcp.settings import Settings

ENV_VARS = [
    "MCP_HOST",
    "MCP_PORT",
    "MCP_PATH",
    "MCP_STATELESS_HTTP",
    "MCP_JSON_RESPONSE",
    "MCP_AUTH_TOKENS",
    "MCP_DNS_REBINDING_PROTECTION",
    "MCP_ALLOWED_HOSTS",
    "MCP_ALLOWED_ORIGINS",
    "MCP_DEFAULT_LIMIT",
    "MCP_MAX_LIMIT",
    "MCP_LOG_LEVEL",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """実行環境の MCP_* に影響されないようにする。"""
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_defaults_match_the_documented_table() -> None:
    """README の環境変数表と一致していること。"""
    s = Settings.from_env()

    assert s.host == "0.0.0.0"
    assert s.port == 8080
    assert s.mcp_path == "/mcp"
    assert s.stateless_http is True  # 複数 replica のため既定で有効
    assert s.json_response is False
    assert s.auth_tokens == []
    assert s.enable_dns_rebinding_protection is True
    assert s.allowed_hosts == []
    assert s.allowed_origins == []
    assert s.default_limit == 5
    assert s.max_limit == 20
    assert s.log_level == "INFO"


def test_every_variable_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("MCP_PORT", "9090")
    monkeypatch.setenv("MCP_PATH", "/rpc")
    monkeypatch.setenv("MCP_STATELESS_HTTP", "false")
    monkeypatch.setenv("MCP_JSON_RESPONSE", "true")
    monkeypatch.setenv("MCP_AUTH_TOKENS", "tok-a,tok-b")
    monkeypatch.setenv("MCP_DNS_REBINDING_PROTECTION", "false")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "search-mcp.apps.example.com")
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "https://example.com")
    monkeypatch.setenv("MCP_DEFAULT_LIMIT", "3")
    monkeypatch.setenv("MCP_MAX_LIMIT", "10")
    monkeypatch.setenv("MCP_LOG_LEVEL", "debug")

    s = Settings.from_env()

    assert s.host == "127.0.0.1"
    assert s.port == 9090
    assert s.mcp_path == "/rpc"
    assert s.stateless_http is False
    assert s.json_response is True
    assert s.auth_tokens == ["tok-a", "tok-b"]
    assert s.enable_dns_rebinding_protection is False
    assert s.allowed_hosts == ["search-mcp.apps.example.com"]
    assert s.allowed_origins == ["https://example.com"]
    assert s.default_limit == 3
    assert s.max_limit == 10
    assert s.log_level == "DEBUG"  # 小文字で書かれても受ける


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "True", "yes", "on", " true "])
def test_truthy_spellings(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("MCP_JSON_RESPONSE", raw)
    assert Settings.from_env().json_response is True


@pytest.mark.parametrize("raw", ["0", "false", "FALSE", "no", "off", "", "maybe"])
def test_anything_else_is_false(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    """未知の値は false 扱い。既定 true の項目でも同じ（安全側ではなく明示優先）。"""
    monkeypatch.setenv("MCP_JSON_RESPONSE", raw)
    assert Settings.from_env().json_response is False

    monkeypatch.setenv("MCP_STATELESS_HTTP", raw)
    assert Settings.from_env().stateless_http is False


def test_unset_booleans_keep_their_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """空文字と未設定は別物。未設定なら既定（true）が残る。"""
    assert Settings.from_env().stateless_http is True
    monkeypatch.setenv("MCP_STATELESS_HTTP", "")
    assert Settings.from_env().stateless_http is False


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a,b,c", ["a", "b", "c"]),
        (" a , b ", ["a", "b"]),  # YAML の折り返しで空白が混じっても落とす
        ("a,,b", ["a", "b"]),  # 空要素は無視（空トークンが通ると全通しになる）
        ("", []),
        ("   ", []),
        (",", []),
        ("single", ["single"]),
    ],
)
def test_comma_separated_lists(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: list[str]
) -> None:
    monkeypatch.setenv("MCP_AUTH_TOKENS", raw)
    assert Settings.from_env().auth_tokens == expected


def test_empty_token_list_means_no_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Secret 未設定時に「空トークンで認証が通る」状態を作らないこと。"""
    monkeypatch.setenv("MCP_AUTH_TOKENS", " , , ")
    assert Settings.from_env().auth_tokens == []


def test_non_numeric_int_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """起動時に落ちてほしい。既定値へ黙って戻ると設定ミスに気づけない。"""
    monkeypatch.setenv("MCP_PORT", "http")
    with pytest.raises(ValueError):
        Settings.from_env()


def test_settings_are_frozen() -> None:
    s = Settings.from_env()
    with pytest.raises(Exception):
        s.port = 1  # type: ignore[misc]
