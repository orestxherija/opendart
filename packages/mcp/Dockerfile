# syntax=docker/dockerfile:1.28.0@sha256:bb22d9815c728170f72750f4e5b0d672e06176142e1d602c7e66c050100b7e5b

# Use matching DHI Python and Alpine versions for the copied virtual environment.
# Authenticate with `docker login dhi.io` before building.
FROM dhi.io/python:3.14.8-alpine3.24-dev@sha256:df552b9c5634f917614a73c7687a6aebfff432f8ea7a6db754e953e618dc51c1 AS builder
HEALTHCHECK NONE

COPY --from=ghcr.io/astral-sh/uv:0.11.20@sha256:eaa5f1a3305307aaf9e67fe2bbba1d85ebbb2d8a63bce23af21797bfafbe0f8b /uv /usr/local/bin/uv

# Override the workspace's managed-Python and local-cache development settings.
# Compiling dependencies once reduces startup work on the read-only runtime.
ENV UV_PYTHON_DOWNLOADS=never \
    UV_NO_MANAGED_PYTHON=1 \
    UV_PYTHON=/usr/bin/python3.14 \
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
RUN mkdir -p /opt/cache-dir

FROM dhi.io/python:3.14.8-alpine3.24@sha256:8cf4b504e7329eedec49f8aed49db76f52b65325c79f40467261ba8f4e1c897d AS runtime

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
# Compose allows one CPU and 64 processes: size Python's default thread pool and the
# in-memory task store's Tokio runtime to one CPU, not to the host's core count. Skip the
# startup banner and its PyPI update check. By default the company directory cache lives on
# the writable /tmp tmpfs and restarts download it again; Compose mounts a named volume at
# /var/cache/opendart-mcp and points the cache there so it survives restarts.
ENV PYTHON_CPU_COUNT=1 \
    TOKIO_WORKER_THREADS=1 \
    FASTMCP_SHOW_SERVER_BANNER=false \
    FASTMCP_CHECK_FOR_UPDATES=off \
    OPENDART_MCP_DIRECTORY__CACHE_DIR=/tmp/opendart-mcp
WORKDIR /app

# Root ownership prevents the service account from modifying installed code. The empty,
# service-owned cache directory gives a new named volume mounted there that ownership.
COPY --from=builder --chown=0:0 /opt/venv /opt/venv
COPY --from=builder --chown=10001:10001 /opt/cache-dir /var/cache/opendart-mcp

# Numeric IDs work without user-management commands in the shell-free runtime.
USER 10001:10001
EXPOSE 8000
# Check listener readiness; CI also verifies MCP discovery and a real tool call.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import socket; from opendart_mcp.settings import get_settings; socket.create_connection(('127.0.0.1', get_settings().http.port), timeout=2).close()"]
CMD ["opendart-mcp"]
