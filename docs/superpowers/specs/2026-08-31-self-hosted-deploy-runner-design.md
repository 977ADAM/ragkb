# Self-hosted runner для выкладки

| | |
|---|---|
| Дата | 2026-08-31 |
| Версия | 1 |
| Статус | в работе |
| Автор | Cursor Grok 4.6 |

## Зачем

GitHub-hosted `ubuntu-latest` не видит корпоративную сеть, SSH до
`10.10.1.114` обрывается по таймауту. Выкладка должна идти из Actions, но
исполняться на сервере в LAN.

## Границы

**В работе:** `runs-on` и шаги `.github/workflows/deploy.yml`; runner живёт
на хосте выкладки.

**Вне работы:** открытие SSH в интернет, отдельный jump host, смена
`deploy.sh` для ручной выкладки с ноутбука.

## Решение

Runner ставится на сервер `/opt/ragkb` (пользователь с Docker, например
`adminai`), labels: `self-hosted`, `linux`, `ragkb`.

Job не использует `appleboy/ssh-action` и не вызывает `deploy.sh` (rsync
«сам на себя»). На сервере:

```
cd /opt/ragkb
git pull origin main
docker compose up -d --build migrate rag frontend
```

Триггеры без изменений: тег `v*` и `workflow_dispatch`.

Секреты `HOST` / `USERNAME` / `KEY` этому job не нужны. Пока runner офлайн,
job в очереди не стартует.
