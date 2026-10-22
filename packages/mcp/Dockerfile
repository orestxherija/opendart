# syntax=docker/dockerfile:1.28.0@sha256:bb22d9815c728170f72750f4e5b0d672e06176142e1d602c7e66c050100b7e5b

# Use matching DHI Python and Alpine versions for the copied virtual environment.
# Authenticate with `docker login dhi.io` before building.
FROM dhi.io/python:3.14.8-alpine3.24-dev@sha256:df552b9c5634f917614a73c7687a6aebfff432f8ea7a6db754e953e618dc51c1 AS builder
HEALTHCHECK NONE

COPY --from=ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff /uv /usr/local/bin/uv

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
WORKDIR /app

# Root ownership prevents the service account from modifying installed code.
COPY --from=builder --chown=0:0 /opt/venv /opt/venv

# Numeric IDs work without user-management commands in the shell-free runtime.
USER 10001:10001
EXPOSE 8000
# Check listener readiness; CI also verifies MCP discovery and a real tool call.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import socket; from opendart_mcp.settings import get_settings; socket.create_connection(('127.0.0.1', get_settings().http.port), timeout=2).close()"]
CMD ["opendart-mcp"]
