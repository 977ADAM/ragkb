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
# Без extra local-models: эмбеддинги считает Ollama вне образа, поэтому
# torch и sentence-transformers здесь не нужны (это ~1.5 ГБ).
RUN uv sync --locked --extra migrations --no-install-project

COPY ragkb ./ragkb
COPY migrations ./migrations
COPY alembic.ini ./

RUN uv sync --locked --extra migrations --no-editable

# Адрес Ollama: в compose это хост-машина через host.docker.internal.
# RAGKB_EMBEDDING_URL в .env перекрывает значение ниже.
ENV RAGKB_EMBEDDING_BACKEND=ollama \
    RAGKB_EMBEDDING_MODEL=qwen3-embedding:0.6b \
    RAGKB_EMBEDDING_URL=http://host.docker.internal:11434 \
    RAGKB_LLM_BACKEND=openai \
    RAGKB_LOG_DIR=/app/data/logs

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "ragkb.main:app", "--host", "0.0.0.0", "--port", "8000"]
