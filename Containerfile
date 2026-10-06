# search-mcp コンテナイメージ
#
# build context はリポジトリルート。search-mcp/pyproject.toml が
# [tool.uv.sources] で ../search-demo を参照しているため、両ディレクトリが
# 同じ context に無いと依存を解決できない。
#
#   podman build -f Containerfile -t search-mcp:1.0.0 .
#
# ベースは Red Hat UBI 9 の Python 3.12。OpenShift 上でのサポート・
# CVE 追従の都合でコミュニティイメージではなく UBI を使う。

# ---- builder: 依存解決と仮想環境の作成 ----------------------------------------
FROM registry.access.redhat.com/ubi9/python-312:latest AS builder

USER 0
WORKDIR /build

# uv を固定バージョンで導入する（search-demo/mise.toml と同じ 0.12.23）。
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# 依存だけ先に解決してレイヤキャッシュを効かせる。
# search-demo はパス依存なので、その pyproject と本体も先にコピーする必要がある。
COPY search-mcp/pyproject.toml search-mcp/uv.lock /build/search-mcp/
COPY search-demo/pyproject.toml search-demo/README.md search-demo/search_demo.py /build/search-demo/
RUN cd /build/search-mcp && uv sync --locked --no-dev --no-editable --no-install-project

# アプリ本体を入れる。ここから下だけが、ソース変更時に再実行されるレイヤ。
COPY search-mcp/src /build/search-mcp/src
COPY search-mcp/README.md /build/search-mcp/
# --no-editable: 既定の editable install は /build/search-mcp を指す .pth を書くため、
# builder を捨てる runtime ステージで ModuleNotFoundError になる。実体を venv に焼く。
RUN cd /build/search-mcp && uv sync --locked --no-dev --no-editable

# ---- runtime -----------------------------------------------------------------
FROM registry.access.redhat.com/ubi9/python-312-minimal:latest AS runtime

LABEL org.opencontainers.image.title="search-mcp" \
      org.opencontainers.image.description="Public API cross-search exposed as an MCP Streamable HTTP server" \
      org.opencontainers.image.source="https://github.com/example/mcp-demo" \
      org.opencontainers.image.licenses="MIT"

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8080

# OpenShift の restricted-v2 SCC は任意の UID（root group 0）で起動するため、
# 特定 UID を前提にしない。1001 は UBI の既定の非 root ユーザー。
USER 1001

EXPOSE 8080

# probe は manifest 側で定義する。ここでは podman 単体実行時の目安として置く。
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/healthz').read()"

ENTRYPOINT ["search-mcp"]
