FROM python:3.11-slim

# uv из официального образа: версия зафиксирована, чтобы сборка была
# воспроизводимой и понимала формат uv.lock (revision 3).
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl \
    && rm -rf /var/lib/apt/lists/*

# Окружение проекта лежит в /app/.venv и добавлено в PATH — CMD и HEALTHCHECK
# вызывают ragkb напрямую, без обёртки `uv run`.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

# Зависимости ставятся отдельным слоем, до копирования исходников: правка кода
# не инвалидирует кэш установки пакетов. --locked запрещает молча обновлять
# uv.lock — версии в образе ровно те же, что и локально.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project

COPY ragkb ./ragkb
COPY config.yaml ./

# Сам пакет ставится не в editable-режиме: в образе он всё равно неизменяем.
RUN uv sync --locked --no-editable

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["ragkb", "serve", "--host", "0.0.0.0", "--port", "8000"]
