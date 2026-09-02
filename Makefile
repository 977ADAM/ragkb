.DEFAULT_GOAL := help
SHELL := /bin/bash

.PHONY: help sync sync-frontend migrate backend frontend test check up down logs deploy

help:
	@echo "sync            uv sync (backend, migrations + dev)"
	@echo "sync-frontend   bun install (frontend)"
	@echo "migrate         alembic upgrade head"
	@echo "backend         uvicorn :8000, session + SQLite data/ragkb.sqlite3"
	@echo "frontend        bun run dev, BFF → 127.0.0.1:8000"
	@echo "test            pytest (backend); нужна RAGKB_TEST_DATABASE_URL"
	@echo "check           svelte-check (frontend)"
	@echo "up              docker compose up postgres migrate ensure-admin rag frontend"
	@echo "down            docker compose down"
	@echo "logs            docker compose logs -f postgres migrate ensure-admin rag frontend"
	@echo "deploy          ./deploy.sh (LAN rsync; .env на сервере не трогает)"

sync:
	cd backend && uv sync --extra migrations --extra dev

sync-frontend:
	cd frontend && bun install

migrate:
	cd backend && uv run alembic upgrade head

backend:
	@set -a; [ -f .env ] && . ./.env; set +a; \
	export RAGKB_DATABASE_URL="sqlite+aiosqlite:///$(abspath data/ragkb.sqlite3)"; \
	export RAGKB_AUTH_MODE="$${RAGKB_AUTH_MODE:-session}"; \
	mkdir -p data; \
	cd backend && uv run alembic upgrade head && \
	uv run uvicorn ragkb.platform.app:build --factory --host 127.0.0.1 --port 8000

frontend:
	cd frontend && bun run dev

test:
	cd backend && uv run pytest

check:
	cd frontend && bun run check

up:
	docker compose up -d --build postgres migrate ensure-admin rag frontend

down:
	docker compose down

logs:
	docker compose logs -f postgres migrate ensure-admin rag frontend

deploy:
	./deploy.sh
