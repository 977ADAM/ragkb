# Корневой Makefile

| | |
|---|---|
| Дата | 2026-08-31 |
| Версия | 1 |
| Статус | в работе |
| Автор | Cursor Grok 4.6 |

## Зачем

Один вход к командам из `AGENTS.md`, compose и ручного `deploy.sh`.

## Решение

Корневой GNU Make, `.DEFAULT_GOAL := help`, только `.PHONY`. Без рекурсивных
Makefile и без цели, которая одновременно держит uvicorn и Vite.

Цели: `sync`, `sync-frontend`, `migrate`, `backend`, `frontend`, `test`,
`check`, `up`, `down`, `logs`, `deploy`. `deploy` вызывает `./deploy.sh`
(LAN), не GitHub Actions.
