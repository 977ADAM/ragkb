.DEFAULT_GOAL := help
SHELL := /bin/bash

.PHONY: help sync sync-frontend migrate backend frontend test check up down logs deploy

help:
	@echo "sync            uv sync (backend, migrations + dev)"
	@echo "sync-frontend   bun install (frontend)"
	@echo "migrate         alembic upgrade head"
	@echo "backend         uvicorn :8000, RAGKB_AUTH_MODE=disabled"
	@echo "frontend        bun run dev, BFF → 127.0.0.1:8000"
	@echo "test            pytest (backend)"
	@echo "check           svelte-check (frontend)"
	@echo "up              docker compose up migrate rag frontend"
	@echo "down            docker compose down"
	@echo "logs            docker compose logs -f migrate rag frontend"
	@echo "deploy          ./deploy.sh (LAN rsync; .env на сервере не трогает)"

sync:
	cd backend && uv sync --extra migrations --extra dev

sync-frontend:
	cd frontend && bun install

migrate:
	cd backend && uv run alembic upgrade head

backend:
	cd backend && RAGKB_AUTH_MODE=disabled uv run uvicorn ragkb.platform.app:build --factory --host 127.0.0.1 --port 8000

frontend:
	cd frontend && RAGKB_BACKEND_URL=http://127.0.0.1:8000 RAGKB_DEV_USER=dev bun run dev

test:
	cd backend && uv run pytest

check:
	cd frontend && bun run check

up:
	docker compose up -d --build migrate rag frontend

down:
	docker compose down

logs:
	docker compose logs -f migrate rag frontend

deploy:
	./deploy.sh
