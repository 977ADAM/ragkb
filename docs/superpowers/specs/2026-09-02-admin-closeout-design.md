# Закрытие админки: доки, статусы спек, локальная проверка

| | |
|---|---|
| Дата | 2026-09-02 |
| Версия | 1 |
| Статус | в работе |
| Автор | Cursor Grok 4.6 |

## Зачем

Роли, сидер, HTTP `/admin/*` и UI уже на `main` (спека
`2026-09-02-admin-users`). Живые доки и статусы спек отстали: README всё ещё
пишет группу `ragkb-admins` для rebuild и `disabled` для `make backend`.
Этот заход закрывает админку как «сделано», без новых фич.

## Границы

**В работе:** статус `2026-09-02-admin-users-design.md` и
`2026-09-01-local-auth-design.md` → готово; правки живых доков `README.md` и
`AGENTS.md`; чеклист оператора для `ADMIN_LOGIN` / `ADMIN_PASSWORD`; sqlite-тесты
админки; локальный проход UI. Код приложения — только если проход UI покажет
баг в уже слитом поведении.

**Вне работы:** деплой на сервер; выгрузки и графики; удаление или создание
пользователя админом в UI; закрытие публичного `/auth/signup` и `/register`;
починка `bun run check`; перепись `docs/superpowers/plans/`; спека identity
`2026-08-19`; `frontend/README.md` про `RAGKB_DEV_GROUPS` в режиме `proxy`;
полный `pytest` с Postgres как блокер (если URL нет — не стоим).

## Документы

`README.md`:

- Таблица HTTP: `POST /index/rebuild` в `session` — роль `admin`; в `proxy` —
  членство в `auth.admin_group` (по умолчанию `ragkb-admins`). Не писать, что
  session-пользователь должен быть в группе.
- Быстрый старт / боевая конфигурация: `make backend` совпадает с Makefile —
  `RAGKB_AUTH_MODE=session`, SQLite `data/ragkb.sqlite3`, не `disabled`.
- Чеклист оператора (сервер, не из этого захода): оба `ADMIN_*` в `.env`;
  `docker compose up` прогоняет сервис `ensure-admin` после `migrate`; оба
  пустые — сидер выходит 0, админа нет; после подъёма — вход админом, `/admin`.

`AGENTS.md`: тот же смысл `make backend` (session + SQLite), без противоречия
README.

Спека `2026-09-02-admin-users-design.md`: статус готово.

Спека `2026-09-01-local-auth-design.md`: статус готово; одна фраза, что роль
админа и кнопка переиндексации в session закрыты спекой
`2026-09-02-admin-users`. Текст «вне работы» той спеки не переписывать целиком.

Исторические планы не трогать.

## Проверка

Sqlite (без Postgres): `backend/tests/test_architecture.py`,
`test_admin_credentials.py`, `test_ensure_admin.py`, `test_admin_http.py`,
`test_guard.py`.

UI локально: `make backend` и фронт; админ через
`ADMIN_LOGIN` / `ADMIN_PASSWORD` и `uv run python -m scripts.ensure_admin` из
`backend/` при том же SQLite URL; вход; `/admin`, `/admin/users` (смена роли),
`/admin/reports` (заглушка); ссылка «Админ» в шапке; переиндексация с экрана
админа или чата.

Если `RAGKB_TEST_DATABASE_URL` задан — полный `pytest` желателен, не блокер.

## Согласованность

Не добавляет ручек. Не закрывает signup. Не требует выката. Не меняет контракт
`ensure-admin` и `/admin/*`.
