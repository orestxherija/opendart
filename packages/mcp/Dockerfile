# syntax=docker/dockerfile:1.28.0@sha256:bb22d9815c728170f72750f4e5b0d672e06176142e1d602c7e66c050100b7e5b

# The official CPython image enables PGO and LTO on amd64 and arm64.
# Share an exact interpreter and OS between the build and runtime stages.
FROM python:3.14.8-slim-trixie@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS python-base
HEALTHCHECK NONE

FROM python-base AS builder
HEALTHCHECK NONE

COPY --from=ghcr.io/astral-sh/uv:0.11.20@sha256:eaa5f1a3305307aaf9e67fe2bbba1d85ebbb2d8a63bce23af21797bfafbe0f8b /uv /usr/local/bin/uv

# Override the workspace's managed-Python and local-cache development settings.
# Compiling dependencies once reduces startup work on the read-only runtime.
ENV UV_PYTHON_DOWNLOADS=never \
    UV_NO_MANAGED_PYTHON=1 \
    UV_PYTHON=/usr/local/bin/python3 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_CACHE_DIR=/root/.cache/uv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
WORKDIR /app

# Source edits reuse this dependency layer; all workspace manifests validate the lock.
COPY pyproject.toml uv.toml uv.lock ./
COPY packages/sdk/pyproject.toml packages/sdk/pyproject.toml
COPY packages/mcp/pyproject.toml packages/mcp/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --package opendart-mcp --no-default-groups --no-editable --no-install-workspace

COPY README.md ./
COPY packages/sdk/README.md packages/sdk/README.md
COPY packages/mcp/README.md packages/mcp/README.md
COPY packages/sdk/src/ packages/sdk/src/
COPY packages/mcp/src/ packages/mcp/src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --package opendart-mcp --no-default-groups --no-editable

FROM python-base AS runtime

# CI supplies build-specific labels; local builds can supply these arguments.
# Keep unknown build facts and the undeclared project license empty.
ARG IMAGE_VERSION=0.1.0
ARG IMAGE_REVISION
ARG IMAGE_CREATED
ARG IMAGE_LICENSES

LABEL org.opencontainers.image.title="OpenDART MCP" \
    org.opencontainers.image.description="OpenDART MCP server over local HTTP" \
    org.opencontainers.image.authors="https://github.com/orestxherija" \
    org.opencontainers.image.vendor="orestxherija" \
    org.opencontainers.image.url="https://github.com/orestxherija/opendart" \
    org.opencontainers.image.documentation="https://github.com/orestxherija/opendart/blob/main/packages/mcp/README.md" \
    org.opencontainers.image.source="https://github.com/orestxherija/opendart" \
    org.opencontainers.image.version="${IMAGE_VERSION}" \
    org.opencontainers.image.revision="${IMAGE_REVISION}" \
    org.opencontainers.image.created="${IMAGE_CREATED}" \
    org.opencontainers.image.licenses="${IMAGE_LICENSES}"

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONSAFEPATH=1 \
    OPENDART_MCP_HTTP__HOST=0.0.0.0 \
    OPENDART_MCP_HTTP__PORT=8000
WORKDIR /app

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --no-log-init \
        --home-dir /nonexistent --shell /usr/sbin/nologin app
# Root ownership prevents the service account from modifying installed code.
COPY --from=builder --chown=0:0 /opt/venv /opt/venv

USER 10001:10001
EXPOSE 8000
# Check listener readiness; CI also verifies MCP discovery and a real tool call.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import socket; from opendart_mcp.settings import get_settings; socket.create_connection(('127.0.0.1', get_settings().http.port), timeout=2).close()"]
CMD ["opendart-mcp"]
