FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl \
      libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
# local-models: sentence-transformers + torch CPU (см. tool.uv.sources в pyproject).
RUN uv sync --locked --extra migrations --extra local-models --no-install-project

COPY ragkb ./ragkb
COPY migrations ./migrations
COPY alembic.ini ./
COPY config.yaml ./
COPY scripts ./scripts

RUN uv sync --locked --extra migrations --extra local-models --no-editable

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "ragkb.platform.app:build", "--factory", "--host", "0.0.0.0", "--port", "8000"]
