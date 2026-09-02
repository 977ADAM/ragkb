# Админка: роли, сидер из Docker, UI без аналитики

| | |
|---|---|
| Дата | 2026-09-02 |
| Версия | 2 |
| Статус | в работе |
| Автор | Cursor Grok 4.6 |

## Зачем

Публичная регистрация остаётся. Нужны админы в режиме `session` (сейчас у
локального пользователя нет групп, `require_admin` всегда 403), ручки
управления людьми и страница-хаб организации. Аналитика и отчёты — не в
этом заходе: только заглушка.

## Границы

**В работе:** колонка `users.role`; сидер админа из `ADMIN_LOGIN` /
`ADMIN_PASSWORD` сервисом compose после migrate; `get_admin_credentials` в
`backend/ragkb/core/security.py`; `backend/scripts/ensure_admin.py`;
`require_admin` по роли в `session`; HTTP `/admin/users`,
`/admin/organization`, `/admin/reports`; BFF; страницы `/admin`,
`/admin/users`, `/admin/reports`; пункт «Админ» в шапке; тесты; `.env.example`
и compose; `GET /auth/me` отдаёт `role`; bootstrap `reindex` по роли admin.

**Вне работы:** закрытие публичного `/auth/signup`; создание пользователя
админом от чужого имени; смена пароля пользователя админом; email; SSO;
хранение организации в Postgres (по-прежнему конфиг `RAGKB_ORG_*`); выгрузки
и графики; JWT; отдельный CLI кроме модуля сидера.

## Роль

`users.role`: TEXT NOT NULL, значения только `user` и `admin`.
Миграция `0006_user_role`: колонка + default `user` для уже существующих строк.
`POST /auth/signup` всегда создаёт `role=user`.

`User` в `platform/auth.py`: поле `role: str = "user"`. В `session` роль из
строки БД. В `proxy` — как сейчас группы; админ если `in_group(admin_group)`
**или** (не используется роль из БД). В `disabled` — `require_admin`
пропускает, как сейчас.

`require_admin` в `session`: `user.role == "admin"`, иначе 403.

Нельзя `DELETE` самого себя. Нельзя `DELETE` или `PATCH` на `user` последнего
админа в таблице.

## Сидер (этап compose, не image build)

Образ при `docker build` к БД не подключается. Сидер — одноразовый сервис
`ensure-admin` (`restart: "no"`, тот же `image: ragkb:local`,
`command: python -m scripts.ensure_admin`). Цепочка только через
`condition: service_completed_successfully` (как `rag` сейчас ждёт
`migrate`):

```yaml
  migrate:
    depends_on:
      postgres:
        condition: service_healthy
    command: alembic upgrade head
    restart: "no"

  ensure-admin:
    image: ragkb:local
    depends_on:
      migrate:
        condition: service_completed_successfully
    environment:
      RAGKB_DATABASE_URL: postgresql+asyncpg://...
      ADMIN_LOGIN: ${ADMIN_LOGIN:-}
      ADMIN_PASSWORD: ${ADMIN_PASSWORD:-}
    command: python -m scripts.ensure_admin
    restart: "no"

  rag:
    depends_on:
      ensure-admin:
        condition: service_completed_successfully
```

`docker compose up` / `make up` / `deploy.sh` / Actions включают сервис
`ensure-admin` в список (иначе `rag` не дождётся сидера). Не `service_started`
и не `service_healthy` для migrate/ensure-admin: оба процесса завершаются.

`get_admin_credentials()`: читает `ADMIN_LOGIN` и `ADMIN_PASSWORD` из
окружения. Оба пустые или один пустой — вернуть `None` (сидер выходит 0, в
логе warning). Логин нормализовать как signup (lower, `[a-z0-9._-]`, 3–32).
Пароль 8–128.

`ensure_admin()`:

1. Нет credentials — выход.
2. Нет пользователя с этим логином — создать `role=admin`, лог
   `Admin created by system at {utc}` (`datetime.now(timezone.utc)`).
3. Есть — `verify_password` против env: совпало — ничего; иначе обновить
   `password_hash`.

`make backend` (SQLite) сервис compose не вызывает. Админ локально: вручную
`ADMIN_LOGIN=… ADMIN_PASSWORD=… uv run python -m scripts.ensure_admin` из
`backend/` при том же `RAGKB_DATABASE_URL`, либо завести через signup и
поменять роль в БД (для отладки UI — сидер предпочтителен).

Dockerfile копирует `scripts/`.

## HTTP

Все `/admin/*` — сессия обязательна, затем `require_admin`. Ошибка:
`{"detail": "…"}`.

| Метод | Путь | Тело / ответ |
|---|---|---|
| `GET` | `/admin/users` | `{ "users": [ { "username", "role", "created_at" } ] }` |
| `PATCH` | `/admin/users/{username}` | `{ "role": "admin" \| "user" }` → тот же объект пользователя |
| `DELETE` | `/admin/users/{username}` | 204, каскад сессий как FK |
| `GET` | `/admin/organization` | `{ "name", "id", "description" }` из текущего конфига организации; `links`: `{ "users": "/admin/users", "reports": "/admin/reports" }` |
| `GET` | `/admin/reports` | `{ "status": "unavailable" }` |

`GET /auth/me` → `{ "username", "role" }` (`disabled` — `anonymous` / `user`).

`POST /index/rebuild` без смены пути: в `session` пускает `role=admin`.

BFF: `frontend/src/routes/api/admin/` проксирует cookie.

## UI

Хуки: `/admin`, `/admin/users`, `/admin/reports` только при сессии и
`role=admin`, иначе редирект на `/` или `/login`.

`/admin` — хаб: название организации, ссылки «Пользователи» и «Отчёты».
`/admin/users` — таблица, смена роли (выдать/снять админа). Удаление в UI
этого захода не обязательно, если есть API; в интерфейсе достаточно роли.
`/admin/reports` — текст, что отчёты появятся позже.

Шапка: ссылка «Админ» при `role=admin`.

## Тесты

- `0006` накатывается; signup даёт `user`.
- `ensure_admin`: создание + лог; повтор с тем же паролем без UPDATE;
  другой пароль — хеш меняется.
- HTTP: не-админ 403; админ список; нельзя снять/удалить последнего админа;
  `GET /admin/reports` 200 с `unavailable`.
- `GET /auth/me` содержит `role`.

## Согласованность

Не противоречит публичному signup. Не переносит org в БД. Не добавляет
метрики. Сидер не в `lifespan` API и не в `Dockerfile RUN`. Ожидание сидера
только `service_completed_successfully`.
