FROM python:3.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.20 /uv /usr/local/bin/uv

ENV UV_PYTHON_DOWNLOADS=0 UV_LINK_MODE=copy
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY packages/sdk/ packages/sdk/
COPY packages/mcp/ packages/mcp/
RUN uv sync --locked --package opendart-mcp --no-dev --no-editable

FROM python:3.14-slim

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home app
COPY --from=builder /app/.venv /app/.venv

USER app
CMD ["opendart-mcp"]
