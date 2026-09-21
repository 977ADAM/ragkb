.DEFAULT_GOAL := help
SHELL := /bin/bash

.PHONY: help sync sync-frontend migrate api api-reload backend frontend test check up down logs deploy

help:
	@echo "sync            uv sync (backend, migrations + dev)"
	@echo "sync-frontend   bun install (frontend)"
	@echo "migrate         alembic upgrade head"
	@echo "api             uvicorn ragkb.main:app из корня (data/ рядом)"
	@echo "api-reload      то же с авто-перезагрузкой на правках кода"
	@echo "frontend        bun run dev, BFF → 127.0.0.1:8000"
	@echo "test            pytest (backend); временная SQLite"
	@echo "check           svelte-check (frontend)"
	@echo "up              docker compose up postgres migrate rag frontend"
	@echo "down            docker compose down"
	@echo "logs            docker compose logs -f postgres migrate rag frontend"
	@echo "deploy          ./deploy.sh (LAN rsync; .env на сервере не трогает)"

sync:
	cd backend && uv sync --extra migrations --extra dev

sync-frontend:
	cd frontend && bun install

migrate:
	cd backend && uv run alembic upgrade head

backend: api

api:
	uv run --project backend uvicorn ragkb.main:app --app-dir backend --host 127.0.0.1 --port 8000

# То же с перезагрузкой: правки в backend/ragkb применяются без перезапуска.
api-reload:
	uv run --project backend uvicorn ragkb.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000

frontend:
	cd frontend && bun run dev

test:
	cd backend && uv run pytest

check:
	cd frontend && bun run check

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

deploy:
	./deploy.sh
